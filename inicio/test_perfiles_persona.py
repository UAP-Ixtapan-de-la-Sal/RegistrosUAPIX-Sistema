from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .forms import RegistroClaseForm, RegistroEventoForm
from .models import Carrera, Grupo, Persona, PersonaPerfil, UsuarioSistema
from .services.importacion_excel import COLUMNAS, ExcelError, confirm, preview
from .test_importacion_excel import ExcelAdminFixture, workbook


def staff_workbook(name='Ana'):
    return workbook({
        'Docentes': [COLUMNAS['Docentes'], ['0001', name, 'Pérez', '']],
        'Administrativos': [COLUMNAS['Administrativos'], ['0001', name, 'Pérez', '']],
    })


class MultipleProfilesTests(TestCase):
    def setUp(self):
        self.user = UsuarioSistema.objects.create_superuser(username='perfiles', password='prueba')

    def test_one_account_can_be_teacher_and_administrator_and_reimport_is_idempotent(self):
        data = staff_workbook()
        with CaptureQueriesContext(connection) as queries:
            plan = preview(data)
        self.assertTrue(plan.valid)
        self.assertEqual(sum(s.new for s in plan.sheets), 1)
        self.assertEqual(sum(s.profiles for s in plan.sheets), 2)
        self.assertFalse(any(q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for q in queries))
        confirm(data, self.user)
        person = Persona.objects.get(matricula='0001')
        self.assertEqual(person.perfil, 'Docente')
        self.assertEqual(person.perfiles_actuales, {'Docente', 'Administrador'})
        self.assertEqual(Persona.objects.count(), 1)
        self.assertEqual(PersonaPerfil.history.count(), 2)
        for record in PersonaPerfil.history.all():
            self.assertEqual(record.history_user, self.user)
        again = confirm(data, self.user)
        self.assertEqual(sum(s.new + s.profiles for s in again.sheets), 0)
        self.assertEqual(PersonaPerfil.history.count(), 2)
        self.assertEqual(UsuarioSistema.objects.count(), 1)

    def test_new_profile_on_existing_person_preserves_identity_and_primary_profile(self):
        person = Persona.objects.create(matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Administrador')
        data = workbook({'Docentes': [COLUMNAS['Docentes'], ['0001', 'Ana', 'Pérez', '']]})
        before = PersonaPerfil.history.count()
        plan = preview(data)
        self.assertEqual(plan.sheets[0].new, 0)
        self.assertEqual(plan.sheets[0].profiles, 1)
        self.assertEqual(person.perfiles.count(), 1)
        self.assertEqual(PersonaPerfil.history.count(), before)
        confirm(data, self.user)
        person.refresh_from_db()
        self.assertEqual(person.perfil, 'Administrador')
        self.assertEqual(person.perfiles_actuales, {'Administrador', 'Docente'})
        self.assertEqual(Persona.objects.get().pk, person.pk)
        record = person.perfiles.get(perfil='Docente').history.get()
        self.assertEqual(record.history_user, self.user)
        self.assertIn('Importación Excel', record.history_change_reason)

    def test_person_can_hold_all_three_profiles_without_losing_academic_relations(self):
        data = workbook({
            'Carreras': [['Carrera'], ['Informática']],
            'Grupos': [COLUMNAS['Grupos'], ['X1', 'Informática', 2, 'Matutino']],
            'Alumnos': [COLUMNAS['Alumnos'], ['0001', 'Ana', 'Pérez', '', 'X1']],
            'Docentes': [COLUMNAS['Docentes'], ['0001', 'Ana', 'Pérez', '']],
            'Administrativos': [COLUMNAS['Administrativos'], ['0001', 'Ana', 'Pérez', '']],
        })
        confirm(data, self.user)
        person = Persona.objects.get()
        self.assertEqual(person.perfiles_actuales, {'Alumno', 'Docente', 'Administrador'})
        self.assertEqual(person.grupo.carrera, person.carrera)
        self.assertEqual(person.perfil, 'Alumno')
        self.assertEqual(Persona.objects.con_perfiles('Administrador', 'Docente').count(), 1)

    def test_existing_teacher_can_gain_student_profile_and_missing_academic_relations(self):
        career = Carrera.objects.create(nombre_carrera='Informática')
        group = Grupo.objects.create(nombre_grupo='X1', semestre=2, turno='Matutino', carrera=career)
        person = Persona.objects.create(matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Docente')
        data = workbook({'Alumnos': [COLUMNAS['Alumnos'], ['0001', 'Ana', 'Pérez', '', 'X1']]})
        plan = preview(data)
        self.assertEqual(plan.sheets[0].relationships, 1)
        person.refresh_from_db()
        self.assertIsNone(person.grupo_id)
        confirm(data, self.user)
        person.refresh_from_db()
        self.assertEqual(person.grupo, group)
        self.assertEqual(person.carrera, career)
        self.assertEqual(person.perfil, 'Docente')
        self.assertTrue(person.tiene_perfil('Alumno'))

    def test_new_profile_never_overwrites_existing_name_or_academic_relation(self):
        career = Carrera.objects.create(nombre_carrera='Informática')
        other = Carrera.objects.create(nombre_carrera='Contaduría')
        group = Grupo.objects.create(nombre_grupo='X1', semestre=2, turno='Matutino', carrera=career)
        person = Persona.objects.create(matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Docente', carrera=other)
        files = (
            workbook({'Administrativos': [COLUMNAS['Administrativos'], ['0001', 'Otra persona', 'Pérez', '']]}),
            workbook({'Alumnos': [COLUMNAS['Alumnos'], ['0001', 'Ana', 'Pérez', '', group.nombre_grupo]]}),
        )
        for data in files:
            self.assertFalse(preview(data).valid)
            with self.assertRaises(ExcelError):
                confirm(data, self.user)
        person.refresh_from_db()
        self.assertEqual(person.nombre, 'Ana')
        self.assertEqual(person.carrera, other)
        self.assertEqual(person.perfiles_actuales, {'Docente'})

    def test_profile_save_failure_rolls_back_person_profiles_and_history(self):
        original_save = PersonaPerfil.save

        def fail_second_profile(obj, *args, **kwargs):
            original_save(obj, *args, **kwargs)
            if obj.perfil == 'Administrador':
                raise IntegrityError('Fallo simulado al agregar segundo perfil')

        with patch.object(PersonaPerfil, 'save', fail_second_profile):
            with self.assertRaises(IntegrityError):
                confirm(staff_workbook(), self.user)
        self.assertFalse(Persona.objects.exists())
        self.assertFalse(PersonaPerfil.objects.exists())
        self.assertFalse(PersonaPerfil.history.exists())

    def test_editing_person_keeps_additional_profiles_and_does_not_duplicate_primary(self):
        person = Persona.objects.create(matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Docente')
        PersonaPerfil.objects.create(persona=person, perfil='Administrador')
        person.nombre = 'Ana María'
        person.save()
        self.assertEqual(person.perfiles_actuales, {'Docente', 'Administrador'})
        self.assertEqual(person.perfiles.count(), 2)
        self.assertEqual(PersonaPerfil.history.count(), 2)

    def test_database_constraints_prevent_repeated_or_unknown_profiles(self):
        person = Persona.objects.create(matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Docente')
        for perfil in ('Docente', 'Superusuario'):
            with self.assertRaises(IntegrityError), transaction.atomic():
                PersonaPerfil.objects.create(persona=person, perfil=perfil)
        self.assertEqual(person.perfiles.count(), 1)

    def test_legacy_primary_profile_remains_usable_during_compatibility_period(self):
        person = Persona.objects.create(matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Docente')
        person.perfiles.all().delete()
        self.assertTrue(person.tiene_perfil('Docente'))
        self.assertEqual(Persona.objects.con_perfiles('Docente').get(), person)
        person.save()
        self.assertEqual(person.perfiles.count(), 1)


class MultipleProfilesAdminTests(TestCase):
    def setUp(self):
        self.user = UsuarioSistema.objects.create_superuser(username='adminperfiles', password='prueba')
        self.client.force_login(self.user)

    def test_admin_can_create_one_person_with_two_profiles(self):
        response = self.client.post(reverse('admin:inicio_persona_add'), {
            'matricula': '0001', 'nombre': 'Ana', 'apellidos': 'Pérez',
            'perfil': 'Administrador', 'perfiles_institucionales': ['Administrador', 'Docente'],
            'grupo': '', 'carrera': '', '_save': 'Guardar',
        })
        self.assertEqual(response.status_code, 302)
        person = Persona.objects.get()
        self.assertEqual(person.perfiles_actuales, {'Administrador', 'Docente'})
        self.assertEqual(PersonaPerfil.history.count(), 2)
        self.assertTrue(all(h.history_user == self.user for h in PersonaPerfil.history.all()))

    def test_admin_filters_find_additional_profile_and_display_all_profiles(self):
        person = Persona.objects.create(matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Administrador')
        PersonaPerfil.objects.create(persona=person, perfil='Docente')
        response = self.client.get(reverse('admin:inicio_persona_changelist'), {'perfil_institucional': 'Docente'})
        self.assertEqual(response.context['cl'].result_count, 1)
        self.assertContains(response, 'Administrador, Docente')

    def test_admin_can_remove_additional_profile_but_keeps_primary(self):
        person = Persona.objects.create(matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Administrador')
        membership = PersonaPerfil.objects.create(persona=person, perfil='Docente')
        membership_id = membership.pk
        response = self.client.post(reverse('admin:inicio_persona_change', args=[person.pk]), {
            'matricula': '0001', 'nombre': 'Ana', 'apellidos': 'Pérez',
            'perfil': 'Administrador', 'perfiles_institucionales': [],
            'grupo': '', 'carrera': '', '_save': 'Guardar',
        })
        self.assertEqual(response.status_code, 302)
        person.refresh_from_db()
        self.assertEqual(person.perfiles_actuales, {'Administrador'})
        record = PersonaPerfil.history.filter(id=membership_id).latest()
        self.assertEqual(record.history_type, '-')
        self.assertEqual(record.history_user, self.user)

    def test_speaker_lookup_accepts_teacher_as_additional_profile_without_duplicates(self):
        person = Persona.objects.create(matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Alumno')
        PersonaPerfil.objects.create(persona=person, perfil='Docente')
        PersonaPerfil.objects.create(persona=person, perfil='Administrador')
        response = self.client.get(reverse('buscar_ponente_sala'), {'cuenta': '0001'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['persona_id'], person.pk)

    def test_teacher_class_form_accepts_additional_teacher_profile(self):
        career = Carrera.objects.create(nombre_carrera='Informática')
        person = Persona.objects.create(matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Administrador', carrera=career)
        PersonaPerfil.objects.create(persona=person, perfil='Docente')
        day = timezone.localdate() + timedelta(days=1)
        while day.weekday() > 4:
            day += timedelta(days=1)
        form = RegistroClaseForm(data={
            'tipo_actividad': 'regular', 'numero_cuenta_docente': '0001',
            'docente_id': person.pk, 'carrera': career.pk, 'materia': '1', 'grupo': '1',
            'fecha': day.isoformat(), 'fecha_fin_repeticion': day.isoformat(),
            'hora_inicio': '09:00', 'hora_fin': '10:00', 'dias_repeticion': [str(day.weekday())],
        }, catalogos={'carreras': [{'id': career.pk, 'nombre': 'Informática'}], 'materias': [{'id': 1, 'nombre': 'Programación'}], 'grupos': [{'id': 1, 'nombre': 'X1'}]})
        self.assertTrue(form.is_valid(), form.errors)

    def test_speaker_form_accepts_additional_profile(self):
        person = Persona.objects.create(matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Alumno')
        PersonaPerfil.objects.create(persona=person, perfil='Docente')
        form = RegistroEventoForm(data={
            'tipo_evento': 'Taller', 'nombre_evento': 'Prueba', 'pertenece_al_plantel': 'si',
            'numero_cuenta_ponente': '0001', 'persona_id': person.pk,
            'fecha': (timezone.localdate() + timedelta(days=1)).isoformat(),
            'hora_inicio': '09:00', 'hora_fin': '10:00',
        })
        self.assertTrue(form.is_valid(), form.errors)


class MultipleProfilesImportUITests(ExcelAdminFixture, TestCase):
    # Reutiliza la preparación de cliente, permisos y carpeta temporal privada.
    def test_preview_and_confirmation_show_added_profiles_and_keep_one_person(self):
        response = self.upload(staff_workbook())
        self.assertContains(response, 'Perfiles por agregar')
        self.assertTrue(response.context['plan'].valid)
        self.assertFalse(Persona.objects.exists())
        response = self.client.post(self.url, {'accion': 'confirmar', 'token': response.context['token']})
        self.assertContains(response, 'Perfiles agregados')
        self.assertEqual(Persona.objects.count(), 1)
        self.assertEqual(PersonaPerfil.objects.count(), 2)

    def test_over_1000_records_are_imported_completely_with_only_100_preview_samples(self):
        rows = [[f'D{n:04}', f'Docente {n}', 'Pérez', ''] for n in range(1, 1102)]
        response = self.upload(workbook({'Docentes': [COLUMNAS['Docentes'], *rows]}))
        self.assertContains(response, 'muestra de 100 de 1101 registros válidos')
        self.assertFalse(Persona.objects.exists())
        response = self.client.post(self.url, {'accion': 'confirmar', 'token': response.context['token']})
        self.assertTrue(response.context['completed'])
        self.assertEqual(Persona.objects.count(), 1101)
        self.assertEqual(PersonaPerfil.objects.count(), 1101)
        self.assertTrue(Persona.objects.filter(matricula='D1101').exists())

    def test_error_after_first_1000_records_blocks_confirmation(self):
        rows = [[f'D{n:04}', f'Docente {n}', 'Pérez', ''] for n in range(1, 1102)]
        rows[-1][1] = ''
        response = self.upload(workbook({'Docentes': [COLUMNAS['Docentes'], *rows]}))
        self.assertNotIn('token', response.context)
        self.assertContains(response, 'fila 1102')
        self.assertFalse(Persona.objects.exists())


class MultipleProfilesMigrationTests(TransactionTestCase):
    def test_existing_profiles_migrate_with_history_and_without_duplicate_people(self):
        old = [('inicio', '0002_integrar_esquema_excel')]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate(old)
        try:
            apps = executor.loader.project_state(old).apps
            person = apps.get_model('inicio', 'Persona').objects.create(
                matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Administrador',
            )
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            self.assertEqual(Persona.objects.count(), 1)
            migrated = Persona.objects.get(pk=person.pk)
            self.assertEqual(migrated.perfil, 'Administrador')
            self.assertEqual(migrated.perfiles_actuales, {'Administrador'})
            self.assertEqual(PersonaPerfil.history.count(), 1)
            # Reaplicar el backfill es idempotente; su reversa no borra datos.
            executor = MigrationExecutor(connection)
            executor.migrate([('inicio', '0003_perfiles_persona')])
            MigrationExecutor(connection).migrate(latest)
            self.assertEqual(PersonaPerfil.objects.count(), 1)
            self.assertEqual(PersonaPerfil.history.count(), 1)
        finally:
            MigrationExecutor(connection).migrate(latest)
