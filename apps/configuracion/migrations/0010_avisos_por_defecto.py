"""Deja los seis motivos creados y andando con lo que ya había configurado.

Los mails salen del "Email de notificaciones" de Configuración del negocio, así el CRM sigue
avisando exactamente igual que antes. Lo nuevo es que ahora cada motivo se puede apuntar a
destinatarios distintos, y sumarle WhatsApp.
"""
from django.db import migrations

ASUNTOS = {
    'reserva_nueva': 'Reserva nueva: {cliente} — {fecha}',
    'comprobante_por_verificar': 'Comprobante para verificar: {cliente} — {sena}',
    'reserva_confirmada': 'Reserva confirmada: {cliente} — {fecha}',
    'reserva_cancelada': 'Reserva cancelada: {cliente} — {fecha}',
    'atencion_humana': 'Atención humana: {cliente}',
    'bot_caido': 'El bot no pudo responder a {cliente}',
}

# Textos cortos para WhatsApp. El mail, en cambio, arranca vacío: así manda el detalle
# completo que arma el sistema, que es lo que se quiere en un mail.
WHATSAPP = {
    'reserva_nueva': ('🗓️ *Reserva nueva*\n{cliente} ({telefono})\n{circuito}\n'
                      '{fecha} · {turno} · {personas} personas\nTotal {total} — seña {sena}\n{link}'),
    'comprobante_por_verificar': ('💸 *Comprobante para verificar*\n{cliente} ({telefono})\n'
                                  '{circuito}\n{fecha} · {turno}\nSeña {sena}\n{link}'),
    'reserva_confirmada': ('✅ *Reserva confirmada*\n{cliente} ({telefono})\n{circuito}\n'
                           '{fecha} · {turno} · {personas} personas\nTotal {total} — seña {sena}\n{link}'),
    'reserva_cancelada': ('❌ *Reserva cancelada*\n{cliente}\n{circuito}\n{fecha} · {turno}\n'
                          'Motivo: {motivo}\n{destino_sena}'),
    'atencion_humana': ('🙋 *Necesita atención humana*\n{cliente} ({telefono})\n{motivo}\n{link}'),
    'bot_caido': ('⚠️ *El bot no pudo responder*\n{cliente} ({telefono})\n{motivo}\n'
                  'Hay que contestarle a mano desde el inbox.'),
}


def crear(apps, schema_editor):
    AvisoInterno = apps.get_model('configuracion', 'AvisoInterno')
    ConfiguracionNegocio = apps.get_model('configuracion', 'ConfiguracionNegocio')
    config = ConfiguracionNegocio.objects.first()
    emails = (config.email_notificaciones if config else '') or ''

    for evento, asunto in ASUNTOS.items():
        AvisoInterno.objects.get_or_create(evento=evento, defaults={
            'activo': True,
            'emails': emails,
            'asunto': asunto,
            'cuerpo_email': '',
            'whatsapps': '',
            'texto_whatsapp': WHATSAPP[evento],
        })


def borrar(apps, schema_editor):
    apps.get_model('configuracion', 'AvisoInterno').objects.filter(evento__in=ASUNTOS).delete()


class Migration(migrations.Migration):

    dependencies = [('configuracion', '0009_avisointerno')]

    operations = [migrations.RunPython(crear, borrar)]
