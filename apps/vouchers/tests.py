"""El camino del voucher de regalo: lo arma el bot, se paga, se aprueba y se canjea.

Lo que se cuida acá es que un voucher NO valga hasta que alguien del spa vio la transferencia
(antes, cualquier estado que no fuera canjeado ni cancelado pasaba el control) y que el precio
y la cantidad de personas queden fijos en el voucher.
"""
import shutil
import tempfile
from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.circuitos.models import Circuito
from apps.configuracion.models import AvisoInterno, ConfiguracionNegocio
from apps.turnero.models import Turno
from apps.vouchers import services
from apps.vouchers.models import Voucher

TMP = tempfile.mkdtemp()


def _un_sabado(desde=None):
    """La primera fecha futura que caiga sábado, para que sea tarifa de fin de semana."""
    dia = (desde or timezone.localdate()) + timedelta(days=1)
    while dia.weekday() != 5:
        dia += timedelta(days=1)
    return dia


@override_settings(MEDIA_ROOT=TMP, MEDIA_URL='/media/')
class VoucherBaseTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = get_user_model().objects.create_user(username='fiore', password='x', rol='dueno')
        self.circuito = Circuito.objects.create(
            nombre='Spa de Parejas Clásico', capacidad_minima=2, capacidad_maxima=2,
            sena_valor=50, precio_semana=320000, precio_finde=350000, duracion_minutos=300)
        self.turno = Turno.objects.create(
            nombre='Mañana', hora_inicio=time(11), hora_fin=time(16),
            dias_aplicables=[0, 1, 2, 3, 4, 5, 6])

    def _voucher(self, **extra):
        datos = dict(
            circuito=self.circuito, personas=2, comprador_nombre='Julieta Pintos',
            comprador_telefono='1166391284', destinatario_nombre='Martina',
            origen=Voucher.Origen.WHATSAPP_BOT, estado=Voucher.Estado.PENDIENTE_PAGO,
        )
        datos.update(extra)
        return services.crear(**datos)


class CrearTest(VoucherBaseTest):
    def test_el_precio_es_el_de_fin_de_semana(self):
        """Se vende al precio más caro para que sirva para cualquier día (decisión del 11/11)."""
        voucher = self._voucher()
        self.assertEqual(voucher.monto, Decimal('350000'))

    def test_el_vencimiento_sale_de_la_configuracion(self):
        config = ConfiguracionNegocio.get_solo()
        config.voucher_validez_dias = 90
        config.save()
        voucher = self._voucher()
        self.assertEqual(voucher.fecha_vencimiento, timezone.localdate() + timedelta(days=90))

    def test_no_se_puede_crear_para_una_cantidad_que_no_entra(self):
        with self.assertRaises(services.VoucherError):
            self._voucher(personas=5)

    def test_el_telefono_queda_normalizado(self):
        self.assertTrue(self._voucher().comprador_telefono.startswith('+549'))


class ValidarTest(VoucherBaseTest):
    def test_un_voucher_sin_pagar_no_vale(self):
        voucher = self._voucher()
        with self.assertRaises(services.VoucherError) as e:
            services.validar(voucher.codigo)
        self.assertEqual(str(e.exception), 'falta_el_pago')

    def test_con_el_comprobante_mandado_tampoco(self):
        """Hasta que no lo mira una persona, el regalo no existe."""
        voucher = self._voucher()
        with patch('apps.configuracion.avisos.disparar'):
            services.registrar_comprobante(voucher, ContentFile(b'x', name='comp.jpg'))
        with self.assertRaises(services.VoucherError) as e:
            services.validar(voucher.codigo)
        self.assertEqual(str(e.exception), 'pago_en_revision')

    def test_aprobado_si_vale(self):
        voucher = services.aprobar(self._voucher(), usuario=self.user)
        self.assertEqual(services.validar(voucher.codigo).pk, voucher.pk)

    def test_vencido_no_vale(self):
        voucher = services.aprobar(self._voucher(), usuario=self.user)
        Voucher.objects.filter(pk=voucher.pk).update(
            fecha_vencimiento=timezone.localdate() - timedelta(days=1))
        with self.assertRaises(services.VoucherError) as e:
            services.validar(voucher.codigo)
        self.assertEqual(str(e.exception), 'vencido')

    def test_un_codigo_que_no_existe(self):
        with self.assertRaises(services.VoucherError) as e:
            services.validar('SPA-XXXX-XXXX')
        self.assertEqual(str(e.exception), 'codigo_inexistente')


class ComprobanteTest(VoucherBaseTest):
    def test_queda_esperando_revision_y_avisa_al_equipo(self):
        voucher = self._voucher()
        with patch('apps.configuracion.avisos.disparar') as disparar:
            services.registrar_comprobante(voucher, ContentFile(b'x', name='comp.jpg'))
        voucher.refresh_from_db()
        self.assertEqual(voucher.estado, Voucher.Estado.PENDIENTE_APROBACION)
        self.assertTrue(voucher.comprobante)
        evento, contexto = disparar.call_args[0]
        self.assertEqual(evento, AvisoInterno.Evento.VOUCHER_POR_VERIFICAR)
        self.assertEqual(contexto['codigo'], voucher.codigo)
        self.assertTrue(contexto['link'].endswith(f'/vouchers/{voucher.pk}/'))

    def test_no_se_puede_mandar_comprobante_de_uno_ya_activo(self):
        voucher = services.aprobar(self._voucher(), usuario=self.user)
        with self.assertRaises(services.VoucherError):
            services.registrar_comprobante(voucher, ContentFile(b'x', name='comp.jpg'))


class AprobarYEnviarTest(VoucherBaseTest):
    def test_aprobar_lo_activa_y_dibuja_los_archivos(self):
        voucher = services.aprobar(self._voucher(), usuario=self.user)
        self.assertEqual(voucher.estado, Voucher.Estado.ACTIVO)
        self.assertTrue(voucher.imagen.name.endswith('.png'))
        self.assertTrue(voucher.archivo_pdf.name.endswith('.pdf'))
        self.assertGreater(voucher.imagen.size, 10000)
        self.assertEqual(voucher.aprobado_por, self.user)

    def test_la_validez_se_cuenta_desde_la_aprobacion(self):
        """El plazo arranca cuando el regalo existe, no cuando el bot armó el borrador."""
        voucher = self._voucher()
        Voucher.objects.filter(pk=voucher.pk).update(
            fecha_vencimiento=timezone.localdate() - timedelta(days=5))
        voucher.refresh_from_db()
        services.aprobar(voucher, usuario=self.user)
        self.assertEqual(voucher.fecha_vencimiento, services.vencimiento())

    def test_enviar_manda_la_imagen_por_whatsapp(self):
        voucher = services.aprobar(self._voucher(), usuario=self.user)
        with patch('apps.whatsapp.services.enviar_archivo') as enviar:
            enviar.return_value = {'ok': True}
            services.enviar(voucher)
        datos = enviar.call_args[1]
        self.assertEqual(datos['mime'], 'image/png')
        self.assertEqual(datos['telefono'], voucher.comprador_telefono)
        self.assertIn(voucher.codigo, datos['caption'])
        self.assertGreater(len(datos['contenido']), 10000)
        voucher.refresh_from_db()
        self.assertIsNotNone(voucher.enviado_at)


class CanjearTest(VoucherBaseTest):
    def _activo(self):
        return services.aprobar(self._voucher(), usuario=self.user)

    def test_el_canje_deja_la_reserva_confirmada(self):
        voucher = self._activo()
        reserva, voucher = services.canjear(
            voucher.codigo, telefono='1166391284', nombre_contacto='Martina',
            turno_id=self.turno.pk, fecha=_un_sabado(), cantidad_personas=None)
        self.assertEqual(reserva.estado, 'confirmado')
        self.assertEqual(reserva.cantidad_personas, 2)
        self.assertEqual(voucher.estado, Voucher.Estado.CANJEADO)
        self.assertEqual(voucher.reserva_canje_id, reserva.pk)

    def test_no_se_canjea_dos_veces(self):
        voucher = self._activo()
        services.canjear(voucher.codigo, telefono='1166391284', nombre_contacto='Martina',
                         turno_id=self.turno.pk, fecha=_un_sabado())
        with self.assertRaises(services.VoucherError) as e:
            services.canjear(voucher.codigo, telefono='1166391284', nombre_contacto='Martina',
                             turno_id=self.turno.pk, fecha=_un_sabado() + timedelta(days=7))
        self.assertEqual(str(e.exception), 'ya_canjeado')

    def test_en_dia_de_semana_no_queda_saldo_negativo(self):
        """El voucher se vendió a tarifa de finde: un martes vale menos y no se devuelve."""
        voucher = self._activo()
        martes = _un_sabado() + timedelta(days=3)
        reserva, _ = services.canjear(
            voucher.codigo, telefono='1166391284', nombre_contacto='Martina',
            turno_id=self.turno.pk, fecha=martes)
        self.assertEqual(reserva.total, Decimal('320000'))
        self.assertEqual(reserva.monto_pagado, Decimal('320000'))
        self.assertEqual(reserva.saldo, Decimal('0'))


class ApiDelBotTest(VoucherBaseTest):
    def setUp(self):
        super().setUp()
        from apps.integraciones.models import ApiKey

        self.key = ApiKey.objects.create(nombre='n8n')
        self.headers = {'HTTP_X_API_KEY': str(self.key.key)}

    def test_crear_devuelve_el_codigo_y_el_monto(self):
        r = self.client.post(reverse('vouchers_api:crear'), {
            'telefono': '1166391284', 'comprador_nombre': 'Julieta',
            'circuito_id': self.circuito.pk, 'personas': 2,
            'destinatario_nombre': 'Martina', 'mensaje_regalo': 'Felices 10 años',
        }, content_type='application/json', **self.headers)
        self.assertEqual(r.status_code, 201, r.content)
        datos = r.json()
        self.assertEqual(float(datos['monto']), 350000)
        self.assertEqual(datos['estado'], 'pendiente_pago')
        voucher = Voucher.objects.get(codigo=datos['codigo'])
        self.assertEqual(voucher.origen, Voucher.Origen.WHATSAPP_BOT)
        self.assertEqual(voucher.mensaje_regalo, 'Felices 10 años')

    def test_crear_con_una_cantidad_que_no_entra_da_422(self):
        r = self.client.post(reverse('vouchers_api:crear'), {
            'telefono': '1166391284', 'comprador_nombre': 'Julieta',
            'circuito_id': self.circuito.pk, 'personas': 7,
        }, content_type='application/json', **self.headers)
        self.assertEqual(r.status_code, 422)

    def test_el_comprobante_deja_el_voucher_para_revisar(self):
        import base64

        voucher = self._voucher()
        with patch('apps.configuracion.avisos.disparar'):
            r = self.client.post(
                reverse('vouchers_api:comprobante', args=[voucher.codigo]),
                {'comprobante_base64': base64.b64encode(b'imagen').decode(),
                 'comprobante_mimetype': 'image/jpeg'},
                content_type='application/json', **self.headers)
        self.assertEqual(r.status_code, 200, r.content)
        voucher.refresh_from_db()
        self.assertEqual(voucher.estado, Voucher.Estado.PENDIENTE_APROBACION)

    def test_validar_un_voucher_sin_pagar_devuelve_el_motivo(self):
        voucher = self._voucher()
        r = self.client.get(reverse('vouchers_api:validar', args=[voucher.codigo]), **self.headers)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {'valido': False, 'motivo': 'falta_el_pago'})

    def test_validar_uno_activo(self):
        voucher = services.aprobar(self._voucher(), usuario=self.user)
        r = self.client.get(reverse('vouchers_api:validar', args=[voucher.codigo]), **self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['personas'], 2)

    def test_canjear_por_el_nombre_del_turno(self):
        """El bot habla de "turno mañana", no de ids."""
        voucher = services.aprobar(self._voucher(), usuario=self.user)
        r = self.client.post(reverse('vouchers_api:canjear'), {
            'codigo': voucher.codigo, 'telefono': '1166391284', 'nombre_contacto': 'Martina',
            'turno': 'mañana', 'fecha': _un_sabado().isoformat(),
        }, content_type='application/json', **self.headers)
        self.assertEqual(r.status_code, 200, r.content)
        voucher.refresh_from_db()
        self.assertEqual(voucher.reserva_canje.turno_id, self.turno.pk)

    def test_canjear_sin_turno_reconocible_da_422(self):
        voucher = services.aprobar(self._voucher(), usuario=self.user)
        r = self.client.post(reverse('vouchers_api:canjear'), {
            'codigo': voucher.codigo, 'telefono': '1166391284',
            'turno': 'medianoche', 'fecha': _un_sabado().isoformat(),
        }, content_type='application/json', **self.headers)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()['error'], 'turno_no_encontrado')

    def test_canjear_por_la_api(self):
        voucher = services.aprobar(self._voucher(), usuario=self.user)
        r = self.client.post(reverse('vouchers_api:canjear'), {
            'codigo': voucher.codigo, 'telefono': '1166391284', 'nombre_contacto': 'Martina',
            'turno_id': self.turno.pk, 'fecha': _un_sabado().isoformat(),
        }, content_type='application/json', **self.headers)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['ok'])


class PantallaTest(VoucherBaseTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_aprobar_desde_el_crm_manda_el_voucher(self):
        voucher = self._voucher()
        with patch('apps.configuracion.avisos.disparar'):
            services.registrar_comprobante(voucher, ContentFile(b'x', name='comp.jpg'))
        with patch('apps.whatsapp.services.enviar_archivo') as enviar:
            enviar.return_value = {'ok': True}
            r = self.client.post(reverse('vouchers:aprobar', args=[voucher.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(enviar.called)
        voucher.refresh_from_db()
        self.assertEqual(voucher.estado, Voucher.Estado.ACTIVO)

    def test_si_falla_el_whatsapp_el_voucher_queda_activo_igual(self):
        from apps.whatsapp.services import EnvioError

        voucher = self._voucher()
        with patch('apps.configuracion.avisos.disparar'):
            services.registrar_comprobante(voucher, ContentFile(b'x', name='comp.jpg'))
        with patch('apps.whatsapp.services.enviar_archivo', side_effect=EnvioError('sin internet')):
            r = self.client.post(reverse('vouchers:aprobar', args=[voucher.pk]), follow=True)
        voucher.refresh_from_db()
        self.assertEqual(voucher.estado, Voucher.Estado.ACTIVO)
        self.assertIn('no se pudo mandar', r.content.decode().lower())

    def test_el_detalle_muestra_el_voucher_dibujado(self):
        voucher = services.aprobar(self._voucher(), usuario=self.user)
        r = self.client.get(reverse('vouchers:detalle', args=[voucher.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn(voucher.imagen.url, r.content.decode())
