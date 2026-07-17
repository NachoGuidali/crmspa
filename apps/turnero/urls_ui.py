from django.urls import path

from . import views_ui

app_name = 'turnero'

urlpatterns = [
    path('', views_ui.calendario, name='calendario'),
    path('hoy/', views_ui.hoy, name='hoy'),
    path('dia/<str:fecha_iso>/', views_ui.dia, name='dia'),
]
