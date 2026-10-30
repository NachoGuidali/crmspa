"""Suma el motivo "el bot anotó algo en una reserva".

Arranca SIN destinatarios a propósito: es el único motivo que puede llegar varias veces en
una misma conversación, así que lo prende quien lo quiera, en vez de empezar mandando mails
que nadie pidió.
"""
from django.db import migrations


def crear(apps, schema_editor):
    apps.get_model('configuracion', 'AvisoInterno').objects.get_or_create(
        evento='nota_en_reserva',
        defaults={
            'activo': True,
            'emails': '',
            'asunto': 'Nota nueva en la reserva de {cliente}',
            'cuerpo_email': '',
            'whatsapps': '',
            'texto_whatsapp': ('📝 *Nota en una reserva*\n{cliente} ({telefono})\n'
                               '{circuito} · {fecha} {turno}\n\n{nota}\n{link}'),
        },
    )


def borrar(apps, schema_editor):
    apps.get_model('configuracion', 'AvisoInterno').objects.filter(evento='nota_en_reserva').delete()


class Migration(migrations.Migration):

    dependencies = [('configuracion', '0012_configuracionnegocio_smtp_host_and_more')]

    operations = [migrations.RunPython(crear, borrar)]
