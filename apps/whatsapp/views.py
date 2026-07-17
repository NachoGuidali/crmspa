import logging

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.integraciones.mixins import ApiKeyLoggedView

from . import services, webhook
from .models import ConfiguracionWhatsApp
from .serializers import EnviarMensajeSerializer, HandoffSerializer
from .tasks import forward_to_n8n

logger = logging.getLogger('apps.whatsapp')


class EvolutionWebhookView(APIView):
    """
    POST /whatsapp/webhook/evolution/ — recibe los eventos crudos de Evolution API.
    Autenticado por token fijo (header 'apikey'), no por ApiKey de integraciones
    (Evolution API no soporta headers custom por request de forma configurable).
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = 'webhook'

    def post(self, request):
        token = request.headers.get('apikey', '')
        configured = ConfiguracionWhatsApp.get_setting('webhook_token')
        if not webhook.verify_webhook_token(token, configured):
            return Response({'error': 'invalid_token'}, status=401)

        payload = request.data if isinstance(request.data, dict) else {}
        procesados = services.procesar_webhook_entrante(payload)

        for extra in procesados:
            enriched = {
                **payload,
                'phone': extra['phone'],
                'message': extra['message'],
                'contact_name': extra['contact_name'],
                'bot_n8n_activo': extra['bot_n8n_activo'],
                'conversacion_id': extra['conversacion_id'],
                'fuera_de_horario': extra['fuera_de_horario'],
            }
            forward_to_n8n.delay(enriched)

        return Response({'ok': True, 'procesados': len(procesados)})


class EnviarMensajeView(ApiKeyLoggedView, APIView):
    """POST /whatsapp/api/enviar/ — único endpoint permitido para que n8n mande mensajes salientes."""

    def post(self, request):
        serializer = EnviarMensajeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            resultado = services.enviar_mensaje(
                telefono=data['phone'],
                mensaje=data['message'],
                media_url=data['media_url'],
                media_type=data['media_type'],
            )
        except services.EnvioError as exc:
            return Response({'ok': False, 'error': 'evolution_api_error', 'detalle': str(exc)}, status=502)

        return Response(resultado)


class HandoffView(ApiKeyLoggedView, APIView):
    """POST /whatsapp/api/handoff/ — el bot deriva la conversación a un agente humano."""

    def post(self, request):
        serializer = HandoffSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            resultado = services.handoff(telefono=data['telefono'], agente_id=data['agente_id'])
        except services.HandoffError:
            return Response({'error': 'conversation_not_found'}, status=404)

        return Response(resultado)
