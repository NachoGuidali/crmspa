from rest_framework.response import Response
from rest_framework.views import APIView

from apps.integraciones.mixins import ApiKeyLoggedView
from utils.phone import normalize_ar_phone

from .models import Contacto
from .serializers import (
    ContactoBuscarSerializer,
    ContactoCrearSerializer,
    ContactoSerializer,
)


class ContactoBuscarView(ApiKeyLoggedView, APIView):
    """GET /api/v1/contactos/buscar/?telefono=... — usado por n8n antes de crear una reserva."""

    def get(self, request):
        serializer = ContactoBuscarSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        telefono = normalize_ar_phone(serializer.validated_data['telefono'])

        contacto = Contacto.objects.filter(telefono=telefono).first()
        if not contacto:
            return Response({'found': False, 'telefono': telefono}, status=404)

        self._contacto_relacionado = contacto
        data = ContactoSerializer(contacto).data
        data['found'] = True
        return Response(data)


class ContactoCrearView(ApiKeyLoggedView, APIView):
    """POST /api/v1/contactos/ — crea el contacto o actualiza datos vacíos si el teléfono ya existe."""

    def post(self, request):
        serializer = ContactoCrearSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        telefono = normalize_ar_phone(data['telefono'])

        contacto, created = Contacto.objects.get_or_create(
            telefono=telefono,
            defaults={'nombre': data.get('nombre') or telefono, 'email': data.get('email', '')},
        )
        if not created:
            updated = False
            if data.get('nombre') and not contacto.nombre:
                contacto.nombre = data['nombre']
                updated = True
            if data.get('email') and not contacto.email:
                contacto.email = data['email']
                updated = True
            if updated:
                contacto.save()

        self._contacto_relacionado = contacto
        return Response(
            {
                'status': 'created' if created else 'updated',
                'contacto_id': contacto.id,
                'telefono': contacto.telefono,
            },
            status=201 if created else 200,
        )
