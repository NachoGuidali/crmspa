from django.contrib.auth.views import LoginView
from django.core.cache import cache

# Límite de intentos de login fallidos por IP (anti fuerza bruta).
MAX_INTENTOS = 8
VENTANA_SEGUNDOS = 300  # 5 minutos


def _ip_cliente(request):
    """La IP real del visitante, la que agrega nuestro nginx.

    Se lee la ÚLTIMA de X-Forwarded-For y no la primera: nginx usa
    `$proxy_add_x_forwarded_for`, que agrega la IP que ve al final de lo que haya mandado el
    cliente. Tomando la primera, cualquiera podía mandar un X-Forwarded-For inventado y
    distinto en cada intento, y el contador de intentos fallidos no frenaba nunca.
    """
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR', 'desconocida')


class ThrottledLoginView(LoginView):
    template_name = 'usuarios/login.html'

    def _cache_key(self):
        return f'login_intentos:{_ip_cliente(self.request)}'

    def post(self, request, *args, **kwargs):
        intentos = cache.get(self._cache_key(), 0)
        if intentos >= MAX_INTENTOS:
            form = self.get_form()
            form.errors['__all__'] = form.error_class([
                'Demasiados intentos fallidos. Esperá unos minutos e intentá de nuevo.'
            ])
            # Para que la pantalla muestre ESTO y no "usuario o contraseña incorrectos": si no,
            # la persona sigue probando la clave buena sin entender por qué no entra.
            form.bloqueado = True
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        cache.delete(self._cache_key())
        return super().form_valid(form)

    def form_invalid(self, form):
        try:
            cache.incr(self._cache_key())
        except ValueError:
            cache.set(self._cache_key(), 1, VENTANA_SEGUNDOS)
        return super().form_invalid(form)
