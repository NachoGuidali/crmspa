"""Segundo intento de seguimiento, al día siguiente y con otro texto.

El primer mensaje sale a las pocas horas y puede pasar desapercibido entre mil notificaciones.
Este es el último intento: un día después, más corto y sin insistir con el detalle del paso
donde quedó. Arranca APAGADA, igual que el primero: escribirle de nuevo a alguien que no
contestó es una decisión del negocio.
"""
from django.db import migrations

TEXTO = ('Hola {{nombre}}! 🌿 Te escribo por última vez por si se te pasó.\n\n'
         'Seguimos con cupos disponibles y la propuesta queda en pie cuando quieras retomarla. '
         'Si no te interesa, avisame y no te escribo más.')


def crear(apps, schema_editor):
    Automatizacion = apps.get_model('automations', 'Automatizacion')
    Plantilla = apps.get_model('whatsapp', 'PlantillaMensaje')

    plantilla, _ = Plantilla.objects.get_or_create(
        nombre='Segundo seguimiento de conversación',
        defaults={'tipo': 'seguimiento_charla', 'cuerpo': TEXTO, 'activa': True},
    )
    Automatizacion.objects.get_or_create(
        tipo='seguimiento_charla_2',
        defaults={
            'activa': False,
            # 24hs después del primer mensaje; la ventana es más ancha porque el reloj
            # arranca cuando salió ese primero, no cuando escribió el cliente.
            'parametros': {'horas_sin_respuesta': 24, 'ventana_horas': 96},
            'plantilla_id': plantilla.id,
        },
    )


def borrar(apps, schema_editor):
    apps.get_model('automations', 'Automatizacion').objects.filter(tipo='seguimiento_charla_2').delete()
    apps.get_model('whatsapp', 'PlantillaMensaje').objects.filter(
        nombre='Segundo seguimiento de conversación').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0005_seguimiento_charla'),
    ]

    operations = [migrations.RunPython(crear, borrar)]
