"""
Dispatcher de proveedor de WhatsApp.

Según el campo `proveedor` de ConfiguracionWhatsApp, delega el envío a Evolution
API (no oficial, con QR) o a Meta Cloud API (oficial). Las vistas, tasks y
servicios importan siempre desde `apps.whatsapp.sender` sin enterarse del
proveedor activo.

Las funciones de conexión de instancia (QR, alta, webhook, logout) son propias
de Evolution y se re-exportan directamente para la pantalla de configuración.
"""
from . import sender_evolution, sender_meta
from .media_utils import get_mediatype  # noqa: F401 (re-export)

# Helpers de Evolution que la config usa directamente (no aplican a Meta).
from .sender_evolution import (  # noqa: F401
    ensure_instance_exists,
    logout_instance,
    setup_instance_webhook,
    trigger_connect,
)


def get_proveedor() -> str:
    from .models import ConfiguracionWhatsApp
    return ConfiguracionWhatsApp.get_proveedor()


def _backend():
    from .models import ConfiguracionWhatsApp
    if get_proveedor() == ConfiguracionWhatsApp.Proveedor.META:
        return sender_meta
    return sender_evolution


# ── Envío (rutea por proveedor) ──────────────────────────────────────────────

def send_text_message(to, body):
    return _backend().send_text_message(to, body)


def send_media_message(to, media_url, mediatype, filename='', caption=''):
    return _backend().send_media_message(to, media_url, mediatype, filename=filename, caption=caption)


def get_connection_state() -> str:
    """Estado de conexión del proveedor activo (Evolution: instancia; Meta: token+número)."""
    return _backend().get_connection_state()
