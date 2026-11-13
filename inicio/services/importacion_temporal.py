"""Excel temporal privado; confirmación firmada, ligada a usuario y sesión."""

import hashlib
from pathlib import Path
import re
import secrets
import time

from django.conf import settings
from django.core import signing
from django.utils.crypto import constant_time_compare

from .importacion_excel import ExcelError


MAX_AGE = 15 * 60
SALT = 'inicio.importacion_excel.v1'


def directory():
    path = Path(getattr(settings, 'EXCEL_IMPORT_TEMP_DIR', settings.BASE_DIR / '.importaciones'))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def session_digest(request):
    return hashlib.sha256((request.session.session_key or '').encode()).hexdigest()


def cleanup():
    # No se recorren otras carpetas ni se eliminan archivos en procesamiento.
    for path in directory().glob('*.xlsx'):
        if re.fullmatch(r'[a-f0-9]{64}\.xlsx', path.name):
            try:
                if path.stat().st_mtime < time.time() - MAX_AGE:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass


def store(data, request):
    cleanup()
    key = secrets.token_hex(32)
    path = directory() / f'{key}.xlsx'
    with path.open('xb') as file:
        file.write(data)
    return signing.dumps({
        'key': key, 'user': request.user.pk, 'session': session_digest(request),
        'sha256': hashlib.sha256(data).hexdigest(),
    }, salt=SALT)


def consume(token, request):
    try:
        payload = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature as exc:
        raise ExcelError('La vista previa venció o la confirmación no es válida. Carga de nuevo el archivo.') from exc
    if not isinstance(payload, dict) or payload.get('user') != request.user.pk or not constant_time_compare(payload.get('session', ''), session_digest(request)):
        raise ExcelError('Esta vista previa pertenece a otro usuario o sesión.')
    key = payload.get('key', '')
    if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}', key):
        raise ExcelError('La confirmación no es válida.')
    path = directory() / f'{key}.xlsx'
    claimed = directory() / f'{key}.processing'
    try:
        # Renombrar consume el archivo de forma atómica: solo una petición gana.
        path.rename(claimed)
    except FileNotFoundError as exc:
        raise ExcelError('Esta importación ya fue confirmada o venció. Carga de nuevo el archivo.') from exc
    try:
        data = claimed.read_bytes()
        if not constant_time_compare(hashlib.sha256(data).hexdigest(), payload.get('sha256', '')):
            raise ExcelError('El archivo cambió desde la vista previa. Cárgalo de nuevo.')
        return data
    finally:
        claimed.unlink(missing_ok=True)
