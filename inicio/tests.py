from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import RegistroClaseForm, RegistroEventoForm, RegistroUsuarioForm
from .models import (
    Asistencia,
    Carrera,
    Clase,
    Equipo,
    EventoTallerConferencia,
    Externo,
    Grupo,
    Materia,
    Persona,
    Registro,
    UsuarioSistema,
    normalizar_hora,
)


class LoginViewTests(TestCase):
    def test_login_page_is_available(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'inicio/login.html')

    def test_valid_credentials_open_the_home_page(self):
        password = 'Prueba-segura-123'
        UsuarioSistema.objects.create_user(username='operador', password=password)

        response = self.client.post(reverse('login'), {
            'usuario': 'operador',
            'contrasena': password,
        })

        self.assertRedirects(response, reverse('homePage'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_invalid_credentials_show_an_error(self):
        response = self.client.post(reverse('login'), {
            'usuario': 'inexistente',
            'contrasena': 'incorrecta',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Usuario o contraseña incorrectos.')


class HomePageViewTests(TestCase):
    def test_home_page_requires_authentication(self):
        response = self.client.get(reverse('homePage'))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('homePage')}")

    def test_authenticated_user_can_open_home_page(self):
        user = UsuarioSistema.objects.create_user(
            username='operador',
            password='Prueba-segura-123',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('homePage'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'inicio/homePage.html')

    def test_splash_is_shown_only_once_after_successful_login(self):
        password = 'Prueba-segura-123'
        UsuarioSistema.objects.create_user(username='operador', password=password)

        login_response = self.client.post(reverse('login'), {
            'usuario': 'operador',
            'contrasena': password,
        })
        self.assertRedirects(login_response, reverse('homePage'), fetch_redirect_response=False)

        first_home_response = self.client.get(reverse('homePage'))
        self.assertContains(first_home_response, 'id="splash-screen"')

        next_home_response = self.client.get(reverse('homePage'))
        self.assertNotContains(next_home_response, 'id="splash-screen"')


class AutoAccesoViewTests(TestCase):
    def setUp(self):
        self.user = UsuarioSistema.objects.create_user(
            username='operador_auto',
            password='Prueba-segura-123',
            mod_auto_acceso=True,
        )
        self.client.force_login(self.user)

    def test_auto_access_page_is_available_from_home_and_has_readonly_student_fields(self):
        response = self.client.get(reverse('auto_acceso'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-auto-access-account')
        self.assertContains(response, 'data-auto-access-reason')
        self.assertContains(response, 'data-student-name readonly')
        self.assertContains(response, 'data-student-last-name readonly')
        self.assertContains(response, 'data-student-career readonly')
        self.assertContains(response, 'data-student-group readonly')
        self.assertContains(response, reverse('buscar_alumno_auto_acceso'))

        home_response = self.client.get(reverse('homePage'))
        self.assertContains(home_response, f'href="{reverse("auto_acceso")}"')

    def test_auto_access_lookup_returns_student_details_and_excludes_non_students(self):
        career = Carrera.objects.create(nombre_carrera='Sistemas')
        group = Grupo.objects.create(nombre_grupo='A', carrera=career)
        student = Persona.objects.create(
            perfil='Alumno',
            matricula='ALU-AUTO-1',
            nombre='Ana',
            apellidos='Pérez',
            carrera=career,
            grupo=group,
        )
        Persona.objects.create(
            perfil='Docente',
            matricula='DOC-AUTO-1',
            nombre='Luis',
            apellidos='López',
        )

        response = self.client.get(reverse('buscar_alumno_auto_acceso'), {
            'cuenta': student.matricula,
        })
        teacher_response = self.client.get(reverse('buscar_alumno_auto_acceso'), {
            'cuenta': 'DOC-AUTO-1',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'encontrado': True,
            'nombre': 'Ana',
            'apellidos': 'Pérez',
            'carrera': 'Sistemas',
            'grupo': str(group),
        })
        self.assertEqual(teacher_response.status_code, 404)

    def test_auto_access_records_visit_and_conversation_for_the_verified_student(self):
        student = Persona.objects.create(
            perfil='Alumno',
            matricula='ALU-AUTO-2',
            nombre='Carlos',
            apellidos='Ruiz',
        )

        for reason in ('Visita', 'Conversacion'):
            with self.subTest(reason=reason):
                response = self.client.post(reverse('auto_acceso'), {
                    'numero_cuenta': student.matricula,
                    'motivo_uso': reason,
                })

                self.assertRedirects(response, reverse('auto_acceso'))
                record = Registro.objects.get(motivo_uso=reason)
                self.assertEqual(record.modulo, 'Auto_Acceso')
                self.assertIsNone(record.tipo_registro)
                self.assertEqual(record.persona, student)
                self.assertEqual(record.registrado_por, self.user)

    def test_auto_access_rejects_an_account_that_is_not_a_student(self):
        Persona.objects.create(
            perfil='Docente',
            matricula='DOC-AUTO-2',
            nombre='Elena',
            apellidos='Díaz',
        )

        response = self.client.post(reverse('auto_acceso'), {
            'numero_cuenta': 'DOC-AUTO-2',
            'motivo_uso': 'Visita',
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('numero_cuenta', response.context['form'].errors)
        self.assertFalse(Registro.objects.filter(modulo='Auto_Acceso').exists())

    def test_auto_access_requires_module_permission(self):
        self.client.logout()
        user = UsuarioSistema.objects.create_user(
            username='sin_auto_acceso',
            password='Prueba-segura-123',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('auto_acceso'))

        self.assertRedirects(
            response,
            f"{reverse('homePage')}?next={reverse('auto_acceso')}",
        )


class SalaComputoViewTests(TestCase):
    def test_entry_type_must_be_selected_before_its_form_is_shown(self):
        response = self.client.get(reverse('sala_computo'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Selecciona un tipo de entrada.')
        self.assertContains(response, 'data-registro-fields="Clase" hidden')
        self.assertContains(response, 'data-registro-type="Clase" aria-pressed="false"')
        self.assertContains(response, 'data-register-attendance')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertNotContains(response, 'data-demo-save')

    def test_scheduling_forms_use_styled_time_picker_with_native_form_values(self):
        response = self.client.get(reverse('sala_computo'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="time" name="hora_inicio"')
        self.assertContains(response, 'type="time" name="hora_fin"')
        self.assertContains(response, 'data-time-picker')
        self.assertContains(response, 'Selecciona la hora')
        self.assertContains(response, 'data-time-apply')
        self.assertContains(response, 'data-nombre-ponente-interno')
        self.assertContains(response, 'data-ponente-externo-fields')
        self.assertContains(response, 'class="app-confirm-dialog"')
        self.assertContains(response, 'data-confirm-accept')

    def test_class_form_lists_careers_from_database(self):
        systems = Carrera.objects.create(nombre_carrera='Sistemas')
        accounting = Carrera.objects.create(nombre_carrera='Contabilidad')

        response = self.client.get(reverse('sala_computo'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['clase_form'].fields['carrera'].choices),
            [
                ('', 'Selecciona la carrera'),
                (str(accounting.pk), 'Contabilidad'),
                (str(systems.pk), 'Sistemas'),
            ],
        )

    def test_class_submission_renders_date_validation_errors(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        response = self.client.post(reverse('sala_computo'), {
            'categoria': 'clase',
            'fecha': yesterday.isoformat(),
            'fecha_fin_repeticion': timezone.localdate().isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'La fecha de inicio no puede ser anterior a hoy.')
        self.assertEqual(response.context['active_schedule_view'], 'clase')

    def test_event_submission_renders_date_validation_errors(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        response = self.client.post(reverse('sala_computo'), {
            'categoria': 'evento',
            'tipo_evento': 'Taller',
            'nombre_evento': 'Evento de prueba',
            'pertenece_al_plantel': 'no',
            'nombre_ponente_externo': 'Ponente de prueba',
            'apellidos_ponente_externo': 'Externo',
            'fecha': yesterday.isoformat(),
            'hora_inicio': '09:00',
            'hora_fin': '10:00',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'La fecha del evento no puede ser anterior a hoy.')
        self.assertEqual(response.context['active_schedule_view'], 'evento')

    def test_internal_speaker_lookup_returns_administrator_or_teacher(self):
        for perfil, matricula in (('Administrador', 'ADM-101'), ('Docente', 'DOC-101')):
            with self.subTest(perfil=perfil):
                persona = Persona.objects.create(
                    perfil=perfil,
                    matricula=matricula,
                    nombre='Ana',
                    apellidos='Pérez',
                )

                response = self.client.get(reverse('buscar_ponente_sala'), {'cuenta': matricula})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {
                    'encontrado': True,
                    'persona_id': persona.pk,
                    'nombre': 'Ana Pérez',
                })

    def test_internal_speaker_lookup_rejects_student_profile(self):
        Persona.objects.create(
            perfil='Alumno',
            matricula='ALU-101',
            nombre='Luis',
            apellidos='López',
        )

        response = self.client.get(reverse('buscar_ponente_sala'), {'cuenta': 'ALU-101'})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()['encontrado'])

    def test_teacher_lookup_returns_teacher_and_career_from_database(self):
        career = Carrera.objects.create(nombre_carrera='Sistemas')
        teacher = Persona.objects.create(
            perfil='Docente',
            matricula='DOC-102',
            nombre='Ana',
            apellidos='Pérez',
            carrera=career,
        )

        response = self.client.get(reverse('buscar_docente_sala'), {'cuenta': teacher.matricula})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'encontrado': True,
            'persona_id': teacher.pk,
            'nombre': 'Ana Pérez',
            'carrera_id': career.pk,
            'carrera': 'Sistemas',
        })

    def test_teacher_lookup_does_not_return_students(self):
        Persona.objects.create(
            perfil='Alumno',
            matricula='ALU-102',
            nombre='Luis',
            apellidos='López',
        )

        response = self.client.get(reverse('buscar_docente_sala'), {'cuenta': 'ALU-102'})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()['encontrado'])

    def test_class_catalogs_only_return_entries_for_the_teacher_career(self):
        career = Carrera.objects.create(nombre_carrera='Sistemas')
        other_career = Carrera.objects.create(nombre_carrera='Contabilidad')
        teacher = Persona.objects.create(
            perfil='Docente',
            matricula='DOC-103',
            nombre='Ana',
            apellidos='Pérez',
            carrera=career,
        )
        subject = Materia.objects.create(nombre_materia='Programación', carrera=career)
        Materia.objects.create(nombre_materia='Contabilidad financiera', carrera=other_career)
        group = Grupo.objects.create(
            nombre_grupo='A',
            semestre=1,
            turno='Matutino',
            carrera=career,
        )
        Grupo.objects.create(nombre_grupo='B', carrera=other_career)

        response = self.client.get(reverse('catalogos_clase_docente'), {
            'cuenta': teacher.matricula,
            'carrera': career.pk,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'carreras': [{'id': career.pk, 'nombre': 'Sistemas'}],
            'materias': [{'id': subject.pk, 'nombre': 'Programación'}],
            'grupos': [{'id': group.pk, 'nombre': str(group)}],
        })

    def test_class_catalogs_reject_a_career_different_from_the_teacher(self):
        career = Carrera.objects.create(nombre_carrera='Sistemas')
        other_career = Carrera.objects.create(nombre_carrera='Contabilidad')
        teacher = Persona.objects.create(
            perfil='Docente',
            matricula='DOC-104',
            nombre='Ana',
            apellidos='Pérez',
            carrera=career,
        )

        response = self.client.get(reverse('catalogos_clase_docente'), {
            'cuenta': teacher.matricula,
            'carrera': other_career.pk,
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn('La carrera seleccionada no corresponde al docente.', response.json()['error'])

    def test_unassigned_teacher_can_load_catalogs_for_a_selected_career(self):
        career = Carrera.objects.create(nombre_carrera='Sistemas')
        other_career = Carrera.objects.create(nombre_carrera='Contabilidad')
        teacher = Persona.objects.create(
            perfil='Docente',
            matricula='DOC-104A',
            nombre='Ana',
            apellidos='Pérez',
        )
        subject = Materia.objects.create(nombre_materia='Programación', carrera=career)
        Materia.objects.create(nombre_materia='Contabilidad financiera', carrera=other_career)
        group = Grupo.objects.create(nombre_grupo='A', carrera=career)
        Grupo.objects.create(nombre_grupo='B', carrera=other_career)

        response = self.client.get(reverse('catalogos_clase_docente'), {
            'cuenta': teacher.matricula,
            'carrera': career.pk,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'carreras': [
                    {'id': other_career.pk, 'nombre': 'Contabilidad'},
                    {'id': career.pk, 'nombre': 'Sistemas'},
                ],
                'materias': [{'id': subject.pk, 'nombre': 'Programación'}],
                'grupos': [{'id': group.pk, 'nombre': str(group)}],
            },
        )

    def test_class_submission_validates_database_catalogs_and_saves(self):
        career = Carrera.objects.create(nombre_carrera='Sistemas')
        teacher = Persona.objects.create(
            perfil='Docente',
            matricula='DOC-105',
            nombre='Ana',
            apellidos='Pérez',
            carrera=career,
        )
        subject = Materia.objects.create(nombre_materia='Programación', carrera=career)
        group = Grupo.objects.create(nombre_grupo='A', carrera=career)
        start = timezone.localdate() + timedelta(days=1)
        while start.weekday() > 4:
            start += timedelta(days=1)

        response = self.client.post(reverse('sala_computo'), {
            'categoria': 'clase',
            'tipo_actividad': 'regular',
            'numero_cuenta_docente': teacher.matricula,
            'docente_id': str(teacher.pk),
            'carrera': str(career.pk),
            'materia': str(subject.pk),
            'grupo': str(group.pk),
            'fecha': start.isoformat(),
            'fecha_fin_repeticion': start.isoformat(),
            'hora_inicio': '09:00',
            'hora_fin': '10:00',
            'dias_repeticion': [str(start.weekday())],
        })

        self.assertRedirects(response, reverse('sala_computo'))
        self.assertEqual(Clase.objects.count(), 1)

    def test_class_submission_saves_for_unassigned_teacher_and_selected_career(self):
        career = Carrera.objects.create(nombre_carrera='Sistemas')
        teacher = Persona.objects.create(
            perfil='Docente',
            matricula='DOC-105A',
            nombre='Ana',
            apellidos='Pérez',
        )
        subject = Materia.objects.create(nombre_materia='Programación', carrera=career)
        group = Grupo.objects.create(nombre_grupo='A', carrera=career)
        start = timezone.localdate() + timedelta(days=1)
        while start.weekday() > 4:
            start += timedelta(days=1)

        response = self.client.post(reverse('sala_computo'), {
            'categoria': 'clase',
            'tipo_actividad': 'regular',
            'numero_cuenta_docente': teacher.matricula,
            'docente_id': str(teacher.pk),
            'carrera': str(career.pk),
            'materia': str(subject.pk),
            'grupo': str(group.pk),
            'fecha': start.isoformat(),
            'fecha_fin_repeticion': start.isoformat(),
            'hora_inicio': '09:00',
            'hora_fin': '10:00',
            'dias_repeticion': [str(start.weekday())],
        })

        self.assertRedirects(response, reverse('sala_computo'))
        clase = Clase.objects.get()
        self.assertEqual(clase.docente, teacher)
        self.assertEqual(clase.materia, subject)
        self.assertEqual(clase.grupo, group)

    def test_class_submission_rejects_a_subject_from_another_career(self):
        career = Carrera.objects.create(nombre_carrera='Sistemas')
        other_career = Carrera.objects.create(nombre_carrera='Contabilidad')
        teacher = Persona.objects.create(
            perfil='Docente',
            matricula='DOC-106',
            nombre='Ana',
            apellidos='Pérez',
            carrera=career,
        )
        foreign_subject = Materia.objects.create(
            nombre_materia='Contabilidad financiera',
            carrera=other_career,
        )
        group = Grupo.objects.create(nombre_grupo='A', carrera=career)
        start = timezone.localdate() + timedelta(days=1)
        while start.weekday() > 4:
            start += timedelta(days=1)

        response = self.client.post(reverse('sala_computo'), {
            'categoria': 'clase',
            'tipo_actividad': 'regular',
            'numero_cuenta_docente': teacher.matricula,
            'docente_id': str(teacher.pk),
            'carrera': str(career.pk),
            'materia': str(foreign_subject.pk),
            'grupo': str(group.pk),
            'fecha': start.isoformat(),
            'fecha_fin_repeticion': start.isoformat(),
            'hora_inicio': '09:00',
            'hora_fin': '10:00',
            'dias_repeticion': [str(start.weekday())],
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('materia', response.context['clase_form'].errors)
        self.assertFalse(Clase.objects.exists())

    def test_equipment_lookup_preserves_available_default_and_can_include_all(self):
        available = Equipo.objects.create(no_equipo='PC-01', lugar='Sala', estado='Disponible')
        occupied = Equipo.objects.create(no_equipo='PC-02', lugar='Sala', estado='Ocupado')
        Equipo.objects.create(no_equipo='PC-03', lugar='Biblioteca', estado='Disponible')

        available_response = self.client.get(reverse('equipos_sala'))
        all_response = self.client.get(reverse('equipos_sala'), {'todos': '1'})

        self.assertEqual(available_response.status_code, 200)
        self.assertEqual([item['id'] for item in available_response.json()['equipos']], [available.pk])
        self.assertEqual(
            [item['id'] for item in all_response.json()['equipos']],
            [available.pk, occupied.pk],
        )

    def test_equipment_lookup_sorts_numeric_numbers_in_natural_order(self):
        for number in ('10', '2', '1'):
            Equipo.objects.create(no_equipo=number, lugar='Sala', estado='Disponible')

        response = self.client.get(reverse('equipos_sala'))

        self.assertEqual(
            [item['nombre'] for item in response.json()['equipos']],
            ['1', '2', '10'],
        )

    def test_equipment_history_filters_by_equipment_date_and_type(self):
        equipment = Equipo.objects.create(no_equipo='PC-11', lugar='Sala')
        other_equipment = Equipo.objects.create(no_equipo='PC-12', lugar='Sala')
        person = Persona.objects.create(
            perfil='Alumno',
            matricula='ALU-111',
            nombre='Luis',
            apellidos='López',
        )
        Registro.objects.create(
            equipo=equipment,
            persona=person,
            modulo='Sala_Computo',
            tipo_registro='Clase',
            fecha=timezone.localdate(),
            hora_entrada=time(9, 0),
        )
        Registro.objects.create(
            equipo=other_equipment,
            persona=person,
            modulo='Sala_Computo',
            tipo_registro='Visita',
            fecha=timezone.localdate(),
            hora_entrada=time(10, 0),
        )

        response = self.client.get(reverse('historial_equipo_sala'), {
            'equipo_id': equipment.pk,
            'fecha': timezone.localdate().isoformat(),
            'tipo': 'CLASE',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['registros'], [{
            'id': Registro.objects.get(equipo=equipment).pk,
            'tipo': 'Clase',
            'persona': 'Luis López',
            'cuenta': 'ALU-111',
            'hora': '09:00',
        }])

    def test_incident_submission_saves_equipment_and_optional_usage_record(self):
        equipment = Equipo.objects.create(no_equipo='PC-21', lugar='Sala')
        person = Persona.objects.create(
            perfil='Alumno',
            matricula='ALU-121',
            nombre='Ana',
            apellidos='Pérez',
        )
        record = Registro.objects.create(
            equipo=equipment,
            persona=person,
            modulo='Sala_Computo',
            tipo_registro='Visita',
            fecha=timezone.localdate(),
            hora_entrada=time(11, 0),
        )

        response = self.client.post(reverse('registrar_incidencia_sala'), {
            'equipo_id': equipment.pk,
            'registro_id': record.pk,
            'momento_deteccion': 'durante_uso',
            'descripcion': 'El teclado no responde.',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['guardado'])
        incidencia = equipment.incidencias.get()
        self.assertEqual(incidencia.registro, record)
        self.assertEqual(incidencia.descripcion, 'El teclado no responde.')

    def test_external_event_attendee_can_register_find_and_close_entry_by_folio(self):
        speaker = Externo.objects.create(
            nombre='Ponente',
            apellidos='Externo',
            institucion='Universidad de prueba',
        )
        with patch(
            'inicio.models.timezone.localtime',
            return_value=datetime.combine(timezone.localdate(), time(8, 0)),
        ):
            event = EventoTallerConferencia.objects.create(
                tipo_evento='Taller',
                nombre_evento='Taller de prueba',
                tipo_ponente='Externo',
                ponente_externo=speaker,
                fecha=timezone.localdate(),
                hora_inicio=time(9, 0),
                hora_fin=time(10, 0),
            )
        equipment = Equipo.objects.create(no_equipo='PC-31', lugar='Sala')
        entry = self.client.post(reverse('registrar_entrada_sala'), {
            'tipo': 'evento',
            'evento_id': event.pk,
            'nombre': 'María',
            'apellidos': 'Gómez',
            'institucion': 'Institución visitante',
            'equipo_id': equipment.pk,
        })
        self.assertEqual(entry.status_code, 200, entry.json())
        record = Registro.objects.get(pk=entry.json()['registro_id'])

        lookup = self.client.get(reverse('buscar_salida_sala'), {'folio': f'R-{record.pk}'})

        self.assertEqual(lookup.status_code, 200)
        self.assertEqual(lookup.json()['nombre'], 'María Gómez')
        self.assertEqual(lookup.json()['cuenta'], '')

        close = self.client.post(reverse('registrar_salida_sala'), {'registro_id': record.pk})

        self.assertEqual(close.status_code, 200)
        record.refresh_from_db()
        equipment.refresh_from_db()
        self.assertIsNotNone(record.hora_salida)
        self.assertEqual(equipment.estado, 'Disponible')

    def test_class_attendance_saves_presence_absence_and_equipment_use(self):
        career = Carrera.objects.create(nombre_carrera='Sistemas')
        group = Grupo.objects.create(nombre_grupo='A', carrera=career)
        subject = Materia.objects.create(nombre_materia='Programación', carrera=career)
        teacher = Persona.objects.create(
            perfil='Docente',
            matricula='DOC-131',
            nombre='Elena',
            apellidos='Ruiz',
            carrera=career,
        )
        students = [
            Persona.objects.create(
                perfil='Alumno',
                matricula='ALU-131',
                nombre='Luis',
                apellidos='López',
                carrera=career,
                grupo=group,
            ),
            Persona.objects.create(
                perfil='Alumno',
                matricula='ALU-132',
                nombre='Ana',
                apellidos='Pérez',
                carrera=career,
                grupo=group,
            ),
        ]
        with patch(
            'inicio.models.timezone.localtime',
            return_value=datetime.combine(timezone.localdate(), time(8, 0)),
        ):
            clase = Clase.objects.create(
                materia=subject,
                grupo=group,
                docente=teacher,
                fecha=timezone.localdate(),
                hora_inicio=time(9, 0),
                hora_fin=time(10, 0),
            )
        equipment = Equipo.objects.create(no_equipo='PC-41', lugar='Sala')

        response = self.client.post(reverse('registrar_asistencia_sala'), {
            'clase_id': clase.pk,
            'asistencias': (
                f'[{{"alumno_id": {students[0].pk}, "estado": "Asistió", "equipo_id": "{equipment.pk}"}},'
                f'{{"alumno_id": {students[1].pk}, "estado": "Falta", "equipo_id": ""}}]'
            ),
        })

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()['total'], 2)
        self.assertEqual(Asistencia.objects.filter(clase=clase).count(), 2)
        self.assertEqual(
            set(Asistencia.objects.filter(clase=clase).values_list('estado', flat=True)),
            {'Asistió', 'Falta'},
        )
        self.assertEqual(Registro.objects.filter(clase=clase).count(), 1)
        equipment.refresh_from_db()
        self.assertEqual(equipment.estado, 'Ocupado')


class RegistroClaseFormValidationTests(TestCase):
    def form(self, **data):
        defaults = {
            'fecha': (timezone.localdate() + timedelta(days=1)).isoformat(),
            'fecha_fin_repeticion': (timezone.localdate() + timedelta(days=8)).isoformat(),
            'hora_inicio': '09:00',
            'hora_fin': '10:00',
            'dias_repeticion': [str((timezone.localdate() + timedelta(days=1)).weekday())],
        }
        defaults.update(data)
        return RegistroClaseForm(data=defaults)

    def test_rejects_start_date_in_the_past(self):
        form = self.form(
            fecha=(timezone.localdate() - timedelta(days=1)).isoformat(),
        )

        self.assertFalse(form.is_valid())
        self.assertIn('La fecha de inicio no puede ser anterior a hoy.', form.errors['fecha'])

    def test_rejects_end_date_in_the_past(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        form = self.form(
            fecha=yesterday.isoformat(),
            fecha_fin_repeticion=yesterday.isoformat(),
            dias_repeticion=[str(yesterday.weekday())],
        )

        self.assertFalse(form.is_valid())
        self.assertIn('La fecha final no puede ser anterior a hoy.', form.errors['fecha_fin_repeticion'])

    def test_rejects_end_date_before_start_date(self):
        start = timezone.localdate() + timedelta(days=7)
        form = self.form(
            fecha=start.isoformat(),
            fecha_fin_repeticion=(start - timedelta(days=1)).isoformat(),
            dias_repeticion=[str(start.weekday())],
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            'La fecha final debe ser igual o posterior a la fecha inicial.',
            form.errors['fecha_fin_repeticion'],
        )

    def test_rejects_end_time_equal_to_or_before_start_time(self):
        for end_time in ('09:00', '08:59'):
            with self.subTest(end_time=end_time):
                form = self.form(hora_fin=end_time)

                self.assertFalse(form.is_valid())
                self.assertIn(
                    'La hora de término debe ser posterior a la hora de inicio.',
                    form.errors['hora_fin'],
                )

    def test_requires_both_times(self):
        form = self.form(hora_inicio='', hora_fin='')

        self.assertFalse(form.is_valid())
        self.assertTrue(form.errors['hora_inicio'])
        self.assertTrue(form.errors['hora_fin'])

    def test_rejects_a_start_time_that_already_passed_today(self):
        today = date(2026, 1, 5)
        now = datetime.combine(today, time(10, 0), tzinfo=timezone.get_current_timezone())
        form = self.form(
            fecha=today.isoformat(),
            fecha_fin_repeticion=(today + timedelta(days=7)).isoformat(),
            hora_inicio='09:00',
            hora_fin='10:30',
            dias_repeticion=['0'],
        )

        with patch('inicio.forms.timezone.localdate', return_value=today), patch(
            'inicio.forms.timezone.localtime',
            return_value=now,
        ):
            self.assertFalse(form.is_valid())

        self.assertIn(
            'La hora de inicio ya pasó para la clase de hoy (fuera del margen de 5 minutos).',
            form.errors['hora_inicio'],
        )


class RegistroEventoFormValidationTests(TestCase):
    def form(self, **data):
        defaults = {
            'tipo_evento': 'Taller',
            'nombre_evento': 'Evento de prueba',
            'pertenece_al_plantel': 'no',
            'nombre_ponente_externo': 'Ponente de prueba',
            'apellidos_ponente_externo': 'Externo',
            'fecha': (timezone.localdate() + timedelta(days=1)).isoformat(),
            'hora_inicio': '09:00',
            'hora_fin': '10:00',
        }
        defaults.update(data)
        return RegistroEventoForm(data=defaults)

    def test_rejects_an_event_date_in_the_past(self):
        form = self.form(fecha=(timezone.localdate() - timedelta(days=1)).isoformat())

        self.assertFalse(form.is_valid())
        self.assertIn('La fecha del evento no puede ser anterior a hoy.', form.errors['fecha'])

    def test_rejects_end_time_equal_to_or_before_start_time(self):
        for end_time in ('09:00', '08:59'):
            with self.subTest(end_time=end_time):
                form = self.form(hora_fin=end_time)

                self.assertFalse(form.is_valid())
                self.assertIn(
                    'La hora de término debe ser posterior a la hora de inicio.',
                    form.errors['hora_fin'],
                )

    def test_rejects_a_start_time_that_already_passed_today(self):
        today = date(2026, 1, 5)
        now = datetime.combine(today, time(10, 0), tzinfo=timezone.get_current_timezone())
        form = self.form(
            fecha=today.isoformat(),
            hora_inicio='09:00',
            hora_fin='10:30',
        )

        with patch('inicio.forms.timezone.localdate', return_value=today), patch(
            'inicio.forms.timezone.localtime',
            return_value=now,
        ):
            self.assertFalse(form.is_valid())

        self.assertIn(
            'La hora de inicio ya pasó para el evento (fuera del margen de 5 minutos).',
            form.errors['hora_inicio'],
        )

    def test_requires_date_and_both_times(self):
        form = self.form(fecha='', hora_inicio='', hora_fin='')

        self.assertFalse(form.is_valid())
        self.assertTrue(form.errors['fecha'])
        self.assertTrue(form.errors['hora_inicio'])
        self.assertTrue(form.errors['hora_fin'])

    def test_accepts_administrator_or_teacher_as_internal_speaker(self):
        for perfil, matricula in (('Administrador', 'ADM-201'), ('Docente', 'DOC-201')):
            with self.subTest(perfil=perfil):
                persona = Persona.objects.create(
                    perfil=perfil,
                    matricula=matricula,
                    nombre='María',
                    apellidos='García',
                )
                form = self.form(
                    pertenece_al_plantel='si',
                    numero_cuenta_ponente=matricula,
                    persona_id=str(persona.pk),
                )

                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data['persona'], persona)

    def test_rejects_a_student_as_internal_speaker(self):
        Persona.objects.create(
            perfil='Alumno',
            matricula='ALU-201',
            nombre='Luis',
            apellidos='López',
        )
        form = self.form(
            pertenece_al_plantel='si',
            numero_cuenta_ponente='ALU-201',
            persona_id='1',
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            'No se encontró un administrador o docente con ese número de cuenta.',
            form.errors['numero_cuenta_ponente'],
        )

    def test_scheduling_forms_include_compact_classes_and_footer(self):
        response = self.client.get(reverse('sala_computo'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'sala-form-panel--schedule')
        self.assertContains(response, 'institutional-footer')
        self.assertContains(response, 'sala-schedule-form-active')


class RegistroUsuarioFormTests(TestCase):
    def test_form_hashes_password_before_saving_user(self):
        form = RegistroUsuarioForm(data={
            'username': 'nuevo_operador',
            'password': 'Prueba-segura-123',
            'rol': 'operador',
        })

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertTrue(user.check_password('Prueba-segura-123'))
        self.assertNotEqual(user.password, 'Prueba-segura-123')
        self.assertEqual(user.rol, 'operador')


class HorarioNormalizacionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.carrera = Carrera.objects.create(nombre_carrera='Sistemas')
        cls.materia = Materia.objects.create(
            nombre_materia='Programación',
            carrera=cls.carrera,
        )
        cls.grupo = Grupo.objects.create(
            nombre_grupo='A',
            semestre=1,
            turno='Matutino',
            carrera=cls.carrera,
        )
        cls.persona = Persona.objects.create(
            perfil='Docente',
            matricula='DOC-001',
            nombre='Ana',
            apellidos='Prueba',
            carrera=cls.carrera,
        )

    def nueva_clase(self, **horarios):
        return Clase(
            materia=self.materia,
            grupo=self.grupo,
            docente=self.persona,
            fecha=timezone.localdate() + timedelta(days=1),
            hora_inicio=horarios.get('hora_inicio', time(9, 30)),
            hora_fin=horarios.get('hora_fin', time(10, 30)),
        )

    def test_model_save_normalizes_and_round_trips_class_times(self):
        clase = self.nueva_clase(
            hora_inicio=time(9, 30, 45, 123456),
            hora_fin=time(10, 30, 45, 654321),
        )
        clase.save()

        guardada = Clase.objects.get(pk=clase.pk)
        self.assertEqual(guardada.hora_inicio, time(9, 30))
        self.assertEqual(guardada.hora_fin, time(10, 30))

    def test_event_model_save_normalizes_both_schedule_fields(self):
        evento = EventoTallerConferencia(
            nombre_evento='Conferencia de prueba',
            fecha=timezone.localdate() + timedelta(days=1),
            hora_inicio=time(9, 30, 45, 123456),
            hora_fin=time(10, 30, 45, 654321),
            ponente_interno=self.persona,
        )
        evento.save()

        guardado = EventoTallerConferencia.objects.get(pk=evento.pk)
        self.assertEqual(guardado.hora_inicio, time(9, 30))
        self.assertEqual(guardado.hora_fin, time(10, 30))

    def test_bulk_create_bulk_update_and_queryset_update_normalize_times(self):
        primera = self.nueva_clase(
            hora_inicio=time(9, 30, 45, 123456),
            hora_fin=time(10, 30, 45, 654321),
        )
        Clase.objects.bulk_create([primera])
        primera.refresh_from_db()
        self.assertEqual(primera.hora_inicio, time(9, 30))
        self.assertEqual(primera.hora_fin, time(10, 30))

        primera.hora_inicio = time(11, 15, 59, 999999)
        primera.hora_fin = time(12, 15, 59, 999999)
        Clase.objects.bulk_update([primera], ['hora_inicio', 'hora_fin'])
        primera.refresh_from_db()
        self.assertEqual(primera.hora_inicio, time(11, 15))
        self.assertEqual(primera.hora_fin, time(12, 15))

        Clase.objects.filter(pk=primera.pk).update(
            hora_inicio=time(13, 45, 59, 123456),
            hora_fin=time(14, 45, 59, 654321),
        )
        primera.refresh_from_db()
        self.assertEqual(primera.hora_inicio, time(13, 45))
        self.assertEqual(primera.hora_fin, time(14, 45))

    def test_validation_compares_normalized_start_and_end(self):
        clase = self.nueva_clase(
            hora_inicio=time(9, 30, 45, 123456),
            hora_fin=time(9, 30, 30, 654321),
        )

        with self.assertRaises(ValidationError) as error:
            clase.save()

        self.assertIn('hora_fin', error.exception.message_dict)

    def test_empty_optional_values_are_left_unchanged(self):
        self.assertIsNone(normalizar_hora(None))
        self.assertEqual(normalizar_hora(''), '')

    def test_scheduling_forms_normalize_before_comparing(self):
        clase_form = RegistroClaseForm(data={
            'tipo_actividad': 'regular',
            'numero_cuenta_docente': self.persona.matricula,
            'docente_id': str(self.persona.pk),
            'carrera': str(self.carrera.pk),
            'materia': str(self.materia.pk),
            'grupo': str(self.grupo.pk),
            'fecha': (timezone.localdate() + timedelta(days=1)).isoformat(),
            'fecha_fin_repeticion': (timezone.localdate() + timedelta(days=7)).isoformat(),
            'hora_inicio': '09:30:45.123456',
            'hora_fin': '09:30:30.654321',
            'dias_repeticion': ['0'],
        }, catalogos={
            'carreras': [{'id': self.carrera.pk, 'nombre': self.carrera.nombre_carrera}],
            'materias': [{'id': self.materia.pk, 'nombre': self.materia.nombre_materia}],
            'grupos': [{'id': self.grupo.pk, 'nombre': str(self.grupo)}],
        })

        self.assertFalse(clase_form.is_valid())
        self.assertIn('hora_fin', clase_form.errors)

        evento_form = RegistroEventoForm(data={
            'tipo_evento': 'Conferencia',
            'nombre_evento': 'Conferencia de prueba',
            'pertenece_al_plantel': 'si',
            'numero_cuenta_ponente': self.persona.matricula,
            'persona_id': str(self.persona.pk),
            'fecha': (timezone.localdate() + timedelta(days=1)).isoformat(),
            'hora_inicio': '09:30:45.123456',
            'hora_fin': '10:30:15.654321',
        })
        self.assertTrue(evento_form.is_valid(), evento_form.errors)
        self.assertEqual(evento_form.cleaned_data['hora_inicio'], time(9, 30))
        self.assertEqual(evento_form.cleaned_data['hora_fin'], time(10, 30))
