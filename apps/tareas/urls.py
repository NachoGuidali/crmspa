from django.urls import path

from . import views

app_name = 'tareas'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('crear/', views.crear, name='crear'),
    path('<int:pk>/completar/', views.completar, name='completar'),
]
