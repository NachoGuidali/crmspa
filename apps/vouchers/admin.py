from django.contrib import admin

from .models import Voucher


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'circuito', 'personas', 'monto', 'comprador_nombre', 'estado',
                    'origen', 'fecha_vencimiento', 'canjeado_at')
    list_filter = ('estado', 'origen', 'circuito')
    search_fields = ('codigo', 'comprador_nombre', 'comprador_telefono', 'destinatario_nombre')
    # El voucher dibujado y el canje los escribe el sistema: a mano se tocan desde la pantalla
    # de vouchers (aprobar, enviar, canjear), que además manda el WhatsApp.
    readonly_fields = ('codigo', 'canjeado_at', 'reserva_canje', 'imagen', 'archivo_pdf',
                       'aprobado_at', 'aprobado_por', 'enviado_at')
