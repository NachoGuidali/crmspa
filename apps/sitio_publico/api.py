"""API pública (sin autenticación) para que la web visible (spacuatroestaciones.com)
lea precios y circuitos directamente del CRM. Así, cambiar un precio en el CRM se refleja
en la web sin tocar código."""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.circuitos.models import Circuito


def _num(v):
    return float(v) if v is not None else None


class CircuitosPublicosView(APIView):
    """GET /api/v1/publico/circuitos/ — circuitos activos con sus precios, para la web."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        data = []
        for c in Circuito.objects.filter(activo=True).prefetch_related('tarifas').order_by('nombre'):
            tramos = list(c.tarifas.order_by('min_personas'))
            item = {
                'id': c.id,
                'nombre': c.nombre,
                'tipo': c.tipo,
                'duracion_minutos': c.duracion_minutos,
                'capacidad_minima': c.capacidad_minima,
                'capacidad_maxima': c.capacidad_maxima,
                'sena_tipo': c.sena_tipo,
                'sena_valor': _num(c.sena_valor),
                'por_persona': bool(tramos),
            }
            if tramos:
                # Grupales: precio POR PERSONA por tramo (semana = Lun-Jue, finde = Vie-Sáb-Dom)
                item['tramos'] = [{
                    'desde': t.min_personas, 'hasta': t.max_personas,
                    'precio_persona_semana': _num(t.precio_persona_semana),
                    'precio_persona_finde': _num(t.precio_persona_finde),
                } for t in tramos]
                item['precio_persona_adicional_semana'] = _num(c.precio_persona_adicional_semana)
                item['precio_persona_adicional_finde'] = _num(c.precio_persona_adicional_finde)
                item['precio_desde'] = min(_num(t.precio_persona_semana) for t in tramos)
            else:
                # Parejas: precio total del circuito
                item['precio_total_semana'] = _num(c.precio_semana)
                item['precio_total_finde'] = _num(c.precio_finde)
                item['precio_desde'] = _num(c.precio_semana)
            data.append(item)

        return Response({'circuitos': data})
