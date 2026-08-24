"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.static import serve


def robots_txt(_request):
    """robots.txt del CRM.

    A propósito NO lleva `Disallow: /`. Lo que mantiene al CRM fuera de Google es el header
    `X-Robots-Tag: noindex` que pone `utils.middleware.NoIndexMiddleware`, y para verlo Google
    necesita poder leer las páginas. Un `Disallow` le taparía los ojos: no vería el noindex y
    podría listar la URL igual, sin descripción, si alguien la enlaza.
    """
    contenido = (
        '# CRM interno de Estancia Cuatro Estaciones — nada de acá va a los buscadores.\n'
        '# El noindex real lo pone el header X-Robots-Tag en cada respuesta; acá no se\n'
        '# bloquea el rastreo para que Google pueda leerlo. La web pública está en\n'
        '# https://spacuatroestaciones.com/robots.txt\n'
        'User-agent: *\n'
        'Allow: /\n'
    )
    return HttpResponse(contenido, content_type='text/plain; charset=utf-8')

from apps.circuitos.views import ExtraListView
from apps.sitio_publico.api import CircuitosPublicosView, PopupPublicoView
from apps.turnero.views import TurneroCrudoView
from apps.whatsapp.views import (
    ConversacionDetalleView,
    ConversacionesView,
    ConversacionMensajeView,
)

urlpatterns = [
    path('robots.txt', robots_txt, name='robots_txt'),
    path('admin/', admin.site.urls),

    path('api/v1/contactos/', include(('apps.contactos.urls', 'contactos'), namespace='contactos_api')),
    path('api/v1/circuitos/', include('apps.circuitos.urls')),
    path('api/v1/extras/', ExtraListView.as_view(), name='extras'),
    path('api/v1/disponibilidad/', include(('apps.turnero.urls', 'turnero'), namespace='turnero_api')),
    path('api/v1/turnero/', TurneroCrudoView.as_view(), name='turnero_crudo'),
    path('api/v1/conversaciones/', ConversacionesView.as_view(), name='conversaciones'),
    path('api/v1/conversaciones/<str:telefono>/', ConversacionDetalleView.as_view(), name='conversacion_detalle'),
    path('api/v1/conversaciones/<str:telefono>/mensajes/', ConversacionMensajeView.as_view(), name='conversacion_mensajes'),
    path('api/v1/reservas/', include(('apps.reservas.urls', 'reservas'), namespace='reservas_api')),
    path('api/v1/vouchers/', include('apps.vouchers.urls_api')),
    path('api/v1/publico/circuitos/', CircuitosPublicosView.as_view(), name='publico_circuitos'),
    path('api/v1/publico/popup/', PopupPublicoView.as_view(), name='publico_popup'),

    path('whatsapp/', include(('apps.whatsapp.urls', 'whatsapp'), namespace='whatsapp_api')),

    path('usuarios/', include('apps.usuarios.urls')),
    path('inbox/', include('apps.whatsapp.urls_ui')),
    path('reservas/', include('apps.reservas.urls_ui')),
    path('turnero/', include('apps.turnero.urls_ui')),
    path('sitio/', include('apps.sitio_publico.urls')),
    path('contactos/', include('apps.contactos.urls_ui')),
    path('configuracion/', include('apps.configuracion.urls')),
    path('campanas/', include('apps.campanas.urls')),
    path('vouchers/', include('apps.vouchers.urls')),
    path('tareas/', include('apps.tareas.urls')),
    path('', include('apps.dashboard.urls')),

    # Media PÚBLICO: lo que la web de spacuatroestaciones.com tiene que poder mostrar sin
    # login (hoy, las fotos de los popups). Va ANTES de la regla protegida para ganarle el
    # match. Todo lo que se suba acá es visible para cualquiera: nada sensible.
    re_path(
        r'^media/publico/(?P<path>.*)$',
        serve,
        {'document_root': settings.MEDIA_ROOT / 'publico'},
        name='media_publico',
    ),
    # Media protegido: los comprobantes de pago son sensibles, sólo staff autenticado.
    re_path(
        r'^media/(?P<path>.*)$',
        login_required(serve),
        {'document_root': settings.MEDIA_ROOT},
        name='media',
    ),
]
