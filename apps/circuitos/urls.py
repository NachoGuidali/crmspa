from django.urls import path

from . import views

app_name = 'circuitos'

urlpatterns = [
    path('', views.CircuitoListView.as_view(), name='list'),
]
