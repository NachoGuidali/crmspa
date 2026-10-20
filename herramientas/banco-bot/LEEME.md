# Banco de pruebas del bot

Corre el nodo **`Code: parsear interpretacion IA`** del flujo de n8n acá, sin n8n y sin mandar
WhatsApps. Ese nodo es el cerebro: decide qué entendió el bot, qué dato guarda, cuándo repregunta
y cuándo deriva a una persona. Casi todos los "se trabó" o "no entendió" salen de ahí.

## Antes de importar un flujo a n8n

```bash
cd herramientas/banco-bot
node probar.js "/ruta/al/Bot WhatsApp - nuevo flujo nacho (v2 revisado).json"
node probar-entrada.js "/ruta/al/mismo.json"
```

El segundo prueba el nodo **`juntar mensajes`**: el que decide, cuando el cliente escribe en
varias tandas, cuál de las ejecuciones contesta y con qué texto. Si eso falla, el bot contesta
tres veces o no contesta ninguna.

Tienen que dar todos OK. Para ver qué cambia respecto de la versión que está en producción:

```bash
node comparar.js "/ruta/flujo-en-produccion.json" "/ruta/flujo-nuevo.json"
```

Lo que aparezca tiene que ser exactamente lo que quisiste cambiar; si cambia otra cosa, es un
efecto colateral.

## Los casos

Están en `casos.js`, uno por línea de conversación real. Lo importante de cada caso:

- `conversacion`: en qué paso del turnero está y qué sabe el CRM de esa persona.
- `ia`: lo que devuelve el modelo. **Un `{}` vacío significa "el modelo no entendió nada"**, que
  es el escenario que más importa: ahí se ve qué resuelve el flujo solo, por texto. La mayoría de
  las fallas de octubre fueron eso — el modelo falló y abajo no había red.
- `espera`: los campos que tienen que salir.

Agregá un caso cada vez que aparezca una conversación que salió mal: queda documentada y no
vuelve a romperse en silencio.

## Qué NO cubre

Solo el parser. No prueba los nodos que arman los mensajes, las llamadas al CRM ni el ruteo entre
pasos; eso se prueba en n8n con un flujo duplicado. `luxon-min.js` es un reemplazo mínimo de las
fechas que n8n expone como `$now`.

## Comparar modelos

Le hace las mismas preguntas a varios modelos con el prompt real del bot y muestra las
respuestas lado a lado, con tiempo, tokens y costo de cada una:

```bash
export OPENAI_API_KEY=...        # la de Groq la saca del flujo si no está en el entorno
node comparar-modelos.js "/ruta/al/flujo.json"
node comparar-modelos.js "/ruta/al/flujo.json" groq:openai/gpt-oss-120b openai:gpt-5-nano
```

Los casos están en `casos-modelos.js`: son conversaciones reales que salieron mal. Agregá las
nuevas ahí. El veredicto lo ponés vos mirando si el modelo entendió lo que la persona quiso
decir; el script no "corrige" solo, porque no hay una única respuesta correcta.

> **Gasta plata de verdad**: cada corrida son unas 8 llamadas por modelo (centavos). Y consume
> del límite por minuto de la cuenta: con el plan gratis de Groq (8.000 tokens por minuto) la
> corrida completa se corta por rate limit a mitad de camino.
