from django.contrib.auth import views as auth_views
from django.urls import path

from .views import ThrottledLoginView

app_name = 'usuarios'

urlpatterns = [
    path('login/', ThrottledLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='usuarios:login'), name='logout'),
]
