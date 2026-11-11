from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, skipUnlessDBFeature

from .models import Carrera, UsuarioSistema
from .services.importacion_excel import confirm
from .test_importacion_excel import workbook


class ExcelMigrationTests(TransactionTestCase):
    def test_upgrade_from_original_schema_keeps_existing_records(self):
        original = [('inicio', '0001_initial')]
        integrated = [('inicio', '0002_integrar_esquema_excel')]
        executor = MigrationExecutor(connection)
        executor.migrate(original)
        try:
            old_apps = executor.loader.project_state(original).apps
            career = old_apps.get_model('inicio', 'Carrera').objects.create(nombre_carrera='Informática')
            group = old_apps.get_model('inicio', 'Grupo').objects.create(nombre_grupo='X1', semestre=2, turno='Matutino', carrera_id=career.pk)
            person = old_apps.get_model('inicio', 'Persona').objects.create(matricula='0001', nombre='Ana', apellidos='Pérez', perfil='Alumno', carrera_id=career.pk)
            subject = old_apps.get_model('inicio', 'Materia').objects.create(nombre_materia='Programación', carrera_id=career.pk)
            executor = MigrationExecutor(connection)
            executor.migrate(integrated)
            apps = executor.loader.project_state(integrated).apps
            new_person = apps.get_model('inicio', 'Persona').objects.get(pk=person.pk)
            new_group = apps.get_model('inicio', 'Grupo').objects.get(pk=group.pk)
            new_subject = apps.get_model('inicio', 'Materia').objects.get(pk=subject.pk)
            self.assertEqual(new_person.matricula, '0001')
            self.assertEqual(new_person.carrera_id, career.pk)
            self.assertIsNone(new_person.grupo_id)
            self.assertIsNone(new_subject.semestre)
            self.assertEqual((new_group.semestre, new_group.turno), (2, 'Matutino'))
        finally:
            MigrationExecutor(connection).migrate(integrated)


class ConcurrentExcelTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_simultaneous_confirmations_do_not_duplicate_nonunique_catalog_names(self):
        user = UsuarioSistema.objects.create_superuser(username='concurrente', password='prueba')
        data = workbook({'Carreras': [['Carrera'], ['Informática']]})
        barrier = Barrier(2, timeout=15)

        def import_file():
            try:
                local_user = UsuarioSistema.objects.get(pk=user.pk)
                barrier.wait()
                return sum(sheet.new for sheet in confirm(data, local_user).sheets)
            finally:
                connections['default'].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(import_file) for _ in range(2)]
            results = [job.result(timeout=30) for job in jobs]
        self.assertEqual(sorted(results), [0, 1])
        self.assertEqual(Carrera.objects.count(), 1)
