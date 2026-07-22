from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.utils import timezone


class ConfiguracionWhatsApp(models.Model):
    """Singleton — proveedor de WhatsApp (Evolution API o Meta Cloud API) y sus credenciales.
    Editable desde Configuración → WhatsApp (o el admin)."""

    class Proveedor(models.TextChoices):
        EVOLUTION = 'evolution', 'Evolution API (no oficial, con QR)'
        META = 'meta', 'Meta Cloud API (oficial)'

    proveedor = models.CharField(
        max_length=20, choices=Proveedor.choices, default=Proveedor.EVOLUTION,
        verbose_name='Proveedor de WhatsApp',
        help_text='Qué canal usa el CRM para enviar/recibir. Evolution conecta escaneando un QR; '
                  'Meta es la API oficial (requiere número y app aprobados en Meta).',
    )

    # --- Evolution API ---
    evolution_api_url = models.CharField(max_length=200, blank=True, verbose_name='Evolution API URL')
    evolution_api_key = models.CharField(max_length=200, blank=True, verbose_name='API Key')
    evolution_instance_name = models.CharField(
        max_length=100, blank=True, default='crmspa', verbose_name='Nombre de instancia'
    )
    webhook_token = models.CharField(
        max_length=100, blank=True, verbose_name='Token de webhook',
        help_text='Token secreto que Evolution API envía en el header al hacer webhook.',
    )

    # --- Meta Cloud API ---
    meta_phone_number_id = models.CharField(
        max_length=50, blank=True, verbose_name='Phone Number ID',
        help_text='ID del número en Meta (WhatsApp → API Setup).',
    )
    meta_waba_id = models.CharField(
        max_length=50, blank=True, verbose_name='WhatsApp Business Account ID',
    )
    meta_access_token = models.CharField(
        max_length=500, blank=True, verbose_name='Access Token',
        help_text='Token permanente del System User con permiso whatsapp_business_messaging.',
    )
    meta_app_secret = models.CharField(
        max_length=100, blank=True, verbose_name='App Secret',
        help_text='Para validar la firma X-Hub-Signature-256 de los webhooks.',
    )
    meta_verify_token = models.CharField(
        max_length=100, blank=True, verbose_name='Verify Token',
        help_text='Token que vos elegís y cargás en Meta al configurar el webhook (verificación GET).',
    )
    meta_api_version = models.CharField(
        max_length=10, blank=True, default='v21.0', verbose_name='Versión de la Graph API',
    )

    class Meta:
        verbose_name = 'Configuración WhatsApp'
        verbose_name_plural = 'Configuración WhatsApp'

    def __str__(self):
        return 'Configuración WhatsApp'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete('whatsapp_config')

    _CAMPOS_CONFIG = [
        'proveedor',
        'evolution_api_url', 'evolution_api_key', 'evolution_instance_name', 'webhook_token',
        'meta_phone_number_id', 'meta_waba_id', 'meta_access_token', 'meta_app_secret',
        'meta_verify_token', 'meta_api_version',
    ]

    @classmethod
    def get_config(cls):
        config = cache.get('whatsapp_config')
        if config is None:
            try:
                obj = cls.objects.get(pk=1)
                config = {campo: getattr(obj, campo) for campo in cls._CAMPOS_CONFIG}
            except cls.DoesNotExist:
                config = {}
            cache.set('whatsapp_config', config, 300)
        return config

    @classmethod
    def get_setting(cls, key):
        config = cls.get_config()
        if key in config:
            db_val = config[key]
            # Estos campos valen aunque estén vacíos (no caen al fallback de settings).
            if key in ('webhook_token', 'proveedor') or db_val:
                return db_val
        settings_map = {
            'evolution_api_url': 'EVOLUTION_API_URL',
            'evolution_api_key': 'EVOLUTION_API_KEY',
            'evolution_instance_name': 'EVOLUTION_INSTANCE',
        }
        return getattr(settings, settings_map.get(key, ''), '')

    @classmethod
    def get_proveedor(cls):
        return cls.get_setting('proveedor') or cls.Proveedor.EVOLUTION


class Conversacion(models.Model):
    class Estado(models.TextChoices):
        NUEVA_CONSULTA = 'nueva_consulta', 'Nueva consulta'
        EN_GESTION = 'en_gestion', 'En gestión'
        RESERVA_CONFIRMADA = 'reserva_confirmada', 'Reserva confirmada'
        REQUIERE_ATENCION_HUMANA = 'requiere_atencion_humana', 'Requiere atención humana'

    telefono = models.CharField(max_length=20, unique=True, db_index=True)
    nombre_contacto = models.CharField(max_length=200, blank=True)
    contacto = models.OneToOneField(
        'contactos.Contacto', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='conversacion_whatsapp',
    )
    agente = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='conversaciones',
    )
    estado = models.CharField(
        max_length=30, choices=Estado.choices, default=Estado.NUEVA_CONSULTA, db_index=True
    )
    bot_activo = models.BooleanField(
        default=True, verbose_name='Bot n8n activo',
        help_text='Si está en False, n8n no debe responderle más a este contacto (handoff a un humano).',
    )
    ultimo_mensaje_at = models.DateTimeField(null=True, blank=True)
    mensajes_no_leidos = models.PositiveIntegerField(default=0)
    archivada = models.BooleanField(default=False, db_index=True)
    ventana_expira_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Hasta cuándo se puede mandar texto libre por Meta (24hs desde el último '
                  'mensaje entrante del cliente). Fuera de esa ventana, Meta exige plantilla.',
    )
    # Estado del flujo conversacional que maneja el bot de n8n. Es una bolsa libre de datos
    # (estado_flujo, personas, tipo_propuesta, fecha_solicitada, intentos_fecha,
    # horario_confirmado, datos_contacto, override_regla, reserva_creada). El CRM es la única
    # fuente de verdad: el bot la lee y la va actualizando por la API de conversaciones.
    estado_bot = models.JSONField(default=dict, blank=True)

    # Campos que el bot maneja dentro de estado_bot pero que tienen efectos/consultas propias.
    ESTADO_FLUJO_DERIVADO = 'derivado'
    CAMPOS_FLUJO = [
        'estado_flujo', 'personas', 'tipo_propuesta', 'fecha_solicitada', 'intentos_fecha',
        'horario_confirmado', 'datos_contacto', 'override_regla', 'reserva_creada',
    ]

    class Meta:
        ordering = ['-ultimo_mensaje_at']
        verbose_name = 'Conversación'
        verbose_name_plural = 'Conversaciones'

    def __str__(self):
        return self.nombre_contacto or self.telefono

    def get_display_name(self):
        return self.nombre_contacto or self.telefono

    @property
    def ventana_abierta(self):
        """True si estamos dentro de las 24hs desde el último mensaje del cliente.
        Solo importa para Meta: fuera de la ventana hay que mandar plantilla."""
        return bool(self.ventana_expira_at and self.ventana_expira_at > timezone.now())

    @property
    def reserva_creada(self):
        return bool(self.estado_bot.get('reserva_creada'))

    @property
    def estado_flujo(self):
        return self.estado_bot.get('estado_flujo')

    def estado_bot_publico(self):
        """El diccionario plano que consume el bot (mergea la bolsa con los campos derivados)."""
        data = {campo: self.estado_bot.get(campo) for campo in self.CAMPOS_FLUJO}
        data.setdefault('estado_flujo', 'nuevo')
        data['reserva_creada'] = self.reserva_creada
        data['override_regla'] = bool(self.estado_bot.get('override_regla'))
        data.update({
            'telefono': self.telefono,
            'nombre': self.nombre_contacto,
            # bot_bloqueado es la cara pública de bot_activo: si el bot está apagado (handoff
            # o reserva ya hecha), está "bloqueado" y no debe responder.
            'bot_bloqueado': not self.bot_activo,
            'last_message_ts': self.ultimo_mensaje_at,
        })
        return data


class Mensaje(models.Model):
    class Tipo(models.TextChoices):
        TEXTO = 'text', 'Texto'
        IMAGEN = 'image', 'Imagen'
        DOCUMENTO = 'document', 'Documento'
        AUDIO = 'audio', 'Audio'
        VIDEO = 'video', 'Video'
        PLANTILLA = 'template', 'Plantilla'
        INTERACTIVO = 'interactive', 'Interactivo'

    class Direccion(models.TextChoices):
        ENTRANTE = 'in', 'Entrante'
        SALIENTE = 'out', 'Saliente'

    class Status(models.TextChoices):
        PENDIENTE = 'pending', 'Pendiente'
        ENVIADO = 'sent', 'Enviado'
        ENTREGADO = 'delivered', 'Entregado'
        LEIDO = 'read', 'Leído'
        FALLIDO = 'failed', 'Fallido'

    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='mensajes')
    contacto = models.ForeignKey(
        'contactos.Contacto', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='mensajes_whatsapp',
    )
    whatsapp_message_id = models.CharField(max_length=100, blank=True, db_index=True)
    direccion = models.CharField(max_length=3, choices=Direccion.choices)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.TEXTO)
    contenido = models.TextField(blank=True)
    media_url = models.CharField(blank=True, max_length=2000)
    media_id = models.CharField(max_length=200, blank=True)
    media_mime = models.CharField(max_length=100, blank=True)
    media_filename = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDIENTE)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    timestamp = models.DateTimeField()
    error_detalle = models.TextField(blank=True)

    class Meta:
        ordering = ['timestamp']
        verbose_name = 'Mensaje'
        verbose_name_plural = 'Mensajes'
        constraints = [
            # Evita mensajes entrantes duplicados si Evolution reenvía el mismo webhook.
            models.UniqueConstraint(
                fields=['whatsapp_message_id'],
                condition=models.Q(direccion='in') & ~models.Q(whatsapp_message_id=''),
                name='uniq_mensaje_entrante_wamid',
            ),
        ]

    def __str__(self):
        return f'[{self.get_direccion_display()}] {self.conversacion} — {self.timestamp}'


class PlantillaMensaje(models.Model):
    class Tipo(models.TextChoices):
        BIENVENIDA = 'bienvenida', 'Bienvenida'
        CONFIRMACION_RESERVA = 'confirmacion_reserva', 'Confirmación de reserva'
        RECORDATORIO_24H = 'recordatorio_24h', 'Recordatorio 24h antes'
        RECORDATORIO_2H = 'recordatorio_2h', 'Recordatorio 2h antes'
        RECLAMO_SENA = 'reclamo_sena', 'Reclamo de seña'
        CANCELACION = 'cancelacion', 'Cancelación'
        ENCUESTA = 'encuesta', 'Encuesta de satisfacción'
        REACTIVACION = 'reactivacion', 'Reactivación de inactivos'
        CUMPLEANOS = 'cumpleanos', 'Cumpleaños'
        LISTA_ESPERA = 'lista_espera', 'Lista de espera'
        OTRO = 'otro', 'Otro'

    class MetaCategoria(models.TextChoices):
        UTILITY = 'utility', 'Utilidad (recordatorios, confirmaciones)'
        MARKETING = 'marketing', 'Marketing (promociones)'
        AUTHENTICATION = 'authentication', 'Autenticación (códigos)'

    nombre = models.CharField(max_length=100, unique=True)
    tipo = models.CharField(max_length=30, choices=Tipo.choices, default=Tipo.OTRO)
    cuerpo = models.TextField(help_text='Usar {{variable}} para valores dinámicos, ej. {{nombre}}, {{circuito}}, {{fecha}}. '
                              'Para plantillas de Meta usar posicionales: {{1}}, {{2}}.')
    variables = models.JSONField(default=list, blank=True, help_text='Lista de nombres de variables disponibles.')
    activa = models.BooleanField(default=True)

    # --- Plantilla de Meta (HSM) para mandar fuera de la ventana de 24hs ---
    meta_nombre = models.CharField(
        max_length=100, blank=True,
        help_text='Nombre EXACTO de la plantilla aprobada en Meta (minúsculas y guiones bajos). '
                  'Si se deja vacío, se usa el "nombre" normalizado.',
    )
    meta_idioma = models.CharField(
        max_length=10, default='es_AR',
        help_text='Código de idioma de la plantilla en Meta (ej. es_AR, es, en_US).',
    )
    meta_categoria = models.CharField(
        max_length=20, choices=MetaCategoria.choices, default=MetaCategoria.UTILITY,
    )
    meta_estado = models.CharField(
        max_length=20, blank=True,
        help_text='Estado de aprobación en Meta (APPROVED / PENDING / REJECTED). Se sincroniza.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Plantilla de mensaje'
        verbose_name_plural = 'Plantillas de mensaje'

    def __str__(self):
        return self.nombre

    def get_meta_nombre(self) -> str:
        import re
        return self.meta_nombre or re.sub(r'[^a-z0-9_]', '_', self.nombre.lower())

    @property
    def aprobada_en_meta(self) -> bool:
        return self.meta_estado.upper() == 'APPROVED'

    def render(self, contexto: dict):
        import re

        def replace(match):
            key = match.group(1)
            val = contexto.get(key)
            return str(val) if val is not None else f'{{{{{key}}}}}'

        return re.sub(r'\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}', replace, self.cuerpo)

    def render_valores(self, valores) -> str:
        """Reemplaza los posicionales {{1}}, {{2}}, ... por los valores en orden. Se usa para el
        preview, para el texto que se guarda en el inbox, y para el fallback de Evolution."""
        import re

        vals = list(valores or [])

        def repl(match):
            idx = int(match.group(1)) - 1
            return str(vals[idx]) if 0 <= idx < len(vals) else match.group(0)

        return re.sub(r'\{\{\s*(\d+)\s*\}\}', repl, self.cuerpo)


class RespuestaRapida(models.Model):
    """Respuestas predefinidas que recepción inserta en el inbox."""

    titulo = models.CharField(max_length=100)
    atajo = models.CharField(max_length=30, unique=True, help_text='Palabra clave sin barra, ej. "precios".')
    texto = models.TextField()
    activa = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['titulo']
        verbose_name = 'Respuesta rápida'
        verbose_name_plural = 'Respuestas rápidas'

    def __str__(self):
        return f'/{self.atajo} — {self.titulo}'


class LogEnvioWhatsApp(models.Model):
    """Log de cada llamada saliente a Evolution API (envío de mensajes)."""

    endpoint = models.CharField(max_length=200)
    request_body = models.TextField(blank=True)
    response_status = models.IntegerField(null=True)
    response_body = models.TextField(blank=True)
    duracion_ms = models.IntegerField(null=True)
    exitoso = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Log de envío WhatsApp'
        verbose_name_plural = 'Logs de envío WhatsApp'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.endpoint} — {self.response_status}'
