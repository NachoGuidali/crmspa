from django.urls import path

from . import views

app_name = 'whatsapp'

urlpatterns = [
    path('webhook/evolution/', views.EvolutionWebhookView.as_view(), name='webhook_evolution'),
    path('api/enviar/', views.EnviarMensajeView.as_view(), name='enviar'),
    path('api/handoff/', views.HandoffView.as_view(), name='handoff'),
]
