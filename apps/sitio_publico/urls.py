from django.urls import path

from . import views

app_name = 'sitio_publico'

urlpatterns = [
    path('', views.vidriera, name='vidriera'),
    # 'reservar/<id>/' deshabilitada: creaba reservas reales sin auth/throttle/captcha, y no
    # la usa nada (la web real es estática + el bot de WhatsApp). Ver docs/qa-informe.md (A2).
]
