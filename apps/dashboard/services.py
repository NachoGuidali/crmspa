from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from apps.circuitos.models import Circuito
from apps.contactos.models import Contacto
from apps.reservas.models import Pago, Reserva
from apps.turnero.services import dia_habilitado
from apps.turnero.models import Turno


def _slots_ofrecidos(circuito, desde, hasta):
    """Cantidad de slots turno-día activos para un circuito en un rango (para % de ocupación)."""
    turnos = list(Turno.objects.filter(activo=True))
    total = 0
    dia = desde
    while dia <= hasta:
        if dia_habilitado(dia):
            total += sum(1 for t in turnos if t.aplica_en(dia))
        dia += timedelta(days=1)
    return total


def resumen(desde, hasta):
    reservas_periodo = Reserva.objects.filter(fecha__gte=desde, fecha__lte=hasta)
    pagos_periodo = Pago.objects.filter(reserva__fecha__gte=desde, reserva__fecha__lte=hasta)

    ingresos_totales = pagos_periodo.aggregate(t=Sum('monto'))['t'] or 0
    ingresos_por_circuito = list(
        pagos_periodo.values('reserva__circuito__nombre')
        .annotate(total=Sum('monto'))
        .order_by('-total')
    )

    turnos_por_estado = dict(
        reservas_periodo.values_list('estado').annotate(c=Count('id'))
    )

    ocupacion_por_circuito = []
    ocupadas = (
        reservas_periodo.filter(estado__in=Reserva.ESTADOS_QUE_OCUPAN_CUPO)
        .values('circuito__id', 'circuito__nombre', 'circuito__capacidad_maxima')
        .annotate(personas=Sum('cantidad_personas'))
    )
    for row in ocupadas:
        circuito = Circuito.objects.get(pk=row['circuito__id'])
        slots = _slots_ofrecidos(circuito, desde, hasta)
        capacidad_total = slots * row['circuito__capacidad_maxima']
        pct = round(100 * row['personas'] / capacidad_total, 1) if capacidad_total else 0
        ocupacion_por_circuito.append({
            'circuito': row['circuito__nombre'], 'personas': row['personas'],
            'capacidad_total': capacidad_total, 'pct': pct,
        })
    ocupacion_por_circuito.sort(key=lambda r: -r['pct'])

    circuito_mas_vendido = (
        reservas_periodo.filter(estado__in=Reserva.ESTADOS_QUE_OCUPAN_CUPO)
        .values('circuito__nombre').annotate(c=Count('id')).order_by('-c').first()
    )
    horarios_pico = list(
        reservas_periodo.filter(estado__in=Reserva.ESTADOS_QUE_OCUPAN_CUPO)
        .values('turno__nombre').annotate(c=Count('id')).order_by('-c')[:5]
    )

    contactos_nuevos = Contacto.objects.filter(fecha_alta__date__gte=desde, fecha_alta__date__lte=hasta).count()
    ids_con_reserva_en_periodo = reservas_periodo.values_list('contacto_id', flat=True).distinct()
    clientes_recurrentes = (
        Contacto.objects.filter(id__in=ids_con_reserva_en_periodo, fecha_alta__date__lt=desde).count()
    )

    senas_pendientes = (
        Reserva.objects.filter(estado=Reserva.Estado.PENDIENTE_SENA)
        .aggregate(t=Sum('monto_sena'))['t'] or 0
    )

    return {
        'desde': desde, 'hasta': hasta,
        'ingresos_totales': ingresos_totales,
        'ingresos_por_circuito': ingresos_por_circuito,
        'turnos_por_estado': turnos_por_estado,
        'ocupacion_por_circuito': ocupacion_por_circuito,
        'circuito_mas_vendido': circuito_mas_vendido,
        'horarios_pico': horarios_pico,
        'contactos_nuevos': contactos_nuevos,
        'clientes_recurrentes': clientes_recurrentes,
        'senas_pendientes': senas_pendientes,
    }


def periodo_mes_actual():
    hoy = timezone.localdate()
    desde = hoy.replace(day=1)
    return desde, hoy


def caja_del_dia(fecha):
    """Pagos registrados en una fecha, agrupados por medio de pago (cierre de caja)."""
    from apps.reservas.models import Pago

    pagos = (
        Pago.objects.filter(fecha__date=fecha)
        .select_related('reserva', 'reserva__contacto')
        .order_by('fecha')
    )
    por_medio = {}
    total = 0
    for p in pagos:
        por_medio[p.get_medio_pago_display()] = por_medio.get(p.get_medio_pago_display(), 0) + p.monto
        total += p.monto
    return {'pagos': pagos, 'por_medio': por_medio, 'total': total}


def saldos_por_cobrar():
    """Reservas activas (no canceladas) con saldo pendiente > 0, ordenadas por fecha."""
    from apps.reservas.models import Reserva

    reservas = (
        Reserva.objects.exclude(estado__in=[Reserva.Estado.CANCELADO])
        .select_related('contacto', 'circuito', 'turno')
        .prefetch_related('extras')
        .order_by('fecha')
    )
    pendientes = [r for r in reservas if r.saldo > 0]
    total = sum((r.saldo for r in pendientes), 0)
    return {'reservas': pendientes, 'total': total}


def salud_sistema():
    """Estado operativo del CRM y sus integraciones, para que el dueño detecte a tiempo
    si el bot quedó mudo, si n8n dejó de responder o si hay mensajes sin enviar."""
    from apps.automations.models import AutomatizacionLog
    from apps.integraciones.models import WebhookLog
    from apps.whatsapp.models import Conversacion, LogEnvioWhatsApp, Mensaje

    ahora = timezone.now()
    hace_24h = ahora - timedelta(hours=24)

    ultimo_entrante = (
        Mensaje.objects.filter(direccion=Mensaje.Direccion.ENTRANTE).order_by('-timestamp').first()
    )
    ultimo_webhook_n8n = WebhookLog.objects.order_by('-created_at').first()
    ultima_automatizacion = AutomatizacionLog.objects.order_by('-ejecutado_at').first()

    envios_fallidos_24h = Mensaje.objects.filter(
        direccion=Mensaje.Direccion.SALIENTE, status=Mensaje.Status.FALLIDO, timestamp__gte=hace_24h,
    ).count()
    evolution_errores_24h = LogEnvioWhatsApp.objects.filter(exitoso=False, created_at__gte=hace_24h).count()

    conversaciones_humano = Conversacion.objects.filter(
        estado=Conversacion.Estado.REQUIERE_ATENCION_HUMANA, archivada=False,
    ).count()

    # Reservas confirmadas cuya fecha ya pasó y nadie marcó asistió/no-show.
    reservas_sin_cerrar = Reserva.objects.filter(
        estado=Reserva.Estado.CONFIRMADO, fecha__lt=timezone.localdate(),
    ).count()

    def _hace_cuanto(dt):
        if not dt:
            return None
        return round((ahora - dt).total_seconds() / 60)  # minutos

    return {
        'ultimo_entrante_at': ultimo_entrante.timestamp if ultimo_entrante else None,
        'ultimo_entrante_hace_min': _hace_cuanto(ultimo_entrante.timestamp if ultimo_entrante else None),
        'ultimo_webhook_n8n_at': ultimo_webhook_n8n.created_at if ultimo_webhook_n8n else None,
        'ultima_automatizacion_at': ultima_automatizacion.ejecutado_at if ultima_automatizacion else None,
        'ultima_automatizacion_hace_min': _hace_cuanto(
            ultima_automatizacion.ejecutado_at if ultima_automatizacion else None
        ),
        'envios_fallidos_24h': envios_fallidos_24h,
        'evolution_errores_24h': evolution_errores_24h,
        'conversaciones_humano': conversaciones_humano,
        'reservas_sin_cerrar': reservas_sin_cerrar,
        # Heurística: si no corre una automatización hace >30min, el worker/beat puede estar caído.
        'automations_ok': ultima_automatizacion is not None
        and (ahora - ultima_automatizacion.ejecutado_at) < timedelta(minutes=30),
    }
