import uuid

from django.db import models


class ApiKey(models.Model):
    """Clave de API para que n8n (u otros clientes externos) consuman la API del CRM."""

    nombre = models.CharField(max_length=200, verbose_name='Nombre / origen')
    key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    activa = models.BooleanField(default=True, db_index=True)

    ultimo_uso_at = models.DateTimeField(null=True, blank=True)
    total_usos = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'API Key'
        verbose_name_plural = 'API Keys'
        ordering = ['-created_at']

    def __str__(self):
        estado = '✅' if self.activa else '🔴'
        return f'{estado} {self.nombre}'

    @property
    def key_display(self):
        return f'...{str(self.key)[-8:]}'


class WebhookLog(models.Model):
    """Log de cada request entrante a la API (llamadas de n8n, formulario público, etc.)."""

    class Status(models.TextChoices):
        OK = 'ok', 'OK'
        ERROR = 'error', 'Error'

    api_key = models.ForeignKey(
        ApiKey, null=True, blank=True, on_delete=models.SET_NULL, related_name='logs'
    )
    endpoint = models.CharField(max_length=200)
    method = models.CharField(max_length=10)
    ip = models.GenericIPAddressField(null=True, blank=True)
    request_body = models.TextField(blank=True)
    response_status = models.PositiveSmallIntegerField(default=200)
    response_body = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OK)
    contacto = models.ForeignKey(
        'contactos.Contacto', null=True, blank=True, on_delete=models.SET_NULL, related_name='webhook_logs'
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Log de webhook'
        verbose_name_plural = 'Logs de webhook'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.method} {self.endpoint} — {self.response_status}'
