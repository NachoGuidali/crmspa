from django import forms

from .models import Tarea


class TareaForm(forms.ModelForm):
    class Meta:
        model = Tarea
        fields = ['tipo', 'descripcion', 'contacto', 'asignado_a', 'fecha_programada']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 2}),
            'fecha_programada': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }
