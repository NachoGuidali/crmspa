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
from django.urls import include, path, re_path
from django.views.static import serve

from apps.sitio_publico.api import CircuitosPublicosView
from apps.turnero.views import TurneroCrudoView
from apps.whatsapp.views import (
    ConversacionDetalleView,
    ConversacionesView,
    ConversacionMensajeView,
)

urlpatterns = [
    path('admin/', admin.site.urls),

    path('api/v1/contactos/', include(('apps.contactos.urls', 'contactos'), namespace='contactos_api')),
    path('api/v1/circuitos/', include('apps.circuitos.urls')),
    path('api/v1/disponibilidad/', include(('apps.turnero.urls', 'turnero'), namespace='turnero_api')),
    path('api/v1/turnero/', TurneroCrudoView.as_view(), name='turnero_crudo'),
    path('api/v1/conversaciones/', ConversacionesView.as_view(), name='conversaciones'),
    path('api/v1/conversaciones/<str:telefono>/', ConversacionDetalleView.as_view(), name='conversacion_detalle'),
    path('api/v1/conversaciones/<str:telefono>/mensajes/', ConversacionMensajeView.as_view(), name='conversacion_mensajes'),
    path('api/v1/reservas/', include(('apps.reservas.urls', 'reservas'), namespace='reservas_api')),
    path('api/v1/vouchers/', include('apps.vouchers.urls_api')),
    path('api/v1/publico/circuitos/', CircuitosPublicosView.as_view(), name='publico_circuitos'),

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

    # Media protegido: los comprobantes de pago son sensibles, sólo staff autenticado.
    re_path(
        r'^media/(?P<path>.*)$',
        login_required(serve),
        {'document_root': settings.MEDIA_ROOT},
        name='media',
    ),
]
