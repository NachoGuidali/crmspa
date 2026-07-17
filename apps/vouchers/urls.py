from django.urls import path

from . import views

app_name = 'vouchers'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('nuevo/', views.crear, name='crear'),
    path('<int:pk>/', views.detalle, name='detalle'),
    path('<int:pk>/canjear/', views.canjear, name='canjear'),
    path('<int:pk>/anular/', views.anular, name='anular'),
]
