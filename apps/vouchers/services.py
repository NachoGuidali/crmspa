from django.db import transaction
from django.utils import timezone

from apps.reservas import services as reservas_services

from .models import Voucher


class VoucherError(Exception):
    pass


def validar(codigo):
    """Devuelve el voucher si es canjeable, o lanza VoucherError."""
    try:
        voucher = Voucher.objects.get(codigo=codigo.strip().upper())
    except Voucher.DoesNotExist:
        raise VoucherError('codigo_inexistente')
    if voucher.estado == Voucher.Estado.CANJEADO:
        raise VoucherError('ya_canjeado')
    if voucher.estado == Voucher.Estado.CANCELADO:
        raise VoucherError('cancelado')
    if voucher.fecha_vencimiento < timezone.localdate():
        raise VoucherError('vencido')
    return voucher


@transaction.atomic
def canjear(codigo, *, telefono, nombre_contacto, turno_id, fecha, cantidad_personas=1):
    """Canjea un voucher creando una reserva ya confirmada (el circuito está pago)."""
    voucher = validar(codigo)

    reserva = reservas_services.crear_reserva(
        telefono=telefono,
        nombre_contacto=nombre_contacto,
        circuito_id=voucher.circuito_id,
        turno_id=turno_id,
        fecha=fecha,
        cantidad_personas=cantidad_personas,
        notas=f'Canje de voucher {voucher.codigo}',
    )
    # El voucher cubre la seña: la reserva queda confirmada.
    from apps.reservas.models import Reserva
    reserva.estado = Reserva.Estado.CONFIRMADO
    reserva.monto_pagado = voucher.monto
    reserva.save(update_fields=['estado', 'monto_pagado'])

    voucher.estado = Voucher.Estado.CANJEADO
    voucher.reserva_canje = reserva
    voucher.canjeado_at = timezone.now()
    voucher.save(update_fields=['estado', 'reserva_canje', 'canjeado_at'])
    return reserva, voucher
