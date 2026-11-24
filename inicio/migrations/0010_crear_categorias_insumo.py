"""Preparar la relación sin convertir ni retirar todavía los textos existentes."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('inicio', '0009_depurar_campos_bitacorafalla'),
    ]

    operations = [
        migrations.CreateModel(
            name='CategoriaInsumo',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('nombre', models.CharField(max_length=100, unique=True)),
            ],
            options={
                'constraints': [models.CheckConstraint(
                    condition=~models.Q(nombre=''), name='cat_insumo_nombre_no_vacio',
                )],
            },
        ),
        migrations.AddField(
            model_name='insumo',
            name='categoria_relacion',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                to='inicio.categoriainsumo',
            ),
        ),
        migrations.AddField(
            model_name='historicalinsumo',
            name='categoria_relacion',
            field=models.ForeignKey(
                blank=True, db_constraint=False, null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name='+', to='inicio.categoriainsumo',
            ),
        ),
    ]
