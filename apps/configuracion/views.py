from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from apps.automations.models import Automatizacion
from apps.circuitos.models import Circuito, Extra
from apps.contactos.models import CampoPersonalizado
from apps.turnero.models import DIAS_SEMANA, BloqueoManual, Feriado, Turno
from apps.usuarios.models import User
from apps.whatsapp.models import PlantillaMensaje, RespuestaRapida

from . import forms
from .models import ConfiguracionNegocio


class DuenoRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser or getattr(self.request.user, 'rol', '') == 'dueno'


@login_required
def hub(request):
    if not (request.user.is_superuser or getattr(request.user, 'rol', '') == 'dueno'):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    secciones = [
        ('Turnos', 'configuracion:turnos', 'Definir los turnos del día (horario, días, activo).'),
        ('Circuitos', 'configuracion:circuitos', 'Alta/edición de circuitos, precios y seña.'),
        ('Feriados', 'configuracion:feriados', 'Días especiales: cerrados o con tarifa de fin de semana.'),
        ('Bloqueos', 'configuracion:bloqueos', 'Bloqueos manuales de turnos/días.'),
        ('Plantillas de mensaje', 'configuracion:plantillas', 'Mensajes del bot editables sin tocar n8n.'),
        ('Respuestas rápidas', 'configuracion:respuestas', 'Atajos para que recepción responda rápido en el inbox.'),
        ('Campos personalizados', 'configuracion:campos', 'Campos extra de contacto (ej. aniversario) para filtrar y segmentar.'),
        ('Extras / opcionales', 'configuracion:extras', 'Adicionales con precio para sumar a las reservas (upsell).'),
        ('Automatizaciones', 'configuracion:automatizaciones', 'Activar/desactivar y configurar automatizaciones.'),
        ('Negocio', 'configuracion:negocio', 'Plazo de seña, política de cancelación, días laborables.'),
        ('Usuarios y roles', 'configuracion:usuarios', 'Cuentas de acceso (dueño / recepción).'),
    ]
    return render(request, 'configuracion/hub.html', {'secciones': secciones})


# ── CRUD base ────────────────────────────────────────────────────────────────

class BaseListView(DuenoRequiredMixin, ListView):
    template_name = 'configuracion/lista.html'
    titulo = ''
    columnas = []
    crear_url = ''
    editar_url = ''
    borrar_url = ''
    accion_extra_url = ''       # url name opcional para una acción extra por fila
    accion_extra_label = ''

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            'titulo': self.titulo, 'columnas': self.columnas,
            'crear_url': self.crear_url, 'editar_url': self.editar_url, 'borrar_url': self.borrar_url,
            'accion_extra_url': self.accion_extra_url, 'accion_extra_label': self.accion_extra_label,
            'filas': [self.fila(obj) for obj in ctx['object_list']],
        })
        return ctx

    def fila(self, obj):
        raise NotImplementedError


class BaseFormView(DuenoRequiredMixin):
    template_name = 'configuracion/form.html'
    titulo = ''

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['titulo'] = self.titulo
        return ctx


# ── Turnos ───────────────────────────────────────────────────────────────────

class TurnoList(BaseListView):
    model = Turno
    titulo = 'Turnos'
    columnas = ['Nombre', 'Inicio', 'Fin', 'Días', 'Activo']
    crear_url = 'configuracion:turno_crear'
    editar_url = 'configuracion:turno_editar'
    borrar_url = 'configuracion:turno_borrar'

    def fila(self, obj):
        nombres = dict(DIAS_SEMANA)
        dias = ', '.join(nombres[d] for d in obj.dias_aplicables) if obj.dias_aplicables else 'Todos'
        return (obj.pk, [obj.nombre, obj.hora_inicio.strftime('%H:%M'), obj.hora_fin.strftime('%H:%M'), dias, 'Sí' if obj.activo else 'No'])


class TurnoCrear(BaseFormView, CreateView):
    model = Turno
    form_class = forms.TurnoForm
    titulo = 'Nuevo turno'
    success_url = reverse_lazy('configuracion:turnos')


class TurnoEditar(BaseFormView, UpdateView):
    model = Turno
    form_class = forms.TurnoForm
    titulo = 'Editar turno'
    success_url = reverse_lazy('configuracion:turnos')


class TurnoBorrar(DuenoRequiredMixin, DeleteView):
    model = Turno
    template_name = 'configuracion/borrar.html'
    success_url = reverse_lazy('configuracion:turnos')


# ── Circuitos ────────────────────────────────────────────────────────────────

class CircuitoList(BaseListView):
    model = Circuito
    titulo = 'Circuitos'
    columnas = ['Nombre', 'Tipo', 'Capacidad', 'Precio', 'Tramos', 'Activo']
    crear_url = 'configuracion:circuito_crear'
    editar_url = 'configuracion:circuito_editar'
    borrar_url = 'configuracion:circuito_borrar'
    accion_extra_url = 'configuracion:circuito_tarifas'
    accion_extra_label = 'Tramos'

    def fila(self, obj):
        n_tramos = obj.tarifas.count()
        if n_tramos:
            precio = 'por persona (por tramo)'
            tramos = f'{n_tramos} tramo{"s" if n_tramos != 1 else ""}'
        else:
            semana = f'${obj.precio_semana:.0f}' if obj.precio_semana is not None else '—'
            finde = f'${obj.precio_finde:.0f}' if obj.precio_finde is not None else '—'
            precio = f'{semana} / {finde} (sem/finde)'
            tramos = '—'
        return (obj.pk, [obj.nombre, obj.get_tipo_display(), obj.capacidad_maxima,
                         precio, tramos, 'Sí' if obj.activo else 'No'])


class CircuitoCrear(BaseFormView, CreateView):
    model = Circuito
    form_class = forms.CircuitoForm
    titulo = 'Nuevo circuito'
    success_url = reverse_lazy('configuracion:circuitos')


class CircuitoEditar(BaseFormView, UpdateView):
    model = Circuito
    form_class = forms.CircuitoForm
    titulo = 'Editar circuito'
    success_url = reverse_lazy('configuracion:circuitos')


class CircuitoBorrar(DuenoRequiredMixin, DeleteView):
    model = Circuito
    template_name = 'configuracion/borrar.html'
    success_url = reverse_lazy('configuracion:circuitos')


class CircuitoTarifas(DuenoRequiredMixin, UpdateView):
    """Editor de tramos de precio por persona de un circuito (Grupal)."""

    model = Circuito
    fields = []  # no editamos el circuito acá, solo sus tramos
    template_name = 'configuracion/circuito_tarifas.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['circuito'] = self.object
        if 'formset' not in ctx:
            ctx['formset'] = forms.TarifaCircuitoFormSet(instance=self.object)
        return ctx

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        formset = forms.TarifaCircuitoFormSet(request.POST, instance=self.object)
        if formset.is_valid():
            formset.save()
            return redirect('configuracion:circuitos')
        return self.render_to_response(self.get_context_data(formset=formset))


# ── Feriados ─────────────────────────────────────────────────────────────────

class FeriadoList(BaseListView):
    model = Feriado
    titulo = 'Feriados'
    columnas = ['Fecha', 'Descripción', 'Modo', 'Recurrente anual']
    crear_url = 'configuracion:feriado_crear'
    editar_url = 'configuracion:feriado_editar'
    borrar_url = 'configuracion:feriado_borrar'

    def fila(self, obj):
        return (obj.pk, [
            obj.fecha.strftime('%d/%m/%Y'), obj.descripcion,
            obj.get_modo_display(), 'Sí' if obj.recurrente_anual else 'No',
        ])


class FeriadoCrear(BaseFormView, CreateView):
    model = Feriado
    form_class = forms.FeriadoForm
    titulo = 'Nuevo feriado'
    success_url = reverse_lazy('configuracion:feriados')


class FeriadoEditar(BaseFormView, UpdateView):
    model = Feriado
    form_class = forms.FeriadoForm
    titulo = 'Editar feriado'
    success_url = reverse_lazy('configuracion:feriados')


class FeriadoBorrar(DuenoRequiredMixin, DeleteView):
    model = Feriado
    template_name = 'configuracion/borrar.html'
    success_url = reverse_lazy('configuracion:feriados')


# ── Bloqueos ─────────────────────────────────────────────────────────────────

class BloqueoList(BaseListView):
    model = BloqueoManual
    titulo = 'Bloqueos manuales'
    columnas = ['Fecha', 'Circuito', 'Turno', 'Motivo']
    crear_url = 'configuracion:bloqueo_crear'
    editar_url = 'configuracion:bloqueo_editar'
    borrar_url = 'configuracion:bloqueo_borrar'

    def fila(self, obj):
        return (obj.pk, [obj.fecha.strftime('%d/%m/%Y'), obj.circuito.nombre if obj.circuito else 'Todos',
                         obj.turno.nombre if obj.turno else 'Todo el día', obj.motivo])


class BloqueoCrear(BaseFormView, CreateView):
    model = BloqueoManual
    form_class = forms.BloqueoManualForm
    titulo = 'Nuevo bloqueo'
    success_url = reverse_lazy('configuracion:bloqueos')


class BloqueoEditar(BaseFormView, UpdateView):
    model = BloqueoManual
    form_class = forms.BloqueoManualForm
    titulo = 'Editar bloqueo'
    success_url = reverse_lazy('configuracion:bloqueos')


class BloqueoBorrar(DuenoRequiredMixin, DeleteView):
    model = BloqueoManual
    template_name = 'configuracion/borrar.html'
    success_url = reverse_lazy('configuracion:bloqueos')


# ── Plantillas ───────────────────────────────────────────────────────────────

class PlantillaList(BaseListView):
    model = PlantillaMensaje
    titulo = 'Plantillas de mensaje'
    columnas = ['Nombre', 'Tipo', 'Activa']
    crear_url = 'configuracion:plantilla_crear'
    editar_url = 'configuracion:plantilla_editar'
    borrar_url = 'configuracion:plantilla_borrar'

    def fila(self, obj):
        return (obj.pk, [obj.nombre, obj.get_tipo_display(), 'Sí' if obj.activa else 'No'])


class PlantillaCrear(BaseFormView, CreateView):
    model = PlantillaMensaje
    form_class = forms.PlantillaMensajeForm
    titulo = 'Nueva plantilla'
    success_url = reverse_lazy('configuracion:plantillas')


class PlantillaEditar(BaseFormView, UpdateView):
    model = PlantillaMensaje
    form_class = forms.PlantillaMensajeForm
    titulo = 'Editar plantilla'
    success_url = reverse_lazy('configuracion:plantillas')


class PlantillaBorrar(DuenoRequiredMixin, DeleteView):
    model = PlantillaMensaje
    template_name = 'configuracion/borrar.html'
    success_url = reverse_lazy('configuracion:plantillas')


# ── Respuestas rápidas ───────────────────────────────────────────────────────

class RespuestaRapidaList(BaseListView):
    model = RespuestaRapida
    titulo = 'Respuestas rápidas'
    columnas = ['Atajo', 'Título', 'Activa']
    crear_url = 'configuracion:respuesta_crear'
    editar_url = 'configuracion:respuesta_editar'
    borrar_url = 'configuracion:respuesta_borrar'

    def fila(self, obj):
        return (obj.pk, [f'/{obj.atajo}', obj.titulo, 'Sí' if obj.activa else 'No'])


class RespuestaRapidaCrear(BaseFormView, CreateView):
    model = RespuestaRapida
    form_class = forms.RespuestaRapidaForm
    titulo = 'Nueva respuesta rápida'
    success_url = reverse_lazy('configuracion:respuestas')


class RespuestaRapidaEditar(BaseFormView, UpdateView):
    model = RespuestaRapida
    form_class = forms.RespuestaRapidaForm
    titulo = 'Editar respuesta rápida'
    success_url = reverse_lazy('configuracion:respuestas')


class RespuestaRapidaBorrar(DuenoRequiredMixin, DeleteView):
    model = RespuestaRapida
    template_name = 'configuracion/borrar.html'
    success_url = reverse_lazy('configuracion:respuestas')


# ── Extras / opcionales ──────────────────────────────────────────────────────

class ExtraList(BaseListView):
    model = Extra
    titulo = 'Extras / opcionales'
    columnas = ['Nombre', 'Precio', 'Por persona', 'Circuito', 'Activo']
    crear_url = 'configuracion:extra_crear'
    editar_url = 'configuracion:extra_editar'
    borrar_url = 'configuracion:extra_borrar'

    def fila(self, obj):
        return (obj.pk, [obj.nombre, f'${obj.precio:.0f}', 'Sí' if obj.por_persona else 'No',
                         obj.circuito.nombre if obj.circuito else 'Todos', 'Sí' if obj.activo else 'No'])


class ExtraCrear(BaseFormView, CreateView):
    model = Extra
    form_class = forms.ExtraForm
    titulo = 'Nuevo extra / opcional'
    success_url = reverse_lazy('configuracion:extras')


class ExtraEditar(BaseFormView, UpdateView):
    model = Extra
    form_class = forms.ExtraForm
    titulo = 'Editar extra / opcional'
    success_url = reverse_lazy('configuracion:extras')


class ExtraBorrar(DuenoRequiredMixin, DeleteView):
    model = Extra
    template_name = 'configuracion/borrar.html'
    success_url = reverse_lazy('configuracion:extras')


# ── Campos personalizados ────────────────────────────────────────────────────

class CampoPersonalizadoList(BaseListView):
    model = CampoPersonalizado
    titulo = 'Campos personalizados'
    columnas = ['Nombre', 'Tipo', 'Requerido', 'Activo']
    crear_url = 'configuracion:campo_crear'
    editar_url = 'configuracion:campo_editar'
    borrar_url = 'configuracion:campo_borrar'

    def fila(self, obj):
        return (obj.pk, [obj.nombre, obj.get_tipo_display(),
                         'Sí' if obj.requerido else 'No', 'Sí' if obj.activo else 'No'])


class CampoPersonalizadoCrear(BaseFormView, CreateView):
    model = CampoPersonalizado
    form_class = forms.CampoPersonalizadoForm
    titulo = 'Nuevo campo personalizado'
    success_url = reverse_lazy('configuracion:campos')


class CampoPersonalizadoEditar(BaseFormView, UpdateView):
    model = CampoPersonalizado
    form_class = forms.CampoPersonalizadoForm
    titulo = 'Editar campo personalizado'
    success_url = reverse_lazy('configuracion:campos')


class CampoPersonalizadoBorrar(DuenoRequiredMixin, DeleteView):
    model = CampoPersonalizado
    template_name = 'configuracion/borrar.html'
    success_url = reverse_lazy('configuracion:campos')


# ── Automatizaciones ─────────────────────────────────────────────────────────

class AutomatizacionList(BaseListView):
    model = Automatizacion
    titulo = 'Automatizaciones'
    columnas = ['Automatización', 'Activa', 'Parámetros', 'Plantilla']
    editar_url = 'configuracion:automatizacion_editar'

    def fila(self, obj):
        return (obj.pk, [obj.get_tipo_display(), 'Sí' if obj.activa else 'No', str(obj.parametros),
                         obj.plantilla.nombre if obj.plantilla else '—'])


class AutomatizacionEditar(BaseFormView, UpdateView):
    model = Automatizacion
    form_class = forms.AutomatizacionForm
    titulo = 'Editar automatización'
    success_url = reverse_lazy('configuracion:automatizaciones')


# ── Usuarios ─────────────────────────────────────────────────────────────────

class UsuarioList(BaseListView):
    model = User
    titulo = 'Usuarios y roles'
    columnas = ['Usuario', 'Nombre', 'Email', 'Rol', 'Activo']
    crear_url = 'configuracion:usuario_crear'
    editar_url = 'configuracion:usuario_editar'

    def fila(self, obj):
        return (obj.pk, [obj.username, obj.get_full_name(), obj.email, obj.get_rol_display(), 'Sí' if obj.is_active else 'No'])


class UsuarioCrear(BaseFormView, CreateView):
    model = User
    form_class = forms.UserForm
    titulo = 'Nuevo usuario'
    success_url = reverse_lazy('configuracion:usuarios')


class UsuarioEditar(BaseFormView, UpdateView):
    model = User
    form_class = forms.UserForm
    titulo = 'Editar usuario'
    success_url = reverse_lazy('configuracion:usuarios')


# ── Config negocio (singleton) ───────────────────────────────────────────────

class NegocioEditar(BaseFormView, UpdateView):
    model = ConfiguracionNegocio
    form_class = forms.ConfiguracionNegocioForm
    titulo = 'Configuración del negocio'
    template_name = 'configuracion/form.html'
    success_url = reverse_lazy('configuracion:hub')

    def get_object(self, queryset=None):
        return ConfiguracionNegocio.get_solo()
