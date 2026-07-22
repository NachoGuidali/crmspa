import base64
import json
import logging
import os
import time

import requests
from django.conf import settings

from .media_utils import ext_from_mime, get_mediatype

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


# ── Conexión de la instancia (QR, estado, alta) ──────────────────────────────

def get_connection_state() -> str:
    """Estado de la instancia: 'open' (conectado), 'connecting', 'close' o 'error'."""
    url = _evo_url(f'/instance/connectionState/{_instance()}')
    try:
        r = requests.get(url, headers=_evo_headers(), timeout=10)
        r.raise_for_status()
        data = r.json()
        # v2: {"instance": {"state": "open"}} — con variantes según versión.
        return (
            data.get('instance', {}).get('state')
            or data.get('connectionStatus')
            or data.get('state')
            or 'close'
        )
    except Exception as e:
        logger.error('Error consultando estado de conexión: %s', e)
        return 'error'


def trigger_connect() -> None:
    """Dispara la conexión de Baileys una vez. El QR llega por el webhook QRCODE_UPDATED."""
    try:
        requests.get(_evo_url(f'/instance/connect/{_instance()}'), headers=_evo_headers(), timeout=10)
    except Exception as e:
        logger.error('Error disparando connect: %s', e)


def ensure_instance_exists() -> None:
    """Crea la instancia en Evolution si todavía no existe (idempotente)."""
    instance = _instance()
    try:
        r = requests.get(_evo_url('/instance/fetchInstances'), headers=_evo_headers(), timeout=10)
        if r.ok:
            for i in (r.json() if isinstance(r.json(), list) else []):
                name = (
                    i.get('instance', {}).get('instanceName')
                    or i.get('instanceName') or i.get('name') or ''
                )
                if name == instance:
                    return
    except Exception:
        pass
    # v2.2.3+ usa 'name'; versiones viejas 'instanceName' — probamos ambas.
    for payload in (
        {'name': instance, 'integration': 'WHATSAPP-BAILEYS'},
        {'instanceName': instance, 'integration': 'WHATSAPP-BAILEYS'},
    ):
        try:
            r = requests.post(_evo_url('/instance/create'), json=payload, headers=_evo_headers(), timeout=15)
            if r.ok or r.status_code == 403:
                logger.info('Instancia Evolution "%s" lista', instance)
                return
        except Exception as e:
            logger.error('Error creando instancia: %s', e)


def setup_instance_webhook(webhook_url: str) -> bool:
    """Registra en Evolution la URL a la que debe mandar los eventos entrantes.
    Si no hay webhook_token, usamos la propia API key de Evolution como token del
    header (el CRM también la acepta), así el webhook no queda sin autenticar."""
    url = _evo_url(f'/webhook/set/{_instance()}')
    webhook_token = _cfg('webhook_token') or _cfg('evolution_api_key') or ''
    payload = {'webhook': {
        'enabled': True, 'url': webhook_url, 'webhook_by_events': False, 'webhook_base64': False,
        'events': ['MESSAGES_UPSERT', 'MESSAGES_UPDATE', 'CONNECTION_UPDATE', 'QRCODE_UPDATED'],
        'headers': {'apikey': webhook_token} if webhook_token else {},
    }}
    try:
        r = requests.post(url, json=payload, headers=_evo_headers(), timeout=10)
        r.raise_for_status()
        logger.info('Webhook Evolution configurado: %s', webhook_url)
        return True
    except Exception as e:
        logger.error('Error configurando webhook Evolution: %s', e)
        return False


def send_uploaded_media(to: str, raw: bytes, mime: str, filename: str = '', caption: str = '', is_ptt: bool = False) -> dict:
    """Envía un archivo subido desde el inbox. Evolution acepta el media en base64; probamos
    base64 crudo y, si falla, data-URI. Para notas de voz usa el endpoint de audio (PTT)."""
    b64 = base64.b64encode(raw).decode('utf-8')
    mediatype = get_mediatype(mime)

    intentos = []
    if is_ptt and mediatype == 'audio':
        intentos.append(lambda data: _send_audio(to, data, filename))
    intentos.append(lambda data: send_media_message(to, data, mediatype, filename=filename, caption=caption))

    last_exc = None
    for enviar in intentos:
        for data in (b64, f'data:{mime};base64,{b64}'):
            try:
                return enviar(data)
            except requests.RequestException as exc:
                last_exc = exc
    raise last_exc


def _send_audio(to: str, audio_b64: str, filename: str = '') -> dict:
    url = _evo_url(f'/message/sendWhatsAppAudio/{_instance()}')
    payload = {'number': _normalize_phone(to), 'audio': audio_b64}
    if filename:
        payload['fileName'] = filename
    start = time.monotonic()
    response = None
    try:
        response = requests.post(url, json=payload, headers=_evo_headers(), timeout=30)
        response.raise_for_status()
        return {'id': _extract_message_id(response.json())}
    finally:
        _log_request(url, 'POST', {'number': payload['number'], 'audio': '<base64>'}, response,
                     int((time.monotonic() - start) * 1000))


def download_and_save_media(message_data: dict, conv_pk: int) -> str:
    """Descarga el archivo (desencriptado) de un mensaje entrante de Evolution y lo guarda
    localmente. Devuelve la URL local (/media/...) o '' si falla."""
    message_id = message_data.get('message_id', '')
    filename = message_data.get('media_filename', '')
    if not message_id:
        return ''
    try:
        url = _evo_url(f'/chat/getBase64FromMediaMessage/{_instance()}')
        r = requests.post(url, json={'message': {'key': {'id': message_id}}}, headers=_evo_headers(), timeout=30)
        if not r.ok:
            logger.warning('getBase64FromMediaMessage %s: %s', r.status_code, r.text[:200])
            return ''
        data = r.json()
        b64 = data.get('base64') or data.get('data') or ''
        if not b64:
            return ''
        if ',' in b64:
            b64 = b64.split(',', 1)[1]
        mime = data.get('mimetype') or message_data.get('media_mime') or 'application/octet-stream'
        return _guardar_media_local(base64.b64decode(b64), mime, filename, conv_pk, message_id)
    except Exception as e:
        logger.error('Error descargando media %s: %s', message_id, e)
        return ''


def _guardar_media_local(contenido: bytes, mime: str, filename: str, conv_pk: int, ref: str) -> str:
    ext = ext_from_mime(mime, filename)
    safe_name = f'{ref[:24]}{ext}'
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', f'conv_{conv_pk}')
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, safe_name), 'wb') as f:
        f.write(contenido)
    return f'{settings.MEDIA_URL}uploads/conv_{conv_pk}/{safe_name}'


def logout_instance() -> None:
    """Desvincula el WhatsApp de la instancia (cierra sesión)."""
    instance = _instance()
    try:
        r = requests.delete(_evo_url(f'/instance/logout/{instance}'), headers=_evo_headers(), timeout=10)
        if r.ok:
            return
    except Exception:
        pass
    try:
        requests.post(_evo_url(f'/instance/restart/{instance}'), headers=_evo_headers(), timeout=10)
    except Exception as e:
        logger.error('Error en logout/restart de instancia: %s', e)
