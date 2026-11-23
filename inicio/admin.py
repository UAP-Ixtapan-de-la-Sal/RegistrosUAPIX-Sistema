#VERSION SERVIBLE
from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from simple_history.admin import SimpleHistoryAdmin
from django.db.models import DateTimeField, Q, TimeField
from .forms_persona_admin import PersonaAdminForm

# MODIFICACIÓN: Importamos todos los nuevos modelos creados para la Sala de Cómputo
from .models import (
    UsuarioSistema, Persona, Carrera, Materia, 
    Grupo, Clase, EventoTallerConferencia, Equipo, Registro, Externo, PersonaPerfil,
    Asistencia, BitacoraFalla,
    ImplementoTecnologico, Prestamo, DetallePrestamo, CategoriaInsumo, Insumo, MovimientoInventario,
    PERFILES_PERSONA,
)

@admin.register(UsuarioSistema)
class UsuarioSistemaAdmin(UserAdmin):
    # 1. Las columnas que verás en la tabla principal del panel
    list_display = ('username', 'rol', 'mod_sala_computo', 'mod_prestamos', 'is_superuser')
    
    # 2. Filtros para buscar usuarios rápidamente por rol
    list_filter = ('rol', 'is_superuser')

    # 3. Esto es clave: Agrega tus checkboxes a la pantalla de editar usuario
    fieldsets = UserAdmin.fieldsets + (
        ('Configuración de Roles y Módulos UAPIX', {
            'fields': (
                'rol', 
                'mod_sala_computo', 
                'mod_auto_acceso', 
                'mod_biblioteca', 
                'mod_prestamos', 
                'mod_insumos', 
                'mod_tecnologicos'
            )
        }),
    )

# Dejamos la tabla Persona lista por si quieren ir agregando alumnos manuales después
class PerfilPersonaFilter(admin.SimpleListFilter):
    title = 'perfil institucional'
    parameter_name = 'perfil_institucional'

    def lookups(self, request, model_admin):
        return PERFILES_PERSONA

    def queryset(self, request, queryset):
        if self.value() in dict(PERFILES_PERSONA):
            return queryset.filter(Q(perfil=self.value()) | Q(perfiles__perfil=self.value())).distinct()
        return queryset


@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    form = PersonaAdminForm
    list_display = ('matricula', 'nombre', 'apellidos', 'perfiles_institucionales', 'carrera', 'grupo')
    search_fields = ('matricula', 'nombre', 'apellidos')
    list_filter = (PerfilPersonaFilter, 'carrera', 'grupo')

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('perfiles')

    @admin.display(description='Perfiles institucionales')
    def perfiles_institucionales(self, obj):
        return ', '.join(sorted(obj.perfiles_actuales))

    def save_model(self, request, obj, form, change):
        obj._history_user = request.user
        obj._change_reason = 'Gestión de perfiles en Django Admin'
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        selected = form.cleaned_data['perfiles_institucionales']
        for membership in form.instance.perfiles.exclude(perfil__in=selected):
            membership._history_user = request.user
            membership._change_reason = 'Gestión de perfiles en Django Admin'
            membership.delete()
        existing = set(form.instance.perfiles.values_list('perfil', flat=True))
        for perfil in selected - existing:
            membership = PersonaPerfil(persona=form.instance, perfil=perfil)
            membership._history_user = request.user
            membership._change_reason = 'Gestión de perfiles en Django Admin'
            membership.full_clean()
            membership.save()


# ==========================================
# === NUEVO APARTADO: CATÁLOGOS ACADÉMICOS ===
# ==========================================

@admin.register(Carrera)
class CarreraAdmin(admin.ModelAdmin):
    list_display = ('id_carrera', 'nombre_carrera')
    search_fields = ('nombre_carrera',)

@admin.register(Materia)
class MateriaAdmin(admin.ModelAdmin):
    # Cambiamos 'id_carrera' por 'carrera' en list_display
    list_display = ('id_materia', 'nombre_materia', 'carrera', 'semestre')
    search_fields = ('nombre_materia',)
    list_filter = ('carrera', 'semestre')

@admin.register(Grupo)
class GrupoAdmin(admin.ModelAdmin):
    # Cambiamos 'id_carrera' por 'carrera' en list_display y list_filter
    list_display = ('id_grupo', 'nombre_grupo', 'semestre', 'turno', 'carrera')
    list_filter = ('semestre', 'turno', 'carrera')

@admin.register(Clase)
class ClaseAdmin(admin.ModelAdmin):
    # Actualizamos los nombres de las columnas para que coincidan con el modelo modificado
    list_display = ('id_clase', 'materia', 'grupo', 'docente', 'fecha', 'hora_inicio', 'hora_fin')
    # Agregamos filtros laterales rápidos
    list_filter = ('fecha', 'materia', 'grupo')
    # SOLUCIÓN DE UX PARA FECHAS: Esto crea una barra de navegación cronológica (Año > Mes > Día)
    date_hierarchy = 'fecha'


@admin.register(Externo)
class ExternoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'apellidos', 'institucion')
    search_fields = ('nombre', 'apellidos')

@admin.register(EventoTallerConferencia)
class EventoAdmin(SimpleHistoryAdmin):
    # Agregamos 'clase' a la lista para que Jaz lo vea de inmediato en el panel
    list_display = ('nombre_evento', 'tipo_evento', 'tipo_ponente', 'clase', 'fecha', 'hora_inicio', 'estado_bloque')
    list_filter = ('tipo_evento', 'tipo_ponente', 'clase', 'fecha', 'estado_bloque')
    search_fields = ('nombre_evento',)
    date_hierarchy = 'fecha'

# =======================================================
# === NUEVO APARTADO: EQUIPOS Y REGISTROS (SALA CÓMPUTO) ===
# =======================================================

@admin.register(Equipo)
class EquipoAdmin(SimpleHistoryAdmin):
    list_display = ('no_equipo', 'no_bien_patrimonial', 'lugar', 'estado', 'condicion')
    list_filter = ('lugar', 'estado', 'condicion')
    search_fields = ('no_equipo', 'no_bien_patrimonial')

@admin.register(Registro)
class RegistroAdmin(SimpleHistoryAdmin):
    # Actualizamos los nombres de las columnas (quitamos los id_) y agregamos hora_entrada
    list_display = ('id_registro', 'fecha', 'hora_entrada', 'hora_salida', 'modulo', 'tipo_registro', 'persona', 'equipo')
    
    list_filter = ('fecha', 'modulo', 'tipo_registro')
    
    # Para buscar por persona, ahora usamos "persona__nombre" en lugar de "id_persona__nombre"
    search_fields = ('persona__nombre', 'persona__matricula')
    
    # También le ponemos su barra de fechas para que Jaz pueda buscar rápido
    date_hierarchy = 'fecha'

@admin.register(Asistencia)
class AsistenciaAdmin(SimpleHistoryAdmin):
    list_display = ('clase', 'alumno', 'estado', 'equipo', 'registro')
    list_filter = ('estado', 'clase__fecha')
    search_fields = ('alumno__matricula', 'alumno__nombre', 'alumno__apellidos')

class BitacoraFallaAdminForm(forms.ModelForm):
    prioridad_alta = forms.TypedChoiceField(
        label='Prioridad alta',
        choices=(('', 'Selecciona'), ('True', 'Sí'), ('False', 'No')),
        coerce=lambda value: value == 'True',
        empty_value=None,
        required=False,
    )
    CAMPOS_REPORTE = (
        'lugar', 'categoria_falla', 'componente_afectado', 'prioridad_alta',
        'condicion', 'estado', 'usuario_sistema',
    )

    class Meta:
        model = BitacoraFalla
        fields = (
            'lugar', 'equipo', 'implemento', 'categoria_falla', 'componente_afectado',
            'prioridad_alta', 'condicion', 'estado', 'descripcion_falla',
            'usuario_sistema', 'observaciones',
        )
        labels = {
            'condicion': 'Condición',
            'estado': 'Estado',
        }
        help_texts = {
            'equipo': 'Selecciona un equipo o un implemento, únicamente uno.',
            'implemento': 'Déjalo vacío si seleccionaste un equipo.',
            'condicion': 'Describe la situación física del objeto al momento del reporte.',
            'estado': 'Describe su disponibilidad al momento del reporte.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre in self.CAMPOS_REPORTE:
            if nombre not in self.fields:
                continue
            campo = self.instance._meta.get_field(nombre)
            valor_anterior = getattr(self.instance, campo.attname)
            # Las altas capturan el reporte completo. El legado puede conservar
            # valores desconocidos; un valor ya capturado no se vuelve vacío.
            self.fields[nombre].required = (
                self.instance._state.adding or valor_anterior not in (None, '')
            )
            if not self.fields[nombre].required:
                self.fields[nombre].help_text += (
                    ' Dato no capturado originalmente; puede permanecer sin dato.'
                )
        for nombre in ('equipo', 'implemento'):
            if nombre in self.fields:
                self.fields[nombre].required = False


@admin.register(BitacoraFalla)
class BitacoraFallaAdmin(SimpleHistoryAdmin):
    form = BitacoraFallaAdminForm
    list_display = (
        'id_falla', 'equipo', 'implemento', 'categoria_falla', 'condicion',
        'estado', 'prioridad_alta', 'usuario_sistema', 'fecha_reporte',
    )
    list_filter = (
        'estado', 'condicion', 'prioridad_alta', 'fecha_reporte',
    )
    search_fields = (
        'equipo__no_equipo', 'equipo__no_bien_patrimonial', 'implemento__codigo_interno',
        'lugar', 'categoria_falla', 'componente_afectado', 'descripcion_falla',
    )
    list_select_related = ('equipo', 'implemento', 'usuario_sistema')
    date_hierarchy = 'fecha_reporte'
    readonly_fields = ('fecha_reporte',)

    def get_fields(self, request, obj=None):
        campos = self.form.Meta.fields
        if obj is not None:
            campos += ('fecha_reporte',)
        return campos


class CapturaManualAdmin(SimpleHistoryAdmin):
    """Captura estándar con historial; sin borrados ni acciones operativas."""

    actions = None
    formfield_overrides = {
        DateTimeField: {
            'form_class': forms.DateTimeField,
            'widget': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'type': 'datetime-local', 'step': 60},
            ),
            'input_formats': ('%Y-%m-%dT%H:%M',),
        },
        TimeField: {
            'widget': forms.TimeInput(
                format='%H:%M', attrs={'type': 'time', 'step': 60},
            ),
            'input_formats': ('%H:%M',),
        },
    }

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_history_permission(self, request, obj=None):
        return False

    def revert_disabled(self, request, obj=None):
        return True

    def history_form_view(self, request, object_id, version_id, extra_context=None):
        if request.method not in ('GET', 'HEAD'):
            raise PermissionDenied('El historial está disponible solo para consulta.')
        return super().history_form_view(request, object_id, version_id, extra_context)


@admin.register(ImplementoTecnologico)
class ImplementoTecnologicoAdmin(CapturaManualAdmin):
    list_display = (
        'codigo_interno', 'tipo_implemento', 'numero_bien_patrimonial',
        'marca', 'modelo', 'estado', 'condicion',
    )
    list_filter = ('estado', 'condicion', 'tipo_implemento')
    search_fields = (
        'codigo_interno', 'tipo_implemento', 'numero_bien_patrimonial',
        'serie', 'marca', 'modelo',
    )
    ordering = ('codigo_interno',)


@admin.register(Prestamo)
class PrestamoAdmin(CapturaManualAdmin):
    list_display = (
        'id_prestamo', 'persona_solicitante', 'operador_prestamo',
        'fecha_hora_prestamo', 'fecha_hora_devolucion_prevista', 'lugar_destino',
    )
    list_filter = ('fecha_hora_prestamo', 'operador_prestamo')
    search_fields = (
        'persona_solicitante__matricula', 'persona_solicitante__nombre',
        'persona_solicitante__apellidos', 'operador_prestamo__username',
        'lugar_destino', 'uso_prestamo',
    )
    list_select_related = ('persona_solicitante', 'operador_prestamo')
    autocomplete_fields = ('persona_solicitante', 'operador_prestamo')
    date_hierarchy = 'fecha_hora_prestamo'
    ordering = ('-fecha_hora_prestamo', '-id_prestamo')


@admin.register(DetallePrestamo)
class DetallePrestamoAdmin(CapturaManualAdmin):
    list_display = (
        'id_detalle_prestamo', 'prestamo', 'implemento', 'condicion_salida',
        'fecha_hora_devolucion', 'persona_devuelve', 'condicion_devolucion',
    )
    list_filter = ('condicion_salida', 'condicion_devolucion', 'fecha_hora_devolucion')
    search_fields = (
        'prestamo__persona_solicitante__matricula',
        'prestamo__persona_solicitante__nombre',
        'prestamo__persona_solicitante__apellidos', 'implemento__codigo_interno',
        'persona_devuelve__matricula', 'persona_devuelve__nombre',
    )
    list_select_related = ('prestamo', 'implemento', 'persona_devuelve')
    autocomplete_fields = ('prestamo', 'implemento', 'persona_devuelve', 'operador_devolucion')
    ordering = ('-id_detalle_prestamo',)


admin.site.register(CategoriaInsumo)


@admin.register(Insumo)
class InsumoAdmin(CapturaManualAdmin):
    list_display = (
        'nombre_insumo', 'categoria', 'unidad_medida',
        'existencia_actual', 'stock_minimo', 'activo',
    )
    list_filter = ('categoria', 'activo')
    search_fields = ('nombre_insumo', 'unidad_medida')
    ordering = ('nombre_insumo',)


@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(CapturaManualAdmin):
    list_display = (
        'id_movimiento', 'insumo', 'tipo_movimiento', 'cantidad', 'fecha',
        'hora', 'persona', 'operador', 'area_destino',
    )
    list_filter = ('tipo_movimiento', 'fecha', 'insumo__categoria')
    search_fields = (
        'insumo__nombre_insumo', 'proveedor', 'area_destino',
        'persona__matricula', 'persona__nombre', 'persona__apellidos',
        'operador__username', 'observaciones',
    )
    list_select_related = ('insumo', 'persona', 'operador')
    autocomplete_fields = ('insumo', 'persona', 'operador')
    date_hierarchy = 'fecha'
    ordering = ('-fecha', '-hora', '-id_movimiento')
