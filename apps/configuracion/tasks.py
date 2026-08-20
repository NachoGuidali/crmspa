import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger('apps.configuracion')


@shared_task(bind=True, max_retries=3, retry_backoff=30, retry_backoff_max=300)
def notificar_evento(self, asunto, cuerpo):
    """Manda un email a los destinatarios configurados (Configuración del negocio →
    Email de notificaciones) cuando pasa algo relevante en el CRM: reserva nueva del bot,
    reserva confirmada, cancelación, o conversación derivada a un humano.

    Si no hay destinatarios configurados o falla el envío, no rompe el flujo que la disparó
    (siempre se llama de forma asíncrona vía Celery, nunca en el request/webhook).
    """
    from .models import ConfiguracionNegocio

    config = ConfiguracionNegocio.get_solo()
    destinatarios = [e.strip() for e in (config.email_notificaciones or '').split(',') if e.strip()]
    if not destinatarios:
        return

    try:
        send_mail(
            subject=f'[{config.nombre_negocio}] {asunto}',
            message=cuerpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=destinatarios,
            fail_silently=False,
        )
    except Exception as exc:
        logger.warning('Error enviando notificación por email (intento %s): %s', self.request.retries + 1, exc)
        raise self.retry(exc=exc)
