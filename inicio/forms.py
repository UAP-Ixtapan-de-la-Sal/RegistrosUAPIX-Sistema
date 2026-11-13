from datetime import timedelta

from django import forms
from django.utils import timezone
from .models import Persona, UsuarioSistema, normalizar_hora

class RegistroUsuarioForm(forms.ModelForm):
    class Meta:
        model = UsuarioSistema
        # Incluimos los campos basándonos en tu diseño gráfico
        fields = [
            'username', 'password', 'rol', 
            'mod_sala_computo', 'mod_auto_acceso', 'mod_biblioteca', 
            'mod_prestamos', 'mod_insumos', 'mod_tecnologicos'
        ]
        widgets = {
            'password': forms.PasswordInput(), # Convierte el texto en asteriscos
        }

    def save(self, commit=True):
        # Pausamos el guardado automático
        user = super().save(commit=False)
        # Encriptamos la contraseña de forma segura
        user.set_password(self.cleaned_data["password"])
        # Reanudamos el guardado
        if commit:
            user.save()
        return user


class AutoAccesoForm(forms.Form):
    numero_cuenta = forms.CharField(
        label='Número de cuenta',
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'sala-form-control',
            'autocomplete': 'off',
            'inputmode': 'numeric',
            'placeholder': 'Ingresa el número de cuenta',
            'data-auto-access-account': 'true',
        }),
    )
    motivo_uso = forms.ChoiceField(
        label='Motivo de acceso',
        choices=(
            ('', 'Selecciona el motivo'),
            ('Visita', 'Visita'),
            ('Conversacion', 'Conversación'),
        ),
        widget=forms.Select(attrs={
            'class': 'sala-form-control',
            'data-auto-access-reason': 'true',
        }),
    )

    def clean(self):
        cleaned_data = super().clean()
        numero_cuenta = (cleaned_data.get('numero_cuenta') or '').strip()
        if numero_cuenta:
            alumno = Persona.objects.con_perfiles('Alumno').filter(
                matricula=numero_cuenta,
            ).select_related('carrera', 'grupo').first()
            if alumno is None:
                self.add_error('numero_cuenta', 'No se encontró un alumno con ese número de cuenta.')
            else:
                cleaned_data['numero_cuenta'] = numero_cuenta
                cleaned_data['alumno'] = alumno
        return cleaned_data


#FUNCIONES PARA REGISTRO DE ACTIVIDADES EN SALA DE CÓMPUTO
class RegistroClaseForm(forms.Form):
    tipo_actividad = forms.ChoiceField(
        choices=(('regular', 'Clase regular'),),
        initial='regular',
        widget=forms.HiddenInput(),
    )
    numero_cuenta_docente = forms.CharField(
        label='Número de cuenta del docente',
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'sala-form-control',
            'autocomplete': 'off',
            'inputmode': 'numeric',
            'placeholder': 'Ingresa el número de cuenta',
            'data-docente-lookup': 'true',
        }),
    )
    docente_id = forms.IntegerField(widget=forms.HiddenInput(attrs={'data-docente-id': 'true'}))
    carrera = forms.ChoiceField(
        label='Carrera',
        choices=(),
        widget=forms.Select(attrs={'class': 'sala-form-control', 'data-carrera-select': 'true'}),
    )
    materia = forms.ChoiceField(
        label='Materia',
        choices=(),
        widget=forms.Select(attrs={'class': 'sala-form-control', 'data-materia-select': 'true'}),
    )
    grupo = forms.ChoiceField(
        label='Grupo',
        choices=(),
        widget=forms.Select(attrs={'class': 'sala-form-control', 'data-grupo-select': 'true'}),
    )
    fecha = forms.DateField(widget=forms.HiddenInput(attrs={'data-calendar-value': 'true'}))
    fecha_fin_repeticion = forms.DateField(
        label='Repetir hasta',
        initial=lambda: timezone.localdate() + timedelta(days=90),
        widget=forms.HiddenInput(attrs={'data-calendar-value': 'true'}),
    )
    hora_inicio = forms.TimeField(widget=forms.TimeInput(attrs={'class': 'sala-form-control', 'type': 'time'}))
    hora_fin = forms.TimeField(widget=forms.TimeInput(attrs={'class': 'sala-form-control', 'type': 'time'}))
    dias_repeticion = forms.MultipleChoiceField(
        label='Días de clase',
        choices=(
            ('0', 'Lunes'),
            ('1', 'Martes'),
            ('2', 'Miércoles'),
            ('3', 'Jueves'),
            ('4', 'Viernes'),
        ),
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, catalogos=None, **kwargs):
        super().__init__(*args, **kwargs)
        catalogos = catalogos or {}
        self.fields['carrera'].choices = [
            ('', 'Selecciona la carrera'),
            *[(str(item['id']), item['nombre']) for item in catalogos.get('carreras', [])],
        ]
        self.fields['materia'].choices = [
            ('', 'Selecciona la materia'),
            *[(str(item['id']), item['nombre']) for item in catalogos.get('materias', [])],
        ]
        self.fields['grupo'].choices = [
            ('', 'Selecciona el grupo'),
            *[(str(item['id']), item['nombre']) for item in catalogos.get('grupos', [])],
        ]
        if not self.is_bound:
            self.initial.setdefault('fecha', timezone.localdate())

    def clean_numero_cuenta_docente(self):
        numero_cuenta = self.cleaned_data['numero_cuenta_docente'].strip()
        try:
            return Persona.objects.con_perfiles('Docente').get(matricula=numero_cuenta)
        except Persona.DoesNotExist:
            raise forms.ValidationError('No se encontró un docente con ese número de cuenta.')

    def clean(self):
        cleaned_data = super().clean()
        docente = cleaned_data.get('numero_cuenta_docente')
        carrera_id = cleaned_data.get('carrera')
        if docente:
            if docente.carrera_id and str(docente.carrera_id) != str(carrera_id or ''):
                self.add_error('carrera', 'La carrera seleccionada no corresponde al docente.')
            if str(cleaned_data.get('docente_id') or '') != str(docente.pk):
                self.add_error('docente_id', 'Vuelve a buscar el número de cuenta del docente.')

        fecha_inicio = cleaned_data.get('fecha')
        fecha_fin = cleaned_data.get('fecha_fin_repeticion')
        dias = cleaned_data.get('dias_repeticion', [])
        hoy = timezone.localdate()
        if fecha_inicio and fecha_inicio < hoy:
            self.add_error('fecha', 'La fecha de inicio no puede ser anterior a hoy.')
        if fecha_fin and fecha_fin < hoy:
            self.add_error('fecha_fin_repeticion', 'La fecha final no puede ser anterior a hoy.')
        if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
            self.add_error('fecha_fin_repeticion', 'La fecha final debe ser igual o posterior a la fecha inicial.')
        if not dias:
            self.add_error('dias_repeticion', 'Selecciona al menos un día de la semana.')
        elif fecha_inicio and fecha_fin:
            dias_semana = {int(dia) for dia in dias}
            if not any(
                (fecha_inicio + timedelta(days=offset)).weekday() in dias_semana
                for offset in range((fecha_fin - fecha_inicio).days + 1)
            ):
                self.add_error('dias_repeticion', 'No hay días seleccionados dentro del periodo indicado.')

        hora_inicio = cleaned_data.get('hora_inicio')
        hora_fin = cleaned_data.get('hora_fin')
        if hora_inicio is not None:
            hora_inicio = cleaned_data['hora_inicio'] = normalizar_hora(hora_inicio)
        if hora_fin is not None:
            hora_fin = cleaned_data['hora_fin'] = normalizar_hora(hora_fin)
        if hora_inicio and hora_fin and hora_fin <= hora_inicio:
            self.add_error('hora_fin', 'La hora de término debe ser posterior a la hora de inicio.')
        elif (
            hora_inicio
            and fecha_inicio
            and fecha_fin
            and fecha_inicio <= hoy <= fecha_fin
            and str(hoy.weekday()) in dias
        ):
            hora_limite = (timezone.localtime() - timedelta(minutes=5)).time()
            if hora_inicio < hora_limite:
                self.add_error(
                    'hora_inicio',
                    'La hora de inicio ya pasó para la clase de hoy (fuera del margen de 5 minutos).',
                )
        return cleaned_data


class RegistroEventoForm(forms.Form):
    tipo_evento = forms.ChoiceField(
        label='Tipo de evento',
        choices=(('Taller', 'Taller'), ('Conferencia', 'Conferencia'), ('Clase', 'Clase')),
        widget=forms.Select(attrs={'class': 'sala-form-control'}),
    )
    nombre_evento = forms.CharField(
        label='Nombre del evento',
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'sala-form-control', 'maxlength': 100}),
    )
    pertenece_al_plantel = forms.ChoiceField(
        label='¿El ponente pertenece al plantel?',
        choices=(('', 'Selecciona una opción'), ('si', 'Sí'), ('no', 'No')),
        widget=forms.Select(attrs={'class': 'sala-form-control', 'data-ponente-interno': 'true'}),
    )
    numero_cuenta_ponente = forms.CharField(
        label='Número de cuenta del ponente',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'sala-form-control',
            'autocomplete': 'off',
            'inputmode': 'numeric',
            'data-cuenta-ponente': 'true',
        }),
    )
    nombre_ponente_interno = forms.CharField(
        label='Nombre del ponente',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'sala-form-control',
            'readonly': True,
            'data-nombre-ponente-interno': 'true',
        }),
    )
    persona_id = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput(attrs={'data-persona-ponente': 'true'}),
    )
    nombre_ponente_externo = forms.CharField(
        label='Nombre(s) del ponente externo',
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'sala-form-control', 'maxlength': 150}),
    )
    apellidos_ponente_externo = forms.CharField(
        label='Apellidos del ponente externo',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'sala-form-control', 'maxlength': 100}),
    )
    institucion_ponente_externo = forms.CharField(
        label='Institución del ponente externo',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'sala-form-control', 'maxlength': 100}),
    )
    fecha = forms.DateField(widget=forms.HiddenInput(attrs={'data-calendar-value': 'true'}))
    hora_inicio = forms.TimeField(widget=forms.TimeInput(attrs={'class': 'sala-form-control', 'type': 'time'}))
    hora_fin = forms.TimeField(widget=forms.TimeInput(attrs={'class': 'sala-form-control', 'type': 'time'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault('fecha', timezone.localdate())

    def clean(self):
        cleaned_data = super().clean()
        es_interno = cleaned_data.get('pertenece_al_plantel')
        cuenta = (cleaned_data.get('numero_cuenta_ponente') or '').strip()
        persona_id = cleaned_data.get('persona_id')
        nombre_externo = (cleaned_data.get('nombre_ponente_externo') or '').strip()
        apellidos_externo = (cleaned_data.get('apellidos_ponente_externo') or '').strip()

        if es_interno == 'si':
            if not cuenta:
                self.add_error('numero_cuenta_ponente', 'Ingresa el número de cuenta del ponente.')
            else:
                try:
                    persona = Persona.objects.con_perfiles('Administrador', 'Docente').get(
                        matricula=cuenta,
                    )
                except Persona.DoesNotExist:
                    self.add_error(
                        'numero_cuenta_ponente',
                        'No se encontró un administrador o docente con ese número de cuenta.',
                    )
                else:
                    if persona.pk != persona_id:
                        self.add_error('persona_id', 'Vuelve a buscar el número de cuenta del ponente.')
                    cleaned_data['persona'] = persona
        elif es_interno == 'no':
            if not nombre_externo:
                self.add_error('nombre_ponente_externo', 'Captura el nombre del ponente externo.')
            if not apellidos_externo:
                self.add_error('apellidos_ponente_externo', 'Captura los apellidos del ponente externo.')
            cleaned_data['persona'] = None
        else:
            self.add_error('pertenece_al_plantel', 'Indica si el ponente pertenece al plantel.')

        fecha = cleaned_data.get('fecha')
        hora_inicio = cleaned_data.get('hora_inicio')
        hora_fin = cleaned_data.get('hora_fin')
        if hora_inicio is not None:
            hora_inicio = cleaned_data['hora_inicio'] = normalizar_hora(hora_inicio)
        if hora_fin is not None:
            hora_fin = cleaned_data['hora_fin'] = normalizar_hora(hora_fin)
        hoy = timezone.localdate()
        if fecha and fecha < hoy:
            self.add_error('fecha', 'La fecha del evento no puede ser anterior a hoy.')
        if fecha == hoy and hora_inicio:
            hora_limite = (timezone.localtime() - timedelta(minutes=5)).time()
            if hora_inicio < hora_limite:
                self.add_error(
                    'hora_inicio',
                    'La hora de inicio ya pasó para el evento (fuera del margen de 5 minutos).',
                )
        if hora_inicio and hora_fin and hora_fin <= hora_inicio:
            self.add_error('hora_fin', 'La hora de término debe ser posterior a la hora de inicio.')
        return cleaned_data
