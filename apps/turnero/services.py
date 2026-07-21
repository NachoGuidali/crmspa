from django.db.models import Sum

from .models import BloqueoManual, Feriado, Turno


def dia_habilitado(fecha):
    """False si el negocio no atiende ese día (feriado CERRADO o fuera de días laborables).
    Un feriado en modo "abre con tarifa de finde" NO cierra el día."""
    from apps.configuracion.models import ConfiguracionNegocio

    cerrados = Feriado.objects.filter(modo=Feriado.Modo.CERRADO)
    if cerrados.filter(recurrente_anual=False, fecha=fecha).exists():
        return False
    if any(f.cae_en(fecha) for f in cerrados.filter(recurrente_anual=True)):
        return False

    config = ConfiguracionNegocio.get_solo()
    dias = config.dias_laborables
    if dias and fecha.weekday() not in dias:
        return False
    return True


def es_dia_tarifa_finde(fecha):
    """True si a esa fecha le corresponde la tarifa de fin de semana: los días configurados
    como 'tarifa finde' (por defecto sáb/dom; en este spa vie-sáb-dom), o un feriado marcado
    como "abre con tarifa de fin de semana"."""
    from apps.configuracion.models import ConfiguracionNegocio

    dias = ConfiguracionNegocio.get_solo().dias_tarifa_finde or [5, 6]
    if fecha.weekday() in dias:
        return True
    finde = Feriado.objects.filter(modo=Feriado.Modo.PRECIO_FINDE)
    if finde.filter(recurrente_anual=False, fecha=fecha).exists():
        return True
    if any(f.cae_en(fecha) for f in finde.filter(recurrente_anual=True)):
        return True
    return False


def turnos_bloqueados(circuito, fecha):
    """IDs de Turno bloqueados manualmente para este circuito+fecha (incluye bloqueos de 'todo el día')."""
    from django.db.models import Q

    bloqueos = BloqueoManual.objects.filter(fecha=fecha).filter(
        Q(circuito__isnull=True) | Q(circuito=circuito)
    )
    bloqueados = set()
    dia_completo = False
    for b in bloqueos:
        if b.turno_id is None:
            dia_completo = True
        else:
            bloqueados.add(b.turno_id)
    return bloqueados, dia_completo


def disponibilidad_circuito(circuito, fecha):
    """
    Devuelve la disponibilidad de un circuito para una fecha, turno por turno.
    Esta es la función que consume la API de disponibilidad para n8n.
    """
    if not dia_habilitado(fecha):
        return {'fecha': fecha.isoformat(), 'habilitado': False, 'turnos': []}

    from apps.configuracion.models import ConfiguracionNegocio
    from apps.reservas.models import Reserva

    exclusivo = ConfiguracionNegocio.get_solo().reserva_exclusiva_por_turno
    bloqueados_ids, dia_completo_bloqueado = turnos_bloqueados(circuito, fecha)

    turnos_qs = Turno.objects.filter(activo=True)
    resultado = []
    for turno in turnos_qs:
        if not turno.aplica_en(fecha):
            continue

        bloqueado = dia_completo_bloqueado or turno.id in bloqueados_ids

        cupo_ocupado = 0
        ocupado_por_otro_circuito = False
        if not bloqueado:
            if exclusivo:
                # El turno se comparte en todo el spa: cualquier reserva lo ocupa por completo.
                reserva_del_slot = (
                    Reserva.objects.filter(
                        fecha=fecha, turno=turno, estado__in=Reserva.ESTADOS_QUE_OCUPAN_CUPO,
                    )
                    .select_related('circuito')
                    .first()
                )
                if reserva_del_slot is not None:
                    cupo_ocupado = circuito.capacidad_maxima  # tomado: sin lugar
                    ocupado_por_otro_circuito = reserva_del_slot.circuito_id != circuito.id
            else:
                cupo_ocupado = Reserva.objects.filter(
                    circuito=circuito, fecha=fecha, turno=turno,
                    estado__in=Reserva.ESTADOS_QUE_OCUPAN_CUPO,
                ).aggregate(total=Sum('cantidad_personas'))['total'] or 0

        cupo_disponible = max(circuito.capacidad_maxima - cupo_ocupado, 0) if not bloqueado else 0

        resultado.append({
            'turno_id': turno.id,
            'turno_nombre': turno.nombre,
            'hora_inicio': turno.hora_inicio.strftime('%H:%M'),
            'hora_fin': turno.hora_fin.strftime('%H:%M'),
            'cupo_total': circuito.capacidad_maxima,
            'cupo_ocupado': cupo_ocupado,
            'cupo_disponible': cupo_disponible,
            'bloqueado': bloqueado,
            'ocupado_por_otro_circuito': ocupado_por_otro_circuito,
        })

    return {'fecha': fecha.isoformat(), 'habilitado': True, 'turnos': resultado}


def disponibilidad_rango(circuito, desde, hasta, personas=None):
    """
    Disponibilidad de un circuito para un rango de fechas (para que el bot muestre
    'qué días hay' o sugiera alternativas cuando un día pedido está lleno).
    Devuelve una lista de días, cada uno con los turnos que tienen lugar.
    """
    from datetime import timedelta

    dias = []
    d = desde
    while d <= hasta:
        info = disponibilidad_circuito(circuito, d)
        turnos_libres = [
            t for t in info['turnos']
            if not t['bloqueado'] and t['cupo_disponible'] > 0
            and (personas is None or t['cupo_disponible'] >= personas)
        ]
        dias.append({
            'fecha': d.isoformat(),
            'habilitado': info['habilitado'],
            'hay_lugar': bool(turnos_libres),
            'turnos_libres': [
                {
                    'turno_id': t['turno_id'], 'turno_nombre': t['turno_nombre'],
                    'hora_inicio': t['hora_inicio'], 'hora_fin': t['hora_fin'],
                    'cupo_disponible': t['cupo_disponible'],
                }
                for t in turnos_libres
            ],
        })
        d += timedelta(days=1)
    return dias
