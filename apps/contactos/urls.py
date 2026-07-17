from django.urls import path

from . import views

app_name = 'contactos'

urlpatterns = [
    path('buscar/', views.ContactoBuscarView.as_view(), name='buscar'),
    path('', views.ContactoCrearView.as_view(), name='crear'),
]
