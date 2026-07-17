from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.circuitos.models import Circuito
from apps.configuracion.models import ConfiguracionNegocio
from apps.contactos.models import Contacto
from apps.turnero.models import Turno
from utils.phone import normalize_ar_phone

from .models import Pago, Reserva


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


@transaction.atomic
def crear_reserva(
    *, telefono, nombre_contacto, circuito_id, turno_id, fecha,
    cantidad_personas=1, acompanantes=None, notas='',
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
    monto_sena = circuito.monto_sena_para(fecha, cantidad_personas)

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
