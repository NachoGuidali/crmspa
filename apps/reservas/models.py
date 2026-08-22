from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ReservaQuerySet(models.QuerySet):
    def ocupando_cupo(self, ahora=None):
        """Reservas que **en este momento** bloquean el slot.

        Mirar solo el estado no alcanza. Una reserva en espera de pago (`pendiente_sena` o
        `pendiente_pago`) es un **hold temporal**: deja de ocupar el cupo apenas pasa
        `vencimiento_sena`, aunque la tarea de Celery que la cancela todavía no haya corrido.
        Si no la excluyéramos acá, el turno quedaría trabado hasta la próxima pasada (hasta
        15 minutos de más sobre un hold de 2 horas) y, si esa automatización estuviera
        apagada, para siempre.

        `pendiente_aprobacion` NO es un hold temporal: ahí el cliente ya pagó y subió el
        comprobante, y lo que falta es que alguien del spa lo mire. Ese cupo se mantiene.

        Un hold sin `vencimiento_sena` tampoco se libera solo (NULL no matchea el `<`): ante la
        duda, el cupo se conserva.
        """
        ahora = ahora or timezone.now()
        return self.filter(estado__in=Reserva.ESTADOS_QUE_OCUPAN_CUPO).exclude(
            estado__in=Reserva.ESTADOS_HOLD_TEMPORAL,
            vencimiento_sena__lt=ahora,
        )

    def holds_vencidos(self, ahora=None):
        """Holds temporales cuyo plazo de pago ya pasó: hay que cancelarlos y liberar el cupo."""
        ahora = ahora or timezone.now()
        return self.filter(
            estado__in=Reserva.ESTADOS_HOLD_TEMPORAL,
            vencimiento_sena__lt=ahora,
        )


class Reserva(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE_PAGO = 'pendiente_pago', 'Pendiente de pago (Mercado Pago)'
        PENDIENTE_APROBACION = 'pendiente_aprobacion', 'Pendiente de aprobación (transferencia)'
        PENDIENTE_SENA = 'pendiente_sena', 'Pendiente de seña'
        CONFIRMADO = 'confirmado', 'Confirmado'
        COMPLETADO = 'completado', 'Completado'
        CANCELADO = 'cancelado', 'Cancelado'
        NO_SHOW = 'no_show', 'No-show'

    # Estados que reservan el cupo (aunque el pago todavía no esté confirmado/verificado).
    ESTADOS_QUE_OCUPAN_CUPO = [
        Estado.PENDIENTE_PAGO, Estado.PENDIENTE_APROBACION, Estado.PENDIENTE_SENA,
        Estado.CONFIRMADO, Estado.COMPLETADO,
    ]

    # Holds temporales: el cupo está retenido mientras el cliente paga, y se libera solo al
    # vencer `vencimiento_sena`. `pendiente_aprobacion` queda afuera a propósito (ahí ya pagó
    # y espera revisión del staff, no hay nada que expirar).
    ESTADOS_HOLD_TEMPORAL = [Estado.PENDIENTE_SENA, Estado.PENDIENTE_PAGO]

    objects = ReservaQuerySet.as_manager()

    class MedioPago(models.TextChoices):
        EFECTIVO = 'efectivo', 'Efectivo'
        TRANSFERENCIA = 'transferencia', 'Transferencia'
        MERCADO_PAGO = 'mercado_pago', 'Mercado Pago'
        TARJETA = 'tarjeta', 'Tarjeta'
        OTRO = 'otro', 'Otro'

    class Origen(models.TextChoices):
        MANUAL = 'manual', 'Carga manual'
        WHATSAPP_BOT = 'whatsapp_bot', 'Bot de WhatsApp'

    contacto = models.ForeignKey(
        'contactos.Contacto', on_delete=models.PROTECT, related_name='reservas'
    )
    circuito = models.ForeignKey(
        'circuitos.Circuito', on_delete=models.PROTECT, related_name='reservas'
    )
    turno = models.ForeignKey(
        'turnero.Turno', on_delete=models.PROTECT, related_name='reservas'
    )
    fecha = models.DateField()

    cantidad_personas = models.PositiveIntegerField(default=1)
    acompanantes = models.JSONField(
        default=list, blank=True,
        help_text='Lista de nombres de acompañantes (no son contactos independientes).',
    )

    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE_SENA)

    precio_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monto_sena = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monto_pagado = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    medio_pago = models.CharField(max_length=20, choices=MedioPago.choices, blank=True)

    vencimiento_sena = models.DateTimeField(
        null=True, blank=True,
        help_text='Si vence sin pagar la seña, el cupo se libera automáticamente.',
    )
    sena_pagada_at = models.DateTimeField(
        null=True, blank=True, verbose_name='Seña pagada el',
        help_text='Cuándo se acreditó la seña. Es el punto de partida de la ventana de reembolso '
                  '(config: "Horas de reembolso desde el pago"). Nulo = la seña todavía no se pagó.',
    )
    sena_reembolsable = models.BooleanField(
        null=True, blank=True,
        help_text='Al cancelar: True si corresponde reembolsar la seña, False si queda retenida.',
    )

    origen = models.CharField(
        max_length=20, choices=Origen.choices, default=Origen.MANUAL,
        help_text='De dónde vino la reserva (carga manual del staff o bot de WhatsApp).',
    )
    resumen = models.TextField(
        blank=True, help_text='Resumen que arma el bot para mostrar en la tarjeta.',
    )
    comprobante = models.ImageField(
        upload_to='comprobantes/', null=True, blank=True,
        help_text='Comprobante de transferencia que sube el cliente por el bot.',
    )
    link_pago = models.URLField(
        blank=True, max_length=500, help_text='Link de pago de Mercado Pago.',
    )

    notas = models.TextField(blank=True)

    idempotency_key = models.CharField(
        max_length=100, null=True, blank=True, unique=True,
        help_text='Clave que manda el bot para que un reintento del mismo POST no cree una '
                  'reserva duplicada. Nulo en las reservas cargadas a mano.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha', 'turno']
        verbose_name = 'Reserva'
        verbose_name_plural = 'Reservas'
        indexes = [
            models.Index(fields=['circuito', 'fecha', 'turno']),
        ]

    def __str__(self):
        return f'{self.contacto.nombre} — {self.circuito.nombre} — {self.fecha}'

    @property
    def extras_total(self):
        """Suma de los extras/opcionales cargados a la reserva."""
        return sum((e.subtotal for e in self.extras.all()), 0)

    @property
    def total(self):
        """Total a pagar: precio del circuito + extras."""
        return (self.precio_total or 0) + self.extras_total

    @property
    def saldo(self):
        """Lo que falta cobrar: total (con extras) menos lo ya pagado."""
        return self.total - (self.monto_pagado or 0)

    @property
    def reembolso_vence_at(self):
        """Hasta cuándo se puede cancelar con reembolso de la seña. `None` si todavía no se pagó
        (sin pago no arranca el reloj)."""
        from datetime import timedelta

        from apps.configuracion.models import ConfiguracionNegocio

        if not self.sena_pagada_at:
            return None
        horas = ConfiguracionNegocio.get_solo().horas_reembolso_desde_pago
        return self.sena_pagada_at + timedelta(hours=horas)

    @property
    def en_ventana_de_reembolso(self):
        """True si en este momento la cancelación todavía daría derecho a reembolso."""
        from django.utils import timezone as _tz

        vence = self.reembolso_vence_at
        return bool(vence and _tz.now() <= vence)

    def clean(self):
        if not (self.circuito_id and self.fecha and self.turno_id):
            return

        from apps.configuracion.models import ConfiguracionNegocio
        config = ConfiguracionNegocio.get_solo()

        # Mínimo de personas del circuito (ej. Grupal: 3 a 8).
        if self.cantidad_personas < self.circuito.capacidad_minima:
            raise ValidationError(
                f'{self.circuito.nombre} requiere un mínimo de {self.circuito.capacidad_minima} '
                f'persona(s); indicaste {self.cantidad_personas}.'
            )

        if config.reserva_exclusiva_por_turno:
            # Modo spa exclusivo: una sola reserva por (fecha, turno) en todo el spa.
            if self.cantidad_personas > self.circuito.capacidad_maxima:
                raise ValidationError(
                    f'{self.circuito.nombre} admite hasta {self.circuito.capacidad_maxima} '
                    f'persona(s); pediste {self.cantidad_personas}.'
                )
            if self._slot_ocupado_por_otra_reserva():
                raise ValidationError(
                    f'El turno {self.turno.nombre} del {self.fecha} ya está reservado. '
                    f'En modo exclusivo el spa admite una sola reserva por turno.'
                )
        else:
            # Modo por circuito: cada circuito lleva su propio cupo.
            ocupacion = self._cupo_ocupado()
            if ocupacion > self.circuito.capacidad_maxima:
                raise ValidationError(
                    f'No hay cupo disponible: {ocupacion}/{self.circuito.capacidad_maxima} '
                    f'para {self.circuito.nombre} el {self.fecha} en el turno {self.turno.nombre}.'
                )

    def _slot_ocupado_por_otra_reserva(self):
        """Modo exclusivo: ¿hay OTRA reserva activa en este (fecha, turno), sin importar el circuito?"""
        qs = Reserva.objects.ocupando_cupo().filter(fecha=self.fecha, turno=self.turno)
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        return qs.exists()

    def _cupo_ocupado(self):
        qs = Reserva.objects.ocupando_cupo().filter(
            circuito=self.circuito, fecha=self.fecha, turno=self.turno,
        )
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        ocupadas = qs.aggregate(total=models.Sum('cantidad_personas'))['total'] or 0
        return ocupadas + self.cantidad_personas


class Pago(models.Model):
    class Tipo(models.TextChoices):
        SENA = 'sena', 'Seña'
        SALDO = 'saldo', 'Saldo'

    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name='pagos')
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    medio_pago = models.CharField(max_length=20, choices=Reserva.MedioPago.choices)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'Pago'
        verbose_name_plural = 'Pagos'

    def __str__(self):
        return f'{self.get_tipo_display()} ${self.monto} — {self.reserva}'


class ReservaExtra(models.Model):
    """Extra/opcional agregado a una reserva. Guarda nombre y precio del momento (snapshot)."""

    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name='extras')
    extra = models.ForeignKey('circuitos.Extra', null=True, blank=True, on_delete=models.SET_NULL)
    nombre = models.CharField(max_length=120)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    cantidad = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Extra de reserva'
        verbose_name_plural = 'Extras de reserva'

    def __str__(self):
        return f'{self.nombre} x{self.cantidad} — {self.reserva}'

    @property
    def subtotal(self):
        return self.precio_unitario * self.cantidad


class ListaEspera(models.Model):
    contacto = models.ForeignKey(
        'contactos.Contacto', on_delete=models.CASCADE, related_name='lista_espera'
    )
    circuito = models.ForeignKey(
        'circuitos.Circuito', on_delete=models.CASCADE, related_name='lista_espera'
    )
    fecha_deseada = models.DateField()
    turno = models.ForeignKey(
        'turnero.Turno', on_delete=models.SET_NULL, null=True, blank=True
    )
    notificado = models.BooleanField(default=False)
    ofrecido_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Cuándo se le ofreció el lugar liberado (hold temporal antes de pasar al siguiente).',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Lista de espera'
        verbose_name_plural = 'Lista de espera'

    def __str__(self):
        return f'{self.contacto.nombre} espera {self.circuito.nombre} el {self.fecha_deseada}'
