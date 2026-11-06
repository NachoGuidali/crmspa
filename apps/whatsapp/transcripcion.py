"""Pasa a texto las notas de voz que manda el cliente.

Por qué vive en el CRM y no en n8n: el archivo ya está acá (`download_and_save_media` baja
todo lo entrante), el endpoint del historial que lee el bot manda `contenido`, así que con
esto el bot entiende los audios sin tocar el workflow — y, sobre todo, el equipo los LEE en
el inbox en vez de tener que escucharlos.

El proveedor se elige por `.env`. Los dos endpoints son compatibles entre sí (la API de Groq
copia la de OpenAI), así que cambiar de uno al otro es cambiar dos variables.
"""
import logging
import re

import requests
from django.conf import settings

from .media_utils import ext_from_mime

logger = logging.getLogger('apps.whatsapp')

ENDPOINTS = {
    'openai': 'https://api.openai.com/v1/audio/transcriptions',
    'groq': 'https://api.groq.com/openai/v1/audio/transcriptions',
}

# Tope de los dos proveedores para un archivo de audio. Una nota de voz de WhatsApp pesa
# cerca de 1 MB por minuto, así que esto no se toca nunca por duración normal.
MAX_BYTES = 25 * 1024 * 1024

# Un audio de menos de esto es un botón del micrófono tocado sin querer. No se manda: además
# de no decir nada, es justo el caso donde Whisper INVENTA texto (ver ALUCINACIONES).
MIN_BYTES = 1500

# Vocabulario del spa. La API acepta un texto corto que sesga la transcripción hacia estas
# palabras; sin esto "la seña" sale "la señal" y "tina finlandesa" sale cualquier cosa.
VOCABULARIO = (
    'Cuatro Raíces, spa, circuito, seña, tina finlandesa, sauna seco, ducha escocesa, '
    'hidromasaje, masaje descontracturante, despedida de soltera, spa en pareja, '
    'spa grupal premium, Fiorella, turno, reserva, transferencia, comprobante.'
)

# Whisper, con silencio o ruido casi puro, devuelve frases de los subtítulos con los que se
# entrenó. Si una de estas entrara como si fuera la clienta hablando, María le contestaría a
# un fantasma. Se descartan.
ALUCINACIONES = (
    'subtitulos realizados por', 'subtítulos realizados por', 'subtitulado por',
    'gracias por ver el video', 'gracias por ver este video', 'amara.org',
    'suscribite al canal', 'suscríbete al canal', 'no olvides suscribirte',
    'thanks for watching', 'subscribe to my channel', 'www.',
)


def habilitada():
    """True si hay con qué transcribir y el dueño lo prendió."""
    from .models import ConfiguracionWhatsApp

    if not _api_key():
        return False
    config = ConfiguracionWhatsApp.objects.filter(pk=1).first()
    return bool(config and config.transcribir_audios)


def _api_key():
    return (getattr(settings, 'TRANSCRIPCION_API_KEY', '') or '').strip()


def _proveedor():
    nombre = (getattr(settings, 'TRANSCRIPCION_PROVEEDOR', 'openai') or 'openai').strip().lower()
    return nombre if nombre in ENDPOINTS else 'openai'


def _modelo():
    return (getattr(settings, 'TRANSCRIPCION_MODELO', '') or '').strip() or (
        'gpt-transcribe' if _proveedor() == 'openai' else 'whisper-large-v3-turbo'
    )


def _max_segundos():
    from .models import ConfiguracionWhatsApp

    config = ConfiguracionWhatsApp.objects.filter(pk=1).first()
    return config.transcripcion_max_segundos if config else 300


def _limpiar(texto):
    """Descarta lo que claramente no dijo nadie y normaliza los espacios."""
    texto = re.sub(r'\s+', ' ', (texto or '')).strip()
    if not texto:
        return ''
    plano = texto.lower().strip(' .!¡?¿-')
    for frase in ALUCINACIONES:
        if frase in plano:
            logger.info('Transcripción descartada por alucinación de Whisper: %r', texto[:80])
            return ''
    # Una transcripción de una sola letra o un solo signo tampoco aporta nada.
    if len(plano) <= 1:
        return ''
    return texto


def transcribir(raw, mime='audio/ogg', filename='', segundos=0):
    """Devuelve el texto del audio, o '' si no se pudo (o no corresponde) transcribir.

    Nunca levanta excepción: si falla, el mensaje queda como "[Audio]" y el bot pide que lo
    escriban, que es exactamente lo que hace hoy. Degradar es mejor que romper el webhook.
    """
    if not habilitada():
        return ''
    if not raw or len(raw) < MIN_BYTES:
        return ''
    if len(raw) > MAX_BYTES:
        logger.info('Audio de %s bytes: supera el tope del proveedor, no se transcribe', len(raw))
        return ''

    tope = _max_segundos()
    if tope and segundos and segundos > tope:
        logger.info('Audio de %ss: supera el tope de %ss, no se transcribe', segundos, tope)
        return ''

    proveedor = _proveedor()
    nombre = filename or f'audio{ext_from_mime(mime)}'
    datos = {
        'model': _modelo(),
        # Sin esto el modelo primero adivina el idioma: tarda más y con audios cortos o con
        # ruido se equivoca.
        'language': 'es',
        'prompt': VOCABULARIO,
        'response_format': 'json',
    }
    try:
        r = requests.post(
            ENDPOINTS[proveedor],
            headers={'Authorization': f'Bearer {_api_key()}'},
            files={'file': (nombre, raw, mime.split(';')[0].strip() or 'audio/ogg')},
            data=datos,
            timeout=60,
        )
        if not r.ok:
            logger.warning('Transcripción (%s) %s: %s', proveedor, r.status_code, r.text[:300])
            return ''
        try:
            texto = r.json().get('text', '')
        except ValueError:
            texto = r.text
        return _limpiar(texto)
    except requests.RequestException as e:
        logger.warning('Error transcribiendo el audio con %s: %s', proveedor, e)
        return ''


def transcribir_archivo_local(media_url, mime='audio/ogg', filename='', segundos=0):
    """Igual que `transcribir`, pero leyendo el archivo que ya guardamos en disco."""
    import os

    if not media_url:
        return ''
    rel = media_url.replace(settings.MEDIA_URL, '', 1).lstrip('/')
    ruta = os.path.join(settings.MEDIA_ROOT, rel)
    if not os.path.exists(ruta):
        logger.warning('No está en disco el audio a transcribir: %s', media_url)
        return ''
    with open(ruta, 'rb') as f:
        return transcribir(f.read(), mime=mime, filename=filename, segundos=segundos)
