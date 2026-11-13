import os #Owen
import json
from datetime import datetime, timedelta
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone #Owen
from django.conf import settings #Owen
from django.http import HttpResponse, JsonResponse #Owen
from openpyxl import load_workbook #Owen
from .models import (
    Asistencia, Carrera, Clase, Equipo, EventoTallerConferencia, Externo, Grupo, Incidencia,
    Materia, Persona, Registro, UsuarioSistema,
)
from openpyxl.drawing.image import Image  # Para insertar imágenes en Excel
from .forms import AutoAccesoForm, RegistroUsuarioForm  # Importamos tu nuevo escudo de seguridad
from .forms import RegistroClaseForm, RegistroEventoForm  # YES -Importamos los formularios de clase y evento 


def _ordenar_equipos_por_numero(equipos):
    def clave(equipo):
        numero = equipo.no_equipo.strip()
        if numero.isdecimal():
            return (0, int(numero), numero.casefold())
        return (1, 0, numero.casefold())

    return sorted(equipos, key=clave)


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


def puede_acceder_auto_acceso(user):
    return user.is_superuser or user.mod_auto_acceso


@login_required
@user_passes_test(puede_acceder_auto_acceso, login_url='homePage')
def auto_acceso_view(request):
    form = AutoAccesoForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        ahora = timezone.localtime()
        registro = Registro(
            modulo='Auto_Acceso',
            motivo_uso=form.cleaned_data['motivo_uso'],
            fecha=ahora.date(),
            hora_entrada=ahora.time(),
            persona=form.cleaned_data['alumno'],
            registrado_por=request.user,
        )
        try:
            with transaction.atomic():
                registro.save()
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'La entrada de Auto Acceso se registró correctamente.')
            return redirect('auto_acceso')
    return render(request, 'inicio/auto_acceso.html', {'form': form})


@login_required
@user_passes_test(puede_acceder_auto_acceso, login_url='homePage')
def buscar_alumno_auto_acceso_view(request):
    if request.method != 'GET':
        return JsonResponse({'encontrado': False, 'error': 'Método no permitido.'}, status=405)

    cuenta = request.GET.get('cuenta', '').strip()
    if not cuenta:
        return JsonResponse({'encontrado': False, 'error': 'Ingresa el número de cuenta del alumno.'}, status=400)

    alumno = Persona.objects.con_perfiles('Alumno').select_related(
        'carrera', 'grupo',
    ).filter(matricula=cuenta).first()
    if alumno is None:
        return JsonResponse({'encontrado': False, 'error': 'No se encontró un alumno con ese número de cuenta.'}, status=404)
    return JsonResponse({
        'encontrado': True,
        'nombre': alumno.nombre,
        'apellidos': alumno.apellidos,
        'carrera': alumno.carrera.nombre_carrera if alumno.carrera_id else '',
        'grupo': str(alumno.grupo) if alumno.grupo_id else '',
    })


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
    catalogos_clase = _catalogos_clase_por_carrera()
    if es_envio_clase:
        cuenta = request.POST.get('numero_cuenta_docente', '').strip()
        carrera_id = request.POST.get('carrera', '')
        docente = Persona.objects.con_perfiles('Docente').select_related('carrera').filter(
            matricula=cuenta,
        ).first()
        if docente and docente.carrera_id:
            catalogos_clase = _catalogos_clase_por_carrera(docente.carrera, docente)
        elif docente:
            carrera = Carrera.objects.filter(pk=carrera_id).first() if carrera_id.isdecimal() else None
            catalogos_clase = _catalogos_clase_por_carrera(carrera, docente)

    clase_form = RegistroClaseForm(
        request.POST if es_envio_clase else None,
        catalogos=catalogos_clase,
    )
    evento_form = RegistroEventoForm(request.POST if es_envio_evento else None)
    if es_envio_clase and clase_form.is_valid():
        datos = clase_form.cleaned_data
        fechas = [
            datos['fecha'] + timedelta(days=offset)
            for offset in range((datos['fecha_fin_repeticion'] - datos['fecha']).days + 1)
            if (datos['fecha'] + timedelta(days=offset)).weekday() in {
                int(dia) for dia in datos['dias_repeticion']
            }
        ]
        clases = [
            Clase(
                materia_id=datos['materia'],
                grupo_id=datos['grupo'],
                docente=datos['numero_cuenta_docente'],
                fecha=fecha,
                hora_inicio=datos['hora_inicio'],
                hora_fin=datos['hora_fin'],
            )
            for fecha in fechas
        ]
        with transaction.atomic():
            Clase.objects.bulk_create(clases)
        messages.success(request, f'Se registraron {len(clases)} fechas de clase.')
        return redirect('sala_computo')
    if es_envio_evento and evento_form.is_valid():
        datos = evento_form.cleaned_data
        with transaction.atomic():
            ponente_externo = None
            tipo_ponente = 'Interno'
            if datos['pertenece_al_plantel'] == 'no':
                tipo_ponente = 'Externo'
                ponente_externo = Externo.objects.create(
                    nombre=datos['nombre_ponente_externo'].strip(),
                    apellidos=datos['apellidos_ponente_externo'].strip(),
                    institucion=datos['institucion_ponente_externo'].strip() or None,
                )
            EventoTallerConferencia.objects.create(
                tipo_evento=datos['tipo_evento'],
                nombre_evento=datos['nombre_evento'].strip(),
                tipo_ponente=tipo_ponente,
                ponente_interno=datos.get('persona'),
                ponente_externo=ponente_externo,
                fecha=datos['fecha'],
                hora_inicio=datos['hora_inicio'],
                hora_fin=datos['hora_fin'],
            )
        messages.success(request, 'El evento se guardó correctamente.')
        return redirect('sala_computo')

    equipos_sala = Equipo.objects.filter(lugar='Sala')
    total_equipos = equipos_sala.count()
    equipos_ocupados = equipos_sala.filter(estado='Ocupado').count()
    registros = Registro.objects.filter(modulo='Sala_Computo').select_related(
        'persona', 'externo', 'equipo', 'clase__materia', 'clase__grupo', 'evento',
    ).order_by('-fecha', '-hora_entrada')
    contexto = {
        'clase_form': clase_form,
        'evento_form': evento_form,
        'active_schedule_view': 'clase' if es_envio_clase else 'evento' if es_envio_evento else '',
        'equipos_total': total_equipos,
        'equipos_ocupados': equipos_ocupados,
        'equipos_disponibles': equipos_sala.filter(estado='Disponible').count(),
        'equipos_ocupados_porcentaje': round(equipos_ocupados * 100 / total_equipos) if total_equipos else 0,
        'fecha_hoy': timezone.localdate().isoformat(),
        'historial_registros': registros,
    }
    return render(request, 'inicio/sala_computo/sala_computo.html', contexto)

def buscar_docente_sala_view(request):
    if request.method != 'GET':
        return JsonResponse({'encontrado': False, 'error': 'Método no permitido.'}, status=405)

    cuenta = request.GET.get('cuenta', '').strip()
    if not cuenta:
        return JsonResponse({'encontrado': False, 'error': 'Ingresa el número de cuenta del docente.'}, status=400)

    docente = Persona.objects.con_perfiles('Docente').select_related('carrera').filter(
        matricula=cuenta,
    ).first()
    if docente is None:
        return JsonResponse({
            'encontrado': False,
            'error': 'No se encontró un docente con ese número de cuenta.',
        }, status=404)

    return JsonResponse({
        'encontrado': True,
        'persona_id': docente.pk,
        'nombre': f'{docente.nombre} {docente.apellidos}'.strip(),
        'carrera_id': docente.carrera_id,
        'carrera': docente.carrera.nombre_carrera if docente.carrera_id else '',
    })


def _catalogos_clase_por_carrera(carrera=None, docente=None):
    carreras = (
        [docente.carrera]
        if docente and docente.carrera_id
        else Carrera.objects.order_by('nombre_carrera')
    )
    return {
        'carreras': [{'id': item.pk, 'nombre': item.nombre_carrera} for item in carreras],
        'materias': [
            {'id': materia.pk, 'nombre': materia.nombre_materia}
            for materia in Materia.objects.filter(carrera=carrera).order_by('nombre_materia')
        ],
        'grupos': [
            {'id': grupo.pk, 'nombre': str(grupo)}
            for grupo in Grupo.objects.filter(carrera=carrera).order_by(
                'nombre_grupo', 'semestre', 'turno',
            )
        ],
    }


def catalogos_clase_docente_view(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido.'}, status=405)

    cuenta = request.GET.get('cuenta', '').strip()
    carrera_id = request.GET.get('carrera', '').strip()
    if not cuenta or not carrera_id:
        return JsonResponse({
            'error': 'Indica el número de cuenta del docente y la carrera.',
        }, status=400)

    docente = Persona.objects.con_perfiles('Docente').select_related('carrera').filter(
        matricula=cuenta,
    ).first()
    if docente is None:
        return JsonResponse({'error': 'No se encontró un docente con ese número de cuenta.'}, status=404)
    if docente.carrera_id and str(docente.carrera_id) != carrera_id:
        return JsonResponse({'error': 'La carrera seleccionada no corresponde al docente.'}, status=400)
    if not carrera_id.isdecimal():
        return JsonResponse({'error': 'Selecciona una carrera válida.'}, status=400)
    carrera = Carrera.objects.filter(pk=carrera_id).first()
    if carrera is None:
        return JsonResponse({'error': 'No se encontró la carrera seleccionada.'}, status=404)

    return JsonResponse(_catalogos_clase_por_carrera(carrera, docente))


def clases_registro_view(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido.'}, status=405)

    fecha = timezone.localdate()
    clases = Clase.objects.filter(fecha=fecha).select_related(
        'docente', 'materia', 'grupo',
    ).order_by('hora_inicio')
    return JsonResponse({
        'clases': [
            {
                'id': clase.pk,
                'nombre': (
                    f'{clase.materia.nombre_materia} · Grupo {clase.grupo} · '
                    f'{clase.hora_inicio:%H:%M}–{clase.hora_fin:%H:%M}'
                ),
                'docente': f'{clase.docente.nombre} {clase.docente.apellidos}'.strip(),
                'cuenta_docente': clase.docente.matricula or '',
            }
            for clase in clases
        ],
    })


def buscar_clases_registro_view(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido.'}, status=405)

    cuenta = request.GET.get('docente', '').strip()
    grupo = request.GET.get('grupo', '').strip()
    materia = request.GET.get('materia', '').strip()
    if not any((cuenta, grupo, materia)):
        return JsonResponse({'error': 'Indica al menos un dato para buscar la clase.'}, status=400)

    clases = Clase.objects.filter(
        fecha=timezone.localdate(),
    ).select_related('docente', 'materia', 'grupo')
    if cuenta:
        clases = clases.filter(docente__matricula__icontains=cuenta)
    if grupo:
        clases = clases.filter(grupo__nombre_grupo__icontains=grupo)
    if materia:
        clases = clases.filter(materia__nombre_materia__icontains=materia)
    return JsonResponse({
        'clases': [
            {
                'id': clase.pk,
                'nombre': (
                    f'{clase.materia.nombre_materia} · Grupo {clase.grupo} · '
                    f'{clase.hora_inicio:%H:%M}–{clase.hora_fin:%H:%M}'
                ),
            }
            for clase in clases.order_by('hora_inicio')
        ],
    })


def alumnos_clase_registro_view(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido.'}, status=405)

    try:
        clase_id = int(request.GET.get('clase', ''))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Selecciona una clase válida.'}, status=400)
    clase = Clase.objects.filter(
        pk=clase_id, fecha=timezone.localdate(),
    ).select_related('grupo', 'materia', 'docente').first()
    if clase is None:
        return JsonResponse({'error': 'No se encontró una clase registrada para hoy.'}, status=404)

    alumnos = Persona.objects.con_perfiles('Alumno').filter(
        grupo_id=clase.grupo_id,
    ).order_by('apellidos', 'nombre')
    equipos = _ordenar_equipos_por_numero(
        Equipo.objects.filter(lugar='Sala', estado='Disponible'),
    )
    return JsonResponse({
        'alumnos': [
            {
                'id': alumno.pk,
                'matricula': alumno.matricula or '',
                'nombre': f'{alumno.nombre} {alumno.apellidos}'.strip(),
            }
            for alumno in alumnos
        ],
        'equipos': [{'id': equipo.pk, 'nombre': equipo.no_equipo} for equipo in equipos],
    })


def eventos_registro_view(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido.'}, status=405)

    eventos = EventoTallerConferencia.objects.filter(
        fecha=timezone.localdate(),
    ).order_by('hora_inicio')
    return JsonResponse({
        'eventos': [
            {
                'id': evento.pk,
                'nombre': (
                    f'{evento.nombre_evento} · '
                    f'{evento.hora_inicio:%H:%M}–{evento.hora_fin:%H:%M}'
                ),
            }
            for evento in eventos
        ],
    })


def alumnos_busqueda_view(request):
    if request.method != 'GET':
        return JsonResponse({'encontrado': False, 'error': 'Método no permitido.'}, status=405)

    cuenta = request.GET.get('cuenta', '').strip()
    if not cuenta:
        return JsonResponse({'encontrado': False, 'error': 'Ingresa el número de cuenta del alumno.'}, status=400)
    alumno = Persona.objects.con_perfiles('Alumno').filter(matricula=cuenta).first()
    if alumno is None:
        return JsonResponse({'encontrado': False, 'error': 'No se encontró un alumno con ese número de cuenta.'}, status=404)
    return JsonResponse({
        'encontrado': True,
        'persona_id': alumno.pk,
        'nombre': f'{alumno.nombre} {alumno.apellidos}'.strip(),
    })


def equipos_sala_view(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido.'}, status=405)
    equipos = Equipo.objects.filter(lugar='Sala')
    if request.GET.get('todos') != '1':
        equipos = equipos.filter(estado='Disponible')
    equipos = _ordenar_equipos_por_numero(equipos)
    return JsonResponse({
        'equipos': [
            {
                'id': equipo.pk,
                'nombre': equipo.no_equipo,
                'bien_patrimonial': equipo.no_bien_patrimonial or '',
            }
            for equipo in equipos
        ],
    })


def _id_formulario(data, campo, requerido=True):
    valor = data.get(campo, '')
    if not valor and not requerido:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ValidationError(f'El campo {campo} debe contener un identificador válido.')


def _crear_registro(request, persona=None, externo=None, equipo=None, clase=None, evento=None,
                    tipo_registro=None, motivo_uso=None):
    momento = timezone.localtime()
    registro = Registro(
        modulo='Sala_Computo',
        tipo_registro=tipo_registro,
        motivo_uso=motivo_uso,
        fecha=timezone.localdate(),
        hora_entrada=momento.time(),
        persona=persona,
        externo=externo,
        equipo=equipo,
        clase=clase,
        evento=evento,
        registrado_por=request.user if request.user.is_authenticated else None,
    )
    registro.save()
    return registro


def registrar_entrada_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido.'}, status=405)

    tipo = request.POST.get('tipo', '')
    try:
        equipo_id = _id_formulario(request.POST, 'equipo_id', requerido=False)
        with transaction.atomic():
            equipo = None
            if equipo_id is not None:
                equipo = Equipo.objects.select_for_update().filter(
                    pk=equipo_id, lugar='Sala', estado='Disponible',
                ).first()
                if equipo is None:
                    return JsonResponse({'error': 'El equipo seleccionado ya no está disponible.'}, status=409)

            if tipo == 'visita':
                persona_id = _id_formulario(request.POST, 'persona_id')
                persona = Persona.objects.con_perfiles('Alumno').filter(pk=persona_id).first()
                if persona is None:
                    return JsonResponse({'error': 'No se encontró al alumno seleccionado.'}, status=404)
                registro = _crear_registro(
                    request, persona=persona, equipo=equipo,
                    tipo_registro='Visita', motivo_uso='Visita',
                )
            elif tipo == 'evento':
                evento_id = _id_formulario(request.POST, 'evento_id')
                evento = EventoTallerConferencia.objects.filter(
                    pk=evento_id, fecha=timezone.localdate(),
                ).first()
                if evento is None:
                    return JsonResponse({'error': 'No se encontró un evento vigente para hoy.'}, status=404)
                nombre = request.POST.get('nombre', '').strip()
                apellidos = request.POST.get('apellidos', '').strip()
                institucion = request.POST.get('institucion', '').strip()
                if not nombre or not apellidos:
                    return JsonResponse({'error': 'Captura nombre y apellidos del asistente.'}, status=400)
                externo = Externo(nombre=nombre, apellidos=apellidos, institucion=institucion or None)
                externo.full_clean()
                externo.save()
                registro = _crear_registro(
                    request, externo=externo, equipo=equipo,
                    evento=evento, tipo_registro='Evento', motivo_uso='Visita',
                )
            else:
                return JsonResponse({'error': 'El tipo de entrada no es válido.'}, status=400)
    except ValidationError as error:
        return JsonResponse({'error': '; '.join(error.messages)}, status=400)
    except IntegrityError:
        return JsonResponse({'error': 'No se pudo guardar la entrada por un conflicto de datos.'}, status=409)

    return JsonResponse({'guardado': True, 'registro_id': registro.pk})


def registrar_asistencia_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido.'}, status=405)

    try:
        clase_id = _id_formulario(request.POST, 'clase_id')
        asistencias = json.loads(request.POST.get('asistencias', ''))
        if not isinstance(asistencias, list) or not asistencias:
            raise ValidationError('Selecciona al menos un alumno para registrar.')
        with transaction.atomic():
            clase = Clase.objects.select_for_update().filter(
                pk=clase_id, fecha=timezone.localdate(),
            ).select_related('grupo').first()
            if clase is None:
                return JsonResponse({'error': 'La clase seleccionada ya no está disponible.'}, status=404)

            alumnos = {
                alumno.pk: alumno
                for alumno in Persona.objects.con_perfiles('Alumno').filter(grupo_id=clase.grupo_id)
            }
            marcados = {}
            for item in asistencias:
                alumno_id = int(item.get('alumno_id'))
                if alumno_id in marcados or alumno_id not in alumnos:
                    raise ValidationError('La lista contiene alumnos duplicados o ajenos al grupo.')
                estado = item.get('estado')
                if estado not in ('Asistió', 'Falta'):
                    raise ValidationError('Selecciona Asistió o Falta para cada alumno.')
                marcados[alumno_id] = (estado, item.get('equipo_id') or None)
            if set(marcados) != set(alumnos):
                raise ValidationError('Registra asistencia o falta para todos los alumnos del grupo.')
            if Asistencia.objects.filter(clase=clase, alumno_id__in=marcados).exists():
                return JsonResponse({'error': 'Ya existe asistencia registrada para esta clase.'}, status=409)

            for alumno_id, (estado, equipo_id) in marcados.items():
                alumno = alumnos[alumno_id]
                equipo = None
                registro = None
                if estado == 'Asistió':
                    if equipo_id:
                        equipo = Equipo.objects.select_for_update().filter(
                            pk=int(equipo_id), lugar='Sala', estado='Disponible',
                        ).first()
                        if equipo is None:
                            raise ValidationError('Uno de los equipos seleccionados ya no está disponible.')
                    registro = _crear_registro(
                        request, persona=alumno, equipo=equipo, clase=clase,
                        tipo_registro='Clase', motivo_uso='Clase',
                    )
                Asistencia.objects.create(
                    clase=clase, alumno=alumno, estado=estado,
                    equipo=equipo, registro=registro,
                )
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
        mensaje = '; '.join(error.messages) if isinstance(error, ValidationError) else str(error)
        return JsonResponse({'error': mensaje}, status=400)
    except IntegrityError:
        return JsonResponse({'error': 'No se pudo guardar la asistencia por un conflicto de datos.'}, status=409)

    return JsonResponse({'guardado': True, 'total': len(asistencias)})


def buscar_salida_view(request):
    if request.method != 'GET':
        return JsonResponse({'encontrado': False, 'error': 'Método no permitido.'}, status=405)
    cuenta = request.GET.get('cuenta', '').strip()
    folio = request.GET.get('folio', '').strip()
    filtros = Registro.objects.filter(
        modulo='Sala_Computo',
        hora_salida__isnull=True,
    )
    if folio:
        try:
            if folio[:2].lower() == 'r-':
                folio = folio[2:]
            filtros = filtros.filter(pk=int(folio))
        except ValueError:
            return JsonResponse({'encontrado': False, 'error': 'Ingresa un folio válido, por ejemplo R-123.'}, status=400)
    elif cuenta:
        filtros = filtros.filter(persona__matricula=cuenta)
    else:
        return JsonResponse({'encontrado': False, 'error': 'Ingresa tu número de cuenta o folio de entrada.'}, status=400)

    registros = list(
        filtros.select_related('persona', 'externo', 'equipo').order_by('-fecha', '-hora_entrada')[:2]
    )
    if not registros:
        return JsonResponse({'encontrado': False, 'error': 'No se encontró una entrada activa para esos datos.'}, status=404)
    if len(registros) > 1:
        return JsonResponse({'encontrado': False, 'error': 'Hay más de una entrada activa; solicita apoyo al encargado.'}, status=409)
    registro = registros[0]
    return JsonResponse({
        'encontrado': True,
        'registro_id': registro.pk,
        'nombre': (
            f'{registro.persona.nombre} {registro.persona.apellidos}'.strip()
            if registro.persona_id else
            f'{registro.externo.nombre} {registro.externo.apellidos}'.strip()
        ),
        'cuenta': registro.persona.matricula or '' if registro.persona_id else '',
        'entrada': registro.hora_entrada.strftime('%H:%M'),
        'equipo': registro.equipo.no_equipo if registro.equipo else 'Sin equipo',
    })


def registrar_salida_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido.'}, status=405)
    try:
        registro_id = _id_formulario(request.POST, 'registro_id')
        with transaction.atomic():
            registro = Registro.objects.select_for_update().filter(
                pk=registro_id, modulo='Sala_Computo', hora_salida__isnull=True,
            ).first()
            if registro is None:
                return JsonResponse({'error': 'La entrada ya fue cerrada o no existe.'}, status=404)
            registro.hora_salida = timezone.localtime().time()
            registro.save()
    except ValidationError as error:
        return JsonResponse({'error': '; '.join(error.messages)}, status=400)
    return JsonResponse({'guardado': True})


def historial_equipo_view(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido.'}, status=405)
    try:
        equipo_id = _id_formulario(request.GET, 'equipo_id')
    except ValidationError as error:
        return JsonResponse({'error': '; '.join(error.messages)}, status=400)
    fecha = request.GET.get('fecha', '')
    tipo = request.GET.get('tipo', '').strip()
    try:
        fecha = datetime.fromisoformat(fecha).date()
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Selecciona una fecha válida.'}, status=400)

    registros = Registro.objects.filter(
        modulo='Sala_Computo',
        equipo_id=equipo_id,
        fecha=fecha,
    ).select_related('persona', 'externo').order_by('hora_entrada')
    if tipo:
        registros = registros.filter(tipo_registro=tipo.title())
    return JsonResponse({
        'registros': [
            {
                'id': registro.pk,
                'tipo': registro.tipo_registro or '',
                'persona': (
                    f'{registro.persona.nombre} {registro.persona.apellidos}'.strip()
                    if registro.persona_id else
                    f'{registro.externo.nombre} {registro.externo.apellidos}'.strip()
                ),
                'cuenta': registro.persona.matricula if registro.persona_id else '',
                'hora': registro.hora_entrada.strftime('%H:%M'),
            }
            for registro in registros
        ],
    })


def registrar_incidencia_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido.'}, status=405)
    try:
        equipo_id = _id_formulario(request.POST, 'equipo_id')
        registro_id = _id_formulario(request.POST, 'registro_id', requerido=False)
        equipo = Equipo.objects.filter(pk=equipo_id, lugar='Sala').first()
        if equipo is None:
            return JsonResponse({'error': 'No se encontró el equipo afectado en la Sala de Cómputo.'}, status=404)
        registro = None
        if registro_id is not None:
            registro = Registro.objects.filter(
                pk=registro_id, equipo=equipo, modulo='Sala_Computo',
            ).first()
            if registro is None:
                return JsonResponse({'error': 'El registro de uso no corresponde al equipo seleccionado.'}, status=400)
        incidencia = Incidencia(
            equipo=equipo,
            registro=registro,
            reportada_por=request.user if request.user.is_authenticated else None,
            momento_deteccion=request.POST.get('momento_deteccion', ''),
            descripcion=request.POST.get('descripcion', '').strip(),
        )
        incidencia.save()
    except ValidationError as error:
        return JsonResponse({'error': '; '.join(error.messages)}, status=400)
    return JsonResponse({'guardado': True, 'incidencia_id': incidencia.pk})


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
