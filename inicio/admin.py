#VERSION SERVIBLE
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from simple_history.admin import SimpleHistoryAdmin

# MODIFICACIÓN: Importamos todos los nuevos modelos creados para la Sala de Cómputo
from .models import (
    UsuarioSistema, Persona, Carrera, Materia, 
    Grupo, Clase, EventoTallerConferencia, Equipo, Registro, Externo
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
@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    list_display = ('matricula', 'nombre', 'apellidos', 'perfil')
    search_fields = ('matricula', 'nombre', 'apellidos')
    list_filter = ('perfil',)


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
    list_display = ('id_materia', 'nombre_materia', 'carrera') 
    search_fields = ('nombre_materia',)
    list_filter = ('carrera',) 

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
