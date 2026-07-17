import logging

from celery import shared_task
from django.utils import timezone

from apps.whatsapp.services import EnvioError, enviar_mensaje

from .models import Campana, EnvioCampana

logger = logging.getLogger('apps.campanas')


@shared_task
def ejecutar_campana(campana_id):
    try:
        campana = Campana.objects.get(pk=campana_id)
    except Campana.DoesNotExist:
        return

    campana.estado = Campana.Estado.EN_EJECUCION
    campana.enviados = 0
    campana.errores = 0
    campana.save(update_fields=['estado', 'enviados', 'errores'])

    contactos = list(campana.destinatarios_queryset())
    campana.total_destinatarios = len(contactos)
    campana.save(update_fields=['total_destinatarios'])

    for contacto in contactos:
        contexto = {'nombre': contacto.nombre, 'telefono': contacto.telefono}
        mensaje = campana.plantilla.render(contexto)
        envio = EnvioCampana(campana=campana, contacto=contacto)
        try:
            enviar_mensaje(telefono=contacto.telefono, mensaje=mensaje)
            envio.estado = EnvioCampana.Estado.ENVIADO
            envio.enviado_at = timezone.now()
            campana.enviados += 1
        except EnvioError as exc:
            envio.estado = EnvioCampana.Estado.ERROR
            envio.detalle = str(exc)
            campana.errores += 1
        envio.save()

    campana.estado = Campana.Estado.COMPLETADA
    campana.save(update_fields=['estado', 'enviados', 'errores'])


@shared_task
def lanzar_campanas_programadas():
    """Beat: dispara las campañas cuya fecha programada ya llegó."""
    ahora = timezone.now()
    pendientes = Campana.objects.filter(estado=Campana.Estado.PROGRAMADA, fecha_programada__lte=ahora)
    for campana in pendientes:
        ejecutar_campana.delay(campana.id)
