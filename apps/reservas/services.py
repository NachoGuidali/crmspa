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


# Ventana del dedup heurístico de reservas del bot (cuando n8n no manda idempotency_key).
VENTANA_DEDUP_BOT_MINUTOS = 5


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
    """Red de contención para cuando n8n reintenta POST /reservas/bot/ (timeout, retry) sin
    mandar `idempotency_key`: si ya hay una reserva del bot para el mismo
    contacto+circuito+turno+fecha en una ventana corta, devolvemos esa en vez de duplicarla.
    Necesario sobre todo en modo por-circuito, donde el lock de cupo no evita el duplicado
    (dos reservas del mismo bot sí caben en el mismo slot).

    Es una heurística: solo cubre reintentos dentro de la ventana. La garantía real la da
    `idempotency_key` (unique en la DB), que no caduca."""
    ventana = timezone.now() - timedelta(minutes=VENTANA_DEDUP_BOT_MINUTOS)
    return (
        # `ocupando_cupo()` y no `estado__in=...`: si el hold anterior ya venció, el cliente
        # que reintenta necesita una reserva nueva, no que le devolvamos una muerta.
        Reserva.objects.ocupando_cupo()
        .filter(
            contacto__telefono=telefono, circuito_id=circuito_id, turno_id=turno_id, fecha=fecha,
            origen=Reserva.Origen.WHATSAPP_BOT, created_at__gte=ventana,
        )
        .order_by('-created_at').first()
    )


@transaction.atomic
def crear_reserva_bot(*, telefono, nombre_contacto, circuito_id, turno_id, fecha,
                      cantidad_personas=1, medio_pago='', resumen='',
                      comprobante=None, link_pago='', extras=None, idempotency_key=''):
    """Crea una reserva desde el bot de WhatsApp: valida cupo (estructurado) y setea el estado
    según el medio de pago.
      - transferencia → pendiente_aprobacion (el staff verifica el comprobante)
      - mercado_pago  → pendiente_pago (se confirma solo cuando MP avisa)

    Idempotente: si n8n manda `idempotency_key` y ya existe una reserva con esa clave,
    devuelve la que ya está creada sin tocar nada.
    """
    telefono_norm = normalize_ar_phone(telefono)
    key = (idempotency_key or '').strip() or None

    if key:
        existente = Reserva.objects.filter(idempotency_key=key).first()
        if existente is not None:
            return existente

    # El lock del slot se toma ACÁ, antes de buscar duplicados, y no solo dentro de
    # crear_reserva: si no, dos POST idénticos concurrentes leen los dos "no hay duplicado"
    # (READ COMMITTED, ninguno ve la fila del otro todavía) y recién después se serializan
    # para el cupo → terminan creando dos reservas. Con el lock adelantado, el segundo entra
    # cuando el primero ya commiteó y lo encuentra. Es reentrante: crear_reserva vuelve a
    # pedir el mismo lock dentro de la misma transacción sin bloquearse.
    _lock_slot(circuito_id, turno_id, fecha)

    if key:
        # Relectura con el lock tomado: el POST gemelo pudo crear la reserva mientras esperábamos.
        existente = Reserva.objects.filter(idempotency_key=key).first()
        if existente is not None:
            return existente

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
    reserva.idempotency_key = key
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


def _revalidar_cupo_si_el_hold_vencio(reserva):
    """Antes de confirmar un hold vencido, chequea que el turno siga libre.

    Como el cupo se libera en el instante del vencimiento, entre que el hold venció y llega el
    pago alguien pudo haber tomado el turno. Confirmar a ciegas sería sobreventa: dos reservas
    activas en un slot exclusivo. Si el hold sigue vigente no hay nada que revisar."""
    vencido = (
        reserva.estado in Reserva.ESTADOS_HOLD_TEMPORAL
        and reserva.vencimiento_sena is not None
        and reserva.vencimiento_sena < timezone.now()
    )
    if not vencido:
        return
    try:
        reserva.full_clean(exclude=['idempotency_key'])
    except ValidationError as e:
        raise ReservaError(
            'hold_vencido_y_turno_tomado: venció el plazo de pago y el turno ya no está '
            'disponible. ' + '; '.join(e.messages)
        )


@transaction.atomic
def confirmar_reserva(reserva):
    """Confirma la reserva (Mercado Pago acreditó, o el staff aprobó el comprobante de
    transferencia) y le avisa al bot para que mande la confirmación final al cliente.

    Acá se acredita la seña, así que es el momento en que arranca la ventana de reembolso."""
    _lock_slot(reserva.circuito_id, reserva.turno_id, reserva.fecha)
    _revalidar_cupo_si_el_hold_vencio(reserva)
    reserva.estado = Reserva.Estado.CONFIRMADO
    campos = ['estado', 'updated_at']
    if reserva.sena_pagada_at is None:
        reserva.sena_pagada_at = timezone.now()
        campos.append('sena_pagada_at')
    reserva.save(update_fields=campos)
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
    _lock_slot(reserva.circuito_id, reserva.turno_id, reserva.fecha)
    _revalidar_cupo_si_el_hold_vencio(reserva)
    pago = Pago.objects.create(
        reserva=reserva, monto=monto, medio_pago=medio_pago, tipo=Pago.Tipo.SENA,
    )
    reserva.monto_pagado += monto
    # La ventana de reembolso se cuenta desde el pago de la seña. Si ya había una seña
    # registrada, mandan la primera: un segundo pago no reabre el plazo.
    if reserva.sena_pagada_at is None:
        reserva.sena_pagada_at = pago.fecha
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
    Política de reembolso del negocio: **la seña se reembolsa solo si la reserva se cancela
    dentro de las N horas posteriores al pago de la seña** (config
    `horas_reembolso_desde_pago`, default 24). Pasado ese plazo la seña queda retenida.

    Ojo: el plazo se cuenta desde el PAGO, no desde la fecha del turno. Una reserva pagada hace
    tres meses para un turno de mañana está fuera de plazo, y una pagada hace dos horas está en
    plazo aunque el turno sea pasado mañana.

    Sin seña acreditada (`sena_pagada_at` nulo) no hay nada que reembolsar → False.
    """
    if reserva.sena_pagada_at is None:
        return False

    cuando = cuando or timezone.now()
    config = ConfiguracionNegocio.get_solo()
    horas_desde_pago = (cuando - reserva.sena_pagada_at).total_seconds() / 3600
    return 0 <= horas_desde_pago <= config.horas_reembolso_desde_pago


def cancelar_reserva(reserva, motivo=''):
    """
    Cancela la reserva, libera el cupo y deja asentada la política de seña:
    reembolsable solo si se cancela dentro de la ventana posterior al pago.
    """
    config = ConfiguracionNegocio.get_solo()
    reembolsa = evaluar_reembolso_sena(reserva)
    reserva.estado = Reserva.Estado.CANCELADO
    partes = [reserva.notas]
    if motivo:
        partes.append(f'Cancelado: {motivo}')
    if reserva.sena_pagada_at is not None:
        pagada = timezone.localtime(reserva.sena_pagada_at).strftime('%d/%m/%Y %H:%M')
        if reembolsa:
            partes.append(
                f'Cancelación dentro de las {config.horas_reembolso_desde_pago} hs del pago '
                f'(seña pagada el {pagada}): corresponde reembolsar la seña.'
            )
        else:
            horas = (timezone.now() - reserva.sena_pagada_at).total_seconds() / 3600
            partes.append(
                f'Cancelación fuera de plazo: pasaron {horas:.0f} hs desde el pago de la seña '
                f'({pagada}) y la política son {config.horas_reembolso_desde_pago} hs. '
                f'La seña queda retenida.'
            )
    else:
        partes.append('Sin seña acreditada al momento de cancelar: no hay reembolso que hacer.')
    reserva.notas = '\n'.join(p for p in partes if p).strip()
    reserva.sena_reembolsable = reembolsa
    reserva.save()
    if reserva.sena_pagada_at is None:
        destino_sena = 'No había seña acreditada.'
    elif reembolsa:
        destino_sena = 'CORRESPONDE REEMBOLSAR la seña (canceló dentro del plazo).'
    else:
        destino_sena = 'La seña queda RETENIDA (canceló fuera del plazo).'
    notificar_evento.delay(
        'Reserva cancelada',
        f'{reserva.contacto.nombre} ({reserva.contacto.telefono}) — {reserva.circuito.nombre} — '
        f'{reserva.fecha} ({reserva.turno.nombre}). Motivo: {motivo or "no especificado"}. '
        f'{destino_sena}',
    )
    return reserva


def liberar_reservas_vencidas():
    """Cancela los holds temporales cuyo plazo de pago venció. Devuelve la lista liberada.

    Cubre `pendiente_sena` **y `pendiente_pago`**: los dos son holds que retienen el cupo
    mientras el cliente paga. La versión anterior miraba solo `pendiente_sena`, así que una
    reserva del bot con link de Mercado Pago que nunca se pagaba **bloqueaba el turno para
    siempre**.

    `pendiente_aprobacion` queda afuera a propósito: ahí el cliente ya transfirió y subió el
    comprobante; cancelarle la reserva por un plazo automático sería quedarse con la plata y
    el turno. Eso lo resuelve una persona.

    Ojo: el cupo ya se considera libre desde el instante del vencimiento
    (`Reserva.objects.ocupando_cupo()`), corra o no esta tarea. Esto es la limpieza que deja
    el estado prolijo, no lo que destraba el turno.
    """
    vencidas = Reserva.objects.holds_vencidos()
    liberadas = list(vencidas.select_related('contacto', 'circuito', 'turno'))
    for reserva in liberadas:
        nota = (f'Cupo liberado automáticamente: venció el plazo para pagar la seña '
                f'({timezone.localtime(reserva.vencimiento_sena):%d/%m/%Y %H:%M}).')
        reserva.notas = f'{reserva.notas}\n{nota}'.strip()
        reserva.estado = Reserva.Estado.CANCELADO
        reserva.save(update_fields=['estado', 'notas', 'updated_at'])
    return liberadas
