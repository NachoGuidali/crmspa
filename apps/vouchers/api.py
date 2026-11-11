"""Endpoints de vouchers para el bot de WhatsApp (n8n).

El bot arma el voucher, le pasa el alias, recibe el comprobante y avisa al equipo. El voucher
recién vale cuando una persona del spa aprueba la transferencia desde el CRM: hasta entonces
`validar` lo rechaza y el canje no se puede hacer.
"""
import base64
import binascii
from datetime import date

from django.core.files.base import ContentFile
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.circuitos.models import Circuito
from apps.integraciones.mixins import ApiKeyLoggedView

from . import services
from .models import Voucher

# Mismo límite que el comprobante de una reserva.
COMPROBANTE_MAX_BYTES = 8 * 1024 * 1024


def _datos(voucher):
    return {
        'codigo': voucher.codigo,
        'estado': voucher.estado,
        'circuito_id': voucher.circuito_id,
        'circuito': voucher.circuito.nombre,
        'personas': voucher.personas,
        'monto': voucher.monto,
        'vence': voucher.fecha_vencimiento.isoformat(),
        'comprador': voucher.comprador_nombre,
        'destinatario': voucher.destinatario_nombre,
    }


class VoucherCrearView(ApiKeyLoggedView, APIView):
    """POST /api/v1/vouchers/ — el bot arma un voucher de regalo, todavía sin pagar.

    Body: {"telefono", "comprador_nombre", "circuito_id", "personas",
           "destinatario_nombre"?, "mensaje_regalo"?, "email"?}
    Devuelve el código y el monto a transferir. El voucher queda en `pendiente_pago`: no
    sirve para canjear hasta que alguien del spa apruebe el comprobante.
    """

    def post(self, request):
        data = request.data
        try:
            circuito = Circuito.objects.get(pk=int(data['circuito_id']))
        except (Circuito.DoesNotExist, KeyError, TypeError, ValueError):
            return Response({'ok': False, 'error': 'circuito_no_encontrado'}, status=422)

        try:
            voucher = services.crear(
                circuito=circuito,
                personas=data.get('personas') or circuito.capacidad_minima,
                comprador_nombre=data.get('comprador_nombre') or data.get('nombre_contacto') or '',
                comprador_telefono=data.get('telefono') or '',
                comprador_email=data.get('email') or '',
                destinatario_nombre=data.get('destinatario_nombre') or '',
                mensaje_regalo=data.get('mensaje_regalo') or '',
                origen=Voucher.Origen.WHATSAPP_BOT,
                estado=Voucher.Estado.PENDIENTE_PAGO,
                medio_pago='transferencia',
            )
        except services.VoucherError as e:
            return Response({'ok': False, 'error': str(e)}, status=422)

        return Response({'ok': True, **_datos(voucher)}, status=201)


class VoucherComprobanteView(ApiKeyLoggedView, APIView):
    """POST /api/v1/vouchers/<codigo>/comprobante/ — el cliente mandó la transferencia.

    Body: {"comprobante_base64": "...", "comprobante_mimetype": "image/jpeg"}
    Deja el voucher esperando revisión y dispara el aviso interno al equipo.
    """

    def post(self, request, codigo):
        voucher = Voucher.objects.filter(codigo=codigo.strip().upper()).select_related('circuito').first()
        if voucher is None:
            return Response({'ok': False, 'error': 'codigo_inexistente'}, status=404)

        b64 = request.data.get('comprobante_base64')
        if not b64:
            return Response({'ok': False, 'error': 'falta_comprobante'}, status=400)
        try:
            crudo = base64.b64decode(b64)
        except (binascii.Error, ValueError):
            return Response({'ok': False, 'error': 'comprobante_base64_invalido'}, status=400)
        if len(crudo) > COMPROBANTE_MAX_BYTES:
            return Response({'ok': False, 'error': 'comprobante_demasiado_grande',
                             'detalle': f'Máximo {COMPROBANTE_MAX_BYTES // (1024 * 1024)} MB.'},
                            status=400)

        mime = request.data.get('comprobante_mimetype', 'image/jpeg')
        ext = (mime.split('/')[-1] or 'jpg').split(';')[0]
        archivo = ContentFile(crudo, name=f'{voucher.codigo}.{ext}')

        try:
            services.registrar_comprobante(voucher, archivo)
        except services.VoucherError as e:
            return Response({'ok': False, 'error': str(e)}, status=422)

        return Response({'ok': True, **_datos(voucher)})


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
            'personas': voucher.personas,
            'monto': voucher.monto,
            'vence': voucher.fecha_vencimiento.isoformat(),
        })


def _turno_por_nombre(nombre):
    """El bot habla de "turno mañana" y "turno tarde", no de ids: acá se traduce.

    Lo que no diga ni mañana ni tarde devuelve None y el canje se rechaza. Si cualquier cosa
    cayera en "mañana" por descarte, un turno mal escrito terminaría confirmando una reserva
    en un horario que la persona no eligió.
    """
    from apps.turnero.models import Turno

    texto = str(nombre or '').lower().replace('ñ', 'n')
    if 'tarde' in texto:
        clave = 'tarde'
    elif 'manan' in texto or 'mañan' in str(nombre or '').lower():
        clave = 'manan'
    else:
        return None
    for turno in Turno.objects.filter(activo=True):
        if clave in turno.nombre.lower().replace('ñ', 'n'):
            return turno.pk
    return None


class VoucherCanjearView(ApiKeyLoggedView, APIView):
    """POST /api/v1/vouchers/canjear/ — n8n canjea el voucher creando la reserva confirmada."""

    def post(self, request):
        data = request.data
        turno_id = data.get('turno_id') or _turno_por_nombre(data.get('turno'))
        if not turno_id:
            return Response({'ok': False, 'error': 'turno_no_encontrado'}, status=422)
        try:
            reserva, voucher = services.canjear(
                data['codigo'],
                telefono=data['telefono'],
                nombre_contacto=data.get('nombre_contacto', ''),
                turno_id=turno_id,
                fecha=date.fromisoformat(data['fecha']),
                cantidad_personas=int(data.get('cantidad_personas') or 0) or None,
            )
        except services.VoucherError as e:
            return Response({'ok': False, 'error': str(e)}, status=422)
        except Exception as e:
            return Response({'ok': False, 'error': str(e)}, status=422)

        self._contacto_relacionado = reserva.contacto
        return Response({'ok': True, 'reserva_id': reserva.id, 'estado': reserva.estado,
                         'codigo': voucher.codigo, 'saldo': reserva.saldo})
