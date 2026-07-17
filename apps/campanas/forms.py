from django import forms

from apps.contactos.models import CampoPersonalizado

from .models import Campana

OPERADOR_CHOICES = [
    ('', '—'),
    ('eq', 'es igual a'),
    ('contiene', 'contiene'),
    ('gte', 'mayor o igual a / desde'),
    ('lte', 'menor o igual a / hasta'),
]


class CampanaForm(forms.ModelForm):
    class Meta:
        model = Campana
        fields = [
            'nombre', 'plantilla', 'modo_seleccion',
            'filtro_etiquetas', 'filtro_circuito', 'filtro_dias_inactividad',
            'filtro_min_reservas', 'filtro_con_email',
            'filtro_campo', 'filtro_campo_operador', 'filtro_campo_valor',
            'fecha_programada',
        ]
        widgets = {
            'filtro_etiquetas': forms.CheckboxSelectMultiple,
            'fecha_programada': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'filtro_campo_operador': forms.Select(choices=OPERADOR_CHOICES),
        }
        labels = {
            'filtro_min_reservas': 'Mínimo de reservas (clientes frecuentes)',
            'filtro_con_email': 'Solo con email cargado',
            'filtro_campo': 'Campo personalizado',
            'filtro_campo_operador': 'Operador',
            'filtro_campo_valor': 'Valor',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plantilla'].help_text = 'El texto se personaliza con {{nombre}}.'
        self.fields['fecha_programada'].help_text = 'Dejar vacío para enviar manualmente con el botón "Enviar ahora".'
        self.fields['filtro_campo'].queryset = CampoPersonalizado.objects.filter(activo=True)
        self.fields['filtro_campo'].required = False
        self.fields['filtro_campo_operador'].required = False
        self.fields['filtro_campo_valor'].required = False
