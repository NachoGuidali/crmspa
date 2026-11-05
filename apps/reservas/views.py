import base64
import binascii
import re
import unicodedata
from datetime import date

from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.utils.dateparse import parse_date
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.integraciones.mixins import ApiKeyLoggedView

from . import services
from .models import NotaReserva, Reserva
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
        try:
            reserva = services.confirmar_sena(reserva, **serializer.validated_data)
        except services.ReservaError as e:
            # El hold venció y el turno ya se lo llevó otro: no se puede cobrar esta seña.
            return Response({'error': str(e)}, status=422)

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


class ReservaBotCrearView(ApiKeyLoggedView, APIView):
    """POST /api/v1/reservas/bot/ — el bot crea la reserva con el medio de pago elegido.
    transferencia → pendiente_aprobacion (con comprobante); mercado_pago → pendiente_pago (con link).
    Manda fecha+turno+personas estructurados (valida cupo)."""

    # Mismo límite que enviar_media (16 MB), pero en base64 (~33% más grande que el binario).
    COMPROBANTE_MAX_BYTES = 8 * 1024 * 1024

    def post(self, request):
        data = request.data
        # Clave de idempotencia: por body o por el header estándar. Si n8n reintenta el POST
        # con la misma clave, devolvemos la reserva original en vez de crear un duplicado.
        idem = (data.get('idempotency_key') or request.headers.get('Idempotency-Key') or '').strip()
        # El comprobante viene en base64 (transferencia)
        comprobante = None
        b64 = data.get('comprobante_base64')
        if b64:
            try:
                raw = base64.b64decode(b64)
            except (binascii.Error, ValueError):
                return Response({'error': 'comprobante_base64_invalido'}, status=400)
            if len(raw) > self.COMPROBANTE_MAX_BYTES:
                return Response({'error': 'comprobante_demasiado_grande',
                                 'detalle': f'Máximo {self.COMPROBANTE_MAX_BYTES // (1024 * 1024)} MB.'},
                                status=400)
            mime = data.get('comprobante_mimetype', 'image/jpeg')
            ext = (mime.split('/')[-1] or 'jpg').split(';')[0]
            comprobante = ContentFile(raw, name=f'comprobante.{ext}')

        try:
            reserva = services.crear_reserva_bot(
                telefono=data['telefono'],
                nombre_contacto=data.get('nombre_contacto', ''),
                circuito_id=data['circuito_id'],
                turno_id=data['turno_id'],
                fecha=date.fromisoformat(data['fecha']),
                cantidad_personas=int(data.get('cantidad_personas', 1)),
                medio_pago=data.get('medio_pago', ''),
                resumen=data.get('resumen', ''),
                comprobante=comprobante,
                link_pago=data.get('link_pago', ''),
                extras=data.get('extras'),
                idempotency_key=idem,
            )
        except services.ReservaError as e:
            return Response({'error': str(e)}, status=422)
        except (KeyError, ValueError) as e:
            return Response({'error': 'datos_invalidos', 'detalle': str(e)}, status=400)
        except IntegrityError:
            # Dos POST con la misma clave entraron a la vez y el unique de la DB frenó al
            # segundo (el lock del slot debería evitarlo, esto es el último cinturón).
            # La transacción del service ya quedó revertida: devolvemos la que sí se guardó.
            existente = Reserva.objects.filter(idempotency_key=idem).first() if idem else None
            if existente is None:
                raise
            return Response(ReservaSerializer(existente).data, status=201)

        self._contacto_relacionado = reserva.contacto
        return Response(ReservaSerializer(reserva).data, status=201)


class ReservaConfirmarPagoView(ApiKeyLoggedView, APIView):
    """POST /api/v1/reservas/confirmar-pago/ — Mercado Pago acreditó: confirma por teléfono.
    Body: {"telefono": "..."}. Busca la reserva pendiente de pago más reciente y la confirma."""

    def post(self, request):
        from utils.phone import normalize_ar_phone

        telefono = request.data.get('telefono', '')
        if not telefono:
            return Response({'error': 'telefono_requerido'}, status=400)
        telefono = normalize_ar_phone(telefono)

        reserva = (
            Reserva.objects.filter(
                contacto__telefono=telefono, estado=Reserva.Estado.PENDIENTE_PAGO,
            )
            .order_by('-created_at').first()
        )
        if not reserva:
            return Response({'error': 'reserva_pendiente_pago_no_encontrada'}, status=404)

        try:
            services.confirmar_reserva(reserva)
        except services.ReservaError as e:
            # Se acreditó el pago pero el hold ya había vencido y el turno está tomado.
            # Devolvemos 422 para que n8n lo derive a una persona (hay plata del cliente).
            self._contacto_relacionado = reserva.contacto
            return Response({'error': str(e), 'reserva_id': reserva.id}, status=422)
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


class ReservasAgendaView(ApiKeyLoggedView, APIView):
    """GET /api/v1/reservas/agenda/?fecha=YYYY-MM-DD&estado=confirmado
    Reservas de una fecha (por defecto confirmadas): las usa el bot para los recordatorios
    automáticos (24hs antes y el mismo día). Devuelve {telefono, nombre, horario}."""

    def get(self, request):
        fecha_raw = request.query_params.get('fecha')
        if not fecha_raw:
            return Response({'error': 'fecha_requerida'}, status=400)
        try:
            fecha = date.fromisoformat(fecha_raw)
        except ValueError:
            return Response({'error': 'fecha_invalida', 'detalle': 'formato YYYY-MM-DD'}, status=400)

        estado = request.query_params.get('estado', Reserva.Estado.CONFIRMADO)
        # Aceptamos "confirmada"/"confirmado" indistintamente.
        if estado in ('confirmada', 'confirmado'):
            estado = Reserva.Estado.CONFIRMADO

        reservas = (
            Reserva.objects.filter(fecha=fecha, estado=estado)
            .select_related('contacto', 'turno')
            .order_by('turno__hora_inicio')
        )
        data = [
            {
                'telefono': r.contacto.telefono,
                'nombre': r.contacto.nombre,
                'horario': f'{r.fecha.isoformat()} ({r.turno.nombre})',
            }
            for r in reservas
        ]
        return Response(data)


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


class ReservaBuscarView(ApiKeyLoggedView, APIView):
    """GET /api/v1/reservas/buscar/?nombre=...&fecha=YYYY-MM-DD[&turno=mañana|tarde]

    Para cuando quien escribe NO es quien reservó: en un grupo la reserva la hace una sola
    persona y desde un solo teléfono, así que `por-telefono` no encuentra nada aunque la
    reserva exista. Acá se busca por nombre de la titular más la fecha.

    El nombre y la fecha son los dos obligatorios a propósito. Con la fecha sola se
    listarían las reservas de terceros de ese día, y con el nombre solo alcanzaría probar
    nombres comunes. Y se devuelve lo mínimo para confirmar que la reserva está —sin
    teléfono, sin email, sin montos y sin notas— porque no sabemos si habla la titular.
    """

    MAX_RESULTADOS = 5

    @staticmethod
    def _sin_tildes(texto):
        base = unicodedata.normalize('NFD', str(texto or '').lower())
        return ''.join(ch for ch in base if unicodedata.category(ch) != 'Mn')

    @classmethod
    def _coincide_nombre(cls, buscado, nombre):
        """Tolerante con cómo lo escriba la clienta: sin tildes, en otro orden y con el
        apellido suelto. Pide palabras de 3 letras o más para que un "de" no matchee todo."""
        b, n = cls._sin_tildes(buscado), cls._sin_tildes(nombre)
        if not b or not n:
            return False
        if b in n or n in b:
            return True
        palabras = [p for p in re.split(r'[^a-z0-9]+', b) if len(p) >= 3]
        return bool(palabras) and all(p in n for p in palabras)

    def get(self, request):
        nombre = (request.query_params.get('nombre') or '').strip()
        fecha_txt = (request.query_params.get('fecha') or '').strip()
        if not nombre or not fecha_txt:
            return Response({'error': 'nombre_y_fecha_requeridos'}, status=400)
        fecha = parse_date(fecha_txt)
        if fecha is None:
            return Response({'error': 'fecha_invalida'}, status=400)

        reservas = (Reserva.objects
                    .filter(fecha=fecha, estado__in=Reserva.ESTADOS_QUE_OCUPAN_CUPO)
                    .select_related('contacto', 'circuito', 'turno')
                    .order_by('turno__hora_inicio'))
        encontradas = [r for r in reservas if self._coincide_nombre(nombre, r.contacto.nombre)]

        # El turno solo afina: si no coincide ninguna, se devuelven igual las del nombre y la
        # fecha, para poder decir "la tengo en el turno tarde" en vez de "no existe".
        turno = self._sin_tildes(request.query_params.get('turno') or '')
        if turno:
            encontradas = [r for r in encontradas
                           if turno in self._sin_tildes(r.turno.nombre)] or encontradas

        return Response({'reservas': [{
            'id': r.id,
            'fecha': r.fecha.isoformat(),
            'turno_nombre': r.turno.nombre,
            'hora_inicio': r.turno.hora_inicio.strftime('%H:%M'),
            'hora_fin': r.turno.hora_fin.strftime('%H:%M'),
            'circuito_nombre': r.circuito.nombre,
            'cantidad_personas': r.cantidad_personas,
            'contacto_nombre': r.contacto.nombre,
            'estado': r.estado,
        } for r in encontradas[:self.MAX_RESULTADOS]]})

class ReservaNotaView(ApiKeyLoggedView, APIView):
    """POST /api/v1/reservas/<id>/notas/ — el bot deja anotado algo que pasó con la reserva.

    Body: {"texto": "Volvió a escribir preguntando si puede llegar más tarde"}.
    Queda en el historial de la reserva, firmado como "Bot de WhatsApp", para que el equipo
    vea lo que pasó sin tener que leer toda la conversación.
    """

    def post(self, request, pk):
        texto = (request.data.get('texto') or '').strip()
        if not texto:
            return Response({'error': 'texto_requerido'}, status=400)
        reserva = Reserva.objects.filter(pk=pk).select_related('contacto').first()
        if reserva is None:
            return Response({'error': 'reserva_not_found'}, status=404)

        origen = request.data.get('origen') or NotaReserva.Origen.BOT
        if origen not in NotaReserva.Origen.values:
            origen = NotaReserva.Origen.BOT
        nota = NotaReserva.objects.create(reserva=reserva, origen=origen, texto=texto[:2000])

        # Avisar al equipo: esto es información que llega sola, no algo que alguien tipeó.
        # Las notas del propio equipo no avisan (quien la escribió ya se enteró).
        from apps.configuracion import avisos
        from apps.configuracion.models import AvisoInterno

        if origen != NotaReserva.Origen.STAFF:
            avisos.disparar(AvisoInterno.Evento.NOTA_EN_RESERVA,
                            avisos.contexto_reserva(reserva, nota=nota.texto))

        self._contacto_relacionado = reserva.contacto
        return Response({'ok': True, 'nota_id': nota.id, 'reserva_id': reserva.id}, status=201)
