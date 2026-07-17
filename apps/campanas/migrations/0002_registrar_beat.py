from django.db import migrations


def registrar(apps, schema_editor):
    try:
        IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        schedule, _ = IntervalSchedule.objects.get_or_create(every=5, period='minutes')
        PeriodicTask.objects.get_or_create(
            name='Lanzar campañas programadas',
            defaults={'interval': schedule, 'task': 'apps.campanas.tasks.lanzar_campanas_programadas', 'enabled': True},
        )
    except Exception:
        pass


def quitar(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(name='Lanzar campañas programadas').delete()
    except Exception:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ('campanas', '0001_initial'),
        ('django_celery_beat', '0001_initial'),
    ]
    operations = [migrations.RunPython(registrar, quitar)]
