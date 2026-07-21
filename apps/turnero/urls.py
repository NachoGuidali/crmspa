from django.urls import path

from . import views

app_name = 'turnero'

urlpatterns = [
    path('', views.DisponibilidadView.as_view(), name='disponibilidad'),
    path('rango/', views.DisponibilidadRangoView.as_view(), name='disponibilidad_rango'),
]
