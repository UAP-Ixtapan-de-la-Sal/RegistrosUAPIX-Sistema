"""Ejecutar con --settings=config.settings_test; solo usa BD de pruebas."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from openpyxl import Workbook
from zipfile import ZIP_DEFLATED, ZipFile

from .models import Carrera, Equipo, Grupo, Materia, Persona, UsuarioSistema
from .services import importacion_temporal
from .services.importacion_excel import (
    COLUMNAS, ExcelError, IMPORT_PERMISSIONS, MAX_FILE_SIZE, confirm, preview,
)


def workbook(sheets):
    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def all_sheets():
    return {
        'Carreras': [COLUMNAS['Carreras'], ['Informática']],
        'Grupos': [COLUMNAS['Grupos'], ['X1', 'Informática', 2, 'Matutino']],
        'Alumnos': [COLUMNAS['Alumnos'], ['00123', 'Ana', 'Pérez', 'López', 'X1']],
        'Docentes': [COLUMNAS['Docentes'], ['D001', 'Luis', 'Díaz', '']],
        'Administrativos': [COLUMNAS['Administrativos'], ['A001', 'Eva', 'Ruiz', '']],
        'Materias': [COLUMNAS['Materias'], ['Programación', 'Informática', 2]],
        'Equipos': [COLUMNAS['Equipos'], ['01', '00050', 'Sala de Cómputo']],
    }


class ExcelServiceTests(TestCase):
    def setUp(self):
        self.user = UsuarioSistema.objects.create_superuser(username='importador', password='prueba')

    def test_seven_sheets_preview_does_not_write_and_confirmation_links_everything(self):
        data = workbook(all_sheets())
        with CaptureQueriesContext(connection) as queries:
            plan = preview(data)
        self.assertTrue(plan.valid, plan)
        self.assertFalse(any(q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for q in queries))
        self.assertFalse(Carrera.objects.exists())
        self.assertFalse(Equipo.history.exists())
        confirm(data, self.user)
        self.assertEqual([m.objects.count() for m in (Carrera, Grupo, Persona, Materia, Equipo)], [1, 1, 3, 1, 1])
        student = Persona.objects.get(matricula='00123')
        self.assertEqual(student.carrera, student.grupo.carrera)
        self.assertEqual(student.apellidos, 'Pérez López')
        self.assertEqual(Materia.objects.get().semestre, 2)
        self.assertEqual(Equipo.objects.get().no_bien_patrimonial, '00050')
        self.assertEqual(UsuarioSistema.objects.count(), 1)

    def test_one_sheet_ignores_missing_sheets(self):
        data = workbook({'Carreras': [['Carrera'], ['Informática']]})
        plan = confirm(data, self.user)
        self.assertEqual(len(plan.sheets), 1)
        self.assertEqual(Carrera.objects.get().nombre_carrera, 'Informática')

    def test_empty_sheets_and_headers_only_are_ignored_before_header_validation(self):
        data = workbook({
            'Carreras': [['Carrera'], ['Informática']], 'Grupos': [],
            'Alumnos': [['solo encabezado']], 'Materias': [[None], ['  ']],
        })
        plan = confirm(data, self.user)
        self.assertEqual(plan.ignored, ['Grupos', 'Alumnos', 'Materias'])
        self.assertEqual(Carrera.objects.count(), 1)

    def test_entirely_empty_workbook_is_not_confirmable(self):
        plan = preview(workbook({'Carreras': [['Carrera']]}))
        self.assertFalse(plan.valid)
        self.assertTrue(plan.errors)

    def test_existing_records_and_reimport_are_preserved_without_history_changes(self):
        obj = Equipo.objects.create(no_equipo='01', no_bien_patrimonial='00050', lugar='Sala', estado='Ocupado')
        count = obj.history.count()
        data = workbook({'Equipos': [COLUMNAS['Equipos'], ['01', '00050', 'Sala de Cómputo']]})
        for _ in range(2):
            plan = confirm(data, self.user)
            self.assertEqual(plan.sheets[0].existing, 1)
        obj.refresh_from_db()
        self.assertEqual(obj.estado, 'Ocupado')
        self.assertEqual(obj.history.count(), count)
        self.assertEqual(Equipo.objects.count(), 1)

    def test_identical_rows_in_excel_do_not_duplicate_records(self):
        plan = confirm(workbook({'Carreras': [['Carrera'], [' Informática '], ['informática']]}), self.user)
        self.assertEqual(Carrera.objects.count(), 1)
        self.assertEqual(plan.sheets[0].new, 1)
        self.assertEqual(plan.sheets[0].existing, 1)
        self.assertEqual(Carrera.objects.get().nombre_carrera, 'Informática')

    def test_existing_case_and_whitespace_match_without_changing_stored_text(self):
        Carrera.objects.create(nombre_carrera='  Ingeniería   en Computación ')
        data = workbook({'Carreras': [[' CARRÉRA '], ['ingeniería en computación']]})
        self.assertEqual(confirm(data, self.user).sheets[0].existing, 1)
        self.assertEqual(Carrera.objects.get().nombre_carrera, '  Ingeniería   en Computación ')

    def test_conflicting_existing_record_blocks_confirmation(self):
        Persona.objects.create(matricula='D01', nombre='Luis', apellidos='Pérez', perfil='Docente')
        data = workbook({'Docentes': [COLUMNAS['Docentes'], ['d01', 'Otro', 'Pérez', '']]})
        plan = preview(data)
        self.assertFalse(plan.valid)
        self.assertEqual(plan.sheets[0].errors[0]['row'], 2)
        with self.assertRaises(ExcelError):
            confirm(data, self.user)
        self.assertEqual(Persona.objects.get().nombre, 'Luis')

    def test_contradictory_rows_and_cross_sheet_profiles_block(self):
        for sheets in (
            {'Docentes': [COLUMNAS['Docentes'], ['D01', 'Luis', 'Pérez', ''], ['D01', 'Otro', 'Pérez', '']]},
            {'Docentes': [COLUMNAS['Docentes'], ['D01', 'Luis', 'Pérez', '']],
             'Administrativos': [COLUMNAS['Administrativos'], ['D01', 'Luis', 'Pérez', '']]},
        ):
            with self.subTest(sheets=sheets):
                self.assertFalse(preview(workbook(sheets)).valid)
                with self.assertRaises(ExcelError):
                    confirm(workbook(sheets), self.user)
        self.assertFalse(Persona.objects.exists())

    def test_nonunique_name_is_never_resolved_arbitrarily(self):
        Carrera.objects.create(nombre_carrera='Informática')
        Carrera.objects.create(nombre_carrera='INFORMÁTICA')
        data = workbook({'Carreras': [['Carrera'], ['Informática']]})
        self.assertFalse(preview(data).valid)
        self.assertEqual(Carrera.objects.count(), 2)

    def test_relations_can_be_resolved_from_database_when_catalog_sheet_is_absent(self):
        career = Carrera.objects.create(nombre_carrera='Informática')
        data = workbook({'Grupos': [COLUMNAS['Grupos'], ['X1', ' informática ', '2', 'Matutino']]})
        confirm(data, self.user)
        self.assertEqual(Grupo.objects.get().carrera, career)

    def test_student_only_file_resolves_existing_group(self):
        career = Carrera.objects.create(nombre_carrera='Informática')
        group = Grupo.objects.create(nombre_grupo='X1', semestre=2, turno='Matutino', carrera=career)
        data = workbook({'Alumnos': [COLUMNAS['Alumnos'], ['0001', 'Ana', 'Pérez', '', ' x1 ']]})
        confirm(data, self.user)
        self.assertEqual(Persona.objects.get().grupo, group)

    def test_missing_reference_is_row_field_error_and_does_not_create_fake_catalog(self):
        data = workbook({'Grupos': [COLUMNAS['Grupos'], ['X1', 'No existe', 2, 'Matutino']]})
        plan = preview(data)
        self.assertFalse(plan.valid)
        self.assertEqual(plan.sheets[0].errors[0]['field'], 'Carrera')
        self.assertFalse(Carrera.objects.exists())

    def test_required_fields_types_and_model_lengths_are_validated(self):
        career = Carrera.objects.create(nombre_carrera='Informática')
        for row in (['X1', career.nombre_carrera, 0, 'Matutino'], ['X1', career.nombre_carrera, 'dos', 'Matutino'], ['X1', career.nombre_carrera, 2, '']):
            with self.subTest(row=row):
                self.assertFalse(preview(workbook({'Grupos': [COLUMNAS['Grupos'], row]})).valid)
        self.assertFalse(preview(workbook({'Carreras': [['Carrera'], ['A' * 101]]})).valid)
        self.assertFalse(preview(workbook({'Docentes': [COLUMNAS['Docentes'], ['', 'Ana', 'Pérez', '']]})).valid)

    def test_missing_and_duplicate_headers_block(self):
        for rows in ([['Otro'], ['Informática']], [['Carrera', ' CARRÉRA '], ['Informática', 'Informática']]):
            self.assertFalse(preview(workbook({'Carreras': rows})).valid)

    def test_duplicate_sheet_names_and_unknown_nonempty_sheets_block(self):
        data = workbook({'Carreras': [['Carrera'], ['A']], ' Carreras ': [['Carrera'], ['B']]})
        self.assertFalse(preview(data).valid)
        self.assertFalse(preview(workbook({'Carreraas': [['Carrera'], ['A']]})).valid)

    def test_unicode_headers_empty_values_and_numeric_identifiers(self):
        data = workbook({' Equipos ': [['NO. EQUIPO ', 'No. Bien Patrimonial', 'Lúgar'], [1.0, '00050', 'Biblioteca Digital']]})
        confirm(data, self.user)
        equipment = Equipo.objects.get()
        self.assertEqual(equipment.no_equipo, '1')
        self.assertEqual(equipment.no_bien_patrimonial, '00050')
        self.assertEqual(equipment.lugar, 'Biblioteca')

    def test_invalid_and_oversized_file_are_rejected(self):
        for data in (b'no soy excel', b'', b'x' * (MAX_FILE_SIZE + 1)):
            with self.assertRaises(ExcelError):
                preview(data)

    def test_row_column_and_expansion_limits_reject_without_truncating(self):
        data = workbook({'Carreras': [['Carrera'], ['Informática'], ['Otra']]})
        with patch('inicio.services.importacion_excel.MAX_ROWS', 1):
            with self.assertRaisesMessage(ExcelError, 'máximo 1 filas'):
                preview(data)
        with patch('inicio.services.importacion_excel.MAX_COLUMNS', 1):
            with self.assertRaisesMessage(ExcelError, 'máximo 1 columnas'):
                preview(workbook({'Carreras': [['Carrera', 'Extra'], ['A', 'B']]}))
        with patch('inicio.services.importacion_excel.MAX_EXPANDED_SIZE', 10):
            with self.assertRaisesMessage(ExcelError, 'descomprimido'):
                preview(data)

    def test_malformed_excel_xml_is_a_validation_error(self):
        original = workbook({'Carreras': [['Carrera'], ['Informática']]})
        buffer = BytesIO()
        with ZipFile(BytesIO(original)) as source, ZipFile(buffer, 'w', ZIP_DEFLATED) as target:
            for member in source.infolist():
                content = b'<worksheet><roto' if member.filename == 'xl/worksheets/sheet1.xml' else source.read(member)
                target.writestr(member, content)
        with self.assertRaises(ExcelError):
            preview(buffer.getvalue())

    def test_save_error_rolls_back_records_and_history(self):
        data = workbook({'Carreras': [['Carrera'], ['Informática']], 'Equipos': [COLUMNAS['Equipos'], ['01', '00050', 'Sala']]})
        original_save = Equipo.save

        def fail_after_save(obj, *args, **kwargs):
            original_save(obj, *args, **kwargs)
            raise IntegrityError('Fallo simulado')

        with patch.object(Equipo, 'save', fail_after_save):
            with self.assertRaises(IntegrityError):
                confirm(data, self.user)
        self.assertFalse(Carrera.objects.exists())
        self.assertFalse(Equipo.objects.exists())
        self.assertFalse(Equipo.history.exists())

    def test_history_keeps_responsible_administrator_and_previous_history(self):
        old = Equipo.objects.create(no_equipo='viejo', no_bien_patrimonial='OLD', lugar='Sala')
        history_id = old.history.get().history_id
        confirm(workbook({'Equipos': [COLUMNAS['Equipos'], ['01', '00050', 'Sala']]}), self.user)
        record = Equipo.objects.get(no_bien_patrimonial='00050').history.get()
        self.assertEqual(record.history_user, self.user)
        self.assertIn('Importación Excel', record.history_change_reason)
        self.assertTrue(old.history.filter(history_id=history_id).exists())

    def test_database_changes_after_preview_are_revalidated(self):
        data = workbook({'Docentes': [COLUMNAS['Docentes'], ['D01', 'Luis', 'Pérez', '']]})
        self.assertTrue(preview(data).valid)
        Persona.objects.create(matricula='D01', nombre='Otro', apellidos='Pérez', perfil='Docente')
        with self.assertRaises(ExcelError):
            confirm(data, self.user)
        self.assertEqual(Persona.objects.get().nombre, 'Otro')

    def test_seven_sheet_reimport_does_not_duplicate_or_overwrite(self):
        data = workbook(all_sheets())
        confirm(data, self.user)
        plan = confirm(data, self.user)
        self.assertEqual(sum(s.new for s in plan.sheets), 0)
        self.assertEqual(sum(s.existing for s in plan.sheets), 7)
        self.assertEqual(Equipo.history.count(), 1)

    def test_subjects_in_different_semesters_follow_reference_identity(self):
        sheets = all_sheets()
        sheets['Materias'].append(['Programación', 'Informática', 3])
        data = workbook(sheets)
        confirm(data, self.user)
        self.assertEqual(set(Materia.objects.values_list('semestre', flat=True)), {2, 3})
        self.assertTrue(preview(data).valid)
        self.assertEqual(confirm(data, self.user).sheets[-2].existing, 2)

    def test_legacy_subject_without_semester_is_not_overwritten_or_duplicated(self):
        career = Carrera.objects.create(nombre_carrera='Informática')
        subject = Materia.objects.create(nombre_materia='Programación', carrera=career)
        data = workbook({'Materias': [COLUMNAS['Materias'], ['Programación', 'Informática', 2]]})
        self.assertFalse(preview(data).valid)
        with self.assertRaises(ExcelError):
            confirm(data, self.user)
        subject.refresh_from_db()
        self.assertIsNone(subject.semestre)
        self.assertEqual(Materia.objects.count(), 1)

    def test_ambiguous_group_code_is_not_resolved_by_guessing(self):
        career = Carrera.objects.create(nombre_carrera='Informática')
        for semester in (1, 2):
            Grupo.objects.create(nombre_grupo='X1', semestre=semester, turno='Matutino', carrera=career)
        data = workbook({'Alumnos': [COLUMNAS['Alumnos'], ['0001', 'Ana', 'Pérez', '', 'X1']]})
        self.assertFalse(preview(data).valid)
        self.assertFalse(Persona.objects.exists())


class IntegratedSchemaTests(TestCase):
    def setUp(self):
        self.career = Carrera.objects.create(nombre_carrera='Informática')

    def test_group_and_subject_metadata_match_optional_reference_schema(self):
        group = Grupo(nombre_grupo='X1', carrera=self.career)
        group.full_clean()
        group.save()
        subject = Materia(nombre_materia='Programación', carrera=self.career)
        subject.full_clean()
        subject.save()
        self.assertIsNone(group.semestre)
        self.assertEqual(group.turno, '')
        self.assertIsNone(subject.semestre)
        self.assertEqual(str(group), 'X1')

    def test_complete_group_keeps_original_display_for_existing_modules(self):
        group = Grupo(nombre_grupo='X1', semestre=2, turno='Matutino', carrera=self.career)
        self.assertEqual(str(group), 'X1 - Semestre 2 (Matutino)')

    def test_person_without_group_still_validates(self):
        person = Persona(matricula='D01', nombre='Luis', apellidos='Pérez', perfil='Docente', carrera=self.career)
        person.full_clean()
        person.save()
        self.assertIsNone(person.grupo_id)

    def test_person_group_must_belong_to_same_career(self):
        other = Carrera.objects.create(nombre_carrera='Contaduría')
        group = Grupo.objects.create(nombre_grupo='X1', carrera=self.career)
        person = Persona(matricula='001', nombre='Ana', apellidos='Pérez', perfil='Alumno', carrera=other, grupo=group)
        with self.assertRaises(ValidationError) as error:
            person.full_clean()
        self.assertIn('grupo', error.exception.message_dict)

    def test_reverse_relation_and_set_null_preserve_person_and_career(self):
        group = Grupo.objects.create(nombre_grupo='X1', carrera=self.career)
        person = Persona.objects.create(matricula='001', nombre='Ana', apellidos='Pérez', perfil='Alumno', carrera=self.career, grupo=group)
        self.assertEqual(list(group.alumnos.all()), [person])
        group.delete()
        person.refresh_from_db()
        self.assertIsNone(person.grupo_id)
        self.assertEqual(person.carrera, self.career)

    def test_database_columns_and_foreign_key_exist_after_migrations(self):
        with connection.cursor() as cursor:
            columns = {column.name: column for column in connection.introspection.get_table_description(cursor, Persona._meta.db_table)}
            constraints = connection.introspection.get_constraints(cursor, Persona._meta.db_table)
            subject_columns = {column.name for column in connection.introspection.get_table_description(cursor, Materia._meta.db_table)}
        self.assertTrue(columns['grupo_id'].null_ok)
        self.assertIn('semestre', subject_columns)
        self.assertTrue(any(c['foreign_key'] == (Grupo._meta.db_table, 'id_grupo') for c in constraints.values()))


class ExcelAdminTests(TestCase):
    def setUp(self):
        self.user = UsuarioSistema.objects.create_superuser(username='adminexcel', password='prueba')
        self.client.force_login(self.user)
        self.url = reverse('importar_excel')
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = self.settings(EXCEL_IMPORT_TEMP_DIR=Path(self.temp.name))
        self.override.enable()
        self.addCleanup(self.override.disable)

    def upload(self, data=None, client=None, filename='datos.xlsx'):
        data = data or workbook({'Carreras': [['Carrera'], ['Informática']]})
        return (client or self.client).post(self.url, {
            'accion': 'validar', 'archivo': SimpleUploadedFile(filename, data),
        })

    def test_global_header_link_and_upload_page_preserve_admin_navigation(self):
        response = self.client.get(reverse('admin:index'))
        self.assertContains(response, self.url)
        self.assertContains(response, 'Importar Excel')
        self.assertContains(response, reverse('admin:inicio_persona_changelist'))
        response = self.client.get(self.url)
        self.assertContains(response, 'Cargar y validar')

    def test_anonymous_nonstaff_and_staff_without_permissions_are_denied(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        for staff in (False, True):
            user = UsuarioSistema.objects.create_user(username=f'staff{staff}', is_staff=staff)
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403 if staff else 302)
            if staff:
                self.assertNotContains(self.client.get(reverse('admin:index')), self.url)

    def test_staff_with_explicit_add_permissions_can_import_without_change_permissions(self):
        user = UsuarioSistema.objects.create_user(username='delegado', is_staff=True)
        user.user_permissions.set(Permission.objects.filter(content_type__app_label='inicio', codename__in=[p.split('.')[1] for p in IMPORT_PERMISSIONS]))
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        response = self.upload()
        response = self.client.post(self.url, {'accion': 'confirmar', 'token': response.context['token']})
        self.assertTrue(response.context['completed'])

    def test_preview_has_no_business_writes_and_confirmation_is_single_use(self):
        response = self.upload()
        self.assertContains(response, 'Confirmar importación')
        self.assertFalse(Carrera.objects.exists())
        token = response.context['token']
        response = self.client.post(self.url, {'accion': 'confirmar', 'token': token})
        self.assertContains(response, 'Importación completada')
        self.assertEqual(Carrera.objects.count(), 1)
        response = self.client.post(self.url, {'accion': 'confirmar', 'token': token})
        self.assertNotContains(response, 'Importación completada')
        self.assertContains(response, 'ya fue confirmada')
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_invalid_preview_does_not_enable_confirmation(self):
        response = self.upload(workbook({'Docentes': [COLUMNAS['Docentes'], ['', 'Ana', 'Pérez', '']]}))
        self.assertNotIn('token', response.context)
        self.assertNotContains(response, '>Confirmar importación</button>')
        self.assertContains(response, 'fila 2')

    def test_invalid_extension_and_invalid_workbook_are_reported(self):
        self.assertContains(self.upload(filename='datos.txt'), 'extensión .xlsx')
        self.assertContains(self.upload(data=b'no es excel'), 'Excel .xlsx válido')

    def test_token_cannot_be_used_by_another_administrator(self):
        response = self.upload()
        token = response.context['token']
        other = UsuarioSistema.objects.create_superuser(username='otro', password='prueba')
        self.client.force_login(other)
        response = self.client.post(self.url, {'accion': 'confirmar', 'token': token})
        self.assertContains(response, 'otro usuario o sesión')
        self.assertFalse(Carrera.objects.exists())

    def test_token_cannot_be_used_in_another_session_of_same_user(self):
        token = self.upload().context['token']
        other_client = Client()
        other_client.force_login(self.user)
        response = other_client.post(self.url, {'accion': 'confirmar', 'token': token})
        self.assertContains(response, 'otro usuario o sesión')

    def test_tampered_expired_and_missing_tokens_do_not_write(self):
        token = self.upload().context['token']
        for invalid in ('', token + 'x'):
            response = self.client.post(self.url, {'accion': 'confirmar', 'token': invalid})
            self.assertContains(response, 'confirmación no es válida')
        with patch('django.core.signing.time.time', return_value=time.time() + 1000):
            response = self.client.post(self.url, {'accion': 'confirmar', 'token': token})
        self.assertContains(response, 'venció')
        self.assertFalse(Carrera.objects.exists())

    def test_changed_temporary_file_is_rejected(self):
        token = self.upload().context['token']
        next(Path(self.temp.name).glob('*.xlsx')).write_bytes(b'alterado')
        response = self.client.post(self.url, {'accion': 'confirmar', 'token': token})
        self.assertContains(response, 'archivo cambió')
        self.assertFalse(Carrera.objects.exists())

    def test_permissions_are_checked_again_at_confirmation(self):
        token = self.upload().context['token']
        self.user.is_superuser = False
        self.user.save()
        self.assertEqual(self.client.post(self.url, {'accion': 'confirmar', 'token': token}).status_code, 403)
        self.assertFalse(Carrera.objects.exists())

    def test_csrf_protection_applies_to_upload_and_confirmation(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, {'accion': 'validar'}).status_code, 403)
        self.assertEqual(client.post(self.url, {'accion': 'confirmar', 'token': 'x'}).status_code, 403)

    def test_failed_confirmation_shows_no_false_success_and_rolls_back(self):
        token = self.upload().context['token']
        with patch.object(Carrera, 'save', side_effect=IntegrityError('Fallo simulado')):
            with self.assertLogs('inicio.views_importacion', level='ERROR'):
                response = self.client.post(self.url, {'accion': 'confirmar', 'token': token})
        self.assertNotContains(response, 'Importación completada')
        self.assertContains(response, 'No se guardaron registros')
        self.assertFalse(Carrera.objects.exists())

    def test_stale_uploads_are_cleaned_up(self):
        token = self.upload().context['token']
        with patch('inicio.services.importacion_temporal.time.time', return_value=time.time() + 1000):
            importacion_temporal.cleanup()
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])
        self.assertTrue(token)
