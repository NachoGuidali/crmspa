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

    dias_tarifa_finde = models.JSONField(
        default=list, blank=True,
        help_text='Días de la semana que cobran tarifa de fin de semana (0=lunes … 6=domingo). '
                  'Vacío = sábado y domingo. En este spa: viernes, sábado y domingo → [4, 5, 6].',
    )

    recargo_feriado_porcentaje = models.DecimalField(
        max_digits=5, decimal_places=2, default=10,
        verbose_name='Recargo por feriado (%)',
        help_text='Porcentaje que se suma al precio del día cuando la fecha es feriado. Se '
                  'aplica SOBRE la tarifa que ya le corresponde a ese día: si el feriado cae '
                  'un sábado, es precio de finde + este %; si cae un día de semana, es precio '
                  'de semana + este %. Un feriado puntual puede llevar su propio porcentaje '
                  'distinto (Configuración → Feriados).',
    )

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
        blank=True,
        help_text='Texto de la política que se le muestra al cliente. Ej. "La seña se reembolsa '
                  'solo si cancelás dentro de las 24 hs posteriores al pago."',
    )
    horas_reembolso_desde_pago = models.PositiveIntegerField(
        default=24, verbose_name='Horas de reembolso desde el pago',
        help_text='La seña se reembolsa SOLO si la reserva se cancela dentro de esta cantidad de '
                  'horas contadas DESDE EL PAGO de la seña (no desde la fecha del turno). '
                  'Pasado ese plazo, la seña queda retenida. Default: 24.',
    )

    # --- Datos que se le mandan al cliente en los mensajes automáticos ---
    # Viven acá y no dentro del texto de cada plantilla: así se escriben una vez y los reusan
    # la confirmación de reserva y los recordatorios de 24h y 2h.
    direccion = models.CharField(
        max_length=250, blank=True,
        help_text='Dirección tal cual querés que la lea el cliente. Podés dejarla vacía y usar '
                  'solo el link del mapa.',
    )
    mapa_url = models.URLField(
        max_length=500, blank=True, verbose_name='Link del mapa',
        help_text='Link de Google Maps al spa. Es lo que le llega al cliente para llegar: '
                  'toca y le abre el GPS.',
    )
    como_llegar = models.TextField(
        blank=True, verbose_name='Cómo llegar (referencias)',
        help_text='Referencias prácticas del acceso: por dónde entrar, estado del camino, qué '
                  'mirar. Ej. "Los últimos metros son camino de tierra: si llovió, vení con '
                  'tiempo". Evita llamados y llegadas tarde.',
    )
    url_politicas = models.URLField(
        max_length=500, blank=True, verbose_name='Link a las políticas',
        help_text='Página de políticas de reserva y cancelación. Se incluye en la confirmación '
                  'para que el cliente las tenga a mano desde el principio.',
    )

    # ── Salida de mails (SMTP) ───────────────────────────────────────────────
    # Se configura acá y no en el .env para no tener que entrar al servidor cada vez que
    # cambia una casilla. Si queda vacío, se usa lo que haya configurado el servidor.
    smtp_host = models.CharField(
        max_length=200, blank=True, verbose_name='Servidor SMTP',
        help_text='Ej. smtp.gmail.com. Vacío = se usa lo configurado en el servidor.',
    )
    smtp_puerto = models.PositiveIntegerField(
        default=587, verbose_name='Puerto', help_text='587 con TLS (lo habitual) o 465 con SSL.',
    )
    smtp_usuario = models.CharField(
        max_length=200, blank=True, verbose_name='Usuario', help_text='Normalmente la casilla completa.',
    )
    smtp_password = models.CharField(
        max_length=200, blank=True, verbose_name='Contraseña',
        help_text='En Gmail NO va la contraseña de la cuenta: hay que generar una "contraseña '
                  'de aplicación" desde la seguridad de Google.',
    )
    smtp_tls = models.BooleanField(
        default=True, verbose_name='Usar TLS',
        help_text='Destildar solo si el servidor pide SSL directo (puerto 465).',
    )
    smtp_remitente = models.CharField(
        max_length=200, blank=True, verbose_name='Remitente',
        help_text='Desde qué dirección salen los avisos. Vacío = el usuario de arriba.',
    )

    email_notificaciones = models.CharField(
        max_length=500, blank=True, verbose_name='Email de notificaciones (respaldo)',
        help_text='Lo que usa un motivo que todavía no tiene destinatarios propios. Para elegir '
                  'quién recibe qué —y sumar avisos por WhatsApp— andá a Configuración → '
                  'Avisos internos.',
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


    def conexion_email(self):
        """La conexión SMTP a usar: la cargada acá, o la del servidor si está vacía."""
        from django.core.mail import get_connection

        if not self.smtp_host:
            return get_connection()      # lo que diga el .env
        # El backend se nombra explícito: si no, manda el EMAIL_BACKEND del entorno (en
        # desarrollo es la consola) y los datos cargados acá se ignorarían en silencio.
        return get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=self.smtp_host, port=self.smtp_puerto,
            username=self.smtp_usuario, password=self.smtp_password,
            use_tls=self.smtp_tls, use_ssl=(not self.smtp_tls and self.smtp_puerto == 465),
        )

    def remitente(self):
        from django.conf import settings

        return self.smtp_remitente or self.smtp_usuario or settings.DEFAULT_FROM_EMAIL


class AvisoInterno(models.Model):
    """Aviso al EQUIPO cuando pasa algo en el CRM (no es un mensaje al cliente).

    Uno por motivo, para poder elegir por separado quién se entera de qué: la confirmación de
    una reserva le puede llegar al dueño por mail y a recepción por WhatsApp, y el pedido de
    atención humana solo a quien esté atendiendo.

    El texto se escribe acá, con variables entre llaves: `{cliente}`, `{fecha}`, etc. Las que no
    existan para ese motivo quedan vacías, no rompen el aviso.
    """

    class Evento(models.TextChoices):
        RESERVA_NUEVA = 'reserva_nueva', 'Reserva nueva del bot'
        COMPROBANTE_POR_VERIFICAR = 'comprobante_por_verificar', 'Comprobante para verificar'
        RESERVA_CONFIRMADA = 'reserva_confirmada', 'Reserva confirmada'
        RESERVA_CANCELADA = 'reserva_cancelada', 'Reserva cancelada'
        ATENCION_HUMANA = 'atencion_humana', 'Conversación que necesita a una persona'
        BOT_CAIDO = 'bot_caido', 'El bot no pudo responder (falla técnica)'

    # Variables que puede usar el texto de cada motivo. Se muestran en el formulario.
    VARIABLES = {
        'reserva_nueva': ['cliente', 'telefono', 'email', 'circuito', 'fecha', 'turno', 'personas',
                          'total', 'sena', 'medio_pago', 'estado', 'extras', 'menu', 'link'],
        'comprobante_por_verificar': ['cliente', 'telefono', 'circuito', 'fecha', 'turno', 'personas',
                                      'total', 'sena', 'link'],
        'reserva_confirmada': ['cliente', 'telefono', 'email', 'circuito', 'fecha', 'turno', 'personas',
                               'total', 'sena', 'medio_pago', 'extras', 'menu', 'link'],
        'reserva_cancelada': ['cliente', 'telefono', 'circuito', 'fecha', 'turno', 'personas',
                              'motivo', 'destino_sena', 'link'],
        'atencion_humana': ['cliente', 'telefono', 'motivo', 'link'],
        'bot_caido': ['cliente', 'telefono', 'motivo', 'link'],
    }

    evento = models.CharField(max_length=40, choices=Evento.choices, unique=True)
    activo = models.BooleanField(
        default=True, help_text='Destildado, este motivo no avisa a nadie.',
    )
    emails = models.CharField(
        max_length=500, blank=True, verbose_name='Emails',
        help_text='Uno o varios separados por coma. Vacío = no se manda mail por este motivo.',
    )
    asunto = models.CharField(
        max_length=200, blank=True,
        help_text='Asunto del mail. Admite variables. Vacío = el nombre del motivo.',
    )
    cuerpo_email = models.TextField(
        blank=True, verbose_name='Texto del mail',
        help_text='Vacío = se manda el detalle completo que arma el sistema.',
    )
    whatsapps = models.CharField(
        max_length=500, blank=True, verbose_name='WhatsApps',
        help_text='Números separados por coma (ej. 1151587091). Vacío = no se manda WhatsApp.',
    )
    texto_whatsapp = models.TextField(
        blank=True, verbose_name='Texto del WhatsApp',
        help_text='Vacío = el mismo texto del mail. Conviene uno más corto.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['evento']
        verbose_name = 'Aviso interno'
        verbose_name_plural = 'Avisos internos'

    def __str__(self):
        return self.get_evento_display()

    def lista_emails(self):
        return [e.strip() for e in (self.emails or '').split(',') if e.strip()]

    def lista_whatsapps(self):
        return [t.strip() for t in (self.whatsapps or '').split(',') if t.strip()]

    def variables_disponibles(self):
        return self.VARIABLES.get(self.evento, [])
