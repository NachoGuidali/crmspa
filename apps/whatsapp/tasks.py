import logging

import requests
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.conf import settings

logger = logging.getLogger('apps.whatsapp')


@shared_task(bind=True, max_retries=5, retry_backoff=10, retry_backoff_max=600, retry_jitter=True)
def forward_to_n8n(self, payload: dict):
    """Reenvía el payload crudo de Evolution API (+ campos de conveniencia) al webhook de n8n.

    Si n8n no responde tras todos los reintentos, deriva la conversación a atención
    humana para que aparezca destacada en el inbox y nadie quede sin respuesta.
    """
    url = settings.N8N_WEBHOOK_URL
    if not url:
        logger.warning('N8N_WEBHOOK_URL no configurado — no se reenvía el mensaje')
        return
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning('Error reenviando a n8n (intento %s): %s', self.request.retries + 1, exc)
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error('n8n inalcanzable tras %s reintentos — derivando a atención humana', self.max_retries)
            _derivar_a_humano_por_falla_n8n(payload)


def _derivar_a_humano_por_falla_n8n(payload: dict):
    """El bot no pudo procesar el mensaje (n8n caído): marca la conversación para que
    un humano la atienda desde el inbox."""
    from apps.whatsapp.models import Conversacion

    conversacion_id = payload.get('conversacion_id')
    telefono = payload.get('phone')
    conv = None
    if conversacion_id:
        conv = Conversacion.objects.filter(pk=conversacion_id).first()
    if conv is None and telefono:
        conv = Conversacion.objects.filter(telefono=telefono).first()
    if conv is None:
        return
    conv.estado = Conversacion.Estado.REQUIERE_ATENCION_HUMANA
    conv.bot_activo = False
    conv.save(update_fields=['estado', 'bot_activo'])

    from apps.configuracion.tasks import notificar_evento
    notificar_evento.delay(
        'Conversación requiere atención humana (bot caído)',
        f'{conv.get_display_name()} ({conv.telefono}) quedó sin respuesta: n8n no contestó '
        f'tras varios reintentos. Revisar que el bot esté funcionando.',
    )


@shared_task(bind=True, max_retries=5, retry_backoff=10, retry_backoff_max=600, retry_jitter=True)
def notificar_reserva_aprobada(self, reserva_id):
    """Avisa a n8n que una reserva quedó confirmada, para que el bot mande la
    confirmación final al cliente por WhatsApp."""
    from apps.reservas.models import Reserva

    url = settings.N8N_RESERVA_APROBADA_URL
    if not url:
        logger.warning('N8N_RESERVA_APROBADA_URL no configurado — no se avisa al bot de la reserva %s', reserva_id)
        return

    reserva = (
        Reserva.objects.select_related('contacto', 'turno', 'circuito').filter(pk=reserva_id).first()
    )
    if reserva is None:
        return

    payload = {
        'telefono': reserva.contacto.telefono,
        'nombre': reserva.contacto.nombre,
        'horario_confirmado': f'{reserva.fecha.isoformat()} ({reserva.turno.nombre})',
        'resumen': reserva.resumen or '',
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning('Error avisando reserva aprobada a n8n (intento %s): %s', self.request.retries + 1, exc)
        raise self.retry(exc=exc)


def _contexto_confirmacion(reserva):
    """Variables que puede usar la plantilla de confirmación de reserva.

    Los datos del lugar (mapa, cómo llegar, políticas) salen de Configuración del negocio y no
    del texto de la plantilla, así se escriben una vez y los reusan también los recordatorios.
    """
    from apps.configuracion.models import ConfiguracionNegocio

    config = ConfiguracionNegocio.get_solo()
    personas = reserva.cantidad_personas or 1

    DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
    fecha = f'{DIAS[reserva.fecha.weekday()]} {reserva.fecha.strftime("%d/%m/%Y")}'

    def plata(monto):
        # Formato argentino: $132.000, sin centavos. Los precios del spa son montos redondos.
        return f'${monto or 0:,.0f}'.replace(',', '.')

    return {
        'nombre': reserva.contacto.nombre or '',
        'total': plata(reserva.total),
        'sena_pagada': plata(reserva.monto_pagado),
        'saldo': plata(reserva.saldo),
        'circuito': reserva.circuito.nombre,
        'fecha': fecha,
        'turno': reserva.turno.nombre,
        'hora_inicio': reserva.turno.hora_inicio.strftime('%H:%M'),
        'hora_fin': reserva.turno.hora_fin.strftime('%H:%M'),
        # Resuelto acá y no en la plantilla: "1 personas" queda mal y el dueño no tiene
        # forma de poner un condicional en el texto.
        'personas': f'{personas} persona' if personas == 1 else f'{personas} personas',
        'direccion': config.direccion or '',
        'mapa': config.mapa_url or '',
        'como_llegar': config.como_llegar or '',
        'politicas': config.url_politicas or '',
    }


@shared_task(bind=True, max_retries=5, retry_backoff=20, retry_backoff_max=600, retry_jitter=True)
def enviar_confirmacion_reserva(self, reserva_id):
    """Le manda al cliente el mensaje de "reserva confirmada" por WhatsApp.

    Se dispara cuando la reserva pasa a confirmada, venga de donde venga: el staff aprobando
    un comprobante de transferencia, Mercado Pago acreditando, o alguien cobrando la seña a
    mano desde el CRM.

    Usa `enviar_automatico`, que resuelve solo el proveedor: con Evolution manda texto libre;
    con Meta, si la ventana de 24hs está cerrada (lo normal si el comprobante se aprueba al día
    siguiente), cambia a la plantilla aprobada. Sin eso, la confirmación se perdería justo
    después de que el cliente pagó.
    """
    from apps.reservas.models import Reserva

    from .models import PlantillaMensaje
    from .services import enviar_automatico

    reserva = (
        Reserva.objects.select_related('contacto', 'turno', 'circuito').filter(pk=reserva_id).first()
    )
    if reserva is None:
        return

    plantilla = PlantillaMensaje.objects.filter(
        tipo=PlantillaMensaje.Tipo.CONFIRMACION_RESERVA, activa=True,
    ).first()
    if plantilla is None:
        logger.warning(
            'No hay plantilla activa de confirmación de reserva — la reserva %s se confirmó '
            'pero al cliente no se le avisó. Cargala en Configuración → Plantillas.', reserva_id,
        )
        return

    try:
        enviar_automatico(
            telefono=reserva.contacto.telefono,
            plantilla=plantilla,
            contexto=_contexto_confirmacion(reserva),
        )
    except Exception as exc:
        logger.warning('Error mandando la confirmación de la reserva %s (intento %s): %s',
                       reserva_id, self.request.retries + 1, exc)
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            # El cliente pagó y no se entera: que quede fuerte en el log y en el panel de salud.
            logger.error('No se pudo avisarle al cliente que la reserva %s quedó confirmada, '
                         'tras %s reintentos.', reserva_id, self.max_retries)
