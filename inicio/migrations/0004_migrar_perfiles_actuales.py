from django.db import migrations
from django.utils import timezone


def migrar_perfiles(apps, schema_editor):
    alias = schema_editor.connection.alias
    Persona = apps.get_model('inicio', 'Persona')
    PersonaPerfil = apps.get_model('inicio', 'PersonaPerfil')
    Historial = apps.get_model('inicio', 'HistoricalPersonaPerfil')
    validos = ('Administrador', 'Docente', 'Alumno')
    invalidos = Persona.objects.using(alias).exclude(perfil__in=validos)
    if invalidos.exists():
        raise RuntimeError('Hay perfiles principales no reconocidos en Persona. Corrige sus valores antes de aplicar la migración de perfiles múltiples.')
    for persona in Persona.objects.using(alias).only('id_persona', 'perfil').iterator():
        perfil, creado = PersonaPerfil.objects.using(alias).get_or_create(
            persona_id=persona.pk, perfil=persona.perfil,
        )
        if creado:
            # Los modelos históricos de migraciones no ejecutan las señales de
            # simple-history. Se registra explícitamente la incorporación.
            Historial.objects.using(alias).create(
                id=perfil.pk, persona_id=persona.pk, perfil=persona.perfil,
                history_date=timezone.now(), history_type='+',
                history_change_reason='Migración de perfil principal',
            )


class Migration(migrations.Migration):
    dependencies = [('inicio', '0003_perfiles_persona')]

    operations = [
        migrations.RunPython(migrar_perfiles, migrations.RunPython.noop, atomic=True),
    ]
