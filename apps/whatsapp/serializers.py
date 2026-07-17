from rest_framework import serializers


class EnviarMensajeSerializer(serializers.Serializer):
    phone = serializers.CharField()
    message = serializers.CharField(required=False, allow_blank=True, default='')
    media_url = serializers.URLField(required=False, allow_blank=True, default='')
    media_type = serializers.ChoiceField(
        choices=['image', 'video', 'audio', 'document'], required=False, allow_blank=True, default=''
    )


class HandoffSerializer(serializers.Serializer):
    telefono = serializers.CharField()
    agente_id = serializers.IntegerField(required=False, allow_null=True, default=None)
