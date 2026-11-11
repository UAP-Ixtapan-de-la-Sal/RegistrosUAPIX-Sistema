"""Crear exclusivamente una base MariaDB local nueva, nunca reutilizarla."""

import re

import MySQLdb
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Crea una base local NUEVA usando --settings=config.settings_integracion.'
    requires_system_checks = []

    def handle(self, *args, **options):
        database = settings.DATABASES['default']
        name = database['NAME']
        if not getattr(settings, 'UAPIX_ISOLATED_DATABASE', False):
            raise CommandError('Usa --settings=config.settings_integracion y define UAPIX_INTEGRATION_DB.')
        if database['ENGINE'] != 'django.db.backends.mysql' or database.get('HOST') not in ('localhost', '127.0.0.1', '::1'):
            raise CommandError('Solo se permite MariaDB local en loopback.')
        if not re.fullmatch(r'uapix_importacion_[a-f0-9]{12}', name):
            raise CommandError('Nombre de base aislada no válido.')
        try:
            connection = MySQLdb.connect(
                host=database['HOST'], port=int(database.get('PORT') or 3306),
                user=database.get('USER') or '', password=database.get('PASSWORD') or '',
                connect_timeout=5, charset='utf8mb4',
            )
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s', [name])
                    if cursor.fetchone():
                        raise CommandError('La base indicada ya existe. No se modificó; elige otro nombre nuevo.')
                    # El identificador pasó una lista estricta de caracteres. No
                    # hay DROP, TRUNCATE, IF NOT EXISTS ni selección de otra base.
                    cursor.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
            finally:
                connection.close()
        except MySQLdb.Error as exc:
            raise CommandError(f'No se pudo crear la base local nueva (código {exc.args[0]}). Revisa servicio y permisos de creación.') from exc
        self.stdout.write(self.style.SUCCESS(f'Base local nueva creada, sin tablas: {name}'))
