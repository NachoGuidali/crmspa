"""Proveedor: WhatsApp Cloud API (Meta, oficial). Graph API."""
import json
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger('apps.whatsapp')

GRAPH_BASE = 'https://graph.facebook.com'


def _cfg(key):
    from .models import ConfiguracionWhatsApp
    return ConfiguracionWhatsApp.get_setting(key)


def _access_token() -> str:
    return _cfg('meta_access_token') or getattr(settings, 'META_ACCESS_TOKEN', '')


def _api_version() -> str:
    return _cfg('meta_api_version') or getattr(settings, 'META_API_VERSION', 'v21.0')


def _phone_number_id() -> str:
    return _cfg('meta_phone_number_id') or getattr(settings, 'META_PHONE_NUMBER_ID', '')


def _waba_id() -> str:
    return _cfg('meta_waba_id') or getattr(settings, 'META_WABA_ID', '')


def _headers() -> dict:
    return {'Authorization': f'Bearer {_access_token()}', 'Content-Type': 'application/json'}


def _url(path: str) -> str:
    return f'{GRAPH_BASE}/{_api_version()}/{path}'


def _messages_url() -> str:
    return _url(f'{_phone_number_id()}/messages')


def _normalize_phone(phone: str) -> str:
    return phone.lstrip('+')


def _log_request(endpoint, method, request_body, response, duracion_ms):
    from .models import LogEnvioWhatsApp
    try:
        LogEnvioWhatsApp.objects.create(
            endpoint=f'{method} {endpoint}',
            request_body=json.dumps(request_body) if isinstance(request_body, dict) else str(request_body),
            response_status=response.status_code if response else None,
            response_body=response.text[:5000] if response else '',
            duracion_ms=duracion_ms,
            exitoso=response is not None and response.status_code < 300,
        )
    except Exception:
        logger.exception('No se pudo guardar LogEnvioWhatsApp')


def _extract_message_id(data: dict) -> str:
    messages = data.get('messages', [])
    return messages[0].get('id', '') if messages else ''


def _post_message(payload: dict, timeout: int = 15) -> dict:
    url = _messages_url()
    start = time.monotonic()
    response = None
    try:
        response = requests.post(url, json=payload, headers=_headers(), timeout=timeout)
        if not response.ok:
            logger.error('Meta API error %s: %s', response.status_code, response.text[:500])
        response.raise_for_status()
        return {'id': _extract_message_id(response.json())}
    except requests.RequestException:
        logger.exception('Error enviando mensaje Meta a %s', payload.get('to'))
        raise
    finally:
        _log_request(url, 'POST', payload, response, int((time.monotonic() - start) * 1000))


def send_text_message(to: str, body: str) -> dict:
    payload = {
        'messaging_product': 'whatsapp',
        'to': _normalize_phone(to),
        'type': 'text',
        'text': {'body': body, 'preview_url': True},
    }
    return _post_message(payload)


def send_media_message(to: str, media_url: str, mediatype: str, filename: str = '', caption: str = '') -> dict:
    media_obj = {'link': media_url}
    if caption and mediatype in ('image', 'video', 'document'):
        media_obj['caption'] = caption
    if filename and mediatype == 'document':
        media_obj['filename'] = filename
    payload = {
        'messaging_product': 'whatsapp',
        'to': _normalize_phone(to),
        'type': mediatype,
        mediatype: media_obj,
    }
    return _post_message(payload, timeout=30)


def get_phone_number_info() -> dict:
    """verified_name, display_phone_number y quality_rating del número conectado.
    Se usa como 'test de conexión' de Meta desde la pantalla de configuración."""
    url = _url(_phone_number_id())
    try:
        r = requests.get(
            url, headers=_headers(), timeout=10,
            params={'fields': 'verified_name,display_phone_number,quality_rating,code_verification_status'},
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error('Error consultando el número de Meta: %s', e)
        return {'error': str(e)}


# ── Funciones de conexión que no aplican a Meta (para paridad con el dispatcher) ──

def get_connection_state() -> str:
    """Meta no usa QR/instancia: reportamos 'open' si hay token+número, si no 'close'."""
    info = get_phone_number_info() if (_access_token() and _phone_number_id()) else {}
    return 'open' if info and 'error' not in info else 'close'
