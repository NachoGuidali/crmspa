from rest_framework.response import Response
from rest_framework.views import APIView

from apps.integraciones.mixins import ApiKeyLoggedView

from . import services
from .models import Reserva
from .serializers import (
    CancelarReservaSerializer,
    ConfirmarSenaSerializer,
    ReprogramarReservaSerializer,
    ReservaCrearSerializer,
    ReservaSerializer,
)


class ReservaCrearView(ApiKeyLoggedView, APIView):
    """POST /api/v1/reservas/ — crea la reserva. Valida cupo y calcula la seña en el backend."""

    def post(self, request):
        serializer = ReservaCrearSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            reserva = services.crear_reserva(**data)
        except services.ReservaError as e:
            return Response({'error': str(e)}, status=422)

        self._contacto_relacionado = reserva.contacto
        return Response(ReservaSerializer(reserva).data, status=201)


class ReservaDetalleView(ApiKeyLoggedView, APIView):
    """GET /api/v1/reservas/<id>/ — estado de una reserva puntual."""

    def get(self, request, pk):
        try:
            reserva = Reserva.objects.get(pk=pk)
        except Reserva.DoesNotExist:
            return Response({'error': 'reserva_not_found'}, status=404)
        self._contacto_relacionado = reserva.contacto
        return Response(ReservaSerializer(reserva).data)


class ReservaConfirmarSenaView(ApiKeyLoggedView, APIView):
    """POST /api/v1/reservas/<id>/confirmar-sena/ — registra el pago de seña y confirma la reserva."""

    def post(self, request, pk):
        try:
            reserva = Reserva.objects.get(pk=pk)
        except Reserva.DoesNotExist:
            return Response({'error': 'reserva_not_found'}, status=404)

        serializer = ConfirmarSenaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reserva = services.confirmar_sena(reserva, **serializer.validated_data)

        self._contacto_relacionado = reserva.contacto
        return Response(ReservaSerializer(reserva).data)


class ReservaCancelarView(ApiKeyLoggedView, APIView):
    """POST /api/v1/reservas/<id>/cancelar/ — cancela y libera el cupo."""

    def post(self, request, pk):
        try:
            reserva = Reserva.objects.get(pk=pk)
        except Reserva.DoesNotExist:
            return Response({'error': 'reserva_not_found'}, status=404)

        serializer = CancelarReservaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reserva = services.cancelar_reserva(reserva, **serializer.validated_data)

        self._contacto_relacionado = reserva.contacto
        return Response(ReservaSerializer(reserva).data)


class ReservaReprogramarView(ApiKeyLoggedView, APIView):
    """POST /api/v1/reservas/<id>/reprogramar/ — mueve la reserva a otra fecha/turno.
    Conserva la seña ya pagada y libera el cupo anterior."""

    def post(self, request, pk):
        try:
            reserva = Reserva.objects.get(pk=pk)
        except Reserva.DoesNotExist:
            return Response({'error': 'reserva_not_found'}, status=404)

        serializer = ReprogramarReservaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            reserva = services.reprogramar_reserva(
                reserva, nueva_fecha=data['fecha'], nuevo_turno_id=data['turno_id']
            )
        except services.ReservaError as e:
            return Response({'error': str(e)}, status=422)

        self._contacto_relacionado = reserva.contacto
        return Response(ReservaSerializer(reserva).data)


class ReservasPorContactoView(ApiKeyLoggedView, APIView):
    """GET /api/v1/reservas/por-telefono/?telefono=... — historial/estado de turnos de un contacto."""

    def get(self, request):
        from utils.phone import normalize_ar_phone

        telefono = request.query_params.get('telefono', '')
        if not telefono:
            return Response({'error': 'telefono_requerido'}, status=400)
        telefono = normalize_ar_phone(telefono)

        reservas = Reserva.objects.filter(contacto__telefono=telefono).order_by('-fecha')
        return Response(ReservaSerializer(reservas, many=True).data)
