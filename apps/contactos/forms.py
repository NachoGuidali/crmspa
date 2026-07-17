from django import forms

from apps.reservas.models import Pago, Reserva

from .models import CampoPersonalizado, Contacto, NotaContacto

EXTRA_PREFIX = 'extra__'


class ContactoForm(forms.ModelForm):
    class Meta:
        model = Contacto
        fields = ['nombre', 'telefono', 'email', 'fecha_nacimiento', 'etiquetas',
                  'recibir_recordatorios', 'recibir_promociones']
        widgets = {
            'fecha_nacimiento': forms.DateInput(attrs={'type': 'date'}),
            'etiquetas': forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        datos = (self.instance.datos_extra or {}) if self.instance else {}
        self._campos_extra = list(CampoPersonalizado.objects.filter(activo=True))
        for campo in self._campos_extra:
            self.fields[EXTRA_PREFIX + campo.slug] = self._build_field(campo, datos.get(campo.slug))

    def _build_field(self, campo, valor):
        req = campo.requerido
        T = CampoPersonalizado.Tipo
        if campo.tipo == T.NUMERO:
            return forms.FloatField(label=campo.nombre, required=req, initial=valor)
        if campo.tipo == T.FECHA:
            return forms.DateField(label=campo.nombre, required=req, initial=valor,
                                   widget=forms.DateInput(attrs={'type': 'date'}))
        if campo.tipo == T.BOOLEANO:
            return forms.BooleanField(label=campo.nombre, required=False, initial=bool(valor))
        if campo.tipo == T.LISTA:
            choices = [('', '—')] + [(o, o) for o in (campo.opciones or [])]
            return forms.ChoiceField(label=campo.nombre, required=req, initial=valor, choices=choices)
        return forms.CharField(label=campo.nombre, required=req, initial=valor)

    def campos_extra_fields(self):
        """Los BoundField de los campos personalizados, para renderizarlos aparte en el template."""
        return [self[EXTRA_PREFIX + c.slug] for c in self._campos_extra]

    def save(self, commit=True):
        obj = super().save(commit=False)
        datos = dict(obj.datos_extra or {})
        for campo in self._campos_extra:
            raw = self.cleaned_data.get(EXTRA_PREFIX + campo.slug)
            valor = campo.coerce(raw.isoformat() if hasattr(raw, 'isoformat') else raw)
            if valor is None:
                datos.pop(campo.slug, None)
            else:
                datos[campo.slug] = valor
        obj.datos_extra = datos
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class NotaContactoForm(forms.ModelForm):
    class Meta:
        model = NotaContacto
        fields = ['texto']
        widgets = {'texto': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Alergias, preferencias, ocasión especial...'})}


class PagoForm(forms.ModelForm):
    class Meta:
        model = Pago
        fields = ['tipo', 'monto', 'medio_pago']
