from datetime import date

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.integraciones.mixins import ApiKeyLoggedView

from .models import Circuito, Extra
from .serializers import CircuitoSerializer, ExtraSerializer


class CircuitoListView(ApiKeyLoggedView, APIView):
    """
    GET /api/v1/circuitos/?fecha=YYYY-MM-DD — circuitos activos, con precio y seña
    ya calculados para esa fecha (o hoy, si no se manda fecha).
    """

    def get(self, request):
        fecha_str = request.query_params.get('fecha')
        fecha = date.fromisoformat(fecha_str) if fecha_str else timezone.localdate()

        personas_str = request.query_params.get('personas')
        personas = int(personas_str) if personas_str and personas_str.isdigit() else None

        circuitos = Circuito.objects.filter(activo=True).prefetch_related('tarifas')
        data = CircuitoSerializer(
            circuitos, many=True, context={'fecha': fecha, 'personas': personas}
        ).data

        # Por qué el precio es el que es: tarifa del día y, si aplica, el recargo por feriado.
        # Va a nivel de la fecha y no de cada circuito porque es la misma para todos.
        from apps.configuracion.models import ConfiguracionNegocio
        from apps.turnero.services import info_tarifa

        # `recargo_porcentaje` (dentro de info_tarifa) es el de ESTA fecha: 0 si no es feriado.
        # `recargo_feriado_general` es la política del negocio, siempre. Con ese puede contestar
        # "los feriados tienen 10% de recargo" sin que el cliente haya dicho ninguna fecha.
        config = ConfiguracionNegocio.get_solo()

        return Response({
            'fecha': fecha.isoformat(),
            'personas': personas,
            **info_tarifa(fecha),
            'recargo_feriado_general': float(config.recargo_feriado_porcentaje or 0),
            'dias_tarifa_finde': config.dias_tarifa_finde or [5, 6],
            'circuitos': data,
        })


class ExtraListView(ApiKeyLoggedView, APIView):
    """
    GET /api/v1/extras/?circuito_id=1 — catálogo de extras/opcionales activos (ej. "Menú sin
    TACC"), con su precio. Sin `circuito_id`, devuelve los globales (aplican a todos los
    circuitos) + los específicos de cada circuito. Con `circuito_id`, devuelve los globales +
    los propios de ese circuito. El bot los usa para sumar el precio de los extras pedidos y
    pasarlos como `extras` en `POST /reservas/bot/`.
    """

    def get(self, request):
        from django.db.models import Q

        circuito_id = request.query_params.get('circuito_id')
        qs = Extra.objects.filter(activo=True).select_related('circuito')

        if circuito_id:
            try:
                circuito_id = int(circuito_id)
            except ValueError:
                return Response({'error': 'circuito_id_invalido'}, status=400)
            qs = qs.filter(Q(circuito__isnull=True) | Q(circuito_id=circuito_id))

        data = ExtraSerializer(qs, many=True).data
        return Response({'extras': data})
