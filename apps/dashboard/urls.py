from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('salud/', views.salud, name='salud'),
    path('caja/', views.caja, name='caja'),
    path('caja/export/', views.export_pagos, name='export_pagos'),
]
