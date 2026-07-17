from rest_framework.permissions import BasePermission


class HasApiKey(BasePermission):
    """Permite el acceso solo si ApiKeyAuthentication autenticó una ApiKey válida."""

    message = 'Falta un header X-Api-Key válido.'

    def has_permission(self, request, view):
        return bool(getattr(request, 'auth', None))
