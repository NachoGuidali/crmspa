"""Transcripción de las notas de voz entrantes.

El punto de todo esto: antes un audio llegaba al inbox como "[Audio]" y el bot contestaba
"¿me lo escribís?". Ahora el texto queda en el mensaje, lo lee el equipo y lo entiende el
bot — y si la transcripción falla, vuelve a quedar exactamente como antes.
"""
import os
import shutil
import tempfile
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.whatsapp import services, transcripcion, webhook
from apps.whatsapp.models import ConfiguracionWhatsApp, Conversacion, Mensaje

TMP = tempfile.mkdtemp()
OGG = b'OggS' + b'\x00' * 4000          # pesa lo suficiente para no caer en el filtro de ruido


def payload_audio(message_id='AUDIO1', segundos=12, telefono='5493815551234'):
    return {
        'event': 'messages.upsert',
        'data': {
            'key': {'id': message_id, 'remoteJid': f'{telefono}@s.whatsapp.net', 'fromMe': False},
            'messageType': 'audioMessage',
            'message': {'audioMessage': {
                'url': 'https://mmg.whatsapp.net/v/encriptado.enc',
                'mimetype': 'audio/ogg; codecs=opus', 'seconds': segundos, 'ptt': True,
            }},
            'messageTimestamp': int(timezone.now().timestamp()),
            'pushName': 'Ana',
        },
    }


@override_settings(MEDIA_ROOT=TMP, MEDIA_URL='/media/',
                   TRANSCRIPCION_API_KEY='sk-test', TRANSCRIPCION_PROVEEDOR='openai',
                   TRANSCRIPCION_MODELO='gpt-transcribe', N8N_WEBHOOK_URL='')
class TranscripcionTest(TestCase):
    def setUp(self):
        ConfiguracionWhatsApp.objects.create(pk=1, transcribir_audios=True,
                                             transcripcion_max_segundos=300)

    def _guardar_audio_en_disco(self, conv_pk, nombre='AUDIO1.ogg'):
        d = os.path.join(TMP, 'uploads', f'conv_{conv_pk}')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, nombre), 'wb') as f:
            f.write(OGG)
        return f'/media/uploads/conv_{conv_pk}/{nombre}'

    # ── 1. el webhook ahora lee la duración del audio ───────────────────────
    def test_el_webhook_extrae_la_duracion(self):
        [m] = webhook.parse_incoming_webhook(payload_audio(segundos=42))
        self.assertEqual(m['type'], 'audio')
        self.assertEqual(m['media_duracion'], 42)
        self.assertEqual(m['content'], '[Audio]')

    def test_duracion_ausente_no_rompe(self):
        p = payload_audio()
        del p['data']['message']['audioMessage']['seconds']
        [m] = webhook.parse_incoming_webhook(p)
        self.assertEqual(m['media_duracion'], 0)

    # ── 2. el camino completo: audio entra, texto queda ─────────────────────
    def _procesar(self, texto_transcripto, **kw):
        [m] = webhook.parse_incoming_webhook(payload_audio(**kw))
        url = self._guardar_audio_en_disco(1)
        with patch('apps.whatsapp.sender.download_and_save_media', return_value=url), \
             patch('apps.whatsapp.transcripcion.transcribir',
                   return_value=texto_transcripto) as stt:
            resultado = services._guardar_mensaje_entrante(m)
        return resultado, stt

    def test_transcribe_y_lo_guarda_en_el_mensaje(self):
        resultado, stt = self._procesar('Hola, somos 4 amigas para el sábado')
        self.assertTrue(stt.called)
        msg = Mensaje.objects.get(whatsapp_message_id='AUDIO1')
        self.assertEqual(msg.tipo, Mensaje.Tipo.AUDIO)
        self.assertEqual(msg.contenido, '[Audio]')          # lo que WhatsApp mandó, intacto
        self.assertEqual(msg.transcripcion, 'Hola, somos 4 amigas para el sábado')
        # Lo que viaja al bot es el texto, no el marcador.
        self.assertEqual(resultado['message'], 'Hola, somos 4 amigas para el sábado')
        self.assertTrue(resultado['es_audio'])
        self.assertTrue(resultado['transcripto'])

    def test_si_falla_queda_como_antes(self):
        resultado, _ = self._procesar('')
        msg = Mensaje.objects.get(whatsapp_message_id='AUDIO1')
        self.assertEqual(msg.transcripcion, '')
        self.assertEqual(resultado['message'], '[Audio]')
        self.assertTrue(resultado['es_audio'])
        self.assertFalse(resultado['transcripto'])

    def test_una_excepcion_no_rompe_el_webhook(self):
        [m] = webhook.parse_incoming_webhook(payload_audio())
        url = self._guardar_audio_en_disco(1)
        with patch('apps.whatsapp.sender.download_and_save_media', return_value=url), \
             patch('apps.whatsapp.transcripcion.transcribir', side_effect=RuntimeError('boom')):
            resultado = services._guardar_mensaje_entrante(m)
        self.assertEqual(resultado['message'], '[Audio]')
        self.assertTrue(Mensaje.objects.filter(whatsapp_message_id='AUDIO1').exists())

    # ── 3. el historial que lee el bot ──────────────────────────────────────
    def test_el_historial_manda_la_transcripcion(self):
        conv = Conversacion.objects.create(telefono='+5493815551234')
        Mensaje.objects.create(
            conversacion=conv, direccion=Mensaje.Direccion.ENTRANTE, tipo=Mensaje.Tipo.AUDIO,
            contenido='[Audio]', transcripcion='quiero reservar para el 15',
            media_url='/media/uploads/conv_1/a.ogg', timestamp=timezone.now())
        from apps.integraciones.models import ApiKey
        clave = ApiKey.objects.create(nombre='test')
        r = self.client.get(
            reverse('conversacion_mensajes', args=['5493815551234']),
            HTTP_X_API_KEY=str(clave.key))
        self.assertEqual(r.status_code, 200)
        fila = r.json()[0]
        self.assertEqual(fila['texto'], 'quiero reservar para el 15')
        self.assertEqual(fila['tipo'], 'audio')

    # ── 4. los filtros ──────────────────────────────────────────────────────
    def test_apagado_no_llama_a_la_api(self):
        ConfiguracionWhatsApp.objects.filter(pk=1).update(transcribir_audios=False)
        with patch('apps.whatsapp.transcripcion.requests.post') as post:
            self.assertEqual(transcripcion.transcribir(OGG), '')
            self.assertFalse(post.called)

    @override_settings(TRANSCRIPCION_API_KEY='')
    def test_sin_clave_no_llama_a_la_api(self):
        with patch('apps.whatsapp.transcripcion.requests.post') as post:
            self.assertEqual(transcripcion.transcribir(OGG), '')
            self.assertFalse(post.called)

    def test_audio_demasiado_corto(self):
        with patch('apps.whatsapp.transcripcion.requests.post') as post:
            self.assertEqual(transcripcion.transcribir(b'OggS'), '')
            self.assertFalse(post.called)

    def test_audio_mas_largo_que_el_tope(self):
        ConfiguracionWhatsApp.objects.filter(pk=1).update(transcripcion_max_segundos=60)
        with patch('apps.whatsapp.transcripcion.requests.post') as post:
            self.assertEqual(transcripcion.transcribir(OGG, segundos=120), '')
            self.assertFalse(post.called)

    def test_tope_en_cero_es_sin_tope(self):
        ConfiguracionWhatsApp.objects.filter(pk=1).update(transcripcion_max_segundos=0)
        with patch('apps.whatsapp.transcripcion.requests.post') as post:
            post.return_value.ok = True
            post.return_value.json.return_value = {'text': 'un audio larguísimo'}
            self.assertEqual(transcripcion.transcribir(OGG, segundos=9999), 'un audio larguísimo')

    # ── 5. las alucinaciones de Whisper con el silencio ─────────────────────
    def test_descarta_las_alucinaciones(self):
        for basura in ('Subtítulos realizados por la comunidad de Amara.org',
                       'Gracias por ver el video', '¡Suscríbete al canal!', '.', 'www.algo.com'):
            with patch('apps.whatsapp.transcripcion.requests.post') as post:
                post.return_value.ok = True
                post.return_value.json.return_value = {'text': basura}
                self.assertEqual(transcripcion.transcribir(OGG), '', basura)

    def test_no_descarta_texto_real(self):
        with patch('apps.whatsapp.transcripcion.requests.post') as post:
            post.return_value.ok = True
            post.return_value.json.return_value = {'text': '  Hola,   quería   consultar \n '}
            self.assertEqual(transcripcion.transcribir(OGG), 'Hola, quería consultar')

    # ── 6. lo que se le manda a la API ──────────────────────────────────────
    def test_parametros_de_la_llamada(self):
        with patch('apps.whatsapp.transcripcion.requests.post') as post:
            post.return_value.ok = True
            post.return_value.json.return_value = {'text': 'ok'}
            transcripcion.transcribir(OGG, mime='audio/ogg; codecs=opus')
            url = post.call_args[0][0]
            datos = post.call_args[1]['data']
            self.assertIn('api.openai.com', url)
            self.assertEqual(datos['model'], 'gpt-transcribe')
            self.assertEqual(datos['language'], 'es')
            self.assertIn('seña', datos['prompt'])          # vocabulario del spa
            self.assertIn('tina finlandesa', datos['prompt'])
            self.assertEqual(post.call_args[1]['headers']['Authorization'], 'Bearer sk-test')

    @override_settings(TRANSCRIPCION_PROVEEDOR='groq', TRANSCRIPCION_MODELO='')
    def test_groq_usa_su_endpoint_y_su_modelo_por_defecto(self):
        with patch('apps.whatsapp.transcripcion.requests.post') as post:
            post.return_value.ok = True
            post.return_value.json.return_value = {'text': 'ok'}
            transcripcion.transcribir(OGG)
            self.assertIn('api.groq.com', post.call_args[0][0])
            self.assertEqual(post.call_args[1]['data']['model'], 'whisper-large-v3-turbo')

    def test_error_de_la_api_devuelve_vacio(self):
        with patch('apps.whatsapp.transcripcion.requests.post') as post:
            post.return_value.ok = False
            post.return_value.status_code = 429
            post.return_value.text = 'rate limit'
            self.assertEqual(transcripcion.transcribir(OGG), '')

    # ── 7. una imagen no se manda a transcribir ─────────────────────────────
    def test_una_imagen_no_pasa_por_el_transcriptor(self):
        p = payload_audio(message_id='IMG1')
        p['data']['messageType'] = 'imageMessage'
        p['data']['message'] = {'imageMessage': {'url': 'x', 'mimetype': 'image/jpeg',
                                                 'caption': 'mirá'}}
        [m] = webhook.parse_incoming_webhook(p)
        with patch('apps.whatsapp.sender.download_and_save_media', return_value='/media/x.jpg'), \
             patch('apps.whatsapp.transcripcion.transcribir') as stt:
            resultado = services._guardar_mensaje_entrante(m)
        self.assertFalse(stt.called)
        self.assertEqual(resultado['message'], 'mirá')
        self.assertFalse(resultado['es_audio'])

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)



class EventosQueNoSonMensajesTest(TestCase):
    """Una reacción con un emoji no es un mensaje.

    Caía en el default del mapa de tipos, se guardaba como `[reactionMessage]` y el bot la
    leía como un archivo: le contestaba "no puedo ver archivos por acá" a alguien que solo
    había puesto un pulgar arriba.
    """

    def payload(self, tipo, cuerpo=None):
        return {
            'event': 'messages.upsert',
            'data': {
                'key': {'id': f'ID-{tipo}', 'remoteJid': '5493815551234@s.whatsapp.net',
                        'fromMe': False},
                'messageType': tipo,
                'message': cuerpo or {tipo: {'text': '👍'}},
                'messageTimestamp': int(timezone.now().timestamp()),
                'pushName': 'Ana',
            },
        }

    def test_la_reaccion_no_genera_mensaje(self):
        self.assertEqual(webhook.parse_incoming_webhook(self.payload('reactionMessage')), [])

    def test_otros_eventos_de_protocolo_tampoco(self):
        for tipo in ('pollUpdateMessage', 'protocolMessage', 'senderKeyDistributionMessage'):
            with self.subTest(tipo=tipo):
                self.assertEqual(webhook.parse_incoming_webhook(self.payload(tipo)), [])

    def test_un_texto_normal_sigue_pasando(self):
        payload = self.payload('conversation', {'conversation': 'Hola, quiero reservar'})
        mensajes = webhook.parse_incoming_webhook(payload)
        self.assertEqual(len(mensajes), 1)
        self.assertEqual(mensajes[0]['content'], 'Hola, quiero reservar')
        self.assertEqual(mensajes[0]['type'], 'text')

    def test_un_tipo_desconocido_sigue_llegando_como_marcador(self):
        """No se silencia todo lo que no se entiende: si es un mensaje de verdad y no lo
        sabemos leer, tiene que llegar al inbox para que el equipo lo vea."""
        mensajes = webhook.parse_incoming_webhook(self.payload('loQueVengaMessage'))
        self.assertEqual(len(mensajes), 1)
        self.assertEqual(mensajes[0]['content'], '[loQueVengaMessage]')
