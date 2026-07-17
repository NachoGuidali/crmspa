"""Carga inicial del spa: configuración, turnos, circuitos con precios reales y extras.

Idempotente — se puede correr varias veces sin duplicar. Uso:
    python manage.py seed_inicial
"""
from datetime import time
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.core.cache import cache
from django.db import transaction

from apps.circuitos.models import Circuito, Extra, TarifaCircuito
from apps.configuracion.models import ConfiguracionNegocio
from apps.turnero.models import Turno

D = lambda x: Decimal(str(x))

CIRCUITOS = [
    {
        'nombre': 'Spa Grupal Clásico', 'tipo': 'grupal',
        'capacidad_minima': 3, 'capacidad_maxima': 8, 'duracion_minutos': 300,
        'descripcion': (
            'Circuito privado para grupos de 3 a 8 personas · 5 horas. No se comparte con otros grupos.\n'
            'Incluye: merienda clásica (dulce y salado), masaje relajante 25 min, ozonoterapia 25 min, '
            'jacuzzi con hidromasaje 40 min, sector de hidratación, infusiones libres, living exterior, '
            'kit de batas y toallas, pool, juegos de mesa, quincho climatizado y acceso a áreas comunes.'
        ),
        'adicional': 15000,
        'tramos': [(3, 4, 130000, 150000), (5, 6, 125000, 140000), (7, 8, 118000, 130000)],
    },
    {
        'nombre': 'Spa Grupal Premium', 'tipo': 'grupal',
        'capacidad_minima': 3, 'capacidad_maxima': 8, 'duracion_minutos': 300,
        'descripcion': (
            'Circuito privado para grupos de 3 a 8 personas · 5 horas. No se comparte con otros grupos.\n'
            'Incluye: brunch premium y picada de campo, masaje descontracturante 35 min, ozonoterapia, '
            'sauna individual 30 min, mascarillas faciales, circuito completo de aguas (jacuzzi y tina '
            'finlandesa), ensalada de frutas, infusiones libres, living y ducha exterior, kit de batas, '
            'pool, juegos, quincho climatizado, 1 trago por persona y brindis final con champagne.'
        ),
        'adicional': 20000,
        'tramos': [(3, 4, 155000, 175000), (5, 6, 140000, 160000), (7, 8, 135000, 145000)],
    },
    {
        'nombre': 'Spa de Parejas Clásico', 'tipo': 'pareja',
        'capacidad_minima': 2, 'capacidad_maxima': 2, 'duracion_minutos': 240,
        'descripcion': (
            'Circuito exclusivo para parejas (2 personas) · 4 horas.\n'
            'Incluye: merienda completa, masaje relajante 35 min, ozonoterapia, sauna individual 25 min, '
            'jacuzzi para dos, infusiones libres, living exterior, pool, juegos, ambientación con luces y '
            'velas, kit de batas y toallas, quincho climatizado y brindis final.\n'
            'Opcionales: tabla de picada, tina finlandesa, +25 min de masaje.'
        ),
        'precio_semana': 296000, 'precio_finde': 316000,
    },
    {
        'nombre': 'Spa de Parejas Premium', 'tipo': 'pareja',
        'capacidad_minima': 2, 'capacidad_maxima': 2, 'duracion_minutos': 300,
        'descripcion': (
            'Circuito exclusivo para parejas (2 personas) · 5 horas.\n'
            'Incluye: brunch premium, masaje descontracturante 55-60 min, sillón masajeador, ozonoterapia, '
            'sauna individual 30 min, mascarilla hidratante, circuito completo de aguas (jacuzzi con sales, '
            'tina finlandesa, sauna seco), mascarilla facial, ensalada de frutas, 2 tragos, living exterior, '
            'pool, juegos, ambientación con velas, kit de batas y toallas, quincho climatizado y brindis final.'
        ),
        'precio_semana': 320000, 'precio_finde': 350000,
    },
]

# Opcionales (aplican al Pareja Clásico según el material del spa)
EXTRAS = [
    ('Tabla de picada de campo', 6000, 'Spa de Parejas Clásico'),
    ('Tina finlandesa', 8000, 'Spa de Parejas Clásico'),
    ('25 min adicionales de masaje', 5000, 'Spa de Parejas Clásico'),
]


class Command(BaseCommand):
    help = 'Carga inicial: configuración, turnos, circuitos con precios reales y extras.'

    @transaction.atomic
    def handle(self, *args, **options):
        # --- Configuración del negocio ---
        cfg = ConfiguracionNegocio.get_solo()
        cfg.nombre_negocio = 'Estancia Cuatro Estaciones'
        cfg.dias_tarifa_finde = [4, 5, 6]       # Vie-Sáb-Dom
        cfg.reserva_exclusiva_por_turno = True   # spa privado, 1 reserva por turno
        cfg.save()
        cache.delete('configuracion_negocio')
        self.stdout.write('Configuración del negocio ✓')

        # --- Turnos (horarios placeholder, ajustables desde el CRM) ---
        for nombre, ini, fin in [('Turno mañana', time(9, 0), time(13, 0)),
                                 ('Turno tarde', time(15, 0), time(19, 0))]:
            Turno.objects.get_or_create(
                nombre=nombre, defaults={'hora_inicio': ini, 'hora_fin': fin, 'dias_aplicables': [], 'activo': True}
            )
        self.stdout.write('Turnos (mañana/tarde) ✓')

        # --- Circuitos + precios ---
        for data in CIRCUITOS:
            tramos = data.pop('tramos', None)
            adicional = data.pop('adicional', None)
            precio_semana = data.pop('precio_semana', None)
            precio_finde = data.pop('precio_finde', None)

            c, _ = Circuito.objects.get_or_create(nombre=data['nombre'], defaults=data)
            for k, v in data.items():
                setattr(c, k, v)
            c.sena_tipo = 'porcentaje'
            c.sena_valor = D(50)
            c.activo = True
            if tramos:
                c.precio_semana = None
                c.precio_finde = None
                c.precio_persona_adicional_semana = D(adicional)
                c.precio_persona_adicional_finde = D(adicional)
            else:
                c.precio_semana = D(precio_semana)
                c.precio_finde = D(precio_finde)
            c.save()

            if tramos:
                c.tarifas.all().delete()
                for mn, mx, ps, pf in tramos:
                    TarifaCircuito.objects.create(
                        circuito=c, min_personas=mn, max_personas=mx,
                        precio_persona_semana=D(ps), precio_persona_finde=D(pf),
                    )
            self.stdout.write(f'Circuito: {c.nombre} ✓')

        # --- Extras / opcionales ---
        for nombre, precio, circuito_nombre in EXTRAS:
            circ = Circuito.objects.filter(nombre=circuito_nombre).first()
            Extra.objects.get_or_create(
                nombre=nombre, defaults={'precio': D(precio), 'circuito': circ, 'activo': True}
            )
        self.stdout.write('Extras / opcionales ✓')

        self.stdout.write(self.style.SUCCESS('\nCarga inicial completa.'))
