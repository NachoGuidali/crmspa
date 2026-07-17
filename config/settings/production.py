from decouple import Csv, config

from .base import *  # noqa: F401,F403
from .base import SECRET_KEY

DEBUG = False

# En producción no se permite arrancar con la SECRET_KEY de desarrollo.
if SECRET_KEY.startswith('django-insecure'):
    raise RuntimeError(
        'SECRET_KEY inseguro en producción. Definí la variable de entorno SECRET_KEY '
        'con un valor aleatorio y secreto.'
    )

CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())

SECURE_SSL_REDIRECT = False  # SSL termination happens at nginx
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
