import secrets

from django.conf import settings
from django.db import models


def generar_codigo():
    """Código legible tipo SPA-XXXX-XXXX."""
    alfabeto = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    parte = lambda: ''.join(secrets.choice(alfabeto) for _ in range(4))
    return f'SPA-{parte()}-{parte()}'


class Voucher(models.Model):
    class Estado(models.TextChoices):
        # El bot lo armó y le pasó los datos para transferir; todavía no pagó nada.
        PENDIENTE_PAGO = 'pendiente_pago', 'Pendiente de pago'
        # Mandó el comprobante y espera que alguien del spa lo mire. No vale para canjear.
        PENDIENTE_APROBACION = 'pendiente_aprobacion', 'Pendiente de aprobación'
        # Pagado y entregado: este es el único estado con el que se puede canjear.
        ACTIVO = 'activo', 'Activo'
        CANJEADO = 'canjeado', 'Canjeado'
        VENCIDO = 'vencido', 'Vencido'
        CANCELADO = 'cancelado', 'Cancelado'

    class Origen(models.TextChoices):
        MANUAL = 'manual', 'Carga manual'
        WHATSAPP_BOT = 'whatsapp_bot', 'Bot de WhatsApp'

    codigo = models.CharField(max_length=20, unique=True, default=generar_codigo, editable=False, db_index=True)
    circuito = models.ForeignKey(
        'circuitos.Circuito', on_delete=models.PROTECT, related_name='vouchers',
        help_text='Circuito que regala este voucher.',
    )
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    # El voucher se vende al precio de fin de semana, así sirve para cualquier día y no hay
    # diferencias que cobrar al canjearlo. La cantidad va guardada porque en el grupal y en la
    # despedida el precio es por persona: sin esto, un voucher de 3 se canjeaba para 8.
    personas = models.PositiveIntegerField(
        default=1, help_text='Para cuántas personas es el voucher (define el precio).',
    )

    comprador_nombre = models.CharField(max_length=150)
    comprador_telefono = models.CharField(max_length=20, blank=True)
    comprador_email = models.EmailField(blank=True)

    destinatario_nombre = models.CharField(max_length=150, blank=True, help_text='A quién se regala (opcional).')
    mensaje_regalo = models.TextField(blank=True)

    estado = models.CharField(max_length=24, choices=Estado.choices, default=Estado.ACTIVO, db_index=True)
    origen = models.CharField(max_length=20, choices=Origen.choices, default=Origen.MANUAL)
    fecha_compra = models.DateField(auto_now_add=True)
    fecha_vencimiento = models.DateField(help_text='Hasta cuándo se puede canjear.')

    # Comprobante de la transferencia. Es FileField y no ImageField a propósito: muchos bancos
    # dan el comprobante en PDF, y con ImageField Django lo rechaza.
    comprobante = models.FileField(upload_to='vouchers/comprobantes/', null=True, blank=True)

    # El voucher dibujado (apps/vouchers/diseno.py). Se guarda en vez de generarse en cada
    # pedido para que sea siempre el mismo archivo: el que se mandó por WhatsApp es el que se
    # descarga después desde el CRM.
    imagen = models.ImageField(upload_to='vouchers/', blank=True)
    archivo_pdf = models.FileField(upload_to='vouchers/', blank=True)

    reserva_canje = models.ForeignKey(
        'reservas.Reserva', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    canjeado_at = models.DateTimeField(null=True, blank=True)

    aprobado_at = models.DateTimeField(null=True, blank=True)
    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    enviado_at = models.DateTimeField(null=True, blank=True)

    medio_pago = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Gift voucher'
        verbose_name_plural = 'Gift vouchers'

    def __str__(self):
        return f'{self.codigo} — {self.circuito.nombre}'

    @property
    def vencido(self):
        from django.utils import timezone
        return self.fecha_vencimiento < timezone.localdate()

    @property
    def vigente(self):
        """Pagado, entregado y todavía dentro de la fecha: se puede canjear."""
        return self.estado == self.Estado.ACTIVO and not self.vencido

    @property
    def espera_revision(self):
        return self.estado == self.Estado.PENDIENTE_APROBACION

    @property
    def pagado(self):
        """Ya se cobró: sirve para no mostrar 'esperando la transferencia' donde no va."""
        return self.estado in (self.Estado.ACTIVO, self.Estado.CANJEADO, self.Estado.VENCIDO)
