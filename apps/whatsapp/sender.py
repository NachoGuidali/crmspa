import json
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger('apps.whatsapp')


def _cfg(key):
    from .models import ConfiguracionWhatsApp
    return ConfiguracionWhatsApp.get_setting(key)


def _evo_headers():
    return {'apikey': _cfg('evolution_api_key'), 'Content-Type': 'application/json'}


def _evo_url(path: str) -> str:
    base = _cfg('evolution_api_url') or getattr(settings, 'EVOLUTION_API_URL', '')
    return f'{base.rstrip("/")}{path}'


def _instance() -> str:
    return _cfg('evolution_instance_name') or getattr(settings, 'EVOLUTION_INSTANCE', 'crmspa')


def _normalize_phone(phone: str) -> str:
    """'+5491112345678' → '5491112345678' (formato Evolution API)."""
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
    return data.get('key', {}).get('id', '')


def send_text_message(to: str, body: str) -> dict:
    url = _evo_url(f'/message/sendText/{_instance()}')
    payload = {'number': _normalize_phone(to), 'text': body}
    start = time.monotonic()
    response = None
    try:
        response = requests.post(url, json=payload, headers=_evo_headers(), timeout=15)
        response.raise_for_status()
        data = response.json()
        msg_id = _extract_message_id(data)
        logger.info('Mensaje de texto enviado a %s (id=%s)', to, msg_id)
        return {'id': msg_id}
    except requests.RequestException:
        logger.exception('Error enviando texto a %s', to)
        raise
    finally:
        _log_request(url, 'POST', payload, response, int((time.monotonic() - start) * 1000))


def send_media_message(to: str, media_url: str, mediatype: str, filename: str = '', caption: str = '') -> dict:
    url = _evo_url(f'/message/sendMedia/{_instance()}')
    payload = {'number': _normalize_phone(to), 'mediatype': mediatype, 'media': media_url}
    if caption:
        payload['caption'] = caption
    if filename:
        payload['fileName'] = filename
    start = time.monotonic()
    response = None
    try:
        response = requests.post(url, json=payload, headers=_evo_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()
        msg_id = _extract_message_id(data)
        logger.info('Media (%s) enviada a %s (id=%s)', mediatype, to, msg_id)
        return {'id': msg_id}
    except requests.RequestException:
        logger.exception('Error enviando media a %s', to)
        raise
    finally:
        _log_request(url, 'POST', payload, response, int((time.monotonic() - start) * 1000))
