import calendar
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render

from apps.circuitos.models import Circuito
from apps.reservas.models import Reserva

from .models import Feriado, Turno
from .services import dia_habilitado, disponibilidad_circuito


def _resumen_dia(dia, turnos_activos, reservas_por_dia):
    """Devuelve un dict con métricas rápidas de un día para pintar la celda del calendario."""
    reservas = reservas_por_dia.get(dia, {'count': 0, 'personas': 0})
    slots = sum(1 for t in turnos_activos if t.aplica_en(dia))
    return {
        'reservas': reservas['count'],
        'personas': reservas['personas'],
        'slots': slots,
        'habilitado': dia_habilitado(dia),
    }


@login_required
def calendario(request):
    hoy = date.today()
    try:
        anio = int(request.GET.get('anio', hoy.year))
        mes = int(request.GET.get('mes', hoy.month))
    except (ValueError, TypeError):
        anio, mes = hoy.year, hoy.month

    primero = date(anio, mes, 1)
    mes_anterior = (primero - timedelta(days=1)).replace(day=1)
    dias_en_mes = calendar.monthrange(anio, mes)[1]
    ultimo = date(anio, mes, dias_en_mes)
    mes_siguiente = (ultimo + timedelta(days=1))

    turnos_activos = list(Turno.objects.filter(activo=True))

    reservas_qs = (
        Reserva.objects.filter(fecha__gte=primero, fecha__lte=ultimo, estado__in=Reserva.ESTADOS_QUE_OCUPAN_CUPO)
        .values('fecha').annotate(count=Count('id'), personas=Sum('cantidad_personas'))
    )
    reservas_por_dia = {r['fecha']: {'count': r['count'], 'personas': r['personas'] or 0} for r in reservas_qs}
    feriados = {
        f.fecha: f.modo
        for f in Feriado.objects.filter(recurrente_anual=False, fecha__gte=primero, fecha__lte=ultimo)
    }
    feriados_rec = list(Feriado.objects.filter(recurrente_anual=True))

    # Armar la grilla del calendario (semanas de lunes a domingo)
    cal = calendar.Calendar(firstweekday=0)
    semanas = []
    for semana in cal.monthdatescalendar(anio, mes):
        fila = []
        for dia in semana:
            modo_feriado = feriados.get(dia)
            if modo_feriado is None:
                for f in feriados_rec:
                    if f.cae_en(dia):
                        modo_feriado = f.modo
                        break
            fila.append({
                'fecha': dia,
                'es_del_mes': dia.month == mes,
                'es_hoy': dia == hoy,
                'es_feriado': modo_feriado is not None,
                'feriado_abre': modo_feriado == Feriado.Modo.PRECIO_FINDE,
                'resumen': _resumen_dia(dia, turnos_activos, reservas_por_dia),
            })
        semanas.append(fila)

    meses_es = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
                'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

    return render(request, 'turnero/calendario.html', {
        'anio': anio, 'mes': mes, 'mes_nombre': meses_es[mes - 1],
        'semanas': semanas,
        'mes_anterior': mes_anterior, 'mes_siguiente': mes_siguiente,
        'dias_semana': ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'],
        'turnos': turnos_activos,
    })


@login_required
def hoy(request):
    """Agenda del día: lo primero que mira recepción. Turnos de hoy con quién viene,
    estado, saldo a cobrar y acciones rápidas."""
    fecha_str = request.GET.get('fecha')
    fecha = date.fromisoformat(fecha_str) if fecha_str else date.today()

    reservas = list(
        Reserva.objects.filter(fecha=fecha)
        .exclude(estado=Reserva.Estado.CANCELADO)
        .select_related('contacto', 'circuito', 'turno')
        .prefetch_related('extras')
        .order_by('turno__hora_inicio', 'circuito__nombre')
    )
    total_a_cobrar = sum((r.saldo for r in reservas), 0)
    total_personas = sum(r.cantidad_personas for r in reservas)

    # Agrupar por turno para mostrar la agenda ordenada
    por_turno = {}
    for r in reservas:
        por_turno.setdefault(r.turno, []).append(r)
    bloques = [{'turno': t, 'reservas': rs} for t, rs in sorted(por_turno.items(), key=lambda x: x[0].hora_inicio)]

    return render(request, 'turnero/hoy.html', {
        'fecha': fecha,
        'es_hoy': fecha == date.today(),
        'fecha_anterior': fecha - timedelta(days=1),
        'fecha_siguiente': fecha + timedelta(days=1),
        'bloques': bloques,
        'total_reservas': len(reservas),
        'total_personas': total_personas,
        'total_a_cobrar': total_a_cobrar,
        'habilitado': dia_habilitado(fecha),
    })


@login_required
def dia(request, fecha_iso):
    fecha = date.fromisoformat(fecha_iso)
    filas = []
    for circuito in Circuito.objects.filter(activo=True):
        data = disponibilidad_circuito(circuito, fecha)
        # reservas por turno
        reservas = (
            Reserva.objects.filter(circuito=circuito, fecha=fecha)
            .select_related('contacto', 'turno').order_by('turno__hora_inicio')
        )
        reservas_por_turno = {}
        for r in reservas:
            reservas_por_turno.setdefault(r.turno_id, []).append(r)
        for t in data['turnos']:
            t['reservas'] = reservas_por_turno.get(t['turno_id'], [])
        filas.append({'circuito': circuito, 'turnos': data['turnos']})

    return render(request, 'turnero/dia.html', {
        'fecha': fecha,
        'fecha_anterior': fecha - timedelta(days=1),
        'fecha_siguiente': fecha + timedelta(days=1),
        'habilitado': dia_habilitado(fecha),
        'filas': filas,
    })
