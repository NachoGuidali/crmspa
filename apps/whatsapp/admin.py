from django.contrib import admin

from .models import (
    ConfiguracionWhatsApp,
    Conversacion,
    LogEnvioWhatsApp,
    Mensaje,
    PlantillaMensaje,
    RespuestaRapida,
)


@admin.register(RespuestaRapida)
class RespuestaRapidaAdmin(admin.ModelAdmin):
    list_display = ('atajo', 'titulo', 'activa')
    list_filter = ('activa',)
    search_fields = ('atajo', 'titulo', 'texto')


@admin.register(ConfiguracionWhatsApp)
class ConfiguracionWhatsAppAdmin(admin.ModelAdmin):
    list_display = ('evolution_instance_name', 'evolution_api_url')

    def has_add_permission(self, request):
        return not ConfiguracionWhatsApp.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class MensajeInline(admin.TabularInline):
    model = Mensaje
    extra = 0
    fields = ('direccion', 'tipo', 'contenido', 'status', 'timestamp')
    readonly_fields = ('timestamp',)
    ordering = ('timestamp',)


@admin.register(Conversacion)
class ConversacionAdmin(admin.ModelAdmin):
    list_display = (
        'get_display_name', 'telefono', 'estado', 'bot_activo',
        'agente', 'ultimo_mensaje_at', 'archivada',
    )
    list_filter = ('estado', 'bot_activo', 'archivada')
    search_fields = ('telefono', 'nombre_contacto', 'contacto__nombre')
    autocomplete_fields = ('contacto',)
    inlines = [MensajeInline]


@admin.register(Mensaje)
class MensajeAdmin(admin.ModelAdmin):
    list_display = ('conversacion', 'direccion', 'tipo', 'status', 'timestamp')
    list_filter = ('direccion', 'tipo', 'status')
    search_fields = ('contenido', 'conversacion__telefono')


@admin.register(PlantillaMensaje)
class PlantillaMensajeAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo', 'activa', 'updated_at')
    list_filter = ('tipo', 'activa')
    search_fields = ('nombre', 'cuerpo')


@admin.register(LogEnvioWhatsApp)
class LogEnvioWhatsAppAdmin(admin.ModelAdmin):
    list_display = ('endpoint', 'response_status', 'exitoso', 'duracion_ms', 'created_at')
    list_filter = ('exitoso',)
    date_hierarchy = 'created_at'
