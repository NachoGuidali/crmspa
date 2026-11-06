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
from apps.reservas.models import NotaReserva, Reserva
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
