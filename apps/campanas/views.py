from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import CampanaForm
from .models import Campana
from .tasks import ejecutar_campana


@login_required
def lista(request):
    campanas = Campana.objects.select_related('plantilla').all()
    return render(request, 'campanas/lista.html', {'campanas': campanas})


@login_required
def crear(request):
    if request.method == 'POST':
        form = CampanaForm(request.POST)
        if form.is_valid():
            campana = form.save(commit=False)
            campana.creado_por = request.user
            if campana.fecha_programada:
                campana.estado = Campana.Estado.PROGRAMADA
            campana.save()
            form.save_m2m()
            return redirect('campanas:detalle', pk=campana.pk)
    else:
        form = CampanaForm()
    return render(request, 'campanas/form.html', {'form': form, 'titulo': 'Nueva campaña'})


@login_required
def detalle(request, pk):
    campana = get_object_or_404(Campana, pk=pk)
    destinatarios = campana.destinatarios_queryset()
    return render(request, 'campanas/detalle.html', {
        'campana': campana,
        'total_actual': destinatarios.count(),
        'envios': campana.envios.select_related('contacto')[:100],
    })


@login_required
@require_POST
def enviar_ahora(request, pk):
    campana = get_object_or_404(Campana, pk=pk)
    if campana.estado in (Campana.Estado.EN_EJECUCION, Campana.Estado.COMPLETADA):
        messages.error(request, 'La campaña ya fue ejecutada.')
    else:
        ejecutar_campana.delay(campana.id)
        messages.success(request, 'Campaña en cola de envío. Actualizá en unos segundos para ver el progreso.')
    return redirect('campanas:detalle', pk=pk)
