from django import forms

from apps.automations.models import Automatizacion
from apps.circuitos.models import Circuito, Extra, TarifaCircuito
from apps.contactos.models import CampoPersonalizado
from apps.sitio_publico.models import PopupWeb
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
        fields = ['fecha', 'descripcion', 'modo', 'recargo_porcentaje', 'recurrente_anual']
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date'}),
            'recargo_porcentaje': forms.NumberInput(attrs={'step': '0.01', 'min': '0',
                                                           'placeholder': 'Vacío = el general'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Mostramos cuál es el recargo general para que no haya que ir a buscarlo a otra pantalla.
        from apps.configuracion.models import ConfiguracionNegocio
        general = ConfiguracionNegocio.get_solo().recargo_feriado_porcentaje
        self.fields['recargo_porcentaje'].help_text = (
            f'Dejalo vacío para usar el recargo general, que hoy es {general:.0f}% '
            f'(se cambia en Configuración del negocio). Completalo solo si ESTE feriado cobra '
            f'otro porcentaje, por ejemplo el 31 de diciembre.'
        )

    def clean(self):
        datos = super().clean()
        if datos.get('modo') == Feriado.Modo.CERRADO and datos.get('recargo_porcentaje') is not None:
            raise forms.ValidationError(
                'Un feriado cerrado no cobra nada, así que no lleva recargo. '
                'Borrá el porcentaje o cambiá el modo a "Abre con recargo".'
            )
        return datos


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
        fields = ['nombre', 'tipo', 'cuerpo', 'activa',
                  'meta_nombre', 'meta_idioma', 'meta_categoria']
        widgets = {'cuerpo': forms.Textarea(attrs={'rows': 5})}
        help_texts = {
            'meta_nombre': 'Solo para Meta: nombre EXACTO de la plantilla aprobada (minúsculas y _). '
                           'Para recordatorios fuera de las 24hs. En Evolution no hace falta.',
        }


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
            'plazo_pago_sena_horas', 'politica_cancelacion', 'horas_reembolso_desde_pago',
            'recargo_feriado_porcentaje',
            'direccion', 'mapa_url', 'como_llegar', 'url_politicas',
            'email_notificaciones',
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
    password = forms.CharField(
        label='Contraseña', required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text='Obligatoria al crear. Al editar, dejala vacía para no cambiarla.',
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'rol', 'is_active', 'is_staff']

    def clean_password(self):
        pw = self.cleaned_data.get('password')
        if not self.instance.pk and not pw:
            raise forms.ValidationError('Poné una contraseña para el usuario nuevo.')
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        pw = self.cleaned_data.get('password')
        if pw:
            user.set_password(pw)
        if commit:
            user.save()
        return user


class PopupWebForm(forms.ModelForm):
    """Cartel emergente de la web pública. Editable por el dueño sin tocar HTML."""

    class Meta:
        model = PopupWeb
        fields = [
            'titulo', 'mensaje', 'imagen', 'cta_texto', 'cta_url',
            'activo', 'desde', 'hasta', 'repetir_horas', 'orden',
        ]
        widgets = {
            'mensaje': forms.Textarea(attrs={'rows': 4}),
            'desde': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'hasta': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # El input datetime-local no entiende el formato por defecto de Django y aparecería
        # vacío al editar, borrando la fecha sin querer al guardar.
        for campo in ('desde', 'hasta'):
            self.fields[campo].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get('desde'), datos.get('hasta')
        if desde and hasta and hasta <= desde:
            raise forms.ValidationError('La fecha de fin tiene que ser posterior a la de inicio.')
        if datos.get('cta_texto') and not datos.get('cta_url'):
            raise forms.ValidationError('Pusiste texto de botón pero no el link al que lleva.')
        if datos.get('cta_url') and not datos.get('cta_texto'):
            raise forms.ValidationError('Pusiste un link pero el botón no tiene texto.')
        if not datos.get('mensaje') and not datos.get('imagen') and not self.instance.imagen:
            raise forms.ValidationError('El cartel necesita al menos un mensaje o una imagen.')
        return datos
