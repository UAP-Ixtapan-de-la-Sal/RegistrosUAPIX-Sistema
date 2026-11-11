"""MariaDB local aislado para validar las migraciones y el importador.

Exige UAPIX_INTEGRATION_DB=uapix_importacion_<12 caracteres hexadecimales>.
No modifica DATABASE_URL ni permite reutilizar su base de datos.
"""

from copy import deepcopy
import os
import re

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403


integration_database = os.environ.get('UAPIX_INTEGRATION_DB', '')
original_database = deepcopy(DATABASES['default'])  # noqa: F405
if not re.fullmatch(r'uapix_importacion_[a-f0-9]{12}', integration_database):
    raise ImproperlyConfigured('Define UAPIX_INTEGRATION_DB con un nombre nuevo: uapix_importacion_<12 caracteres hexadecimales>.')
if original_database['ENGINE'] != 'django.db.backends.mysql':
    raise ImproperlyConfigured('La integración local requiere el backend MySQL/MariaDB.')
if original_database.get('HOST', '') not in ('localhost', '127.0.0.1', '::1'):
    raise ImproperlyConfigured('Solo se permite un servidor MariaDB local en loopback.')
if original_database['NAME'].casefold() in (integration_database.casefold(), f'test_{integration_database}'.casefold()):
    raise ImproperlyConfigured('La base de integración y su base de pruebas deben diferir de DATABASE_URL.')

DATABASES = {'default': {
    **original_database,
    'NAME': integration_database,
    'TEST': {'NAME': f'test_{integration_database}', 'CHARSET': 'utf8mb4', 'COLLATION': 'utf8mb4_unicode_ci'},
}}
UAPIX_ISOLATED_DATABASE = True
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
