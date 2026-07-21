from rest_framework.response import Response
from rest_framework.views import APIView

from apps.circuitos.models import Circuito
from apps.integraciones.mixins import ApiKeyLoggedView

from .serializers import DisponibilidadQuerySerializer, RangoDisponibilidadQuerySerializer
from .services import disponibilidad_circuito, disponibilidad_rango, turnero_crudo


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


class TurneroCrudoView(ApiKeyLoggedView, APIView):
    """GET /api/v1/turnero/?desde=YYYY-MM-DD&dias=N — ocupación cruda por (fecha, turno)
    para todo el spa, sin reglas de negocio ni circuito. El bot la usa como vista simple del
    turnero; toda la lógica de cupo/precio vive en el CRM."""

    MAX_DIAS = 62

    def get(self, request):
        from datetime import date

        desde_raw = request.query_params.get('desde')
        try:
            desde = date.fromisoformat(desde_raw) if desde_raw else date.today()
        except ValueError:
            return Response({'error': 'desde_invalido', 'detalle': 'formato YYYY-MM-DD'}, status=400)

        try:
            dias = int(request.query_params.get('dias', 14))
        except (TypeError, ValueError):
            return Response({'error': 'dias_invalido'}, status=400)
        if dias < 1:
            return Response({'error': 'dias_invalido', 'detalle': 'dias >= 1'}, status=400)
        dias = min(dias, self.MAX_DIAS)

        return Response({
            'desde': desde.isoformat(),
            'dias': dias,
            'turnero': turnero_crudo(desde, dias),
        })


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
