from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import RegistroClaseForm, RegistroEventoForm, RegistroUsuarioForm
from .models import (
    Carrera,
    Clase,
    EventoTallerConferencia,
    Grupo,
    Materia,
    Persona,
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


class SalaComputoViewTests(TestCase):
    def test_entry_type_must_be_selected_before_its_form_is_shown(self):
        response = self.client.get(reverse('sala_computo'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Selecciona un tipo de entrada.')
        self.assertContains(response, 'data-registro-fields="Clase" hidden')
        self.assertContains(response, 'data-registro-type="Clase" aria-pressed="false"')

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
