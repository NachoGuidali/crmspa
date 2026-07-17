from django.conf import settings
from django.db import models


class Campana(models.Model):
    class Modo(models.TextChoices):
        SEGMENTO = 'segmento', 'Por segmento (filtros automáticos)'
        MANUAL = 'manual', 'Selección manual de contactos'

    class Estado(models.TextChoices):
        BORRADOR = 'borrador', 'Borrador'
        PROGRAMADA = 'programada', 'Programada'
        EN_EJECUCION = 'en_ejecucion', 'En ejecución'
        COMPLETADA = 'completada', 'Completada'

    nombre = models.CharField(max_length=200)
    plantilla = models.ForeignKey('whatsapp.PlantillaMensaje', on_delete=models.PROTECT, related_name='campanas')
    modo_seleccion = models.CharField(max_length=10, choices=Modo.choices, default=Modo.SEGMENTO)

    # Segmento (filtros automáticos)
    filtro_etiquetas = models.ManyToManyField('contactos.Etiqueta', blank=True, related_name='campanas')
    filtro_dias_inactividad = models.PositiveIntegerField(
        null=True, blank=True, help_text='Solo contactos sin reservas en los últimos N días.'
    )
    filtro_circuito = models.ForeignKey(
        'circuitos.Circuito', null=True, blank=True, on_delete=models.SET_NULL,
        help_text='Solo contactos que alguna vez reservaron este circuito.',
    )
    filtro_min_reservas = models.PositiveIntegerField(
        null=True, blank=True, help_text='Solo contactos con al menos N reservas (clientes frecuentes).'
    )
    filtro_con_email = models.BooleanField(
        default=False, help_text='Solo contactos que tienen email cargado.'
    )
    # Filtro por campo personalizado
    filtro_campo = models.ForeignKey(
        'contactos.CampoPersonalizado', null=True, blank=True, on_delete=models.SET_NULL,
        help_text='Filtrar por un campo personalizado del contacto.',
    )
    filtro_campo_operador = models.CharField(max_length=10, blank=True)
    filtro_campo_valor = models.CharField(max_length=200, blank=True)

    # Selección manual
    contactos_ids = models.JSONField(default=list, blank=True)

    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.BORRADOR)
    fecha_programada = models.DateTimeField(null=True, blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    total_destinatarios = models.PositiveIntegerField(default=0)
    enviados = models.PositiveIntegerField(default=0)
    errores = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Campaña'
        verbose_name_plural = 'Campañas'

    def __str__(self):
        return self.nombre

    def destinatarios_queryset(self):
        """Contactos objetivo de la campaña (aplica todos los filtros del segmento)."""
        from datetime import timedelta

        from django.db.models import Count, Max
        from django.utils import timezone

        from apps.contactos.filtros import aplicar_filtro_campo
        from apps.contactos.models import Contacto

        # Las campañas son difusión/marketing: respetan la preferencia de promociones.
        if self.modo_seleccion == self.Modo.MANUAL:
            return Contacto.objects.filter(pk__in=self.contactos_ids or [], recibir_promociones=True)

        qs = Contacto.objects.filter(recibir_promociones=True)
        etiquetas = list(self.filtro_etiquetas.values_list('id', flat=True))
        if etiquetas:
            qs = qs.filter(etiquetas__in=etiquetas).distinct()
        if self.filtro_circuito_id:
            qs = qs.filter(reservas__circuito_id=self.filtro_circuito_id).distinct()
        if self.filtro_dias_inactividad:
            limite = timezone.localdate() - timedelta(days=self.filtro_dias_inactividad)
            qs = qs.annotate(ultima=Max('reservas__fecha')).filter(
                models.Q(ultima__isnull=True) | models.Q(ultima__lt=limite)
            )
        if self.filtro_min_reservas:
            qs = qs.annotate(n_reservas=Count('reservas')).filter(n_reservas__gte=self.filtro_min_reservas)
        if self.filtro_con_email:
            qs = qs.exclude(email='')
        if self.filtro_campo_id:
            qs = aplicar_filtro_campo(qs, self.filtro_campo, self.filtro_campo_operador, self.filtro_campo_valor)
        return qs.distinct()


class EnvioCampana(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        ENVIADO = 'enviado', 'Enviado'
        ERROR = 'error', 'Error'

    campana = models.ForeignKey(Campana, on_delete=models.CASCADE, related_name='envios')
    contacto = models.ForeignKey('contactos.Contacto', on_delete=models.CASCADE, related_name='+')
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    detalle = models.TextField(blank=True)
    enviado_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-enviado_at']
        verbose_name = 'Envío de campaña'
        verbose_name_plural = 'Envíos de campaña'

    def __str__(self):
        return f'{self.campana} → {self.contacto} ({self.estado})'
