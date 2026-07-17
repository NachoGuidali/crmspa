import logging
from datetime import datetime, timedelta

from celery import shared_task
from django.db.models import Sum
from django.utils import timezone

from apps.reservas.models import Reserva
from apps.reservas.services import liberar_reservas_vencidas
from apps.whatsapp.services import enviar_mensaje

from .models import Automatizacion, AutomatizacionLog

logger = logging.getLogger('apps.automations')


# Categoría de cada automatización → qué preferencia del contacto respeta.
CATEGORIA = {
    Automatizacion.Tipo.RECORDATORIO_24H: 'recordatorio',
    Automatizacion.Tipo.RECORDATORIO_2H: 'recordatorio',
    Automatizacion.Tipo.RECLAMO_SENA: 'recordatorio',
    Automatizacion.Tipo.ENCUESTA_SATISFACCION: 'recordatorio',
    Automatizacion.Tipo.LISTA_ESPERA: 'recordatorio',
    Automatizacion.Tipo.REACTIVACION_INACTIVOS: 'promo',
    Automatizacion.Tipo.CUMPLEANOS: 'promo',
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
        enviar_mensaje(telefono=reserva.contacto.telefono, mensaje=mensaje)
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

    for reserva in liberar_reservas_vencidas():
        _log(automatizacion, AutomatizacionLog.Resultado.EXITOSO,
             'Cupo liberado por vencimiento de seña', contacto=reserva.contacto, reserva=reserva)


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
        mensaje = plantilla.render({'nombre': contacto.nombre}) if plantilla else None
        if not mensaje:
            _log(automatizacion, AutomatizacionLog.Resultado.OMITIDO, 'Sin plantilla configurada', contacto=contacto)
            continue
        try:
            enviar_mensaje(telefono=contacto.telefono, mensaje=mensaje)
            _log(automatizacion, AutomatizacionLog.Resultado.EXITOSO, mensaje, contacto=contacto)
        except Exception as exc:
            logger.exception('Error en reactivacion_inactivos para contacto %s', contacto.id)
            _log(automatizacion, AutomatizacionLog.Resultado.ERROR, str(exc), contacto=contacto)


def alerta_cupo(automatizacion):
    """Deja constancia en el log cuando un circuito llega a cupo completo o queda 1 lugar.
    (Sin canal de notificación interna todavía — se agrega junto con la UI del inbox/kanban.)"""
    hoy = timezone.localdate()
    reservas = (
        Reserva.objects.filter(
            estado__in=Reserva.ESTADOS_QUE_OCUPAN_CUPO, fecha__gte=hoy, fecha__lte=hoy + timedelta(days=7),
        )
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
        mensaje = plantilla.render({
            'nombre': siguiente.contacto.nombre, 'circuito': siguiente.circuito.nombre,
            'fecha': siguiente.fecha_deseada.strftime('%d/%m/%Y'),
        }) if plantilla else None
        if not mensaje:
            _log(automatizacion, AutomatizacionLog.Resultado.OMITIDO, 'Sin plantilla configurada', contacto=siguiente.contacto)
            continue
        try:
            enviar_mensaje(telefono=siguiente.contacto.telefono, mensaje=mensaje)
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
        mensaje = plantilla.render({'nombre': contacto.nombre}) if plantilla else None
        if not mensaje:
            _log(automatizacion, AutomatizacionLog.Resultado.OMITIDO, 'Sin plantilla configurada', contacto=contacto)
            continue
        try:
            enviar_mensaje(telefono=contacto.telefono, mensaje=mensaje)
            _log(automatizacion, AutomatizacionLog.Resultado.EXITOSO, mensaje, contacto=contacto)
        except Exception as exc:
            logger.exception('Error enviando cumpleanos a contacto %s', contacto.id)
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
}


@shared_task
def ejecutar_automatizaciones():
    for automatizacion in Automatizacion.objects.filter(activa=True):
        handler = HANDLERS.get(automatizacion.tipo)
        if not handler:
            continue
        try:
            handler(automatizacion)
        except Exception:
            logger.exception('Error ejecutando automatización %s', automatizacion.tipo)
