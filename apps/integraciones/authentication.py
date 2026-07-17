from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import ApiKey


class ApiKeyAuthentication(BaseAuthentication):
    """
    Autentica requests externos (n8n, formulario público) vía header X-Api-Key.
    request.auth queda con la instancia de ApiKey usada; request.user queda anónimo
    (no hay un usuario humano detrás de estas llamadas).
    """

    header_name = 'X-Api-Key'

    def authenticate(self, request):
        raw_key = request.headers.get(self.header_name)
        if not raw_key:
            return None

        try:
            api_key = ApiKey.objects.get(key=raw_key, activa=True)
        except (ApiKey.DoesNotExist, ValueError, TypeError):
            raise AuthenticationFailed('API key inválida o inactiva.')

        ApiKey.objects.filter(pk=api_key.pk).update(
            ultimo_uso_at=timezone.now(), total_usos=api_key.total_usos + 1
        )
        return (AnonymousUser(), api_key)

    def authenticate_header(self, request):
        return self.header_name
