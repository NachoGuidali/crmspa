import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .models import ConfiguracionWhatsApp, Conversacion, Mensaje, PlantillaMensaje, RespuestaRapida


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

    proveedor_meta = ConfiguracionWhatsApp.get_proveedor() == ConfiguracionWhatsApp.Proveedor.META

    return render(request, 'whatsapp/inbox.html', {
        'conversaciones': conversaciones,
        'unread_total': unread_total,
        'selected': selected,
        'mensajes': mensajes,
        'last_msg_id': last_msg_id,
        'plantillas': plantillas,
        'respuestas': respuestas,
        'proveedor_meta': proveedor_meta,
        'ventana_abierta': selected.ventana_abierta if selected else True,
        'estados': Conversacion.Estado.choices,
        'q': request.GET.get('q', ''),
        'estado_filtro': request.GET.get('estado', ''),
        'no_leidos': request.GET.get('no_leidos', ''),
    })


@login_required
@require_POST
def enviar_media(request, pk):
    """Envía un archivo (foto/audio/documento) desde el inbox y lo guarda en la ficha del contacto."""
    import os
    import re

    from django.conf import settings as dj_settings
    from django.utils import timezone

    from . import sender
    from .media_utils import get_mediatype

    MAX_MB = 16
    conv = get_object_or_404(Conversacion, pk=pk)
    archivo = request.FILES.get('archivo')
    caption = request.POST.get('caption', '').strip()
    is_ptt = request.POST.get('ptt') == '1'

    if not archivo:
        return JsonResponse({'ok': False, 'error': 'No se recibió ningún archivo.'}, status=400)
    if archivo.size > MAX_MB * 1024 * 1024:
        return JsonResponse({'ok': False, 'error': f'El archivo supera los {MAX_MB}MB.'}, status=400)

    mime = archivo.content_type or 'application/octet-stream'
    mediatype = get_mediatype(mime)
    filename = archivo.name or 'archivo'
    raw = archivo.read()

    # Guardar local (para verlo en el inbox y en la ficha del contacto).
    safe_name = re.sub(r'[^\w.\-]', '_', filename)
    upload_dir = os.path.join(dj_settings.MEDIA_ROOT, 'uploads', f'conv_{pk}')
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, safe_name), 'wb') as f:
        f.write(raw)
    local_url = f'{dj_settings.MEDIA_URL}uploads/conv_{pk}/{safe_name}'

    try:
        resultado = sender.send_uploaded_media(
            conv.telefono, raw, mime, filename=filename, caption=caption, is_ptt=is_ptt,
        )
    except Exception as exc:
        logger.exception('Error enviando media a %s', conv.telefono)
        return JsonResponse({'ok': False, 'error': f'No se pudo enviar: {str(exc)[:120]}'}, status=502)

    tipo_map = {
        'image': Mensaje.Tipo.IMAGEN, 'video': Mensaje.Tipo.VIDEO,
        'audio': Mensaje.Tipo.AUDIO, 'document': Mensaje.Tipo.DOCUMENTO,
    }
    tipo = tipo_map.get(mediatype, Mensaje.Tipo.DOCUMENTO)
    msg = Mensaje.objects.create(
        conversacion=conv,
        contacto=conv.contacto,
        whatsapp_message_id=resultado.get('id', ''),
        direccion=Mensaje.Direccion.SALIENTE,
        tipo=tipo,
        contenido=caption,
        media_url=local_url,
        media_mime=mime,
        media_filename=filename,
        status=Mensaje.Status.ENVIADO if resultado.get('id') else Mensaje.Status.PENDIENTE,
        enviado_por=request.user,
        timestamp=timezone.now(),
    )
    if conv.contacto:
        conv.contacto.registrar_archivo(url=local_url, tipo=tipo, mime=mime, filename=filename, direccion='out')
    Conversacion.objects.filter(pk=conv.pk).update(ultimo_mensaje_at=msg.timestamp)

    return JsonResponse({'ok': True, 'mensaje': {
        'id': msg.id, 'direccion': 'out', 'tipo': tipo, 'contenido': caption,
        'media_url': local_url, 'media_mime': mime, 'media_filename': filename,
        'timestamp': msg.timestamp.strftime('%d/%m %H:%M'), 'status': msg.get_status_display(),
    }})


@login_required
def nueva_conversacion(request):
    """Abrir/crear una conversación desde el inbox: eligiendo un contacto o tipeando un número.
    Si el número ya existe como contacto, se vincula solo (y el front lo avisa en vivo)."""
    from apps.contactos.models import Contacto
    from utils.phone import normalize_ar_phone

    if request.method == 'POST':
        contacto_id = request.POST.get('contacto_id', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        mensaje = request.POST.get('mensaje', '').strip()

        if contacto_id:
            c = Contacto.objects.filter(pk=contacto_id).first()
            if c:
                telefono = c.telefono
        if not telefono:
            messages.error(request, 'Elegí un contacto o ingresá un número.')
            return redirect('whatsapp:nueva_conversacion')

        telefono = normalize_ar_phone(telefono)
        conv, _ = Conversacion.objects.get_or_create(telefono=telefono)
        # Vincular el contacto si ese número ya existe en la agenda.
        if not conv.contacto:
            c = Contacto.objects.filter(telefono=telefono).first()
            if c:
                conv.contacto = c
                if not conv.nombre_contacto:
                    conv.nombre_contacto = c.nombre
                conv.save(update_fields=['contacto', 'nombre_contacto'])

        if mensaje:
            try:
                services.enviar_mensaje(telefono=telefono, mensaje=mensaje, usuario=request.user)
            except services.EnvioError as exc:
                messages.error(request, f'No se pudo enviar: {exc}')

        return redirect(f"{reverse('whatsapp:inbox')}?conv={conv.pk}")

    contactos = list(Contacto.objects.order_by('nombre').values('id', 'nombre', 'telefono'))
    return render(request, 'whatsapp/nueva_conversacion.html', {'contactos': contactos})


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
        # Los valores de los {{1}}, {{2}}... se ingresan separados por "|".
        valores_raw = request.POST.get('valores', '').strip()
        valores = [v.strip() for v in valores_raw.split('|')] if valores_raw else []
        try:
            services.enviar_plantilla(telefono=conv.telefono, plantilla=plantilla, valores=valores, usuario=request.user)
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
        'tipo': m.tipo,
        'media_url': m.media_url,
        'media_mime': m.media_mime,
        'media_filename': m.media_filename,
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


# ── Configuración de WhatsApp (proveedor, Evolution + QR, Meta) ───────────────

from .models import ConfiguracionWhatsApp


def _es_dueno(user):
    return user.is_superuser or getattr(user, 'rol', '') == 'dueno'


@login_required
def config_whatsapp(request):
    """Configuración → WhatsApp: elegir proveedor y cargar credenciales."""
    if not _es_dueno(request.user):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    config = ConfiguracionWhatsApp.objects.filter(pk=1).first() or ConfiguracionWhatsApp()

    if request.method == 'POST':
        config.proveedor = request.POST.get('proveedor', ConfiguracionWhatsApp.Proveedor.EVOLUTION)
        # Evolution
        config.evolution_api_url = request.POST.get('evolution_api_url', '').strip()
        config.evolution_api_key = request.POST.get('evolution_api_key', '').strip()
        config.evolution_instance_name = request.POST.get('evolution_instance_name', '').strip() or 'crmspa'
        config.webhook_token = request.POST.get('webhook_token', '').strip()
        # Meta
        config.meta_phone_number_id = request.POST.get('meta_phone_number_id', '').strip()
        config.meta_waba_id = request.POST.get('meta_waba_id', '').strip()
        config.meta_access_token = request.POST.get('meta_access_token', '').strip()
        config.meta_app_secret = request.POST.get('meta_app_secret', '').strip()
        config.meta_verify_token = request.POST.get('meta_verify_token', '').strip()
        config.meta_api_version = request.POST.get('meta_api_version', '').strip() or 'v21.0'
        config.save()

        # Si es Evolution, damos de alta la instancia y registramos el webhook.
        if config.proveedor == ConfiguracionWhatsApp.Proveedor.EVOLUTION and config.evolution_api_url:
            from django.conf import settings as dj_settings

            from . import sender
            # Por defecto la URL pública (autodetectada); si EVOLUTION_WEBHOOK_URL está seteada
            # (p.ej. la interna de Docker), usamos esa para que Evolution alcance el CRM.
            webhook_url = dj_settings.EVOLUTION_WEBHOOK_URL or request.build_absolute_uri(
                reverse('whatsapp_api:webhook_evolution')
            )
            try:
                sender.ensure_instance_exists()
                sender.setup_instance_webhook(webhook_url)
                messages.success(request, 'Configuración guardada. Instancia y webhook de Evolution listos.')
            except Exception as e:
                messages.warning(request, f'Guardado, pero no se pudo registrar la instancia/webhook: {e}')
        else:
            messages.success(request, 'Configuración guardada.')
        return redirect('whatsapp:config')

    estado = 'desconocido'
    meta_info = None
    if config.proveedor == ConfiguracionWhatsApp.Proveedor.EVOLUTION and config.evolution_api_url:
        from . import sender
        try:
            estado = sender.get_connection_state()
        except Exception:
            estado = 'error'
    elif config.proveedor == ConfiguracionWhatsApp.Proveedor.META and config.meta_access_token and config.meta_phone_number_id:
        from . import sender_meta
        meta_info = sender_meta.get_phone_number_info()

    webhook_evolution = request.build_absolute_uri(reverse('whatsapp_api:webhook_evolution'))
    webhook_meta = request.build_absolute_uri(reverse('whatsapp_api:webhook_meta'))
    return render(request, 'whatsapp/config.html', {
        'config': config,
        'connection_state': estado,
        'webhook_evolution_url': webhook_evolution,
        'webhook_meta_url': webhook_meta,
        'meta_info': meta_info,
        'PROVEEDORES': ConfiguracionWhatsApp.Proveedor.choices,
    })


@login_required
def config_qr(request):
    """Devuelve el QR (base64) de Evolution para vincular WhatsApp. Polleado por el front."""
    if not _es_dueno(request.user):
        return JsonResponse({'error': 'forbidden'}, status=403)
    from django.core.cache import cache

    from . import sender
    try:
        sender.ensure_instance_exists()
        estado = sender.get_connection_state()
        if estado == 'open':
            cache.delete('whatsapp_qr_code')
            cache.delete('whatsapp_qr_text')
            return JsonResponse({'connected': True, 'qr_base64': None})
        if not cache.get('whatsapp_qr_text') and not cache.get('whatsapp_qr_code'):
            sender.trigger_connect()
        return JsonResponse({
            'connected': False,
            'qr_base64': cache.get('whatsapp_qr_code'),
            'qr_code': cache.get('whatsapp_qr_text'),
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def config_estado(request):
    """Estado de conexión de la instancia de Evolution (para el badge)."""
    from . import sender
    try:
        estado = sender.get_connection_state()
    except Exception as e:
        return JsonResponse({'state': 'error', 'connected': False, 'detail': str(e)})
    return JsonResponse({'state': estado, 'connected': estado == 'open'})


@login_required
@require_POST
def config_logout(request):
    """Desvincula el WhatsApp de la instancia de Evolution."""
    if not _es_dueno(request.user):
        return JsonResponse({'error': 'forbidden'}, status=403)
    from . import sender
    try:
        sender.logout_instance()
        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)
