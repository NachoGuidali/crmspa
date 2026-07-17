from django.contrib import admin

from .models import Contacto, Etiqueta, NotaContacto


class NotaContactoInline(admin.TabularInline):
    model = NotaContacto
    extra = 0
    fields = ('texto', 'autor', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(Contacto)
class ContactoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'telefono', 'email', 'fecha_nacimiento', 'lista_etiquetas', 'fecha_alta')
    search_fields = ('nombre', 'telefono', 'email')
    list_filter = ('etiquetas',)
    filter_horizontal = ('etiquetas',)
    inlines = [NotaContactoInline]

    @admin.display(description='Etiquetas')
    def lista_etiquetas(self, obj):
        return ', '.join(e.nombre for e in obj.etiquetas.all())


@admin.register(Etiqueta)
class EtiquetaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'color')
    search_fields = ('nombre',)
