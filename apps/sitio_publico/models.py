from django.db import models
from django.utils import timezone


class PopupWebQuerySet(models.QuerySet):
    def vigentes(self, ahora=None):
        """Popups prendidos y dentro de su ventana de fechas.

        `desde`/`hasta` son opcionales: vacío = sin límite de ese lado. Así un popup permanente
        ("Reservá tu fecha") convive con uno de campaña ("Promo día de la madre, 10 al 20/10").
        """
        ahora = ahora or timezone.now()
        return (
            self.filter(activo=True)
            .filter(models.Q(desde__isnull=True) | models.Q(desde__lte=ahora))
            .filter(models.Q(hasta__isnull=True) | models.Q(hasta__gte=ahora))
        )


class PopupWeb(models.Model):
    """Cartel emergente de la web pública (spacuatroestaciones.com), editable desde el CRM.

    La web es estática: no la sirve Django. El puente es `GET /api/v1/publico/popup/`, que
    `web/crm-popup.js` consulta al cargar la página. Prender, apagar, cambiar el texto o la
    foto acá se ve en la web sin tocar el HTML ni volver a deployar.
    """

    titulo = models.CharField(max_length=120, help_text='Título grande del cartel.')
    mensaje = models.TextField(
        blank=True, help_text='Texto debajo del título. Opcional si la foto ya dice todo.',
    )
    imagen = models.ImageField(
        upload_to='publico/popups/', blank=True, null=True,
        help_text='Foto o flyer de la promo. Se muestra arriba del texto. Opcional. '
                  'Ojo: esta imagen es PÚBLICA (la ve cualquiera que entre a la web).',
    )
    cta_texto = models.CharField(
        max_length=60, blank=True, verbose_name='Texto del botón',
        help_text='Ej. "Reservar por WhatsApp". Vacío = sin botón.',
    )
    cta_url = models.URLField(
        max_length=500, blank=True, verbose_name='Link del botón',
        help_text='A dónde lleva el botón. Ej. el link de WhatsApp del spa.',
    )

    activo = models.BooleanField(
        default=False,
        help_text='La llave maestra: apagado, el cartel no se muestra aunque esté en fecha.',
    )
    desde = models.DateTimeField(
        null=True, blank=True, verbose_name='Mostrar desde',
        help_text='Vacío = desde ya. Sirve para dejar la promo cargada y que arranque sola.',
    )
    hasta = models.DateTimeField(
        null=True, blank=True, verbose_name='Mostrar hasta',
        help_text='Vacío = sin fecha de fin. Pasada esta fecha deja de mostrarse solo.',
    )

    repetir_horas = models.PositiveIntegerField(
        default=24, verbose_name='Repetir cada (horas)',
        help_text='Si alguien lo cierra, cuántas horas esperar antes de volver a mostrárselo. '
                  '0 = mostrar siempre, en cada visita.',
    )
    orden = models.PositiveIntegerField(
        default=0, help_text='Si hay varios vigentes, se muestra el de menor orden.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PopupWebQuerySet.as_manager()

    class Meta:
        ordering = ['orden', '-created_at']
        verbose_name = 'Popup de la web'
        verbose_name_plural = 'Popups de la web'

    def __str__(self):
        return self.titulo

    @property
    def vigente(self):
        """¿Se está mostrando ahora? Es lo mismo que pregunta `vigentes()`, para una sola fila."""
        ahora = timezone.now()
        return bool(
            self.activo
            and (self.desde is None or self.desde <= ahora)
            and (self.hasta is None or self.hasta >= ahora)
        )

    @property
    def estado_legible(self):
        """Por qué se muestra o no, para la lista del CRM."""
        if not self.activo:
            return 'Apagado'
        ahora = timezone.now()
        if self.desde and self.desde > ahora:
            return f'Programado ({timezone.localtime(self.desde):%d/%m %H:%M})'
        if self.hasta and self.hasta < ahora:
            return f'Vencido ({timezone.localtime(self.hasta):%d/%m %H:%M})'
        return 'EN VIVO'
