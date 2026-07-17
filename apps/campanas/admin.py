from django.contrib import admin

from .models import Campana, EnvioCampana


@admin.register(Campana)
class CampanaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'estado', 'modo_seleccion', 'total_destinatarios', 'enviados', 'errores', 'created_at')
    list_filter = ('estado', 'modo_seleccion')
    filter_horizontal = ('filtro_etiquetas',)


@admin.register(EnvioCampana)
class EnvioCampanaAdmin(admin.ModelAdmin):
    list_display = ('campana', 'contacto', 'estado', 'enviado_at')
    list_filter = ('estado', 'campana')
