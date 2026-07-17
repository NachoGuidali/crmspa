from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import Voucher


class VoucherForm(forms.ModelForm):
    class Meta:
        model = Voucher
        fields = [
            'circuito', 'monto', 'comprador_nombre', 'comprador_telefono', 'comprador_email',
            'destinatario_nombre', 'mensaje_regalo', 'fecha_vencimiento', 'medio_pago',
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
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['fecha_vencimiento'].initial = timezone.localdate() + timedelta(days=365)
        self.fields['circuito'].help_text = 'El monto sugerido es el precio del circuito; podés ajustarlo.'
