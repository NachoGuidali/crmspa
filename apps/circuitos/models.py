from decimal import Decimal

from django.db import models


class Circuito(models.Model):
    class Tipo(models.TextChoices):
        INDIVIDUAL = 'individual', 'Individual'
        PAREJA = 'pareja', 'Pareja'
        GRUPAL = 'grupal', 'Grupal'
        PREMIUM = 'premium', 'Premium'

    class SenaTipo(models.TextChoices):
        MONTO = 'monto', 'Monto fijo'
        PORCENTAJE = 'porcentaje', 'Porcentaje del precio'

    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.INDIVIDUAL)
    duracion_minutos = models.PositiveIntegerField(default=60)
    capacidad_minima = models.PositiveIntegerField(
        default=1, help_text='Mínimo de personas para reservar este circuito (ej. Grupal: 3).'
    )
    capacidad_maxima = models.PositiveIntegerField(default=1)

    # Precio plano (circuitos de precio fijo, ej. Pareja). Para circuitos con tramos por
    # cantidad de personas (ej. Grupal), dejar vacío y cargar los tramos (TarifaCircuito).
    precio_semana = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    precio_finde = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Precio POR PERSONA para cada persona que supere el tramo más alto (solo circuitos con tramos).
    precio_persona_adicional_semana = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Precio por persona adicional (pasando el tramo más alto), en día de semana.',
    )
    precio_persona_adicional_finde = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Precio por persona adicional (pasando el tramo más alto), en fin de semana/feriado.',
    )

    sena_tipo = models.CharField(max_length=20, choices=SenaTipo.choices, default=SenaTipo.PORCENTAJE)
    sena_valor = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text='Si es porcentaje: número de 0 a 100. Si es monto fijo: importe en pesos.',
    )

    imagen = models.ImageField(upload_to='circuitos/', blank=True, null=True)
    activo = models.BooleanField(default=True, help_text='Si está inactivo, no se muestra en la web pública.')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Circuito'
        verbose_name_plural = 'Circuitos'

    def __str__(self):
        return self.nombre

    @staticmethod
    def es_finde(fecha):
        return fecha.weekday() >= 5  # sábado=5, domingo=6

    def _tramos(self):
        return list(self.tarifas.order_by('min_personas'))

    def personas_referencia(self):
        """Cantidad de personas 'de muestra' para mostrar un precio cuando no hay una reserva
        concreta (ej. listado de circuitos): el mínimo del tramo más bajo, o 1."""
        tramos = self._tramos()
        return tramos[0].min_personas if tramos else 1

    def precio_para(self, fecha, personas=1):
        """Precio TOTAL para esa fecha y cantidad de personas.

        - Sin tramos: precio plano (precio_semana/finde).
        - Con tramos: tarifa POR PERSONA del tramo que corresponde × personas; si supera el
          tramo más alto, se cobra el tramo más alto por su tope + la tarifa por persona
          adicional por cada persona de más.
        """
        from apps.turnero.services import es_dia_tarifa_finde
        finde = es_dia_tarifa_finde(fecha)
        tramos = self._tramos()

        if not tramos:
            base = self.precio_finde if finde else self.precio_semana
            return base or Decimal('0')

        campo = 'precio_persona_finde' if finde else 'precio_persona_semana'
        personas = max(int(personas or 1), 1)

        for t in tramos:
            if t.min_personas <= personas <= t.max_personas:
                return getattr(t, campo) * personas

        top = tramos[-1]
        if personas > top.max_personas:
            adicional = (self.precio_persona_adicional_finde if finde
                         else self.precio_persona_adicional_semana) or Decimal('0')
            return getattr(top, campo) * top.max_personas + adicional * (personas - top.max_personas)

        # Menos personas que el tramo más bajo → se cobra a la tarifa del tramo más bajo.
        return getattr(tramos[0], campo) * personas

    def precio_para_fecha(self, fecha, personas=None):
        if personas is None:
            personas = self.personas_referencia()
        return self.precio_para(fecha, personas)

    def monto_sena_para(self, fecha, personas=None):
        precio = self.precio_para_fecha(fecha, personas)
        if self.sena_tipo == self.SenaTipo.MONTO:
            return self.sena_valor
        return (precio * self.sena_valor / Decimal('100')).quantize(Decimal('0.01'))


class Extra(models.Model):
    """Adicional opcional que se puede sumar a una reserva (upsell): tina finlandesa,
    tabla de picada, minutos extra de masaje, etc."""

    nombre = models.CharField(max_length=120)
    descripcion = models.CharField(max_length=250, blank=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    por_persona = models.BooleanField(
        default=False, help_text='Si está activo, el precio se multiplica por la cantidad indicada.'
    )
    circuito = models.ForeignKey(
        'Circuito', null=True, blank=True, on_delete=models.CASCADE, related_name='extras',
        help_text='Dejar vacío para que el extra esté disponible en todos los circuitos.',
    )
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['orden', 'nombre']
        verbose_name = 'Extra / opcional'
        verbose_name_plural = 'Extras / opcionales'

    def __str__(self):
        return f'{self.nombre} (${self.precio:.0f})'


class TarifaCircuito(models.Model):
    """Tramo de precio POR PERSONA según el tamaño del grupo (ej. Grupal: 3-4, 5-6, 7-8)."""

    circuito = models.ForeignKey(Circuito, on_delete=models.CASCADE, related_name='tarifas')
    min_personas = models.PositiveIntegerField()
    max_personas = models.PositiveIntegerField()
    precio_persona_semana = models.DecimalField(max_digits=10, decimal_places=2)
    precio_persona_finde = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ['circuito', 'min_personas']
        verbose_name = 'Tramo de precio'
        verbose_name_plural = 'Tramos de precio'
        constraints = [
            models.UniqueConstraint(
                fields=['circuito', 'min_personas', 'max_personas'], name='uniq_tramo_circuito'
            ),
        ]

    def __str__(self):
        return f'{self.circuito.nombre}: {self.min_personas}-{self.max_personas}p'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.min_personas and self.max_personas and self.min_personas > self.max_personas:
            raise ValidationError('El mínimo de personas no puede ser mayor que el máximo.')
