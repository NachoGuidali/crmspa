from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.turnero.models import Turno

from . import services
from .forms import VoucherForm
from .models import Voucher


@login_required
def lista(request):
    vouchers = Voucher.objects.select_related('circuito').all()
    estado = request.GET.get('estado', '')
    if estado:
        vouchers = vouchers.filter(estado=estado)
    return render(request, 'vouchers/lista.html', {
        'vouchers': vouchers,
        'estados': Voucher.Estado.choices,
        'estado_actual': estado,
        # Los que están esperando que alguien mire la transferencia van arriba de todo: es lo
        # único de esta pantalla que frena a un cliente.
        'por_revisar': Voucher.objects.filter(estado=Voucher.Estado.PENDIENTE_APROBACION).count(),
    })


@login_required
def crear(request):
    if request.method == 'POST':
        form = VoucherForm(request.POST)
        if form.is_valid():
            voucher = form.save()
            # Cargado a mano el pago ya está visto, así que el voucher nace activo y con el
            # archivo listo para descargar o mandar.
            services.generar_archivos(voucher)
            return redirect('vouchers:detalle', pk=voucher.pk)
    else:
        form = VoucherForm()
    return render(request, 'vouchers/form.html', {'form': form})


@login_required
def detalle(request, pk):
    voucher = get_object_or_404(Voucher.objects.select_related('circuito'), pk=pk)
    return render(request, 'vouchers/detalle.html', {'voucher': voucher})


@login_required
@require_POST
def aprobar(request, pk):
    """El equipo miró la transferencia: el voucher queda activo y sale para el cliente."""
    voucher = get_object_or_404(Voucher, pk=pk)
    try:
        services.aprobar(voucher, usuario=request.user)
    except services.VoucherError as e:
        messages.error(request, f'No se pudo aprobar: {e}')
        return redirect('vouchers:detalle', pk=pk)

    messages.success(request, 'Voucher aprobado.')
    _enviar(request, voucher)
    return redirect('vouchers:detalle', pk=pk)


@login_required
@require_POST
def reenviar(request, pk):
    voucher = get_object_or_404(Voucher, pk=pk)
    _enviar(request, voucher)
    return redirect('vouchers:detalle', pk=pk)


def _enviar(request, voucher):
    """Manda el voucher y cuenta qué pasó. Que falle el envío no desarma la aprobación:
    el voucher ya está activo y el botón de reenviar queda a mano."""
    from apps.whatsapp.services import EnvioError, FueraDeVentanaError

    try:
        services.enviar(voucher, usuario=request.user)
    except (services.VoucherError, EnvioError, FueraDeVentanaError) as e:
        messages.error(request, f'El voucher quedó activo, pero no se pudo mandar por WhatsApp: {e}')
        return False
    messages.success(request, f'Voucher enviado por WhatsApp a {voucher.comprador_telefono}.')
    return True


@login_required
def canjear(request, pk):
    voucher = get_object_or_404(Voucher, pk=pk)
    turnos = Turno.objects.filter(activo=True)
    if request.method == 'POST':
        try:
            reserva, _ = services.canjear(
                voucher.codigo,
                telefono=request.POST['telefono'],
                nombre_contacto=request.POST.get('nombre_contacto', ''),
                turno_id=request.POST['turno_id'],
                fecha=date.fromisoformat(request.POST['fecha']),
                cantidad_personas=int(request.POST.get('cantidad_personas', 0) or 0) or None,
            )
        except services.VoucherError as e:
            messages.error(request, f'No se pudo canjear: {e}')
            return render(request, 'vouchers/canjear.html', {'voucher': voucher, 'turnos': turnos})
        except Exception as e:
            messages.error(request, f'No se pudo crear la reserva: {e}')
            return render(request, 'vouchers/canjear.html', {'voucher': voucher, 'turnos': turnos})
        messages.success(request, f'Voucher canjeado. Reserva #{reserva.id} creada y confirmada.')
        return redirect('vouchers:detalle', pk=voucher.pk)
    return render(request, 'vouchers/canjear.html', {'voucher': voucher, 'turnos': turnos})


@login_required
@require_POST
def anular(request, pk):
    voucher = get_object_or_404(Voucher, pk=pk)
    if voucher.estado != Voucher.Estado.CANJEADO:
        voucher.estado = Voucher.Estado.CANCELADO
        voucher.save(update_fields=['estado'])
        messages.success(request, 'Voucher anulado.')
    return redirect('vouchers:detalle', pk=pk)
