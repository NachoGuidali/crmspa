import logging

from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.integraciones.mixins import ApiKeyLoggedView

from . import services, webhook
from .models import ConfiguracionWhatsApp, Conversacion, Mensaje
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


class ConversacionesView(ApiKeyLoggedView, APIView):
    """
    POST /api/v1/conversaciones/  — crea una conversación (primer mensaje de un número).
    GET  /api/v1/conversaciones/?inactiva_desde_horas=72&reserva_creada=false&estado_flujo_distinto_de=derivado
         — lista de conversaciones para seguimiento (devuelve {telefono, nombre_contacto}).
    """

    def post(self, request):
        from utils.phone import normalize_ar_phone

        telefono = request.data.get('telefono', '')
        if not telefono:
            return Response({'error': 'telefono_requerido'}, status=400)
        telefono = normalize_ar_phone(telefono)

        nombre = request.data.get('nombre', '') or ''
        estado_flujo = request.data.get('estado_flujo', 'nuevo') or 'nuevo'

        conv, creada = Conversacion.objects.get_or_create(
            telefono=telefono,
            defaults={'nombre_contacto': nombre, 'estado_bot': {'estado_flujo': estado_flujo}},
        )
        if not creada:
            # Ya existía: completamos nombre si faltaba, sin pisar el estado del flujo.
            campos = []
            if nombre and not conv.nombre_contacto:
                conv.nombre_contacto = nombre
                campos.append('nombre_contacto')
            if not conv.estado_bot.get('estado_flujo'):
                conv.estado_bot['estado_flujo'] = estado_flujo
                campos.append('estado_bot')
            if campos:
                conv.save(update_fields=campos)

        return Response(conv.estado_bot_publico(), status=201 if creada else 200)

    def get(self, request):
        qp = request.query_params
        qs = Conversacion.objects.filter(archivada=False)

        horas = qp.get('inactiva_desde_horas')
        if horas:
            try:
                limite = timezone.now() - timezone.timedelta(hours=int(horas))
            except (TypeError, ValueError):
                return Response({'error': 'inactiva_desde_horas_invalido'}, status=400)
            qs = qs.filter(ultimo_mensaje_at__lte=limite)

        reserva = qp.get('reserva_creada')
        if reserva is not None:
            quiere = reserva.lower() in ('true', '1', 'si', 'sí')
            # reserva_creada vive dentro del JSON; filtramos por el key.
            qs = qs.filter(estado_bot__reserva_creada=quiere) if quiere else qs.exclude(estado_bot__reserva_creada=True)

        distinto = qp.get('estado_flujo_distinto_de')
        if distinto:
            qs = qs.exclude(estado_bot__estado_flujo=distinto)

        data = [
            {'telefono': c.telefono, 'nombre_contacto': c.nombre_contacto}
            for c in qs.only('telefono', 'nombre_contacto')[:500]
        ]
        return Response(data)


class ConversacionDetalleView(ApiKeyLoggedView, APIView):
    """
    GET   /api/v1/conversaciones/<telefono>/ — estado del flujo (404 si no existe).
    PATCH /api/v1/conversaciones/<telefono>/ — actualiza parcialmente los campos del flujo.
    """

    def _get_conv(self, telefono):
        from utils.phone import normalize_ar_phone

        return Conversacion.objects.filter(telefono=normalize_ar_phone(telefono)).first()

    def get(self, request, telefono):
        conv = self._get_conv(telefono)
        if conv is None:
            return Response({'error': 'conversacion_no_encontrada'}, status=404)
        self._contacto_relacionado = conv.contacto
        return Response(conv.estado_bot_publico())

    def patch(self, request, telefono):
        conv = self._get_conv(telefono)
        if conv is None:
            return Response({'error': 'conversacion_no_encontrada'}, status=404)

        data = request.data if isinstance(request.data, dict) else {}
        estado = dict(conv.estado_bot or {})

        # Solo aceptamos los campos conocidos del flujo; el resto se ignora.
        for campo in Conversacion.CAMPOS_FLUJO:
            if campo in data:
                estado[campo] = data[campo]
        conv.estado_bot = estado

        # Efectos automáticos: si se derivó o ya reservó, el bot queda bloqueado.
        derivado = estado.get('estado_flujo') == Conversacion.ESTADO_FLUJO_DERIVADO
        reservo = bool(estado.get('reserva_creada'))
        if derivado or reservo:
            conv.bot_activo = False
            if derivado:
                conv.estado = Conversacion.Estado.REQUIERE_ATENCION_HUMANA
            elif reservo:
                conv.estado = Conversacion.Estado.RESERVA_CONFIRMADA

        # El bot puede pedir explícitamente (des)bloquear el bot.
        if 'bot_bloqueado' in data:
            conv.bot_activo = not bool(data['bot_bloqueado'])

        conv.save()
        self._contacto_relacionado = conv.contacto
        return Response(conv.estado_bot_publico())


class ConversacionMensajeView(ApiKeyLoggedView, APIView):
    """
    POST /api/v1/conversaciones/<telefono>/mensajes/ — guarda un mensaje entrante aunque el bot
    esté bloqueado, para que el staff lo vea en el inbox. Body: {"texto": "...", "de": "cliente"}.
    """

    def post(self, request, telefono):
        from utils.phone import normalize_ar_phone

        telefono = normalize_ar_phone(telefono)
        texto = request.data.get('texto', '')
        de = request.data.get('de', 'cliente')

        conv, _ = Conversacion.objects.get_or_create(telefono=telefono)
        direccion = Mensaje.Direccion.ENTRANTE if de == 'cliente' else Mensaje.Direccion.SALIENTE
        ahora = timezone.now()
        msg = Mensaje.objects.create(
            conversacion=conv,
            contacto=conv.contacto,
            direccion=direccion,
            tipo=Mensaje.Tipo.TEXTO,
            contenido=texto,
            status=Mensaje.Status.ENTREGADO,
            timestamp=ahora,
        )
        conv.ultimo_mensaje_at = ahora
        if direccion == Mensaje.Direccion.ENTRANTE:
            conv.mensajes_no_leidos = (conv.mensajes_no_leidos or 0) + 1
        conv.save(update_fields=['ultimo_mensaje_at', 'mensajes_no_leidos'])

        self._contacto_relacionado = conv.contacto
        return Response({'ok': True, 'mensaje_id': msg.id, 'conversacion_id': conv.id}, status=201)


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
