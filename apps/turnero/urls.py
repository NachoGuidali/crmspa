from django.urls import path

from . import views

app_name = 'turnero'

urlpatterns = [
    path('', views.DisponibilidadView.as_view(), name='disponibilidad'),
    path('rango/', views.DisponibilidadRangoView.as_view(), name='disponibilidad_rango'),
    # Los feriados que vienen: el bot los necesita para entender "el finde largo".
    path('feriados/', views.FeriadosView.as_view(), name='feriados'),
]
