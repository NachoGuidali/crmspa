"""Suma el motivo "voucher de regalo pago, para revisar y enviar".

Es el aviso que frena a un cliente: compró un regalo, transfirió el total y el voucher no le
llega hasta que alguien del spa mira el comprobante. Arranca activo y sin destinatarios, como
los demás: se completan desde Configuración → Avisos internos.
"""
from django.db import migrations


def crear(apps, schema_editor):
    apps.get_model('configuracion', 'AvisoInterno').objects.get_or_create(
        evento='voucher_por_verificar',
        defaults={
            'activo': True,
            'emails': '',
            'asunto': 'Voucher de regalo pago: {cliente}',
            'cuerpo_email': '',
            'whatsapps': '',
            'texto_whatsapp': ('🎁 *Voucher de regalo pago*\n{cliente} ({telefono})\n'
                               '{circuito} · {personas} personas · ${total}\n'
                               'Código: {codigo}\n\n'
                               'Mirá el comprobante y aprobalo para que le llegue:\n{link}'),
        },
    )


def borrar(apps, schema_editor):
    apps.get_model('configuracion', 'AvisoInterno').objects.filter(evento='voucher_por_verificar').delete()


class Migration(migrations.Migration):

    dependencies = [('configuracion', '0016_configuracionnegocio_voucher_validez_dias_and_more')]

    operations = [migrations.RunPython(crear, borrar)]
