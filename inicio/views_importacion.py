import logging

from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .forms_importacion import ImportarExcelForm
from .services import importacion_temporal
from .services.importacion_excel import ExcelError, IMPORT_PERMISSIONS, confirm, preview


logger = logging.getLogger(__name__)


@require_http_methods(['GET', 'POST'])
def importar_excel(request):
    if not request.user.is_active or not request.user.is_staff or not request.user.has_perms(IMPORT_PERMISSIONS):
        raise PermissionDenied('No tienes permisos para importar los catálogos institucionales.')
    context = {
        **admin.site.each_context(request),
        'title': 'Importar Excel',
        'form': ImportarExcelForm(),
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
