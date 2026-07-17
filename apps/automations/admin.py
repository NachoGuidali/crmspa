from django.contrib import admin

from .models import Automatizacion, AutomatizacionLog


class AutomatizacionLogInline(admin.TabularInline):
    model = AutomatizacionLog
    extra = 0
    fields = ('resultado', 'contacto', 'reserva', 'detalle', 'ejecutado_at')
    readonly_fields = ('ejecutado_at',)
    can_delete = False
    max_num = 10
    ordering = ('-ejecutado_at',)


@admin.register(Automatizacion)
class AutomatizacionAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'activa', 'plantilla', 'updated_at')
    list_filter = ('activa',)
    list_editable = ('activa',)
    inlines = [AutomatizacionLogInline]


@admin.register(AutomatizacionLog)
class AutomatizacionLogAdmin(admin.ModelAdmin):
    list_display = ('automatizacion', 'resultado', 'contacto', 'reserva', 'ejecutado_at')
    list_filter = ('resultado', 'automatizacion')
    date_hierarchy = 'ejecutado_at'
