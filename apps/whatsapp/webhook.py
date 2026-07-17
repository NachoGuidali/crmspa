import logging
from datetime import datetime, timezone as dt_tz

from django.utils import timezone

from utils.phone import normalize_ar_phone

logger = logging.getLogger('apps.whatsapp')

_STATUS_MAP = {
    'PENDING': 'pending',
    'SENT': 'sent',
    'DELIVERY_ACK': 'delivered',
    'READ': 'read',
    'PLAYED': 'read',
    'ERROR': 'failed',
    'FAILED': 'failed',
}


def verify_webhook_token(request_token: str, configured_token: str) -> bool:
    from django.conf import settings

    if not configured_token:
        # En producción, un webhook sin token configurado es un agujero de seguridad
        # (cualquiera podría inyectar mensajes). Solo se permite en DEBUG para desarrollo.
        if settings.DEBUG:
            logger.warning('No hay webhook_token configurado — se omite la verificación (DEBUG)')
            return True
        logger.error('Webhook rechazado: no hay webhook_token configurado en producción')
        return False
    return request_token == configured_token


def parse_incoming_webhook(payload: dict) -> list:
    """Devuelve una lista de dicts de mensaje nuevo. [] para eventos que no son un mensaje."""
    raw_event = payload.get('event', '')
    event = raw_event.lower().replace('_', '.')

    if event == 'messages.upsert':
        return _parse_message_upsert(payload)

    if event == 'messages.update':
        _process_status_updates(payload.get('data', []))
        return []

    logger.debug('Evento de webhook sin manejar: %s', raw_event)
    return []


def _parse_message_upsert(payload: dict) -> list:
    messages_data = []
    try:
        data = payload.get('data', {})
        key = data.get('key', {})

        if key.get('fromMe', False):
            return []

        remote_jid = key.get('remoteJid', '')
        if '@g.us' in remote_jid:
            return []

        from_phone = _extract_from_jid(remote_jid)
        message_id = key.get('id', '')
        msg_type_raw = data.get('messageType', 'conversation')
        message = data.get('message', {})
        timestamp_val = data.get('messageTimestamp', 0)

        msg_type = _normalize_type(msg_type_raw)
        content = _extract_content_evo(message, msg_type_raw)
        media_url, media_mime, media_filename = _extract_media_fields(message, msg_type_raw)
        contact_name = data.get('pushName', '')

        if isinstance(timestamp_val, (int, float)):
            ts = datetime.fromtimestamp(int(timestamp_val), tz=dt_tz.utc)
        else:
            ts = timezone.now()

        messages_data.append({
            'from_phone': from_phone,
            'message_id': message_id,
            'type': msg_type,
            'content': content,
            'media_url': media_url,
            'media_mime': media_mime,
            'media_filename': media_filename,
            'timestamp': ts,
            'contact_name': contact_name,
        })
    except Exception:
        logger.exception('Error parseando payload de webhook (messages.upsert)')
    return messages_data


def _extract_from_jid(jid: str) -> str:
    number = jid.split('@')[0]
    if not number.startswith('+'):
        number = '+' + number
    return normalize_ar_phone(number)


def _normalize_type(msg_type_raw: str) -> str:
    type_map = {
        'conversation': 'text',
        'extendedTextMessage': 'text',
        'imageMessage': 'image',
        'documentMessage': 'document',
        'documentWithCaptionMessage': 'document',
        'audioMessage': 'audio',
        'videoMessage': 'video',
        'stickerMessage': 'image',
        'buttonsResponseMessage': 'text',
        'listResponseMessage': 'text',
        'templateButtonReplyMessage': 'text',
    }
    return type_map.get(msg_type_raw, 'text')


def _extract_content_evo(message: dict, msg_type_raw: str) -> str:
    if msg_type_raw in ('conversation', 'extendedTextMessage'):
        return message.get('conversation', '') or message.get('extendedTextMessage', {}).get('text', '')
    if msg_type_raw == 'imageMessage':
        return message.get('imageMessage', {}).get('caption', '')
    if msg_type_raw == 'videoMessage':
        return message.get('videoMessage', {}).get('caption', '') or '[Video]'
    if msg_type_raw == 'documentMessage':
        doc = message.get('documentMessage', {})
        return doc.get('title', '') or doc.get('caption', '') or '[Documento]'
    if msg_type_raw == 'documentWithCaptionMessage':
        inner = message.get('documentWithCaptionMessage', {}).get('message', {}).get('documentMessage', {})
        return inner.get('title', '') or inner.get('caption', '') or '[Documento]'
    if msg_type_raw == 'audioMessage':
        return '[Audio]'
    if msg_type_raw == 'stickerMessage':
        return '[Sticker]'
    if msg_type_raw == 'buttonsResponseMessage':
        return message.get('buttonsResponseMessage', {}).get('selectedDisplayText', '')
    if msg_type_raw == 'listResponseMessage':
        row = message.get('listResponseMessage', {}).get('singleSelectReply', {})
        return row.get('title', '') or row.get('selectedRowId', '')
    if msg_type_raw == 'templateButtonReplyMessage':
        return message.get('templateButtonReplyMessage', {}).get('selectedDisplayText', '')
    return f'[{msg_type_raw}]'


def _extract_media_fields(message: dict, msg_type_raw: str) -> tuple:
    type_map = {
        'imageMessage': ('imageMessage', 'image/jpeg'),
        'videoMessage': ('videoMessage', 'video/mp4'),
        'audioMessage': ('audioMessage', 'audio/ogg; codecs=opus'),
        'stickerMessage': ('stickerMessage', 'image/webp'),
        'documentMessage': ('documentMessage', 'application/octet-stream'),
    }

    if msg_type_raw == 'documentWithCaptionMessage':
        inner = message.get('documentWithCaptionMessage', {}).get('message', {}).get('documentMessage', {})
        url = inner.get('url', '') or inner.get('mediaUrl', '')
        mime = inner.get('mimetype', 'application/octet-stream')
        fname = inner.get('title', '') or inner.get('fileName', '') or inner.get('caption', '')
        return url, mime, fname

    entry = type_map.get(msg_type_raw)
    if not entry:
        return '', '', ''

    inner_key, default_mime = entry
    obj = message.get(inner_key, {})
    url = obj.get('url', '') or obj.get('mediaUrl', '')
    mime = obj.get('mimetype', default_mime) or default_mime
    fname = obj.get('title', '') or obj.get('fileName', '') or obj.get('caption', '')
    return url, mime, fname


def _process_status_updates(update_list: list):
    from .models import Mensaje

    if not isinstance(update_list, list):
        return
    for item in update_list:
        if not isinstance(item, dict):
            continue
        msg_id = item.get('key', {}).get('id', '')
        raw_status = item.get('update', {}).get('status', '')
        mapped = _STATUS_MAP.get(raw_status.upper() if raw_status else '', '')
        if msg_id and mapped:
            Mensaje.objects.filter(whatsapp_message_id=msg_id).update(status=mapped)
