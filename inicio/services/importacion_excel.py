"""Importador Excel con lectura limitada y normalización mediante openpyxl."""

from contextlib import closing
from dataclasses import dataclass, field
from io import BytesIO
import re
import unicodedata
from zipfile import BadZipFile, ZipFile
from xml.etree.ElementTree import ParseError

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from django.core.exceptions import ValidationError
from django.db import transaction

from inicio.models import Carrera, Equipo, Grupo, Materia, Persona, PersonaPerfil


MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_EXPANDED_SIZE = 50 * 1024 * 1024
MAX_ROWS = 20000
MAX_COLUMNS = 64
PREVIEW_LIMIT = 100
COLUMNAS = {
    'Carreras': ['Carrera'],
    'Grupos': ['Grupo', 'Carrera', 'Semestre', 'Turno'],
    'Alumnos': ['Cuenta', 'Nombre', 'Apellido Paterno', 'Apellido Materno', 'Grupo'],
    'Docentes': ['Cuenta', 'Nombre', 'Apellido Paterno', 'Apellido Materno'],
    'Administrativos': ['Cuenta', 'Nombre', 'Apellido Paterno', 'Apellido Materno'],
    'Materias': ['Materia', 'Carrera', 'Semestre'],
    'Equipos': ['No. Equipo', 'No. Bien Patrimonial', 'Lugar'],
}
MODELOS = (Carrera, Grupo, Persona, Materia, Equipo)
IMPORT_PERMISSIONS = tuple(f'inicio.add_{model._meta.model_name}' for model in MODELOS)


def normalize_header(value):
    normalized = unicodedata.normalize('NFKD', str(value))
    without_accents = ''.join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', without_accents.casefold())


def cell_text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        texto = str(int(value))
    else:
        texto = str(value).strip()

    # Conversión global a mayúsculas y sin acentos
    nfkd_form = unicodedata.normalize('NFKD', texto)
    sin_acentos = ''.join(c for c in nfkd_form if not unicodedata.combining(c))
    return sin_acentos.upper()


def equivalent(value):
    """Comparar sin distinguir mayúsculas, acentos ni espacios repetidos."""
    return ' '.join(cell_text(value).split()).casefold()


class ExcelError(ValueError):
    pass


@dataclass
class Sheet:
    name: str
    rows: list = field(default_factory=list)
    new: int = 0
    existing: int = 0
    profiles: int = 0
    relationships: int = 0
    errors: list = field(default_factory=list)
    samples: list = field(default_factory=list)

    @property
    def error_count(self):
        return len({error['row'] for error in self.errors})

    @property
    def valid_count(self):
        return self.new + self.existing


@dataclass
class Plan:
    sheets: list = field(default_factory=list)
    ignored: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    entries: list = field(default_factory=list)
    profile_entries: list = field(default_factory=list)
    relationship_updates: list = field(default_factory=list)

    @property
    def valid(self):
        return bool(self.sheets) and not self.errors and all(not s.errors for s in self.sheets)


def read_workbook(data):
    if not data or len(data) > MAX_FILE_SIZE:
        raise ExcelError('El archivo debe contener datos y pesar como máximo 5 MB.')
    try:
        with ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 5000 or sum(m.file_size for m in members) > MAX_EXPANDED_SIZE:
                raise ExcelError('El Excel excede el límite de contenido descomprimido (50 MB).')
            if any(m.flag_bits & 1 for m in members):
                raise ExcelError('No se admiten archivos cifrados.')
        plan = Plan()
        canonical = {normalize_header(name): name for name in COLUMNAS}
        seen = set()
        total = 0

        with closing(load_workbook(filename=BytesIO(data), data_only=True, read_only=True)) as wb:
            for original_name in wb.sheetnames:
                worksheet = wb[original_name]
                if (worksheet.max_row or 0) > MAX_ROWS + 1:
                    raise ExcelError(f'Hoja "{original_name}": máximo {MAX_ROWS} filas después del encabezado, incluidas las vacías.')
                if (worksheet.max_column or 0) > MAX_COLUMNS:
                    raise ExcelError(f'Hoja "{original_name}": máximo {MAX_COLUMNS} columnas.')

                headers = []
                rows = []
                for number, row_vals in enumerate(worksheet.iter_rows(values_only=True), start=1):
                    if number > MAX_ROWS + 1:
                        raise ExcelError(f'Hoja "{original_name}": máximo {MAX_ROWS} filas después del encabezado, incluidas las vacías.')
                    if len(row_vals) > MAX_COLUMNS:
                        raise ExcelError(f'Hoja "{original_name}": máximo {MAX_COLUMNS} columnas.')
                    if number == 1:
                        headers = [normalize_header(value) for value in row_vals]
                        continue
                    values = [cell_text(value) for value in row_vals]
                    if any(values):
                        total += 1
                        if total > MAX_ROWS:
                            raise ExcelError(f'El archivo supera el máximo de {MAX_ROWS} registros.')
                        rows.append((number, dict(zip(headers, values))))

                # Las hojas sin registros se ignoran antes de validar su nombre y encabezados.
                if not rows:
                    plan.ignored.append(original_name)
                    continue

                name = canonical.get(normalize_header(original_name))
                if name is None:
                    plan.errors.append(f'Hoja "{original_name}": nombre no reconocido.')
                    continue
                if name in seen:
                    plan.errors.append(f'La hoja "{name}" está repetida.')
                    continue
                seen.add(name)

                sheet = Sheet(name=name, rows=rows)
                plan.sheets.append(sheet)

                if len([h for h in headers if h]) != len(set(h for h in headers if h)):
                    sheet.errors.append(dict(row=1, field='Encabezados', message='Hay encabezados repetidos.'))
                missing = [h for h in COLUMNAS[name] if normalize_header(h) not in headers]
                if missing:
                    sheet.errors.append(dict(row=1, field='Encabezados', message='Faltan columnas: ' + ', '.join(missing)))

        if not plan.sheets and not plan.errors:
            plan.errors.append('El archivo no contiene registros para importar.')
        plan.sheets.sort(key=lambda s: list(COLUMNAS).index(s.name))
        return plan
    except ExcelError:
        raise
    except (BadZipFile, ValueError, OSError, KeyError, TypeError, ParseError, InvalidFileException) as exc:
        raise ExcelError('No se pudo leer el archivo. Selecciona un Excel .xlsx válido, sin contraseña.') from exc


class Planner:
    def __init__(self, plan, *, lock=False):
        self.plan = plan
        self.index = {model: {} for model in MODELOS}
        self.profiles = {}
        for model in MODELOS:
            queryset = model.objects.all()
            if lock:
                queryset = queryset.select_for_update()
            if model is Persona:
                queryset = queryset.prefetch_related('perfiles')
            for obj in queryset:
                self.index[model].setdefault(self.identity(obj), []).append(obj)
                if model is Persona:
                    self.profiles[self.identity(obj)] = obj.perfiles_actuales

    @staticmethod
    def identity(obj):
        if isinstance(obj, Carrera):
            return equivalent(obj.nombre_carrera)
        if isinstance(obj, Grupo):
            return equivalent(obj.nombre_grupo)
        if isinstance(obj, Persona):
            return equivalent(obj.matricula or '')
        if isinstance(obj, Materia):
            return (equivalent(obj.nombre_materia), Planner.related_key(obj.carrera), obj.semestre)
        return equivalent(obj.no_bien_patrimonial or '')

    @staticmethod
    def related_key(obj):
        if obj is None:
            return None
        return (type(obj).__name__, obj.pk) if obj.pk is not None else (type(obj).__name__, Planner.identity(obj))

    def reference(self, model, key, label):
        matches = self.index[model].get(equivalent(key), [])
        if not matches:
            raise ValidationError({label: f'"{key}" no existe en el Excel ni en la base de datos.'})
        if len(matches) != 1:
            raise ValidationError({label: f'"{key}" tiene varias coincidencias; se requiere una referencia inequívoca.'})
        return matches[0]

    def values(self, sheet, row):
        def text(label, required=True):
            value = row.get(normalize_header(label), '')
            if required and not value:
                raise ValidationError({label: 'Este campo es obligatorio.'})
            return value

        def semester():
            value = text('Semestre')
            if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 2147483647:
                raise ValidationError({'Semestre': 'Debe ser un número entero positivo.'})
            return int(value)

        if sheet == 'Carreras':
            return Carrera, {'nombre_carrera': text('Carrera')}
        if sheet == 'Grupos':
            return Grupo, dict(
                nombre_grupo=text('Grupo'),
                carrera=self.reference(Carrera, text('Carrera'), 'Carrera'),
                semestre=semester(), turno=text('Turno'),
            )
        if sheet in ('Alumnos', 'Docentes', 'Administrativos'):
            data = dict(
                matricula=text('Cuenta'), nombre=text('Nombre'),
                apellidos=' '.join(filter(None, (text('Apellido Paterno', False), text('Apellido Materno', False)))),
                perfil={'Alumnos': 'Alumno', 'Docentes': 'Docente', 'Administrativos': 'Administrador'}[sheet],
            )
            if sheet == 'Alumnos':
                group = self.reference(Grupo, text('Grupo'), 'Grupo')
                data.update(grupo=group, carrera=group.carrera)
            return Persona, data
        if sheet == 'Materias':
            return Materia, dict(
                nombre_materia=text('Materia'),
                carrera=self.reference(Carrera, text('Carrera'), 'Carrera'), semestre=semester(),
            )

        # Mapeo robusto para los lugares de equipos reconociendo las opciones oficiales del modelo
        places = {
            normalize_header(value): value
            for value, _ in Equipo.LUGAR_CHOICES
        }
        places.update({
            normalize_header(label): value
            for value, label in Equipo.LUGAR_CHOICES
        })
        places.update({
            normalize_header('Sala de Computo'): 'Sala',
            normalize_header('Sala de Auto Acceso'): 'Auto Acceso',
            normalize_header('Auto Acceso'): 'Auto Acceso',
            normalize_header('Autoacceso'): 'Auto Acceso',
            normalize_header('Biblioteca Digital'): 'Biblioteca',
        })

        place = text('Lugar')

        return Equipo, dict(
            no_equipo=text('No. Equipo'),
            no_bien_patrimonial=text('No. Bien Patrimonial'),
            lugar=places.get(normalize_header(place), place),
        )

    def compare(self, obj, values):
        conflicts = []
        for name, value in values.items():
            old = getattr(obj, name)
            if isinstance(obj, Persona):
                if name == 'perfil':
                    continue
                if name in ('grupo', 'carrera') and old is None:
                    continue
            if hasattr(value, '_meta') or hasattr(old, '_meta'):
                same = self.related_key(old) == self.related_key(value)
            elif isinstance(value, str):
                same = equivalent(old) == equivalent(value)
            else:
                same = old == value
            if not same:
                conflicts.append(name)
        return conflicts

    def build(self):
        for sheet in self.plan.sheets:
            if sheet.errors:
                continue
            for number, row in sheet.rows:
                try:
                    model, values = self.values(sheet.name, row)
                    candidate = model(**values)
                    exclude = [name for name, value in values.items() if hasattr(value, '_meta') and value.pk is None]
                    candidate.full_clean(exclude=exclude, validate_unique=False, validate_constraints=False)
                    key = self.identity(candidate)
                    matches = self.index[model].get(key, [])
                    if len(matches) > 1:
                        raise ValidationError({'Identidad': 'Existen varias coincidencias en la base de datos; no se seleccionará una automáticamente.'})
                    if matches:
                        target = matches[0]
                        conflicts = self.compare(target, values)
                        if conflicts:
                            raise ValidationError({name: 'La información contradice un registro existente o una fila anterior. No se sobrescribirá.' for name in conflicts})
                        sheet.existing += 1
                        status = 'Existente / repetido, se conserva'
                        if model is Persona:
                            changes = {name: value for name, value in values.items() if name in ('grupo', 'carrera') and getattr(target, name) is None}
                            if changes:
                                for name, value in changes.items():
                                    setattr(target, name, value)
                                self.plan.relationship_updates.append((target, changes))
                                sheet.relationships += 1
                                status = 'Existente; agregar relación académica ausente'
                    else:
                        if model is Materia and self.index[Materia].get((*key[:2], None)):
                            raise ValidationError({'semestre': 'Hay una materia existente sin semestre con este nombre y carrera. Resuelve esa ambigüedad antes de importar; no se actualizará ni duplicará.'})
                        candidate.validate_unique(exclude=exclude)
                        self.index[model].setdefault(key, []).append(candidate)
                        self.plan.entries.append((candidate, values, sheet.name, number))
                        target = candidate
                        sheet.new += 1
                        status = 'Nuevo'
                    if model is Persona:
                        profiles = self.profiles.setdefault(key, set())
                        if values['perfil'] not in profiles:
                            profiles.add(values['perfil'])
                            self.plan.profile_entries.append((target, values['perfil'], sheet.name, number))
                            sheet.profiles += 1
                            status += f'; agregar perfil {values["perfil"]}'
                    if len(sheet.samples) < PREVIEW_LIMIT:
                        sheet.samples.append(dict(row=number, status=status, values=' · '.join(str(v) for v in values.values())))
                except ValidationError as exc:
                    errors = exc.message_dict if hasattr(exc, 'message_dict') else {'Registro': exc.messages}
                    for name, messages in errors.items():
                        for message in messages:
                            sheet.errors.append(dict(row=number, field=name, message=message))
        return self.plan


def preview(data):
    return Planner(read_workbook(data)).build()


def confirm(data, user):
    """Revalidar y agregar registros, perfiles y relaciones ausentes de forma atómica."""
    if not user.is_active or not user.is_staff or not user.has_perms(IMPORT_PERMISSIONS):
        raise ExcelError('No tienes permisos para importar estos catálogos.')
    from django.contrib.contenttypes.models import ContentType

    with transaction.atomic():
        ContentType.objects.select_for_update().get(app_label='inicio', model='carrera')
        plan = Planner(read_workbook(data), lock=True).build()
        if not plan.valid:
            raise ExcelError('La revalidación detectó errores o cambios desde la vista previa. Vuelve a cargar el archivo para revisar los detalles.')
        for obj, values, sheet, number in plan.entries:
            for name, value in values.items():
                if hasattr(value, '_meta'):
                    setattr(obj, name, value)
            obj.full_clean()
            if hasattr(obj, 'history') or isinstance(obj, Persona):
                obj._history_user = user
                obj._change_reason = f'Importación Excel: {sheet}, fila {number}'
            obj.save(force_insert=True)
        for obj, changes in plan.relationship_updates:
            for name, value in changes.items():
                setattr(obj, name, value)
            obj._history_user = user
            obj.full_clean()
            obj.save(update_fields=list(changes))
        for person, perfil, sheet, number in plan.profile_entries:
            if not PersonaPerfil.objects.filter(persona=person, perfil=perfil).exists():
                membership = PersonaPerfil(persona=person, perfil=perfil)
                membership._history_user = user
                membership._change_reason = f'Importación Excel: {sheet}, fila {number}'
                membership.full_clean()
                membership.save()
        return plan
