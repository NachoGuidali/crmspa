from datetime import date

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.integraciones.mixins import ApiKeyLoggedView

from . import services


class VoucherValidarView(ApiKeyLoggedView, APIView):
    """GET /api/v1/vouchers/<codigo>/ — n8n valida un voucher que menciona el cliente."""

    def get(self, request, codigo):
        try:
            voucher = services.validar(codigo)
        except services.VoucherError as e:
            return Response({'valido': False, 'motivo': str(e)}, status=404)
        return Response({
            'valido': True,
            'codigo': voucher.codigo,
            'circuito_id': voucher.circuito_id,
            'circuito': voucher.circuito.nombre,
            'monto': voucher.monto,
            'vence': voucher.fecha_vencimiento.isoformat(),
        })


class VoucherCanjearView(ApiKeyLoggedView, APIView):
    """POST /api/v1/vouchers/canjear/ — n8n canjea el voucher creando la reserva confirmada."""

    def post(self, request):
        data = request.data
        try:
            reserva, voucher = services.canjear(
                data['codigo'],
                telefono=data['telefono'],
                nombre_contacto=data.get('nombre_contacto', ''),
                turno_id=data['turno_id'],
                fecha=date.fromisoformat(data['fecha']),
                cantidad_personas=int(data.get('cantidad_personas', 1)),
            )
        except services.VoucherError as e:
            return Response({'ok': False, 'error': str(e)}, status=422)
        except Exception as e:
            return Response({'ok': False, 'error': str(e)}, status=422)

        self._contacto_relacionado = reserva.contacto
        return Response({'ok': True, 'reserva_id': reserva.id, 'estado': reserva.estado, 'codigo': voucher.codigo})
