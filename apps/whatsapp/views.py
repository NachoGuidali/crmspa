import json
import logging

from django.http import HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.integraciones.mixins import ApiKeyLoggedView

from . import services, webhook, webhook_meta
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
        # Aceptamos el webhook_token configurado o la propia API key de Evolution
        # (algunas versiones mandan la instance key en el header).
        evo_key = ConfiguracionWhatsApp.get_setting('evolution_api_key')
        if not webhook.verify_webhook_token(token, configured) and not (evo_key and token == evo_key):
            return Response({'error': 'invalid_token'}, status=401)

        payload = request.data if isinstance(request.data, dict) else {}

        # El QR de vinculación llega por webhook: lo cacheamos para mostrarlo en Configuración.
        event = str(payload.get('event', '')).upper().replace('.', '_')
        if event == 'QRCODE_UPDATED':
            self._cachear_qr(payload)
            return Response({'ok': True})

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

    @staticmethod
    def _cachear_qr(payload):
        from django.core.cache import cache

        data = payload.get('data', {}) or {}
        qr = data.get('qrcode', data) or {}
        code = qr.get('code', '')
        b64 = qr.get('base64', '')
        if b64 and ',' in b64:
            b64 = b64.split(',', 1)[1]
        if code or b64:
            cache.set('whatsapp_qr_code', b64, timeout=55)
            cache.set('whatsapp_qr_text', code, timeout=55)
            logger.info('QR de WhatsApp cacheado desde webhook')


@method_decorator(csrf_exempt, name='dispatch')
class MetaWebhookView(View):
    """
    Webhook de WhatsApp Cloud API (Meta).
    - GET: handshake de verificación al suscribir el webhook (hub.challenge).
    - POST: mensajes entrantes, validados con la firma X-Hub-Signature-256.
    Usa la firma cruda de request.body (por eso es una View de Django, no DRF).
    """

    def get(self, request):
        mode = request.GET.get('hub.mode', '')
        token = request.GET.get('hub.verify_token', '')
        challenge = request.GET.get('hub.challenge', '')
        configured = ConfiguracionWhatsApp.get_setting('meta_verify_token')
        if webhook_meta.verify_webhook_get(mode, token, configured):
            return HttpResponse(challenge, status=200)
        return HttpResponse('Forbidden', status=403)

    def post(self, request):
        app_secret = ConfiguracionWhatsApp.get_setting('meta_app_secret')
        signature = request.headers.get('X-Hub-Signature-256', '')
        if app_secret and not webhook_meta.verify_signature(request.body, signature, app_secret):
            logger.warning('Webhook Meta rechazado — firma inválida')
            return HttpResponse('Forbidden', status=403)
        try:
            payload = json.loads(request.body or '{}')
        except (ValueError, TypeError):
            return HttpResponse('OK', status=200)

        for procesado in services.procesar_webhook_entrante(payload, origen='meta'):
            forward_to_n8n.delay(procesado)
        return HttpResponse('OK', status=200)


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
        except services.FueraDeVentanaError as exc:
            # Meta: pasó la ventana de 24hs → n8n debe mandar una plantilla (/api/enviar-plantilla/).
            return Response({'ok': False, 'error': 'fuera_de_ventana_24h', 'detalle': str(exc)}, status=409)
        except services.EnvioError as exc:
            return Response({'ok': False, 'error': 'envio_error', 'detalle': str(exc)}, status=502)

        return Response(resultado)


class EnviarPlantillaView(ApiKeyLoggedView, APIView):
    """POST /whatsapp/api/enviar-plantilla/ — manda una plantilla (para iniciar conversación fuera
    de la ventana de 24hs en Meta, ej. recordatorios).
    Body: {"telefono": "...", "plantilla": <id o meta_nombre>, "valores": ["Ana", "25/07 mañana"]}."""

    def post(self, request):
        from .models import PlantillaMensaje

        data = request.data
        telefono = data.get('telefono') or data.get('phone')
        if not telefono:
            return Response({'error': 'telefono_requerido'}, status=400)

        ident = data.get('plantilla') or data.get('template')
        if not ident:
            return Response({'error': 'plantilla_requerida'}, status=400)

        plantilla = None
        if str(ident).isdigit():
            plantilla = PlantillaMensaje.objects.filter(pk=int(ident)).first()
        if plantilla is None:
            plantilla = (
                PlantillaMensaje.objects.filter(meta_nombre=ident).first()
                or PlantillaMensaje.objects.filter(nombre=ident).first()
            )
        if plantilla is None:
            return Response({'error': 'plantilla_no_encontrada'}, status=404)

        try:
            resultado = services.enviar_plantilla(
                telefono=telefono, plantilla=plantilla, valores=data.get('valores') or [],
            )
        except services.EnvioError as exc:
            return Response({'ok': False, 'error': 'envio_error', 'detalle': str(exc)}, status=502)

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
