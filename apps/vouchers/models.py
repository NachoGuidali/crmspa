import secrets

from django.db import models


def generar_codigo():
    """Código legible tipo SPA-XXXX-XXXX."""
    alfabeto = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    parte = lambda: ''.join(secrets.choice(alfabeto) for _ in range(4))
    return f'SPA-{parte()}-{parte()}'


class Voucher(models.Model):
    class Estado(models.TextChoices):
        ACTIVO = 'activo', 'Activo'
        CANJEADO = 'canjeado', 'Canjeado'
        VENCIDO = 'vencido', 'Vencido'
        CANCELADO = 'cancelado', 'Cancelado'

    codigo = models.CharField(max_length=20, unique=True, default=generar_codigo, editable=False, db_index=True)
    circuito = models.ForeignKey(
        'circuitos.Circuito', on_delete=models.PROTECT, related_name='vouchers',
        help_text='Circuito que regala este voucher.',
    )
    monto = models.DecimalField(max_digits=10, decimal_places=2)

    comprador_nombre = models.CharField(max_length=150)
    comprador_telefono = models.CharField(max_length=20, blank=True)
    comprador_email = models.EmailField(blank=True)

    destinatario_nombre = models.CharField(max_length=150, blank=True, help_text='A quién se regala (opcional).')
    mensaje_regalo = models.TextField(blank=True)

    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.ACTIVO, db_index=True)
    fecha_compra = models.DateField(auto_now_add=True)
    fecha_vencimiento = models.DateField(help_text='Hasta cuándo se puede canjear.')

    reserva_canje = models.ForeignKey(
        'reservas.Reserva', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    canjeado_at = models.DateTimeField(null=True, blank=True)

    medio_pago = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Gift voucher'
        verbose_name_plural = 'Gift vouchers'

    def __str__(self):
        return f'{self.codigo} — {self.circuito.nombre}'

    @property
    def vigente(self):
        from django.utils import timezone
        return self.estado == self.Estado.ACTIVO and self.fecha_vencimiento >= timezone.localdate()
