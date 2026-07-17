from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Rol(models.TextChoices):
        DUENO = 'dueno', 'Dueño'
        RECEPCION = 'recepcion', 'Recepción'

    rol = models.CharField(max_length=20, choices=Rol.choices, default=Rol.RECEPCION)

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def es_dueno(self):
        return self.rol == self.Rol.DUENO or self.is_superuser
