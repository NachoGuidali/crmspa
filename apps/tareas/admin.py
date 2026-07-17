from django.contrib import admin

from .models import Tarea


@admin.register(Tarea)
class TareaAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'descripcion', 'contacto', 'asignado_a', 'fecha_programada', 'estado')
    list_filter = ('estado', 'tipo', 'asignado_a')
    date_hierarchy = 'fecha_programada'
