from django.urls import path

from . import views

app_name = 'sitio_publico'

urlpatterns = [
    path('', views.vidriera, name='vidriera'),
    path('reservar/<int:circuito_id>/', views.reservar, name='reservar'),
]
