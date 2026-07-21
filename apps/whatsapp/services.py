import logging

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.contactos.models import Contacto

from . import sender, webhook
from .models import Conversacion, Mensaje

logger = logging.getLogger('apps.whatsapp')


def procesar_webhook_entrante(payload: dict, origen: str = 'evolution') -> list:
    """
    Parsea el payload entrante (Evolution o Meta), guarda los mensajes/conversaciones,
    y devuelve la lista de mensajes entrantes procesados (para reenviar a n8n).
    """
    if origen == 'meta':
        from . import webhook_meta
        mensajes = webhook_meta.parse_incoming_webhook(payload)
    else:
        mensajes = webhook.parse_incoming_webhook(payload)
    procesados = []
    for m in mensajes:
        resultado = _guardar_mensaje_entrante(m)
        if resultado is not None:  # None = mensaje duplicado, ya procesado
            procesados.append(resultado)
    return procesados


def _guardar_mensaje_entrante(m: dict):
    """
    Guarda el mensaje entrante y devuelve el dict para reenviar a n8n.
    Devuelve None si el mensaje ya fue procesado antes (webhook reintentado):
    así no se duplica en el inbox ni se reenvía dos veces a n8n.
    """
    message_id = m.get('message_id', '')
    if message_id and Mensaje.objects.filter(whatsapp_message_id=message_id).exists():
        logger.info('Webhook duplicado ignorado (message_id=%s)', message_id)
        return None

    telefono = m['from_phone']
    conversacion, creada = Conversacion.objects.get_or_create(
        telefono=telefono,
        defaults={'nombre_contacto': m.get('contact_name', '')},
    )

    if creada:
        contacto = Contacto.objects.filter(telefono=telefono).first()
        if contacto:
            conversacion.contacto = contacto
    elif not conversacion.nombre_contacto and m.get('contact_name'):
        conversacion.nombre_contacto = m['contact_name']

    try:
        with transaction.atomic():
            Mensaje.objects.create(
                conversacion=conversacion,
                contacto=conversacion.contacto,
                whatsapp_message_id=message_id,
                direccion=Mensaje.Direccion.ENTRANTE,
                tipo=m['type'],
                contenido=m['content'],
                media_url=m.get('media_url', ''),
                media_mime=m.get('media_mime', ''),
                media_filename=m.get('media_filename', ''),
                status=Mensaje.Status.LEIDO,
                timestamp=m['timestamp'],
            )
    except IntegrityError:
        # Otra entrega del mismo webhook llegó en paralelo y ya lo guardó.
        logger.info('Webhook duplicado (carrera) ignorado (message_id=%s)', message_id)
        return None

    conversacion.ultimo_mensaje_at = m['timestamp']
    conversacion.mensajes_no_leidos += 1
    conversacion.save()

    from apps.configuracion.models import ConfiguracionNegocio
    fuera_de_horario = not ConfiguracionNegocio.get_solo().esta_en_horario_atencion()

    return {
        'phone': telefono,
        'message': m['content'],
        'contact_name': conversacion.nombre_contacto,
        'bot_n8n_activo': conversacion.bot_activo and conversacion.estado != Conversacion.Estado.REQUIERE_ATENCION_HUMANA,
        'conversacion_id': conversacion.id,
        'fuera_de_horario': fuera_de_horario,
    }


def enviar_mensaje(*, telefono, mensaje='', media_url='', media_type='', usuario=None):
    """
    Único punto de envío de WhatsApp saliente — nunca llamar a Evolution API directamente
    por afuera de esto, o el mensaje no queda registrado en el historial del inbox.
    """
    from utils.phone import normalize_ar_phone

    telefono = normalize_ar_phone(telefono)
    conversacion, _ = Conversacion.objects.get_or_create(telefono=telefono)
    contacto = conversacion.contacto or Contacto.objects.filter(telefono=telefono).first()
    tipo = (media_type or Mensaje.Tipo.DOCUMENTO) if media_url else Mensaje.Tipo.TEXTO

    try:
        if media_url:
            resultado = sender.send_media_message(telefono, media_url, media_type or 'document', caption=mensaje)
        else:
            resultado = sender.send_text_message(telefono, mensaje)
    except Exception as exc:
        Mensaje.objects.create(
            conversacion=conversacion, contacto=contacto, direccion=Mensaje.Direccion.SALIENTE,
            tipo=tipo, contenido=mensaje, media_url=media_url, status=Mensaje.Status.FALLIDO,
            enviado_por=usuario, timestamp=timezone.now(), error_detalle=str(exc),
        )
        raise EnvioError(str(exc)) from exc

    msg = Mensaje.objects.create(
        conversacion=conversacion,
        contacto=contacto,
        whatsapp_message_id=resultado.get('id', ''),
        direccion=Mensaje.Direccion.SALIENTE,
        tipo=tipo,
        contenido=mensaje,
        media_url=media_url,
        status=Mensaje.Status.ENVIADO if resultado.get('id') else Mensaje.Status.FALLIDO,
        enviado_por=usuario,
        timestamp=timezone.now(),
    )
    conversacion.ultimo_mensaje_at = msg.timestamp
    conversacion.save()

    return {
        'ok': True,
        'message_id': resultado.get('id', ''),
        'mensaje_id': msg.id,
        'conversacion_id': conversacion.id,
        'contacto_id': contacto.id if contacto else None,
    }


class EnvioError(Exception):
    """El mensaje no pudo enviarse (Evolution API no configurada, caída, etc.)."""


class HandoffError(Exception):
    pass


def handoff(*, telefono, agente_id=None):
    """Deriva la conversación a un agente humano y desactiva el bot de n8n."""
    from utils.phone import normalize_ar_phone

    telefono = normalize_ar_phone(telefono)
    conversacion = Conversacion.objects.filter(telefono=telefono).first()
    if not conversacion:
        raise HandoffError('conversation_not_found')

    User = get_user_model()
    if agente_id:
        agente = User.objects.filter(pk=agente_id).first()
    else:
        agente = _agente_con_menor_carga(User)

    conversacion.bot_activo = False
    conversacion.estado = Conversacion.Estado.REQUIERE_ATENCION_HUMANA
    conversacion.agente = agente
    conversacion.save()

    return {
        'ok': True,
        'conversacion_id': conversacion.id,
        'estado': conversacion.estado,
        'agente_id': agente.id if agente else None,
    }


def _agente_con_menor_carga(User):
    return (
        User.objects.filter(is_active=True, is_staff=True)
        .annotate(
            carga=Count(
                'conversaciones',
                filter=Q(conversaciones__estado=Conversacion.Estado.REQUIERE_ATENCION_HUMANA, conversaciones__archivada=False),
            )
        )
        .order_by('carga')
        .first()
    )
