# Revisión del bot y del CRM

Dos scripts para correr antes de subir cambios. No reemplazan probar la charla real, pero
agarran lo que se rompe sin avisar.

## El flujo del bot

```bash
cd herramientas/banco-bot
python3 revisar-flujo.py "/ruta/SPA Nuevo flujo ia.json"
node probar.js "/ruta/SPA Nuevo flujo ia.json"          # el parser, caso por caso
node probar-entrada.js "/ruta/SPA Nuevo flujo ia.json"  # el juntado de mensajes
```

`revisar-flujo.py` busca cinco cosas, todas vistas en producción:

1. Conexiones a nodos que no existen.
2. Nodos que no se alcanzan desde el webhook.
3. Lecturas `$('Nodo')` de nodos que pueden no haber corrido en ese camino (n8n falla en
   ejecución, con un cliente esperando).
4. **Campos fantasma**: `$('Nodo').item.json.campo` donde ese nodo nunca devuelve `campo`.
   No falla: llega `undefined`. Así un nodo recibió el mensaje del cliente vacío.
5. Nodos Code con error de sintaxis.

## El CRM

```bash
docker compose run --rm -v "$PWD:/app" web python herramientas/revision/revisar_crm.py
```

Ejercita, contra la base de verdad: las URLs nuevas, el reconocimiento de clientes que
vuelven, el registro de pasos del embudo, las dos automatizaciones de seguimiento, el
endpoint de feriados y los permisos de la pantalla del embudo. Crea datos de prueba y los
borra al final.

> **Montá el código con `-v "$PWD:/app"`.** Sin eso, el container usa la imagen construida y
> estás probando la versión anterior — no tus cambios. Pasó: un `manage.py check` dio OK
> mientras el archivo local tenía un error.
