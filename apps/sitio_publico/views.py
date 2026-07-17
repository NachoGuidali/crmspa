from datetime import date

from django.shortcuts import get_object_or_404, render

from apps.circuitos.models import Circuito
from apps.reservas import services
from apps.turnero.models import Turno


def vidriera(request):
    hoy = date.today()
    circuitos = list(Circuito.objects.filter(activo=True))
    for c in circuitos:
        c.precio_hoy = c.precio_para_fecha(hoy)
        c.sena_hoy = c.monto_sena_para(hoy)
    return render(request, 'sitio_publico/vidriera.html', {'circuitos': circuitos})


def reservar(request, circuito_id):
    circuito = get_object_or_404(Circuito, pk=circuito_id, activo=True)
    turnos = Turno.objects.filter(activo=True)

    if request.method == 'POST':
        try:
            reserva = services.crear_reserva(
                telefono=request.POST['telefono'],
                nombre_contacto=request.POST.get('nombre_contacto', ''),
                circuito_id=circuito.id,
                turno_id=request.POST['turno_id'],
                fecha=date.fromisoformat(request.POST['fecha']),
                cantidad_personas=int(request.POST.get('cantidad_personas', 1)),
            )
        except services.ReservaError as e:
            return render(request, 'sitio_publico/reservar.html', {
                'circuito': circuito, 'turnos': turnos, 'error': str(e),
            })
        return render(request, 'sitio_publico/confirmacion.html', {'reserva': reserva})

    return render(request, 'sitio_publico/reservar.html', {'circuito': circuito, 'turnos': turnos})
