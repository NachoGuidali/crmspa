from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import TareaForm
from .models import Tarea


@login_required
def lista(request):
    filtro = request.GET.get('filtro', 'mias')
    qs = Tarea.objects.select_related('contacto', 'asignado_a')
    if filtro == 'mias':
        qs = qs.filter(asignado_a=request.user)
    elif filtro == 'pendientes':
        qs = qs.exclude(estado=Tarea.Estado.COMPLETADA)
    return render(request, 'tareas/lista.html', {
        'tareas': qs, 'filtro': filtro, 'form': TareaForm(initial={'asignado_a': request.user}),
    })


@login_required
@require_POST
def crear(request):
    form = TareaForm(request.POST)
    if form.is_valid():
        form.save()
    return redirect('tareas:lista')


@login_required
@require_POST
def completar(request, pk):
    tarea = get_object_or_404(Tarea, pk=pk)
    tarea.estado = Tarea.Estado.COMPLETADA
    tarea.resultado = request.POST.get('resultado', '')
    tarea.save(update_fields=['estado', 'resultado'])
    return redirect('tareas:lista')
