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


def _ultimo_comprobante_del_cliente(telefono, desde_hace_horas=6):
    """La última imagen que mandó ese cliente, para usarla de comprobante.

    El bot manda el comprobante en base64, pero lo saca del payload crudo de Evolution
    (`data.message.base64`), que solo llega si Evolution está configurado para incluirlo — y
    con Meta ese campo directamente no existe. Cuando no viene, la reserva quedaba sin
    comprobante y había que ir a buscarlo a la conversación.

    El CRM ya descarga y guarda toda imagen entrante por su cuenta (`download_and_save_media`),
    así que la tenemos igual: la enganchamos desde acá y el staff la ve en la ficha.
    """
    import os

    from django.conf import settings
    from django.core.files.base import ContentFile

    from apps.whatsapp.models import Mensaje

    mensaje = (
        Mensaje.objects
        .filter(
            conversacion__telefono=telefono,
            direccion=Mensaje.Direccion.ENTRANTE,
            tipo=Mensaje.Tipo.IMAGEN,
            timestamp__gte=timezone.now() - timedelta(hours=desde_hace_horas),
        )
        .exclude(media_url='')
        .order_by('-timestamp')
        .first()
    )
    if mensaje is None:
        return None

    # media_url es "/media/uploads/conv_N/archivo.jpg" → la ruta real en disco.
    rel = mensaje.media_url.replace(settings.MEDIA_URL, '', 1).lstrip('/')
    ruta = os.path.join(settings.MEDIA_ROOT, rel)
    if not os.path.exists(ruta):
        return None
    with open(ruta, 'rb') as f:
        return ContentFile(f.read(), name=os.path.basename(ruta))


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
        if comprobante is None:
            # El bot no lo mandó: buscamos la última imagen que mandó el cliente. Sin esto la
            # reserva llega a "pendiente de aprobación" sin nada que aprobar.
            comprobante = _ultimo_comprobante_del_cliente(telefono_norm)
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


def _reactivar_bot(reserva):
    """Vuelve a prender el bot cuando la reserva queda confirmada.

    Al crear la reserva el bot se apaga y queda esperando que alguien verifique la
    transferencia. Una vez confirmada ya no hay nada que esperar: si el cliente escribe
    ("¿cómo llego?", "¿puedo llevar mascota?", o quiere reservar de nuevo), no tiene sentido
    que nadie le conteste hasta que un humano lea el inbox.

    NO se reactiva si la conversación estaba en atención humana de verdad — una queja, un
    pedido de cancelación, alguien que pidió hablar con una persona. Ahí hay alguien
    ocupándose y prender el bot sería pisarle la conversación.
    """
    from apps.whatsapp.models import Conversacion

    conv = Conversacion.objects.filter(telefono=reserva.contacto.telefono).first()
    if conv is None:
        return
    if conv.estado == Conversacion.Estado.REQUIERE_ATENCION_HUMANA:
        return

    estado = dict(conv.estado_bot or {})
    # `reserva_creada` es lo que mantiene el bot apagado: el CRM lo vuelve a apagar en cada
    # PATCH mientras siga en true. Sin limpiarlo, prender `bot_activo` no dura nada.
    estado['reserva_creada'] = False
    estado['estado_flujo'] = 'menu'
    # Se borra lo de ESTA reserva para que un pedido nuevo no herede fecha, turno ni menú
    # de la anterior. Los datos de contacto se conservan: ya nos los dio, no se los pedimos
    # de nuevo.
    for campo in ('fecha_solicitada', 'personas', 'tipo_propuesta', 'nivel', 'menu_especial',
                  'menu_especial_cantidad', 'extras_pedidos', 'medio_pago', 'horario_confirmado',
                  'turno_nombre', 'turno_horario', 'dias_ofrecidos', 'fallos_consecutivos'):
        estado.pop(campo, None)

    conv.estado_bot = estado
    conv.bot_activo = True
    conv.save(update_fields=['estado_bot', 'bot_activo'])


def _avisar_reserva_confirmada(reserva):
    """Todo lo que pasa cuando una reserva queda confirmada, venga del camino que venga.

    Vive en una sola función porque hay tres puertas de entrada (staff aprueba comprobante,
    Mercado Pago acredita, alguien cobra la seña a mano) y las tres tienen que avisar igual.

    Son tres avisos distintos con destinatarios distintos:
      1. Al CLIENTE, por WhatsApp: la confirmación con los datos y cómo llegar.
      2. A n8n: por si el bot tiene que hacer algo extra con el evento (opcional).
      3. Al DUEÑO, por mail.
    """
    from apps.whatsapp.tasks import enviar_confirmacion_reserva, notificar_reserva_aprobada

    detalle = (
        f'{reserva.contacto.nombre} ({reserva.contacto.telefono}) — {reserva.circuito.nombre} — '
        f'{reserva.fecha} ({reserva.turno.nombre}).'
    )

    # Antes de avisar: el bot vuelve a estar disponible para este cliente.
    _reactivar_bot(reserva)

    def _disparar():
        enviar_confirmacion_reserva.delay(reserva.id)
        notificar_reserva_aprobada.delay(reserva.id)
        notificar_evento.delay('Reserva confirmada', detalle)

    # `on_commit` y no `.delay()` suelto: quien confirma está dentro de una transacción, y un
    # worker de Celery es otro proceso — si arranca antes del commit, lee la reserva todavía
    # sin confirmar y le manda al cliente un mensaje con datos viejos, o no la encuentra.
    # Fuera de transacción, `on_commit` ejecuta al toque, así que sirve igual en los dos casos.
    transaction.on_commit(_disparar)


def _registrar_sena_acreditada(reserva, monto=None):
    """Deja asentado el `Pago` de la seña que se acaba de acreditar.

    Sin esto, confirmar por transferencia o Mercado Pago dejaba la reserva en `monto_pagado=0`
    y sin ningún `Pago`. Consecuencias: al cliente le figuraba el total como saldo pendiente, y
    la caja del día y los ingresos del dashboard —que suman `Pago`— no contaban esas señas.

    El monto es `monto_sena`, que es lo que el CRM le pidió al cliente. El medio sale del que
    eligió al reservar.

    Idempotente: si ya hay una seña registrada no crea otra, así un reintento no duplica plata.
    """
    if reserva.pagos.filter(tipo=Pago.Tipo.SENA).exists():
        return None

    monto = monto if monto is not None else (reserva.monto_sena or Decimal('0'))
    if monto <= 0:
        return None

    pago = Pago.objects.create(
        reserva=reserva,
        monto=monto,
        medio_pago=reserva.medio_pago or Reserva.MedioPago.OTRO,
        tipo=Pago.Tipo.SENA,
    )
    reserva.monto_pagado = (reserva.monto_pagado or Decimal('0')) + monto
    return pago


@transaction.atomic
def confirmar_reserva(reserva, monto_sena=None):
    """Confirma la reserva: Mercado Pago acreditó, o el staff aprobó el comprobante de
    transferencia.

    Acá se acredita la seña: se registra el pago y arranca la ventana de reembolso.
    `monto_sena` permite pasar el monto real si difiere del esperado; por defecto usa el que
    la reserva tiene calculado.
    """
    if reserva.estado == Reserva.Estado.CONFIRMADO:
        # Ya estaba confirmada (doble clic en el botón, reintento de Mercado Pago): no la
        # volvemos a confirmar, ni registramos la seña dos veces, ni le mandamos al cliente
        # un segundo "reserva confirmada".
        return reserva

    _lock_slot(reserva.circuito_id, reserva.turno_id, reserva.fecha)
    _revalidar_cupo_si_el_hold_vencio(reserva)
    reserva.estado = Reserva.Estado.CONFIRMADO
    campos = ['estado', 'monto_pagado', 'updated_at']
    if reserva.sena_pagada_at is None:
        reserva.sena_pagada_at = timezone.now()
        campos.append('sena_pagada_at')
    _registrar_sena_acreditada(reserva, monto_sena)
    reserva.save(update_fields=campos)
    _avisar_reserva_confirmada(reserva)
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
    # Cobrar la seña también confirma, así que también le avisa al cliente. Antes este camino
    # no mandaba nada: quien pagaba en efectivo o por transferencia cargada a mano se quedaba
    # sin la confirmación.
    recien_confirmada = reserva.estado == Reserva.Estado.PENDIENTE_SENA
    if recien_confirmada:
        reserva.estado = Reserva.Estado.CONFIRMADO
    reserva.save()
    if recien_confirmada:
        _avisar_reserva_confirmada(reserva)
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
