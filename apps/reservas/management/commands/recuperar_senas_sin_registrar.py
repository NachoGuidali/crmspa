# -*- coding: utf-8 -*-
"""Registra las señas de reservas que se confirmaron sin dejar el `Pago` asentado.

Durante un tiempo, `confirmar_reserva()` marcaba la reserva como confirmada pero no creaba el
`Pago` de la seña. Esas señas se cobraron de verdad —la reserva se confirmó justamente porque
alguien verificó la transferencia o Mercado Pago acreditó— pero no figuran en la caja del día
ni en los ingresos del dashboard, que suman `Pago`.

Este comando las reconstruye. Por defecto solo MUESTRA lo que haría; hay que pasar `--aplicar`
para que escriba. Se puede correr las veces que haga falta: nunca duplica.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.reservas.models import Pago, Reserva


class Command(BaseCommand):
    help = 'Registra el Pago de seña de las reservas confirmadas que quedaron sin él.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--aplicar', action='store_true',
            help='Escribe los cambios. Sin esto solo muestra qué haría.',
        )

    def handle(self, *args, **options):
        aplicar = options['aplicar']

        # Confirmadas o ya realizadas, sin plata registrada y sin ningún pago cargado.
        # `sena_pagada_at` no nulo es la marca de que la seña se acreditó de verdad.
        candidatas = (
            Reserva.objects
            .filter(
                estado__in=[Reserva.Estado.CONFIRMADO, Reserva.Estado.COMPLETADO],
                monto_pagado=0,
                sena_pagada_at__isnull=False,
                monto_sena__gt=0,
            )
            .exclude(pagos__isnull=False)
            .select_related('contacto', 'circuito', 'turno')
            .order_by('fecha')
        )

        if not candidatas.exists():
            self.stdout.write(self.style.SUCCESS(
                'No hay señas sin registrar. La caja ya está completa.'))
            return

        total = Decimal('0')
        self.stdout.write('')
        self.stdout.write(f'{"FECHA":<12} {"CONTACTO":<24} {"CIRCUITO":<22} {"SEÑA":>12}  MEDIO')
        self.stdout.write('─' * 88)
        for r in candidatas:
            total += r.monto_sena
            self.stdout.write(
                f'{r.fecha.strftime("%d/%m/%Y"):<12} {r.contacto.nombre[:23]:<24} '
                f'{r.circuito.nombre[:21]:<22} {r.monto_sena:>12,.0f}  '
                f'{r.get_medio_pago_display() or "sin especificar"}'
            )
        self.stdout.write('─' * 88)
        self.stdout.write(f'{"":<60}{"TOTAL":>12} {total:>11,.0f}')
        self.stdout.write('')

        n = candidatas.count()
        if not aplicar:
            self.stdout.write(self.style.WARNING(
                f'Simulación: {n} reserva(s) por ${total:,.0f}. No se escribió nada.\n'
                f'Para aplicarlo de verdad:\n'
                f'  python manage.py recuperar_senas_sin_registrar --aplicar'
            ))
            return

        with transaction.atomic():
            for r in candidatas:
                Pago.objects.create(
                    reserva=r,
                    monto=r.monto_sena,
                    medio_pago=r.medio_pago or Reserva.MedioPago.OTRO,
                    tipo=Pago.Tipo.SENA,
                    # `fecha` es auto_now_add, así que el pago queda fechado hoy. Lo dejamos
                    # explícito abajo para que la caja lo ubique el día real de la seña.
                )
                Pago.objects.filter(reserva=r, tipo=Pago.Tipo.SENA).update(fecha=r.sena_pagada_at)
                r.monto_pagado = r.monto_sena
                r.save(update_fields=['monto_pagado', 'updated_at'])

        self.stdout.write(self.style.SUCCESS(
            f'Listo: {n} seña(s) registradas por ${total:,.0f}. '
            f'Cada pago quedó fechado el día en que se acreditó, así la caja de esos días '
            f'refleja lo que entró.'
        ))
