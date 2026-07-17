from django.contrib import admin

from .models import BloqueoManual, Feriado, Turno


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'hora_inicio', 'hora_fin', 'dias_aplicables', 'activo')
    list_filter = ('activo',)
    list_editable = ('activo',)


@admin.register(Feriado)
class FeriadoAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'descripcion', 'recurrente_anual')
    list_filter = ('recurrente_anual',)


@admin.register(BloqueoManual)
class BloqueoManualAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'circuito', 'turno', 'motivo')
    list_filter = ('circuito', 'turno')
    date_hierarchy = 'fecha'
