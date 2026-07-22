from django.urls import path

from . import views_ui

app_name = 'whatsapp'

urlpatterns = [
    path('', views_ui.inbox, name='inbox'),
    path('nuevo/', views_ui.nueva_conversacion, name='nueva_conversacion'),
    path('config/', views_ui.config_whatsapp, name='config'),
    path('config/qr/', views_ui.config_qr, name='config_qr'),
    path('config/estado/', views_ui.config_estado, name='config_estado'),
    path('config/logout/', views_ui.config_logout, name='config_logout'),
    path('accion/', views_ui.inbox_accion, name='accion'),
    path('kanban/', views_ui.kanban, name='kanban'),
    path('<int:pk>/mensajes/', views_ui.inbox_mensajes, name='mensajes'),
    path('<int:pk>/mover/', views_ui.kanban_move, name='mover'),
]
