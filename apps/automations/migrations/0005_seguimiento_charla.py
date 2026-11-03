"""Crea la automatización de seguimiento y su plantilla.

Arranca APAGADA: escribirle a alguien que no contestó es una decisión del negocio, no algo
que deba empezar a pasar solo porque se actualizó el sistema.
"""
from django.db import migrations

# {{pendiente}} es una oración entera que cambia según dónde quedó la charla: puede ser
# "¿Te quedó alguna duda?..." o "Quedamos por la mitad: me faltaba tu email."
TEXTO = ('Hola {{nombre}}! 🌿 {{pendiente}}\n\n'
         'Si ya no te interesa no hay problema, avisame y no te escribo más.')


def crear(apps, schema_editor):
    Automatizacion = apps.get_model('automations', 'Automatizacion')
    Plantilla = apps.get_model('whatsapp', 'PlantillaMensaje')

    plantilla, _ = Plantilla.objects.get_or_create(
        nombre='Seguimiento de conversación',
        defaults={'tipo': 'seguimiento_charla', 'cuerpo': TEXTO, 'activa': True},
    )
    Automatizacion.objects.get_or_create(
        tipo='seguimiento_charla',
        defaults={
            'activa': False,
            'parametros': {'horas_sin_respuesta': 2, 'ventana_horas': 48},
            'plantilla_id': plantilla.id,
        },
    )


def borrar(apps, schema_editor):
    apps.get_model('automations', 'Automatizacion').objects.filter(tipo='seguimiento_charla').delete()
    apps.get_model('whatsapp', 'PlantillaMensaje').objects.filter(nombre='Seguimiento de conversación').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0004_alter_automatizacion_tipo'),
        ('whatsapp', '0012_alter_plantillamensaje_tipo'),
    ]

    operations = [migrations.RunPython(crear, borrar)]
