"""Avisos internos: qué se le manda al equipo cuando pasa algo, y a quién.

El CRM llama a `disparar(evento, contexto)` y se olvida: acá se decide si ese motivo está
activo, a qué mails y a qué WhatsApps va, y con qué texto. Todo configurable desde
Configuración → Avisos internos, sin tocar código.
"""
import logging

logger = logging.getLogger('apps.configuracion')


class _Faltantes(dict):
    """Una variable que el motivo no tiene no rompe el aviso: queda vacía."""

    def __missing__(self, clave):
        return ''


def render(texto, contexto):
    try:
        return texto.format_map(_Faltantes(contexto))
    except (ValueError, IndexError) as exc:
        # Llaves mal escritas en el texto que cargó el usuario: se manda sin reemplazar antes
        # que no mandar nada.
        logger.warning('Texto de aviso con formato inválido (%s): %s', exc, texto[:80])
        return texto


def detalle_por_defecto(contexto):
    """El texto que se manda cuando el motivo no tiene uno escrito: todos los datos que haya."""
    ETIQUETAS = [
        ('cliente', 'Cliente'), ('telefono', 'Teléfono'), ('email', 'Email'),
        ('circuito', 'Circuito'), ('fecha', 'Fecha'), ('turno', 'Turno'),
        ('personas', 'Personas'), ('total', 'Total'), ('sena', 'Seña'),
        ('medio_pago', 'Medio de pago'), ('estado', 'Estado'), ('extras', 'Extras'),
        ('menu', 'Menú especial'), ('motivo', 'Motivo'), ('destino_sena', 'Seña'),
        ('link', 'Ver en el CRM'),
    ]
    return '\n'.join(f'{etiqueta}: {contexto[clave]}' for clave, etiqueta in ETIQUETAS
                     if contexto.get(clave) not in (None, ''))


def disparar(evento, contexto):
    """Dispara el aviso de un motivo. Nunca rompe lo que lo llamó: va por Celery."""
    from .tasks import enviar_aviso_interno

    try:
        enviar_aviso_interno.delay(evento, {k: ('' if v is None else str(v)) for k, v in contexto.items()})
    except Exception:
        # Redis caído: el aviso se pierde, pero la reserva (o lo que sea) sigue su curso.
        logger.exception('No se pudo encolar el aviso interno %s', evento)


def url_crm(path):
    """Link absoluto al CRM para poder tocarlo desde el mail o el WhatsApp."""
    from django.conf import settings

    origenes = getattr(settings, 'CSRF_TRUSTED_ORIGINS', None) or []
    if origenes:
        base = origenes[0].rstrip('/')
    else:
        hosts = [h for h in settings.ALLOWED_HOSTS if h not in ('*', 'localhost', '127.0.0.1')]
        base = f'https://{hosts[0]}' if hosts else 'http://localhost:8000'
    return f'{base}{path}'


def contexto_reserva(reserva, **extra):
    """Todos los datos de una reserva, listos para usar como variables del aviso."""
    from django.urls import reverse

    extras = ', '.join(
        f'{e.cantidad}× {e.nombre}' if e.cantidad > 1 else e.nombre
        for e in reserva.extras.all()
    )
    contacto = reserva.contacto
    datos = {
        'cliente': contacto.nombre,
        'telefono': contacto.telefono,
        'email': contacto.email or '',
        'circuito': reserva.circuito.nombre,
        'fecha': reserva.fecha.strftime('%d/%m/%Y'),
        'turno': reserva.turno.nombre if reserva.turno else '',
        'personas': reserva.cantidad_personas,
        'total': f'${reserva.total:,.0f}'.replace(',', '.'),
        'sena': f'${reserva.monto_sena:,.0f}'.replace(',', '.') if reserva.monto_sena else '',
        'medio_pago': reserva.get_medio_pago_display() or 'sin especificar',
        'estado': reserva.get_estado_display(),
        'extras': extras,
        'menu': '',
        'link': url_crm(reverse('reservas:detalle', args=[reserva.pk])),
    }
    datos.update(extra)
    return datos
