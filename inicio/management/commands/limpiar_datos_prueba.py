"""Limpieza local, explícita y transaccional; nunca equivale a un flush."""

import os
import sys

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections, models, transaction
from django.db.migrations.recorder import MigrationRecorder


# Lista revisada contra models.py. Un modelo nuevo requiere revisar este comando.
# Los hijos se borran antes que los padres, también para CASCADE y SET_NULL,
# evitando actualizaciones colaterales y respetando las relaciones PROTECT.
ORDEN_OPERATIVOS = (
    'Asistencia', 'DetallePrestamo', 'MovimientoInventario', 'BitacoraFalla',
    'Registro', 'EventoTallerConferencia', 'Prestamo', 'Clase', 'PersonaPerfil',
    'Persona', 'Materia', 'Grupo', 'Equipo', 'Externo',
    'ImplementoTecnologico', 'Insumo', 'CategoriaInsumo', 'Carrera',
)
AUDITADOS = (
    'PersonaPerfil', 'EventoTallerConferencia', 'Equipo', 'Registro',
    'Asistencia', 'ImplementoTecnologico', 'Prestamo', 'DetallePrestamo',
    'Insumo', 'MovimientoInventario', 'BitacoraFalla',
)
PROTEGIDOS = (
    'inicio.UsuarioSistema', 'inicio.UsuarioSistema_groups',
    'inicio.UsuarioSistema_user_permissions', 'auth.Group',
    'auth.Group_permissions', 'auth.Permission', 'contenttypes.ContentType',
    'admin.LogEntry', 'sessions.Session',
)


def relacion(destino, politica):
    return (f'inicio.{destino}', politica)


CASCADE, PROTECT, SET_NULL = models.CASCADE, models.PROTECT, models.SET_NULL
RELACIONES = {
    'Persona': {'grupo': relacion('Grupo', SET_NULL), 'carrera': relacion('Carrera', SET_NULL)},
    'PersonaPerfil': {'persona': relacion('Persona', CASCADE)},
    'Materia': {'carrera': relacion('Carrera', CASCADE)},
    'Grupo': {'carrera': relacion('Carrera', CASCADE)},
    'Clase': {name: relacion(target, CASCADE) for name, target in (
        ('materia', 'Materia'), ('grupo', 'Grupo'), ('docente', 'Persona'),
    )},
    'EventoTallerConferencia': {
        'clase': relacion('Clase', SET_NULL),
        'ponente_interno': relacion('Persona', CASCADE),
        'ponente_externo': relacion('Externo', CASCADE),
    },
    'Registro': {
        'persona': relacion('Persona', CASCADE), 'externo': relacion('Externo', PROTECT),
        'equipo': relacion('Equipo', SET_NULL), 'clase': relacion('Clase', SET_NULL),
        'evento': relacion('EventoTallerConferencia', SET_NULL),
        'registrado_por': relacion('UsuarioSistema', SET_NULL),
    },
    'Asistencia': {
        'clase': relacion('Clase', CASCADE), 'alumno': relacion('Persona', CASCADE),
        'equipo': relacion('Equipo', SET_NULL), 'registro': relacion('Registro', PROTECT),
    },
    'Prestamo': {
        'persona_solicitante': relacion('Persona', PROTECT),
        'operador_prestamo': relacion('UsuarioSistema', PROTECT),
    },
    'DetallePrestamo': {name: relacion(target, PROTECT) for name, target in (
        ('prestamo', 'Prestamo'), ('implemento', 'ImplementoTecnologico'),
        ('persona_devuelve', 'Persona'), ('operador_devolucion', 'UsuarioSistema'),
    )},
    'Insumo': {'categoria': relacion('CategoriaInsumo', PROTECT)},
    'MovimientoInventario': {
        'insumo': relacion('Insumo', PROTECT), 'persona': relacion('Persona', PROTECT),
        'operador': relacion('UsuarioSistema', PROTECT),
    },
    'BitacoraFalla': {
        'equipo': relacion('Equipo', PROTECT), 'implemento': relacion('ImplementoTecnologico', PROTECT),
        'usuario_sistema': relacion('UsuarioSistema', PROTECT),
    },
}
RELACIONES_PROTEGIDAS = {
    'inicio.UsuarioSistema_groups': {
        'usuariosistema': relacion('UsuarioSistema', CASCADE), 'group': ('auth.Group', CASCADE),
    },
    'inicio.UsuarioSistema_user_permissions': {
        'usuariosistema': relacion('UsuarioSistema', CASCADE), 'permission': ('auth.Permission', CASCADE),
    },
    'auth.Group_permissions': {'group': ('auth.Group', CASCADE), 'permission': ('auth.Permission', CASCADE)},
    'auth.Permission': {'content_type': ('contenttypes.ContentType', CASCADE)},
    'admin.LogEntry': {
        'user': relacion('UsuarioSistema', CASCADE), 'content_type': ('contenttypes.ContentType', SET_NULL),
    },
}


class Command(BaseCommand):
    help = 'Elimina TODOS los datos operativos locales y su historial, conservando cuentas y permisos.'
    # Los bloqueos deben ocurrir antes de cualquier comprobación que abra la BD.
    requires_system_checks = []

    def add_arguments(self, parser):
        modo = parser.add_mutually_exclusive_group(required=True)
        modo.add_argument('--dry-run', action='store_true', help='Solo muestra cantidades; no escribe en la BD.')
        modo.add_argument('--confirmar', action='store_true', help='Solicita el nombre de la BD en una terminal interactiva.')

    def handle(self, *args, **options):
        self.alias = DEFAULT_DB_ALIAS
        self.connection = connections[self.alias]
        nombre = self.validar_entorno()
        operativos, historicos, protegidos = self.validar_modelos()
        self.validar_esquema((*operativos, *historicos, *protegidos))
        cantidades = self.contar((*operativos, *historicos))
        self.mostrar_plan(nombre, operativos, historicos, cantidades)
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS('Simulación terminada: no se modificó ningún registro.'))
            return

        if not sys.stdin.isatty():
            raise CommandError('El borrado requiere una terminal interactiva; no se permite entrada redirigida.')
        self.stdout.write(self.style.WARNING(
            'Se eliminarán TODOS los registros operativos, incluso catálogos e historiales. '
            'Detén el servidor y cualquier proceso que escriba en esta base.'
        ))
        try:
            respuesta = input(f'Escribe exactamente el nombre de la base de datos ({nombre}): ')
        except (EOFError, KeyboardInterrupt) as exc:
            raise CommandError('Limpieza cancelada sin cambios.') from exc
        if respuesta != nombre:
            raise CommandError('El nombre no coincide. Limpieza cancelada sin cambios.')

        try:
            with transaction.atomic(using=self.alias):
                # Revalidar tras la espera de la confirmación humana.
                if self.validar_entorno() != nombre:
                    raise CommandError('Cambió la base de datos durante la confirmación.')
                self.validar_modelos()
                self.validar_esquema((*operativos, *historicos, *protegidos))
                if self.contar((*operativos, *historicos)) != cantidades:
                    raise CommandError('Los datos cambiaron durante la confirmación. Repite la simulación.')
                antes = self.snapshot(protegidos, bloquear=True)
                eliminados = 0
                for modelo in operativos:
                    eliminados += self.borrar_modelo(modelo)
                # post_delete de simple-history crea entradas '-': borrar el
                # historial DESPUÉS de los objetos, incluidos historiales huérfanos.
                historiales_eliminados = 0
                for modelo in historicos:
                    historiales_eliminados += self.borrar_modelo(modelo)
                if any(self.contar((*operativos, *historicos)).values()):
                    raise CommandError('Quedan datos operativos o históricos; se revierte la limpieza.')
                if self.snapshot(protegidos) != antes:
                    raise CommandError('Cambió información protegida; se revierte la limpieza.')
        except Exception as exc:
            raise CommandError(f'Limpieza revertida por completo: {exc}') from exc

        self.stdout.write(self.style.SUCCESS(
            f'Limpieza completada: {eliminados} registros operativos y '
            f'{historiales_eliminados} históricos eliminados (incluye los generados al borrar). '
            'No quedan registros operativos ni históricos. '
            'Todas las cuentas, contraseñas, roles, módulos, permisos y tablas internas permanecen intactos.'
        ))

    def validar_entorno(self):
        if not settings.DEBUG:
            raise CommandError('Limpieza bloqueada: requiere DEBUG=True en desarrollo local.')
        if os.environ.get('UAPIX_PERMITIR_LIMPIEZA_PRUEBA') != '1':
            raise CommandError('Limpieza bloqueada: exige UAPIX_PERMITIR_LIMPIEZA_PRUEBA=1.')
        nombre = str(self.connection.settings_dict.get('NAME') or '')
        permitidas = {
            item.strip() for item in os.environ.get('UAPIX_BD_PRUEBA_PERMITIDAS', '').split(',')
            if item.strip()
        }
        if not nombre or nombre not in permitidas:
            raise CommandError('Limpieza bloqueada: NAME no está en UAPIX_BD_PRUEBA_PERMITIDAS.')
        if settings.DATABASE_ROUTERS:
            raise CommandError('Limpieza bloqueada: los routers de base de datos no están contemplados.')
        config = self.connection.settings_dict
        if config['ENGINE'] == 'django.db.backends.mysql':
            if config.get('HOST', '') not in ('', 'localhost', '127.0.0.1', '::1'):
                raise CommandError('Limpieza bloqueada: solo se permiten servidores locales.')
            # Evita conexiones alternativas mediante un archivo de opciones o
            # parámetros del driver que podrían sustituir HOST/NAME.
            if set(config.get('OPTIONS', {})) - {'charset', 'use_unicode'}:
                raise CommandError('Limpieza bloqueada: OPTIONS de MySQL no contempladas.')
        elif config['ENGINE'] == 'django.db.backends.sqlite3':
            if set(config.get('OPTIONS', {})) - {'timeout', 'transaction_mode'}:
                raise CommandError('Limpieza bloqueada: OPTIONS de SQLite no contempladas.')
            if nombre.startswith('file:') or nombre.startswith(('\\\\', '//')):
                # Django usa una URI de memoria en su runner aislado de pruebas.
                if not (nombre.startswith('file:memorydb_') and 'mode=memory' in nombre):
                    raise CommandError('Limpieza bloqueada: SQLite requiere un archivo local o memoria.')
        else:
            raise CommandError('Limpieza bloqueada: motor no contemplado (solo MariaDB/MySQL y SQLite).')
        if not self.connection.features.supports_transactions:
            raise CommandError('Limpieza bloqueada: el motor no permite reversión transaccional.')
        return nombre

    def validar_modelos(self):
        operativos = tuple(apps.get_model('inicio', name) for name in ORDEN_OPERATIVOS)
        historicos = tuple(apps.get_model('inicio', f'Historical{name}') for name in AUDITADOS)
        protegidos = tuple(apps.get_model(label) for label in PROTEGIDOS)
        conocidos = set((*operativos, *historicos, *protegidos))
        actuales = set(apps.get_models(include_auto_created=True))
        if actuales != conocidos:
            diferencia = sorted(m._meta.label for m in actuales ^ conocidos)
            raise CommandError(f'Modelos no contemplados o ausentes: {", ".join(diferencia)}.')
        if apps.get_model(settings.AUTH_USER_MODEL) not in protegidos:
            raise CommandError('El modelo de autenticación no está protegido.')

        for modelo in conocidos:
            esperadas = RELACIONES.get(modelo.__name__, {}) if modelo in operativos else None
            if modelo in protegidos:
                esperadas = RELACIONES_PROTEGIDAS.get(modelo._meta.label, {})
            if modelo in historicos:
                base = modelo.__name__.removeprefix('Historical')
                esperadas = {
                    name: (target, models.DO_NOTHING)
                    for name, (target, _) in RELACIONES.get(base, {}).items()
                }
                esperadas['history_user'] = relacion('UsuarioSistema', SET_NULL)
                if base == 'BitacoraFalla':
                    esperadas['registro'] = relacion('Registro', models.DO_NOTHING)
                if apps.get_model('inicio', base).history.model is not modelo:
                    raise CommandError('Cambió la configuración de simple-history.')
            actuales_fk = {}
            for campo in modelo._meta.local_fields:
                if not campo.is_relation:
                    continue
                destino = campo.remote_field.model
                if destino not in conocidos:
                    raise CommandError(f'Dependencia desconocida en {modelo._meta.label}.{campo.name}.')
                if modelo in protegidos and destino not in protegidos:
                    raise CommandError(f'Una tabla protegida depende de datos operativos: {modelo._meta.label}.')
                actuales_fk[campo.name] = (destino._meta.label, campo.remote_field.on_delete)
            if esperadas is not None and actuales_fk != esperadas:
                raise CommandError(f'Relaciones no contempladas en {modelo._meta.label}.')
            if modelo._meta.private_fields or modelo._meta.parents:
                raise CommandError(f'Herencia o relación genérica no contemplada en {modelo._meta.label}.')
            for campo in modelo._meta.local_many_to_many:
                if campo.remote_field.through not in protegidos or modelo not in protegidos:
                    raise CommandError(f'Relación M2M no contemplada en {modelo._meta.label}.')

        posiciones = {modelo._meta.label: i for i, modelo in enumerate(operativos)}
        for modelo in operativos:
            for destino, _ in RELACIONES.get(modelo.__name__, {}).values():
                if destino in posiciones and posiciones[modelo._meta.label] >= posiciones[destino]:
                    raise CommandError('El orden de borrado no respeta las dependencias.')
        return operativos, historicos, protegidos

    def validar_esquema(self, modelos):
        modelos = (*modelos, MigrationRecorder.Migration)
        # MariaDB en Windows suele guardar bitacoraFalla como bitacorafalla.
        # Respetar la sensibilidad a mayúsculas declarada por el servidor.
        normalizar = str.casefold if self.connection.features.ignores_table_name_case else lambda name: name
        tablas = {normalizar(modelo._meta.db_table) for modelo in modelos}
        if len(tablas) != len(modelos):
            raise CommandError('Varios modelos comparten una tabla; se cancela la limpieza.')
        with self.connection.cursor() as cursor:
            existentes = {normalizar(tabla) for tabla in self.connection.introspection.table_names(cursor, include_views=True)}
            if existentes != tablas:
                raise CommandError('Tablas no contempladas o ausentes: ' + ', '.join(sorted(existentes ^ tablas)))
            for modelo in modelos:
                esperadas = {
                    (campo.column, normalizar(campo.target_field.model._meta.db_table), campo.target_field.column)
                    for campo in modelo._meta.local_fields
                    if campo.is_relation and campo.db_constraint
                }
                # get_relations consulta directamente las FK; no necesita
                # analizar expresiones CHECK de precisión de minutos.
                relaciones = self.connection.introspection.get_relations(cursor, modelo._meta.db_table)
                actuales = {
                    (columna, normalizar(datos[1]), datos[0])
                    for columna, datos in relaciones.items()
                }
                if actuales != esperadas:
                    raise CommandError(f'Claves foráneas no contempladas en {modelo._meta.db_table}.')
                if any(len(datos) > 2 and datos[2] not in (None, models.DO_NOTHING) for datos in relaciones.values()):
                    raise CommandError(f'Acción de borrado SQL no contemplada en {modelo._meta.db_table}.')
            if self.connection.vendor == 'mysql':
                # Solo lectura de metadatos: ningún SQL destructivo.
                cursor.execute('SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()')
                no_transaccionales = [tabla for tabla, motor in cursor.fetchall() if normalizar(tabla) in tablas and motor != 'InnoDB']
                if no_transaccionales:
                    raise CommandError('Tablas sin reversión garantizada (requieren InnoDB): ' + ', '.join(no_transaccionales))
                cursor.execute(
                    'SELECT TABLE_NAME FROM information_schema.KEY_COLUMN_USAGE '
                    'WHERE (TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_SCHEMA <> DATABASE()) '
                    'OR (REFERENCED_TABLE_SCHEMA = DATABASE() AND TABLE_SCHEMA <> DATABASE())'
                )
                if cursor.fetchall():
                    raise CommandError('Dependencias entre bases de datos no contempladas.')
                cursor.execute('SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()')
                if cursor.fetchall():
                    raise CommandError('Triggers no contemplados; se cancela la limpieza.')
            elif self.connection.vendor == 'sqlite':
                cursor.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
                if cursor.fetchall():
                    raise CommandError('Triggers no contemplados; se cancela la limpieza.')

    def contar(self, modelos):
        return {modelo._meta.label: modelo._base_manager.using(self.alias).count() for modelo in modelos}

    def mostrar_plan(self, nombre, operativos, historicos, cantidades):
        self.stdout.write(f'Base de datos: {nombre} (alias {self.alias})')
        self.stdout.write('Registros operativos que se eliminarían:')
        for modelo in operativos:
            self.stdout.write(f'  {modelo._meta.label}: {cantidades[modelo._meta.label]}')
        self.stdout.write('Historiales que se eliminarían:')
        for modelo in historicos:
            self.stdout.write(f'  {modelo._meta.label}: {cantidades[modelo._meta.label]}')
        self.stdout.write(f'Total históricos actuales: {sum(cantidades[m._meta.label] for m in historicos)}')
        usuarios = apps.get_model('inicio', 'UsuarioSistema')._base_manager.using(self.alias)
        self.stdout.write(f'Superusuarios que se conservarán: {usuarios.filter(is_superuser=True).count()}')
        self.stdout.write(f'Operadores que se conservarán (sin contar superusuarios): {usuarios.filter(rol="operador", is_superuser=False).count()}')
        self.stdout.write(f'Total de cuentas protegidas: {usuarios.count()}')

    def snapshot(self, protegidos, bloquear=False):
        resultado = {}
        # Incluye asignaciones M2M, sesiones, bitácora administrativa y migraciones.
        for modelo in (*protegidos, MigrationRecorder.Migration):
            qs = modelo._base_manager.using(self.alias).order_by(modelo._meta.pk.name)
            if bloquear:
                qs = qs.select_for_update()
            resultado[modelo._meta.label] = list(qs.values_list())
        return resultado

    def borrar_modelo(self, modelo):
        permitidos = {f'inicio.{name}' for name in ORDEN_OPERATIVOS}
        permitidos.update(f'inicio.Historical{name}' for name in AUDITADOS)
        if modelo._meta.label not in permitidos:
            raise CommandError(f'Intento de borrar un modelo protegido: {modelo._meta.label}.')
        cantidad, detalle = modelo._base_manager.using(self.alias).all().delete()
        if set(detalle) - permitidos:
            raise CommandError('El borrado alcanzó un modelo no autorizado.')
        return cantidad
