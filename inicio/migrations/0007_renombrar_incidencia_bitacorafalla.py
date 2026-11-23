"""Renombrar incidencias sin copiar filas ni perder autorizaciones."""
from django.db import migrations


PARES = (
    ('incidencia', 'bitacorafalla'),
    ('historicalincidencia', 'historicalbitacorafalla'),
)


def comprobar_destinos(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    alias = schema_editor.connection.alias
    for anterior, nuevo in PARES:
        tipos = ContentType.objects.using(alias).filter(app_label='inicio', model__in=[anterior, nuevo])
        if tipos.count() > 1:
            raise RuntimeError(f'Existen ambos content types {anterior}/{nuevo}; revisar antes de migrar.')
        tipo = tipos.first()
        if tipo:
            for accion in ('add', 'change', 'delete', 'view'):
                permisos = Permission.objects.using(alias).filter(
                    content_type_id=tipo.pk,
                    codename__in=[f'{accion}_{anterior}', f'{accion}_{nuevo}'],
                )
                if permisos.count() > 1:
                    raise RuntimeError(f'Colisión de permisos {accion}_{anterior}/{nuevo}; revisar antes de migrar.')


def renombrar_autorizaciones(apps, schema_editor, pares):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    alias = schema_editor.connection.alias
    for anterior, nuevo in pares:
        # migrate puede haber inyectado RenameContentType; executor puede no hacerlo.
        tipo = ContentType.objects.using(alias).filter(app_label='inicio', model=anterior).first()
        if tipo:
            if ContentType.objects.using(alias).filter(app_label='inicio', model=nuevo).exists():
                raise RuntimeError(f'Colisión de content types {anterior}/{nuevo}.')
            ContentType.objects.using(alias).filter(pk=tipo.pk).update(model=nuevo)
        else:
            tipo = ContentType.objects.using(alias).filter(app_label='inicio', model=nuevo).first()
        if tipo:
            for accion in ('add', 'change', 'delete', 'view'):
                anteriores = Permission.objects.using(alias).filter(content_type_id=tipo.pk, codename=f'{accion}_{anterior}')
                if anteriores.exists() and Permission.objects.using(alias).filter(content_type_id=tipo.pk, codename=f'{accion}_{nuevo}').exists():
                    raise RuntimeError(f'Colisión de permisos {accion}_{anterior}/{nuevo}.')
                anteriores.update(codename=f'{accion}_{nuevo}')
    # No modificar PK: grupos, usuarios, LogEntry y referencias genéricas los conservan.
    if hasattr(ContentType.objects, 'clear_cache'):
        ContentType.objects.clear_cache()


def forwards(apps, schema_editor):
    renombrar_autorizaciones(apps, schema_editor, PARES)


def backwards(apps, schema_editor):
    renombrar_autorizaciones(apps, schema_editor, [(nuevo, anterior) for anterior, nuevo in PARES])


class Migration(migrations.Migration):
    dependencies = [
        ('inicio', '0006_asistencia_historicalasistencia_historicalincidencia_and_more'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]
    operations = [
        migrations.RunPython(comprobar_destinos, migrations.RunPython.noop),
        migrations.RenameModel('Incidencia', 'BitacoraFalla'),
        migrations.RenameModel('HistoricalIncidencia', 'HistoricalBitacoraFalla'),
        migrations.AlterModelTable('bitacorafalla', 'bitacoraFalla'),
        *[
            migrations.RenameField(modelo, anterior, nuevo)
            for modelo in ('bitacorafalla', 'historicalbitacorafalla')
            for anterior, nuevo in (
                ('id', 'id_falla'),
                ('descripcion', 'descripcion_falla'),
                ('estado', 'estado_atencion'),
                ('creada_en', 'fecha_reporte'),
                ('reportada_por', 'usuario_sistema'),
            )
        ],
        migrations.RunPython(forwards, backwards),
    ]
