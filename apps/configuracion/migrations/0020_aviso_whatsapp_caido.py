"""El aviso de "se desconectó el WhatsApp del spa".

Va por MAIL a propósito: el aviso por WhatsApp sale por la misma instancia que está caída,
así que no llegaría. Arranca apuntando a los mismos mails de Configuración del negocio, para
que avise desde el primer día sin que haya que configurar nada.
"""
from django.db import migrations


def crear(apps, schema_editor):
    AvisoInterno = apps.get_model('configuracion', 'AvisoInterno')
    ConfiguracionNegocio = apps.get_model('configuracion', 'ConfiguracionNegocio')
    config = ConfiguracionNegocio.objects.first()
    AvisoInterno.objects.get_or_create(
        evento='whatsapp_caido',
        defaults={
            'activo': True,
            'emails': (config.email_notificaciones if config else '') or '',
            'asunto': '⚠️ WhatsApp del spa: {estado}',
            'cuerpo_email': ('{motivo}\n\n'
                             'Mientras esté desconectado, los mensajes de los clientes NO entran '
                             'y el bot no puede contestar.\n\n'
                             'Para reconectarlo hay que escanear el QR desde el CRM:\n{link}'),
            # Se deja vacío: por WhatsApp no puede salir si justamente el WhatsApp está caído.
            'whatsapps': '',
            'texto_whatsapp': '',
        },
    )


def borrar(apps, schema_editor):
    apps.get_model('configuracion', 'AvisoInterno').objects.filter(evento='whatsapp_caido').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('configuracion', '0019_alter_avisointerno_evento'),
    ]

    operations = [migrations.RunPython(crear, borrar)]
