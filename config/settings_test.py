r"""Pruebas locales aisladas: jamás conectan a la base institucional.

Ejecutar: .\.venv\Scripts\python.exe manage.py test --settings=config.settings_test
"""

from .settings import *  # noqa: F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
        'TEST': {'NAME': ':memory:'},
    },
}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
