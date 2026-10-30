"""Chequeos propios que corren con `manage.py check` (y por lo tanto en cada deploy).

Están para frenar errores que no rompen nada —el sitio levanta igual— pero se le muestran
al usuario en pantalla.
"""
import glob
import os
import re

from django.conf import settings
from django.core.checks import Error, register

# {# … #} de Django es de UNA línea. Si abarca dos, deja de ser un comentario y el texto se
# imprime en la pantalla. Pasó dos veces, así que mejor que lo diga una máquina.
COMENTARIO_ABIERTO = re.compile(r'\{#(?![^\n]*#\})')


@register()
def comentarios_de_plantilla(app_configs, **kwargs):
    problemas = []
    for carpeta in [d for cfg in settings.TEMPLATES for d in cfg.get('DIRS', [])]:
        for ruta in glob.glob(os.path.join(carpeta, '**', '*.html'), recursive=True):
            with open(ruta, encoding='utf-8') as f:
                contenido = f.read()
            for m in COMENTARIO_ABIERTO.finditer(contenido):
                linea = contenido[:m.start()].count('\n') + 1
                problemas.append(Error(
                    f'Comentario {{# #}} de más de una línea en {os.path.relpath(ruta)}:{linea}. '
                    f'Django lo va a imprimir en la pantalla: usá {{% comment %}} … {{% endcomment %}}.',
                    id='configuracion.E001',
                ))
    return problemas
