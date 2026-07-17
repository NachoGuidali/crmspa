from django.urls import path

from . import views

app_name = 'campanas'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('nueva/', views.crear, name='crear'),
    path('<int:pk>/', views.detalle, name='detalle'),
    path('<int:pk>/enviar/', views.enviar_ahora, name='enviar'),
]
