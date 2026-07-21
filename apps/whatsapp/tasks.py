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
