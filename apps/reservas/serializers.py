from rest_framework import serializers

from .models import Pago, Reserva


class ReservaCrearSerializer(serializers.Serializer):
    telefono = serializers.CharField()
    nombre_contacto = serializers.CharField(required=False, allow_blank=True, default='')
    circuito_id = serializers.IntegerField()
    turno_id = serializers.IntegerField()
    fecha = serializers.DateField()
    cantidad_personas = serializers.IntegerField(min_value=1, default=1)
    acompanantes = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    notas = serializers.CharField(required=False, allow_blank=True, default='')


class PagoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pago
        fields = ['id', 'monto', 'medio_pago', 'tipo', 'fecha']


class ReservaSerializer(serializers.ModelSerializer):
    pagos = PagoSerializer(many=True, read_only=True)
    contacto_nombre = serializers.CharField(source='contacto.nombre', read_only=True)
    contacto_telefono = serializers.CharField(source='contacto.telefono', read_only=True)
    circuito_nombre = serializers.CharField(source='circuito.nombre', read_only=True)
    turno_nombre = serializers.CharField(source='turno.nombre', read_only=True)

    class Meta:
        model = Reserva
        fields = [
            'id', 'contacto_nombre', 'contacto_telefono', 'circuito_nombre', 'turno_nombre',
            'fecha', 'cantidad_personas', 'acompanantes', 'estado',
            'precio_total', 'monto_sena', 'monto_pagado', 'medio_pago', 'vencimiento_sena',
            'origen', 'resumen', 'link_pago', 'comprobante', 'notas', 'pagos',
        ]


class ConfirmarSenaSerializer(serializers.Serializer):
    monto = serializers.DecimalField(max_digits=10, decimal_places=2)
    medio_pago = serializers.ChoiceField(choices=Reserva.MedioPago.choices)


class CancelarReservaSerializer(serializers.Serializer):
    motivo = serializers.CharField(required=False, allow_blank=True, default='')


class ReprogramarReservaSerializer(serializers.Serializer):
    fecha = serializers.DateField()
    turno_id = serializers.IntegerField()
