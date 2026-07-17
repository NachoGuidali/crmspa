from django.contrib import admin

from .models import ListaEspera, Pago, Reserva


class PagoInline(admin.TabularInline):
    model = Pago
    extra = 0
    fields = ('tipo', 'monto', 'medio_pago', 'fecha')
    readonly_fields = ('fecha',)


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = (
        'contacto', 'circuito', 'fecha', 'turno', 'cantidad_personas',
        'estado', 'monto_sena', 'monto_pagado',
    )
    list_filter = ('estado', 'circuito', 'turno')
    search_fields = ('contacto__nombre', 'contacto__telefono')
    date_hierarchy = 'fecha'
    autocomplete_fields = ('contacto', 'circuito')
    inlines = [PagoInline]


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ('reserva', 'tipo', 'monto', 'medio_pago', 'fecha')
    list_filter = ('tipo', 'medio_pago')


@admin.register(ListaEspera)
class ListaEsperaAdmin(admin.ModelAdmin):
    list_display = ('contacto', 'circuito', 'fecha_deseada', 'turno', 'notificado')
    list_filter = ('circuito', 'notificado')
