from django.shortcuts import render
from django.utils import timezone

from apps.circuitos.models import Circuito


def vidriera(request):
    hoy = timezone.localdate()
    circuitos = list(Circuito.objects.filter(activo=True))
    for c in circuitos:
        c.precio_hoy = c.precio_para_fecha(hoy)
        c.sena_hoy = c.monto_sena_para(hoy)
    # El WhatsApp sale de la configuración, igual que en la web pública.
    from utils.phone import normalize_ar_phone

    from apps.configuracion.models import ConfiguracionNegocio

    crudo = (ConfiguracionNegocio.get_solo().telefono_whatsapp or '').strip()
    return render(request, 'sitio_publico/vidriera.html', {
        'circuitos': circuitos,
        'whatsapp_web': normalize_ar_phone(crudo).lstrip('+') if crudo else '',
    })
