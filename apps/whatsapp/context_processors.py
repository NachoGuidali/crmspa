"""Avisos de sistema que se muestran en todas las pantallas del CRM."""


def estado_whatsapp(request):
    """Cartel rojo cuando el WhatsApp del spa está desconectado.

    El mail puede tardar en leerse y el aviso por WhatsApp no puede salir (sale por la misma
    instancia caída), así que el canal que siempre funciona es el propio CRM: quien entra a
    trabajar lo ve en la primera pantalla que abra.

    Lee el estado que dejó el vigía (`apps.whatsapp.tasks.vigilar_conexion`), no le pregunta a
    Evolution: así no agrega una llamada HTTP a cada página.
    """
    usuario = getattr(request, 'user', None)
    if not (usuario and usuario.is_authenticated):
        return {}

    from .models import ConfiguracionWhatsApp

    try:
        config = ConfiguracionWhatsApp.objects.filter(pk=1).only(
            'estado_conexion', 'desconectado_desde').first()
    except Exception:
        return {}
    if config is None or not config.estado_conexion or config.estado_conexion == 'open':
        return {}
    return {'whatsapp_desconectado': {'estado': config.estado_conexion,
                                      'desde': config.desconectado_desde}}
