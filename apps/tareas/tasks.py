from celery import shared_task
from django.utils import timezone

from .models import Tarea


@shared_task
def marcar_tareas_vencidas():
    Tarea.objects.filter(
        estado=Tarea.Estado.PENDIENTE, fecha_programada__lt=timezone.now()
    ).update(estado=Tarea.Estado.VENCIDA)
