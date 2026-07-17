from django.urls import path

from . import views_ui

app_name = 'contactos'

urlpatterns = [
    path('', views_ui.lista, name='lista'),
    path('export/', views_ui.export_csv, name='export_csv'),
    path('<int:pk>/', views_ui.detalle, name='detalle'),
    path('<int:pk>/editar/', views_ui.editar, name='editar'),
    path('<int:pk>/nota/', views_ui.agregar_nota, name='agregar_nota'),
    path('reserva/<int:reserva_id>/pago/', views_ui.registrar_pago, name='registrar_pago'),
]
