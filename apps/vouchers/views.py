from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.turnero.models import Turno

from . import services
from .forms import VoucherForm
from .models import Voucher


@login_required
def lista(request):
    vouchers = Voucher.objects.select_related('circuito').all()
    return render(request, 'vouchers/lista.html', {'vouchers': vouchers})


@login_required
def crear(request):
    if request.method == 'POST':
        form = VoucherForm(request.POST)
        if form.is_valid():
            voucher = form.save()
            return redirect('vouchers:detalle', pk=voucher.pk)
    else:
        form = VoucherForm()
    return render(request, 'vouchers/form.html', {'form': form})


@login_required
def detalle(request, pk):
    voucher = get_object_or_404(Voucher, pk=pk)
    return render(request, 'vouchers/detalle.html', {'voucher': voucher})


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
                cantidad_personas=int(request.POST.get('cantidad_personas', 1)),
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
def anular(request, pk):
    voucher = get_object_or_404(Voucher, pk=pk)
    if request.method == 'POST' and voucher.estado == Voucher.Estado.ACTIVO:
        voucher.estado = Voucher.Estado.CANCELADO
        voucher.save(update_fields=['estado'])
    return redirect('vouchers:detalle', pk=pk)
