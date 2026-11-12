import json
import os
import shutil
import tempfile
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.circuitos.models import Circuito
from apps.contactos.models import Contacto
from apps.reservas import services
from apps.reservas.models import NotaReserva, Pago, Reserva
from apps.turnero.models import Turno
from apps.whatsapp.models import Conversacion, Mensaje

TMP = tempfile.mkdtemp()

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
       b'\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00'
       b'\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')


@override_settings(MEDIA_ROOT=TMP, MEDIA_URL='/media/')
class ComprobanteTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='fiore', password='x', rol='dueno')
        self.client.force_login(self.user)
        self.contacto = Contacto.objects.create(nombre='Ana', telefono='+5493815551234')
        self.circuito = Circuito.objects.create(
            nombre='Spa Pareja', capacidad_maxima=2, sena_valor=50,
            precio_semana=40000, precio_finde=50000)
        self.turno = Turno.objects.create(
            nombre='Mañana', hora_inicio=time(10), hora_fin=time(12),
            dias_aplicables=[0, 1, 2, 3, 4, 5, 6])
        self.reserva = Reserva.objects.create(
            contacto=self.contacto, circuito=self.circuito, turno=self.turno,
            fecha=date.today() + timedelta(days=3), cantidad_personas=2,
            medio_pago=Reserva.MedioPago.TRANSFERENCIA,
            estado=Reserva.Estado.PENDIENTE_APROBACION, monto_sena=20000)
        self.conv = Conversacion.objects.create(
            telefono=self.contacto.telefono, contacto=self.contacto)

    def _mensaje_con_imagen(self, horas_atras=2, nombre='comp.png'):
        d = os.path.join(TMP, 'uploads', f'conv_{self.conv.pk}')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, nombre), 'wb') as f:
            f.write(PNG)
        return Mensaje.objects.create(
            conversacion=self.conv, contacto=self.contacto,
            direccion=Mensaje.Direccion.ENTRANTE, tipo=Mensaje.Tipo.IMAGEN,
            media_url=f'/media/uploads/conv_{self.conv.pk}/{nombre}',
            media_mime='image/png',
            timestamp=timezone.now() - timedelta(hours=horas_atras))

    # ── 1. la ficha ofrece las imágenes del chat ────────────────────────────
    def test_ficha_muestra_las_imagenes_del_chat(self):
        m = self._mensaje_con_imagen()
        r = self.client.get(reverse('reservas:detalle', args=[self.reserva.pk]))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Usar esta', html)
        self.assertIn(m.media_url, html)
        self.assertIn('No hay ninguno adjunto', html)

    # ── 2. adjuntar una imagen puntual del chat ─────────────────────────────
    def test_adjuntar_desde_el_chat(self):
        m = self._mensaje_con_imagen()
        r = self.client.post(reverse('reservas:adjuntar_comprobante', args=[self.reserva.pk]),
                             {'mensaje_id': m.pk}, follow=True)
        self.assertEqual(r.status_code, 200)
        self.reserva.refresh_from_db()
        self.assertTrue(self.reserva.comprobante)
        self.assertEqual(self.reserva.comprobante.read(), PNG)
        self.assertTrue(NotaReserva.objects.filter(
            reserva=self.reserva, texto__startswith='Se adjuntó el comprobante').exists())

    # ── 3. subir un archivo a mano ──────────────────────────────────────────
    def test_subir_archivo(self):
        f = SimpleUploadedFile('transferencia.png', PNG, content_type='image/png')
        self.client.post(reverse('reservas:adjuntar_comprobante', args=[self.reserva.pk]),
                         {'archivo': f})
        self.reserva.refresh_from_db()
        self.assertTrue(self.reserva.comprobante)

    # ── 4. un PDF se rechaza con un mensaje claro ───────────────────────────
    def test_pdf_rechazado(self):
        f = SimpleUploadedFile('c.pdf', b'%PDF-1.4', content_type='application/pdf')
        r = self.client.post(reverse('reservas:adjuntar_comprobante', args=[self.reserva.pk]),
                             {'archivo': f}, follow=True)
        self.reserva.refresh_from_db()
        self.assertFalse(self.reserva.comprobante)
        self.assertIn('captura', r.content.decode())

    # ── 5. no se puede robar la imagen de otro cliente ──────────────────────
    def test_mensaje_de_otra_conversacion(self):
        otro = Contacto.objects.create(nombre='Beto', telefono='+5493815559999')
        conv2 = Conversacion.objects.create(telefono=otro.telefono, contacto=otro)
        d = os.path.join(TMP, 'uploads', f'conv_{conv2.pk}')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'x.png'), 'wb') as f:
            f.write(PNG)
        ajeno = Mensaje.objects.create(
            conversacion=conv2, contacto=otro, direccion=Mensaje.Direccion.ENTRANTE,
            tipo=Mensaje.Tipo.IMAGEN, media_url=f'/media/uploads/conv_{conv2.pk}/x.png',
            timestamp=timezone.now())
        self.client.post(reverse('reservas:adjuntar_comprobante', args=[self.reserva.pk]),
                         {'mensaje_id': ajeno.pk})
        self.reserva.refresh_from_db()
        self.assertFalse(self.reserva.comprobante)

    # ── 6. la ventana de 72 h ───────────────────────────────────────────────
    def test_imagen_vieja_no_se_engancha_sola_pero_se_puede_elegir(self):
        m = self._mensaje_con_imagen(horas_atras=100, nombre='vieja.png')
        # Automático: no la toma (podría ser cualquier cosa).
        self.assertEqual(services.imagenes_del_chat(self.contacto.telefono), [])
        self.assertEqual(services.adjuntar_comprobante(self.reserva), '')
        # A mano: la ficha la ofrece igual, con su fecha, y se puede elegir.
        self.assertEqual(services.imagenes_del_chat(self.contacto.telefono, horas=None), [m])
        r = self.client.get(reverse('reservas:detalle', args=[self.reserva.pk]))
        self.assertIn(m.media_url, r.content.decode())
        self.assertTrue(services.adjuntar_comprobante(self.reserva, mensaje_id=m.pk))

    # ── 7. el informe de comprobantes ahora la ve ───────────────────────────
    def test_entra_en_el_informe(self):
        from apps.dashboard.views import _comprobantes
        m = self._mensaje_con_imagen()
        services.adjuntar_comprobante(self.reserva, mensaje_id=m.pk, autor=self.user)
        hoy = date.today()
        self.assertIn(self.reserva, list(_comprobantes(hoy - timedelta(days=1), hoy)))

    # ── 8. el bot sigue andando igual (ventana corta) ───────────────────────
    def test_camino_del_bot_intacto(self):
        self._mensaje_con_imagen(horas_atras=2)
        self.assertIsNotNone(services._ultimo_comprobante_del_cliente(self.contacto.telefono))
        self._mensaje_con_imagen(horas_atras=20, nombre='v2.png')
        self.assertIsNone(
            services._ultimo_comprobante_del_cliente('+5493815550000'))

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)


@override_settings(MEDIA_ROOT=TMP, MEDIA_URL='/media/')
class AsistioCobraElSaldoTest(TestCase):
    """Marcar "asistió" tiene que cobrar lo que falta, no solo cambiar el estado.

    Antes solo pasaba la reserva a completado: una reserva atendida y cobrada en el mostrador
    seguía figurando con saldo pendiente y contando en "por cobrar" del dashboard.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='reca', password='x', rol='recepcion')
        self.client.force_login(self.user)
        self.contacto = Contacto.objects.create(nombre='Ana', telefono='+5493815551234')
        self.circuito = Circuito.objects.create(
            nombre='Spa Pareja', capacidad_maxima=2, sena_valor=50,
            precio_semana=40000, precio_finde=50000)
        self.turno = Turno.objects.create(
            nombre='Mañana', hora_inicio=time(10), hora_fin=time(12),
            dias_aplicables=[0, 1, 2, 3, 4, 5, 6])

    def _reserva(self, total=40000, pagado=20000, estado=Reserva.Estado.CONFIRMADO):
        return Reserva.objects.create(
            contacto=self.contacto, circuito=self.circuito, turno=self.turno,
            fecha=date.today(), cantidad_personas=2, precio_total=total,
            monto_sena=total / 2, monto_pagado=pagado, estado=estado,
            medio_pago=Reserva.MedioPago.TRANSFERENCIA)

    # ── 1. con saldo, el botón del día lleva a la pantalla de cobro ──────────
    def test_get_muestra_la_pantalla_con_el_saldo_precargado(self):
        r = self._reserva()
        resp = self.client.get(reverse('reservas:asistio', args=[r.pk]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('¿Cuánto pagó ahora?', html)
        self.assertIn('value="20000"', html)       # lo que faltaba, precargado
        # El GET no cambia nada.
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.CONFIRMADO)

    # ── 2. el camino normal: cobra y cierra ─────────────────────────────────
    def test_cobra_el_saldo_y_completa(self):
        r = self._reserva()
        resp = self.client.post(reverse('reservas:asistio', args=[r.pk]),
                                {'monto': '20000', 'medio_pago': 'efectivo'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.COMPLETADO)
        self.assertEqual(r.saldo, 0)
        pago = Pago.objects.get(reserva=r)
        self.assertEqual(pago.monto, 20000)
        self.assertEqual(pago.tipo, Pago.Tipo.SALDO)
        self.assertEqual(pago.medio_pago, 'efectivo')
        self.assertTrue(NotaReserva.objects.filter(
            reserva=r, texto__contains='Se cobró').exists())

    # ── 3. el pago entra en la caja del día ─────────────────────────────────
    def test_entra_en_la_caja_del_dia(self):
        from apps.dashboard.services import caja_del_dia

        r = self._reserva()
        self.client.post(reverse('reservas:asistio', args=[r.pk]),
                         {'monto': '20000', 'medio_pago': 'efectivo'})
        caja = caja_del_dia(timezone.localdate())
        self.assertEqual(caja['total'], 20000)
        self.assertEqual(caja['por_medio'], {'Efectivo': 20000})

    # ── 4. pago parcial: se cierra igual y queda el resto ───────────────────
    def test_pago_parcial_deja_saldo(self):
        r = self._reserva()
        self.client.post(reverse('reservas:asistio', args=[r.pk]),
                         {'monto': '5000', 'medio_pago': 'efectivo'})
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.COMPLETADO)
        self.assertEqual(r.saldo, 15000)

    # ── 5. cerrar sin cobrar sigue siendo posible, pero explícito ───────────
    def test_sin_cobrar(self):
        r = self._reserva()
        self.client.post(reverse('reservas:asistio', args=[r.pk]), {'sin_cobrar': '1'})
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.COMPLETADO)
        self.assertEqual(r.saldo, 20000)
        self.assertFalse(Pago.objects.filter(reserva=r).exists())
        self.assertTrue(NotaReserva.objects.filter(
            reserva=r, texto__contains='sin cobrar').exists())

    # ── 6. sin medio de pago no se cobra a ciegas ───────────────────────────
    def test_monto_sin_medio_de_pago(self):
        r = self._reserva()
        resp = self.client.post(reverse('reservas:asistio', args=[r.pk]),
                                {'monto': '20000', 'medio_pago': ''})
        self.assertIn('Elegí con qué medio pagó', resp.content.decode())
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.CONFIRMADO)
        self.assertFalse(Pago.objects.filter(reserva=r).exists())

    # ── 7. ya paga: el botón cierra directo, sin preguntar ──────────────────
    def test_sin_saldo_cierra_directo(self):
        r = self._reserva(pagado=40000)
        self.client.post(reverse('reservas:asistio', args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.COMPLETADO)
        self.assertFalse(Pago.objects.filter(reserva=r).exists())

    # ── 8. el kanban no completa a ciegas: manda a cobrar ───────────────────
    def test_kanban_con_saldo_redirige_a_cobrar(self):
        r = self._reserva()
        resp = self.client.post(
            reverse('reservas:mover', args=[r.pk]),
            data=json.dumps({'estado': Reserva.Estado.COMPLETADO}),
            content_type='application/json')
        datos = resp.json()
        self.assertFalse(datos['ok'])
        self.assertIn(reverse('reservas:asistio', args=[r.pk]), datos['redirigir'])
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.CONFIRMADO)

    def test_kanban_sin_saldo_completa(self):
        r = self._reserva(pagado=40000)
        resp = self.client.post(
            reverse('reservas:mover', args=[r.pk]),
            data=json.dumps({'estado': Reserva.Estado.COMPLETADO}),
            content_type='application/json')
        self.assertTrue(resp.json()['ok'])
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.COMPLETADO)

    # ── 9. cobrar el saldo desde la ficha (las ya cerradas) ─────────────────
    def test_cobrar_saldo_desde_la_ficha(self):
        r = self._reserva(estado=Reserva.Estado.COMPLETADO)
        resp = self.client.get(reverse('reservas:detalle', args=[r.pk]))
        self.assertIn('Registrar cobro', resp.content.decode())
        self.client.post(reverse('reservas:cobrar_saldo', args=[r.pk]),
                         {'monto': '20000', 'medio_pago': 'efectivo'})
        r.refresh_from_db()
        self.assertEqual(r.saldo, 0)
        self.assertEqual(r.estado, Reserva.Estado.COMPLETADO)   # no cambia el estado
        self.assertEqual(Pago.objects.get(reserva=r).tipo, Pago.Tipo.SALDO)

    def test_cobrar_saldo_monto_invalido(self):
        r = self._reserva()
        self.client.post(reverse('reservas:cobrar_saldo', args=[r.pk]),
                         {'monto': '0', 'medio_pago': 'efectivo'})
        r.refresh_from_db()
        self.assertEqual(r.saldo, 20000)
        self.assertFalse(Pago.objects.filter(reserva=r).exists())

    # ── 10. el día ofrece el link de cobro cuando falta plata ───────────────
    def test_el_dia_linkea_a_cobrar(self):
        r = self._reserva()
        resp = self.client.get(reverse('turnero:hoy'))
        html = resp.content.decode()
        self.assertIn(reverse('reservas:asistio', args=[r.pk]) + '?next=', html)

    # ── 11. deja de contar en "por cobrar" del dashboard ────────────────────
    def test_sale_de_los_saldos_por_cobrar(self):
        from apps.dashboard.services import saldos_por_cobrar

        r = self._reserva()
        self.assertEqual(saldos_por_cobrar()['total'], 20000)
        self.client.post(reverse('reservas:asistio', args=[r.pk]),
                         {'monto': '20000', 'medio_pago': 'efectivo'})
        self.assertEqual(saldos_por_cobrar()['total'], 0)


class AvisoDeReservaTest(TestCase):
    """Lo que ve el equipo cuando entra una reserva: tiene que alcanzar para trabajar sin
    abrir el CRM (extras, nombre, teléfono, total, seña y el saldo a cobrar el día)."""

    def setUp(self):
        from apps.circuitos.models import Extra

        self.circuito = Circuito.objects.create(
            nombre='Spa Grupal Premium', capacidad_minima=3, capacidad_maxima=8, sena_valor=50,
            precio_semana=492000, precio_finde=528000, duracion_minutos=300)
        self.turno = Turno.objects.create(
            nombre='Mañana', hora_inicio=time(11), hora_fin=time(16),
            dias_aplicables=[0, 1, 2, 3, 4, 5, 6])
        self.extra = Extra.objects.create(nombre='Menu vegetariano', precio=0, por_persona=True)

    def _lunes(self):
        dia = date.today() + timedelta(days=1)
        while dia.weekday() != 0:
            dia += timedelta(days=1)
        return dia

    def test_el_contexto_trae_saldo_horario_y_fecha_en_palabras(self):
        from apps.configuracion import avisos

        reserva = services.crear_reserva(
            telefono='1166390002', nombre_contacto='Gabriela Ponce',
            circuito_id=self.circuito.pk, turno_id=self.turno.pk, fecha=self._lunes(),
            cantidad_personas=3, extras=[{'extra_id': self.extra.pk, 'cantidad': 1}])
        datos = avisos.contexto_reserva(reserva)

        self.assertEqual(datos['horario'], '11:00 a 16:00')
        self.assertTrue(datos['fecha_larga'].startswith('lunes '), datos['fecha_larga'])
        self.assertEqual(datos['total'], '$492.000')
        self.assertEqual(datos['sena'], '$246.000')
        # Todavía no hay pago registrado, pero la seña se descuenta igual: el aviso sale
        # cuando la está transfiriendo.
        self.assertEqual(datos['saldo'], '$246.000')
        self.assertEqual(datos['bloque_extras'], '\n- Menu vegetariano')
        self.assertEqual(datos['cliente'], 'Gabriela Ponce')

    def test_sin_extras_no_queda_un_renglon_vacio(self):
        from apps.configuracion import avisos

        reserva = services.crear_reserva(
            telefono='1166390003', nombre_contacto='Ana',
            circuito_id=self.circuito.pk, turno_id=self.turno.pk, fecha=self._lunes(),
            cantidad_personas=3)
        self.assertEqual(avisos.contexto_reserva(reserva)['bloque_extras'], '')

    def test_la_reserva_queda_a_nombre_de_quien_lo_dijo_y_no_del_pushname(self):
        from apps.contactos.models import Contacto

        Contacto.objects.create(nombre='username.gabriela', telefono='+5491166390004')
        Conversacion.objects.create(telefono='+5491166390004', nombre_contacto='username.gabriela')
        reserva = services.crear_reserva(
            telefono='1166390004', nombre_contacto='Gabriela Ponce',
            circuito_id=self.circuito.pk, turno_id=self.turno.pk, fecha=self._lunes(),
            cantidad_personas=3)
        self.assertEqual(reserva.contacto.nombre, 'Gabriela Ponce')
