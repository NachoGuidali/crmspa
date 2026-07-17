from django.db import models


class Automatizacion(models.Model):
    class Tipo(models.TextChoices):
        RECORDATORIO_24H = 'recordatorio_24h', 'Recordatorio de turno 24h antes'
        RECORDATORIO_2H = 'recordatorio_2h', 'Recordatorio de turno 2h antes'
        RECLAMO_SENA = 'reclamo_sena', 'Reclamo de seña / liberación de cupo por vencimiento'
        ENCUESTA_SATISFACCION = 'encuesta_satisfaccion', 'Encuesta de satisfacción post-circuito'
        REACTIVACION_INACTIVOS = 'reactivacion_inactivos', 'Reactivación de clientes inactivos'
        ALERTA_CUPO = 'alerta_cupo', 'Alerta interna de cupo completo / último lugar'
        LISTA_ESPERA = 'lista_espera', 'Oferta automática de lista de espera'
        CUMPLEANOS = 'cumpleanos', 'Recordatorio de cumpleaños con oferta'

    tipo = models.CharField(max_length=30, choices=Tipo.choices, unique=True)
    activa = models.BooleanField(default=True)
    parametros = models.JSONField(
        default=dict, blank=True,
        help_text='Ej. {"horas_antes": 24} o {"horas_plazo_sena": 2} o {"dias_inactividad": 60}.',
    )
    plantilla = models.ForeignKey(
        'whatsapp.PlantillaMensaje', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='automatizaciones',
        help_text='Plantilla de mensaje que usa esta automatización, si aplica.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['tipo']
        verbose_name = 'Automatización'
        verbose_name_plural = 'Automatizaciones'

    def __str__(self):
        return self.get_tipo_display()


class AutomatizacionLog(models.Model):
    class Resultado(models.TextChoices):
        EXITOSO = 'exitoso', 'Exitoso'
        ERROR = 'error', 'Error'
        OMITIDO = 'omitido', 'Omitido'

    automatizacion = models.ForeignKey(
        Automatizacion, on_delete=models.CASCADE, related_name='logs'
    )
    contacto = models.ForeignKey(
        'contactos.Contacto', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    reserva = models.ForeignKey(
        'reservas.Reserva', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    resultado = models.CharField(max_length=10, choices=Resultado.choices)
    detalle = models.TextField(blank=True)
    ejecutado_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-ejecutado_at']
        verbose_name = 'Log de automatización'
        verbose_name_plural = 'Logs de automatización'

    def __str__(self):
        return f'{self.automatizacion} — {self.resultado} — {self.ejecutado_at:%Y-%m-%d %H:%M}'
