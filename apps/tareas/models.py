from django.conf import settings
from django.db import models
from django.utils import timezone


class Tarea(models.Model):
    class Tipo(models.TextChoices):
        LLAMADA = 'llamada', 'Llamada'
        WHATSAPP = 'whatsapp', 'WhatsApp'
        PREPARACION = 'preparacion', 'Preparación de sala'
        SEGUIMIENTO = 'seguimiento', 'Seguimiento'
        OTRO = 'otro', 'Otro'

    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        COMPLETADA = 'completada', 'Completada'
        VENCIDA = 'vencida', 'Vencida'

    contacto = models.ForeignKey(
        'contactos.Contacto', null=True, blank=True, on_delete=models.SET_NULL, related_name='tareas'
    )
    asignado_a = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='tareas'
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.SEGUIMIENTO)
    descripcion = models.TextField()
    fecha_programada = models.DateTimeField()
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True)
    resultado = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fecha_programada']
        verbose_name = 'Tarea'
        verbose_name_plural = 'Tareas'

    def __str__(self):
        return f'{self.get_tipo_display()} — {self.fecha_programada:%d/%m %H:%M}'

    @property
    def vencida(self):
        return self.estado == self.Estado.PENDIENTE and self.fecha_programada < timezone.now()
