#!/usr/bin/env python3
"""Hace que el dominio viejo (spacuatroestaciones.com) redirija (301) al nuevo.

Sin flag toca solo los bloques de la WEB → spacuatroraices.com.ar. El CRM viejo queda igual.
Con --crm toca solo el bloque del CRM viejo → crm.spacuatroraices.com.ar. Hacelo recién cuando los
webhooks de Meta y Evolution (y el flujo de n8n) apunten al CRM nuevo: un webhook no sigue
redirects, un POST que pegue en el viejo se pierde.

Por qué un script y no editar a mano: el archivo de /etc/nginx fue reescrito por certbot, y un
error de sintaxis ahí tira abajo TODOS los sitios del server — la web nueva y el CRM incluidos.
Este script:

  1. hace backup del archivo,
  2. cambia únicamente los bloques `server` de la web vieja,
  3. corre `nginx -t`,
  4. si la prueba falla, restaura el backup y no recarga nada.

Uso:
    sudo python3 deploy/redirigir-dominio-viejo.py --solo-mostrar   # muestra el cambio, no escribe
    sudo python3 deploy/redirigir-dominio-viejo.py                  # aplica, prueba y recarga
    sudo python3 deploy/redirigir-dominio-viejo.py --crm --solo-mostrar   # idem, CRM viejo
    sudo python3 deploy/redirigir-dominio-viejo.py --crm
"""
import difflib
import re
import shutil
import subprocess
import sys
import time

ARCHIVO = '/etc/nginx/sites-available/spacuatroestaciones'
VIEJO = 'spacuatroestaciones.com'
NUEVO_WEB = 'https://spacuatroraices.com.ar$request_uri'
NUEVO_CRM = 'https://crm.spacuatroraices.com.ar$request_uri'

# Directivas que sirven el sitio y que el redirect reemplaza. Todo lo demás (listen, ssl_*,
# server_name, los "# managed by Certbot") se conserva tal cual.
QUE_SERVIR = re.compile(r'^\s*(root|index|try_files|expires|access_log|client_max_body_size)\b')


def bloques_server(texto):
    """Devuelve (inicio, fin) de cada bloque `server { ... }` de primer nivel, contando llaves."""
    bloques, i = [], 0
    for m in re.finditer(r'(?m)^\s*server\s*\{', texto):
        if m.start() < i:
            continue
        prof, j = 0, texto.index('{', m.start())
        while j < len(texto):
            if texto[j] == '{':
                prof += 1
            elif texto[j] == '}':
                prof -= 1
                if prof == 0:
                    bloques.append((m.start(), j + 1))
                    i = j + 1
                    break
            j += 1
    return bloques


def es_web_vieja(bloque):
    """Un bloque de la web vieja: sirve archivos de /opt/crmspa/web con server_name del dominio viejo.
    Nunca el del CRM (ese hace proxy_pass, no tiene root)."""
    nombres = re.search(r'server_name\s+([^;]+);', bloque)
    if not nombres or VIEJO not in nombres.group(1):
        return False
    if 'crm.' in nombres.group(1):
        return False
    return 'root' in bloque and 'proxy_pass' not in bloque


def es_crm_viejo(bloque):
    """El bloque del CRM viejo: server_name crm.spacuatroestaciones.com y hace proxy_pass."""
    nombres = re.search(r'server_name\s+([^;]+);', bloque)
    return bool(nombres) and 'crm.' + VIEJO in nombres.group(1) and 'proxy_pass' in bloque


def convertir(bloque, destino):
    """Saca lo que sirve el sitio (root, index, locations) y pone el redirect."""
    # Los `location` se sacan enteros, contando llaves.
    salida, i = [], 0
    for m in re.finditer(r'(?m)^[ \t]*location\b[^{]*\{', bloque):
        if m.start() < i:
            continue
        prof, j = 0, bloque.index('{', m.start())
        while j < len(bloque):
            if bloque[j] == '{':
                prof += 1
            elif bloque[j] == '}':
                prof -= 1
                if prof == 0:
                    break
            j += 1
        salida.append(bloque[i:m.start()])
        i = j + 1
        # consumir el salto de línea que queda después de la llave
        if i < len(bloque) and bloque[i] == '\n':
            i += 1
    salida.append(bloque[i:])
    bloque = ''.join(salida)

    lineas = [l for l in bloque.split('\n') if not QUE_SERVIR.match(l)]
    # comentarios propios que quedaron huérfanos sobre lo que se sacó
    lineas = [l for l in lineas
              if not re.match(r'^\s*#\s*(Carpeta web|Cache de assets)', l)]
    lineas = [re.sub(r'\s*#\s*subida de imágenes.*$', '', l) for l in lineas]
    cuerpo = '\n'.join(lineas)

    # El redirect va justo después de server_name, así se lee arriba del bloque.
    redirect = (
        '\n    # Dominio viejo: redirige al nuevo conservando la ruta, así cada link viejo cae\n'
        '    # en su página equivalente.\n'
        f'    return 301 {destino};'
    )
    cuerpo = re.sub(r'(server_name\s+[^;]+;)', r'\1' + redirect.replace('\\', '\\\\').replace('$', '$'),
                    cuerpo, count=1)
    # compactar líneas vacías repetidas
    return re.sub(r'\n{3,}', '\n\n', cuerpo)


def main():
    solo_mostrar = '--solo-mostrar' in sys.argv
    modo_crm = '--crm' in sys.argv
    ruta = next((a for a in sys.argv[1:] if not a.startswith('--')), ARCHIVO)
    destino = NUEVO_CRM if modo_crm else NUEVO_WEB
    que = 'del CRM viejo' if modo_crm else 'de la web vieja'

    original = open(ruta).read()
    bloques = bloques_server(original)
    elegidos = [(a, b) for a, b in bloques
                if (es_crm_viejo if modo_crm else es_web_vieja)(original[a:b])]
    # El resto de los bloques tiene que quedar byte por byte igual.
    otros = [(a, b) for a, b in bloques if (a, b) not in elegidos]

    if not elegidos:
        if f'return 301 {destino}' in original:
            print(f'El redirect {que} ya está aplicado. No hay nada que hacer.')
            return 0
        print(f'No encontré ningún bloque {que}. No toco nada.')
        return 1

    nuevo, desde = [], 0
    for a, b in elegidos:
        nuevo.append(original[desde:a])
        nuevo.append(convertir(original[a:b], destino))
        desde = b
    nuevo.append(original[desde:])
    nuevo = ''.join(nuevo)

    # Red de seguridad: lo que no se eligió no puede cambiar.
    for a, b in otros:
        if original[a:b] not in nuevo:
            print('ABORTADO: el cambio tocaba otro bloque. No escribo nada.')
            return 1

    print(f'Bloques {que} a redirigir: {len(elegidos)}')
    print(f'Otros bloques (sin tocar): {len(otros)}\n')
    sys.stdout.writelines(difflib.unified_diff(
        original.splitlines(True), nuevo.splitlines(True), 'antes', 'después'))

    if solo_mostrar:
        print('\n(--solo-mostrar: no se escribió nada)')
        return 0

    backup = f'{ruta}.bak-{time.strftime("%Y%m%d-%H%M%S")}'
    shutil.copy2(ruta, backup)
    open(ruta, 'w').write(nuevo)
    print(f'\nBackup en {backup}')

    # Cualquier falla de acá en adelante —nginx -t en rojo, o que ni siquiera se pueda correr—
    # tiene que dejar el archivo como estaba. Sin el try, una excepción saltaba entre escribir y
    # restaurar, y el archivo quedaba modificado sin validar.
    try:
        prueba = subprocess.run(['nginx', '-t'], capture_output=True, text=True)
        ok, detalle = prueba.returncode == 0, prueba.stderr
    except Exception as e:
        ok, detalle = False, f'no se pudo correr nginx -t: {e}'
    if not ok:
        shutil.copy2(backup, ruta)
        print('\nnginx -t FALLÓ. Restauré el backup, no se recargó nada. Detalle:')
        print(detalle)
        return 1

    recarga = subprocess.run(['systemctl', 'reload', 'nginx'], capture_output=True, text=True)
    if recarga.returncode != 0:
        print('\nLa config es válida y quedó escrita, pero no se pudo recargar nginx:')
        print(recarga.stderr)
        print('Recargalo a mano: sudo systemctl reload nginx')
        return 1
    print('\nnginx -t OK y recargado. Probá:')
    if modo_crm:
        print(f'  curl -sI https://crm.{VIEJO}/usuarios/login/ | grep -i ^location')
    else:
        print(f'  curl -sI https://{VIEJO}/spa-grupal.html | grep -i ^location')
    return 0


if __name__ == '__main__':
    sys.exit(main())
