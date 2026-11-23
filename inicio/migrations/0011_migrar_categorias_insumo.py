"""Mapear categorías activas e históricas antes de sustituir la columna de texto."""

import django.db.models.deletion
from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


CATEGORIAS_INICIALES = ('Limpieza', 'Papelería', 'Consumibles')


def migrar_categorias(apps, schema_editor):
    alias = schema_editor.connection.alias
    Categoria = apps.get_model('inicio', 'CategoriaInsumo')
    modelos = [apps.get_model('inicio', nombre) for nombre in ('Insumo', 'HistoricalInsumo')]

    # Comparar los textos en Python: una collation insensible a mayúsculas o
    # acentos podría ocultar variantes en DISTINCT o GROUP BY de MariaDB.
    for Modelo in modelos:
        valores = set(Modelo.objects.using(alias).values_list('categoria', flat=True).iterator())
        desconocidos = valores.difference(CATEGORIAS_INICIALES)
        if desconocidos:
            raise RuntimeError(
                f'Categorías sin correspondencia en {Modelo._meta.label}: '
                f'{sorted(desconocidos, key=repr)!r}. Revisar antes de continuar; '
                'no se han retirado los textos existentes.'
            )

    correspondencias = {}
    for nombre in CATEGORIAS_INICIALES:
        categoria, _ = Categoria.objects.using(alias).get_or_create(nombre=nombre)
        correspondencias[nombre] = categoria.pk

    for Modelo in modelos:
        for nombre, categoria_id in correspondencias.items():
            # update() no genera nuevas fotografías ni altera la auditoría.
            Modelo.objects.using(alias).filter(categoria=nombre).update(categoria_relacion_id=categoria_id)
        if Modelo.objects.using(alias).filter(categoria_relacion__isnull=True).exists():
            raise RuntimeError(f'Quedaron categorías sin migrar en {Modelo._meta.label}.')


def impedir_reversion_con_datos(apps, schema_editor):
    alias = schema_editor.connection.alias
    for nombre in ('Insumo', 'HistoricalInsumo'):
        if apps.get_model('inicio', nombre).objects.using(alias).exists():
            raise IrreversibleError(
                'No se puede volver a las categorías fijas con insumos o historial. '
                'Se requiere una migración explícita que conserve sus relaciones.'
            )
    if apps.get_model('inicio', 'CategoriaInsumo').objects.using(alias).exclude(
        nombre__in=CATEGORIAS_INICIALES,
    ).exists():
        raise IrreversibleError('Existen categorías adicionales; la reversión podría eliminarlas.')


class Migration(migrations.Migration):
    dependencies = [
        ('inicio', '0010_crear_categorias_insumo'),
    ]

    operations = [
        migrations.RunPython(migrar_categorias, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name='insumo', name='insumo_categoria_valida'),
        migrations.RemoveIndex(model_name='insumo', name='insumo_categoria_activo_idx'),
        migrations.RemoveField(model_name='insumo', name='categoria'),
        migrations.RemoveField(model_name='historicalinsumo', name='categoria'),
        migrations.RenameField(model_name='insumo', old_name='categoria_relacion', new_name='categoria'),
        migrations.RenameField(model_name='historicalinsumo', old_name='categoria_relacion', new_name='categoria'),
        migrations.AlterField(
            model_name='insumo',
            name='categoria',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='inicio.categoriainsumo'),
        ),
        migrations.AddIndex(
            model_name='insumo',
            index=models.Index(fields=['categoria', 'activo'], name='insumo_categoria_activo_idx'),
        ),
        # Primero al revertir: no ejecutar DDL ni descartar categorías con datos.
        migrations.RunPython(migrations.RunPython.noop, impedir_reversion_con_datos),
    ]
