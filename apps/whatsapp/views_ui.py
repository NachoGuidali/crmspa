import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .models import Conversacion, PlantillaMensaje, RespuestaRapida


def _conversaciones_filtradas(request):
    qs = Conversacion.objects.filter(archivada=False).select_related('contacto', 'agente')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(nombre_contacto__icontains=q) | Q(telefono__icontains=q) | Q(contacto__nombre__icontains=q))
    estado = request.GET.get('estado', '').strip()
    if estado:
        qs = qs.filter(estado=estado)
    if request.GET.get('no_leidos'):
        qs = qs.filter(mensajes_no_leidos__gt=0)
    return qs.order_by('-ultimo_mensaje_at')


@login_required
def inbox(request):
    conversaciones = list(_conversaciones_filtradas(request)[:100])
    unread_total = Conversacion.objects.filter(archivada=False, mensajes_no_leidos__gt=0).count()

    selected = None
    mensajes = []
    plantillas = []
    conv_pk = request.GET.get('conv', '').strip()
    if conv_pk:
        try:
            selected = Conversacion.objects.select_related('contacto', 'agente').get(pk=int(conv_pk))
            Conversacion.objects.filter(pk=selected.pk).update(mensajes_no_leidos=0)
            selected.mensajes_no_leidos = 0
            mensajes = list(selected.mensajes.order_by('timestamp')[:200])
            plantillas = PlantillaMensaje.objects.filter(activa=True)
        except (Conversacion.DoesNotExist, ValueError):
            selected = None

    last_msg_id = mensajes[-1].id if mensajes else 0
    respuestas = RespuestaRapida.objects.filter(activa=True) if selected else []

    return render(request, 'whatsapp/inbox.html', {
        'conversaciones': conversaciones,
        'unread_total': unread_total,
        'selected': selected,
        'mensajes': mensajes,
        'last_msg_id': last_msg_id,
        'plantillas': plantillas,
        'respuestas': respuestas,
        'estados': Conversacion.Estado.choices,
        'q': request.GET.get('q', ''),
        'estado_filtro': request.GET.get('estado', ''),
        'no_leidos': request.GET.get('no_leidos', ''),
    })


@login_required
@require_POST
def inbox_accion(request):
    conv = get_object_or_404(Conversacion, pk=request.POST.get('conv_pk'))
    accion = request.POST.get('accion', '')

    if accion == 'enviar_texto':
        texto = request.POST.get('mensaje', '').strip()
        if texto:
            try:
                services.enviar_mensaje(telefono=conv.telefono, mensaje=texto, usuario=request.user)
            except services.EnvioError as exc:
                messages.error(request, f'No se pudo enviar: {exc}')

    elif accion == 'enviar_plantilla':
        plantilla = get_object_or_404(PlantillaMensaje, pk=request.POST.get('plantilla_id'))
        contexto = {'nombre': conv.get_display_name(), 'telefono': conv.telefono}
        try:
            services.enviar_mensaje(telefono=conv.telefono, mensaje=plantilla.render(contexto), usuario=request.user)
        except services.EnvioError as exc:
            messages.error(request, f'No se pudo enviar: {exc}')

    elif accion == 'toggle_bot':
        conv.bot_activo = not conv.bot_activo
        conv.save(update_fields=['bot_activo'])

    elif accion == 'cambiar_estado':
        nuevo = request.POST.get('estado')
        if nuevo in dict(Conversacion.Estado.choices):
            conv.estado = nuevo
            conv.bot_activo = nuevo != Conversacion.Estado.REQUIERE_ATENCION_HUMANA
            conv.save(update_fields=['estado', 'bot_activo'])

    elif accion == 'handoff':
        conv.estado = Conversacion.Estado.REQUIERE_ATENCION_HUMANA
        conv.bot_activo = False
        conv.agente = request.user
        conv.save(update_fields=['estado', 'bot_activo', 'agente'])

    elif accion == 'archivar':
        conv.archivada = True
        conv.save(update_fields=['archivada'])
        return redirect('whatsapp:inbox')

    return redirect(f"{reverse('whatsapp:inbox')}?conv={conv.pk}")


@login_required
def inbox_mensajes(request, pk):
    """JSON de mensajes de una conversación (para el polling del chat abierto)."""
    conv = get_object_or_404(Conversacion, pk=pk)
    after = request.GET.get('after', '0')
    try:
        after_id = int(after)
    except ValueError:
        after_id = 0
    qs = conv.mensajes.filter(id__gt=after_id).order_by('timestamp')
    data = [{
        'id': m.id,
        'direccion': m.direccion,
        'contenido': m.contenido,
        'timestamp': m.timestamp.strftime('%d/%m %H:%M'),
        'status': m.get_status_display(),
    } for m in qs]
    if data:
        Conversacion.objects.filter(pk=conv.pk).update(mensajes_no_leidos=0)
    return JsonResponse({'mensajes': data})


# ── Kanban (vista alternativa) ────────────────────────────────────────────────

@login_required
def kanban(request):
    columnas = []
    for value, label in Conversacion.Estado.choices:
        columnas.append({
            'estado': value, 'label': label,
            'conversaciones': Conversacion.objects.filter(estado=value, archivada=False).order_by('-ultimo_mensaje_at'),
        })
    return render(request, 'whatsapp/kanban.html', {'columnas': columnas})


@login_required
@require_POST
def kanban_move(request, pk):
    conversacion = get_object_or_404(Conversacion, pk=pk)
    data = json.loads(request.body or '{}')
    nuevo_estado = data.get('estado')
    if nuevo_estado not in dict(Conversacion.Estado.choices):
        return JsonResponse({'error': 'estado_invalido'}, status=400)
    conversacion.estado = nuevo_estado
    conversacion.bot_activo = nuevo_estado != Conversacion.Estado.REQUIERE_ATENCION_HUMANA
    conversacion.save()
    return JsonResponse({'ok': True})
