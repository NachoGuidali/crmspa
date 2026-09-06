from django.db import models

DIAS_SEMANA = [
    (0, 'Lunes'),
    (1, 'Martes'),
    (2, 'Miércoles'),
    (3, 'Jueves'),
    (4, 'Viernes'),
    (5, 'Sábado'),
    (6, 'Domingo'),
]

TODOS_LOS_DIAS = [d for d, _ in DIAS_SEMANA]


class Turno(models.Model):
    nombre = models.CharField(max_length=100, help_text='Ej. "Turno mañana"')
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    dias_aplicables = models.JSONField(
        default=list,
        help_text='Lista de días de semana en que aplica (0=lunes ... 6=domingo). Vacío = todos los días.',
    )
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['hora_inicio']
        verbose_name = 'Turno'
        verbose_name_plural = 'Turnos'

    def __str__(self):
        return f'{self.nombre} ({self.hora_inicio:%H:%M}-{self.hora_fin:%H:%M})'

    def aplica_en(self, fecha):
        dias = self.dias_aplicables or TODOS_LOS_DIAS
        return fecha.weekday() in dias


class Feriado(models.Model):
    """Día feriado. Un feriado NO cambia la tarifa del día: le suma un recargo encima.

    Es la diferencia importante con la versión anterior, que cobraba tarifa de finde. Con
    recargo, un feriado que cae sábado sale precio de finde + %, y uno que cae un miércoles
    sale precio de semana + %. Antes, un feriado en sábado no cobraba nada extra (ya estaba
    en tarifa de finde) y uno entre semana saltaba a la tarifa de finde entera.
    """

    class Modo(models.TextChoices):
        RECARGO = 'recargo', 'Abre con recargo sobre el precio del día'
        CERRADO = 'cerrado', 'Cerrado (no se atiende)'

    fecha = models.DateField()
    descripcion = models.CharField(max_length=150, blank=True)
    recurrente_anual = models.BooleanField(
        default=False, help_text='Si está marcado, se repite todos los años en el mismo mes/día.'
    )
    modo = models.CharField(
        max_length=20, choices=Modo.choices, default=Modo.RECARGO,
        help_text='"Abre con recargo": se atiende y se cobra la tarifa normal del día '
                  '(semana o finde, según qué día caiga) más el recargo. '
                  '"Cerrado": ese día no se atiende.',
    )
    recargo_porcentaje = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        verbose_name='Recargo propio (%)',
        help_text='Dejalo vacío para usar el recargo general de Configuración del negocio. '
                  'Completalo solo si ESTE feriado cobra un porcentaje distinto '
                  '(ej. 31 de diciembre).',
    )

    class Meta:
        ordering = ['fecha']
        verbose_name = 'Feriado'
        verbose_name_plural = 'Feriados'

    def __str__(self):
        return f'{self.fecha} — {self.descripcion}' if self.descripcion else str(self.fecha)

    def cae_en(self, fecha):
        if self.recurrente_anual:
            return (self.fecha.month, self.fecha.day) == (fecha.month, fecha.day)
        return self.fecha == fecha

    @property
    def porcentaje_efectivo(self):
        """El recargo que se aplica de verdad: el propio del feriado, o el general si no tiene.

        Un feriado cerrado no cobra nada, así que devuelve 0.
        """
        from decimal import Decimal

        if self.modo != self.Modo.RECARGO:
            return Decimal('0')
        if self.recargo_porcentaje is not None:
            return self.recargo_porcentaje

        from apps.configuracion.models import ConfiguracionNegocio
        return ConfiguracionNegocio.get_solo().recargo_feriado_porcentaje or Decimal('0')


class BloqueoManual(models.Model):
    circuito = models.ForeignKey(
        'circuitos.Circuito', on_delete=models.CASCADE, null=True, blank=True,
        related_name='bloqueos', help_text='Vacío = bloquea todos los circuitos.',
    )
    fecha = models.DateField()
    turno = models.ForeignKey(
        Turno, on_delete=models.CASCADE, null=True, blank=True,
        help_text='Vacío = bloquea el día completo.',
    )
    motivo = models.CharField(max_length=200, help_text='Ej. mantenimiento, limpieza entre turnos, feriado.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'Bloqueo manual'
        verbose_name_plural = 'Bloqueos manuales'

    def __str__(self):
        alcance = self.circuito.nombre if self.circuito else 'Todos los circuitos'
        return f'{self.fecha} — {alcance} — {self.motivo}'
