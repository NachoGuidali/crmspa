from django.urls import path

from . import views

app_name = 'reservas'

urlpatterns = [
    path('', views.ReservaCrearView.as_view(), name='crear'),
    path('bot/', views.ReservaBotCrearView.as_view(), name='crear_bot'),
    path('confirmar-pago/', views.ReservaConfirmarPagoView.as_view(), name='confirmar_pago'),
    path('agenda/', views.ReservasAgendaView.as_view(), name='agenda'),
    path('por-telefono/', views.ReservasPorContactoView.as_view(), name='por_telefono'),
    path('<int:pk>/', views.ReservaDetalleView.as_view(), name='detalle'),
    path('<int:pk>/confirmar-sena/', views.ReservaConfirmarSenaView.as_view(), name='confirmar_sena'),
    path('<int:pk>/cancelar/', views.ReservaCancelarView.as_view(), name='cancelar'),
    path('<int:pk>/reprogramar/', views.ReservaReprogramarView.as_view(), name='reprogramar'),
]
