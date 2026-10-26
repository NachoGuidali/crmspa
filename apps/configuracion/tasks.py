import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from utils.phone import normalize_ar_phone

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


@shared_task(bind=True, max_retries=3, retry_backoff=30, retry_backoff_max=300)
def enviar_aviso_interno(self, evento, contexto):
    """Manda el aviso de un motivo a los mails y WhatsApps configurados para ese motivo.

    Si el motivo todavía no se configuró, usa el email general de Configuración del negocio:
    así el CRM nunca deja de avisar por no haber tocado la pantalla nueva.
    """
    from apps.whatsapp import sender

    from . import avisos
    from .models import AvisoInterno, ConfiguracionNegocio

    config = ConfiguracionNegocio.get_solo()
    aviso = AvisoInterno.objects.filter(evento=evento).first()
    if aviso and not aviso.activo:
        return

    etiqueta = dict(AvisoInterno.Evento.choices).get(evento, evento)
    cuerpo = avisos.detalle_por_defecto(contexto)

    emails = aviso.lista_emails() if aviso else [
        e.strip() for e in (config.email_notificaciones or '').split(',') if e.strip()
    ]
    if emails:
        asunto = avisos.render(aviso.asunto, contexto) if (aviso and aviso.asunto) else etiqueta
        texto = avisos.render(aviso.cuerpo_email, contexto) if (aviso and aviso.cuerpo_email) else cuerpo
        try:
            send_mail(
                subject=f'[{config.nombre_negocio}] {asunto}',
                message=texto,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=emails,
                fail_silently=False,
            )
        except Exception as exc:
            logger.warning('Error mandando el aviso %s por mail (intento %s): %s',
                           evento, self.request.retries + 1, exc)
            raise self.retry(exc=exc)

    # El WhatsApp al equipo va por el proveedor directo, sin crear conversación: son avisos
    # internos y no tienen que aparecer como charlas en el inbox.
    if aviso and aviso.lista_whatsapps():
        texto = avisos.render(aviso.texto_whatsapp or aviso.cuerpo_email, contexto) \
            if (aviso.texto_whatsapp or aviso.cuerpo_email) else f'{etiqueta}\n\n{cuerpo}'
        for numero in aviso.lista_whatsapps():
            try:
                sender.send_text_message(normalize_ar_phone(numero), texto)
            except Exception as exc:
                # Un número que falla no puede frenar a los demás ni reintentar los mails.
                logger.warning('Error mandando el aviso %s por WhatsApp a %s: %s', evento, numero, exc)
