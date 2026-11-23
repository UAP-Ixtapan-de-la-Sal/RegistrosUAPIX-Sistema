"""Catálogo de categorías y conversión de insumos e historial en bases aisladas."""

from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import CategoriaInsumo, Insumo, UsuarioSistema


class CategoriaInsumoAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UsuarioSistema.objects.create_superuser(username='admincategorias', password='prueba')

    def setUp(self):
        self.client.force_login(self.user)
        self.add_url = reverse('admin:inicio_categoriainsumo_add')
        self.insumo_add_url = reverse('admin:inicio_insumo_add')

    def test_initial_categories_exist(self):
        self.assertEqual(set(CategoriaInsumo.objects.values_list('nombre', flat=True)),
                         {'Limpieza', 'Papelería', 'Consumibles'})

    def test_native_popup_creates_category_and_insumo_can_select_it(self):
        response = self.client.post(self.add_url + '?_popup=1', {'nombre': 'Laboratorio', '_popup': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'admin/popup_response.html')
        category = CategoriaInsumo.objects.get(nombre='Laboratorio')

        response = self.client.get(self.insumo_add_url)
        field = response.context['adminform'].form.fields['categoria']
        self.assertTrue(field.required)
        self.assertTrue(field.widget.can_add_related)
        self.assertContains(response, 'id="add_id_categoria"')
        self.assertTrue(field.queryset.filter(pk=category.pk).exists())

        response = self.client.post(self.insumo_add_url, {
            'nombre_insumo': 'Frasco', 'categoria': str(category.pk),
            'unidad_medida': 'pieza', 'existencia_actual': '0', 'stock_minimo': '0',
            'activo': 'on',
        })
        self.assertEqual(response.status_code, 302)
        supply = Insumo.objects.get()
        self.assertEqual(supply.categoria, category)
        self.assertEqual(supply.history.get().categoria_id, category.pk)
        self.assertEqual(supply.history.get().history_user_id, self.user.pk)

        response = self.client.get(reverse('admin:inicio_insumo_changelist'), {'categoria__id__exact': category.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row.pk for row in response.context['cl'].result_list], [supply.pk])

    def test_standard_admin_can_edit_category(self):
        category = CategoriaInsumo.objects.create(nombre='Material especial')
        url = reverse('admin:inicio_categoriainsumo_change', args=[category.pk])
        form = self.client.get(url).context['adminform'].form
        self.assertEqual(set(form.fields), {'nombre'})
        self.assertEqual(self.client.post(url, {'nombre': 'Material de laboratorio'}).status_code, 302)
        category.refresh_from_db()
        self.assertEqual(category.nombre, 'Material de laboratorio')
        self.assertEqual(str(category), category.nombre)

    def test_related_add_button_respects_category_permissions(self):
        operator = UsuarioSistema.objects.create_user(username='capturainsumos', is_staff=True)
        operator.user_permissions.set(Permission.objects.filter(
            content_type__app_label='inicio', codename__in=['view_insumo', 'add_insumo', 'change_insumo'],
        ))
        self.client.force_login(operator)
        response = self.client.get(self.insumo_add_url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['adminform'].form.fields['categoria'].widget.can_add_related)
        self.assertNotContains(response, 'id="add_id_categoria"')
        self.assertEqual(self.client.get(self.add_url).status_code, 403)

        operator.user_permissions.add(Permission.objects.get(
            content_type__app_label='inicio', codename='add_categoriainsumo',
        ))
        response = self.client.get(self.insumo_add_url)
        self.assertTrue(response.context['adminform'].form.fields['categoria'].widget.can_add_related)
        self.assertEqual(self.client.get(self.add_url).status_code, 200)

    def test_duplicate_names_are_rejected_in_form_and_database(self):
        response = self.client.post(self.add_url, {'nombre': 'Limpieza'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('nombre', response.context['adminform'].form.errors)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CategoriaInsumo.objects.create(nombre='Limpieza')

    def test_name_is_required_in_model_and_database(self):
        with self.assertRaises(ValidationError):
            CategoriaInsumo(nombre='').full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CategoriaInsumo.objects.create(nombre='')

    def test_insumo_category_remains_required(self):
        response = self.client.post(self.insumo_add_url, {
            'nombre_insumo': 'Papel', 'categoria': '', 'unidad_medida': 'pieza',
            'existencia_actual': '0', 'stock_minimo': '0', 'activo': 'on',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('categoria', response.context['adminform'].form.errors)
        self.assertFalse(Insumo.objects.exists())
        with self.assertRaises(IntegrityError), transaction.atomic():
            Insumo.objects.create(nombre_insumo='Papel', unidad_medida='pieza', categoria=None)

    def test_used_category_cannot_be_deleted(self):
        category = CategoriaInsumo.objects.get(nombre='Papelería')
        supply = Insumo.objects.create(nombre_insumo='Papel', unidad_medida='pieza', categoria=category)
        with self.assertRaises(ProtectedError):
            category.delete()
        self.assertTrue(CategoriaInsumo.objects.filter(pk=category.pk).exists())
        self.assertEqual(Insumo.objects.get(pk=supply.pk).categoria_id, category.pk)

    def test_history_keeps_category_references_on_change(self):
        first = CategoriaInsumo.objects.get(nombre='Limpieza')
        second = CategoriaInsumo.objects.create(nombre='Material especial')
        supply = Insumo.objects.create(nombre_insumo='Material', unidad_medida='pieza', categoria=first)
        previous = supply.history.get()
        supply.categoria = second
        supply.save()
        self.assertEqual(supply.history.count(), 2)
        previous.refresh_from_db()
        self.assertEqual(previous.categoria_id, first.pk)
        self.assertEqual(previous.instance.categoria_id, first.pk)
        self.assertEqual(supply.history.exclude(pk=previous.pk).get().categoria_id, second.pk)


class CategoriaInsumoMigrationTests(TransactionTestCase):
    previous = [('inicio', '0009_depurar_campos_bitacorafalla')]

    def test_conversion_preserves_supplies_and_all_historical_snapshots(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate(self.previous)
        try:
            old_apps = executor.loader.project_state(self.previous).apps
            Supply = old_apps.get_model('inicio', 'Insumo')
            History = old_apps.get_model('inicio', 'HistoricalInsumo')
            user = old_apps.get_model('inicio', 'UsuarioSistema').objects.create(username='operadoranterior', password='!')
            stamp = timezone.now().replace(second=37, microsecond=654321)
            for name in ('Limpieza', 'Papelería', 'Consumibles'):
                supply = Supply.objects.create(
                    nombre_insumo=f'Material {name}', categoria=name, unidad_medida='litro',
                    existencia_actual=Decimal('1.250'), stock_minimo=Decimal('0.500'),
                )
                History.objects.create(
                    **{field.attname: getattr(supply, field.attname) for field in Supply._meta.fields},
                    history_date=stamp, history_user_id=user.pk, history_type='+',
                    history_change_reason='Carga anterior',
                )
            # Fotografías con una categoría anterior distinta y de un insumo borrado.
            source = Supply.objects.get(categoria='Limpieza')
            attrs = {field.attname: getattr(source, field.attname) for field in Supply._meta.fields}
            attrs['categoria'] = 'Consumibles'
            History.objects.create(**attrs, history_date=stamp, history_user_id=user.pk, history_type='~')
            attrs.update(id_insumo=999, nombre_insumo='Insumo eliminado', categoria='Papelería')
            History.objects.create(**attrs, history_date=stamp, history_user_id=user.pk, history_type='-')
            before = list(Supply.objects.order_by('pk').values())
            snapshots = list(History.objects.order_by('pk').values())

            prepared = [('inicio', '0010_crear_categorias_insumo')]
            MigrationExecutor(connection).migrate(prepared)
            prepared_apps = MigrationExecutor(connection).loader.project_state(prepared).apps
            # El mapeo debe consultar identificadores reales, sin asumir 1/2/3.
            prepared_apps.get_model('inicio', 'CategoriaInsumo').objects.create(id=71, nombre='Papelería')
            MigrationExecutor(connection).migrate(latest)

            self.assertEqual(set(CategoriaInsumo.objects.values_list('nombre', flat=True)),
                             {'Limpieza', 'Papelería', 'Consumibles'})
            self.assertEqual(CategoriaInsumo.objects.get(nombre='Papelería').pk, 71)
            self.assertEqual(Insumo.objects.count(), len(before))
            self.assertEqual(Insumo.history.count(), len(snapshots))
            for row in before:
                expected = row.copy()
                expected['categoria_id'] = CategoriaInsumo.objects.get(nombre=expected.pop('categoria')).pk
                self.assertEqual(Insumo.objects.filter(pk=row['id_insumo']).values().get(), expected)
            for row in snapshots:
                expected = row.copy()
                expected['categoria_id'] = CategoriaInsumo.objects.get(nombre=expected.pop('categoria')).pk
                self.assertEqual(Insumo.history.filter(pk=row['history_id']).values().get(), expected)
                historical = Insumo.history.get(pk=row['history_id'])
                self.assertEqual(historical.instance.categoria_id, expected['categoria_id'])
                self.assertEqual(historical.categoria.nombre, row['categoria'])
        finally:
            MigrationExecutor(connection).migrate(latest)

    def test_unknown_historical_text_stops_conversion_without_removing_it(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        prepared = [('inicio', '0010_crear_categorias_insumo')]
        executor.migrate(self.previous)
        MigrationExecutor(connection).migrate(prepared)
        apps = MigrationExecutor(connection).loader.project_state(prepared).apps
        History = apps.get_model('inicio', 'HistoricalInsumo')
        snapshot = History.objects.create(
            id_insumo=999, nombre_insumo='Anterior', categoria='Sin correspondencia', unidad_medida='pieza',
            history_date=timezone.now(), history_type='-',
        )
        try:
            with self.assertRaisesRegex(RuntimeError, 'Sin correspondencia'):
                MigrationExecutor(connection).migrate(latest)
            unchanged = History.objects.get(pk=snapshot.pk)
            self.assertEqual(unchanged.categoria, 'Sin correspondencia')
            self.assertIsNone(unchanged.categoria_relacion_id)
            self.assertFalse(apps.get_model('inicio', 'CategoriaInsumo').objects.exists())
        finally:
            History.objects.filter(pk=snapshot.pk).delete()
            MigrationExecutor(connection).migrate(latest)
