"""Vouchers de regalo: alta, cobro, entrega y canje.

El camino largo (el del bot) es este:

    crear()  →  pendiente_pago     el bot lo arma y le pasa el alias para transferir
    registrar_comprobante()  →  pendiente_aprobacion    mandó la transferencia; avisa al equipo
    aprobar()  →  activo           Fiore mira el comprobante; se dibuja y se manda solo
    canjear()  →  canjeado         se cambia por una reserva ya confirmada

Cargado a mano desde el CRM arranca directo en `activo`: ahí el pago ya lo vio quien lo carga.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.reservas import services as reservas_services

from . import diseno
from .models import Voucher

logger = logging.getLogger('apps.vouchers')


class VoucherError(Exception):
    pass


# ── Datos del voucher ─────────────────────────────────────────────────────────

def dias_de_validez():
    from apps.configuracion.models import ConfiguracionNegocio

    return ConfiguracionNegocio.get_solo().voucher_validez_dias or 60


def vencimiento(desde=None):
    return (desde or timezone.localdate()) + timedelta(days=dias_de_validez())


def precio(circuito, personas):
    """Lo que sale un voucher: la tarifa de FIN DE SEMANA para esa cantidad de personas.

    Decisión del 11/11/2026: se vende al precio más caro para que el voucher sirva para
    cualquier día y no haya diferencias que cobrar al canjearlo. Si lo canjean un día de
    semana, no se devuelve la diferencia (y el voucher lo dice: vale para cualquier día).
    """
    return circuito.precio_por_tarifa(personas or 1, finde=True)


def _validar_personas(circuito, personas):
    personas = int(personas or 1)
    if personas < circuito.capacidad_minima or personas > circuito.capacidad_maxima:
        raise VoucherError(
            f'{circuito.nombre} es para {circuito.capacidad_minima} a '
            f'{circuito.capacidad_maxima} personas.'
        )
    return personas


@transaction.atomic
def crear(*, circuito, personas=1, comprador_nombre, comprador_telefono='', comprador_email='',
          destinatario_nombre='', mensaje_regalo='', origen=Voucher.Origen.MANUAL,
          estado=Voucher.Estado.ACTIVO, monto=None, medio_pago='', fecha_vencimiento=None):
    """Crea el voucher. Sin `monto` lo calcula solo, así el bot no hace cuentas."""
    from utils.phone import normalize_ar_phone

    if not circuito.activo:
        raise VoucherError('El circuito no está activo.')
    personas = _validar_personas(circuito, personas)
    if not (comprador_nombre or '').strip():
        raise VoucherError('Falta el nombre de quien compra el voucher.')

    return Voucher.objects.create(
        circuito=circuito,
        personas=personas,
        monto=Decimal(monto) if monto is not None else precio(circuito, personas),
        comprador_nombre=comprador_nombre.strip()[:150],
        comprador_telefono=normalize_ar_phone(comprador_telefono) if comprador_telefono else '',
        comprador_email=(comprador_email or '').strip(),
        destinatario_nombre=(destinatario_nombre or '').strip()[:150],
        mensaje_regalo=(mensaje_regalo or '').strip(),
        estado=estado,
        origen=origen,
        medio_pago=medio_pago,
        fecha_vencimiento=fecha_vencimiento or vencimiento(),
    )


# ── Cobro ─────────────────────────────────────────────────────────────────────

def registrar_comprobante(voucher, archivo, *, medio_pago='transferencia'):
    """Guarda el comprobante y deja el voucher esperando que alguien del spa lo mire.

    El voucher NO se manda acá: hasta que no se verifica la transferencia no existe como
    regalo. Lo único que pasa es que al equipo le entra el aviso con el link.
    """
    if voucher.estado not in (Voucher.Estado.PENDIENTE_PAGO, Voucher.Estado.PENDIENTE_APROBACION):
        raise VoucherError('voucher_no_espera_pago')

    voucher.comprobante = archivo
    voucher.estado = Voucher.Estado.PENDIENTE_APROBACION
    voucher.medio_pago = medio_pago or voucher.medio_pago
    voucher.save(update_fields=['comprobante', 'estado', 'medio_pago'])
    _avisar_al_equipo(voucher)
    return voucher


def _avisar_al_equipo(voucher):
    from apps.configuracion import avisos
    from apps.configuracion.models import AvisoInterno

    avisos.disparar(AvisoInterno.Evento.VOUCHER_POR_VERIFICAR, {
        'cliente': voucher.comprador_nombre,
        'telefono': voucher.comprador_telefono,
        'email': voucher.comprador_email,
        'circuito': voucher.circuito.nombre,
        'personas': voucher.personas,
        'total': voucher.monto,
        'codigo': voucher.codigo,
        'destinatario': voucher.destinatario_nombre,
        'link': avisos.url_crm(f'/vouchers/{voucher.pk}/'),
    })


# ── Entrega ───────────────────────────────────────────────────────────────────

def generar_archivos(voucher, *, forzar=False):
    """Dibuja el voucher y lo guarda (PNG + PDF). Si ya están, no los vuelve a hacer."""
    if voucher.imagen and voucher.archivo_pdf and not forzar:
        return voucher

    imagen = diseno.dibujar(voucher)
    base = voucher.codigo.lower().replace('-', '_')
    voucher.imagen.save(f'{base}.png', ContentFile(diseno.png(voucher)), save=False)
    voucher.archivo_pdf.save(f'{base}.pdf', ContentFile(diseno.pdf(voucher, imagen)), save=False)
    voucher.save(update_fields=['imagen', 'archivo_pdf'])
    return voucher


def texto_de_entrega(voucher):
    vence = voucher.fecha_vencimiento.strftime('%d/%m/%Y')
    partes = [
        f'¡Listo! 🎁 Acá va el voucher de regalo de *{voucher.circuito.nombre}* '
        f'para {voucher.personas} {"persona" if voucher.personas == 1 else "personas"}.',
        '',
        f'Código: *{voucher.codigo}*',
        f'Válido hasta el {vence}.',
        '',
        'Para usarlo, quien lo reciba nos escribe por acá con el código y coordinamos la fecha '
        'según la disponibilidad. ¡Que lo disfruten! 💚',
    ]
    return '\n'.join(partes)


def enviar(voucher, *, usuario=None):
    """Le manda el voucher por WhatsApp a quien lo compró (y por mail si dejó uno).

    Va al comprador y no al destinatario: es un regalo, lo entrega quien lo compró cuando
    quiera. Si el WhatsApp falla, se levanta el error para que la pantalla lo muestre; el
    voucher ya está activo y se puede reintentar con el botón.
    """
    from apps.whatsapp import services as whatsapp_services

    generar_archivos(voucher)
    if not voucher.comprador_telefono:
        raise VoucherError('El voucher no tiene teléfono de quien lo compró.')

    voucher.imagen.open('rb')
    try:
        contenido = voucher.imagen.read()
    finally:
        voucher.imagen.close()

    whatsapp_services.enviar_archivo(
        telefono=voucher.comprador_telefono,
        contenido=contenido,
        mime='image/png',
        filename=f'{voucher.codigo}.png',
        caption=texto_de_entrega(voucher),
        usuario=usuario,
    )
    voucher.enviado_at = timezone.now()
    voucher.save(update_fields=['enviado_at'])
    _enviar_por_email(voucher)
    return voucher


def _enviar_por_email(voucher):
    """El mismo voucher en PDF por mail, si dejó uno.

    Es un extra: si el mail falla, el voucher ya salió por WhatsApp, así que se loguea y
    listo. Va el PDF porque es el formato que se imprime o se reenvía bien por mail.
    """
    if not voucher.comprador_email:
        return
    try:
        from django.core.mail import EmailMessage

        from apps.configuracion.models import ConfiguracionNegocio

        config = ConfiguracionNegocio.get_solo()
        voucher.archivo_pdf.open('rb')
        try:
            pdf = voucher.archivo_pdf.read()
        finally:
            voucher.archivo_pdf.close()

        mail = EmailMessage(
            subject=f'Tu voucher de regalo — {voucher.circuito.nombre}',
            body=texto_de_entrega(voucher).replace('*', ''),
            from_email=config.remitente(),
            to=[voucher.comprador_email],
            connection=config.conexion_email(),
        )
        mail.attach(f'{voucher.codigo}.pdf', pdf, 'application/pdf')
        mail.send(fail_silently=False)
    except Exception:
        logger.exception('No se pudo mandar por mail el voucher %s', voucher.codigo)


@transaction.atomic
def aprobar(voucher, *, usuario=None):
    """Fiore vio la transferencia: el voucher pasa a activo y sale para el cliente."""
    if voucher.estado in (Voucher.Estado.CANJEADO, Voucher.Estado.CANCELADO):
        raise VoucherError('voucher_no_aprobable')

    voucher.estado = Voucher.Estado.ACTIVO
    voucher.aprobado_at = timezone.now()
    voucher.aprobado_por = usuario if getattr(usuario, 'pk', None) else None
    # Recién ahora arranca la validez: el plazo se cuenta desde que el regalo existe, no
    # desde que el bot armó el borrador.
    voucher.fecha_vencimiento = vencimiento()
    voucher.save(update_fields=['estado', 'aprobado_at', 'aprobado_por', 'fecha_vencimiento'])
    generar_archivos(voucher, forzar=True)
    return voucher


# ── Canje ─────────────────────────────────────────────────────────────────────

def validar(codigo):
    """Devuelve el voucher si es canjeable, o lanza VoucherError."""
    try:
        voucher = Voucher.objects.select_related('circuito').get(codigo=codigo.strip().upper())
    except Voucher.DoesNotExist:
        raise VoucherError('codigo_inexistente')
    if voucher.estado == Voucher.Estado.CANJEADO:
        raise VoucherError('ya_canjeado')
    if voucher.estado == Voucher.Estado.CANCELADO:
        raise VoucherError('cancelado')
    # Un voucher que el bot armó pero que nadie pagó no vale como regalo. Antes de tener
    # estos dos estados, cualquier cosa que no estuviera canjeada ni cancelada pasaba.
    if voucher.estado == Voucher.Estado.PENDIENTE_PAGO:
        raise VoucherError('falta_el_pago')
    if voucher.estado == Voucher.Estado.PENDIENTE_APROBACION:
        raise VoucherError('pago_en_revision')
    if voucher.vencido:
        raise VoucherError('vencido')
    return voucher


@transaction.atomic
def canjear(codigo, *, telefono, nombre_contacto, turno_id, fecha, cantidad_personas=None):
    """Canjea un voucher creando una reserva ya confirmada (el circuito está pago).

    Sin `cantidad_personas` van las del voucher: es lo que se pagó. Si vienen más, la
    diferencia queda como saldo de la reserva y se paga el día.
    """
    voucher = validar(codigo)
    personas = int(cantidad_personas or voucher.personas)

    reserva = reservas_services.crear_reserva(
        telefono=telefono,
        nombre_contacto=nombre_contacto,
        circuito_id=voucher.circuito_id,
        turno_id=turno_id,
        fecha=fecha,
        cantidad_personas=personas,
        notas=f'Canje de voucher {voucher.codigo}',
    )
    # El voucher cubre la seña: la reserva queda confirmada y arranca la ventana de reembolso.
    from apps.reservas.models import Reserva
    reserva.estado = Reserva.Estado.CONFIRMADO
    # El voucher se vendió a tarifa de fin de semana: si lo canjean un día de semana, lo
    # pagado no puede superar el total o la reserva quedaría con saldo negativo. Si vienen
    # más personas que las del voucher, la diferencia queda como saldo a pagar ese día.
    reserva.monto_pagado = min(voucher.monto, reserva.total)
    reserva.sena_pagada_at = timezone.now()
    reserva.save(update_fields=['estado', 'monto_pagado', 'sena_pagada_at'])

    voucher.estado = Voucher.Estado.CANJEADO
    voucher.reserva_canje = reserva
    voucher.canjeado_at = timezone.now()
    voucher.save(update_fields=['estado', 'reserva_canje', 'canjeado_at'])
    return reserva, voucher
