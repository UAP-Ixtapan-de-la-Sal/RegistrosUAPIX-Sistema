import os #Owen
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone #Owen
from django.conf import settings #Owen
from django.http import HttpResponse, JsonResponse #Owen
from openpyxl import load_workbook #Owen
from .models import Persona, UsuarioSistema
from openpyxl.drawing.image import Image  # Para insertar imágenes en Excel
from .forms import RegistroUsuarioForm  # Importamos tu nuevo escudo de seguridad
from datetime import datetime
from .forms import RegistroClaseForm, RegistroEventoForm  # YES -Importamos los formularios de clase y evento 
from .models import (Registro) #Owen

# AQUI EMPEZO A MODIFICAR OWEN
def exportar_auditoria_excel(request):
    ruta_plantilla = os.path.join(settings.BASE_DIR, 'inicio', 'plantillas', 'plantilla_auditoria.xlsx')
    workbook = load_workbook(ruta_plantilla)
    hoja = workbook.active

    # === 1. TÍTULO DINÁMICO ===
    fecha_actual = timezone.localtime().strftime('%d/%m/%Y')
    
    # Celda del título según tu nuevo formato en la imagen
    hoja['B3'] = f"Registro del día: {fecha_actual}"

    # === 2. INSERCIÓN DE LOGOS POR CÓDIGO ===
    # Logo Izquierdo
    ruta_logo_izq = os.path.join(settings.BASE_DIR, 'inicio', 'plantillas', 'logo_izq.png')
    if os.path.exists(ruta_logo_izq):
        img_izq = Image(ruta_logo_izq)
        img_izq.width = 90  # Puedes ajustar el ancho en píxeles según tu diseño
        img_izq.height = 90  # Puedes ajustar el alto en píxeles
        hoja.add_image(img_izq, 'A1')  # Ubica el logo en la celda A1

    # Logo Derecho
    ruta_logo_der = os.path.join(settings.BASE_DIR, 'inicio', 'plantillas', 'logo_der.png')
    if os.path.exists(ruta_logo_der):
        img_der = Image(ruta_logo_der)
        img_der.width = 170
        img_der.height = 85
        hoja.add_image(img_der, 'F1')  # Ubica el logo en la celda F1 (o la columna que prefieras)

    # === 2. INYECCIÓN DE DATOS DE HISTORIAL ===
    historial_registros = Registro.history.all().order_by('-history_date')

    # Comenzamos a inyectar datos debajo de los encabezados (Fila 5 según tu Excel)
    fila_actual = 5
    for registro in historial_registros:
        if registro.history_type == '+':
            accion = 'Creación'
        elif registro.history_type == '~':
            accion = 'Modificación'
        else:
            accion = 'Eliminación'

        operador = registro.history_user.username if registro.history_user else 'Sistema'
        hora_mexico = timezone.localtime(registro.history_date)

        hoja.cell(row=fila_actual, column=1, value=hora_mexico.strftime('%d/%m/%y %I:%M %p'))
        hoja.cell(row=fila_actual, column=2, value=operador)
        hoja.cell(row=fila_actual, column=3, value=registro.modulo)
        hoja.cell(row=fila_actual, column=4, value=registro.tipo_registro or 'N/A')
        hoja.cell(row=fila_actual, column=5, value=accion)
        hoja.cell(row=fila_actual, column=6, value=registro.observaciones or 'Sin observaciones')

        fila_actual += 1

    # === 3. DESCARGA DEL ARCHIVO ===
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="Auditoria_UAPIX_{fecha_actual.replace("/", "-")}.xlsx"'
    workbook.save(response)
    
    return response
# Hasta aqui modifico Owen

# 1. VISTA DE LOGIN
def login_view(request):
    if request.method == 'POST':
        username_ingresado = request.POST.get('usuario')
        password_ingresado = request.POST.get('contrasena')
        
        user = authenticate(request, username=username_ingresado, password=password_ingresado)
        
        if user is not None:
            login(request, user)
            request.session['mostrar_splash_inicio'] = True
            
            # Inicializamos el sello de tiempo estricto para el administrador
            request.session['ultima_actividad'] = datetime.now().timestamp()
            request.session.pop('admin_reautenticado', None)
            request.session.modified = True
            
            return redirect('homePage')
        else:
            messages.error(request, "Usuario o contraseña incorrectos.")
            
    return render(request, 'inicio/login.html')

# 2. VISTA DEL HOMEPAGE (Con control de inactividad de 1 min solo para superusuario)
@login_required
def homePage(request):
    if request.user.is_superuser:
        ahora = datetime.now().timestamp()
        
        # Si no existe un registro previo, lo inicializamos
        if 'ultima_actividad' not in request.session:
            request.session['ultima_actividad'] = ahora
            request.session.modified = True
            
        ultima_actividad = request.session.get('ultima_actividad')
        
        # Evaluamos si han pasado más de 300 segundos (5 minutos) desde la última actividad
        if (ahora - ultima_actividad) > 300:
            logout(request)
            messages.error(request, "Sesión de administrador cerrada por inactividad de seguridad.")
            return redirect('login')
            
        # Actualizamos la marca de tiempo solo si el usuario interactúa explícitamente
        request.session['ultima_actividad'] = ahora
        request.session.modified = True
        
    # Los operadores comunes trabajan todo el día sin restricciones
    mostrar_splash = request.session.pop('mostrar_splash_inicio', False)
    return render(request, 'inicio/homePage.html', {'mostrar_splash': mostrar_splash})

# 3. CANDADO DE SEGURIDAD
def es_admin_general(user):
    return user.is_superuser

# 4. VISTA PARA AGREGAR USUARIO
@login_required
@user_passes_test(es_admin_general, login_url='homePage')
def agregar_usuario_view(request):
    if request.method == 'POST':
        form = RegistroUsuarioForm(request.POST)
        
        if form.is_valid():
            form.save() 
            messages.success(request, "¡Usuario y Permisos Guardados Exitosamente!")
            return redirect('agregar_usuario')
        else:
            messages.error(request, "Error al crear el usuario. Verifica los datos ingresados.")
    else:
        form = RegistroUsuarioForm()

    return render(request, 'inicio/agregar_usuario.html', {'form': form})

# 5. VISTA DE LOGOUT
def logout_view(request):
    logout(request)
    return redirect('login')

#6. VISTA DE AUDITORÍA Y REPORTES
@login_required
@user_passes_test(es_admin_general, login_url='homePage')
def auditoria_reportes_view(request):
    # Lógica para la vista de auditoría y reportes
    return render(request, 'inicio/auditoria_reportes.html')

#7. VISTA DE RESPALDOS DE BASE DE DATOS
@login_required
@user_passes_test(es_admin_general, login_url='homePage')
def respaldos_bd_view(request):
    # Lógica para la vista de respaldos de base de datos
    return render(request, 'inicio/respaldos_bd.html')


#8. VISTAS DE SALA DE COMPUTO    --YES
def sala_computo_view(request):
    es_envio_clase = request.method == 'POST' and request.POST.get('categoria') == 'clase'
    es_envio_evento = request.method == 'POST' and request.POST.get('categoria') == 'evento'
    clase_form = RegistroClaseForm(request.POST if es_envio_clase else None)
    evento_form = RegistroEventoForm(request.POST if es_envio_evento else None)
    if es_envio_clase and clase_form.is_valid():
        messages.info(
            request,
            'Las fechas y el horario son válidos. El registro de clases aún no se guarda desde este formulario.',
        )
    if es_envio_evento and evento_form.is_valid():
        messages.info(
            request,
            'La fecha y el horario son válidos. El registro de eventos aún no se guarda desde este formulario.',
        )

    contexto = {
        'clase_form': clase_form,
        'evento_form': evento_form,
        'active_schedule_view': 'clase' if es_envio_clase else 'evento' if es_envio_evento else '',
    }
    return render(request, 'inicio/sala_computo/sala_computo.html', contexto)

def buscar_docente_sala_view(request):
    return render(request, 'inicio/sala_computo/buscar_docente_sala.html')
def catalogos_clase_docente_view(request):
    return render(request, 'inicio/sala_computo/catalogos_clase_docente.html')  
def buscar_ponente_sala_view(request):
    if request.method != 'GET':
        return JsonResponse({'encontrado': False, 'error': 'Método no permitido.'}, status=405)

    cuenta = request.GET.get('cuenta', '').strip()
    if not cuenta:
        return JsonResponse({'encontrado': False, 'error': 'Ingresa el número de cuenta del ponente.'}, status=400)

    persona = Persona.objects.con_perfiles('Administrador', 'Docente').filter(
        matricula=cuenta,
    ).first()
    if persona is None:
        return JsonResponse({
            'encontrado': False,
            'error': 'No se encontró un administrador o docente con ese número de cuenta.',
        }, status=404)

    return JsonResponse({
        'encontrado': True,
        'persona_id': persona.pk,
        'nombre': f'{persona.nombre} {persona.apellidos}'.strip(),
    })

@login_required
@user_passes_test(es_admin_general, login_url='homePage')
def auditoria_reportes_view(request):
    # Lógica para la vista de auditoría y reportes
    return render(request, 'inicio/auditoria_reportes.html')
