from django.db import migrations


def registrar(apps, schema_editor):
    try:
        IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        schedule, _ = IntervalSchedule.objects.get_or_create(every=15, period='minutes')
        PeriodicTask.objects.get_or_create(
            name='Marcar tareas vencidas',
            defaults={'interval': schedule, 'task': 'apps.tareas.tasks.marcar_tareas_vencidas', 'enabled': True},
        )
    except Exception:
        pass


def quitar(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(name='Marcar tareas vencidas').delete()
    except Exception:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ('tareas', '0001_initial'),
        ('django_celery_beat', '0001_initial'),
    ]
    operations = [migrations.RunPython(registrar, quitar)]
