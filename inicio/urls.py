from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    # Redirige el favicon directamente a la ruta estática compilada
    path('favicon.ico', RedirectView.as_view(url='/static/inicio/images/icono-pag.png')),

    path('', views.login_view, name='login'),
    path('homePage/', views.homePage, name='homePage'),
    path('auto-acceso/', views.auto_acceso_view, name='auto_acceso'),
    path('auto-acceso/buscar-alumno/', views.buscar_alumno_auto_acceso_view, name='buscar_alumno_auto_acceso'),

    # Ruta para la vista de auditoría y reportes
    path('auditoria-reportes/', views.auditoria_reportes_view, name='auditoria_reportes'),
    path('exportar-auditoria/', views.exportar_auditoria_excel, name='exportar_auditoria'),

    

    # Rutas de la sala de computo
    path('sala_computo/', views.sala_computo_view, name='sala_computo'),
    path('sala-computo/buscar-docente/', views.buscar_docente_sala_view, name='buscar_docente_sala'),
    path('sala-computo/catalogos-clase/', views.catalogos_clase_docente_view, name='catalogos_clase_docente'),
    path('sala-computo/buscar-ponente/', views.buscar_ponente_sala_view, name='buscar_ponente_sala'),
    path('sala-computo/clases-registro/', views.clases_registro_view, name='clases_registro'),
    path('sala-computo/buscar-clases-registro/', views.buscar_clases_registro_view, name='buscar_clases_registro'),
    path('sala-computo/alumnos-clase/', views.alumnos_clase_registro_view, name='alumnos_clase_registro'),
    path('sala-computo/eventos-registro/', views.eventos_registro_view, name='eventos_registro'),
    path('sala-computo/buscar-alumno/', views.alumnos_busqueda_view, name='buscar_alumno_sala'),
    path('sala-computo/equipos-disponibles/', views.equipos_sala_view, name='equipos_sala'),
    path('sala-computo/registrar-entrada/', views.registrar_entrada_view, name='registrar_entrada_sala'),
    path('sala-computo/registrar-asistencia/', views.registrar_asistencia_view, name='registrar_asistencia_sala'),
    path('sala-computo/buscar-salida/', views.buscar_salida_view, name='buscar_salida_sala'),
    path('sala-computo/registrar-salida/', views.registrar_salida_view, name='registrar_salida_sala'),
    path('sala-computo/historial-equipo/', views.historial_equipo_view, name='historial_equipo_sala'),
    path('sala-computo/registrar-incidencia/', views.registrar_incidencia_view, name='registrar_incidencia_sala'),

    #Ruta para la vista de agregar usuario y logout
    path('agregar-usuario/', views.agregar_usuario_view, name='agregar_usuario'),
    # Ruta obligatoria para que el botón de cerrar sesión funcione
    path('auditoria-reportes/', views.auditoria_reportes_view, name='auditoria_reportes'),
    path('exportar-auditoria/', views.exportar_auditoria_excel, name='exportar_auditoria'),
    path('logout/', views.logout_view, name='logout'),

   
]