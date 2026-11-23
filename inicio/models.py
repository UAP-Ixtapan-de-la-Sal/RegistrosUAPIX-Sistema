from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models, router, transaction
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import time as time_type, timedelta
from simple_history.models import HistoricalRecords
from .db_constraints import PrecisionMinuto


PERFILES_PERSONA = (
    ('Administrador', 'Administrador'),
    ('Docente', 'Docente'),
    ('Alumno', 'Alumno'),
)


class PersonaQuerySet(models.QuerySet):
    def con_perfiles(self, *perfiles):
        return self.filter(
            models.Q(perfil__in=perfiles) | models.Q(perfiles__perfil__in=perfiles),
        ).distinct()


def normalizar_hora(valor):
    if valor is None or valor == '':
        return valor
    if hasattr(valor, 'resolve_expression'):
        raise ValueError('Los horarios no admiten expresiones ORM sin normalizar.')
    if not isinstance(valor, time_type):
        valor = models.TimeField().to_python(valor)
    return valor.replace(second=0, microsecond=0)


class HorarioQuerySet(models.QuerySet):
    CAMPOS_HORARIO = {'hora_inicio', 'hora_fin'}

    def _chain(self):
        clone = super()._chain()
        clone._bulk_update_in_progress = getattr(self, '_bulk_update_in_progress', False)
        return clone

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False,
                    update_conflicts=False, update_fields=None, unique_fields=None):
        objs = list(objs)
        audited = hasattr(self.model, 'history')
        if audited and (ignore_conflicts or update_conflicts):
            raise ValueError('Los eventos con historial no admiten omitir o sobrescribir conflictos en bulk_create.')
        for obj in objs:
            obj.hora_inicio = normalizar_hora(obj.hora_inicio)
            obj.hora_fin = normalizar_hora(obj.hora_fin)
            obj.full_clean()
        with transaction.atomic(using=self.db):
            result = super().bulk_create(
                objs, batch_size=batch_size, ignore_conflicts=ignore_conflicts,
                update_conflicts=update_conflicts, update_fields=update_fields,
                unique_fields=unique_fields,
            )
            if audited:
                if any(obj.pk is None for obj in result):
                    raise ValueError('El motor debe devolver los identificadores para registrar el historial de eventos.')
                self.model.history.bulk_history_create(result, batch_size=batch_size)
            return result

    def bulk_update(self, objs, fields, batch_size=None):
        objs = list(objs)
        if self.CAMPOS_HORARIO.intersection(fields):
            for obj in objs:
                obj.hora_inicio = normalizar_hora(obj.hora_inicio)
                obj.hora_fin = normalizar_hora(obj.hora_fin)
                obj.full_clean()
        with transaction.atomic(using=self.db):
            audited = hasattr(self.model, 'history')
            if audited:
                affected = list(self.select_for_update().filter(pk__in=[obj.pk for obj in objs]).values_list('pk', flat=True))
            self._bulk_update_in_progress = True
            try:
                updated = super().bulk_update(objs, fields, batch_size=batch_size)
            finally:
                self._bulk_update_in_progress = False
            if audited:
                # Leer el estado realmente guardado respeta los filtros del
                # queryset y los campos indicados en bulk_update.
                saved = list(self.model._base_manager.using(self.db).filter(pk__in=affected))
                original = {obj.pk: obj for obj in objs}
                for obj in saved:
                    source = original[obj.pk]
                    for attr in ('_history_user', '_change_reason', '_history_date'):
                        if hasattr(source, attr):
                            setattr(obj, attr, getattr(source, attr))
                self.model.history.bulk_history_create(saved, batch_size=batch_size, update=True)
            return updated

    def update(self, **kwargs):
        if getattr(self, '_bulk_update_in_progress', False):
            return super().update(**kwargs)
        campos_horario = self.CAMPOS_HORARIO.intersection(kwargs)
        audited = hasattr(self.model, 'history')
        if not kwargs or not (campos_horario or audited):
            return super().update(**kwargs)
        for campo in campos_horario:
            kwargs[campo] = normalizar_hora(kwargs[campo])
        with transaction.atomic(using=self.db):
            affected = list(self.select_for_update().values_list('pk', flat=True))
            updated = super().update(**kwargs)
            if campos_horario:
                for obj in self.model._base_manager.using(self.db).filter(pk__in=affected):
                    # Validar el resultado completo incluye otros cambios de la
                    # misma actualización; cualquier error revierte el conjunto.
                    obj.full_clean()
            if audited:
                saved = list(self.model._base_manager.using(self.db).filter(pk__in=affected))
                self.model.history.bulk_history_create(saved, update=True)
            return updated

class UsuarioSistema(AbstractUser):
    # 1. Definimos el Rol (Operador o Visualizador)
    ROLES = (
        ('operador', 'Operador de Módulo'),
        ('visualizador', 'Visualizador'),
    )
    rol = models.CharField(max_length=20, choices=ROLES, default='visualizador')

    # 2. Checkboxes reales para módulos
    mod_sala_computo = models.BooleanField('Sala de Cómputo', default=False)
    mod_auto_acceso = models.BooleanField('Auto Acceso', default=False)
    mod_biblioteca = models.BooleanField('Biblioteca Digital', default=False)
    mod_prestamos = models.BooleanField('Préstamos y Devolución', default=False)
    mod_insumos = models.BooleanField('Control de Insumos', default=False)
    mod_tecnologicos = models.BooleanField('Insumos Tecnológicos', default=False)

    def __str__(self):
        return self.username

#TABLA CLASE 
class Carrera(models.Model):
    id_carrera = models.AutoField(primary_key=True)
    nombre_carrera = models.CharField(max_length=100)

    def __str__(self):
        return self.nombre_carrera

class Persona(models.Model):
    objects = PersonaQuerySet.as_manager()
    id_persona = models.AutoField(primary_key=True)
    grupo = models.ForeignKey(
        'Grupo', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='alumnos', verbose_name='Grupo',
    )
    
    # CORRECCIÓN: Vinculamos formalmente a la tabla Carrera para evitar el número suelto
    carrera = models.ForeignKey(Carrera, on_delete=models.SET_NULL, null=True, blank=True, db_column='id_carrera', verbose_name="Carrera")
    
    # Perfil principal conservado para compatibilidad con los módulos existentes.
    perfil = models.CharField(max_length=50, choices=PERFILES_PERSONA)
    matricula = models.CharField(max_length=20, unique=True, null=True, blank=True)
    nombre = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)

    def clean(self):
        super().clean()
        if self.grupo_id and self.carrera_id != self.grupo.carrera_id:
            raise ValidationError({'grupo': 'El grupo debe pertenecer a la carrera de la persona.'})

    @property
    def perfiles_actuales(self):
        perfiles = {item.perfil for item in self.perfiles.all()} if self.pk else set()
        if self.perfil:
            perfiles.add(self.perfil)
        return perfiles

    def tiene_perfil(self, *perfiles):
        return bool(self.perfiles_actuales.intersection(perfiles))

    def save(self, *args, **kwargs):
        using = kwargs.get('using') or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            super().save(*args, **kwargs)
            if self.perfil in dict(PERFILES_PERSONA):
                # Serializa la sincronización del perfil principal al editar una
                # persona existente. Los perfiles adicionales nunca se eliminan.
                type(self).objects.using(using).select_for_update().get(pk=self.pk)
                if not PersonaPerfil.objects.using(using).filter(persona_id=self.pk, perfil=self.perfil).exists():
                    membership = PersonaPerfil(persona_id=self.pk, perfil=self.perfil)
                    membership._history_user = getattr(self, '_history_user', None)
                    membership._change_reason = getattr(self, '_change_reason', None)
                    membership.save(using=using)

    def __str__(self):
        return f"{self.matricula or 'S/N'} {self.nombre} {self.apellidos}"


class PersonaPerfil(models.Model):
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name='perfiles')
    perfil = models.CharField(max_length=50, choices=PERFILES_PERSONA)
    history = HistoricalRecords()

    class Meta:
        verbose_name = 'perfil institucional'
        verbose_name_plural = 'perfiles institucionales'
        constraints = [
            models.UniqueConstraint(fields=('persona', 'perfil'), name='inicio_persona_perfil_unico'),
            models.CheckConstraint(condition=models.Q(perfil__in=[p for p, _ in PERFILES_PERSONA]), name='inicio_persona_perfil_valido'),
        ]

    def __str__(self):
        return f'{self.persona} - {self.get_perfil_display()}'


class Externo(models.Model):
    id_externo = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    institucion = models.CharField(max_length=100, null=True, blank=True, verbose_name="Institución de procedencia")

    def __str__(self):
        return f"{self.nombre} {self.apellidos} (Externo)"



class Materia(models.Model):
    id_materia = models.AutoField(primary_key=True)
    nombre_materia = models.CharField(max_length=100)
    semestre = models.IntegerField(null=True, blank=True)
    carrera = models.ForeignKey(Carrera, on_delete=models.CASCADE, db_column='id_carrera', verbose_name="Carrera")

    def __str__(self):
        return self.nombre_materia


class Grupo(models.Model):
    id_grupo = models.AutoField(primary_key=True)
    nombre_grupo = models.CharField(max_length=20)
    semestre = models.IntegerField(null=True, blank=True)
    turno = models.CharField(max_length=20, blank=True)
    carrera = models.ForeignKey(Carrera, on_delete=models.CASCADE, db_column='id_carrera', verbose_name="Carrera")

    def __str__(self):
        if self.semestre is not None and self.turno:
            return f"{self.nombre_grupo} - Semestre {self.semestre} ({self.turno})"
        partes = [self.nombre_grupo]
        if self.semestre is not None:
            partes.append(f'Semestre {self.semestre}')
        if self.turno:
            partes.append(self.turno)
        return ' - '.join(partes)


class Clase(models.Model):
    objects = HorarioQuerySet.as_manager()

    id_clase = models.AutoField(primary_key=True)
    materia = models.ForeignKey(Materia, on_delete=models.CASCADE, db_column='id_materia', verbose_name="Materia")
    grupo = models.ForeignKey(Grupo, on_delete=models.CASCADE, db_column='id_grupo', verbose_name="Grupo")
    docente = models.ForeignKey(
        Persona,
        on_delete=models.CASCADE,
        db_column='id_persona',
        limit_choices_to=models.Q(perfil='Docente') | models.Q(perfiles__perfil='Docente'),
        verbose_name="Responsable a cargo",
    )
    
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    def clean(self):
        self.hora_inicio = normalizar_hora(self.hora_inicio)
        self.hora_fin = normalizar_hora(self.hora_fin)
        if not self.fecha or not self.hora_inicio or not self.hora_fin:
            return

        fecha_actual = timezone.localdate()
        if self.fecha < fecha_actual:
            raise ValidationError({'fecha': 'Error: No puedes agendar una clase en una fecha pasada.'})

        # Margen de tolerancia de 5 minutos
        if self.fecha == fecha_actual:
            hora_limite = (timezone.localtime() - timedelta(minutes=5)).time()
            if self.hora_inicio < hora_limite:
                raise ValidationError({'hora_inicio': 'Error: La hora de inicio ya pasó (fuera del margen de 5 minutos).'})

        if self.hora_fin <= self.hora_inicio:
            raise ValidationError({'hora_fin': 'Error: La hora de fin debe ser después del inicio.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Clase: {self.materia} - {self.grupo} ({self.fecha})"


class EventoTallerConferencia(models.Model):
    objects = HorarioQuerySet.as_manager()

    TIPO_EVENTO_CHOICES = [
        ('Taller', 'Taller'),
        ('Conferencia', 'Conferencia'),
        ('Clase', 'Clase'),
    ]
    TIPO_PONENTE_CHOICES = [
        ('Interno', 'Docente/Alumno del Plantel'),
        ('Externo', 'Persona Externa'),
    ]

    id_evento = models.AutoField(primary_key=True)
    tipo_evento = models.CharField(max_length=50, choices=TIPO_EVENTO_CHOICES, default='Taller')
    nombre_evento = models.CharField(max_length=100)
    clase = models.ForeignKey(Clase, on_delete=models.SET_NULL, null=True, blank=True, db_column='id_clase', verbose_name="Clase vinculada")
    
    tipo_ponente = models.CharField(max_length=20, choices=TIPO_PONENTE_CHOICES, default='Interno')
    ponente_interno = models.ForeignKey(Persona, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Ponente Interno")
    ponente_externo = models.ForeignKey(Externo, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Ponente Externo")
    
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    estado_bloque = models.BooleanField("Bloquear horario", default=True, help_text="Si está activo, no se podrán asignar más actividades en este horario.")
    history = HistoricalRecords()  # Para el historial de cambios
    
    def clean(self):
        self.hora_inicio = normalizar_hora(self.hora_inicio)
        self.hora_fin = normalizar_hora(self.hora_fin)
        if not self.fecha or not self.hora_inicio or not self.hora_fin:
            return

        fecha_actual = timezone.localtime().date()
        if self.fecha < fecha_actual:
            raise ValidationError({'fecha': 'Error: No puedes agendar un evento en una fecha pasada.'})

        if self.fecha == fecha_actual:
            ahora_local = timezone.localtime()
            hora_limite = (ahora_local - timedelta(minutes=5)).time()
            if self.hora_inicio < hora_limite:
                raise ValidationError({'hora_inicio': 'Error: La hora de inicio ya pasó.'})

        if self.hora_fin <= self.hora_inicio:
            raise ValidationError({'hora_fin': 'Error: La hora de fin debe ser después del inicio.'})
        
        # === NUEVA LÓGICA INTELIGENTE DE PONENTES ===
        if self.tipo_ponente == 'Interno':
            if not self.ponente_interno:
                raise ValidationError({'ponente_interno': 'Seleccionaste tipo Interno. Debes elegir un Ponente Interno.'})
            # Vaciamos el externo automáticamente para evitar choques de datos
            self.ponente_externo = None 

        elif self.tipo_ponente == 'Externo':
            if not self.ponente_externo:
                raise ValidationError({'ponente_externo': 'Seleccionaste tipo Externo. Debes elegir o agregar un Ponente Externo.'})
            # Vaciamos el interno automáticamente
            self.ponente_interno = None

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre_evento


class Equipo(models.Model):
    LUGAR_CHOICES = [
        ('Sala', 'Sala de Cómputo'),
        ('Auto Acceso', 'Auto Acceso'),
        ('Biblioteca', 'Biblioteca')
    ]
    ESTADO_CHOICES = [
        ('Disponible', 'Disponible'),
        ('Ocupado', 'Ocupado'),
        ('Mantenimiento', 'Mantenimiento'),
        ('Baja', 'Baja')
    ]
    CONDICION_CHOICES = [
        ('Bueno', 'Bueno'),
        ('Regular', 'Regular'),
        ('Malo', 'Malo')
    ]

    id_equipo = models.AutoField(primary_key=True)
    no_equipo = models.CharField(max_length=50)
    no_bien_patrimonial = models.CharField(max_length=100, unique=True, null=True, blank=True)
    lugar = models.CharField(max_length=50, choices=LUGAR_CHOICES)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='Disponible')
    condicion = models.CharField(max_length=20, choices=CONDICION_CHOICES, default='Bueno')
    observaciones = models.TextField(null=True, blank=True)
    history = HistoricalRecords()  # Para el historial de cambios

    def __str__(self):
        return f"Eq: {self.no_equipo} ({self.lugar})"


class Registro(models.Model):
    MODULO_CHOICES = [
        ('Sala_Computo', 'Sala de Cómputo'),
        ('Auto_Acceso', 'Auto Acceso'),
        ('Biblioteca', 'Biblioteca Digital')
    ]
    TIPO_REGISTRO_CHOICES = [
        ('Clase', 'Clase'),
        ('Evento', 'Evento'),
        ('Visita', 'Visita')
    ]
    MOTIVO_USO_CHOICES = [
        ('Clase', 'Clase'),
        ('Visita', 'Visita'),
        ('Conversacion', 'Conversación')
    ]

    id_registro = models.AutoField(primary_key=True)
    modulo = models.CharField(max_length=20, choices=MODULO_CHOICES, default='Sala_Computo')
    tipo_registro = models.CharField(max_length=20, choices=TIPO_REGISTRO_CHOICES, null=True, blank=True)
    motivo_uso = models.CharField(max_length=20, choices=MOTIVO_USO_CHOICES, null=True, blank=True)
    
    fecha = models.DateField(default=timezone.now)
    hora_entrada = models.TimeField(default=timezone.now)
    hora_salida = models.TimeField(null=True, blank=True)
    
    persona = models.ForeignKey(
        Persona, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Usuario / Persona",
    )
    externo = models.ForeignKey(
        Externo, on_delete=models.PROTECT, null=True, blank=True, verbose_name="Asistente externo",
    )
    equipo = models.ForeignKey(Equipo, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Equipo de Cómputo")
    clase = models.ForeignKey(Clase, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Clase asignada")
    evento = models.ForeignKey(EventoTallerConferencia, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Evento asignado")
    registrado_por = models.ForeignKey(UsuarioSistema, on_delete=models.SET_NULL, null=True, blank=True)
    observaciones = models.TextField(null=True, blank=True)
    history = HistoricalRecords()  # Para el historial de cambios

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(persona__isnull=False, externo__isnull=True)
                    | models.Q(persona__isnull=True, externo__isnull=False)
                ),
                name='inicio_registro_un_solo_asistente',
            ),
        ]

    # SISTEMA ANTI-CHOQUES RESTAURADO
    def clean(self):
        if bool(self.persona_id) == bool(self.externo_id):
            raise ValidationError('El registro debe estar asociado a una persona o a un asistente externo.')

        if self.hora_entrada and self.hora_salida:
            if self.hora_salida <= self.hora_entrada:
                raise ValidationError({'hora_salida': 'Error lógico: La hora de salida no puede ser antes o igual a la hora de entrada.'})

        if self.equipo:
            registros_existentes = Registro.objects.filter(
                equipo=self.equipo,
                fecha=self.fecha
            ).exclude(id_registro=self.id_registro)

            for reg in registros_existentes:
                if not reg.hora_salida:
                    raise ValidationError({'equipo': f'Bloqueo: Este equipo está siendo ocupado actualmente (Entró a las {reg.hora_entrada}).'})

                if self.hora_salida:
                    if self.hora_entrada < reg.hora_salida and self.hora_salida > reg.hora_entrada:
                        raise ValidationError({'hora_entrada': f'Choque de horario: Este equipo ya fue utilizado de {reg.hora_entrada} a {reg.hora_salida}.'})
                else:
                    if self.hora_entrada < reg.hora_salida:
                        raise ValidationError({'hora_entrada': f'Choque de horario: La entrada interfiere con un registro previo de {reg.hora_entrada} a {reg.hora_salida}.'})
        if self.equipo:
            # Diccionario para empatar los valores del módulo con los del lugar del equipo
            mapeo_lugares = {
                'Sala_Computo': 'Sala',
                'Auto_Acceso': 'Auto Acceso',
                'Biblioteca': 'Biblioteca'
            }
            
            lugar_correspondiente = mapeo_lugares.get(self.modulo)
            
            if self.equipo.lugar != lugar_correspondiente:
                raise ValidationError({
                    'equipo': f'Incongruencia: Seleccionaste el módulo {self.modulo}, pero este equipo pertenece a {self.equipo.lugar}.'
                })
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        
        if self.equipo:
            if self.hora_salida:
                self.equipo.estado = 'Disponible'
            else:
                self.equipo.estado = 'Ocupado'
            self.equipo.save()
#CHIDO PERRON
    def __str__(self):
        return f"Registro {self.id_registro} - {self.modulo} ({self.fecha})"


class Asistencia(models.Model):
    ESTADOS = (
        ('Asistió', 'Asistió'),
        ('Falta', 'Falta'),
    )

    clase = models.ForeignKey(Clase, on_delete=models.CASCADE, related_name='asistencias')
    alumno = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name='asistencias')
    estado = models.CharField(max_length=10, choices=ESTADOS)
    equipo = models.ForeignKey(Equipo, on_delete=models.SET_NULL, null=True, blank=True)
    registro = models.OneToOneField(
        Registro, on_delete=models.PROTECT, null=True, blank=True, related_name='asistencia',
    )
    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('clase', 'alumno'), name='inicio_asistencia_clase_alumno_unica'),
        ]
        ordering = ('alumno__apellidos', 'alumno__nombre')

    def clean(self):
        super().clean()
        if self.clase_id and self.alumno_id:
            if not self.alumno.tiene_perfil('Alumno'):
                raise ValidationError({'alumno': 'La asistencia solo puede registrarse para alumnos.'})
            if self.alumno.grupo_id != self.clase.grupo_id:
                raise ValidationError({'alumno': 'El alumno no pertenece al grupo de esta clase.'})

        if self.estado == 'Asistió':
            if not self.registro_id:
                raise ValidationError({'registro': 'La asistencia requiere el registro de entrada correspondiente.'})
            if self.registro.persona_id != self.alumno_id or self.registro.clase_id != self.clase_id:
                raise ValidationError({'registro': 'El registro de entrada no corresponde a este alumno y clase.'})
            if self.registro.equipo_id != self.equipo_id:
                raise ValidationError({'equipo': 'El equipo debe coincidir con el registro de entrada.'})
        elif self.estado == 'Falta' and (self.registro_id or self.equipo_id):
            raise ValidationError('Una falta no puede tener registro de entrada ni equipo asignado.')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.alumno} - {self.clase} - {self.get_estado_display()}'


class EstadoObjeto(models.TextChoices):
    DISPONIBLE = 'Disponible', 'Disponible'
    OCUPADO = 'Ocupado', 'Ocupado'
    MANTENIMIENTO = 'Mantenimiento', 'Mantenimiento'
    BAJA = 'Baja', 'Baja'


class CondicionObjeto(models.TextChoices):
    BUENO = 'Bueno', 'Bueno'
    REGULAR = 'Regular', 'Regular'
    MALO = 'Malo', 'Malo'


def restriccion_minuto(campo, nombre, *, nullable=False):
    condicion = models.Q(PrecisionMinuto(campo))
    if nullable:
        condicion |= models.Q(**{f'{campo}__isnull': True})
    return models.CheckConstraint(condition=condicion, name=nombre)


class ImplementoTecnologico(models.Model):
    id_implemento = models.AutoField(primary_key=True)
    codigo_interno = models.CharField(max_length=50, unique=True)
    tipo_implemento = models.CharField(max_length=100)
    numero_bien_patrimonial = models.CharField(max_length=100, blank=True, null=True)
    serie = models.CharField(max_length=100, blank=True, null=True)
    marca = models.CharField(max_length=100, blank=True, null=True)
    modelo = models.CharField(max_length=100, blank=True, null=True)
    estado = models.CharField(max_length=20, choices=EstadoObjeto.choices)
    condicion = models.CharField(max_length=20, choices=CondicionObjeto.choices)
    observaciones = models.TextField(blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        indexes = [models.Index(fields=['estado', 'tipo_implemento'], name='impl_estado_tipo_idx')]
        constraints = [
            models.CheckConstraint(condition=~models.Q(codigo_interno=''), name='impl_codigo_no_vacio'),
            models.CheckConstraint(condition=~models.Q(tipo_implemento=''), name='impl_tipo_no_vacio'),
            models.CheckConstraint(condition=models.Q(estado__in=EstadoObjeto.values), name='impl_estado_valido'),
            models.CheckConstraint(condition=models.Q(condicion__in=CondicionObjeto.values), name='impl_condicion_valida'),
        ]

    def __str__(self):
        return f'{self.codigo_interno} - {self.tipo_implemento}'


class Prestamo(models.Model):
    id_prestamo = models.AutoField(primary_key=True)
    persona_solicitante = models.ForeignKey(
        Persona, on_delete=models.PROTECT, related_name='prestamos_solicitados',
    )
    operador_prestamo = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='prestamos_registrados',
    )
    fecha_hora_prestamo = models.DateTimeField()
    fecha_hora_devolucion_prevista = models.DateTimeField()
    lugar_destino = models.CharField(max_length=150)
    uso_prestamo = models.TextField()
    observaciones = models.TextField(blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        indexes = [
            models.Index(fields=['persona_solicitante', 'fecha_hora_prestamo'], name='prest_solicitante_fecha_idx'),
            models.Index(fields=['fecha_hora_devolucion_prevista'], name='prest_devol_prevista_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fecha_hora_devolucion_prevista__gte=models.F('fecha_hora_prestamo')),
                name='prest_fechas_coherentes',
            ),
            models.CheckConstraint(condition=~models.Q(lugar_destino=''), name='prest_lugar_no_vacio'),
            models.CheckConstraint(condition=~models.Q(uso_prestamo=''), name='prest_uso_no_vacio'),
            restriccion_minuto('fecha_hora_prestamo', 'prest_inicio_minuto'),
            restriccion_minuto('fecha_hora_devolucion_prevista', 'prest_prevista_minuto'),
        ]

    def __str__(self):
        return f'Préstamo {self.pk}'


class DetallePrestamo(models.Model):
    id_detalle_prestamo = models.AutoField(primary_key=True)
    prestamo = models.ForeignKey(Prestamo, on_delete=models.PROTECT, related_name='detalles')
    implemento = models.ForeignKey(ImplementoTecnologico, on_delete=models.PROTECT, related_name='detalles_prestamo')
    condicion_salida = models.CharField(max_length=20, choices=CondicionObjeto.choices)
    observaciones_salida = models.TextField(blank=True, null=True)
    fecha_hora_devolucion = models.DateTimeField(blank=True, null=True)
    persona_devuelve = models.ForeignKey(
        Persona, on_delete=models.PROTECT, blank=True, null=True, related_name='implementos_devueltos',
    )
    operador_devolucion = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, blank=True, null=True,
        related_name='devoluciones_registradas',
    )
    condicion_devolucion = models.CharField(max_length=20, choices=CondicionObjeto.choices, blank=True, null=True)
    observaciones_devolucion = models.TextField(blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        indexes = [
            models.Index(fields=['implemento', 'fecha_hora_devolucion'], name='detalle_impl_devolucion_idx'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['prestamo', 'implemento'], name='detalle_prestamo_impl_unico'),
            models.CheckConstraint(
                condition=(
                    models.Q(fecha_hora_devolucion__isnull=True, persona_devuelve__isnull=True,
                             operador_devolucion__isnull=True, condicion_devolucion__isnull=True)
                    | models.Q(fecha_hora_devolucion__isnull=False, persona_devuelve__isnull=False,
                               operador_devolucion__isnull=False, condicion_devolucion__isnull=False)
                ),
                name='detalle_devolucion_completa',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(fecha_hora_devolucion__isnull=False)
                    | models.Q(observaciones_devolucion__isnull=True)
                    | models.Q(observaciones_devolucion='')
                ),
                name='detalle_obs_solo_devolucion',
            ),
            models.CheckConstraint(condition=models.Q(condicion_salida__in=CondicionObjeto.values), name='detalle_cond_salida_valida'),
            models.CheckConstraint(
                condition=models.Q(condicion_devolucion__isnull=True) | models.Q(condicion_devolucion__in=CondicionObjeto.values),
                name='detalle_cond_dev_valida',
            ),
            restriccion_minuto('fecha_hora_devolucion', 'detalle_devolucion_minuto', nullable=True),
        ]

    def clean(self):
        super().clean()
        # Coherencia entre tablas: no es una restricción CHECK de la BD.
        if self.prestamo_id and self.fecha_hora_devolucion:
            inicio = Prestamo.objects.filter(pk=self.prestamo_id).values_list('fecha_hora_prestamo', flat=True).first()
            if inicio and self.fecha_hora_devolucion < inicio:
                raise ValidationError({'fecha_hora_devolucion': 'La devolución no puede ser anterior al préstamo.'})

    def __str__(self):
        return f'{self.prestamo_id} - {self.implemento_id}'


class CategoriaInsumo(models.Model):
    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~models.Q(nombre=''), name='cat_insumo_nombre_no_vacio'),
        ]

    def __str__(self):
        return self.nombre


class Insumo(models.Model):
    id_insumo = models.AutoField(primary_key=True)
    nombre_insumo = models.CharField(max_length=150)
    categoria = models.ForeignKey(CategoriaInsumo, on_delete=models.PROTECT)
    unidad_medida = models.CharField(max_length=50)
    existencia_actual = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0'), validators=[MinValueValidator(Decimal('0'))])
    stock_minimo = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0'), validators=[MinValueValidator(Decimal('0'))])
    activo = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        indexes = [models.Index(fields=['categoria', 'activo'], name='insumo_categoria_activo_idx')]
        constraints = [
            models.CheckConstraint(condition=models.Q(existencia_actual__gte=0), name='insumo_existencia_no_negativa'),
            models.CheckConstraint(condition=models.Q(stock_minimo__gte=0), name='insumo_minimo_no_negativo'),
            models.CheckConstraint(condition=~models.Q(nombre_insumo=''), name='insumo_nombre_no_vacio'),
            models.CheckConstraint(condition=~models.Q(unidad_medida=''), name='insumo_unidad_no_vacia'),
            models.CheckConstraint(condition=models.Q(activo__in=[True, False]), name='insumo_activo_booleano'),
        ]

    def __str__(self):
        return self.nombre_insumo


class MovimientoInventario(models.Model):
    class Tipo(models.TextChoices):
        ENTRADA = 'Entrada', 'Entrada'
        SALIDA = 'Salida', 'Salida'

    id_movimiento = models.AutoField(primary_key=True)
    insumo = models.ForeignKey(Insumo, on_delete=models.PROTECT, related_name='movimientos')
    tipo_movimiento = models.CharField(max_length=10, choices=Tipo.choices)
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal('0.001'))])
    fecha = models.DateField()
    hora = models.TimeField()
    proveedor = models.CharField(max_length=150, blank=True, null=True)
    area_destino = models.CharField(max_length=150, blank=True, null=True)
    persona = models.ForeignKey(Persona, on_delete=models.PROTECT, blank=True, null=True, related_name='movimientos_material')
    operador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='movimientos_inventario')
    observaciones = models.TextField(blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        indexes = [
            models.Index(fields=['insumo', 'fecha', 'hora'], name='mov_insumo_fecha_hora_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name='mov_cantidad_positiva'),
            models.CheckConstraint(condition=models.Q(tipo_movimiento__in=['Entrada', 'Salida']), name='mov_tipo_valido'),
            restriccion_minuto('hora', 'mov_hora_minuto'),
        ]

    def __str__(self):
        return f'{self.tipo_movimiento}: {self.cantidad} ({self.insumo_id})'


class CamposRetiradosHistorialFalla(models.Model):
    """Columnas de auditoría anteriores; no forman parte del modelo activo."""

    MOMENTOS_DETECCION = (
        ('durante_uso', 'Durante el uso'),
        ('al_finalizar', 'Al finalizar el uso'),
        ('despues_actividad', 'Después del evento o visita'),
    )
    ESTADOS_ATENCION = (
        ('Pendiente', 'Pendiente'),
        ('Resuelta', 'Resuelta'),
    )

    registro = models.ForeignKey(
        Registro, on_delete=models.DO_NOTHING, null=True, blank=True,
        db_constraint=False, related_name='+',
    )
    momento_deteccion = models.CharField(
        max_length=24, choices=MOMENTOS_DETECCION, blank=True, null=True,
    )
    estado_atencion = models.CharField(
        max_length=10, choices=ESTADOS_ATENCION, blank=True, null=True,
    )

    class Meta:
        abstract = True


class BitacoraFalla(models.Model):
    id_falla = models.BigAutoField(primary_key=True)
    # NULL representa información desconocida durante la transición del módulo.
    lugar = models.CharField(max_length=150, blank=True, null=True)
    equipo = models.ForeignKey(Equipo, on_delete=models.PROTECT, blank=True, null=True, related_name='incidencias')
    implemento = models.ForeignKey(
        ImplementoTecnologico, on_delete=models.PROTECT, blank=True, null=True, related_name='fallas',
    )
    categoria_falla = models.CharField(max_length=100, blank=True, null=True)
    componente_afectado = models.CharField(max_length=100, blank=True, null=True)
    prioridad_alta = models.BooleanField(blank=True, null=True)
    condicion = models.CharField(max_length=20, choices=CondicionObjeto.choices, blank=True, null=True)
    estado = models.CharField(max_length=20, choices=EstadoObjeto.choices, blank=True, null=True)
    descripcion_falla = models.TextField()
    fecha_reporte = models.DateTimeField(auto_now_add=True)
    usuario_sistema = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='incidencias',
    )
    observaciones = models.TextField(blank=True, null=True)
    history = HistoricalRecords(bases=[CamposRetiradosHistorialFalla])

    class Meta:
        db_table = 'bitacoraFalla'
        indexes = [
            models.Index(fields=['equipo', 'fecha_reporte'], name='falla_equipo_fecha_idx'),
            models.Index(fields=['implemento', 'fecha_reporte'], name='falla_impl_fecha_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(equipo__isnull=False, implemento__isnull=True)
                    | models.Q(equipo__isnull=True, implemento__isnull=False)
                ),
                name='falla_exactamente_un_objeto',
            ),
            models.CheckConstraint(
                condition=models.Q(condicion__isnull=True) | models.Q(condicion__in=CondicionObjeto.values),
                name='falla_condicion_valida',
            ),
            models.CheckConstraint(
                condition=models.Q(estado__isnull=True) | models.Q(estado__in=EstadoObjeto.values),
                name='falla_estado_objeto_valido',
            ),
            models.CheckConstraint(
                condition=models.Q(prioridad_alta__isnull=True) | models.Q(prioridad_alta__in=[True, False]),
                name='falla_prioridad_booleana',
            ),
        ]

    def clean(self):
        super().clean()
        if bool(self.equipo_id) == bool(self.implemento_id):
            mensaje = 'Selecciona exactamente un equipo o un implemento.'
            raise ValidationError({'equipo': mensaje, 'implemento': mensaje})

    def save(self, *args, **kwargs):
        # Validación existente de Incidencia; no implementa flujos nuevos.
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Falla {self.pk or "nueva"} - {self.equipo or self.implemento}'
