import csv
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from . import services


@login_required
def home(request):
    # El dashboard con facturación e ingresos es solo para el dueño.
    # Recepción entra directo al turnero (su herramienta de trabajo).
    if not request.user.es_dueno:
        return redirect('turnero:hoy')

    desde_str = request.GET.get('desde')
    hasta_str = request.GET.get('hasta')
    if desde_str and hasta_str:
        desde, hasta = date.fromisoformat(desde_str), date.fromisoformat(hasta_str)
    else:
        desde, hasta = services.periodo_mes_actual()

    data = services.resumen(desde, hasta)
    return render(request, 'dashboard/home.html', data)


@login_required
def salud(request):
    if not request.user.es_dueno:
        return redirect('turnero:hoy')
    return render(request, 'dashboard/salud.html', {'salud': services.salud_sistema()})


@login_required
def caja(request):
    if not request.user.es_dueno:
        return redirect('turnero:hoy')
    fecha_str = request.GET.get('fecha')
    fecha = date.fromisoformat(fecha_str) if fecha_str else date.today()
    from datetime import timedelta
    return render(request, 'dashboard/caja.html', {
        'fecha': fecha,
        'fecha_anterior': fecha - timedelta(days=1),
        'fecha_siguiente': fecha + timedelta(days=1),
        'es_hoy': fecha == date.today(),
        'caja': services.caja_del_dia(fecha),
        'saldos': services.saldos_por_cobrar(),
    })


@login_required
def export_pagos(request):
    if not request.user.es_dueno:
        return redirect('turnero:hoy')
    from apps.reservas.models import Pago
    fecha_str = request.GET.get('fecha')
    fecha = date.fromisoformat(fecha_str) if fecha_str else date.today()

    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="caja_{fecha.isoformat()}.csv"'
    resp.write('﻿')  # BOM para que Excel abra bien los acentos
    w = csv.writer(resp)
    w.writerow(['Fecha', 'Hora', 'Cliente', 'Teléfono', 'Circuito', 'Tipo', 'Medio de pago', 'Monto'])
    pagos = (
        Pago.objects.filter(fecha__date=fecha)
        .select_related('reserva__contacto', 'reserva__circuito').order_by('fecha')
    )
    for p in pagos:
        w.writerow([
            fecha.isoformat(), p.fecha.strftime('%H:%M'),
            p.reserva.contacto.nombre, p.reserva.contacto.telefono,
            p.reserva.circuito.nombre, p.get_tipo_display(), p.get_medio_pago_display(), p.monto,
        ])
    return resp
