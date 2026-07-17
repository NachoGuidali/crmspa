import json
from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.circuitos.models import Circuito
from apps.contactos.models import Contacto
from apps.turnero.models import Turno

from . import services
from .models import ListaEspera, Reserva


@login_required
def kanban(request):
    columnas = []
    for value, label in Reserva.Estado.choices:
        columnas.append({
            'estado': value,
            'label': label,
            'reservas': Reserva.objects.filter(estado=value).select_related('contacto', 'circuito', 'turno').order_by('fecha')[:100],
        })
    return render(request, 'reservas/kanban.html', {'columnas': columnas})


@login_required
@require_POST
def kanban_move(request, pk):
    reserva = get_object_or_404(Reserva, pk=pk)
    data = json.loads(request.body or '{}')
    nuevo_estado = data.get('estado')
    if nuevo_estado not in dict(Reserva.Estado.choices):
        return JsonResponse({'error': 'estado_invalido'}, status=400)

    anterior = reserva.estado
    reserva.estado = nuevo_estado
    try:
        reserva.full_clean()
    except ValidationError as e:
        return JsonResponse({'error': '; '.join(e.messages)}, status=422)
    reserva.save()
    return JsonResponse({'ok': True, 'anterior': anterior})


def _nueva_reserva_context(extra=None):
    ctx = {
        'circuitos': Circuito.objects.filter(activo=True),
        'turnos': Turno.objects.filter(activo=True),
        'contactos': list(Contacto.objects.order_by('nombre').values('id', 'nombre', 'telefono')),
    }
    if extra:
        ctx.update(extra)
    return ctx


@login_required
def nueva_reserva(request):
    if request.method == 'POST':
        # El cliente puede venir de un contacto existente (contacto_id) o cargarse nuevo
        # con teléfono + nombre. En ambos casos la reserva queda asociada a un contacto:
        # si el teléfono no existe todavía, crear_reserva lo crea.
        telefono = request.POST.get('telefono', '').strip()
        nombre = request.POST.get('nombre_contacto', '').strip()
        contacto_id = request.POST.get('contacto_id')
        if contacto_id:
            contacto = Contacto.objects.filter(pk=contacto_id).first()
            if contacto:
                telefono = contacto.telefono
                nombre = contacto.nombre

        if not telefono:
            return render(request, 'reservas/nueva.html', _nueva_reserva_context({
                'error': 'Elegí un contacto existente o ingresá teléfono y nombre del cliente.',
            }))

        try:
            services.crear_reserva(
                telefono=telefono,
                nombre_contacto=nombre,
                circuito_id=request.POST['circuito_id'],
                turno_id=request.POST['turno_id'],
                fecha=date.fromisoformat(request.POST['fecha']),
                cantidad_personas=int(request.POST.get('cantidad_personas', 1)),
                notas=request.POST.get('notas', ''),
            )
        except services.ReservaError as e:
            return render(request, 'reservas/nueva.html', _nueva_reserva_context({'error': str(e)}))
        return redirect('reservas:kanban')

    return render(request, 'reservas/nueva.html', _nueva_reserva_context())


@login_required
def detalle(request, pk):
    reserva = get_object_or_404(Reserva.objects.select_related('contacto', 'circuito', 'turno'), pk=pk)
    from apps.circuitos.models import Extra
    from django.db.models import Q
    extras_disponibles = Extra.objects.filter(activo=True).filter(
        Q(circuito__isnull=True) | Q(circuito=reserva.circuito)
    )
    return render(request, 'reservas/detalle.html', {
        'reserva': reserva,
        'turnos': Turno.objects.filter(activo=True),
        'extras_disponibles': extras_disponibles,
        'extras_reserva': reserva.extras.all(),
    })


@login_required
def comprobante(request, pk):
    reserva = get_object_or_404(
        Reserva.objects.select_related('contacto', 'circuito', 'turno').prefetch_related('extras'), pk=pk
    )
    from apps.configuracion.models import ConfiguracionNegocio
    return render(request, 'reservas/comprobante.html', {
        'reserva': reserva,
        'negocio': ConfiguracionNegocio.get_solo(),
    })


@login_required
@require_POST
def agregar_extra(request, pk):
    from apps.circuitos.models import Extra

    from .models import ReservaExtra
    reserva = get_object_or_404(Reserva, pk=pk)
    extra = Extra.objects.filter(pk=request.POST.get('extra_id'), activo=True).first()
    if extra:
        cantidad = max(int(request.POST.get('cantidad', 1) or 1), 1)
        ReservaExtra.objects.create(
            reserva=reserva, extra=extra, nombre=extra.nombre,
            precio_unitario=extra.precio, cantidad=cantidad,
        )
    return redirect('reservas:detalle', pk=pk)


@login_required
@require_POST
def quitar_extra(request, pk, extra_id):
    from .models import ReservaExtra
    ReservaExtra.objects.filter(pk=extra_id, reserva_id=pk).delete()
    return redirect('reservas:detalle', pk=pk)


@login_required
@require_POST
def reprogramar(request, pk):
    from datetime import date as _date

    reserva = get_object_or_404(Reserva, pk=pk)
    from django.contrib import messages
    try:
        services.reprogramar_reserva(
            reserva,
            nueva_fecha=_date.fromisoformat(request.POST['fecha']),
            nuevo_turno_id=request.POST['turno_id'],
        )
        messages.success(request, 'Reserva reprogramada. El cupo anterior quedó liberado.')
    except services.ReservaError as e:
        messages.error(request, f'No se pudo reprogramar: {e}')
    return redirect('reservas:detalle', pk=pk)


@login_required
@require_POST
def cancelar(request, pk):
    reserva = get_object_or_404(Reserva, pk=pk)
    services.cancelar_reserva(reserva, motivo=request.POST.get('motivo', ''))
    return redirect('reservas:detalle', pk=pk)


def _redirect_next(request, pk):
    next_url = request.POST.get('next')
    return redirect(next_url) if next_url else redirect('reservas:detalle', pk=pk)


@login_required
@require_POST
def marcar_asistio(request, pk):
    services.marcar_asistio(get_object_or_404(Reserva, pk=pk))
    return _redirect_next(request, pk)


@login_required
@require_POST
def marcar_no_show(request, pk):
    services.marcar_no_show(get_object_or_404(Reserva, pk=pk))
    return _redirect_next(request, pk)


@login_required
def lista_espera(request):
    if request.method == 'POST':
        telefono = request.POST.get('telefono', '').strip()
        nombre = request.POST.get('nombre', '').strip()
        circuito_id = request.POST.get('circuito_id')
        fecha = request.POST.get('fecha_deseada')
        turno_id = request.POST.get('turno_id') or None
        if telefono and circuito_id and fecha:
            from datetime import date as _date

            from utils.phone import normalize_ar_phone
            contacto, _ = Contacto.objects.get_or_create(
                telefono=normalize_ar_phone(telefono), defaults={'nombre': nombre or telefono}
            )
            ListaEspera.objects.create(
                contacto=contacto, circuito_id=circuito_id,
                fecha_deseada=_date.fromisoformat(fecha), turno_id=turno_id,
            )
        return redirect('reservas:lista_espera')

    return render(request, 'reservas/lista_espera.html', {
        'esperas': ListaEspera.objects.select_related('contacto', 'circuito', 'turno').order_by('notificado', 'created_at'),
        'circuitos': Circuito.objects.filter(activo=True),
        'turnos': Turno.objects.filter(activo=True),
    })


@login_required
@require_POST
def quitar_espera(request, pk):
    get_object_or_404(ListaEspera, pk=pk).delete()
    return redirect('reservas:lista_espera')
