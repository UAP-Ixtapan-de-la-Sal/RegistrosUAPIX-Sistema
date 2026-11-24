"""Formulario real de BitacoraFalla; ejecutar con config.settings_test."""
from datetime import time
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    BitacoraFalla, Equipo, ImplementoTecnologico, UsuarioSistema,
)


class BitacoraFallaAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UsuarioSistema.objects.create_superuser(username='adminfallas', password='prueba')
        cls.equipo = Equipo.objects.create(no_equipo='PC-FALLA', lugar='Sala')
        cls.implemento = ImplementoTecnologico.objects.create(
            codigo_interno='HDMI-FALLA', tipo_implemento='Cable HDMI',
            condicion='Bueno', estado='Disponible',
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.add_url = reverse('admin:inicio_bitacorafalla_add')

    def payload(self, **changes):
        data = {
            'lugar': 'Aula 4', 'equipo': str(self.equipo.pk), 'implemento': '',
            'categoria_falla': 'Conectividad', 'componente_afectado': 'Conector',
            'prioridad_alta': 'False', 'condicion': 'Regular', 'estado': 'Mantenimiento',
            'descripcion_falla': 'El conector no responde.',
            'usuario_sistema': str(self.user.pk), 'observaciones': '',
        }
        data.update(changes)
        return data

    def assert_saved(self, response):
        if response.status_code == 200:
            self.fail(str(response.context['adminform'].form.errors))
        self.assertEqual(response.status_code, 302)

    def test_actual_add_form_exposes_only_target_fields_in_one_plain_form(self):
        response = self.client.get(self.add_url)
        self.assertEqual(response.status_code, 200)
        form = response.context['adminform'].form
        target = {
            'lugar', 'equipo', 'implemento', 'categoria_falla', 'componente_afectado',
            'prioridad_alta', 'condicion', 'estado', 'descripcion_falla',
            'usuario_sistema', 'observaciones',
        }
        self.assertEqual(set(form.fields), target)
        self.assertEqual({field.name for field in BitacoraFalla._meta.fields},
                         target | {'id_falla', 'fecha_reporte'})
        for name in ('equipo', 'implemento', 'observaciones'):
            self.assertFalse(form.fields[name].required, name)
        for name in target - {'equipo', 'implemento', 'observaciones'}:
            self.assertTrue(form.fields[name].required, name)
        self.assertNotIn('id_falla', form.fields)
        self.assertNotIn('fecha_reporte', form.fields)
        fieldsets = response.context['adminform'].fieldsets
        self.assertEqual(len(fieldsets), 1)
        self.assertIsNone(fieldsets[0][0])
        self.assertNotContains(response, 'Información heredada')
        self.assertTemplateUsed(response, 'jazzmin/includes/single.html')
        self.assertEqual(form.fields['condicion'].label, 'Condición')
        self.assertEqual(form.fields['estado'].label, 'Estado')
        self.assertContains(response, 'name="implemento"')

    def test_create_with_only_equipment_and_empty_observations(self):
        response = self.client.post(self.add_url, self.payload())
        self.assert_saved(response)
        failure = BitacoraFalla.objects.get()
        self.assertEqual(failure.equipo_id, self.equipo.pk)
        self.assertIsNone(failure.implemento_id)
        self.assertIn(failure.observaciones, (None, ''))
        self.assertFalse(failure.prioridad_alta)
        self.assertEqual(failure.history.count(), 1)
        self.assertEqual(failure.history.get().history_user_id, self.user.pk)
        for name in ('registro_id', 'momento_deteccion', 'estado_atencion'):
            self.assertIsNone(getattr(failure.history.get(), name))

    def test_create_with_only_implement_and_edit_it(self):
        data = self.payload(equipo='', implemento=str(self.implemento.pk), prioridad_alta='True')
        self.assert_saved(self.client.post(self.add_url, data))
        failure = BitacoraFalla.objects.get()
        self.assertIsNone(failure.equipo_id)
        self.assertEqual(failure.implemento_id, self.implemento.pk)
        self.assertTrue(failure.prioridad_alta)
        url = reverse('admin:inicio_bitacorafalla_change', args=[failure.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        data['descripcion_falla'] = 'Se verificó el conector.'
        self.assert_saved(self.client.post(url, data))
        failure.refresh_from_db()
        self.assertEqual(failure.descripcion_falla, data['descripcion_falla'])
        self.assertEqual(failure.history.count(), 2)

    def test_both_or_neither_object_are_form_errors_without_saving(self):
        cases = (
            {'equipo': str(self.equipo.pk), 'implemento': str(self.implemento.pk)},
            {'equipo': '', 'implemento': ''},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                response = self.client.post(self.add_url, self.payload(**changes))
                self.assertEqual(response.status_code, 200)
                errors = response.context['adminform'].form.errors
                self.assertIn('equipo', errors)
                self.assertIn('implemento', errors)
                self.assertEqual(BitacoraFalla.objects.count(), 0)
                self.assertEqual(BitacoraFalla.history.count(), 0)

    def test_xor_also_applies_in_model_validation_and_database(self):
        for references in ({}, {'equipo': self.equipo, 'implemento': self.implemento}):
            with self.subTest(references=references):
                failure = BitacoraFalla(descripcion_falla='Falla', **references)
                with self.assertRaises(ValidationError):
                    failure.full_clean()
                # bulk_create omite save/full_clean: la BD debe rechazarlo.
                with self.assertRaises(IntegrityError), transaction.atomic():
                    BitacoraFalla.objects.bulk_create([failure])

    def test_new_reports_require_snapshot_without_inventing_priority(self):
        names = ('lugar', 'categoria_falla', 'componente_afectado', 'prioridad_alta',
                 'condicion', 'estado', 'usuario_sistema')
        response = self.client.post(self.add_url, self.payload(**{name: '' for name in names}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(set(names).issubset(response.context['adminform'].form.errors))
        self.assertEqual(BitacoraFalla.objects.count(), 0)

    def test_condition_and_object_state_have_exact_choices(self):
        form = self.client.get(self.add_url).context['adminform'].form
        self.assertEqual([value for value, _ in form.fields['condicion'].choices if value],
                         ['Bueno', 'Regular', 'Malo'])
        self.assertEqual([value for value, _ in form.fields['estado'].choices if value],
                         ['Disponible', 'Ocupado', 'Mantenimiento', 'Baja'])
        self.assertEqual([(value, label) for value, label in form.fields['prioridad_alta'].choices if value],
                         [('True', 'Sí'), ('False', 'No')])
        for name, invalid in (('condicion', 'Resuelta'), ('estado', 'Pendiente')):
            response = self.client.post(self.add_url, self.payload(**{name: invalid}))
            self.assertEqual(response.status_code, 200)
            self.assertIn(name, response.context['adminform'].form.errors)

    def test_new_priority_is_explicitly_yes_or_no(self):
        for value in ('', 'None', 'Pendiente', '1'):
            with self.subTest(value=value):
                response = self.client.post(self.add_url, self.payload(prioridad_alta=value))
                self.assertEqual(response.status_code, 200)
                self.assertIn('prioridad_alta', response.context['adminform'].form.errors)
                self.assertEqual(BitacoraFalla.objects.count(), 0)

    def test_database_rejects_invalid_condition_and_state_on_updates(self):
        failure = BitacoraFalla.objects.create(equipo=self.equipo, descripcion_falla='Falla')
        for name, value in (('condicion', 'Resuelta'), ('estado', 'Pendiente')):
            with self.subTest(name=name):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    BitacoraFalla.objects.filter(pk=failure.pk).update(**{name: value})

    def test_legacy_unknown_values_and_previous_history_are_preserved(self):
        stamp = timezone.now().replace(second=41, microsecond=123456)
        with patch('django.utils.timezone.now', return_value=stamp):
            failure = BitacoraFalla.objects.create(
                equipo=self.equipo, descripcion_falla='Reporte anterior',
            )
        snapshots = list(failure.history.values())
        url = reverse('admin:inicio_bitacorafalla_change', args=[failure.pk])
        response = self.client.get(url)
        form = response.context['adminform'].form
        for name in ('lugar', 'categoria_falla', 'componente_afectado', 'prioridad_alta',
                     'condicion', 'estado', 'usuario_sistema'):
            self.assertFalse(form.fields[name].required, name)
        self.assertNotIn('fecha_reporte', form.fields)
        self.assertIn('fecha_reporte', response.context['adminform'].readonly_fields)
        self.assertContains(response, 'Dato no capturado originalmente')
        response = self.client.post(url, {
            'equipo': str(self.equipo.pk), 'descripcion_falla': 'Descripción revisada',
            'observaciones': '', 'fecha_reporte': '2000-01-01T00:00',
        })
        self.assert_saved(response)
        failure.refresh_from_db()
        self.assertEqual(failure.fecha_reporte, stamp)
        for name in ('lugar', 'categoria_falla', 'componente_afectado', 'prioridad_alta',
                     'condicion', 'estado', 'usuario_sistema_id'):
            self.assertIsNone(getattr(failure, name), name)
        self.assertEqual(failure.history.count(), 2)
        for snapshot in snapshots:
            self.assertEqual(failure.history.filter(history_id=snapshot['history_id']).values().get(), snapshot)
        self.assertEqual(self.client.get(reverse('admin:inicio_bitacorafalla_history', args=[failure.pk])).status_code, 200)

    def test_edit_does_not_silently_erase_known_snapshot_values(self):
        self.assert_saved(self.client.post(self.add_url, self.payload()))
        failure = BitacoraFalla.objects.get()
        response = self.client.post(
            reverse('admin:inicio_bitacorafalla_change', args=[failure.pk]),
            self.payload(condicion='', estado='', prioridad_alta=''),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue({'condicion', 'estado', 'prioridad_alta'}.issubset(response.context['adminform'].form.errors))
        self.assertEqual(failure.history.count(), 1)

    def test_existing_incident_endpoint_keeps_its_contract(self):
        response = self.client.post(reverse('registrar_incidencia_sala'), {
            'equipo_id': self.equipo.pk, 'registro_id': '123',
            'momento_deteccion': 'durante_uso', 'descripcion': 'Teclado sin respuesta.',
        })
        self.assertEqual(response.status_code, 200)
        failure = BitacoraFalla.objects.get()
        self.assertEqual(response.json(), {'guardado': True, 'incidencia_id': failure.pk})
        self.assertEqual(failure.descripcion_falla, 'Teclado sin respuesta.')
        self.assertEqual(failure.usuario_sistema_id, self.user.pk)
        for name in ('lugar', 'categoria_falla', 'componente_afectado', 'prioridad_alta', 'estado', 'condicion'):
            self.assertIsNone(getattr(failure, name), name)
        for name in ('registro_id', 'momento_deteccion', 'estado_atencion'):
            self.assertIsNone(getattr(failure.history.get(), name))

    def test_existing_permissions_allow_implement_reports_without_expanding_access(self):
        editor = UsuarioSistema.objects.create_user(username='editorfallas', is_staff=True)
        editor.user_permissions.set(Permission.objects.filter(
            content_type__app_label='inicio', content_type__model='bitacorafalla',
            codename__in=['view_bitacorafalla', 'add_bitacorafalla', 'change_bitacorafalla'],
        ))
        self.client.force_login(editor)
        data = self.payload(equipo='', implemento=str(self.implemento.pk), usuario_sistema=str(editor.pk))
        self.assert_saved(self.client.post(self.add_url, data))
        failure = BitacoraFalla.objects.get()
        self.assert_saved(self.client.post(
            reverse('admin:inicio_bitacorafalla_change', args=[failure.pk]), data,
        ))
        viewer = UsuarioSistema.objects.create_user(username='lectorfallas', is_staff=True)
        viewer.user_permissions.set(Permission.objects.filter(
            content_type__app_label='inicio', codename='view_bitacorafalla',
        ))
        self.client.force_login(viewer)
        url = reverse('admin:inicio_bitacorafalla_change', args=[failure.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, data).status_code, 403)


class BitacoraFallaMigrationTests(TransactionTestCase):
    def test_removal_preserves_ids_target_data_permissions_and_existing_history(self):
        previous = [('inicio', '0008_estructura_prestamos_inventario')]
        target = [('inicio', '0009_depurar_campos_bitacorafalla')]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate(previous)
        try:
            old_apps = executor.loader.project_state(previous).apps
            old_failure = old_apps.get_model('inicio', 'BitacoraFalla')
            old_history = old_apps.get_model('inicio', 'HistoricalBitacoraFalla')
            user = old_apps.get_model('inicio', 'UsuarioSistema').objects.create(
                username='operadoranterior', password='!', is_staff=True, is_superuser=True,
            )
            equipment = old_apps.get_model('inicio', 'Equipo').objects.create(no_equipo='PC-ANTERIOR', lugar='Sala')
            person = old_apps.get_model('inicio', 'Persona').objects.create(
                nombre='Ana', apellidos='Ejemplo', perfil='Alumno',
            )
            record = old_apps.get_model('inicio', 'Registro').objects.create(
                persona_id=person.pk, equipo_id=equipment.pk, fecha=timezone.localdate(),
                hora_entrada=time(9), modulo='Sala_Computo', tipo_registro='Visita',
            )
            failure = old_failure.objects.create(
                id_falla=401, equipo_id=equipment.pk, registro_id=record.pk,
                usuario_sistema_id=user.pk, momento_deteccion='durante_uso',
                estado_atencion='Resuelta', descripcion_falla='Reporte anterior',
            )
            stamp = timezone.now().replace(second=43, microsecond=654321)
            old_failure.objects.filter(pk=failure.pk).update(fecha_reporte=stamp)
            failure.refresh_from_db()
            snapshot = old_history.objects.create(
                **{field.attname: getattr(failure, field.attname) for field in old_failure._meta.fields},
                history_id=501, history_date=stamp, history_type='+',
                history_user_id=user.pk, history_change_reason='Reporte original',
            )
            old_snapshot = old_history.objects.filter(pk=snapshot.pk).values().get()
            target_names = [field.attname for field in BitacoraFalla._meta.fields]
            old_target = old_failure.objects.filter(pk=failure.pk).values(*target_names).get()
            permissions = list(Permission.objects.filter(
                content_type__app_label='inicio', content_type__model='bitacorafalla',
            ).order_by('pk').values())
            tables = set(connection.introspection.table_names())

            MigrationExecutor(connection).migrate(target)

            self.assertEqual(set(connection.introspection.table_names()), tables)
            self.assertEqual(BitacoraFalla.objects.filter(pk=failure.pk).values(*target_names).get(), old_target)
            self.assertEqual(BitacoraFalla.history.filter(pk=snapshot.pk).values().get(), old_snapshot)
            self.assertEqual(list(Permission.objects.filter(
                content_type__app_label='inicio', content_type__model='bitacorafalla',
            ).order_by('pk').values()), permissions)
            with connection.cursor() as cursor:
                table = connection.ops.quote_name(BitacoraFalla._meta.db_table)
                cursor.execute(f'SELECT * FROM {table} WHERE 1=0')
                columns = {column[0] for column in cursor.description}
            self.assertFalse(columns & {'registro_id', 'momento_deteccion', 'estado_atencion'})

            historical = BitacoraFalla.history.get(pk=snapshot.pk)
            self.assertEqual(historical.registro_id, record.pk)
            self.assertEqual(historical.estado_atencion, 'Resuelta')
            self.assertEqual(historical.instance.pk, failure.pk)
            self.assertEqual(historical.history_object.pk, failure.pk)
            current = BitacoraFalla.objects.get(pk=failure.pk)
            current.descripcion_falla = 'Descripción corregida'
            current.save()
            self.assertEqual(current.history.count(), 2)
            new_snapshot = current.history.exclude(pk=snapshot.pk).get()
            for name in ('registro_id', 'momento_deteccion', 'estado_atencion'):
                self.assertIsNone(getattr(new_snapshot, name))
            self.assertEqual(BitacoraFalla.history.filter(pk=snapshot.pk).values().get(), old_snapshot)
            self.client.force_login(UsuarioSistema.objects.get(pk=user.pk))
            history_url = reverse('admin:inicio_bitacorafalla_simple_history', args=[failure.pk, snapshot.pk])
            self.assertEqual(self.client.get(history_url).status_code, 200)

            # La reversión con datos se detiene antes de reconstruir columnas.
            with self.assertRaises(IrreversibleError):
                MigrationExecutor(connection).migrate(previous)
            self.assertEqual(BitacoraFalla.objects.get(pk=failure.pk).descripcion_falla, 'Descripción corregida')
        finally:
            MigrationExecutor(connection).migrate(latest)
