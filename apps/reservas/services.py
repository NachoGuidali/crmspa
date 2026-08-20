from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.circuitos.models import Circuito, Extra
from apps.configuracion.models import ConfiguracionNegocio
from apps.configuracion.tasks import notificar_evento
from apps.contactos.models import Contacto
from apps.turnero.models import Turno
from utils.phone import normalize_ar_phone

from .models import Pago, Reserva, ReservaExtra


class ReservaError(Exception):
    """Error de negocio al crear/modificar una reserva (cupo, día no habilitado, etc.)."""


def _lock_slot(circuito_id, turno_id, fecha):
    """
    Toma un advisory lock de transacción para serializar la validación de cupo. Sin esto,
    dos reservas concurrentes leen el mismo cupo disponible y ambas insertan → sobreventa.
    El lock se libera solo al terminar la transacción. DEBE llamarse dentro de @transaction.atomic.

    - Modo exclusivo: el lock es por (turno, fecha), sin circuito, para que dos reservas de
      circuitos distintos en el mismo horario también se serialicen entre sí.
    - Modo por circuito: el lock es por (circuito, turno, fecha).
    """
    if ConfiguracionNegocio.get_solo().reserva_exclusiva_por_turno:
        key = f'reserva-slot-excl:{turno_id}-{fecha.isoformat()}'
    else:
        key = f'reserva-slot:{circuito_id}-{turno_id}-{fecha.isoformat()}'
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [key])


def _validar_fecha_futura(fecha):
    if fecha < timezone.localdate():
        raise ReservaError('fecha_en_el_pasado')


def _resolver_extras(circuito, extras_data):
    """Valida una lista de extras pedidos (`[{"extra_id": 3, "cantidad": 2}, ...]`) contra el
    catálogo: tienen que existir, estar activos, y aplicar a este circuito (globales o propios
    de él). Devuelve una lista de (Extra, cantidad)."""
    resueltos = []
    for item in extras_data or []:
        if not isinstance(item, dict):
            raise ReservaError(f'extra_invalido: {item}')
        extra_id = item.get('extra_id') or item.get('id')
        try:
            cantidad = int(item.get('cantidad') or 1)
        except (TypeError, ValueError):
            raise ReservaError(f'extra_cantidad_invalida: {extra_id}')
        if cantidad < 1:
            raise ReservaError(f'extra_cantidad_invalida: {extra_id}')
        try:
            extra = Extra.objects.get(pk=extra_id, activo=True)
        except (Extra.DoesNotExist, TypeError, ValueError):
            raise ReservaError(f'extra_not_found: {extra_id}')
        if extra.circuito_id and extra.circuito_id != circuito.id:
            raise ReservaError(f'extra_no_aplica_al_circuito: {extra_id}')
        resueltos.append((extra, cantidad))
    return resueltos


@transaction.atomic
def crear_reserva(
    *, telefono, nombre_contacto, circuito_id, turno_id, fecha,
    cantidad_personas=1, acompanantes=None, notas='', extras=None,
):
    from apps.turnero.services import dia_habilitado, turnos_bloqueados

    telefono = normalize_ar_phone(telefono)
    _validar_fecha_futura(fecha)
    try:
        circuito = Circuito.objects.get(pk=circuito_id, activo=True)
    except Circuito.DoesNotExist:
        raise ReservaError('circuito_not_found')

    try:
        turno = Turno.objects.get(pk=turno_id, activo=True)
    except Turno.DoesNotExist:
        raise ReservaError('turno_not_found')

    if not turno.aplica_en(fecha):
        raise ReservaError('turno_no_aplica_ese_dia')

    if not dia_habilitado(fecha):
        raise ReservaError('dia_no_habilitado')

    bloqueados_ids, dia_completo = turnos_bloqueados(circuito, fecha)
    if dia_completo or turno.id in bloqueados_ids:
        raise ReservaError('turno_bloqueado')

    extras_resueltos = _resolver_extras(circuito, extras)
    extras_total = sum((e.precio * cant for e, cant in extras_resueltos), Decimal('0'))

    # Serializa la validación de cupo de este slot puntual (anti-sobreventa).
    _lock_slot(circuito.id, turno.id, fecha)

    contacto, _ = Contacto.objects.get_or_create(
        telefono=telefono, defaults={'nombre': nombre_contacto or telefono},
    )
    if nombre_contacto and not contacto.nombre:
        contacto.nombre = nombre_contacto
        contacto.save()

    config = ConfiguracionNegocio.get_solo()
    precio_total = circuito.precio_para(fecha, cantidad_personas)
    # La seña se calcula sobre circuito + extras (si el cliente pidió "menú sin TACC" u otro
    # opcional, se cubre con la misma seña, no queda afuera).
    monto_sena = circuito.monto_sena_para(fecha, cantidad_personas, monto_adicional=extras_total)

    reserva = Reserva(
        contacto=contacto,
        circuito=circuito,
        turno=turno,
        fecha=fecha,
        cantidad_personas=cantidad_personas,
        acompanantes=acompanantes or [],
        estado=Reserva.Estado.PENDIENTE_SENA,
        precio_total=precio_total,
        monto_sena=monto_sena,
        vencimiento_sena=timezone.now() + timedelta(hours=config.plazo_pago_sena_horas),
        notas=notas,
    )
    try:
        reserva.full_clean()
    except ValidationError as e:
        raise ReservaError('sin_cupo: ' + '; '.join(e.messages))

    reserva.save()

    for extra, cantidad in extras_resueltos:
        ReservaExtra.objects.create(
            reserva=reserva, extra=extra, nombre=extra.nombre,
            precio_unitario=extra.precio, cantidad=cantidad,
        )

    return reserva


def _reserva_bot_duplicada(telefono, circuito_id, turno_id, fecha):
    """Idempotencia: si n8n reintenta POST /reservas/bot/ (timeout, retry) para el mismo
    contacto+circuito+turno+fecha en una ventana corta, devolvemos la reserva ya creada en vez
    de duplicarla. Necesario sobre todo en modo por-circuito, donde el lock de cupo no evita el
    duplicado (dos reservas del mismo bot sí caben en el mismo slot)."""
    ventana = timezone.now() - timedelta(minutes=5)
    return (
        Reserva.objects.filter(
            contacto__telefono=telefono, circuito_id=circuito_id, turno_id=turno_id, fecha=fecha,
            origen=Reserva.Origen.WHATSAPP_BOT, estado__in=Reserva.ESTADOS_QUE_OCUPAN_CUPO,
            created_at__gte=ventana,
        )
        .order_by('-created_at').first()
    )


@transaction.atomic
def crear_reserva_bot(*, telefono, nombre_contacto, circuito_id, turno_id, fecha,
                      cantidad_personas=1, medio_pago='', resumen='',
                      comprobante=None, link_pago='', extras=None):
    """Crea una reserva desde el bot de WhatsApp: valida cupo (estructurado) y setea el estado
    según el medio de pago.
      - transferencia → pendiente_aprobacion (el staff verifica el comprobante)
      - mercado_pago  → pendiente_pago (se confirma solo cuando MP avisa)
    """
    telefono_norm = normalize_ar_phone(telefono)
    existente = _reserva_bot_duplicada(telefono_norm, circuito_id, turno_id, fecha)
    if existente is not None:
        return existente

    reserva = crear_reserva(
        telefono=telefono, nombre_contacto=nombre_contacto,
        circuito_id=circuito_id, turno_id=turno_id, fecha=fecha,
        cantidad_personas=cantidad_personas, extras=extras,
    )
    reserva.origen = Reserva.Origen.WHATSAPP_BOT
    reserva.resumen = resumen or ''
    reserva.medio_pago = medio_pago or ''

    if medio_pago == Reserva.MedioPago.TRANSFERENCIA:
        reserva.estado = Reserva.Estado.PENDIENTE_APROBACION
        if comprobante is not None:
            reserva.comprobante = comprobante
    elif medio_pago == Reserva.MedioPago.MERCADO_PAGO:
        reserva.estado = Reserva.Estado.PENDIENTE_PAGO
        reserva.link_pago = link_pago or ''
    # otros medios quedan como pendiente_sena (el que puso crear_reserva)

    reserva.save()

    notificar_evento.delay(
        'Nueva reserva del bot',
        f'{reserva.contacto.nombre} ({reserva.contacto.telefono}) — {reserva.circuito.nombre} — '
        f'{reserva.fecha} ({reserva.turno.nombre}) — {reserva.cantidad_personas} persona(s) — '
        f'medio de pago: {reserva.get_medio_pago_display() or "sin especificar"} — '
        f'estado: {reserva.get_estado_display()}.',
    )
    return reserva


def confirmar_reserva(reserva):
    """Confirma la reserva (Mercado Pago acreditó, o el staff aprobó el comprobante de
    transferencia) y le avisa al bot para que mande la confirmación final al cliente."""
    reserva.estado = Reserva.Estado.CONFIRMADO
    reserva.save(update_fields=['estado', 'updated_at'])
    from apps.whatsapp.tasks import notificar_reserva_aprobada
    notificar_reserva_aprobada.delay(reserva.id)
    notificar_evento.delay(
        'Reserva confirmada',
        f'{reserva.contacto.nombre} ({reserva.contacto.telefono}) — {reserva.circuito.nombre} — '
        f'{reserva.fecha} ({reserva.turno.nombre}).',
    )
    return reserva


@transaction.atomic
def confirmar_sena(reserva, monto, medio_pago):
    Pago.objects.create(reserva=reserva, monto=monto, medio_pago=medio_pago, tipo=Pago.Tipo.SENA)
    reserva.monto_pagado += monto
    if reserva.estado == Reserva.Estado.PENDIENTE_SENA:
        reserva.estado = Reserva.Estado.CONFIRMADO
    reserva.save()
    return reserva


@transaction.atomic
def registrar_pago_saldo(reserva, monto, medio_pago):
    Pago.objects.create(reserva=reserva, monto=monto, medio_pago=medio_pago, tipo=Pago.Tipo.SALDO)
    reserva.monto_pagado += monto
    reserva.save()
    return reserva


@transaction.atomic
def reprogramar_reserva(reserva, *, nueva_fecha, nuevo_turno_id):
    """Mueve la reserva a otra fecha/turno. Libera el cupo viejo y valida el nuevo."""
    _validar_fecha_futura(nueva_fecha)
    turno = Turno.objects.filter(pk=nuevo_turno_id, activo=True).first()
    if not turno:
        raise ReservaError('turno_not_found')
    if not turno.aplica_en(nueva_fecha):
        raise ReservaError('turno_no_aplica_ese_dia')

    from apps.turnero.services import dia_habilitado, turnos_bloqueados
    if not dia_habilitado(nueva_fecha):
        raise ReservaError('dia_no_habilitado')
    bloqueados_ids, dia_completo = turnos_bloqueados(reserva.circuito, nueva_fecha)
    if dia_completo or turno.id in bloqueados_ids:
        raise ReservaError('turno_bloqueado')

    # Serializa el cupo del nuevo slot (anti-sobreventa al reprogramar).
    _lock_slot(reserva.circuito_id, turno.id, nueva_fecha)

    # Al cambiar fecha/turno, clean() valida el cupo del nuevo slot (el viejo queda libre solo).
    reserva.fecha = nueva_fecha
    reserva.turno = turno
    try:
        reserva.full_clean(exclude=None)
    except ValidationError as e:
        raise ReservaError('sin_cupo: ' + '; '.join(e.messages))
    reserva.save()
    return reserva


def marcar_asistio(reserva):
    """Cierre del día: el cliente asistió. Pasa la reserva a completado (habilita la encuesta)."""
    reserva.estado = Reserva.Estado.COMPLETADO
    reserva.save(update_fields=['estado', 'updated_at'])
    return reserva


def marcar_no_show(reserva):
    """Cierre del día: el cliente no vino. La seña ya pagada queda retenida (no se reembolsa)."""
    reserva.estado = Reserva.Estado.NO_SHOW
    nota = 'No-show: la seña abonada queda retenida.'
    reserva.notas = f'{reserva.notas}\n{nota}'.strip()
    reserva.save(update_fields=['estado', 'notas', 'updated_at'])
    return reserva


def evaluar_reembolso_sena(reserva, cuando=None):
    """
    Según la política del negocio, indica si al cancelar corresponde reembolsar la seña.
    Reembolsa si se cancela con al menos `horas_cancelacion_con_reembolso` de anticipación
    respecto del inicio del turno.
    """
    from datetime import datetime

    cuando = cuando or timezone.now()
    config = ConfiguracionNegocio.get_solo()
    inicio_turno = timezone.make_aware(datetime.combine(reserva.fecha, reserva.turno.hora_inicio))
    horas_hasta_turno = (inicio_turno - cuando).total_seconds() / 3600
    return horas_hasta_turno >= config.horas_cancelacion_con_reembolso


def cancelar_reserva(reserva, motivo=''):
    """
    Cancela la reserva, libera el cupo y aplica la política de seña:
    si la cancelación es tardía, la seña queda retenida.
    """
    reembolsa = reserva.monto_pagado > 0 and evaluar_reembolso_sena(reserva)
    reserva.estado = Reserva.Estado.CANCELADO
    partes = [reserva.notas]
    if motivo:
        partes.append(f'Cancelado: {motivo}')
    if reserva.monto_pagado > 0:
        if reembolsa:
            partes.append('Cancelación en término: corresponde reembolsar la seña.')
        else:
            partes.append('Cancelación tardía: la seña queda retenida.')
    reserva.notas = '\n'.join(p for p in partes if p).strip()
    reserva.sena_reembolsable = reembolsa
    reserva.save()
    notificar_evento.delay(
        'Reserva cancelada',
        f'{reserva.contacto.nombre} ({reserva.contacto.telefono}) — {reserva.circuito.nombre} — '
        f'{reserva.fecha} ({reserva.turno.nombre}). Motivo: {motivo or "no especificado"}.',
    )
    return reserva


def liberar_reservas_vencidas():
    """Cancela reservas pendientes de seña cuyo plazo de pago venció. Devuelve la lista liberada."""
    vencidas = Reserva.objects.filter(
        estado=Reserva.Estado.PENDIENTE_SENA,
        vencimiento_sena__lt=timezone.now(),
    )
    liberadas = list(vencidas)
    vencidas.update(estado=Reserva.Estado.CANCELADO)
    return liberadas
