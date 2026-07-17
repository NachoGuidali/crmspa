from rest_framework import serializers

from .models import Circuito, TarifaCircuito


class TarifaCircuitoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TarifaCircuito
        fields = ['min_personas', 'max_personas', 'precio_persona_semana', 'precio_persona_finde']


class CircuitoSerializer(serializers.ModelSerializer):
    tarifas = TarifaCircuitoSerializer(many=True, read_only=True)
    precio = serializers.SerializerMethodField()
    monto_sena = serializers.SerializerMethodField()

    class Meta:
        model = Circuito
        fields = [
            'id', 'nombre', 'descripcion', 'tipo', 'duracion_minutos',
            'capacidad_maxima', 'precio_semana', 'precio_finde',
            'precio_persona_adicional_semana', 'precio_persona_adicional_finde',
            'tarifas', 'precio', 'monto_sena', 'activo',
        ]

    def get_precio(self, obj):
        """Precio TOTAL para la fecha y (si se pasó) la cantidad de personas del contexto.
        Sin personas, usa una cantidad de referencia (el mínimo del tramo más bajo)."""
        fecha = self.context.get('fecha')
        if not fecha:
            return None
        return obj.precio_para_fecha(fecha, self.context.get('personas'))

    def get_monto_sena(self, obj):
        fecha = self.context.get('fecha')
        if not fecha:
            return None
        return obj.monto_sena_para(fecha, self.context.get('personas'))
