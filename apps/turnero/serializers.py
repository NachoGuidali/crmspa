from rest_framework import serializers


class DisponibilidadQuerySerializer(serializers.Serializer):
    circuito_id = serializers.IntegerField()
    fecha = serializers.DateField()
