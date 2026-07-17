from django.urls import path

from . import views_ui

app_name = 'whatsapp'

urlpatterns = [
    path('', views_ui.inbox, name='inbox'),
    path('accion/', views_ui.inbox_accion, name='accion'),
    path('kanban/', views_ui.kanban, name='kanban'),
    path('<int:pk>/mensajes/', views_ui.inbox_mensajes, name='mensajes'),
    path('<int:pk>/mover/', views_ui.kanban_move, name='mover'),
]
