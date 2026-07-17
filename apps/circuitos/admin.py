from django.contrib import admin

from .models import Circuito


@admin.register(Circuito)
class CircuitoAdmin(admin.ModelAdmin):
    list_display = (
        'nombre', 'tipo', 'capacidad_maxima', 'duracion_minutos',
        'precio_semana', 'precio_finde', 'sena_tipo', 'sena_valor', 'activo',
    )
    list_filter = ('tipo', 'activo')
    search_fields = ('nombre',)
    list_editable = ('activo',)
