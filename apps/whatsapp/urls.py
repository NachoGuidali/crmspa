from django.urls import path

from . import views

app_name = 'whatsapp'

urlpatterns = [
    path('webhook/evolution/', views.EvolutionWebhookView.as_view(), name='webhook_evolution'),
    path('webhook/meta/', views.MetaWebhookView.as_view(), name='webhook_meta'),
    path('api/enviar/', views.EnviarMensajeView.as_view(), name='enviar'),
    path('api/enviar-plantilla/', views.EnviarPlantillaView.as_view(), name='enviar_plantilla'),
    path('api/handoff/', views.HandoffView.as_view(), name='handoff'),
]
