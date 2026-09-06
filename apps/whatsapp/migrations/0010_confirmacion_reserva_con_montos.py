# -*- coding: utf-8 -*-
"""Suma el detalle de plata a la plantilla de confirmación.

La versión de `0009` no llevaba montos a propósito: `confirmar_reserva` no registraba el
`Pago` de la seña, así que la reserva quedaba en `monto_pagado=0` y el mensaje le habría dicho
al cliente "seña $0, saldo $132.000" justo después de que pagó. Ahora la seña se registra, así
que los montos son correctos y vale la pena mostrarlos.

Solo reemplaza el texto si sigue siendo EXACTAMENTE el de `0009`. Si el spa ya lo editó desde
el CRM, se respeta lo suyo y esta migración no hace nada.
"""
from django.db import migrations

CUERPO_0009 = """✅ *¡Tu reserva está confirmada!*

Hola {{nombre}}, recibimos tu seña y ya te guardamos el lugar.

*{{circuito}}*
📅 {{fecha}}
🕐 {{turno}}, de {{hora_inicio}} a {{hora_fin}}
👥 {{personas}}

📍 *Cómo llegar*
{{mapa}}
{{como_llegar}}

🎒 *Qué traer*
Traje de baño, ojotas o chinelas, y ropa de abrigo si el día está fresco.
La bata, la toalla y el toallón te los damos nosotros.

🕐 *A qué hora llegar*
10 minutos antes de tu horario. Si es tu primera vez, mejor 15: así completás la ficha y te mostramos el lugar con tranquilidad.

📄 Políticas de reserva y cancelación: {{politicas}}

Cualquier cosa, respondé este mensaje y te contestamos 💚
*Estancia Cuatro Estaciones*"""

CUERPO_NUEVO = """✅ *¡Tu reserva está confirmada!*

Hola {{nombre}}, recibimos tu seña y ya te guardamos el lugar.

*{{circuito}}*
📅 {{fecha}}
🕐 {{turno}}, de {{hora_inicio}} a {{hora_fin}}
👥 {{personas}}

💵 *Tu reserva*
Total: {{total}}
Seña abonada: {{sena_pagada}}
Saldo a abonar el día del turno: {{saldo}}

📍 *Cómo llegar*
{{mapa}}
{{como_llegar}}

🎒 *Qué traer*
Traje de baño, ojotas o chinelas, y ropa de abrigo si el día está fresco.
La bata, la toalla y el toallón te los damos nosotros.

🕐 *A qué hora llegar*
10 minutos antes de tu horario. Si es tu primera vez, mejor 15: así completás la ficha y te mostramos el lugar con tranquilidad.

📄 Políticas de reserva y cancelación: {{politicas}}

Cualquier cosa, respondé este mensaje y te contestamos 💚
*Estancia Cuatro Estaciones*"""

VARIABLES = [
    'nombre', 'circuito', 'fecha', 'turno', 'hora_inicio', 'hora_fin', 'personas',
    'total', 'sena_pagada', 'saldo', 'mapa', 'como_llegar', 'politicas',
]


def sumar_montos(apps, schema_editor):
    PlantillaMensaje = apps.get_model('whatsapp', 'PlantillaMensaje')
    pl = PlantillaMensaje.objects.filter(tipo='confirmacion_reserva').first()
    if pl is None or pl.cuerpo.strip() != CUERPO_0009.strip():
        return          # la editaron: no le tocamos nada
    pl.cuerpo = CUERPO_NUEVO
    pl.variables = VARIABLES
    pl.save(update_fields=['cuerpo', 'variables'])


def sacar_montos(apps, schema_editor):
    PlantillaMensaje = apps.get_model('whatsapp', 'PlantillaMensaje')
    pl = PlantillaMensaje.objects.filter(tipo='confirmacion_reserva').first()
    if pl is None or pl.cuerpo.strip() != CUERPO_NUEVO.strip():
        return
    pl.cuerpo = CUERPO_0009
    pl.save(update_fields=['cuerpo'])


class Migration(migrations.Migration):

    dependencies = [('whatsapp', '0009_plantilla_confirmacion_reserva')]

    operations = [migrations.RunPython(sumar_montos, sacar_montos)]
