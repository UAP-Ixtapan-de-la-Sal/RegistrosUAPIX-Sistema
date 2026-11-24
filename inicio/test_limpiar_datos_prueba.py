"""Pruebas del borrado: ejecutar únicamente con config.settings_test (SQLite en memoria)."""

import os
from datetime import time, timedelta
from io import StringIO
from unittest.mock import patch

from django.apps import apps
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, models
from django.db.models.signals import post_delete
from django.test import TestCase, override_settings
from django.test.utils import isolate_apps
from django.utils import timezone

from . import models as m
from .management.commands.limpiar_datos_prueba import (
    AUDITADOS, ORDEN_OPERATIVOS, PROTEGIDOS, Command,
)


@override_settings(DEBUG=True)
class LimpiarDatosPruebaTests(TestCase):
    @classmethod
    def setUpClass(cls):
        nombre = str(connection.settings_dict['NAME'])
        if connection.vendor != 'sqlite' or not (
            nombre == ':memory:' or (nombre.startswith('file:memorydb_') and 'mode=memory' in nombre)
        ):
            raise RuntimeError('Estas pruebas requieren SQLite en memoria: --settings=config.settings_test')
        super().setUpClass()

    def setUp(self):
        self.nombre = str(connection.settings_dict['NAME'])
        self.env = patch.dict(os.environ, {
            'UAPIX_PERMITIR_LIMPIEZA_PRUEBA': '1',
            'UAPIX_BD_PRUEBA_PERMITIDAS': self.nombre,
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.admin = m.UsuarioSistema.objects.create_superuser('adminlimpieza', password='clave-original')
        self.operador = m.UsuarioSistema.objects.create_user(
            'operadorlimpieza', password='clave-operador', rol='operador',
            is_staff=True, mod_sala_computo=True, mod_auto_acceso=True,
            mod_biblioteca=True, mod_prestamos=True, mod_insumos=True, mod_tecnologicos=True,
        )
        self.visualizador = m.UsuarioSistema.objects.create_user('lectorlimpieza', password='clave-lector')
        self.grupo_auth = Group.objects.create(name='Operadores de prueba')
        permiso = Permission.objects.get(content_type__app_label='inicio', codename='view_persona')
        self.grupo_auth.permissions.add(permiso)
        self.operador.groups.add(self.grupo_auth)
        self.operador.user_permissions.add(Permission.objects.get(
            content_type__app_label='inicio', codename='add_persona',
        ))
        self.crear_operativos()
        LogEntry.objects.log_actions(
            user_id=self.operador.pk, queryset=m.Persona.objects.filter(pk=self.persona.pk),
            action_flag=ADDITION,
        )
        # Una sesión válida debe seguir sirviendo tras la limpieza.
        self.client.login(username='operadorlimpieza', password='clave-operador')
        self.session_key = self.client.session.session_key

    def crear_operativos(self):
        fecha = timezone.localdate() + timedelta(days=2)
        inicio = timezone.now().replace(second=0, microsecond=0)
        carrera = m.Carrera.objects.create(nombre_carrera='Sistemas de prueba')
        grupo = m.Grupo.objects.create(nombre_grupo='101', carrera=carrera)
        materia = m.Materia.objects.create(nombre_materia='Programación', carrera=carrera)
        docente = m.Persona.objects.create(nombre='Docente', apellidos='Prueba', perfil='Docente')
        self.persona = m.Persona.objects.create(
            nombre='Alumno', apellidos='Prueba', perfil='Alumno', carrera=carrera, grupo=grupo,
        )
        membresia = m.PersonaPerfil(persona=self.persona, perfil='Docente')
        membresia._history_user = self.operador
        membresia.save()
        externo = m.Externo.objects.create(nombre='Externo', apellidos='Prueba')
        clase = m.Clase.objects.create(
            materia=materia, grupo=grupo, docente=docente, fecha=fecha,
            hora_inicio=time(9), hora_fin=time(10),
        )
        evento = m.EventoTallerConferencia.objects.create(
            nombre_evento='Taller de prueba', clase=clase, tipo_ponente='Externo',
            ponente_externo=externo, fecha=fecha, hora_inicio=time(10), hora_fin=time(11),
        )
        for modulo, lugar in (
            ('Sala_Computo', 'Sala'), ('Auto_Acceso', 'Auto Acceso'), ('Biblioteca', 'Biblioteca'),
        ):
            equipo = m.Equipo.objects.create(no_equipo=modulo, lugar=lugar)
            registro = m.Registro.objects.create(
                modulo=modulo, persona=self.persona, equipo=equipo,
                clase=clase, evento=evento, registrado_por=self.operador,
                fecha=fecha, hora_entrada=time(9), hora_salida=time(10),
            )
            if modulo == 'Sala_Computo':
                m.Asistencia.objects.create(
                    clase=clase, alumno=self.persona, estado='Asistió', equipo=equipo, registro=registro,
                )
        m.Registro.objects.create(externo=externo, fecha=fecha, hora_entrada=time(11))
        implemento = m.ImplementoTecnologico.objects.create(
            codigo_interno='TEC-PRUEBA', tipo_implemento='Proyector',
            estado='Disponible', condicion='Bueno',
        )
        prestamo = m.Prestamo.objects.create(
            persona_solicitante=self.persona, operador_prestamo=self.operador,
            fecha_hora_prestamo=inicio, fecha_hora_devolucion_prevista=inicio + timedelta(hours=2),
            lugar_destino='Aula 1', uso_prestamo='Prueba',
        )
        m.DetallePrestamo.objects.create(
            prestamo=prestamo, implemento=implemento, condicion_salida='Bueno',
            fecha_hora_devolucion=inicio + timedelta(hours=1), persona_devuelve=self.persona,
            operador_devolucion=self.operador, condicion_devolucion='Bueno',
        )
        categoria = m.CategoriaInsumo.objects.create(nombre='Categoría de prueba')
        insumo = m.Insumo.objects.create(nombre_insumo='Papel', categoria=categoria, unidad_medida='pieza')
        m.MovimientoInventario.objects.create(
            insumo=insumo, tipo_movimiento='Salida', cantidad=1, fecha=fecha, hora=time(9),
            persona=self.persona, operador=self.operador,
        )
        for objeto in ({'equipo': equipo}, {'implemento': implemento}):
            falla = m.BitacoraFalla(usuario_sistema=self.operador, descripcion_falla='Prueba', **objeto)
            falla._history_user = self.operador
            falla.save()
        # Historial huérfano, anterior a ejecutar el comando.
        equipo_huerfano = m.Equipo.objects.create(no_equipo='BORRADO', lugar='Sala')
        equipo_huerfano.delete()

    def ejecutar(self, modo='--confirmar', respuesta=None, interactiva=True):
        salida = StringIO()
        with patch('sys.stdin.isatty', return_value=interactiva), patch(
            'builtins.input', return_value=self.nombre if respuesta is None else respuesta,
        ):
            call_command('limpiar_datos_prueba', modo, stdout=salida)
        return salida.getvalue()

    def snapshot(self):
        comando = Command()
        comando.alias = 'default'
        return comando.snapshot(tuple(apps.get_model(label) for label in PROTEGIDOS))

    def conteos(self):
        nombres = (*ORDEN_OPERATIVOS, *(f'Historical{name}' for name in AUDITADOS))
        return {name: apps.get_model('inicio', name).objects.count() for name in nombres}

    def test_limpieza_completa_y_conservacion_exacta_de_cuentas_y_tablas_internas(self):
        antes = self.snapshot()
        conteos = self.conteos()
        self.assertTrue(all(conteos.values()), conteos)
        borrados_auditados = sum(apps.get_model('inicio', name).objects.count() for name in AUDITADOS)
        total_historicos = sum(conteos[f'Historical{name}'] for name in AUDITADOS)
        salida = self.ejecutar()
        self.assertFalse(any(self.conteos().values()))
        self.assertEqual(self.snapshot(), antes)
        self.assertIn(f'{total_historicos + borrados_auditados} históricos eliminados', salida)
        self.assertIn('Superusuarios que se conservarán: 1', salida)
        self.assertIn('Operadores que se conservarán (sin contar superusuarios): 1', salida)
        self.assertIn('Total de cuentas protegidas: 3', salida)
        self.assertIn('permanecen intactos', salida)

    def test_autenticacion_permisos_y_sesion_siguen_funcionando(self):
        permisos = self.operador.get_all_permissions()
        self.ejecutar()
        for nombre, clave in (
            ('adminlimpieza', 'clave-original'), ('operadorlimpieza', 'clave-operador'),
            ('lectorlimpieza', 'clave-lector'),
        ):
            usuario = authenticate(username=nombre, password=clave)
            self.assertIsNotNone(usuario)
            self.assertTrue(usuario.check_password(clave))
        operador = m.UsuarioSistema.objects.get(pk=self.operador.pk)
        self.assertEqual(operador.get_all_permissions(), permisos)
        self.assertEqual(list(operador.groups.values_list('pk', flat=True)), [self.grupo_auth.pk])
        self.assertTrue(operador.mod_sala_computo and operador.mod_prestamos)
        self.assertEqual(operador.rol, 'operador')
        sesion = Session.objects.get(session_key=self.session_key)
        self.assertEqual(sesion.get_decoded()['_auth_user_id'], str(operador.pk))
        self.assertTrue(self.client.get('/admin/').wsgi_request.user.is_authenticated)

    def test_dry_run_no_escribe_ni_pide_confirmacion(self):
        antes, conteos = self.snapshot(), self.conteos()
        salida = StringIO()
        with patch('builtins.input', side_effect=AssertionError('No debe pedir confirmación')):
            call_command('limpiar_datos_prueba', '--dry-run', stdout=salida)
        salida = salida.getvalue()
        self.assertEqual(self.snapshot(), antes)
        self.assertEqual(self.conteos(), conteos)
        self.assertIn(f'Base de datos: {self.nombre}', salida)
        for nombre in (*ORDEN_OPERATIVOS, *(f'Historical{name}' for name in AUDITADOS)):
            self.assertIn(f'inicio.{nombre}: {conteos[nombre]}', salida)
        self.assertIn('no se modificó ningún registro', salida)

    def test_error_despues_de_borrado_revierte_incluso_historial_generado(self):
        antes, conteos = self.snapshot(), self.conteos()
        original = Command.borrar_modelo

        def fallar(comando, modelo):
            resultado = original(comando, modelo)
            if modelo is m.Prestamo:
                raise RuntimeError('fallo simulado después de borrar préstamos')
            return resultado

        with patch.object(Command, 'borrar_modelo', new=fallar):
            with self.assertRaisesMessage(CommandError, 'revertida por completo'):
                self.ejecutar()
        self.assertEqual(self.conteos(), conteos)
        self.assertEqual(self.snapshot(), antes)

    def test_error_al_final_de_los_historiales_revierte_todo(self):
        conteos = self.conteos()
        original = Command.borrar_modelo

        def fallar(comando, modelo):
            original(comando, modelo)
            if modelo is m.BitacoraFalla.history.model:
                raise RuntimeError('fallo al terminar historiales')
            return 0

        with patch.object(Command, 'borrar_modelo', new=fallar):
            with self.assertRaisesMessage(CommandError, 'fallo al terminar historiales'):
                self.ejecutar()
        self.assertEqual(self.conteos(), conteos)

    def test_cambio_colateral_a_cuenta_protegida_revierte_todo(self):
        antes, conteos = self.snapshot(), self.conteos()

        def modificar_cuenta(**kwargs):
            m.UsuarioSistema.objects.filter(pk=self.operador.pk).update(rol='visualizador')

        post_delete.connect(modificar_cuenta, sender=m.Asistencia, weak=False)
        try:
            with self.assertRaisesMessage(CommandError, 'Cambió información protegida'):
                self.ejecutar()
        finally:
            post_delete.disconnect(modificar_cuenta, sender=m.Asistencia)
        self.assertEqual(self.snapshot(), antes)
        self.assertEqual(self.conteos(), conteos)

    def test_nunca_se_invoca_borrado_sobre_usuario_sistema(self):
        original = models.QuerySet.delete
        vistos = []

        def observar(qs):
            vistos.append(qs.model)
            self.assertNotEqual(qs.model, m.UsuarioSistema)
            return original(qs)

        with patch.object(models.QuerySet, 'delete', new=observar):
            self.ejecutar()
        self.assertNotIn(m.UsuarioSistema, vistos)
        self.assertEqual(m.UsuarioSistema.objects.count(), 3)
        with self.assertRaisesMessage(CommandError, 'modelo protegido'):
            Command().borrar_modelo(m.UsuarioSistema)

    def test_bloqueos_de_entorno_sin_borrados(self):
        conteos = self.conteos()
        for debug, autorizacion, nombres, mensaje in (
            (False, '1', self.nombre, 'DEBUG=True'),
            (True, '', self.nombre, 'UAPIX_PERMITIR'),
            (True, 'true', self.nombre, 'UAPIX_PERMITIR'),
            (True, '1', '', 'UAPIX_BD_PRUEBA_PERMITIDAS'),
            (True, '1', 'otra_base', 'UAPIX_BD_PRUEBA_PERMITIDAS'),
            (True, '1', self.nombre + '_otro', 'UAPIX_BD_PRUEBA_PERMITIDAS'),
        ):
            with self.subTest(debug=debug, autorizacion=autorizacion, nombres=nombres):
                with override_settings(DEBUG=debug), patch.dict(os.environ, {
                    'UAPIX_PERMITIR_LIMPIEZA_PRUEBA': autorizacion,
                    'UAPIX_BD_PRUEBA_PERMITIDAS': nombres,
                }):
                    with self.assertRaisesMessage(CommandError, mensaje):
                        self.ejecutar('--dry-run')
        self.assertEqual(self.conteos(), conteos)

    def test_servidores_remotos_y_parametros_alternativos_bloqueados_sin_conectar(self):
        comando = Command()
        comando.connection = connection
        for cambios, mensaje in (
            ({'ENGINE': 'django.db.backends.mysql', 'HOST': 'produccion.example'}, 'servidores locales'),
            ({'ENGINE': 'django.db.backends.mysql', 'HOST': '192.168.1.10'}, 'servidores locales'),
            ({'ENGINE': 'django.db.backends.mysql', 'HOST': 'localhost',
              'OPTIONS': {'read_default_file': 'my.cnf'}}, 'OPTIONS'),
            ({'OPTIONS': {'database': 'otra-base'}}, 'OPTIONS'),
            ({'ENGINE': 'otro.motor'}, 'motor no contemplado'),
        ):
            with self.subTest(cambios=cambios), patch.dict(connection.settings_dict, cambios):
                with self.assertRaisesMessage(CommandError, mensaje):
                    comando.validar_entorno()

    def test_sqlite_en_red_o_uri_de_archivo_bloqueados(self):
        comando = Command()
        comando.connection = connection
        for nombre in ('file:datos.sqlite3?mode=rw', '//servidor/base.sqlite3', '\\\\servidor\\base.sqlite3'):
            with self.subTest(nombre=nombre), patch.dict(connection.settings_dict, {'NAME': nombre}), patch.dict(
                os.environ, {'UAPIX_BD_PRUEBA_PERMITIDAS': nombre},
            ):
                with self.assertRaisesMessage(CommandError, 'archivo local o memoria'):
                    comando.validar_entorno()

    def test_motores_sin_transacciones_y_routers_bloqueados(self):
        with patch.object(connection.features, 'supports_transactions', False):
            with self.assertRaisesMessage(CommandError, 'reversión transaccional'):
                self.ejecutar('--dry-run')
        with override_settings(DATABASE_ROUTERS=[object()]):
            with self.assertRaisesMessage(CommandError, 'routers'):
                self.ejecutar('--dry-run')

    def test_borrado_desatendido_y_confirmacion_incorrecta_bloqueados(self):
        conteos = self.conteos()
        with self.assertRaisesMessage(CommandError, 'terminal interactiva'):
            self.ejecutar(interactiva=False)
        for respuesta in ('', 'si', 'otra-base', ' ' + self.nombre):
            with self.subTest(respuesta=respuesta):
                with self.assertRaisesMessage(CommandError, 'nombre no coincide'):
                    self.ejecutar(respuesta=respuesta)
        self.assertEqual(self.conteos(), conteos)

    def test_confirmacion_interrumpida_no_borra(self):
        conteos = self.conteos()
        for error in (EOFError, KeyboardInterrupt):
            with self.subTest(error=error), patch('sys.stdin.isatty', return_value=True), patch(
                'builtins.input', side_effect=error,
            ):
                with self.assertRaisesMessage(CommandError, 'cancelada sin cambios'):
                    call_command('limpiar_datos_prueba', '--confirmar', stdout=StringIO())
        self.assertEqual(self.conteos(), conteos)

    def test_modelo_desconocido_cancela_incluso_sin_registros(self):
        originales = list(apps.get_models(include_auto_created=True))
        with isolate_apps('inicio'):
            class ModeloDesconocido(models.Model):
                persona = models.ForeignKey(m.Persona, on_delete=models.CASCADE)

                class Meta:
                    app_label = 'inicio'

            with patch.object(apps, 'get_models', return_value=[*originales, ModeloDesconocido]):
                with self.assertRaisesMessage(CommandError, 'Modelos no contemplados'):
                    self.ejecutar()
        self.assertTrue(m.Persona.objects.exists())

    def test_politica_fk_modificada_cancela(self):
        campo = m.Prestamo._meta.get_field('persona_solicitante')
        with patch.object(campo.remote_field, 'on_delete', models.CASCADE):
            with self.assertRaisesMessage(CommandError, 'Relaciones no contempladas'):
                self.ejecutar('--dry-run')

    def test_dependencia_de_tabla_protegida_hacia_operativa_cancela(self):
        campo = LogEntry._meta.get_field('user')
        with patch.object(campo.remote_field, 'model', m.Persona):
            with self.assertRaisesMessage(CommandError, 'tabla protegida depende'):
                self.ejecutar('--dry-run')

    def test_tabla_o_fk_desconocidas_cancela_antes_de_borrar(self):
        originales = connection.introspection.table_names
        with patch.object(connection.introspection, 'table_names', side_effect=lambda *a, **kw: [
            *originales(*a, **kw), 'tabla_no_revisada',
        ]):
            with self.assertRaisesMessage(CommandError, 'Tablas no contempladas'):
                self.ejecutar()
        relaciones = connection.introspection.get_relations

        def agregar_fk(cursor, tabla):
            resultado = relaciones(cursor, tabla)
            if tabla == m.Carrera._meta.db_table:
                resultado['fk_desconocida'] = ('id', m.UsuarioSistema._meta.db_table, models.DO_NOTHING)
            return resultado

        with patch.object(connection.introspection, 'get_relations', side_effect=agregar_fk):
            with self.assertRaisesMessage(CommandError, 'Claves foráneas no contempladas'):
                self.ejecutar()
        self.assertTrue(m.Persona.objects.exists())

    def test_tablas_mysql_sin_innodb_bloqueadas(self):
        comando = Command()
        comando.connection = connection
        modelos = tuple(apps.get_model('inicio', name) for name in ORDEN_OPERATIVOS)
        modelos += tuple(apps.get_model('inicio', f'Historical{name}') for name in AUDITADOS)
        modelos += tuple(apps.get_model(label) for label in PROTEGIDOS)
        # Se simula únicamente la lectura de ENGINE; jamás conecta a MariaDB.
        with patch.object(connection, 'vendor', 'mysql'), patch.object(connection, 'cursor') as cursor_mock:
            cursor = cursor_mock.return_value.__enter__.return_value
            cursor.fetchall.return_value = [(m.Persona._meta.db_table, 'MyISAM')]
            with patch.object(connection.introspection, 'table_names', return_value=[
                *(modelo._meta.db_table for modelo in modelos), 'django_migrations',
            ]), patch.object(connection.introspection, 'get_relations', side_effect=lambda c, tabla: {
                campo.column: (campo.target_field.column, campo.target_field.model._meta.db_table, models.DO_NOTHING)
                for modelo in modelos if modelo._meta.db_table == tabla
                for campo in modelo._meta.local_fields if campo.is_relation and campo.db_constraint
            }):
                with self.assertRaisesMessage(CommandError, 'requieren InnoDB'):
                    comando.validar_esquema(modelos)

    def test_si_cambian_datos_mientras_se_confirma_cancela(self):
        def confirmar(prompt):
            m.Carrera.objects.create(nombre_carrera='Dato creado mientras se confirma')
            return self.nombre

        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', side_effect=confirmar):
            with self.assertRaisesMessage(CommandError, 'datos cambiaron'):
                call_command('limpiar_datos_prueba', '--confirmar', stdout=StringIO())
        self.assertTrue(m.Persona.objects.exists())

    def test_metadatos_mysql_innodb_y_dependencias_externas_o_triggers(self):
        comando = Command()
        comando.connection = connection
        operativos, historicos, protegidos = comando.validar_modelos()
        modelos = (*operativos, *historicos, *protegidos)
        # FK obtenidas de la SQLite aislada: solo se simulan los metadatos extra
        # de MariaDB para que estas pruebas nunca abran un servidor real.
        with connection.cursor() as cursor:
            relaciones = {
                modelo._meta.db_table: connection.introspection.get_relations(cursor, modelo._meta.db_table)
                for modelo in modelos
            }
        tablas = [*(modelo._meta.db_table for modelo in modelos), 'django_migrations']
        motores = [(tabla, 'InnoDB') for tabla in tablas]
        for entre_bases, triggers, error in (
            ([], [], None),
            ([('otra_tabla',)], [], 'Dependencias entre bases'),
            ([], [('trigger_no_revisado',)], 'Triggers no contemplados'),
        ):
            with self.subTest(error=error), patch.object(connection, 'vendor', 'mysql'), patch.object(
                connection, 'cursor',
            ) as cursor_mock, patch.object(connection.introspection, 'table_names', return_value=tablas), patch.object(
                connection.introspection, 'get_relations', side_effect=lambda c, tabla: relaciones.get(tabla, {}),
            ):
                cursor_mock.return_value.__enter__.return_value.fetchall.side_effect = [motores, entre_bases, triggers]
                if error:
                    with self.assertRaisesMessage(CommandError, error):
                        comando.validar_esquema(modelos)
                else:
                    comando.validar_esquema(modelos)

    def test_accion_sql_de_cascada_desconocida_cancela(self):
        relaciones = connection.introspection.get_relations

        def cambiar_accion(cursor, tabla):
            resultado = relaciones(cursor, tabla)
            if tabla == LogEntry._meta.db_table:
                columna = LogEntry._meta.get_field('content_type').column
                resultado[columna] = (*resultado[columna][:2], models.DB_CASCADE)
            return resultado

        with patch.object(connection.introspection, 'get_relations', side_effect=cambiar_accion):
            with self.assertRaisesMessage(CommandError, 'Acción de borrado SQL'):
                self.ejecutar('--dry-run')

    def test_nombres_de_tablas_sin_distincion_de_mayusculas(self):
        tablas = connection.introspection.table_names
        relaciones = connection.introspection.get_relations

        def minusculas(cursor, tabla):
            return {
                columna: (datos[0], datos[1].lower(), *datos[2:])
                for columna, datos in relaciones(cursor, tabla).items()
            }

        with patch.object(connection.features, 'ignores_table_name_case', True), patch.object(
            connection.introspection, 'table_names', side_effect=lambda *a, **kw: [
                tabla.lower() for tabla in tablas(*a, **kw)
            ],
        ), patch.object(connection.introspection, 'get_relations', side_effect=minusculas):
            self.ejecutar('--dry-run')

    def test_repetir_limpieza_es_seguro(self):
        self.ejecutar()
        salida = self.ejecutar()
        self.assertIn('0 registros operativos y 0 históricos eliminados', salida)
        self.assertEqual(m.UsuarioSistema.objects.count(), 3)

    def test_argumento_de_modo_obligatorio_y_excluyente(self):
        with self.assertRaises(CommandError):
            call_command('limpiar_datos_prueba', stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('limpiar_datos_prueba', '--dry-run', '--confirmar', stdout=StringIO())
