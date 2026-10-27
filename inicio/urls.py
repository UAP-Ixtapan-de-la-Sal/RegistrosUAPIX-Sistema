from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    # Redirige el favicon directamente a la ruta estática compilada
    path('favicon.ico', RedirectView.as_view(url='/static/inicio/images/icono-pag.png')),

    path('', views.login_view, name='login'),
    path('homePage/', views.homePage, name='homePage'),
    path('sala_computo/', views.sala_computo_view, name='sala_computo'),
    path('sala-computo/buscar-docente/', views.buscar_docente_sala_view, name='buscar_docente_sala'),
    path('sala-computo/catalogos-clase/', views.catalogos_clase_docente_view, name='catalogos_clase_docente'),
    path('sala-computo/buscar-ponente/', views.buscar_ponente_sala_view, name='buscar_ponente_sala'),
    path('agregar-usuario/', views.agregar_usuario_view, name='agregar_usuario'),
    path('exportar-auditoria/', views.exportar_auditoria_excel, name='auditoria_reportes'),
    # Ruta obligatoria para que el botón de cerrar sesión funcione
    path('logout/', views.logout_view, name='logout'),
]