import logging

from django.contrib import admin
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods

from .forms_importacion import ImportarExcelForm
from .services import importacion_temporal
from .services.importacion_excel import (
    ExcelError, IMPORT_PERMISSIONS, MAX_ROWS, PREVIEW_LIMIT, confirm, preview,
)


logger = logging.getLogger(__name__)
EXCEL_TEMPLATE_PATH = settings.BASE_DIR / 'inicio' / 'plantillas' / 'Plantilla.xlsx'


def _require_import_permissions(request):
    if not request.user.is_active or not request.user.is_staff or not request.user.has_perms(IMPORT_PERMISSIONS):
        raise PermissionDenied('No tienes permisos para importar los catálogos institucionales.')


@require_GET
def descargar_plantilla_excel(request):
    _require_import_permissions(request)
    try:
        archivo = EXCEL_TEMPLATE_PATH.open('rb')
    except FileNotFoundError as exc:
        raise Http404('La plantilla Excel no está disponible.') from exc
    return FileResponse(
        archivo, as_attachment=True, filename='Plantilla.xlsx',
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@require_http_methods(['GET', 'POST'])
def importar_excel(request):
    _require_import_permissions(request)
    context = {
        **admin.site.each_context(request),
        'title': 'Importar Excel',
        'form': ImportarExcelForm(),
        'max_import_rows': MAX_ROWS,
        'max_preview_rows': PREVIEW_LIMIT,
    }
    request.current_app = admin.site.name
    if request.method == 'POST':
        try:
            if request.POST.get('accion') == 'confirmar':
                data = importacion_temporal.consume(request.POST.get('token', ''), request)
                context['plan'] = confirm(data, request.user)
                context['completed'] = True
            elif request.POST.get('accion') == 'validar':
                form = ImportarExcelForm(request.POST, request.FILES)
                context['form'] = form
                if form.is_valid():
                    data = form.cleaned_data['archivo'].read()
                    plan = preview(data)
                    context['plan'] = plan
                    if plan.valid:
                        context['token'] = importacion_temporal.store(data, request)
            else:
                raise ExcelError('Selecciona un archivo para validar antes de confirmar.')
        except ExcelError as exc:
            context['error'] = str(exc)
        except ValidationError:
            context['error'] = 'La validación cambió al guardar. Se revirtió toda la importación. Carga nuevamente el archivo.'
        except DatabaseError:
            logger.exception('No se pudo completar la importación Excel; transacción revertida.')
            context['error'] = 'No se pudo completar la operación en la base de datos. No se guardaron registros de esta importación.'
        except OSError:
            logger.exception('No se pudo acceder al archivo temporal de importación.')
            context['error'] = 'No se pudo preparar o recuperar la vista previa. Carga nuevamente el archivo.'
    return render(request, 'admin/inicio/importar_excel.html', context)
