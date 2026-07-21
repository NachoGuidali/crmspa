from rest_framework.response import Response
from rest_framework.views import APIView

from apps.circuitos.models import Circuito
from apps.integraciones.mixins import ApiKeyLoggedView

from .serializers import DisponibilidadQuerySerializer, RangoDisponibilidadQuerySerializer
from .services import disponibilidad_circuito, disponibilidad_rango


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


class DisponibilidadRangoView(ApiKeyLoggedView, APIView):
    """GET /api/v1/disponibilidad/rango/?circuito_id=&desde=&hasta=&personas=
    Disponibilidad de varios días de una: para 'qué hay este mes' o sugerir alternativas."""

    MAX_DIAS = 62

    def get(self, request):
        serializer = RangoDisponibilidadQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        desde, hasta = data['desde'], data['hasta']

        if hasta < desde:
            return Response({'error': 'rango_invalido', 'detalle': 'hasta < desde'}, status=400)
        if (hasta - desde).days > self.MAX_DIAS:
            return Response({'error': 'rango_demasiado_grande', 'max_dias': self.MAX_DIAS}, status=400)

        try:
            circuito = Circuito.objects.get(pk=data['circuito_id'], activo=True)
        except Circuito.DoesNotExist:
            return Response({'error': 'circuito_not_found'}, status=404)

        dias = disponibilidad_rango(circuito, desde, hasta, data.get('personas'))
        return Response({
            'circuito_id': circuito.id,
            'circuito_nombre': circuito.nombre,
            'desde': desde.isoformat(),
            'hasta': hasta.isoformat(),
            'dias': dias,
        })
