"""Helpers de control de acceso reutilizables (vistas función y CBV)."""
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


def _es_dueno(user):
    return user.is_authenticated and getattr(user, 'es_dueno', False)


#: Decorator para vistas función: solo el dueño (o superuser) puede entrar.
dueno_required = user_passes_test(_es_dueno)


class DuenoRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin para CBV: solo el dueño (o superuser) puede entrar."""

    def test_func(self):
        return _es_dueno(self.request.user)
