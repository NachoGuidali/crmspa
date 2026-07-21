"""Parser y verificación de webhook: WhatsApp Cloud API (Meta)."""
import hashlib
import hmac
import logging
from datetime import datetime, timezone as dt_tz

from django.utils import timezone

logger = logging.getLogger('apps.whatsapp')


def verify_webhook_get(mode: str, token: str, configured_token: str) -> bool:
    """Handshake GET que Meta hace al suscribir el webhook (hub.mode=subscribe)."""
    if not configured_token:
        logger.warning('Webhook handshake rechazado — meta_verify_token no configurado')
        return False
    return mode == 'subscribe' and token == configured_token


def verify_signature(raw_body: bytes, signature_header: str, app_secret: str) -> bool:
    """Verifica la firma X-Hub-Signature-256 que Meta manda en cada POST."""
    if not app_secret or not signature_header:
        return False
    if not signature_header.startswith('sha256='):
        return False
    expected = hmac.new(app_secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
    received = signature_header.split('=', 1)[1]
    return hmac.compare_digest(expected, received)


def parse_incoming_webhook(payload: dict) -> list:
    """Devuelve una lista de dicts de mensaje entrante (mismo formato que el parser de Evolution)."""
    messages_data = []
    try:
        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                if not isinstance(value, dict):
                    continue
                _process_statuses(value)
                messages_data.extend(_process_messages(value))
    except Exception:
        logger.exception('Error parseando payload de webhook (Meta)')
    return messages_data


def _process_messages(value: dict) -> list:
    from utils.phone import normalize_ar_phone

    out = []
    contacts = value.get('contacts', [])
    contact_name = contacts[0].get('profile', {}).get('name', '') if contacts else ''

    for msg in value.get('messages', []):
        from_phone = msg.get('from', '')
        if not from_phone:
            continue
        msg_type = msg.get('type', 'text')
        content = _extract_content(msg, msg_type)
        media_id, media_mime, media_filename = _extract_media_fields(msg, msg_type)

        ts = msg.get('timestamp')
        try:
            timestamp = datetime.fromtimestamp(int(ts), tz=dt_tz.utc) if ts else timezone.now()
        except (TypeError, ValueError):
            timestamp = timezone.now()

        out.append({
            'from_phone': normalize_ar_phone('+' + from_phone),
            'message_id': msg.get('id', ''),
            'type': _normalize_type(msg_type),
            'content': content,
            'media_id': media_id,
            'media_url': '',
            'media_mime': media_mime,
            'media_filename': media_filename,
            'timestamp': timestamp,
            'contact_name': contact_name,
        })
    return out


def _extract_content(msg: dict, msg_type: str) -> str:
    if msg_type == 'text':
        return msg.get('text', {}).get('body', '')
    if msg_type == 'image':
        return msg.get('image', {}).get('caption', '') or '[Imagen]'
    if msg_type == 'video':
        return msg.get('video', {}).get('caption', '') or '[Video]'
    if msg_type == 'document':
        doc = msg.get('document', {})
        return doc.get('caption', '') or doc.get('filename', '') or '[Documento]'
    if msg_type == 'audio':
        return '[Audio]'
    if msg_type == 'sticker':
        return '[Sticker]'
    if msg_type == 'button':
        return msg.get('button', {}).get('text', '')
    if msg_type == 'interactive':
        interactive = msg.get('interactive', {})
        if interactive.get('type') == 'button_reply':
            return interactive.get('button_reply', {}).get('title', '')
        if interactive.get('type') == 'list_reply':
            return interactive.get('list_reply', {}).get('title', '')
        return ''
    return f'[{msg_type}]'


def _extract_media_fields(msg: dict, msg_type: str) -> tuple:
    """Devuelve (media_id, media_mime, media_filename) para tipos de media."""
    if msg_type not in ('image', 'video', 'audio', 'document', 'sticker'):
        return '', '', ''
    obj = msg.get(msg_type, {})
    media_id = obj.get('id', '')
    mime = obj.get('mime_type', '')
    filename = obj.get('filename', '') if msg_type == 'document' else ''
    return media_id, mime, filename


def _normalize_type(msg_type: str) -> str:
    mapping = {
        'text': 'text', 'image': 'image', 'video': 'video',
        'audio': 'audio', 'document': 'document', 'sticker': 'image',
        'button': 'text', 'interactive': 'text',
    }
    return mapping.get(msg_type, 'text')


def _process_statuses(value: dict):
    from .models import Mensaje

    status_map = {'sent': 'sent', 'delivered': 'delivered', 'read': 'read', 'failed': 'failed'}
    for status in value.get('statuses', []):
        msg_id = status.get('id', '')
        mapped = status_map.get(status.get('status', ''))
        if not msg_id or not mapped:
            continue
        update_fields = {'status': mapped}
        if mapped == 'failed':
            errors = status.get('errors', [])
            if errors:
                update_fields['error_detalle'] = errors[0].get('title', '') or str(errors[0])
        Mensaje.objects.filter(whatsapp_message_id=msg_id).update(**update_fields)
