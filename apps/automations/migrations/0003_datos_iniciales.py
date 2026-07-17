from django.db import migrations

DEFAULT_PARAMS = {
    'recordatorio_24h': {'horas_antes': 24, 'margen_horas': 0.5},
    'recordatorio_2h': {'horas_antes': 2, 'margen_horas': 0.5},
    'reclamo_sena': {'horas_aviso': 1},
    'encuesta_satisfaccion': {'dias_despues': 1},
    'reactivacion_inactivos': {'dias_inactividad': 60},
    'alerta_cupo': {},
    'lista_espera': {},
    'cumpleanos': {},
}


def crear_automatizaciones(apps, schema_editor):
    Automatizacion = apps.get_model('automations', 'Automatizacion')
    for tipo, parametros in DEFAULT_PARAMS.items():
        Automatizacion.objects.get_or_create(
            tipo=tipo, defaults={'activa': False, 'parametros': parametros},
        )


def eliminar_automatizaciones(apps, schema_editor):
    Automatizacion = apps.get_model('automations', 'Automatizacion')
    Automatizacion.objects.filter(tipo__in=DEFAULT_PARAMS.keys()).delete()


def registrar_beat(apps, schema_editor):
    try:
        IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=15, period='minutes',
        )
        PeriodicTask.objects.get_or_create(
            name='Ejecutar automatizaciones',
            defaults={
                'interval': schedule,
                'task': 'apps.automations.tasks.ejecutar_automatizaciones',
                'enabled': True,
            },
        )
    except Exception:
        pass


def quitar_beat(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(name='Ejecutar automatizaciones').delete()
    except Exception:
        pass


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0002_initial'),
        ('django_celery_beat', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(crear_automatizaciones, eliminar_automatizaciones),
        migrations.RunPython(registrar_beat, quitar_beat),
    ]
