from django import forms

from .models import Voucher


class VoucherForm(forms.ModelForm):
    class Meta:
        model = Voucher
        fields = [
            'circuito', 'personas', 'monto', 'comprador_nombre', 'comprador_telefono',
            'comprador_email', 'destinatario_nombre', 'mensaje_regalo', 'fecha_vencimiento',
            'medio_pago',
        ]
        widgets = {
            'fecha_vencimiento': forms.DateInput(attrs={'type': 'date'}),
            'mensaje_regalo': forms.Textarea(attrs={'rows': 2}),
            'medio_pago': forms.Select(choices=[
                ('efectivo', 'Efectivo'), ('transferencia', 'Transferencia'),
                ('mercado_pago', 'Mercado Pago'), ('tarjeta', 'Tarjeta'),
            ]),
        }

    def __init__(self, *args, **kwargs):
        from . import services

        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            # El plazo sale de Configuración del negocio → Vouchers de regalo, y se puede
            # pisar a mano acá mismo para un caso puntual.
            self.fields['fecha_vencimiento'].initial = services.vencimiento()
        self.fields['monto'].required = False
        self.fields['monto'].help_text = (
            'Vacío = el precio de fin de semana del circuito para esa cantidad de personas, '
            'que es como se venden los vouchers (así sirven para cualquier día).'
        )
        self.fields['personas'].help_text = 'Para cuántas personas es. En el circuito de pareja, 2.'

    def clean(self):
        from . import services

        datos = super().clean()
        circuito, personas = datos.get('circuito'), datos.get('personas')
        if circuito and personas:
            if personas < circuito.capacidad_minima or personas > circuito.capacidad_maxima:
                self.add_error('personas', f'{circuito.nombre} es para {circuito.capacidad_minima} '
                                           f'a {circuito.capacidad_maxima} personas.')
            elif not datos.get('monto'):
                datos['monto'] = services.precio(circuito, personas)
        return datos
