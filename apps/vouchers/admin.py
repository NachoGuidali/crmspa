from django.contrib import admin

from .models import Voucher


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'circuito', 'monto', 'comprador_nombre', 'estado', 'fecha_vencimiento', 'canjeado_at')
    list_filter = ('estado', 'circuito')
    search_fields = ('codigo', 'comprador_nombre', 'comprador_telefono', 'destinatario_nombre')
    readonly_fields = ('codigo', 'canjeado_at', 'reserva_canje')
