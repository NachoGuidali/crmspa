from rest_framework.response import Response
from rest_framework.views import APIView

from apps.circuitos.models import Circuito
from apps.integraciones.mixins import ApiKeyLoggedView

from .serializers import DisponibilidadQuerySerializer
from .services import disponibilidad_circuito


class DisponibilidadView(ApiKeyLoggedView, APIView):
    """GET /api/v1/disponibilidad/?circuito_id=&fecha=YYYY-MM-DD — la usa n8n para ofrecer horarios."""

    def get(self, request):
        serializer = DisponibilidadQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            circuito = Circuito.objects.get(pk=data['circuito_id'], activo=True)
        except Circuito.DoesNotExist:
            return Response({'error': 'circuito_not_found'}, status=404)

        resultado = disponibilidad_circuito(circuito, data['fecha'])
        resultado['circuito_id'] = circuito.id
        resultado['circuito_nombre'] = circuito.nombre
        return Response(resultado)
