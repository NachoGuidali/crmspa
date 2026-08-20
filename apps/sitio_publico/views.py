from django.shortcuts import render
from django.utils import timezone

from apps.circuitos.models import Circuito


def vidriera(request):
    hoy = timezone.localdate()
    circuitos = list(Circuito.objects.filter(activo=True))
    for c in circuitos:
        c.precio_hoy = c.precio_para_fecha(hoy)
        c.sena_hoy = c.monto_sena_para(hoy)
    return render(request, 'sitio_publico/vidriera.html', {'circuitos': circuitos})
