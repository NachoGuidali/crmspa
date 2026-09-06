# -*- coding: utf-8 -*-
"""La confirmación desglosa los extras.

Hasta ahora el mensaje decía solo el total, y si el cliente había sumado un menú celíaco o
vegetariano no aparecía por ningún lado. Peor: el bot ni siquiera le mandaba los extras al CRM
al crear la reserva, así que el total era el del circuito pelado.

Solo reemplaza el texto si sigue siendo exactamente el de `0010`. Si el spa ya lo editó, no se
le toca nada.
"""
from django.db import migrations

BLOQUE_VIEJO = """💵 *Tu reserva*
Total: {{total}}
Seña abonada: {{sena_pagada}}
Saldo a abonar el día del turno: {{saldo}}"""

BLOQUE_NUEVO = """💵 *Tu reserva*
{{desglose}}Total: {{total}}
Seña abonada: {{sena_pagada}}
Saldo a abonar el día del turno: {{saldo}}"""

VARIABLES = [
    'nombre', 'circuito', 'fecha', 'turno', 'hora_inicio', 'hora_fin', 'personas',
    'desglose', 'total', 'sena_pagada', 'saldo',
    'mapa', 'como_llegar', 'politicas',
]


def desglosar(apps, schema_editor):
    PlantillaMensaje = apps.get_model('whatsapp', 'PlantillaMensaje')
    pl = PlantillaMensaje.objects.filter(tipo='confirmacion_reserva').first()
    if pl is None or BLOQUE_VIEJO not in pl.cuerpo:
        return
    pl.cuerpo = pl.cuerpo.replace(BLOQUE_VIEJO, BLOQUE_NUEVO, 1)
    pl.variables = VARIABLES
    pl.save(update_fields=['cuerpo', 'variables'])


def volver(apps, schema_editor):
    PlantillaMensaje = apps.get_model('whatsapp', 'PlantillaMensaje')
    pl = PlantillaMensaje.objects.filter(tipo='confirmacion_reserva').first()
    if pl is None or BLOQUE_NUEVO not in pl.cuerpo:
        return
    pl.cuerpo = pl.cuerpo.replace(BLOQUE_NUEVO, BLOQUE_VIEJO, 1)
    pl.save(update_fields=['cuerpo'])


class Migration(migrations.Migration):
    dependencies = [('whatsapp', '0010_confirmacion_reserva_con_montos')]
    operations = [migrations.RunPython(desglosar, volver)]
