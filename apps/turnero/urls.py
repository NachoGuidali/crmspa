from django.urls import path

from . import views

app_name = 'turnero'

urlpatterns = [
    path('', views.DisponibilidadView.as_view(), name='disponibilidad'),
]
