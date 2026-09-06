# Arquitectura y flujos internos

Cómo está construido el CRM y cómo se comporta ante cada situación. Complementa
[`api-n8n.md`](./api-n8n.md) (contrato externo) con el "por dentro".

---

## 1. Stack

| Pieza | Tecnología |
|---|---|
| Backend | Django 5.1 + Django REST Framework |
| Base de datos | PostgreSQL |
| Tareas asíncronas / programadas | Celery + django-celery-beat (Redis como broker) |
| WhatsApp gateway | Evolution API (self-hosted) |
| Orquestador del bot | n8n (cliente externo de la API) |
| Frontend | Django templates + CSS propio (marca "Estancia Cuatro Estaciones") |

### Apps de Django

```
usuarios       Usuario + roles (dueño / recepción)
contactos      Clientes, etiquetas, notas, campos personalizados (datos_extra)
circuitos      Circuitos con capacidad, precio semana/finde, seña
turnero        Turnos, feriados, bloqueos manuales, disponibilidad
reservas       Reservas, pagos, lista de espera
whatsapp       Conversaciones, mensajes, plantillas, respuestas rápidas, inbox
automations    Automatizaciones fijas (recordatorios, encuestas, etc.)
campanas       Campañas de WhatsApp por segmento
vouchers       Gift cards
tareas         Tareas internas del equipo
integraciones  API Keys + log de webhooks (auditoría de n8n)
configuracion  Configuración del negocio + CRUDs editables desde la UI
dashboard      Métricas para el dueño + panel de salud + caja del día + agenda de hoy
sitio_publico  Web pública / formularios
```

---

## 2. El modelo de negocio (clave para entender todo)

- Se reserva un **circuito** (no un profesional). Cada circuito tiene una
  **capacidad máxima** por turno.
- Una **reserva** = 1 contacto + N personas (los acompañantes son solo datos dentro de la
  reserva, no contactos independientes).
- **Modo de cupo** (config `reserva_exclusiva_por_turno`, default **ON**):
  - **Exclusivo (spa completo):** cada turno (mañana/tarde) admite **una sola reserva en todo
    el spa**, sin importar el circuito. Quien contrata no comparte el turno con otros clientes.
    El grupo se limita a la capacidad del circuito (individual=1, pareja=2, grupal=N).
  - **Por circuito:** cada circuito lleva su propio cupo; la suma de `cantidad_personas` de las
    reservas activas (`pendiente_sena`, `confirmado`, `completado`) no puede superar su capacidad.
    Pueden coexistir reservas de distintos circuitos en el mismo turno.
- **Precio** según día: `precio_semana` o `precio_finde`, según la config `dias_tarifa_finde`
  (por defecto sáb-dom; en este spa **vie-sáb-dom**).
- **Feriados: recargo, no cambio de tarifa.** Un feriado **no reemplaza** la tarifa del día, le
  **suma un porcentaje encima**:

  | El feriado cae… | Se cobra |
  |---|---|
  | Sábado (día de tarifa finde) | `precio_finde` **+ recargo** |
  | Miércoles (día de tarifa semana) | `precio_semana` **+ recargo** |

  El recargo sale de `ConfiguracionNegocio.recargo_feriado_porcentaje` (default **10%**,
  editable en *Configuración del negocio*). Un feriado puntual puede pisar ese número con su
  propio `Feriado.recargo_porcentaje` (ej. 31/12 al 50%); vacío = usa el general.

  El otro modo es *"cerrado"* (no se atiende ese día). También hay feriados **recurrentes
  anuales**, que se repiten cada año en el mismo mes/día.

  > **Ojo, esto cambió.** Antes el feriado se cobraba a `precio_finde`. Eso hacía que un feriado
  > en sábado no cobrara nada extra (ya estaba en tarifa de finde) y que uno entre semana saltara
  > a la tarifa de finde entera. La migración `turnero/0004` reetiqueta los feriados existentes.
- **Dos esquemas de precio por circuito:**
  - **Plano** (ej. Pareja): un precio fijo `precio_semana`/`precio_finde`.
  - **Por persona en tramos** (ej. Grupal): `TarifaCircuito` define la tarifa **por persona**
    según el tamaño del grupo (3–4, 5–6, 7–8…). El total = personas × tarifa del tramo. Pasando
    el último tramo, cada persona adicional paga `precio_persona_adicional_*`. El tope es
    `capacidad_maxima`. Ver `Circuito.precio_para(fecha, personas)`.
- **Seña**: monto fijo o porcentaje del precio; se calcula en el backend sobre el precio del día
  y la cantidad de personas. La reserva guarda `precio_total`, `monto_sena`, `monto_pagado` y `saldo`.

---

## 3. Flujo del bot de WhatsApp (end to end)

```
Cliente
  │  escribe por WhatsApp
  ▼
Evolution API
  │  POST /whatsapp/webhook/evolution/   (header apikey = webhook_token)
  ▼
CRM (Django)
  │  1. verifica el token del webhook
  │  2. parsea el evento de Evolution
  │  3. DEDUPLICA por message_id (si ya existía, ignora)
  │  4. guarda el mensaje en el inbox
  │  5. calcula bot_n8n_activo y fuera_de_horario
  │  6. encola forward_to_n8n (Celery)
  ▼
n8n  (POST a N8N_WEBHOOK_URL)
  │  decide la respuesta usando la API del CRM
  ▼
CRM: POST /whatsapp/api/enviar/  →  Evolution  →  Cliente
```

Puntos importantes:

- **Idempotencia:** el guardado del mensaje entrante está protegido por un *unique constraint*
  parcial sobre `whatsapp_message_id` (dirección entrante). Si Evolution reenvía el mismo
  webhook, no se duplica ni se reenvía dos veces a n8n.
- **`bot_n8n_activo`:** es `false` cuando la conversación está en handoff
  (`estado = requiere_atencion_humana` o `bot_activo = false`). n8n debe respetarlo.
- **`fuera_de_horario`:** se calcula con el horario/días configurados en
  *Configuración del negocio*. Permite un auto-reply fuera de hora.

---

## 4. Handoff (bot ↔ humano)

- **Desde n8n:** `POST /whatsapp/api/handoff/` cuando el bot no entiende o el cliente pide una
  persona.
- **Desde el inbox:** recepción puede tomar la conversación, apagar el bot y responder a mano
  (estilo WhatsApp Web).
- **Automático por falla:** si n8n no responde tras los reintentos de `forward_to_n8n`, el CRM
  hace el handoff solo → la conversación aparece como *"requiere atención humana"* en el inbox.
  Así, si el bot se cae, **nadie queda sin respuesta**.

---

## 5. Automatizaciones (Celery Beat)

Celery Beat dispara `ejecutar_automatizaciones` **cada 15 minutos**. Son **8 tipos fijos**,
cada uno activable y con plantilla de mensaje configurable desde la UI:

| Tipo | Qué hace |
|---|---|
| `recordatorio_24h` | Recordatorio del turno 24h antes |
| `recordatorio_2h` | Recordatorio del turno 2h antes |
| `reclamo_sena` | Avisa antes de que venza la seña y **libera el cupo** al vencer |
| `encuesta_satisfaccion` | Encuesta post-circuito (solo a quienes **asistieron**) |
| `reactivacion_inactivos` | Reengancha clientes sin reservas hace X días |
| `alerta_cupo` | Deja constancia cuando un turno queda con 0-1 lugares |
| `lista_espera` | Ofrece un lugar liberado al **primero** de la fila (con hold temporal) |
| `cumpleanos` | Saludo + oferta el día del cumpleaños |

Detalles de diseño:

- **Deduplicación por éxito:** cada automatización se marca en `AutomatizacionLog` solo cuando
  el envío es **exitoso**. Un envío fallido (ej. Evolution caída) se **reintenta solo** en el
  próximo ciclo. Los recordatorios tienen una ventana de tolerancia para no perderse.
- **Lista de espera con hold:** cuando se libera un cupo, se ofrece al primero de la fila y se
  le da un *hold* de unas horas antes de pasar al siguiente. No se avisa a todos a la vez (eso
  reintroduciría sobreventa).

---

## 5b. Campos personalizados y segmentación

- El dueño define **campos personalizados** de contacto desde *Configuración → Campos
  personalizados* (texto, número, fecha, sí/no, lista de opciones). Los valores se guardan en
  `Contacto.datos_extra` (JSON, indexado por `slug`) y se editan en la ficha del contacto.
- Se puede **filtrar la lista de contactos** por cualquier campo (operadores: es igual /
  contiene / desde / hasta), y **segmentar campañas** por esos mismos campos.
- Las **campañas** por segmento combinan (AND) varios filtros: etiquetas, circuito reservado,
  días de inactividad, mínimo de reservas (clientes frecuentes), email cargado y un campo
  personalizado. La lógica vive en `Campana.destinatarios_queryset()` y en
  `apps/contactos/filtros.py` (`aplicar_filtro_campo`, compartido con la lista de contactos).

## 6. Reservas: reglas y cierre del día

### Anti-sobreventa (lock de cupo)

`crear_reserva`, `reprogramar_reserva` y el canje de voucher toman un **advisory lock de
Postgres por slot** (`circuito + turno + fecha`) dentro de la transacción antes de validar el
cupo. Sin esto, dos reservas simultáneas para el último lugar leerían el mismo cupo y ambas
entrarían. El lock serializa **solo ese slot** (no bloquea el resto del sistema).

### No-shows / cierre del día

- Las reservas **no** pasan a `completado` automáticamente.
- Al terminar el día, recepción marca cada reserva desde el **turnero** (`/turnero/dia/...`):
  - **Asistió** → `completado` (habilita la encuesta de satisfacción).
  - **No vino** → `no_show`; la seña abonada queda **retenida** (queda registrado en `notas`).
- El panel de salud muestra las *"reservas pasadas sin cerrar"* como recordatorio.

### Política de cancelación (reembolso de la seña)

> **La regla:** la seña se reembolsa **solo si la reserva se cancela dentro de las 24 hs
> posteriores al pago de la seña**. Pasado ese plazo queda retenida.

El plazo se cuenta **desde el pago, no desde la fecha del turno** — es la diferencia importante
con una política de "cancelá con X horas de anticipación". Consecuencias:

- Reserva pagada hace 2 horas para dentro de 3 meses → **se reembolsa**.
- Reserva pagada hace 3 meses para el turno de mañana → **no se reembolsa**.

El punto de partida es `Reserva.sena_pagada_at`, que se setea la primera vez que la seña se
acredita, por cualquiera de las tres vías:

| Vía | Cuándo |
|---|---|
| `confirmar_reserva()` | El staff aprueba el comprobante de transferencia, o Mercado Pago acredita (flujo del bot). |
| `confirmar_sena()` | El staff cobra la seña desde el CRM (registra un `Pago` de tipo `sena`). |
| Canje de voucher | El voucher cubre la seña. |

Un **segundo pago no reabre el plazo**: manda siempre la primera acreditación.

`evaluar_reembolso_sena(reserva)` responde la pregunta, y `cancelar_reserva` deja el resultado en
`sena_reembolsable` (`true`/`false`) y una nota en `notas` explicando **por qué**, con la fecha del
pago y las horas transcurridas. El mail de "Reserva cancelada" también dice qué pasa con la plata.

En la ficha de la reserva, el recuadro de *Cancelar* muestra **antes de apretar el botón** si
corresponde reembolso y hasta cuándo (`reembolso_vence_at`). Sin seña acreditada
(`sena_pagada_at` nulo) no hay nada que reembolsar.

El plazo se configura en *Configuración del negocio* → **Horas de reembolso desde el pago**
(`horas_reembolso_desde_pago`, default 24).

### Registro de la seña al confirmar

`confirmar_reserva()` crea el `Pago` de tipo `sena` por `monto_sena`, con el medio que el
cliente eligió al reservar, y actualiza `monto_pagado`. Es idempotente: si ya hay una seña
registrada no crea otra.

> **Antes esto no pasaba** y tenía dos consecuencias: al cliente le figuraba el total entero
> como saldo pendiente, y la **caja del día** y los **ingresos del dashboard** —que suman
> `Pago`— no contaban ninguna seña cobrada por transferencia ni por Mercado Pago. Solo
> aparecían las cobradas a mano con `confirmar_sena()`.

Para las reservas viejas que quedaron sin el pago asentado hay un comando que las reconstruye,
fechando cada `Pago` el día real en que se acreditó (`sena_pagada_at`) y no el día que se corre:

```bash
python manage.py recuperar_senas_sin_registrar            # simula, no escribe
python manage.py recuperar_senas_sin_registrar --aplicar  # aplica
```

Es idempotente: correrlo dos veces no duplica.

### Confirmación de reserva → WhatsApp al cliente

Las tres puertas que confirman una reserva (`confirmar_reserva` desde la aprobación del
comprobante o Mercado Pago, y `confirmar_sena` desde el cobro manual) pasan por
`_avisar_reserva_confirmada()`, que dispara tres avisos con destinatarios distintos:

| Aviso | Para quién | Tarea |
|---|---|---|
| Confirmación con datos y cómo llegar | **El cliente**, por WhatsApp | `enviar_confirmacion_reserva` |
| Evento de reserva aprobada | **n8n**, por si tiene que hacer algo extra | `notificar_reserva_aprobada` |
| "Reserva confirmada" | **El dueño**, por mail | `notificar_evento` |

Dos detalles que importan:

- **`transaction.on_commit`, no `.delay()` suelto.** Quien confirma está dentro de una
  transacción y el worker de Celery es otro proceso: si arranca antes del commit, lee la
  reserva sin confirmar y manda datos viejos, o directamente no la encuentra.
- **Guarda anti-duplicado:** `confirmar_reserva` corta si la reserva ya estaba confirmada, así
  un doble clic en "Aprobar" no manda dos veces el mensaje.

El mensaje sale por `enviar_automatico()`, que resuelve el proveedor solo: con Evolution es
texto libre; con Meta, si la ventana de 24hs está cerrada (lo normal si el comprobante se
aprueba al otro día) manda la **plantilla aprobada**. Sin eso, la confirmación se perdería
justo después de que el cliente pagó.

El cuerpo sale de la `PlantillaMensaje` de tipo `confirmacion_reserva` (la carga la migración
`whatsapp/0009`, con `get_or_create` para no pisar ediciones). Los datos del lugar —
`direccion`, `mapa_url`, `como_llegar`, `url_politicas` — viven en `ConfiguracionNegocio` y no
en el texto de la plantilla, para que los reusen también los recordatorios.

> **Si no hay plantilla activa**, la tarea corta y deja un `warning` en el log: la reserva se
> confirma igual, pero al cliente no se le avisa.

### Reserva temporal del turno mientras se paga (hold)

Cuando se crea una reserva, el turno queda **retenido** hasta `vencimiento_sena`
(= creación + `plazo_pago_sena_horas`, config, default **2 hs**). Es un hold: bloquea el cupo
para que nadie lo pise mientras el cliente paga, y se suelta solo si no paga.

**Qué estados son un hold temporal** (`Reserva.ESTADOS_HOLD_TEMPORAL`):

| Estado | ¿Es hold? | Por qué |
|---|---|---|
| `pendiente_sena` | **Sí** | Todavía no pagó nada. |
| `pendiente_pago` | **Sí** | Se le mandó el link de Mercado Pago y no lo pagó. |
| `pendiente_aprobacion` | **No** | Ya transfirió y subió el comprobante: falta que una persona lo mire. Cancelarlo por un plazo automático sería quedarse con la plata **y** el turno. |
| `confirmado` / `completado` | **No** | Cupo firme. |

**El cupo se libera en el instante del vencimiento, no cuando corre Celery.** Toda consulta de
ocupación pasa por `Reserva.objects.ocupando_cupo()`, que descarta los holds ya vencidos:

```
Reserva.objects.ocupando_cupo()   # ← turnero, disponibilidad, validación de cupo, alerta de cupo
```

Esto es lo que evita que un hold muerto trabe el turno. Antes, el cupo dependía de que la tarea
de limpieza hubiera pasado (hasta 15 minutos de demora sobre un hold de 2 horas).

`liberar_reservas_vencidas()` es la **limpieza**: pasa los holds vencidos a `cancelado` y deja una
nota explicando por qué. Corre en `ejecutar_automatizaciones` (cada 15 min), **fuera** del loop de
automatizaciones: liberar cupo es integridad de datos, no un mensaje, así que no depende de que la
automatización `reclamo_sena` esté activa.

**Si el pago llega tarde:** `confirmar_reserva()` y `confirmar_sena()` toman el lock del slot y
revalidan el cupo cuando el hold ya venció. Si en el medio otro cliente tomó el turno, tiran
`ReservaError('hold_vencido_y_turno_tomado')` en vez de confirmar — que sería sobreventa. La API
responde **422** y la UI muestra el aviso al staff. Si el turno sigue libre, el pago tardío se
acepta sin problema.

> **Ojo con el flujo de Mercado Pago:** si el cliente paga después del vencimiento y el turno ya
> está tomado, `POST /reservas/confirmar-pago/` devuelve 422 con el `reserva_id`. Hay plata del
> cliente en el medio: eso tiene que ir a una persona (reprogramar o devolver).

---

## 7. Roles y accesos

| | Dueño | Recepción |
|---|---|---|
| Inbox, turnero, reservas, contactos, tareas | ✅ | ✅ |
| Campañas, vouchers | ✅ | ✅ |
| **Dashboard / facturación** | ✅ | ❌ (se redirige al turnero) |
| **Panel de salud del sistema** | ✅ | ❌ |
| **Configuración** (circuitos, turnos, plantillas, etc.) | ✅ | ❌ (403) |
| Admin de Django | ✅ (superuser) | ❌ |

- El gating se hace con `utils.permisos.DuenoRequiredMixin` (CBV) y `dueno_required` (vistas
  función). El sidebar oculta lo que el rol no puede usar.
- "Dueño" = usuario con `rol = 'dueno'` **o** `is_superuser`.

---

## 8. Seguridad

- **API de n8n:** autenticación por `X-Api-Key`; cada request se registra en `WebhookLog`.
  Rate limiting por IP (throttling de DRF).
- **Webhook de Evolution:** exige *webhook token*; en producción se **rechaza** si no está
  configurado.
- **Login:** rate limit anti-fuerza-bruta por IP (8 intentos / 5 min).
- **Producción:** `SECRET_KEY` inseguro hace **fallar el arranque**; cookies seguras + HSTS +
  `SESSION/CSRF_COOKIE_SECURE` (ver [`deploy.md`](./deploy.md)).
- **Datos sensibles:** alergias/preferencias se guardan como notas de contacto. Solo el staff
  logueado accede al CRM.

---

## 9. Panel de salud (`/salud/`, solo dueño)

Para detectar a tiempo si el sistema quedó mudo:

- Estado de **Celery/automatizaciones** (rojo si no corre una hace >30 min → worker/Redis caído).
- Hace cuánto llegó el **último mensaje entrante** y la **última llamada de n8n**.
- **Mensajes salientes fallidos** y **errores de Evolution** en las últimas 24h.
- **Conversaciones esperando atención humana** y **reservas pasadas sin cerrar**.


---

## 10. Web pública ← CRM (contenido editable sin deploy)

La web (`spacuatroestaciones.com`) es **HTML estático** servido por nginx desde `web/`: Django
no la toca. Para que el dueño pueda cambiar cosas sin tocar código, hay dos puentes, los dos
con la misma forma — **un endpoint público en el CRM + un `<script>` en la web**:

| Qué | Endpoint | Script | Se edita en |
|---|---|---|---|
| Precios de los circuitos | `GET /api/v1/publico/circuitos/` | `web/crm-precios.js` | Configuración → Circuitos |
| Cartel de promos (popup) | `GET /api/v1/publico/popup/` | `web/crm-popup.js` | Configuración → Popups de la web |

Los dos endpoints son `AllowAny` sin API key (los consume un navegador anónimo) y **solo leen**.
Los dos scripts fallan en silencio: si el CRM no responde, la web sigue andando — los precios
quedan en los del HTML y el popup simplemente no aparece.

### El popup

`PopupWeb` (app `sitio_publico`) con `activo` + ventana `desde`/`hasta`. El endpoint devuelve
**uno solo** (el vigente de menor `orden`) o `null`, así el script no decide nada.

`repetir_horas` lo resuelve el navegador con `localStorage`, bajo la clave `crm_popup_visto`.
La clave de cada cartel es `<id>:<version>`, donde `version` es su `updated_at`: al editar un
popup cambia la versión y **vuelve a aparecer** a quien ya lo había cerrado. Todo lectura y
escritura de `localStorage` va en `try/catch` (en navegación privada, tocarlo tira excepción).

El texto se inserta con `textContent`, nunca `innerHTML`: lo que se carga en el CRM no puede
inyectar HTML en la web.

### Media público vs. protegido

`/media/` está detrás de `login_required` porque ahí viven los **comprobantes de pago**. La foto
del popup, en cambio, tiene que verla cualquiera. Por eso hay dos rutas en `config/urls.py`, y
**el orden importa**:

```
^media/publico/(?P<path>.*)$   →  serve                    (público)
^media/(?P<path>.*)$           →  login_required(serve)    (protegido)
```

La regla pública va **primera** para ganarle el match. `PopupWeb.imagen` sube a
`publico/popups/`, así que cae del lado público. **Todo lo que se guarde bajo `media/publico/`
es visible para cualquiera**: nada sensible ahí.

### CORS

Los dos scripts hacen `fetch` cross-origin (`spacuatroestaciones.com` → `crm.spacuatroestaciones.com`).
Sin `CORS_ALLOWED_ORIGINS` con el dominio de la web, el navegador los bloquea y no se ve ni el
precio ni el popup. Ver `.env.example`.


---

## 11. SEO de la web pública

Todo el SEO vive en el **`<head>` estático** de cada `web/*.html`, no en el `<helmet>` del
framework `dc`. Es a propósito: los crawlers y sobre todo los previsualizadores de links de
**WhatsApp y Facebook** leen el HTML crudo sin ejecutar JavaScript. Un tag que aparece recién
después de que corre el JS, para ellos no existe — y WhatsApp es el canal principal del spa.

**Qué tiene cada página:**

- `<title>` y `<meta name="description">` propios, escritos para búsqueda local
  ("spa de campo Virrey del Pino", "despedida de soltera zona oeste").
- `<link rel="canonical">` — evita que `?utm_source=...` o `www` se indexen como páginas
  distintas.
- **Open Graph + Twitter Card** con `og:image` — esto es lo que hace que al pegar el link en
  WhatsApp aparezca la foto y el texto en vez de una URL pelada.
- **Geo tags** (`geo.position`, `ICBM`) apuntando a la ubicación real.
- `lang="es"` en `<html>` y favicon.

**Datos estructurados (JSON-LD):**

| Página | Tipo | Para qué |
|---|---|---|
| `index.html` | `HealthAndBeautyBusiness` | Ficha del negocio: dirección, teléfono, geo, redes, mapa, los tres circuitos como `makesOffer`. Es lo que alimenta el panel local de Google. |
| Las 3 de circuitos | `Service` | Cada circuito como servicio, con `provider` apuntando por `@id` a la ficha de la home. |

**`robots.txt` + `sitemap.xml`** en la raíz de `web/`. Las páginas legales (políticas, términos,
privacidad) van con `noindex, follow`: no aportan a la búsqueda y diluyen el sitio. **No** se
bloquean en `robots.txt` a propósito — si Google no las puede leer, nunca se entera del
`noindex`.

> **Al agregar una página nueva a `web/`:** copiá el bloque `<!-- ── SEO ── -->` de una
> existente, cambiá `title`/`description`/`canonical`/`og:image`, y sumala a `sitemap.xml`
> con su `lastmod`.

**Pendiente, es una decisión de contenido y no técnica:** el `<h1>` de la home es
*"Un refugio para desconectar del mundo y reconectar con vos"*. Es lindo pero no tiene ninguna
palabra por la que alguien busque. Un `<h1>` que incluya "Spa de Campo en Virrey del Pino"
posicionaría bastante mejor. El `<title>` ya cubre esas palabras, así que no es urgente, pero
el h1 pesa.
