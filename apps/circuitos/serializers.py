from rest_framework import serializers

from .models import Circuito, Extra, TarifaCircuito


class ExtraSerializer(serializers.ModelSerializer):
    class Meta:
        model = Extra
        fields = ['id', 'nombre', 'descripcion', 'precio', 'por_persona', 'circuito_id']


class TarifaCircuitoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TarifaCircuito
        fields = ['min_personas', 'max_personas', 'precio_persona_semana', 'precio_persona_finde']


class CircuitoSerializer(serializers.ModelSerializer):
    tarifas = TarifaCircuitoSerializer(many=True, read_only=True)
    precio = serializers.SerializerMethodField()
    precio_base = serializers.SerializerMethodField()
    recargo_feriado = serializers.SerializerMethodField()
    monto_sena = serializers.SerializerMethodField()

    class Meta:
        model = Circuito
        fields = [
            'id', 'nombre', 'descripcion', 'tipo', 'duracion_minutos',
            'capacidad_maxima', 'precio_semana', 'precio_finde',
            'precio_persona_adicional_semana', 'precio_persona_adicional_finde',
            'tarifas', 'precio', 'precio_base', 'recargo_feriado', 'monto_sena', 'activo',
        ]

    def _personas(self):
        return self.context.get('personas')

    def get_precio(self, obj):
        """Precio TOTAL a cobrar para la fecha y (si se pasó) la cantidad de personas del
        contexto — ya incluye el recargo por feriado. Sin personas, usa una cantidad de
        referencia (el mínimo del tramo más bajo)."""
        fecha = self.context.get('fecha')
        if not fecha:
            return None
        return obj.precio_para_fecha(fecha, self._personas())

    def get_precio_base(self, obj):
        """La tarifa del día sin el recargo por feriado. Sirve para que el bot pueda mostrar
        el desglose ('$100.000 + 10% por feriado') en vez de un número suelto."""
        fecha = self.context.get('fecha')
        if not fecha:
            return None
        personas = self._personas()
        if personas is None:
            personas = obj.personas_referencia()
        return obj.precio_base_para(fecha, personas)

    def get_recargo_feriado(self, obj):
        """Cuánta plata del precio es recargo por feriado. 0 si la fecha no es feriado."""
        fecha = self.context.get('fecha')
        if not fecha:
            return None
        return self.get_precio(obj) - self.get_precio_base(obj)

    def get_monto_sena(self, obj):
        fecha = self.context.get('fecha')
        if not fecha:
            return None
        return obj.monto_sena_para(fecha, self._personas())
