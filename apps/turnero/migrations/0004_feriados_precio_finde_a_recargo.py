"""Los feriados existentes pasan de "tarifa de finde" a "recargo".

El modo `precio_finde` dejó de existir: un feriado ya no reemplaza la tarifa del día, le suma
un recargo encima. Las filas viejas quedarían con un valor que el modelo no reconoce, así que
se reetiquetan.

`recargo_porcentaje` se deja en NULL a propósito: así todas toman el porcentaje general de
Configuración del negocio (10% por defecto) y alcanza con cambiarlo en un solo lugar.

Ojo: esto cambia el precio de esos días. Un feriado en sábado antes salía igual que cualquier
sábado y ahora sale un 10% más; uno entre semana antes saltaba a la tarifa de finde entera y
ahora sale tarifa de semana + 10%, que suele ser más barato. Es el cambio pedido.
"""
from django.db import migrations


def a_recargo(apps, schema_editor):
    Feriado = apps.get_model('turnero', 'Feriado')
    Feriado.objects.filter(modo='precio_finde').update(modo='recargo')


def a_precio_finde(apps, schema_editor):
    Feriado = apps.get_model('turnero', 'Feriado')
    Feriado.objects.filter(modo='recargo').update(modo='precio_finde')


class Migration(migrations.Migration):

    dependencies = [
        ('turnero', '0003_feriado_recargo_porcentaje_alter_feriado_modo'),
    ]

    operations = [
        migrations.RunPython(a_recargo, a_precio_finde),
    ]
