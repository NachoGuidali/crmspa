from django import forms

from apps.automations.models import Automatizacion
from apps.circuitos.models import Circuito, Extra, TarifaCircuito
from apps.contactos.models import CampoPersonalizado
from apps.turnero.models import DIAS_SEMANA, BloqueoManual, Feriado, Turno
from apps.usuarios.models import User
from apps.whatsapp.models import PlantillaMensaje, RespuestaRapida

from .models import ConfiguracionNegocio


class DiasSemanaField(forms.MultipleChoiceField):
    """Campo para elegir días de la semana; guarda una lista de enteros en un JSONField."""

    widget = forms.CheckboxSelectMultiple

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('choices', DIAS_SEMANA)
        kwargs.setdefault('required', False)
        kwargs.setdefault('help_text', 'Vacío = todos los días.')
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        if value is None:
            return []
        return [str(v) for v in value]

    def clean(self, value):
        value = super().clean(value)
        return [int(v) for v in value]


class TurnoForm(forms.ModelForm):
    dias_aplicables = DiasSemanaField(label='Días aplicables')

    class Meta:
        model = Turno
        fields = ['nombre', 'hora_inicio', 'hora_fin', 'dias_aplicables', 'activo']
        widgets = {
            'hora_inicio': forms.TimeInput(attrs={'type': 'time'}),
            'hora_fin': forms.TimeInput(attrs={'type': 'time'}),
        }


class FeriadoForm(forms.ModelForm):
    class Meta:
        model = Feriado
        fields = ['fecha', 'descripcion', 'modo', 'recurrente_anual']
        widgets = {'fecha': forms.DateInput(attrs={'type': 'date'})}


class BloqueoManualForm(forms.ModelForm):
    class Meta:
        model = BloqueoManual
        fields = ['circuito', 'fecha', 'turno', 'motivo']
        widgets = {'fecha': forms.DateInput(attrs={'type': 'date'})}


class CircuitoForm(forms.ModelForm):
    class Meta:
        model = Circuito
        fields = [
            'nombre', 'descripcion', 'tipo', 'duracion_minutos',
            'capacidad_minima', 'capacidad_maxima',
            'precio_semana', 'precio_finde',
            'precio_persona_adicional_semana', 'precio_persona_adicional_finde',
            'sena_tipo', 'sena_valor', 'imagen', 'activo',
        ]
        help_texts = {
            'precio_semana': 'Precio plano (circuitos de precio fijo como Pareja). Si el circuito '
                             'cobra por persona según el grupo, dejá esto vacío y cargá los tramos.',
            'capacidad_maxima': 'Tope máximo de personas que admite este circuito.',
        }


class ExtraForm(forms.ModelForm):
    class Meta:
        model = Extra
        fields = ['nombre', 'descripcion', 'precio', 'por_persona', 'circuito', 'orden', 'activo']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['circuito'].queryset = Circuito.objects.filter(activo=True)
        self.fields['circuito'].required = False
        self.fields['circuito'].empty_label = 'Todos los circuitos'


class CampoPersonalizadoForm(forms.ModelForm):
    opciones_texto = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'rows': 3}),
        label='Opciones (una por línea)',
        help_text='Solo para tipo "Lista de opciones".',
    )

    class Meta:
        model = CampoPersonalizado
        fields = ['nombre', 'tipo', 'requerido', 'orden', 'activo']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['opciones_texto'].initial = '\n'.join(self.instance.opciones or [])

    def save(self, commit=True):
        obj = super().save(commit=False)
        if obj.tipo == CampoPersonalizado.Tipo.LISTA:
            obj.opciones = [ln.strip() for ln in self.cleaned_data['opciones_texto'].splitlines() if ln.strip()]
        else:
            obj.opciones = []
        if commit:
            obj.save()
        return obj


TarifaCircuitoFormSet = forms.inlineformset_factory(
    Circuito, TarifaCircuito,
    fields=['min_personas', 'max_personas', 'precio_persona_semana', 'precio_persona_finde'],
    extra=1, can_delete=True,
)


class PlantillaMensajeForm(forms.ModelForm):
    class Meta:
        model = PlantillaMensaje
        fields = ['nombre', 'tipo', 'cuerpo', 'activa']
        widgets = {'cuerpo': forms.Textarea(attrs={'rows': 5})}


class RespuestaRapidaForm(forms.ModelForm):
    class Meta:
        model = RespuestaRapida
        fields = ['titulo', 'atajo', 'texto', 'activa']
        widgets = {'texto': forms.Textarea(attrs={'rows': 3})}


class ConfiguracionNegocioForm(forms.ModelForm):
    dias_laborables = DiasSemanaField(label='Días laborables')
    dias_tarifa_finde = DiasSemanaField(label='Días con tarifa de fin de semana', required=False)

    class Meta:
        model = ConfiguracionNegocio
        fields = [
            'nombre_negocio', 'dias_laborables', 'dias_tarifa_finde',
            'horario_atencion_desde', 'horario_atencion_hasta',
            'reserva_exclusiva_por_turno',
            'plazo_pago_sena_horas', 'politica_cancelacion', 'horas_cancelacion_con_reembolso',
        ]
        widgets = {
            'horario_atencion_desde': forms.TimeInput(attrs={'type': 'time'}),
            'horario_atencion_hasta': forms.TimeInput(attrs={'type': 'time'}),
            'politica_cancelacion': forms.Textarea(attrs={'rows': 3}),
        }


class AutomatizacionForm(forms.ModelForm):
    class Meta:
        model = Automatizacion
        fields = ['activa', 'parametros', 'plantilla']


class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'rol', 'is_active', 'is_staff']
