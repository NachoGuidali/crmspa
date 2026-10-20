from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('salud/', views.salud, name='salud'),
    path('caja/', views.caja, name='caja'),
    path('caja/export/', views.export_pagos, name='export_pagos'),
    path('comprobantes/', views.comprobantes, name='comprobantes'),
    path('comprobantes/export/', views.export_comprobantes_csv, name='export_comprobantes_csv'),
    path('comprobantes/zip/', views.export_comprobantes_zip, name='export_comprobantes_zip'),
]
