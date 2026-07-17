import json

from rest_framework.utils.encoders import JSONEncoder

from .authentication import ApiKeyAuthentication
from .models import WebhookLog
from .permissions import HasApiKey


class ApiKeyLoggedView:
    """
    Mixin para APIView: exige ApiKey válida y registra cada request en WebhookLog.
    Las subclases pueden setear `self._contacto_relacionado` durante el handler
    para que quede referenciado en el log.
    """

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        try:
            body = request.body.decode('utf-8') if request.body else ''
        except Exception:
            body = ''
        WebhookLog.objects.create(
            api_key=getattr(request, 'auth', None),
            endpoint=request.path,
            method=request.method,
            ip=request.META.get('REMOTE_ADDR'),
            request_body=body[:5000],
            response_status=response.status_code,
            response_body=json.dumps(response.data, cls=JSONEncoder)[:5000] if hasattr(response, 'data') else '',
            status=WebhookLog.Status.OK if response.status_code < 400 else WebhookLog.Status.ERROR,
            contacto=getattr(self, '_contacto_relacionado', None),
        )
        return response
