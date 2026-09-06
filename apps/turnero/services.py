from django.db.models import Count, Sum

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
    """True si a esa fecha le corresponde la tarifa de fin de semana.

    Depende SOLO del día de la semana (config `dias_tarifa_finde`; por defecto sáb/dom, en
    este spa vie-sáb-dom). Los feriados ya no entran acá: no cambian la tarifa del día, le
    suman un recargo encima — ver `recargo_feriado()`.
    """
    from apps.configuracion.models import ConfiguracionNegocio

    dias = ConfiguracionNegocio.get_solo().dias_tarifa_finde or [5, 6]
    return fecha.weekday() in dias


def feriado_de(fecha):
    """El feriado que cae en esa fecha, o None. Contempla los recurrentes anuales.

    Si hubiera más de uno cargado para el mismo día (por ejemplo uno puntual y uno recurrente),
    gana el puntual: es el que alguien cargó a mano para ese año en concreto.
    """
    puntual = Feriado.objects.filter(recurrente_anual=False, fecha=fecha).first()
    if puntual is not None:
        return puntual
    for f in Feriado.objects.filter(recurrente_anual=True):
        if f.cae_en(fecha):
            return f
    return None


def recargo_feriado(fecha):
    """Porcentaje de recargo por feriado que le toca a esa fecha. 0 si no es feriado."""
    from decimal import Decimal

    feriado = feriado_de(fecha)
    return feriado.porcentaje_efectivo if feriado is not None else Decimal('0')


def info_tarifa(fecha):
    """Todo lo que hace falta para explicar el precio de un día, en un solo lugar.

    Lo usan la API del bot y la UI, así que la explicación del precio sale siempre igual y no
    hay dos versiones de la misma cuenta dando vueltas.
    """
    feriado = feriado_de(fecha)
    es_feriado = feriado is not None and feriado.modo == Feriado.Modo.RECARGO
    return {
        'tarifa': 'finde' if es_dia_tarifa_finde(fecha) else 'semana',
        'es_feriado': es_feriado,
        'feriado': (feriado.descripcion or 'Feriado') if feriado is not None else '',
        'recargo_porcentaje': float(feriado.porcentaje_efectivo) if es_feriado else 0.0,
    }


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
        # Le decimos al bot POR QUÉ está cerrado: no es lo mismo "ese día no abrimos nunca"
        # que "el 25 de diciembre estamos cerrados". Con esto puede dar una respuesta útil
        # en vez de un "no hay turnos" seco.
        feriado = feriado_de(fecha)
        cerrado_por_feriado = feriado is not None and feriado.modo == Feriado.Modo.CERRADO
        return {
            'fecha': fecha.isoformat(),
            'habilitado': False,
            'motivo_cierre': 'feriado' if cerrado_por_feriado else 'dia_no_laborable',
            'motivo_detalle': (feriado.descripcion or 'Feriado') if cerrado_por_feriado else '',
            'turnos': [],
        }

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
                    Reserva.objects.ocupando_cupo()
                    .filter(fecha=fecha, turno=turno)
                    .select_related('circuito')
                    .first()
                )
                if reserva_del_slot is not None:
                    cupo_ocupado = circuito.capacidad_maxima  # tomado: sin lugar
                    ocupado_por_otro_circuito = reserva_del_slot.circuito_id != circuito.id
            else:
                cupo_ocupado = Reserva.objects.ocupando_cupo().filter(
                    circuito=circuito, fecha=fecha, turno=turno,
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

    return {
        'fecha': fecha.isoformat(),
        'habilitado': True,
        **info_tarifa(fecha),
        'turnos': resultado,
    }


def turnero_crudo(desde, dias=14):
    """Ocupación cruda por (fecha, turno) para todo el spa, SIN reglas de negocio ni circuito.
    Para cada día del rango y cada turno activo devuelve si hay una reserva que ocupa el slot
    y cuántas personas suma. El bot lo usa como fuente de verdad simple del turnero; toda la
    lógica de cupo/precio/exclusividad vive en el CRM y no se expone acá."""
    from datetime import timedelta

    from apps.reservas.models import Reserva

    dias_semana = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']
    turnos = list(Turno.objects.filter(activo=True).order_by('hora_inicio'))
    hasta = desde + timedelta(days=max(dias, 1) - 1)

    ocupacion = {}
    reservas = (
        Reserva.objects.ocupando_cupo()
        .filter(fecha__gte=desde, fecha__lte=hasta)
        .values('fecha', 'turno_id')
        .annotate(personas=Sum('cantidad_personas'), reservas=Count('id'))
    )
    for row in reservas:
        ocupacion[(row['fecha'], row['turno_id'])] = (row['personas'] or 0, row['reservas'])

    resultado = []
    d = desde
    while d <= hasta:
        slots = []
        for turno in turnos:
            personas, cant = ocupacion.get((d, turno.id), (0, 0))
            slots.append({
                'turno_id': turno.id,
                'turno_nombre': turno.nombre,
                'hora_inicio': turno.hora_inicio.strftime('%H:%M'),
                'hora_fin': turno.hora_fin.strftime('%H:%M'),
                'ocupado': cant > 0,
                'personas': personas,
                'reservas': cant,
            })
        resultado.append({
            'fecha': d.isoformat(),
            'dia_semana': dias_semana[d.weekday()],
            'turnos': slots,
        })
        d += timedelta(days=1)
    return resultado


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
            'es_feriado': info.get('es_feriado', False),
            'feriado': info.get('feriado', ''),
            'recargo_porcentaje': info.get('recargo_porcentaje', 0.0),
            'tarifa': info.get('tarifa', ''),
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
