"""Los avisos de reserva, con todo lo que hace falta para trabajar sin abrir el CRM.

Antes el WhatsApp interno traía cliente, circuito, fecha, turno, personas y total+seña en
una línea. Faltaban los extras, el email y, sobre todo, el saldo a cobrar el día del spa,
que es la cuenta que alguien tenía que hacer a mano. El formato nuevo lo pidió el dueño.

Solo se pisan los textos que siguen siendo el default que puso la migración 0010: si alguien
los editó desde Configuración → Avisos internos, se respeta lo que escribió.
"""
from django.db import migrations

VIEJOS = {
    'reserva_nueva': ('🗓️ *Reserva nueva*\n{cliente} ({telefono})\n{circuito}\n'
                      '{fecha} · {turno} · {personas} personas\nTotal {total} — seña {sena}\n{link}'),
    'comprobante_por_verificar': ('💸 *Comprobante para verificar*\n{cliente} ({telefono})\n'
                                  '{circuito}\n{fecha} · {turno}\nSeña {sena}\n{link}'),
    'reserva_confirmada': ('✅ *Reserva confirmada*\n{cliente} ({telefono})\n{circuito}\n'
                           '{fecha} · {turno} · {personas} personas\nTotal {total} — seña {sena}\n{link}'),
}

# El bloque de datos es igual en los tres: lo que cambia es el título y qué falta hacer.
DATOS = (
    '{fecha_larga}\n'
    'Horario: {horario}\n'
    '{circuito} para {personas} personas{bloque_extras}\n'
    '\n'
    'Nombre: {cliente}\n'
    'Tel: {telefono}\n'
    'Email: {email}\n'
    '\n'
    'Total: {total}\n'
    'Seña: {sena}\n'
    'Saldo el día del spa: {saldo}\n'
    '{link}'
)

NUEVOS = {
    'reserva_nueva': f'🗓️ *Reserva nueva*\n{DATOS}',
    'comprobante_por_verificar': f'💸 *Transferencia para verificar*\n{DATOS}',
    'reserva_confirmada': f'✅ *Reserva confirmada*\n{DATOS}',
}


def actualizar(apps, schema_editor):
    AvisoInterno = apps.get_model('configuracion', 'AvisoInterno')
    for evento, texto in NUEVOS.items():
        AvisoInterno.objects.filter(evento=evento, texto_whatsapp=VIEJOS[evento]).update(
            texto_whatsapp=texto)


def volver(apps, schema_editor):
    AvisoInterno = apps.get_model('configuracion', 'AvisoInterno')
    for evento, texto in NUEVOS.items():
        AvisoInterno.objects.filter(evento=evento, texto_whatsapp=texto).update(
            texto_whatsapp=VIEJOS[evento])


class Migration(migrations.Migration):

    dependencies = [('configuracion', '0017_aviso_voucher_por_verificar')]

    operations = [migrations.RunPython(actualizar, volver)]
