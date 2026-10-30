"""Carga en el CRM las reservas que venían en la planilla de Excel.

Lee un CSV (hecho a partir de la planilla, ya revisado a mano) y crea los contactos, las
reservas, sus extras y el pago de la seña. Por defecto NO escribe nada: muestra qué haría.
Para que escriba hay que pasarle --aplicar.

    python manage.py importar_reservas reservas.csv                    # muestra
    python manage.py importar_reservas reservas.csv --aplicar          # escribe
    python manage.py importar_reservas reservas.csv --bloqueos dias.csv --aplicar

Se puede correr dos veces sin miedo: cada fila queda marcada con su celda de origen
(`idempotency_key`), y una reserva ya importada se saltea.
"""
import csv
from datetime import date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.circuitos.models import Circuito
from apps.contactos.models import Contacto
from apps.reservas.models import Pago, Reserva, ReservaExtra
from apps.turnero.models import BloqueoManual, Feriado, Turno
from utils.phone import normalize_ar_phone

# Lo que dice la planilla → el circuito del CRM. Se busca por nombre y no por id, que cambia
# entre la base de prueba y la del servidor.
NOMBRES_CIRCUITO = {
    ('pareja', 'premium'): 'Spa de Parejas Premium',
    ('pareja', 'clasico'): 'Spa de Parejas Clásico',
    ('grupal', 'premium'): 'Spa Grupal Premium',
    ('grupal', 'clasico'): 'Spa Grupal Clásico',
    ('despedida', ''): 'Despedida de Soltera',
}
NOMBRES_TURNO = {'mañana': 'Turno mañana', 'tarde': 'Turno tarde'}


def plata(texto):
    texto = (texto or '').strip().replace('.', '').replace('$', '')
    return Decimal(texto) if texto else None


class Command(BaseCommand):
    help = 'Importa reservas desde un CSV armado a partir de la planilla del spa.'

    def add_arguments(self, parser):
        parser.add_argument('csv', help='CSV de reservas')
        parser.add_argument('--bloqueos', help='CSV de días bloqueados y feriados')
        parser.add_argument('--aplicar', action='store_true',
                            help='Escribe en la base. Sin esto solo muestra lo que haría.')

    def handle(self, *args, **opciones):
        self.aplicar = opciones['aplicar']
        filas = self._leer(opciones['csv'])
        problemas = []

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n{len(filas)} reservas en el archivo\n'))

        for fila in filas:
            try:
                self._importar_reserva(fila)
            except CommandError as exc:
                problemas.append(f'{fila.get("celda", "?")}: {exc}')
                self.stdout.write(self.style.ERROR(f'  ✗ {fila.get("celda")}: {exc}'))

        if opciones['bloqueos']:
            self.stdout.write(self.style.MIGRATE_HEADING('\nDías bloqueados y feriados\n'))
            for fila in self._leer(opciones['bloqueos']):
                self._importar_bloqueo(fila)

        if problemas:
            self.stdout.write(self.style.ERROR(f'\n{len(problemas)} fila(s) con problemas:'))
            for p in problemas:
                self.stdout.write(self.style.ERROR(f'   {p}'))
        if not self.aplicar:
            self.stdout.write(self.style.WARNING(
                '\nNo se escribió nada. Cuando esté todo bien, repetí con --aplicar.'))

    # ── Lectura ──────────────────────────────────────────────────────────────
    def _leer(self, ruta):
        try:
            with open(ruta, encoding='utf-8-sig') as f:
                return [fila for fila in csv.DictReader(f) if any(v.strip() for v in fila.values())]
        except FileNotFoundError:
            raise CommandError(f'No encontré el archivo {ruta}')

    def _fecha(self, texto):
        try:
            return datetime.strptime(texto.strip(), '%Y-%m-%d').date()
        except ValueError:
            raise CommandError(f'fecha inválida: "{texto}" (va como 2026-11-08)')

    def _circuito(self, fila):
        clave = (fila['circuito'].strip().lower(), fila['nivel'].strip().lower())
        nombre = NOMBRES_CIRCUITO.get(clave) or NOMBRES_CIRCUITO.get((clave[0], ''))
        if not nombre:
            raise CommandError(f'no sé qué circuito es "{fila["circuito"]} {fila["nivel"]}"')
        circuito = Circuito.objects.filter(nombre__iexact=nombre).first()
        if not circuito:
            disponibles = ', '.join(Circuito.objects.values_list('nombre', flat=True))
            raise CommandError(f'falta el circuito "{nombre}" en el CRM. Hay: {disponibles}')
        return circuito

    # ── Reservas ─────────────────────────────────────────────────────────────
    def _importar_reserva(self, fila):
        celda = fila['celda'].strip()
        clave = f'excel-{celda}'
        if Reserva.objects.filter(idempotency_key=clave).exists():
            self.stdout.write(f'  = {celda}: ya estaba importada, no la toco')
            return

        fecha = self._fecha(fila['fecha'])
        circuito = self._circuito(fila)
        turno = Turno.objects.filter(nombre__iexact=NOMBRES_TURNO.get(fila['turno'].strip(), '')).first()
        if not turno:
            raise CommandError(f'no encontré el turno "{fila["turno"]}"')

        telefono = normalize_ar_phone(fila['telefono'].strip())
        if not telefono:
            raise CommandError('sin teléfono: el contacto se identifica por ahí')

        # Dos reservas en el mismo turno del mismo día es, casi siempre, un error de carga.
        choque = Reserva.objects.filter(fecha=fecha, turno=turno).exclude(
            estado=Reserva.Estado.CANCELADO).first()
        if choque:
            raise CommandError(f'ya hay una reserva ese día y turno ({choque.contacto.nombre})')

        total = plata(fila['total'])
        sena = plata(fila['sena'])
        pagado = plata(fila['pagado']) or Decimal(0)
        personas = int(fila['personas']) if fila['personas'].strip() else circuito.capacidad_minima

        notas = [f'Importada de la planilla (celda {celda}).']
        if sena and pagado and pagado != sena:
            notas.append(f'Abonó ${pagado:,.0f} de una seña de ${sena:,.0f}: '
                         f'faltan ${sena - pagado:,.0f}.'.replace(',', '.'))
        if total and pagado:
            notas.append(f'Saldo del total: ${total - pagado:,.0f}.'.replace(',', '.'))
        if fila.get('documento', '').strip():
            notas.append(f'DNI/CUIT: {fila["documento"].strip()}')
        if fila.get('notas', '').strip():
            notas.append(fila['notas'].strip())

        extras = [e.strip() for e in (fila.get('extras') or '').split(';') if e.strip()]

        self.stdout.write(
            f'  + {celda}: {fecha} {turno.nombre} · {circuito.nombre} · {personas}p · '
            f'{fila["nombre"]} ({telefono}) · total ${total or 0:,.0f} · pagado ${pagado:,.0f}'
            .replace(',', '.') + (f' · extras: {", ".join(extras)}' if extras else ''))

        if not self.aplicar:
            return

        with transaction.atomic():
            contacto, nuevo = Contacto.objects.get_or_create(
                telefono=telefono, defaults={'nombre': fila['nombre'].strip() or 'Sin nombre'})
            # A un contacto que ya existía solo se le completan los huecos: no se pisa lo suyo.
            cambios = []
            if not contacto.email and fila.get('email', '').strip():
                contacto.email = fila['email'].strip().lower(); cambios.append('email')
            if cambios:
                contacto.save(update_fields=cambios)

            reserva = Reserva.objects.create(
                contacto=contacto, circuito=circuito, turno=turno, fecha=fecha,
                cantidad_personas=personas,
                precio_total=total or Decimal(0),
                monto_sena=sena or Decimal(0),
                monto_pagado=pagado,
                medio_pago=Reserva.MedioPago.TRANSFERENCIA,
                estado=Reserva.Estado.CONFIRMADO,
                sena_pagada_at=timezone.now() if pagado else None,
                origen=Reserva.Origen.MANUAL,
                notas='\n'.join(notas),
                idempotency_key=clave,
            )
            for nombre_extra in extras:
                ReservaExtra.objects.create(
                    reserva=reserva, nombre=nombre_extra,
                    precio_unitario=Decimal(0), cantidad=1,
                )
            if pagado:
                Pago.objects.create(reserva=reserva, monto=pagado,
                                    medio_pago=Reserva.MedioPago.TRANSFERENCIA,
                                    tipo=Pago.Tipo.SENA)
            if nuevo:
                self.stdout.write(f'      contacto nuevo: {contacto.nombre}')

    # ── Bloqueos y feriados ──────────────────────────────────────────────────
    def _importar_bloqueo(self, fila):
        fecha = self._fecha(fila['fecha'])
        tipo = fila['tipo'].strip().lower()
        motivo = fila['motivo'].strip()

        if tipo == 'feriado':
            existe = Feriado.objects.filter(fecha=fecha).exists()
            self.stdout.write(f'  {"=" if existe else "+"} feriado {fecha}: {motivo}')
            if self.aplicar and not existe:
                Feriado.objects.create(fecha=fecha, descripcion=motivo, modo=Feriado.Modo.RECARGO)
            return

        turno = None
        if fila.get('turno', '').strip():
            turno = Turno.objects.filter(nombre__iexact=NOMBRES_TURNO.get(fila['turno'].strip(), '')).first()
        existe = BloqueoManual.objects.filter(fecha=fecha, turno=turno).exists()
        self.stdout.write(f'  {"=" if existe else "+"} bloqueo {fecha} '
                          f'{turno.nombre if turno else "(día completo)"}: {motivo}')
        if self.aplicar and not existe:
            BloqueoManual.objects.create(fecha=fecha, turno=turno, motivo=motivo)
