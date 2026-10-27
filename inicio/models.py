from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from simple_history.models import HistoricalRecords

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
    id_persona = models.AutoField(primary_key=True)
    
    # CORRECCIÓN: Vinculamos formalmente a la tabla Carrera para evitar el número suelto
    carrera = models.ForeignKey(Carrera, on_delete=models.SET_NULL, null=True, blank=True, db_column='id_carrera', verbose_name="Carrera")
    
    perfil = models.CharField(max_length=50, choices=[
        ('Administrador', 'Administrador'),
        ('Docente', 'Docente'),
        ('Alumno', 'Alumno')
    ])
    matricula = models.CharField(max_length=20, unique=True, null=True, blank=True)
    nombre = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.matricula or 'S/N'} {self.nombre} {self.apellidos}"


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
    carrera = models.ForeignKey(Carrera, on_delete=models.CASCADE, db_column='id_carrera', verbose_name="Carrera")

    def __str__(self):
        return self.nombre_materia


class Grupo(models.Model):
    id_grupo = models.AutoField(primary_key=True)
    nombre_grupo = models.CharField(max_length=20)
    semestre = models.IntegerField()
    turno = models.CharField(max_length=20)
    carrera = models.ForeignKey(Carrera, on_delete=models.CASCADE, db_column='id_carrera', verbose_name="Carrera")

    def __str__(self):
        return f"{self.nombre_grupo} - Semestre {self.semestre} ({self.turno})"


class Clase(models.Model):
    id_clase = models.AutoField(primary_key=True)
    materia = models.ForeignKey(Materia, on_delete=models.CASCADE, db_column='id_materia', verbose_name="Materia")
    grupo = models.ForeignKey(Grupo, on_delete=models.CASCADE, db_column='id_grupo', verbose_name="Grupo")
    docente = models.ForeignKey(Persona, on_delete=models.CASCADE, db_column='id_persona', verbose_name="Responsable a cargo")
    
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    def clean(self):
        if not self.fecha or not self.hora_inicio or not self.hora_fin:
            return

        fecha_actual = timezone.now().date()
        if self.fecha < fecha_actual:
            raise ValidationError({'fecha': 'Error: No puedes agendar una clase en una fecha pasada.'})

        # Margen de tolerancia de 5 minutos
        if self.fecha == fecha_actual:
            hora_limite = (timezone.now() - timedelta(minutes=5)).time()
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
    
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, verbose_name="Usuario / Persona")
    equipo = models.ForeignKey(Equipo, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Equipo de Cómputo")
    clase = models.ForeignKey(Clase, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Clase asignada")
    evento = models.ForeignKey(EventoTallerConferencia, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Evento asignado")
    registrado_por = models.ForeignKey(UsuarioSistema, on_delete=models.SET_NULL, null=True, blank=True)
    observaciones = models.TextField(null=True, blank=True)
    history = HistoricalRecords()  # Para el historial de cambios

    # SISTEMA ANTI-CHOQUES RESTAURADO
    def clean(self):
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
