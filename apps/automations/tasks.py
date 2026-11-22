import logging
from datetime import datetime, time, timedelta

from celery import shared_task
from django.db.models import Sum
from django.utils import timezone

from apps.reservas.models import Reserva
from apps.reservas.services import liberar_reservas_vencidas
from apps.whatsapp.services import enviar_automatico

from .models import Automatizacion, AutomatizacionLog

logger = logging.getLogger('apps.automations')

# Cuántas veces se reintenta el seguimiento cuando el envío falla. Sin tope, la automatización
# vuelve a intentarlo en cada pasada (cada 15 minutos) mientras la charla siga en la ventana.
MAX_INTENTOS_SEGUIMIENTO = 2

# Automatizaciones que le escriben AL CLIENTE. Todas respetan el horario de atención: un
# WhatsApp del spa a las 2 de la mañana molesta y queda mal. `alerta_cupo` queda afuera
# porque es un aviso interno al equipo, y `reclamo_sena` también: la seña vence sola y el
# mensaje es la respuesta a algo que la persona acaba de empezar, así que llega cuando tiene
# que llegar.
AUTOMATIZACIONES_AL_CLIENTE = {
    Automatizacion.Tipo.RECORDATORIO_24H,
    Automatizacion.Tipo.RECORDATORIO_2H,
    Automatizacion.Tipo.ENCUESTA_SATISFACCION,
    Automatizacion.Tipo.REACTIVACION_INACTIVOS,
    Automatizacion.Tipo.LISTA_ESPERA,
    Automatizacion.Tipo.CUMPLEANOS,
    Automatizacion.Tipo.SEGUIMIENTO_CHARLA,
    Automatizacion.Tipo.SEGUIMIENTO_CHARLA_2,
}

# Si no hay horario cargado en Configuración, `esta_en_horario_atencion()` da 24 horas. Para
# el bot eso está bien (contesta cuando le escriben), pero para un mensaje que arrancamos
# nosotros no: sin horario configurado nos quedamos en esta franja segura.
HORARIO_SEGURO = (time(9, 0), time(21, 0))


def _puede_escribirle_al_cliente(cuando=None):
    """Horario de atención, y si no hay ninguno cargado, una franja razonable."""
    from apps.configuracion.models import ConfiguracionNegocio

    config = ConfiguracionNegocio.get_solo()
    cuando = cuando or timezone.localtime()
    if config.horario_atencion_desde and config.horario_atencion_hasta:
        return config.esta_en_horario_atencion(cuando)
    if cuando.weekday() not in (config.dias_laborables or list(range(7))):
        return False
    desde, hasta = HORARIO_SEGURO
    return desde <= cuando.time() <= hasta


# Categoría de cada automatización → qué preferencia del contacto respeta.
CATEGORIA = {
    Automatizacion.Tipo.RECORDATORIO_24H: 'recordatorio',
    Automatizacion.Tipo.RECORDATORIO_2H: 'recordatorio',
    Automatizacion.Tipo.RECLAMO_SENA: 'recordatorio',
    Automatizacion.Tipo.ENCUESTA_SATISFACCION: 'recordatorio',
    Automatizacion.Tipo.LISTA_ESPERA: 'recordatorio',
    Automatizacion.Tipo.REACTIVACION_INACTIVOS: 'promo',
    Automatizacion.Tipo.CUMPLEANOS: 'promo',
    Automatizacion.Tipo.SEGUIMIENTO_CHARLA: 'recordatorio',
}


def _contacto_acepta(contacto, automatizacion):
    """True si el contacto acepta recibir este tipo de mensaje (según su preferencia)."""
    categoria = CATEGORIA.get(automatizacion.tipo)
    if categoria == 'promo':
        return contacto.recibir_promociones
    if categoria == 'recordatorio':
        return contacto.recibir_recordatorios
    return True


def _log(automatizacion, resultado, detalle='', contacto=None, reserva=None):
    AutomatizacionLog.objects.create(
        automatizacion=automatizacion, resultado=resultado, detalle=detalle,
        contacto=contacto, reserva=reserva,
    )


def _ya_enviado_a_reserva(automatizacion, reserva):
    return AutomatizacionLog.objects.filter(
        automatizacion=automatizacion, reserva=reserva, resultado=AutomatizacionLog.Resultado.EXITOSO,
    ).exists()


def _ya_enviado_a_contacto_este_anio(automatizacion, contacto):
    return AutomatizacionLog.objects.filter(
        automatizacion=automatizacion, contacto=contacto,
        resultado=AutomatizacionLog.Resultado.EXITOSO,
        ejecutado_at__year=timezone.localdate().year,
    ).exists()


def _enviar_a_reserva(automatizacion, reserva, contexto_extra=None):
    if not _contacto_acepta(reserva.contacto, automatizacion):
        _log(automatizacion, AutomatizacionLog.Resultado.OMITIDO, 'Contacto no acepta este tipo de mensaje',
             contacto=reserva.contacto, reserva=reserva)
        return
    contexto = {
        'nombre': reserva.contacto.nombre,
        'circuito': reserva.circuito.nombre,
        'fecha': reserva.fecha.strftime('%d/%m/%Y'),
        'turno': reserva.turno.nombre,
        'monto_sena': str(reserva.monto_sena),
        **(contexto_extra or {}),
    }
    plantilla = automatizacion.plantilla
    mensaje = plantilla.render(contexto) if plantilla else None
    if not mensaje:
        _log(automatizacion, AutomatizacionLog.Resultado.OMITIDO, 'Sin plantilla configurada',
             contacto=reserva.contacto, reserva=reserva)
        return
    try:
        enviar_automatico(telefono=reserva.contacto.telefono, plantilla=plantilla, contexto=contexto)
        _log(automatizacion, AutomatizacionLog.Resultado.EXITOSO, mensaje,
             contacto=reserva.contacto, reserva=reserva)
    except Exception as exc:
        logger.exception('Error enviando automatización %s a reserva %s', automatizacion.tipo, reserva.id)
        _log(automatizacion, AutomatizacionLog.Resultado.ERROR, str(exc),
             contacto=reserva.contacto, reserva=reserva)


def _reservas_proximas(dias_adelante=2):
    hoy = timezone.localdate()
    return (
        Reserva.objects.filter(
            estado__in=[Reserva.Estado.CONFIRMADO, Reserva.Estado.COMPLETADO],
            fecha__gte=hoy, fecha__lte=hoy + timedelta(days=dias_adelante),
        )
        .select_related('turno', 'contacto', 'circuito')
    )


def _horas_hasta_turno(reserva):
    turno_dt = timezone.make_aware(datetime.combine(reserva.fecha, reserva.turno.hora_inicio))
    return (turno_dt - timezone.now()).total_seconds() / 3600


def _recordatorio(automatizacion, horas_default):
    horas_antes = automatizacion.parametros.get('horas_antes', horas_default)
    margen = automatizacion.parametros.get('margen_horas', 0.5)
    for reserva in _reservas_proximas():
        if _ya_enviado_a_reserva(automatizacion, reserva):
            continue
        restantes = _horas_hasta_turno(reserva)
        if horas_antes - margen <= restantes <= horas_antes + margen:
            _enviar_a_reserva(automatizacion, reserva)


def recordatorio_24h(automatizacion):
    _recordatorio(automatizacion, horas_default=24)


def recordatorio_2h(automatizacion):
    _recordatorio(automatizacion, horas_default=2)


def reclamo_sena(automatizacion):
    horas_aviso = automatizacion.parametros.get('horas_aviso', 1)
    ahora = timezone.now()
    proximas_a_vencer = Reserva.objects.filter(
        estado=Reserva.Estado.PENDIENTE_SENA,
        vencimiento_sena__gte=ahora,
        vencimiento_sena__lte=ahora + timedelta(hours=horas_aviso),
    ).select_related('turno', 'contacto', 'circuito')
    for reserva in proximas_a_vencer:
        if not _ya_enviado_a_reserva(automatizacion, reserva):
            _enviar_a_reserva(automatizacion, reserva)

    # La liberación del cupo NO se hace acá: es integridad de datos, no un mensaje.
    # Corre siempre en `ejecutar_automatizaciones`, esté esta automatización activa o no.


def encuesta_satisfaccion(automatizacion):
    dias_despues = automatizacion.parametros.get('dias_despues', 1)
    fecha_objetivo = timezone.localdate() - timedelta(days=dias_despues)
    reservas = Reserva.objects.filter(
        estado=Reserva.Estado.COMPLETADO, fecha=fecha_objetivo,
    ).select_related('turno', 'contacto', 'circuito')
    for reserva in reservas:
        if not _ya_enviado_a_reserva(automatizacion, reserva):
            _enviar_a_reserva(automatizacion, reserva)


def reactivacion_inactivos(automatizacion):
    from django.db.models import Max

    from apps.contactos.models import Contacto

    dias_inactividad = automatizacion.parametros.get('dias_inactividad', 60)
    limite = timezone.localdate() - timedelta(days=dias_inactividad)

    candidatos = (
        Contacto.objects.annotate(ultima_reserva=Max('reservas__fecha'))
        .filter(ultima_reserva__isnull=False, ultima_reserva__lt=limite)
    )
    for contacto in candidatos:
        if not _contacto_acepta(contacto, automatizacion):
            continue
        ya_reactivado = AutomatizacionLog.objects.filter(
            automatizacion=automatizacion, contacto=contacto,
            resultado=AutomatizacionLog.Resultado.EXITOSO,
            ejecutado_at__gte=timezone.now() - timedelta(days=dias_inactividad),
        ).exists()
        if ya_reactivado:
            continue
        plantilla = automatizacion.plantilla
        ctx = {'nombre': contacto.nombre}
        mensaje = plantilla.render(ctx) if plantilla else None
        if not mensaje:
            _log(automatizacion, AutomatizacionLog.Resultado.OMITIDO, 'Sin plantilla configurada', contacto=contacto)
            continue
        try:
            enviar_automatico(telefono=contacto.telefono, plantilla=plantilla, contexto=ctx)
            _log(automatizacion, AutomatizacionLog.Resultado.EXITOSO, mensaje, contacto=contacto)
        except Exception as exc:
            logger.exception('Error en reactivacion_inactivos para contacto %s', contacto.id)
            _log(automatizacion, AutomatizacionLog.Resultado.ERROR, str(exc), contacto=contacto)


def alerta_cupo(automatizacion):
    """Deja constancia en el log cuando un circuito llega a cupo completo o queda 1 lugar.
    (Sin canal de notificación interna todavía — se agrega junto con la UI del inbox/kanban.)"""
    hoy = timezone.localdate()
    reservas = (
        Reserva.objects.ocupando_cupo()
        .filter(fecha__gte=hoy, fecha__lte=hoy + timedelta(days=7))
        .values('circuito', 'fecha', 'turno')
        .annotate(ocupacion=Sum('cantidad_personas'))
        .select_related()
    )
    from apps.circuitos.models import Circuito
    from apps.turnero.models import Turno

    for r in reservas:
        circuito = Circuito.objects.get(pk=r['circuito'])
        turno = Turno.objects.get(pk=r['turno'])
        restante = circuito.capacidad_maxima - r['ocupacion']
        if restante in (0, 1):
            detalle = f'{circuito.nombre} {r["fecha"]} {turno.nombre}: quedan {restante} lugar(es).'
            ya_alertado = AutomatizacionLog.objects.filter(
                automatizacion=automatizacion, detalle=detalle,
            ).exists()
            if not ya_alertado:
                _log(automatizacion, AutomatizacionLog.Resultado.EXITOSO, detalle)


def lista_espera(automatizacion):
    """Ofrece un lugar liberado al PRIMERO de la fila (no a todos a la vez) y le da un
    hold temporal antes de pasar al siguiente, para que no se vuelva a sobrevender."""
    from collections import defaultdict

    from apps.reservas.models import ListaEspera
    from apps.turnero.services import disponibilidad_circuito

    hold_horas = automatizacion.parametros.get('hold_horas', 4)
    ahora = timezone.now()

    esperas = list(
        ListaEspera.objects.select_related('circuito', 'contacto', 'turno').order_by('created_at')
    )
    por_slot = defaultdict(list)
    for e in esperas:
        por_slot[(e.circuito_id, e.fecha_deseada, e.turno_id)].append(e)

    for lista in por_slot.values():
        # Si hay una oferta vigente (hold sin vencer), este slot está reservado para esa persona.
        hay_oferta_vigente = any(
            e.ofrecido_at and (ahora - e.ofrecido_at) < timedelta(hours=hold_horas)
            for e in lista
        )
        if hay_oferta_vigente:
            continue

        # El siguiente candidato: el primero que todavía no recibió una oferta.
        siguiente = next((e for e in lista if e.ofrecido_at is None), None)
        if siguiente is None:
            continue
        if not _contacto_acepta(siguiente.contacto, automatizacion):
            continue

        disponibilidad = disponibilidad_circuito(siguiente.circuito, siguiente.fecha_deseada)
        hay_lugar = any(
            t['cupo_disponible'] > 0 and (siguiente.turno_id is None or t['turno_id'] == siguiente.turno_id)
            for t in disponibilidad['turnos']
        )
        if not hay_lugar:
            continue

        plantilla = automatizacion.plantilla
        ctx = {
            'nombre': siguiente.contacto.nombre, 'circuito': siguiente.circuito.nombre,
            'fecha': siguiente.fecha_deseada.strftime('%d/%m/%Y'),
        }
        mensaje = plantilla.render(ctx) if plantilla else None
        if not mensaje:
            _log(automatizacion, AutomatizacionLog.Resultado.OMITIDO, 'Sin plantilla configurada', contacto=siguiente.contacto)
            continue
        try:
            enviar_automatico(telefono=siguiente.contacto.telefono, plantilla=plantilla, contexto=ctx)
            siguiente.notificado = True
            siguiente.ofrecido_at = ahora
            siguiente.save(update_fields=['notificado', 'ofrecido_at'])
            _log(automatizacion, AutomatizacionLog.Resultado.EXITOSO, mensaje, contacto=siguiente.contacto)
        except Exception as exc:
            logger.exception('Error notificando lista de espera %s', siguiente.id)
            _log(automatizacion, AutomatizacionLog.Resultado.ERROR, str(exc), contacto=siguiente.contacto)


def cumpleanos(automatizacion):
    from apps.contactos.models import Contacto

    hoy = timezone.localdate()
    contactos = Contacto.objects.filter(
        fecha_nacimiento__month=hoy.month, fecha_nacimiento__day=hoy.day,
    )
    for contacto in contactos:
        if not _contacto_acepta(contacto, automatizacion):
            continue
        if _ya_enviado_a_contacto_este_anio(automatizacion, contacto):
            continue
        plantilla = automatizacion.plantilla
        ctx = {'nombre': contacto.nombre}
        mensaje = plantilla.render(ctx) if plantilla else None
        if not mensaje:
            _log(automatizacion, AutomatizacionLog.Resultado.OMITIDO, 'Sin plantilla configurada', contacto=contacto)
            continue
        try:
            enviar_automatico(telefono=contacto.telefono, plantilla=plantilla, contexto=ctx)
            _log(automatizacion, AutomatizacionLog.Resultado.EXITOSO, mensaje, contacto=contacto)
        except Exception as exc:
            logger.exception('Error enviando cumpleanos a contacto %s', contacto.id)
            _log(automatizacion, AutomatizacionLog.Resultado.ERROR, str(exc), contacto=contacto)


# Qué decirle según dónde quedó la charla. Es una oración entera y no una palabra suelta,
# porque el caso más común no es una reserva a medio armar: es alguien que preguntó algo,
# recibió la respuesta y no contestó más.
PENDIENTE_POR_PASO = {
    # Preguntó o saludó, pero nunca arrancó una reserva.
    'nuevo': '¿Te quedó alguna duda? Si querés te paso info de las experiencias, precios o te ayudo a reservar.',
    'menu': '¿Te quedó alguna duda? Si querés te paso info de las experiencias, precios o te ayudo a reservar.',
    # Reserva a medio armar: se retoma por el dato que faltaba.
    'turno_personas': 'Quedamos por la mitad: me faltaba saber cuántas personas vienen y qué experiencia te interesa.',
    'turno_nivel': 'Quedamos por la mitad: me faltaba saber si preferís la versión Clásica o la Premium.',
    'turno_fecha': 'Quedamos por la mitad: me faltaba saber qué día estabas buscando.',
    'turno_fecha_elegir_turno': 'Quedamos por la mitad: me faltaba saber si preferís el turno de la mañana o el de la tarde.',
    'turno_confirmar_fecha': 'Quedamos por la mitad: me faltaba que me confirmes el día y el turno.',
    'turno_datos_nombre': 'Quedamos por la mitad: me faltaba tu nombre y apellido.',
    'turno_datos_telefono': 'Quedamos por la mitad: me faltaba tu teléfono de contacto.',
    'turno_datos_email': 'Quedamos por la mitad: me faltaba tu email.',
    'turno_datos_menu': 'Quedamos por la mitad: me faltaba saber si necesitás menú apto celíaco o vegetariano.',
    'turno_menu_especial_cantidad': 'Quedamos por la mitad: me faltaba saber para cuántas personas era el menú especial.',
    'turno_confirmar_resumen': 'Quedamos por la mitad: me faltaba que me confirmes la reserva.',
    'turno_pago': 'Quedamos por la mitad: me faltaba saber cómo vas a abonar la seña.',
    # turno_pago_comprobante queda afuera a propósito: de ese se encarga el reclamo de seña,
    # que además libera el cupo. Dos mensajes por lo mismo es acoso.
}


def seguimiento_charla(automatizacion):
    """Vuelve a escribirle a quien dejó la charla por la mitad.

    Alguien que preguntó precios y no contestó más es una reserva que se está por perder, y
    hoy nadie se entera. Se le escribe UNA vez, retomando el paso donde quedó.

    Condiciones para escribir, todas necesarias:
      - el último mensaje lo mandó el bot (si escribió el cliente, le toca responder al bot);
      - la charla sigue en manos del bot (no derivada a una persona ni archivada);
      - no hay reserva hecha todavía;
      - pasaron las horas configuradas, pero no muchísimas (nadie quiere un mensaje de una
        charla de hace tres semanas apenas se prende la automatización);
      - estamos en horario de atención.
    """
    from apps.configuracion.models import ConfiguracionNegocio
    from apps.whatsapp.models import Conversacion, Mensaje

    horas = float(automatizacion.parametros.get('horas_sin_respuesta', 4))
    ventana = float(automatizacion.parametros.get('ventana_horas', 48))
    # El segundo intento solo mira charlas a las que ya se les escribió una vez; el primero,
    # solo las que no. Si no, los dos le escribirían a la misma persona el mismo día.
    es_segundo = automatizacion.tipo == Automatizacion.Tipo.SEGUIMIENTO_CHARLA_2
    ahora = timezone.now()
    desde, hasta = ahora - timedelta(hours=ventana), ahora - timedelta(hours=horas)

    candidatas = (
        Conversacion.objects.filter(
            bot_activo=True, archivada=False,
            ultimo_mensaje_at__gte=desde, ultimo_mensaje_at__lte=hasta,
        )
        .exclude(estado=Conversacion.Estado.REQUIERE_ATENCION_HUMANA)
        .select_related('contacto')
    )
    hoy = timezone.localdate()
    for conv in candidatas:
        if conv.reserva_creada:
            continue
        # `reserva_creada` solo lo marca el bot cuando la reserva la hizo él. Una cargada a
        # mano por el equipo no lo marca, así que a esa persona se la perseguía como si fuera
        # un cliente perdido. Pasó el 19/11/2026: le preguntó al bot por su reserva del 20 y
        # le llegó "¿te quedó alguna duda? te paso info de las experiencias". Lo mismo con
        # quien recibe "tu reserva está confirmada" y no contesta nada, que es lo normal.
        # Se busca por TELÉFONO y no por el contacto vinculado a la charla: hay charlas sin
        # contacto (creadas por la API, o importadas) y ahí la reserva no se veía.
        if Reserva.objects.ocupando_cupo().filter(
                contacto__telefono=conv.telefono, fecha__gte=hoy).exists():
            continue
        paso = (conv.estado_bot or {}).get('estado_flujo') or 'nuevo'
        if paso not in PENDIENTE_POR_PASO:
            continue        # pasos que ya tienen su propio recordatorio (ej. el comprobante)

        ultimo = conv.mensajes.order_by('-timestamp').first()
        if ultimo is None or ultimo.direccion != Mensaje.Direccion.SALIENTE:
            continue        # si el último mensaje es del cliente, el que debe contestar es el bot

        contacto = conv.contacto
        # Una sola vez por charla: se mira si ya se escribió después del último mensaje.
        # Una sola vez por charla y por tipo: se mira si ya se escribió desde el último
        # mensaje. El segundo intento, además, necesita que el primero haya salido.
        def ya_escribio(tipo):
            if not contacto:
                return False
            return AutomatizacionLog.objects.filter(
                automatizacion__tipo=tipo, resultado=AutomatizacionLog.Resultado.EXITOSO,
                contacto=contacto, ejecutado_at__gte=conv.ultimo_mensaje_at,
            ).exists()

        if ya_escribio(automatizacion.tipo):
            continue
        # Un envío fallido no cuenta como escrito, así que sin este freno la automatización
        # lo reintentaba en CADA pasada (cada 15 minutos) hasta que la charla saliera de la
        # ventana de 48 hs: el 19/11/2026 a Marcela le quedaron cinco intentos seguidos en el
        # inbox. Se permiten dos intentos por si fue algo pasajero del proveedor, y listo.
        if contacto and AutomatizacionLog.objects.filter(
                automatizacion__tipo=automatizacion.tipo,
                resultado=AutomatizacionLog.Resultado.ERROR,
                contacto=contacto, ejecutado_at__gte=conv.ultimo_mensaje_at,
        ).count() >= MAX_INTENTOS_SEGUIMIENTO:
            continue
        primero_hecho = ya_escribio(Automatizacion.Tipo.SEGUIMIENTO_CHARLA)
        if es_segundo and not primero_hecho:
            continue        # todavía no le escribimos la primera vez
        if not es_segundo and primero_hecho:
            continue
        if contacto and not _contacto_acepta(contacto, automatizacion):
            continue

        plantilla = automatizacion.plantilla
        contexto = {
            'nombre': (conv.get_display_name() or '').split(' ')[0],
            'pendiente': PENDIENTE_POR_PASO[paso],
        }
        mensaje = plantilla.render(contexto) if plantilla else None
        if not mensaje:
            _log(automatizacion, AutomatizacionLog.Resultado.OMITIDO, 'Sin plantilla configurada',
                 contacto=contacto)
            return      # sin plantilla no tiene sentido recorrer el resto
        try:
            enviar_automatico(telefono=conv.telefono, plantilla=plantilla, contexto=contexto)
            _log(automatizacion, AutomatizacionLog.Resultado.EXITOSO, mensaje, contacto=contacto)
        except Exception as exc:
            logger.exception('Error en seguimiento_charla para %s', conv.telefono)
            _log(automatizacion, AutomatizacionLog.Resultado.ERROR, str(exc), contacto=contacto)

HANDLERS = {
    Automatizacion.Tipo.RECORDATORIO_24H: recordatorio_24h,
    Automatizacion.Tipo.RECORDATORIO_2H: recordatorio_2h,
    Automatizacion.Tipo.RECLAMO_SENA: reclamo_sena,
    Automatizacion.Tipo.ENCUESTA_SATISFACCION: encuesta_satisfaccion,
    Automatizacion.Tipo.REACTIVACION_INACTIVOS: reactivacion_inactivos,
    Automatizacion.Tipo.ALERTA_CUPO: alerta_cupo,
    Automatizacion.Tipo.LISTA_ESPERA: lista_espera,
    Automatizacion.Tipo.CUMPLEANOS: cumpleanos,
    Automatizacion.Tipo.SEGUIMIENTO_CHARLA: seguimiento_charla,
    Automatizacion.Tipo.SEGUIMIENTO_CHARLA_2: seguimiento_charla,
}


@shared_task
def ejecutar_automatizaciones():
    # El vigía de la conexión de WhatsApp viaja con esta tarea en vez de tener su propia
    # entrada en el scheduler: esta ya corre cada 15 minutos, así que no hay nada que
    # configurar. No depende de que haya automatizaciones activas: si el WhatsApp está
    # caído hay que avisar igual.
    try:
        from apps.whatsapp.tasks import vigilar_conexion

        vigilar_conexion()
    except Exception:
        logger.exception('Falló el vigía de la conexión de WhatsApp')

    # Primero la limpieza de holds vencidos. Va afuera del loop de automatizaciones a
    # propósito: liberar el cupo es integridad de datos, no una campaña. Antes vivía dentro
    # del handler `reclamo_sena`, así que apagar esa automatización (algo razonable si no
    # querés mandar el mensaje de reclamo) dejaba de liberar turnos sin que nadie se entere.
    try:
        for reserva in liberar_reservas_vencidas():
            logger.info('Cupo liberado por vencimiento de seña — reserva %s (%s %s, %s)',
                        reserva.id, reserva.fecha, reserva.turno.nombre, reserva.contacto.telefono)
    except Exception:
        logger.exception('Error liberando reservas vencidas')

    en_horario = _puede_escribirle_al_cliente()
    for automatizacion in Automatizacion.objects.filter(activa=True):
        handler = HANDLERS.get(automatizacion.tipo)
        if not handler:
            continue
        # Fuera del horario de atención no se le escribe a ningún cliente. Antes esto lo
        # miraba SOLO el seguimiento de charlas: el cumpleaños, la encuesta, la reactivación
        # y los recordatorios salían a cualquier hora, incluidas las 2 de la mañana.
        if not en_horario and automatizacion.tipo in AUTOMATIZACIONES_AL_CLIENTE:
            _log(automatizacion, AutomatizacionLog.Resultado.OMITIDO,
                 'Fuera del horario de atención: se manda cuando abra')
            continue
        try:
            handler(automatizacion)
        except Exception:
            logger.exception('Error ejecutando automatización %s', automatizacion.tipo)
