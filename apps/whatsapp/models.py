from django.conf import settings
from django.core.cache import cache
from django.db import models


class ConfiguracionWhatsApp(models.Model):
    """Singleton — credenciales de Evolution API, editables desde el admin."""

    evolution_api_url = models.CharField(max_length=200, blank=True, verbose_name='Evolution API URL')
    evolution_api_key = models.CharField(max_length=200, blank=True, verbose_name='API Key')
    evolution_instance_name = models.CharField(
        max_length=100, blank=True, default='crmspa', verbose_name='Nombre de instancia'
    )
    webhook_token = models.CharField(
        max_length=100, blank=True, verbose_name='Token de webhook',
        help_text='Token secreto que Evolution API envía en el header al hacer webhook.',
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

    @classmethod
    def get_config(cls):
        config = cache.get('whatsapp_config')
        if config is None:
            try:
                obj = cls.objects.get(pk=1)
                config = {
                    'evolution_api_url': obj.evolution_api_url,
                    'evolution_api_key': obj.evolution_api_key,
                    'evolution_instance_name': obj.evolution_instance_name,
                    'webhook_token': obj.webhook_token,
                }
            except cls.DoesNotExist:
                config = {}
            cache.set('whatsapp_config', config, 300)
        return config

    @classmethod
    def get_setting(cls, key):
        config = cls.get_config()
        if key in config:
            db_val = config[key]
            if key == 'webhook_token':
                return db_val
            if db_val:
                return db_val
        settings_map = {
            'evolution_api_url': 'EVOLUTION_API_URL',
            'evolution_api_key': 'EVOLUTION_API_KEY',
            'evolution_instance_name': 'EVOLUTION_INSTANCE',
        }
        return getattr(settings, settings_map.get(key, ''), '')


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

    class Meta:
        ordering = ['-ultimo_mensaje_at']
        verbose_name = 'Conversación'
        verbose_name_plural = 'Conversaciones'

    def __str__(self):
        return self.nombre_contacto or self.telefono

    def get_display_name(self):
        return self.nombre_contacto or self.telefono


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
    media_url = models.URLField(blank=True, max_length=2000)
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

    nombre = models.CharField(max_length=100, unique=True)
    tipo = models.CharField(max_length=30, choices=Tipo.choices, default=Tipo.OTRO)
    cuerpo = models.TextField(help_text='Usar {{variable}} para valores dinámicos, ej. {{nombre}}, {{circuito}}, {{fecha}}.')
    variables = models.JSONField(default=list, blank=True, help_text='Lista de nombres de variables disponibles.')
    activa = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Plantilla de mensaje'
        verbose_name_plural = 'Plantillas de mensaje'

    def __str__(self):
        return self.nombre

    def render(self, contexto: dict):
        import re

        def replace(match):
            key = match.group(1)
            val = contexto.get(key)
            return str(val) if val is not None else f'{{{{{key}}}}}'

        return re.sub(r'\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}', replace, self.cuerpo)


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
