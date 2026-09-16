# -*- coding: utf-8 -*-
"""El link a las políticas pasa al dominio nuevo.

`url_politicas` se completó en `whatsapp/0009` con https://spacuatroestaciones.com/... y viaja
en el WhatsApp de confirmación de cada reserva. El dominio viejo va a redirigir al nuevo, así que
el link no se rompería, pero el cliente vería el nombre anterior en la URL.

Solo se cambia si sigue siendo exactamente el valor que cargó la migración: si el spa lo editó
desde Configuración del negocio, se respeta.
"""
from django.core.cache import cache
from django.db import migrations

VIEJO = 'https://spacuatroestaciones.com/politicas-de-cancelacion.html'
NUEVO = 'https://spacuatroraices.com.ar/politicas-de-cancelacion.html'


def mudar(apps, schema_editor):
    ConfiguracionNegocio = apps.get_model('configuracion', 'ConfiguracionNegocio')
    if ConfiguracionNegocio.objects.filter(url_politicas=VIEJO).update(url_politicas=NUEVO):
        # El modelo histórico no trae el save() que invalida el caché de get_solo().
        cache.delete('configuracion_negocio')


def volver(apps, schema_editor):
    ConfiguracionNegocio = apps.get_model('configuracion', 'ConfiguracionNegocio')
    if ConfiguracionNegocio.objects.filter(url_politicas=NUEVO).update(url_politicas=VIEJO):
        cache.delete('configuracion_negocio')


class Migration(migrations.Migration):
    dependencies = [
        ('configuracion', '0007_configuracionnegocio_como_llegar_and_more'),
        ('whatsapp', '0009_plantilla_confirmacion_reserva'),
    ]
    operations = [migrations.RunPython(mudar, volver)]
