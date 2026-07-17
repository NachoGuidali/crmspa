from django.contrib import admin

from .models import ApiKey, WebhookLog


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'key_display', 'activa', 'ultimo_uso_at', 'total_usos', 'created_at')
    list_filter = ('activa',)
    readonly_fields = ('key', 'ultimo_uso_at', 'total_usos', 'created_at')


@admin.register(WebhookLog)
class WebhookLogAdmin(admin.ModelAdmin):
    list_display = ('endpoint', 'method', 'status', 'response_status', 'api_key', 'created_at')
    list_filter = ('status', 'method', 'api_key')
    search_fields = ('endpoint', 'request_body')
    date_hierarchy = 'created_at'
