import csv
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify

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
    data['por_verificar'] = services.transferencias_por_verificar()
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
    fecha = date.fromisoformat(fecha_str) if fecha_str else timezone.localdate()
    from datetime import timedelta
    return render(request, 'dashboard/caja.html', {
        'fecha': fecha,
        'fecha_anterior': fecha - timedelta(days=1),
        'fecha_siguiente': fecha + timedelta(days=1),
        'es_hoy': fecha == timezone.localdate(),
        'caja': services.caja_del_dia(fecha),
        'saldos': services.saldos_por_cobrar(),
    })


@login_required
def export_pagos(request):
    if not request.user.es_dueno:
        return redirect('turnero:hoy')
    from apps.reservas.models import Pago
    fecha_str = request.GET.get('fecha')
    fecha = date.fromisoformat(fecha_str) if fecha_str else timezone.localdate()

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


# ── Comprobantes de transferencia ────────────────────────────────────────────
# El cliente manda la foto por WhatsApp y queda pegada a la reserva. Esto junta las de un
# período para contabilidad: la lista en pantalla, un CSV, o un ZIP con las imágenes.

def _comprobantes(desde, hasta):
    """Reservas con comprobante adjunto en el período, de la más nueva a la más vieja.

    La fecha que manda es la de acreditación de la seña; si todavía no se verificó, la de
    creación de la reserva — así los comprobantes pendientes también aparecen y no se
    escapan del período.
    """
    from django.db.models.functions import Coalesce

    from apps.reservas.models import Reserva

    return (
        Reserva.objects
        .exclude(comprobante='').exclude(comprobante__isnull=True)
        .annotate(fecha_comprobante=Coalesce('sena_pagada_at', 'created_at'))
        .filter(fecha_comprobante__date__gte=desde, fecha_comprobante__date__lte=hasta)
        .select_related('contacto', 'circuito', 'turno')
        .order_by('-fecha_comprobante')
    )


def _periodo(request):
    desde_str, hasta_str = request.GET.get('desde'), request.GET.get('hasta')
    if desde_str and hasta_str:
        return date.fromisoformat(desde_str), date.fromisoformat(hasta_str)
    return services.periodo_mes_actual()


FILAS_COMPROBANTES = ['Fecha del pago', 'Cliente', 'Teléfono', 'Fecha de la reserva', 'Turno',
                      'Circuito', 'Personas', 'Seña', 'Medio de pago', 'Estado', 'Archivo']


def _fila_comprobante(r, nombre_archivo=''):
    return [
        timezone.localtime(r.fecha_comprobante).strftime('%Y-%m-%d %H:%M'),
        r.contacto.nombre, r.contacto.telefono,
        r.fecha.isoformat(), r.turno.nombre if r.turno else '',
        r.circuito.nombre, r.cantidad_personas, r.monto_sena,
        r.get_medio_pago_display(), r.get_estado_display(),
        nombre_archivo or (r.comprobante.url if r.comprobante else ''),
    ]


@login_required
def comprobantes(request):
    if not request.user.es_dueno:
        return redirect('turnero:hoy')
    desde, hasta = _periodo(request)
    reservas = list(_comprobantes(desde, hasta))
    return render(request, 'dashboard/comprobantes.html', {
        'desde': desde, 'hasta': hasta, 'reservas': reservas,
        'total_sena': sum((r.monto_sena or 0) for r in reservas),
    })


@login_required
def export_comprobantes_csv(request):
    if not request.user.es_dueno:
        return redirect('turnero:hoy')
    desde, hasta = _periodo(request)
    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="comprobantes_{desde}_a_{hasta}.csv"'
    resp.write('﻿')  # BOM para que Excel abra bien los acentos
    w = csv.writer(resp)
    w.writerow(FILAS_COMPROBANTES)
    for r in _comprobantes(desde, hasta):
        w.writerow(_fila_comprobante(r))
    return resp


@login_required
def export_comprobantes_zip(request):
    """Las imágenes del período en un ZIP, con un CSV adentro que las relaciona con su reserva."""
    if not request.user.es_dueno:
        return redirect('turnero:hoy')
    import io
    import zipfile

    desde, hasta = _periodo(request)
    buffer = io.BytesIO()
    filas = [FILAS_COMPROBANTES]
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for r in _comprobantes(desde, hasta)[:500]:   # tope de seguridad: no armar un ZIP gigante
            fecha = timezone.localtime(r.fecha_comprobante).strftime('%Y-%m-%d')
            apellido = slugify(r.contacto.nombre) or 'sin-nombre'
            extension = (r.comprobante.name.rsplit('.', 1) + ['jpg'])[1].lower()
            nombre = f'{fecha}_{apellido}_reserva-{r.pk}.{extension}'
            try:
                with r.comprobante.open('rb') as f:
                    z.writestr(nombre, f.read())
            except (FileNotFoundError, OSError):
                # El archivo figura en la base pero no está en disco: queda anotado en el CSV.
                nombre = '(archivo no encontrado)'
            filas.append(_fila_comprobante(r, nombre))

        indice = io.StringIO()
        csv.writer(indice).writerows(filas)
        z.writestr('comprobantes.csv', '﻿' + indice.getvalue())

    resp = HttpResponse(buffer.getvalue(), content_type='application/zip')
    resp['Content-Disposition'] = f'attachment; filename="comprobantes_{desde}_a_{hasta}.zip"'
    return resp
