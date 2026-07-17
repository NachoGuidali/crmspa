from datetime import date

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.integraciones.mixins import ApiKeyLoggedView

from .models import Circuito
from .serializers import CircuitoSerializer


class CircuitoListView(ApiKeyLoggedView, APIView):
    """
    GET /api/v1/circuitos/?fecha=YYYY-MM-DD — circuitos activos, con precio y seña
    ya calculados para esa fecha (o hoy, si no se manda fecha).
    """

    def get(self, request):
        fecha_str = request.query_params.get('fecha')
        fecha = date.fromisoformat(fecha_str) if fecha_str else date.today()

        personas_str = request.query_params.get('personas')
        personas = int(personas_str) if personas_str and personas_str.isdigit() else None

        circuitos = Circuito.objects.filter(activo=True).prefetch_related('tarifas')
        data = CircuitoSerializer(
            circuitos, many=True, context={'fecha': fecha, 'personas': personas}
        ).data
        return Response({'fecha': fecha.isoformat(), 'personas': personas, 'circuitos': data})
