from rest_framework import serializers


class DisponibilidadQuerySerializer(serializers.Serializer):
    circuito_id = serializers.IntegerField()
    fecha = serializers.DateField()


class RangoDisponibilidadQuerySerializer(serializers.Serializer):
    circuito_id = serializers.IntegerField()
    desde = serializers.DateField()
    hasta = serializers.DateField()
    personas = serializers.IntegerField(required=False, min_value=1)
