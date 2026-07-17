from django.core.cache import cache
from django.db import models

from apps.turnero.models import DIAS_SEMANA, TODOS_LOS_DIAS


class ConfiguracionNegocio(models.Model):
    """Singleton con la configuración general del negocio."""

    nombre_negocio = models.CharField(max_length=150, default='Spa de Campo')

    dias_laborables = models.JSONField(
        default=list, blank=True,
        help_text='Días de semana en que el negocio atiende (0=lunes ... 6=domingo). Vacío = todos.',
    )
    horario_atencion_desde = models.TimeField(null=True, blank=True)
    horario_atencion_hasta = models.TimeField(null=True, blank=True)

    reserva_exclusiva_por_turno = models.BooleanField(
        default=True,
        verbose_name='Reserva exclusiva por turno',
        help_text='Si está activo, cada turno (mañana/tarde) admite UNA sola reserva en todo el '
                  'spa, sin importar el circuito: quien contrata no comparte el turno con otros '
                  'clientes. El tamaño del grupo se limita a la capacidad del circuito. '
                  'Si se desactiva, cada circuito lleva su propio cupo por separado.',
    )

    plazo_pago_sena_horas = models.PositiveIntegerField(
        default=2, help_text='Horas para pagar la seña antes de liberar el cupo automáticamente.'
    )
    politica_cancelacion = models.TextField(
        blank=True, help_text='Ej. "Reembolso de seña hasta 24h antes del turno."'
    )
    horas_cancelacion_con_reembolso = models.PositiveIntegerField(
        default=24, help_text='Horas de anticipación para cancelar con reembolso de seña.'
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración del negocio'
        verbose_name_plural = 'Configuración del negocio'

    def __str__(self):
        return self.nombre_negocio

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete('configuracion_negocio')

    @classmethod
    def get_solo(cls):
        obj = cache.get('configuracion_negocio')
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set('configuracion_negocio', obj, 300)
        return obj

    def dias_laborables_display(self):
        dias = self.dias_laborables or TODOS_LOS_DIAS
        nombres = dict(DIAS_SEMANA)
        return ', '.join(nombres[d] for d in dias)

    def esta_en_horario_atencion(self, cuando=None):
        """True si `cuando` (datetime local) cae dentro del horario y días de atención.
        Si no hay horario configurado, se asume atención 24h en los días laborables."""
        from django.utils import timezone

        cuando = cuando or timezone.localtime()
        dias = self.dias_laborables or TODOS_LOS_DIAS
        if cuando.weekday() not in dias:
            return False
        if self.horario_atencion_desde and self.horario_atencion_hasta:
            hora = cuando.time()
            return self.horario_atencion_desde <= hora <= self.horario_atencion_hasta
        return True
