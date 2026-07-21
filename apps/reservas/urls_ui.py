from django.urls import path

from . import views_ui

app_name = 'reservas'

urlpatterns = [
    path('', views_ui.kanban, name='kanban'),
    path('nueva/', views_ui.nueva_reserva, name='nueva'),
    path('lista-espera/', views_ui.lista_espera, name='lista_espera'),
    path('lista-espera/<int:pk>/quitar/', views_ui.quitar_espera, name='quitar_espera'),
    path('<int:pk>/', views_ui.detalle, name='detalle'),
    path('<int:pk>/reprogramar/', views_ui.reprogramar, name='reprogramar'),
    path('<int:pk>/cancelar/', views_ui.cancelar, name='cancelar'),
    path('<int:pk>/aprobar/', views_ui.aprobar, name='aprobar'),
    path('<int:pk>/asistio/', views_ui.marcar_asistio, name='asistio'),
    path('<int:pk>/no-show/', views_ui.marcar_no_show, name='no_show'),
    path('<int:pk>/comprobante/', views_ui.comprobante, name='comprobante'),
    path('<int:pk>/extra/', views_ui.agregar_extra, name='agregar_extra'),
    path('<int:pk>/extra/<int:extra_id>/quitar/', views_ui.quitar_extra, name='quitar_extra'),
    path('<int:pk>/mover/', views_ui.kanban_move, name='mover'),
]
