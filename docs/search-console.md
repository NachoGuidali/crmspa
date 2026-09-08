# Cómo dar de alta la web en Google Search Console

**Para:** quien administra la cuenta de Google del spa
**Sitio:** spacuatroestaciones.com

---

## Antes de empezar

**Google Search Console** es una herramienta gratuita de Google. Sirve para dos cosas:

1. **Avisarle a Google que la web existe**, para que la muestre en los resultados de búsqueda.
2. **Ver por qué búsquedas te encuentra la gente** ("spa de campo zona oeste", "despedida de
   soltera la matanza") y cuántas veces te mostró.

La web ya está preparada por dentro para esto — títulos, descripciones, ficha del negocio y
mapa del sitio. Falta solo darla de alta.

### Dos cosas para tener a mano

- **La cuenta de Google del spa.** Usá **la misma** con la que manejás la ficha del negocio en
  Google Maps. Si usás otra, después no se pueden conectar entre sí.
- **Acceso al proveedor del dominio** (donde se compró `spacuatroestaciones.com`, normalmente
  DonWeb). Hace falta en el paso 3. **Si no lo tenés, pedíselo a Nacho** — es un solo dato que
  hay que cargar y no cuesta nada.

> ⏱️ Son unos 15 minutos. Después hay que esperar: Google tarda **entre unos días y 2 o 3
> semanas** en empezar a mostrar información.

---

## Paso 1 — Entrar

Andá a **[search.google.com/search-console](https://search.google.com/search-console)** e
iniciá sesión con la cuenta de Google del spa.

Si es la primera vez, te va a ofrecer directamente agregar una propiedad y podés saltar al
paso 2. Si ya entraste antes, arriba a la izquierda hay un desplegable con el nombre del sitio:
abrilo y elegí **"Agregar propiedad"**.

## Paso 2 — Elegir el tipo "Dominio"

Google te va a mostrar **dos opciones**:

| Opción | ¿Cuál elegir? |
|---|---|
| **Dominio** | ✅ **Esta.** Cubre la web entera de una sola vez. |
| Prefijo de la URL | ❌ No. Habría que cargar cada versión de la dirección por separado. |

En el recuadro de la izquierda ("Dominio"), escribí exactamente:

```
spacuatroestaciones.com
```

Sin `https://` y sin `www`. Tocá **Continuar**.

## Paso 3 — Verificar que la web es tuya

Google necesita comprobar que sos el dueño del sitio. Te va a mostrar un texto largo parecido a:

```
google-site-verification=AbC123xyz...
```

**Copialo completo.**

Ahora hay que pegarlo en el panel del proveedor del dominio:

1. Entrá a tu cuenta del proveedor (DonWeb u otro).
2. Buscá la sección **"Dominios"** → tu dominio → **"Zona DNS"** o **"Administrar DNS"**.
3. Agregá un registro nuevo con estos datos:

| Campo | Qué poner |
|---|---|
| **Tipo** | `TXT` |
| **Nombre** o **Host** | `@` (si no lo acepta, dejalo vacío o poné el dominio) |
| **Valor** o **Contenido** | El texto `google-site-verification=...` completo |
| **TTL** | Dejá el que viene por defecto |

4. Guardá.
5. Volvé a Search Console y tocá **"Verificar"**.

> **Si dice que no lo encuentra:** es normal. Esperá 15 o 20 minutos y probá de nuevo. A veces
> tarda algunas horas en propagarse.

> ⚠️ **No borres nunca ese registro TXT.** Google lo revisa cada tanto; si desaparece, perdés
> el acceso y hay que rehacer todo.

## Paso 4 — Enviar el mapa del sitio

Esto le pasa a Google la lista de todas las páginas de una.

1. En el menú de la izquierda, entrá a **"Sitemaps"**.
2. Donde dice "Agregar un sitemap nuevo", escribí:

```
sitemap.xml
```

3. Tocá **Enviar**.

Tiene que quedar en estado **"Correcto"**, con **7 páginas** detectadas. Si figura "No se pudo
obtener", esperá un rato y actualizá — a veces lo lee recién unas horas después.

## Paso 5 — Pedir que revise las páginas principales

Esto acelera la aparición en Google.

Arriba de todo hay una barra de búsqueda que dice *"Inspeccionar cualquier URL"*. Pegá estas
cuatro direcciones, **de a una**, y en cada una tocá **"Solicitar indexación"**:

```
https://spacuatroestaciones.com/
https://spacuatroestaciones.com/spa-de-parejas.html
https://spacuatroestaciones.com/spa-grupal.html
https://spacuatroestaciones.com/despedida-de-soltera.html
```

Cada una tarda un minuto en procesarse. Si dice *"La URL no está en Google"*, está bien — es
justamente lo que estás pidiendo que cambie.

---

## Listo. ¿Y ahora?

**Los primeros días el panel va a estar vacío** y va a decir que no hay datos. **Es normal, no
está fallando.** Google necesita tiempo.

Volvé a entrar **en 2 semanas** y mirá dos secciones:

- **Rendimiento** — por qué palabras te encuentra la gente y cuántas veces apareciste. Es la
  información más útil: te dice qué busca realmente la gente que llega al spa.
- **Páginas** — cuáles indexó y cuáles no.

> Vas a ver aparecer también `crm.spacuatroestaciones.com` (el sistema interno), marcado como
> **"Excluida por etiqueta noindex"**. **Está bien así, es a propósito**: el CRM no tiene que
> salir en Google. No hay nada que arreglar ahí.

---

## Lo que MÁS te va a servir (y no es Search Console)

Con la web ya damos por cubierta la parte técnica. Pero para un spa, **lo que más clientes
trae es la ficha de Google Maps**, no la web. Cuando alguien busca "spa de campo zona oeste",
lo primero que aparece es el mapa con tres negocios — no los resultados de abajo.

Ahí ya tenés una base excelente: **4,7 estrellas con 115 reseñas**. Vale mucho la pena
aprovecharla. Entrá a **[business.google.com](https://business.google.com)** con la misma
cuenta y revisá:

- [ ] **Horarios de atención cargados** y actualizados.
- [ ] **Servicios cargados uno por uno**: Spa de Parejas, Spa Grupal, Despedida de Soltera.
- [ ] **Rango de precios** y atributos (estacionamiento, apto grupos, etc.).
- [ ] **El link a la web** apuntando a `spacuatroestaciones.com`.
- [ ] **Fotos nuevas cada tanto.** Google le da mejor lugar a los perfiles activos, y las fotos
      son lo primero que mira la gente. De material te sobra.
- [ ] **Responder todas las reseñas**, no solo algunas. Cuenta como señal de actividad, y el que
      lee las respuestas se da cuenta de cómo atienden.
- [ ] **Usar "Publicaciones"** para promos y fechas especiales — las mismas que cargás en el
      cartel de la web. Es gratis y aparece al costado en Google.

---

## Tres cosas para definir

Estas necesitan una decisión tuya, no son técnicas:

1. **¿"Residencia" o "Estancia"?** En Google Maps el negocio figura como **Residencia Cuatro
   Estaciones**, pero la web y la marca dicen **Cuatro Raíces**. Para Google son
   dos negocios distintos y eso le resta fuerza a los dos. Conviene unificar con un solo nombre.

2. **¿Sigue siendo 4,7 con 115 reseñas?** Ese número está escrito en la web. Si cambió, decilo
   y se actualiza.

3. **¿Se puede publicar la dirección exacta?** Hoy la web dice solo "Virrey del Pino, Buenos
   Aires". Poner la calle y el número ayuda bastante en las búsquedas del tipo "spa cerca mío".
   Si preferís no publicarla por privacidad, se deja como está — es una decisión del negocio.

---

## Si algo no sale

Anotá en qué paso te trabaste y qué decía la pantalla, y pasáselo a Nacho. Ningún paso de acá
rompe nada: si algo sale mal, se vuelve a intentar sin problema.
