from rest_framework import serializers

from .models import Contacto, Etiqueta


class EtiquetaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Etiqueta
        fields = ['id', 'nombre', 'color']


class ContactoSerializer(serializers.ModelSerializer):
    etiquetas = EtiquetaSerializer(many=True, read_only=True)

    class Meta:
        model = Contacto
        fields = ['id', 'nombre', 'telefono', 'email', 'fecha_nacimiento', 'etiquetas', 'fecha_alta']
        read_only_fields = ['id', 'fecha_alta']


class ContactoBuscarSerializer(serializers.Serializer):
    telefono = serializers.CharField()


class ContactoCrearSerializer(serializers.Serializer):
    telefono = serializers.CharField()
    nombre = serializers.CharField(required=False, allow_blank=True, default='')
    email = serializers.EmailField(required=False, allow_blank=True, default='')
