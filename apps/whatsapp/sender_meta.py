"""Proveedor: WhatsApp Cloud API (Meta, oficial). Graph API."""
import json
import logging
import os
import time

import requests
from django.conf import settings

from .media_utils import ext_from_mime, get_mediatype

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
    """Formato que espera Meta Cloud API para el destinatario.

    Argentina: el wa_id entrante trae el '9' de celular (54 9 11 ...), pero para ENVIAR
    Meta espera el número SIN ese 9 (54 + área + número). Si no se saca, Meta responde
    131030 'recipient not in allowed list' / no entrega. Solo aplica a móviles argentinos
    (prefijo 549); el resto de los países no se toca.
    """
    p = phone.lstrip('+')
    if p.startswith('549'):
        p = '54' + p[3:]
    return p


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


def send_uploaded_media(to: str, raw: bytes, mime: str, filename: str = '', caption: str = '', is_ptt: bool = False) -> dict:
    """Sube el archivo a Meta (POST /media) y lo envía por su media id."""
    mediatype = get_mediatype(mime)
    media_id = _upload_media(raw, mime, filename)

    media_obj = {'id': media_id}
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


def _upload_media(raw: bytes, mime: str, filename: str = '') -> str:
    """Sube un archivo al endpoint de media de Meta y devuelve su id."""
    url = _url(f'{_phone_number_id()}/media')
    files = {
        'file': (filename or f'archivo{ext_from_mime(mime)}', raw, mime),
        'messaging_product': (None, 'whatsapp'),
        'type': (None, mime),
    }
    headers = {'Authorization': f'Bearer {_access_token()}'}  # sin Content-Type: multipart lo pone requests
    r = requests.post(url, files=files, headers=headers, timeout=30)
    if not r.ok:
        logger.error('Meta upload media error %s: %s', r.status_code, r.text[:300])
    r.raise_for_status()
    return r.json().get('id', '')


def download_and_save_media(message_data: dict, conv_pk: int) -> str:
    """Descarga un archivo entrante de Meta (metadata → URL temporal con Bearer) y lo guarda
    localmente. Devuelve la URL local o '' si falla."""
    media_id = message_data.get('media_id', '')
    filename = message_data.get('media_filename', '')
    if not media_id:
        return ''
    try:
        meta = requests.get(_url(media_id), headers=_headers(), timeout=15)
        if not meta.ok:
            logger.warning('Media metadata %s: %s', meta.status_code, meta.text[:200])
            return ''
        info = meta.json()
        download_url = info.get('url', '')
        mime = info.get('mime_type', message_data.get('media_mime', '')) or 'application/octet-stream'
        if not download_url:
            return ''
        dl = requests.get(download_url, headers={'Authorization': f'Bearer {_access_token()}'}, timeout=30)
        if not dl.ok:
            return ''
        ext = ext_from_mime(mime, filename)
        safe_name = f'{media_id[:24]}{ext}'
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', f'conv_{conv_pk}')
        os.makedirs(upload_dir, exist_ok=True)
        with open(os.path.join(upload_dir, safe_name), 'wb') as f:
            f.write(dl.content)
        return f'{settings.MEDIA_URL}uploads/conv_{conv_pk}/{safe_name}'
    except Exception as e:
        logger.error('Error descargando media Meta %s: %s', media_id, e)
        return ''


def send_template_message(to: str, plantilla, valores=None) -> dict:
    """Envía una plantilla (HSM) aprobada por Meta. `valores` son los parámetros del body
    en orden ({{1}}, {{2}}, ...)."""
    components = []
    if valores:
        components.append({
            'type': 'body',
            'parameters': [{'type': 'text', 'text': str(v)} for v in valores],
        })
    payload = {
        'messaging_product': 'whatsapp',
        'to': _normalize_phone(to),
        'type': 'template',
        'template': {
            'name': plantilla.get_meta_nombre(),
            'language': {'code': plantilla.meta_idioma or 'es_AR'},
            'components': components,
        },
    }
    return _post_message(payload)


def fetch_templates_from_meta() -> list:
    """Trae las plantillas registradas en la WABA con su estado de aprobación."""
    url = _url(f'{_waba_id()}/message_templates')
    templates = []
    params = {'limit': 100}
    try:
        while url:
            r = requests.get(url, headers=_headers(), timeout=15, params=params)
            r.raise_for_status()
            data = r.json()
            templates.extend(data.get('data', []))
            url = data.get('paging', {}).get('next')
            params = None
    except Exception as e:
        logger.error('Error trayendo plantillas de Meta: %s', e)
    return templates


def get_phone_number_info() -> dict:
    """verified_name, display_phone_number y quality_rating del número conectado.
    Se usa como 'test de conexión' de Meta desde la pantalla de configuración.
    Ante un error, devuelve el mensaje real que manda Meta (token vencido, id
    equivocado, etc.), no un "401" pelado."""
    url = _url(_phone_number_id())
    try:
        r = requests.get(
            url, headers=_headers(), timeout=10,
            params={'fields': 'verified_name,display_phone_number,quality_rating'},
        )
        data = r.json() if r.content else {}
        if not r.ok:
            err = data.get('error') or {}
            msg = err.get('message') or f'{r.status_code} {r.reason}'
            logger.error('Error consultando el número de Meta: %s', msg)
            return {'error': msg}
        return data
    except Exception as e:
        logger.error('Error consultando el número de Meta: %s', e)
        return {'error': str(e)}


# ── Funciones de conexión que no aplican a Meta (para paridad con el dispatcher) ──

def get_connection_state() -> str:
    """Meta no usa QR/instancia: reportamos 'open' si hay token+número, si no 'close'."""
    info = get_phone_number_info() if (_access_token() and _phone_number_id()) else {}
    return 'open' if info and 'error' not in info else 'close'
