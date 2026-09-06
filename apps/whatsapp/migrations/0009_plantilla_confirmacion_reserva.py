# -*- coding: utf-8 -*-
"""Carga la plantilla de confirmación de reserva y los datos del lugar.

Hasta ahora, confirmar una reserva no le mandaba NADA al cliente: `confirmar_reserva` solo
posteaba a n8n vía `N8N_RESERVA_APROBADA_URL`, que está sin configurar. Esta plantilla es la
que sale ahora por WhatsApp.

Usa `get_or_create`: si el spa ya la editó desde el CRM, no se le pisa el texto.
"""
from django.db import migrations

CUERPO = """✅ *¡Tu reserva está confirmada!*

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

VARIABLES = [
    'nombre', 'circuito', 'fecha', 'turno', 'hora_inicio', 'hora_fin',
    'personas', 'mapa', 'como_llegar', 'politicas',
]

COMO_LLEGAR = (
    'Los últimos metros son camino de tierra. Si llovió, vení con tiempo y manejá despacio.'
)
MAPA = 'https://maps.app.goo.gl/RWskANLutaWP1SkJ6'
POLITICAS = 'https://spacuatroestaciones.com/politicas-de-cancelacion.html'


def cargar(apps, schema_editor):
    PlantillaMensaje = apps.get_model('whatsapp', 'PlantillaMensaje')
    PlantillaMensaje.objects.get_or_create(
        nombre='Confirmación de reserva',
        defaults={
            'tipo': 'confirmacion_reserva',
            'cuerpo': CUERPO,
            'variables': VARIABLES,
            'activa': True,
            'meta_categoria': 'utility',
        },
    )

    # Los datos del lugar solo se completan si están vacíos, para no pisar lo que ya cargaron.
    # `get_or_create(pk=1)` y no `first()`: la configuración es un singleton que se crea recién
    # en el primer acceso desde la app, así que corriendo esta migración en una base nueva
    # todavía no existe la fila.
    ConfiguracionNegocio = apps.get_model('configuracion', 'ConfiguracionNegocio')
    config, _ = ConfiguracionNegocio.objects.get_or_create(pk=1)
    cambios = []
    if not config.mapa_url:
        config.mapa_url = MAPA
        cambios.append('mapa_url')
    if not config.como_llegar:
        config.como_llegar = COMO_LLEGAR
        cambios.append('como_llegar')
    if not config.url_politicas:
        config.url_politicas = POLITICAS
        cambios.append('url_politicas')
    if cambios:
        config.save(update_fields=cambios)
        # El modelo histórico de la migración no trae el `save()` que limpia el caché, así que
        # lo hacemos a mano: si no, `get_solo()` puede servir la config vieja (sin mapa ni
        # políticas) hasta 5 minutos, y la primera confirmación tras el deploy saldría coja.
        from django.core.cache import cache
        cache.delete('configuracion_negocio')


def borrar(apps, schema_editor):
    PlantillaMensaje = apps.get_model('whatsapp', 'PlantillaMensaje')
    PlantillaMensaje.objects.filter(nombre='Confirmación de reserva').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('whatsapp', '0008_conversacion_ventana_expira_at_and_more'),
        ('configuracion', '0007_configuracionnegocio_como_llegar_and_more'),
    ]

    operations = [
        migrations.RunPython(cargar, borrar),
    ]
