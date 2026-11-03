"""Ejercita lo que se tocó hoy en el CRM, contra la base de verdad."""
import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()
from datetime import date, timedelta
from django.conf import settings
settings.ALLOWED_HOSTS = ['*']
from django.test import Client
from django.test.utils import setup_test_environment
setup_test_environment()
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

fallas = []
def ok(cond, msg):
    print(('  ok   ' if cond else '  FALLA ') + msg)
    if not cond: fallas.append(msg)

print('1) URLs nuevas')
for nombre in ['whatsapp:embudo', 'turnero_api:feriados']:
    try:
        print('  ok    ' + nombre + ' → ' + reverse(nombre))
    except Exception as e:
        ok(False, f'{nombre}: {e}')

print('\n2) Clientes que vuelven (estado_bot_publico)')
from apps.whatsapp.models import Conversacion, PasoConversacion
from apps.contactos.models import Contacto
from apps.reservas.models import Reserva
from apps.circuitos.models import Circuito
from apps.turnero.models import Turno

Reserva.objects.filter(contacto__nombre__startswith='REVISION').delete()
Conversacion.objects.filter(telefono__startswith='+54911999').delete()
Contacto.objects.filter(nombre__startswith='REVISION').delete()

c_nuevo, _ = Conversacion.objects.get_or_create(telefono='+549119990001')
d = c_nuevo.estado_bot_publico()
ok(d.get('cliente_recurrente') is False, 'sin contacto: cliente_recurrente=False')
ok(d.get('ultima_visita') is None, 'sin contacto: ultima_visita=None')

contacto = Contacto.objects.create(nombre='REVISION Ana', telefono='+549119990002')
c_viejo, _ = Conversacion.objects.get_or_create(telefono='+549119990002')
c_viejo.contacto = contacto; c_viejo.save()
circuito = Circuito.objects.filter(activo=True).first()
turno = Turno.objects.first()
if circuito and turno:
    ayer = date.today() - timedelta(days=30)
    Reserva.objects.create(contacto=contacto, circuito=circuito, turno=turno, fecha=ayer,
                           cantidad_personas=2, estado=Reserva.Estado.COMPLETADO,
                           precio_total=100, monto_sena=50)
    d = c_viejo.estado_bot_publico()
    ok(d.get('cliente_recurrente') is True, 'con reserva pasada: cliente_recurrente=True')
    ok(d.get('ultima_visita') == ayer.isoformat(), f'ultima_visita={d.get("ultima_visita")} (esperaba {ayer})')
    ok(d.get('visitas_totales') == 1, f'visitas_totales={d.get("visitas_totales")}')
    # Una reserva FUTURA no cuenta como visita.
    Reserva.objects.create(contacto=contacto, circuito=circuito, turno=turno,
                           fecha=date.today() + timedelta(days=10),
                           cantidad_personas=2, estado=Reserva.Estado.CONFIRMADO,
                           precio_total=100, monto_sena=50)
    d = c_viejo.estado_bot_publico()
    ok(d.get('visitas_totales') == 1, 'una reserva futura no cuenta como visita')
else:
    print('  (sin circuitos/turnos en esta base: salteado)')

print('\n3) Registro de pasos al PATCH del bot')
from apps.integraciones.models import ApiKey
k = ApiKey.objects.filter(activa=True).first() or ApiKey.objects.create(nombre='revision', activa=True)
cl = Client()
antes = PasoConversacion.objects.filter(conversacion=c_nuevo).count()
r = cl.patch(f'/api/v1/conversaciones/{c_nuevo.telefono}/', data={'estado_flujo': 'turno_personas'},
             content_type='application/json', HTTP_X_API_KEY=str(k.key))
ok(r.status_code == 200, f'PATCH responde 200 (dio {r.status_code})')
ok(PasoConversacion.objects.filter(conversacion=c_nuevo).count() == antes + 1, 'guardó el cambio de paso')
r = cl.patch(f'/api/v1/conversaciones/{c_nuevo.telefono}/', data={'estado_flujo': 'turno_personas'},
             content_type='application/json', HTTP_X_API_KEY=str(k.key))
ok(PasoConversacion.objects.filter(conversacion=c_nuevo).count() == antes + 1,
   'el mismo paso dos veces NO duplica fila')
ultimo = PasoConversacion.objects.filter(conversacion=c_nuevo).order_by('-id').first()
ok(ultimo.paso_anterior == 'nuevo', f'guarda de dónde venía (anterior={ultimo.paso_anterior})')

print('\n4) Automatizaciones de seguimiento')
from apps.automations.models import Automatizacion
from apps.automations.tasks import HANDLERS
for tipo in [Automatizacion.Tipo.SEGUIMIENTO_CHARLA, Automatizacion.Tipo.SEGUIMIENTO_CHARLA_2]:
    a = Automatizacion.objects.filter(tipo=tipo).first()
    ok(a is not None, f'{tipo} existe en la base')
    if a:
        ok(a.activa is False, f'{tipo} arranca apagada')
        ok(a.plantilla is not None, f'{tipo} tiene plantilla')
        ok(tipo in HANDLERS, f'{tipo} tiene handler registrado')
if Automatizacion.objects.filter(tipo=Automatizacion.Tipo.SEGUIMIENTO_CHARLA_2).first():
    p = Automatizacion.objects.get(tipo=Automatizacion.Tipo.SEGUIMIENTO_CHARLA_2).parametros
    ok(p.get('horas_sin_respuesta') == 24, f'el segundo escribe a las 24hs (dice {p.get("horas_sin_respuesta")})')

print('\n5) Endpoint de feriados y pantalla del embudo')
r = cl.get('/api/v1/disponibilidad/feriados/?dias=150', HTTP_X_API_KEY=str(k.key))
ok(r.status_code == 200 and 'feriados' in r.json(), f'feriados responde 200 con la lista (dio {r.status_code})')
r = cl.get('/api/v1/disponibilidad/feriados/', HTTP_X_API_KEY='clave-invalida')
ok(r.status_code in (401, 403), f'sin clave válida NO responde (dio {r.status_code})')

U = get_user_model()
u, _ = U.objects.get_or_create(username='revision_crm', defaults={'is_staff': True})
u.set_password('x'); u.save()
cl2 = Client(); cl2.force_login(u)
r = cl2.get('/inbox/embudo/')
ok(r.status_code == 200, f'el embudo carga (dio {r.status_code})')
r = cl2.get('/inbox/embudo/?dias=abc')
ok(r.status_code == 200, 'el embudo aguanta un ?dias= basura')
r = Client().get('/inbox/embudo/')
ok(r.status_code in (301, 302), f'el embudo pide login (dio {r.status_code})')

# Limpieza
Reserva.objects.filter(contacto__nombre__startswith='REVISION').delete()
Conversacion.objects.filter(telefono__startswith='+54911999').delete()
Contacto.objects.filter(nombre__startswith='REVISION').delete()
U.objects.filter(username='revision_crm').delete()

print(f'\n{"TODO OK" if not fallas else str(len(fallas)) + " FALLA(S)"}')
sys.exit(1 if fallas else 0)
