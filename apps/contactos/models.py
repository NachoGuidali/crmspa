from django.conf import settings
from django.db import models
from django.utils.text import slugify

from utils.phone import normalize_ar_phone


class CampoPersonalizado(models.Model):
    """Campo extra configurable para los contactos (ej. 'Aniversario', 'Cómo nos conoció').
    Los valores se guardan en Contacto.datos_extra, indexados por slug."""

    class Tipo(models.TextChoices):
        TEXTO = 'texto', 'Texto'
        NUMERO = 'numero', 'Número'
        FECHA = 'fecha', 'Fecha'
        BOOLEANO = 'booleano', 'Sí / No'
        LISTA = 'lista', 'Lista de opciones'

    nombre = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, editable=False)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.TEXTO)
    opciones = models.JSONField(
        default=list, blank=True,
        help_text='Para tipo "Lista": una opción por línea.',
    )
    requerido = models.BooleanField(default=False)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['orden', 'nombre']
        verbose_name = 'Campo personalizado'
        verbose_name_plural = 'Campos personalizados'

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.nombre) or 'campo'
            slug, n = base, 1
            while CampoPersonalizado.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def coerce(self, raw):
        """Convierte el valor crudo (de un form) al tipo JSON que se guarda."""
        if raw in (None, ''):
            return None
        if self.tipo == self.Tipo.NUMERO:
            try:
                num = float(raw)
                return int(num) if num.is_integer() else num
            except (TypeError, ValueError):
                return None
        if self.tipo == self.Tipo.BOOLEANO:
            return str(raw).lower() in ('true', '1', 'on', 'si', 'sí', 'yes')
        # fecha (ISO 'YYYY-MM-DD'), texto, lista → string
        return str(raw)

    def formato(self, valor):
        """Representación legible para mostrar en pantalla."""
        if valor in (None, ''):
            return '—'
        if self.tipo == self.Tipo.BOOLEANO:
            return 'Sí' if valor else 'No'
        return str(valor)


class Etiqueta(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=7, default='#6b7280', help_text='Color hex, ej. #6b7280')

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Etiqueta'
        verbose_name_plural = 'Etiquetas'

    def __str__(self):
        return self.nombre


class Contacto(models.Model):
    nombre = models.CharField(max_length=150)
    telefono = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    etiquetas = models.ManyToManyField(Etiqueta, blank=True, related_name='contactos')
    datos_extra = models.JSONField(
        default=dict, blank=True,
        help_text='Valores de los campos personalizados, indexados por slug.',
    )
    recibir_recordatorios = models.BooleanField(
        default=True, verbose_name='Recibir recordatorios',
        help_text='Recordatorios de turno, aviso de seña y ofertas de lista de espera.',
    )
    recibir_promociones = models.BooleanField(
        default=True, verbose_name='Recibir promociones',
        help_text='Reactivación, cumpleaños y campañas de difusión.',
    )
    fecha_alta = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha_alta']
        verbose_name = 'Contacto'
        verbose_name_plural = 'Contactos'

    def __str__(self):
        return f'{self.nombre} ({self.telefono})'

    def save(self, *args, **kwargs):
        if self.telefono:
            self.telefono = normalize_ar_phone(self.telefono)
        super().save(*args, **kwargs)

    def campos_extra(self):
        """Lista de (campo, valor_formateado) de los campos personalizados activos."""
        datos = self.datos_extra or {}
        return [
            (campo, campo.formato(datos.get(campo.slug)))
            for campo in CampoPersonalizado.objects.filter(activo=True)
        ]


class NotaContacto(models.Model):
    contacto = models.ForeignKey(Contacto, on_delete=models.CASCADE, related_name='notas')
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    texto = models.TextField(help_text='Alergias, preferencias, ocasión especial, etc.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Nota de contacto'
        verbose_name_plural = 'Notas de contacto'

    def __str__(self):
        return f'Nota de {self.contacto.nombre} ({self.created_at:%Y-%m-%d})'
