#!/usr/bin/env python3
"""Revisa el flujo del bot sin ejecutarlo. Cinco cosas que ya rompieron algo en producción:

  1. Conexiones a nodos que no existen.
  2. Nodos que no se alcanzan desde el webhook (código muerto que uno cree activo).
  3. Lecturas `$('Nodo')` de nodos que PUEDEN no haber corrido en ese camino. n8n tira error
     en ejecución, no al importar: se descubre con un cliente esperando respuesta.
  4. Campos fantasma: `$('Nodo').item.json.campo` donde ese nodo nunca devuelve `campo`.
     No falla: llega `undefined`. Así el nodo de respuesta libre recibió el mensaje vacío.
  5. Nodos Code con error de sintaxis.

Uso:  python3 revisar-flujo.py "<flujo .json>"
Devuelve 1 si encontró algo.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict, deque

RAIZ = 'Webhook: CRM reenvia mensaje entrante'
NODE = os.environ.get('NODE_BIN', '/mnt/c/Program Files/nodejs/node.exe')

# Campos que llegan de la API del CRM o de n8n, no de un nodo del flujo.
DEL_CRM = {
    'estado_flujo', 'personas', 'tipo_propuesta', 'fecha_solicitada', 'intentos_fecha',
    'horario_confirmado', 'datos_contacto', 'override_regla', 'reserva_creada', 'nivel',
    'menu_especial_cantidad', 'extras_pedidos', 'fallos_consecutivos', 'catalogo_enviado',
    'historial', 'telefono', 'nombre', 'bot_bloqueado', 'last_message_ts', 'dias_ofrecidos',
    'menu_especial', 'nombre_cliente', 'telefono_cliente', 'email_cliente', 'medio_pago',
    'cliente_recurrente', 'ultima_visita', 'visitas_totales', 'mp_habilitado',
    'transferencia_habilitada',
    # Respuestas de la API y de los nodos HTTP.
    'extras', 'circuitos', 'feriados', 'disponibilidad', 'reserva', 'reservas', 'mensajes',
    'results', 'choices', 'body', 'statusCode', 'error', 'id', 'detalle',
}


def cargar(ruta):
    with open(ruta, encoding='utf-8') as f:
        return json.load(f)


def grafo(d):
    out, pred = defaultdict(list), defaultdict(list)
    for origen, salidas in d['connections'].items():
        for ramas in salidas.values():
            for rama in (ramas or []):
                for con in (rama or []):
                    out[origen].append(con['node'])
                    pred[con['node']].append(origen)
    return out, pred


def dominadores(nodos_vivos, out, pred):
    """Qué nodos seguro ya corrieron cuando corre cada nodo."""
    dom = {n: set(nodos_vivos) for n in nodos_vivos}
    dom[RAIZ] = {RAIZ}
    cambio = True
    while cambio:
        cambio = False
        for n in nodos_vivos:
            if n == RAIZ:
                continue
            padres = [p for p in pred[n] if p in nodos_vivos]
            if not padres:
                continue
            nuevo = set.intersection(*[dom[p] for p in padres]) | {n}
            if nuevo != dom[n]:
                dom[n] = nuevo
                cambio = True
    return dom


def campos_que_devuelve(nodo):
    """(campos, hereda) — `hereda` es True si hace spread y no se puede saber qué sale."""
    p = nodo.get('parameters', {})
    cod = p.get('jsCode')
    if cod is not None:
        campos = {m.group(1) for m in re.finditer(r'^\s{0,10}([a-z_][a-z0-9_]*)\s*:', cod, re.M | re.I)}
        return campos, bool(re.search(r'\.\.\.\s*[\w$]', cod))
    if 'values' in p:
        vals = p['values'] or {}
        return {v['name'] for t in vals.values() for v in t if isinstance(v, dict) and 'name' in v}, False
    return set(), True       # HTTP u otro: la forma la define la API, no el flujo


def revisar(ruta):
    d = cargar(ruta)
    N = {n['name']: n for n in d['nodes']}
    out, pred = grafo(d)

    fallas = []

    # 1. Conexiones rotas.
    for origen, salidas in d['connections'].items():
        for ramas in salidas.values():
            for rama in (ramas or []):
                for con in (rama or []):
                    if con['node'] not in N:
                        fallas.append(f'conexión rota: "{origen}" apunta a "{con["node"]}", que no existe')

    # 2. Alcanzables desde el webhook.
    vivos, cola = set(), deque([RAIZ])
    while cola:
        n = cola.popleft()
        if n in vivos:
            continue
        vivos.add(n)
        cola.extend(out.get(n, []))
    for n in sorted(set(N) - vivos):
        fallas.append(f'nodo inalcanzable: "{n}" (no se llega desde el webhook)')

    # 3 y 4. Lecturas de otros nodos.
    dom = dominadores(vivos, out, pred)
    patron = re.compile(r"\$\('([^']+)'\)\s*\.\s*(?:item|first\(\))\s*\.?\s*json\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)")
    for n in sorted(vivos):
        texto = json.dumps(N[n].get('parameters', {}), ensure_ascii=False)
        for origen in set(re.findall(r"\$\('([^']+)'\)", texto)):
            if origen not in N:
                fallas.append(f'"{n}" lee el nodo "{origen}", que no existe')
            elif origen not in dom[n] and origen != n:
                fallas.append(f'"{n}" lee "{origen}", que puede no haber corrido en ese camino')
        for origen, campo in patron.findall(texto):
            if origen not in N:
                continue
            devuelve, hereda = campos_que_devuelve(N[origen])
            if campo in devuelve or campo in DEL_CRM or hereda:
                continue
            fallas.append(f'campo fantasma: "{n}" lee .{campo} de "{origen}", que nunca lo devuelve')

    # 5. Sintaxis de los nodos Code.
    for n in d['nodes']:
        cod = (n.get('parameters') or {}).get('jsCode')
        if not cod:
            continue
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write('(function($, $json, $input, $now){' + cod + '})')
            tmp = f.name
        r = subprocess.run([NODE, '--check', tmp], capture_output=True, text=True)
        os.unlink(tmp)
        if r.returncode:
            detalle = (r.stderr or '').strip().splitlines()
            fallas.append(f'no compila: "{n["name"]}" — {detalle[-1] if detalle else "error de sintaxis"}')

    print(f'{len(N)} nodos · {len(vivos)} alcanzables · {sum(1 for n in d["nodes"] if (n.get("parameters") or {}).get("jsCode"))} nodos Code')
    if fallas:
        print(f'\n{len(fallas)} problema(s):')
        for f in fallas:
            print('  ✗', f)
        return 1
    print('\nsin problemas')
    return 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(revisar(sys.argv[1]))
