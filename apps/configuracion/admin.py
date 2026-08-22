from django.contrib import admin

from .models import ConfiguracionNegocio


@admin.register(ConfiguracionNegocio)
class ConfiguracionNegocioAdmin(admin.ModelAdmin):
    list_display = ('nombre_negocio', 'plazo_pago_sena_horas', 'horas_reembolso_desde_pago')

    def has_add_permission(self, request):
        return not ConfiguracionNegocio.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
