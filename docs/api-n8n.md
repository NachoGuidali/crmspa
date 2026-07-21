# API del CRM para n8n

Contrato completo de la API que **n8n** consume para operar el bot de WhatsApp.

> **Regla de oro:** toda la lógica de negocio (cupo, precios por día, seña, políticas de
> cancelación, validaciones) vive en este backend. n8n **no** calcula nada de eso: solo
> llama a estos endpoints y arma la conversación con las respuestas. Si algo de negocio
> parece faltar, se agrega acá, no en n8n.

---

## 1. Autenticación

Casi todos los endpoints exigen una **API Key** en el header:

```
X-Api-Key: <uuid-de-la-api-key>
```

- Las keys se crean/desactivan desde el **admin de Django** → *Integraciones → API Keys*.
- Cada llamada queda registrada en `WebhookLog` (auditoría: endpoint, IP, body, status).
- Sin key válida → `401`/`403`.

**Excepción:** el webhook entrante de Evolution (`/whatsapp/webhook/evolution/`) **no** usa
`X-Api-Key`; usa el header `apikey` con el *webhook token* (ver §7).

### Rate limiting

| Ámbito | Límite por defecto | Variable de entorno |
|---|---|---|
| Llamadas de n8n (anónimas por API Key) | `120/min` por IP | `THROTTLE_ANON` |
| Webhook de Evolution | `600/min` por IP | `THROTTLE_WEBHOOK` |

Si se supera → `429 Too Many Requests`.

### Base URL

```
https://<tu-dominio>/api/v1/
```

Los ejemplos usan `http://localhost:8003` (Docker local).

---

## 2. Formato general

- Request y response en **JSON** (`Content-Type: application/json`).
- Fechas: **`YYYY-MM-DD`** (ISO). Horas: **`HH:MM`**. Zona horaria del negocio:
  `America/Argentina/Buenos_Aires`.
- Teléfonos: se pueden mandar en cualquier formato argentino razonable; el backend los
  **normaliza** (`+549...`). Se recomienda mandar con código de país.
- Montos: números decimales (pesos).

### Códigos de error de negocio (campo `error`)

| `error` | Significado |
|---|---|
| `circuito_not_found` | El circuito no existe o está inactivo |
| `turno_not_found` | El turno no existe o está inactivo |
| `turno_no_aplica_ese_dia` | Ese turno no se ofrece ese día de la semana |
| `dia_no_habilitado` | Feriado o día fuera de los laborables |
| `turno_bloqueado` | Bloqueo manual (mantenimiento, evento privado, etc.) |
| `fecha_en_el_pasado` | La fecha pedida ya pasó |
| `sin_cupo: ...` | No hay lugar en ese turno/fecha |

---

## 3. Contactos

### Buscar contacto por teléfono
`GET /api/v1/contactos/buscar/?telefono=3815551234`

**200** (existe):
```json
{
  "found": true,
  "id": 12,
  "nombre": "Ana Pérez",
  "telefono": "+5493815551234",
  "email": "ana@mail.com",
  "fecha_nacimiento": "1990-05-20",
  "etiquetas": [{"id": 3, "nombre": "VIP", "color": "#617245"}],
  "fecha_alta": "2026-01-10T14:30:00Z"
}
```
**404** (no existe): `{"found": false, "telefono": "+5493815551234"}`

### Crear (o completar) contacto
`POST /api/v1/contactos/`
```json
{"telefono": "3815551234", "nombre": "Ana Pérez", "email": "ana@mail.com"}
```
- Si el teléfono ya existe, **completa** los campos vacíos (no pisa datos cargados).

**201** (creado) / **200** (actualizado):
```json
{"status": "created", "contacto_id": 12, "telefono": "+5493815551234"}
```

> **Nota:** normalmente **no** hace falta crear el contacto aparte: `POST /reservas/` y
> `POST /vouchers/canjear/` lo crean solos con el teléfono.

---

## 4. Circuitos y disponibilidad

### Listar circuitos con precio y seña para una fecha
`GET /api/v1/circuitos/?fecha=2026-07-11&personas=6`

Si no mandás `fecha`, usa hoy. `personas` es opcional pero **recomendado** para circuitos que
cobran por persona (ver abajo). El backend ya calcula **precio total** y **seña**.

**200:**
```json
{
  "fecha": "2026-07-11",
  "personas": 6,
  "circuitos": [
    {
      "id": 2, "nombre": "Grupal Clásica", "descripcion": "...",
      "tipo": "grupal", "duracion_minutos": 120, "capacidad_maxima": 12,
      "precio_semana": null, "precio_finde": null,
      "precio_persona_adicional_semana": "7000.00", "precio_persona_adicional_finde": "9000.00",
      "tarifas": [
        {"min_personas": 3, "max_personas": 4, "precio_persona_semana": "10000.00", "precio_persona_finde": "12000.00"},
        {"min_personas": 5, "max_personas": 6, "precio_persona_semana": "9000.00", "precio_persona_finde": "11000.00"},
        {"min_personas": 7, "max_personas": 8, "precio_persona_semana": "8000.00", "precio_persona_finde": "10000.00"}
      ],
      "precio": "66000.00", "monto_sena": "33000.00", "activo": true
    }
  ]
}
```

**Dos tipos de precio:**
- **Precio plano** (ej. Pareja): `precio_semana` / `precio_finde` tienen valor y `tarifas` está vacío.
  `precio` = ese valor según el día.
- **Precio por persona** (ej. Grupal): `precio_semana`/`precio_finde` son `null` y hay **`tarifas`**
  (tramos por cantidad de personas). El precio por persona depende del tamaño del grupo:
  3–4 personas una tarifa, 5–6 otra, 7–8 otra. Pasando el último tramo, cada persona adicional
  paga `precio_persona_adicional_*`. El tope es `capacidad_maxima`.

> `precio` y `monto_sena` ya vienen **calculados** para `fecha` + `personas`. Usalos, no
> recalcules. Si no mandaste `personas`, `precio` se calcula con una cantidad de referencia
> (el mínimo del tramo más bajo), útil para mostrar un "desde $…".

### Consultar disponibilidad de un circuito en una fecha
`GET /api/v1/disponibilidad/?circuito_id=1&fecha=2026-07-11`

**200:**
```json
{
  "fecha": "2026-07-11",
  "habilitado": true,
  "circuito_id": 1,
  "circuito_nombre": "Circuito Relax",
  "turnos": [
    {
      "turno_id": 2, "turno_nombre": "Turno mañana",
      "hora_inicio": "10:00", "hora_fin": "12:00",
      "cupo_total": 4, "cupo_ocupado": 1, "cupo_disponible": 3,
      "bloqueado": false
    }
  ]
}
```
- `habilitado: false` → el negocio no atiende ese día (`turnos` vacío).
- Ofrecé al cliente solo los turnos con `cupo_disponible > 0` y `bloqueado: false`.

### Disponibilidad de un rango de fechas (varios días de una)
`GET /api/v1/disponibilidad/rango/?circuito_id=3&desde=2026-08-01&hasta=2026-08-31&personas=6`

Para cuando el cliente pregunta **"¿qué días hay este mes?"** o para **sugerir alternativas**
cuando el día que pidió está lleno. `personas` es opcional (filtra los turnos que tengan lugar
para esa cantidad). El rango máximo es **62 días**.

**200:**
```json
{
  "circuito_id": 3, "circuito_nombre": "Spa Grupal Clásico",
  "desde": "2026-08-01", "hasta": "2026-08-31",
  "dias": [
    {
      "fecha": "2026-08-01", "habilitado": true, "hay_lugar": true,
      "turnos_libres": [
        {"turno_id": 2, "turno_nombre": "Turno tarde", "hora_inicio": "15:00", "hora_fin": "19:00", "cupo_disponible": 8}
      ]
    },
    {"fecha": "2026-08-02", "habilitado": true, "hay_lugar": false, "turnos_libres": []}
  ]
}
```
Cómo lo usa el bot:
- **"¿qué días hay en agosto?"** → filtrá los `dias` con `hay_lugar: true`.
- **"el sábado 23 no hay, ¿cuándo sí?"** → consultá el rango desde esa fecha y ofrecé el primer
  día con `hay_lugar: true` (o el primero cuyo `turnos_libres` incluya el turno que quiere).
- **400** si el rango está invertido (`hasta < desde`) o supera 62 días.
- `ocupado_por_otro_circuito: true` → (solo en **modo spa exclusivo**) el turno ya está
  reservado por otro circuito, así que no hay lugar aunque sea otro servicio.
- **404** `{"error": "circuito_not_found"}`.

> **Modo spa exclusivo** (configurable, activo por defecto): cada turno admite **una sola
> reserva en todo el spa**. Si la mañana del 10/7 ya tiene una reserva de "Pareja", la
> disponibilidad de cualquier otro circuito para esa mañana viene con `cupo_disponible: 0`.
> El cupo del grupo se limita a la capacidad del circuito.

### Turnero crudo (ocupación simple, sin reglas)
`GET /api/v1/turnero/?desde=2026-08-01&dias=14`

Vista **cruda** del turnero: para cada día y cada turno, si está **ocupado** y cuántas
**personas** suma, **sin** aplicar reglas de negocio ni distinguir circuito. Es una fuente de
verdad simple para que el bot arme un calendario; toda la lógica de cupo/precio/exclusividad
vive en el CRM y **no** se expone acá. Preferí `disponibilidad` / `disponibilidad/rango` para
decidir si hay lugar — este endpoint es solo para pintar ocupación.

- `desde` opcional (default hoy), formato `YYYY-MM-DD`. `dias` opcional (default 14, máximo 62).

**200:**
```json
{
  "desde": "2026-08-01", "dias": 14,
  "turnero": [
    {
      "fecha": "2026-08-01",
      "turnos": [
        {"turno_id": 1, "turno_nombre": "Turno mañana", "hora_inicio": "10:00", "hora_fin": "14:00", "ocupado": true, "personas": 3, "reservas": 1},
        {"turno_id": 2, "turno_nombre": "Turno tarde", "hora_inicio": "15:00", "hora_fin": "19:00", "ocupado": false, "personas": 0, "reservas": 0}
      ]
    }
  ]
}
```
- **400** `{"error": "desde_invalido"}` o `{"error": "dias_invalido"}`.

---

## 5. Reservas

### Crear reserva
`POST /api/v1/reservas/`
```json
{
  "telefono": "3815551234",
  "nombre_contacto": "Ana Pérez",
  "circuito_id": 1,
  "turno_id": 2,
  "fecha": "2026-07-11",
  "cantidad_personas": 2,
  "acompanantes": ["Juan"],
  "notas": "Aniversario"
}
```
- `nombre_contacto`, `acompanantes`, `notas` son opcionales. `cantidad_personas` default 1.
- Crea el contacto si no existe. La reserva nace en estado **`pendiente_sena`** con la
  seña ya calculada y un **vencimiento** (si no se paga, el cupo se libera solo).
- **La validación de cupo es atómica**: dos reservas simultáneas para el último lugar no
  pueden sobrevender (lock a nivel base de datos).

**201:**
```json
{
  "id": 45, "contacto_nombre": "Ana Pérez", "contacto_telefono": "+5493815551234",
  "circuito_nombre": "Circuito Relax", "turno_nombre": "Turno mañana",
  "fecha": "2026-07-11", "cantidad_personas": 2, "acompanantes": ["Juan"],
  "estado": "pendiente_sena", "precio_total": "44000.00",
  "monto_sena": "22000.00", "monto_pagado": "0.00",
  "medio_pago": "", "vencimiento_sena": "2026-07-09T18:00:00Z",
  "notas": "Aniversario", "pagos": []
}
```
**422** `{"error": "sin_cupo: ..."}` (ver tabla de errores en §2).

### Crear reserva desde el bot (con medio de pago)
`POST /api/v1/reservas/bot/`

Igual que crear reserva, pero pensado para el flujo del bot: además de los datos
estructurados (que **siguen validando cupo**) lleva el **medio de pago elegido**, un
**resumen** en texto y, según el caso, el **comprobante** o el **link de pago**.

```json
{
  "telefono": "3815551234",
  "nombre_contacto": "Ana Pérez",
  "circuito_id": 1,
  "turno_id": 2,
  "fecha": "2026-07-11",
  "cantidad_personas": 2,
  "medio_pago": "transferencia",
  "resumen": "2 personas · Circuito Relax · sábado 11/07 · turno mañana",
  "comprobante_base64": "<imagen del comprobante en base64>",
  "comprobante_mimetype": "image/jpeg"
}
```

- **`medio_pago: "transferencia"`** → la reserva nace en **`pendiente_aprobacion`**. Mandá el
  comprobante en `comprobante_base64` (+ `comprobante_mimetype`, default `image/jpeg`). Una
  persona del spa lo revisa y **aprueba manualmente** desde el CRM; recién ahí se confirma y
  el CRM te avisa por el webhook `reserva-aprobada` (ver §7.5).
- **`medio_pago: "mercado_pago"`** → la reserva nace en **`pendiente_pago`**. Pasá el
  `link_pago`. Cuando MP acredita, confirmás con **`confirmar-pago`** (abajo).
- `resumen` es texto libre para que el staff vea de un vistazo lo que armó el bot.
- `cantidad_personas`, `circuito_id`, `turno_id` y `fecha` son obligatorios y **se validan
  igual que en la reserva normal** (cupo atómico, mínimos/máximos, modo exclusivo).

**201** → ReservaSerializer (incluye `origen: "whatsapp_bot"`, `estado`, `resumen`, `link_pago`).
**422** `{"error": "sin_cupo: ..."}` · **400** `{"error": "datos_invalidos"}` o `comprobante_base64_invalido`.

### Confirmar pago de Mercado Pago (por teléfono)
`POST /api/v1/reservas/confirmar-pago/`
```json
{"telefono": "3815551234"}
```
- Para el flujo automático de MP: cuando el bot detecta el pago acreditado, llama acá.
- Busca la reserva **`pendiente_pago`** más reciente de ese teléfono y la pasa a
  **`confirmado`**, disparando el webhook `reserva-aprobada` (§7.5).

**200** → ReservaSerializer con `estado: "confirmado"` ·
**404** `{"error": "reserva_pendiente_pago_no_encontrada"}` · **400** `{"error": "telefono_requerido"}`.

### Ver una reserva
`GET /api/v1/reservas/<id>/` → **200** ReservaSerializer · **404** `{"error": "reserva_not_found"}`

### Confirmar seña (registra pago y confirma)
`POST /api/v1/reservas/<id>/confirmar-sena/`
```json
{"monto": "11000.00", "medio_pago": "transferencia"}
```
- `medio_pago`: `efectivo` · `transferencia` · `mercado_pago` · `tarjeta` · `otro`.
- Pasa la reserva a **`confirmado`** y suma el pago.

**200** → ReservaSerializer con `estado: "confirmado"`.

### Reprogramar (cambiar fecha/turno)
`POST /api/v1/reservas/<id>/reprogramar/`
```json
{"fecha": "2026-07-18", "turno_id": 3}
```
- Libera el cupo viejo, valida el nuevo (mismo lock anti-sobreventa) y **conserva la seña
  ya pagada**. Preferí esto antes que cancelar + crear.

**200** → ReservaSerializer actualizado · **422** `{"error": "..."}`.

### Cancelar
`POST /api/v1/reservas/<id>/cancelar/`
```json
{"motivo": "El cliente no puede asistir"}
```
- Libera el cupo y aplica la **política de seña**: si se cancela con menos anticipación que
  la configurada (`horas_cancelacion_con_reembolso`, default 24h), la seña queda **retenida**;
  si se cancela en término, queda **reembolsable**. El resultado se refleja en el campo
  `sena_reembolsable` de la reserva y en `notas`.

**200** → ReservaSerializer con `estado: "cancelado"`.

### Historial de un contacto
`GET /api/v1/reservas/por-telefono/?telefono=3815551234`

**200** → lista de ReservaSerializer (más recientes primero). Útil para que el bot diga
"tenés un turno confirmado el 11/07" o para reconocer clientes recurrentes.

### Agenda de una fecha (para recordatorios)
`GET /api/v1/reservas/agenda/?fecha=2026-07-25&estado=confirmada`

Reservas de una fecha (por defecto **confirmadas**). Pensado para los recordatorios
automáticos: se llama con `fecha=mañana` (24hs antes) y con `fecha=hoy` (el mismo día).
Acepta `estado=confirmada` o `confirmado` indistintamente.

**200:**
```json
[
  {"telefono": "+5493815551234", "nombre": "Ana Pérez", "horario": "2026-07-25 (Turno mañana)"}
]
```
- **400** `{"error": "fecha_requerida"}` o `{"error": "fecha_invalida"}`.

### Estados de una reserva
- `pendiente_sena` — reserva normal esperando la seña.
- `pendiente_aprobacion` — transferencia con comprobante, esperando que el staff la apruebe.
- `pendiente_pago` — Mercado Pago, esperando que se acredite el pago.
- `confirmado` → `completado` · o `cancelado` · o `no_show`.

Flujo: (`pendiente_sena` | `pendiente_aprobacion` | `pendiente_pago`) → `confirmado` →
`completado`. Los cuatro primeros estados **ocupan cupo**. (`completado`/`no_show` los marca
recepción desde el turnero al cierre del día.)

---

## 6. Vouchers (gift cards)

### Validar un voucher
`GET /api/v1/vouchers/<codigo>/` (ej. `/api/v1/vouchers/SPA-2EXN-FPRW/`)

**200** (canjeable):
```json
{"valido": true, "codigo": "SPA-2EXN-FPRW", "circuito_id": 1,
 "circuito": "Circuito Relax", "monto": "22000.00", "vence": "2027-07-03"}
```
**404** (no canjeable): `{"valido": false, "motivo": "ya_canjeado"}`
(`codigo_inexistente` · `ya_canjeado` · `cancelado` · `vencido`)

### Canjear un voucher (crea reserva confirmada)
`POST /api/v1/vouchers/canjear/`
```json
{
  "codigo": "SPA-2EXN-FPRW", "telefono": "3815559999",
  "nombre_contacto": "Quien lo recibe", "turno_id": 2,
  "fecha": "2026-07-20", "cantidad_personas": 1
}
```
- El voucher ya está pago → la reserva nace **`confirmado`** (mismo lock de cupo).

**200:** `{"ok": true, "reserva_id": 51, "estado": "confirmado", "codigo": "SPA-2EXN-FPRW"}`
**422:** `{"ok": false, "error": "vencido"}` (o error de cupo/turno).

---

## 7. WhatsApp: entrada y salida

Este es el corazón del bot. El flujo es:

```
Cliente → WhatsApp → Evolution API
   → POST /whatsapp/webhook/evolution/  (el CRM guarda el mensaje)
   → el CRM reenvía a N8N_WEBHOOK_URL   (n8n decide la respuesta)
   → n8n → POST /whatsapp/api/enviar/   (el CRM manda la respuesta por Evolution)
```

### 7.1 Webhook entrante (Evolution → CRM)
`POST /whatsapp/webhook/evolution/`
- Autenticación: header **`apikey`** = *webhook token* (config en *Configuración WhatsApp*).
  En producción, sin token configurado el webhook **se rechaza** (agujero de seguridad).
- El CRM parsea el evento de Evolution, guarda el mensaje en el inbox (**deduplicado** por
  `message_id`, así un reenvío de Evolution no duplica) y **reenvía a n8n**.

### 7.2 Payload que el CRM le manda a n8n

Tu nodo Webhook en n8n recibe el payload crudo de Evolution **enriquecido** con estos campos
ya masticados:

```json
{
  "...": "campos crudos de Evolution",
  "phone": "+5493815551234",
  "message": "hola, quiero reservar",
  "contact_name": "Ana",
  "bot_n8n_activo": true,
  "conversacion_id": 87,
  "fuera_de_horario": false
}
```

| Campo | Qué hacer en n8n |
|---|---|
| `phone` | Teléfono normalizado del cliente (usalo en todas las llamadas a la API) |
| `message` | Texto del mensaje ya extraído |
| `bot_n8n_activo` | **Si es `false`, NO respondas.** La conversación está en manos de un humano (handoff). |
| `fuera_de_horario` | Si es `true`, mandá el auto-reply "estamos cerrados, te contestamos a las…" |
| `conversacion_id` | Referencia interna de la conversación |

> **Importante:** respetá `bot_n8n_activo`. Si un humano tomó la conversación desde el inbox,
> el bot debe callarse hasta que se reactive.

### 7.3 Enviar mensaje (n8n → CRM → cliente)
`POST /whatsapp/api/enviar/` (con `X-Api-Key`)
```json
{"phone": "+5493815551234", "message": "¡Hola Ana! Tenemos lugar el 11/07 a las 10hs."}
```
Para multimedia:
```json
{"phone": "+5493815551234", "media_url": "https://.../foto.jpg", "media_type": "image", "message": "Mirá el spa"}
```
- `media_type`: `image` · `video` · `audio` · `document`.

**200:** `{"ok": true, "message_id": "...", "mensaje_id": 340, "conversacion_id": 87, "contacto_id": 12}`
**502:** `{"ok": false, "error": "evolution_api_error", "detalle": "..."}` (Evolution caída).

> Mandá **siempre** por acá, nunca directo a Evolution: así el mensaje queda registrado en el
> inbox y recepción ve toda la conversación.

### 7.4 Derivar a un humano (handoff)
`POST /whatsapp/api/handoff/` (con `X-Api-Key`)
```json
{"telefono": "+5493815551234", "agente_id": null}
```
- Apaga el bot para esa conversación (`bot_activo=false`), la marca
  **"requiere atención humana"** y la asigna a un agente (si `agente_id` es null, al de
  menor carga). A partir de ahí el bot recibirá `bot_n8n_activo: false`.

**200:** `{"ok": true, "conversacion_id": 87, "estado": "requiere_atencion_humana", "agente_id": 4}`
**404:** `{"error": "conversation_not_found"}`

> Usá handoff cuando el bot no entiende, el cliente lo pide, o hay un reclamo. Además, si
> **n8n se cae** y no responde tras varios reintentos, el CRM hace el handoff automáticamente
> para que la conversación aparezca destacada en el inbox y nadie quede sin respuesta.

### 7.5 Reserva aprobada (CRM → n8n)
El CRM llama a un webhook **tuyo** cuando una reserva pasa a **`confirmado`**, para que el bot
le mande la confirmación final al cliente. Ocurre en dos casos:
- El staff **aprueba** manualmente una transferencia (`pendiente_aprobacion` → `confirmado`).
- Se confirma un pago de **Mercado Pago** vía `confirmar-pago` (`pendiente_pago` → `confirmado`).

`POST {N8N_RESERVA_APROBADA_URL}` (configurable, ej. `https://n8n.tu-dominio/webhook/reserva-aprobada`)
```json
{
  "telefono": "+5493815551234",
  "nombre": "Ana Pérez",
  "horario_confirmado": "2026-07-11 (Turno mañana)",
  "resumen": "2 personas · Circuito Relax · sábado 11/07"
}
```
- Se envía de forma asíncrona con reintentos. Si `N8N_RESERVA_APROBADA_URL` no está
  configurada, el CRM simplemente no avisa (no falla la aprobación).
- En n8n: recibí este webhook y mandá el mensaje de confirmación al cliente con
  `POST /whatsapp/api/enviar/`.

### 7.6 Estado de la conversación (flujo del bot)
El CRM es la **única fuente de verdad** del estado del flujo: el bot no guarda nada en Redis,
lo lee y actualiza acá. Cada conversación tiene una bolsa de campos del flujo.

**Crear conversación** — `POST /api/v1/conversaciones/`
```json
{"telefono": "5491122334455", "nombre": "Juana", "estado_flujo": "nuevo"}
```
Crea la conversación la primera vez que escribe un número (si ya existe, no pisa el estado).
**201** (creada) / **200** (ya existía) → el objeto de estado (abajo).

**Leer estado** — `GET /api/v1/conversaciones/<telefono>/`
```json
{
  "telefono": "+5491122334455", "nombre": "Juana",
  "estado_flujo": "turno_fecha", "personas": 4, "tipo_propuesta": "Spa de Parejas",
  "fecha_solicitada": "2026-07-25", "intentos_fecha": 1, "horario_confirmado": null,
  "datos_contacto": null, "reserva_creada": false, "override_regla": false,
  "bot_bloqueado": false, "last_message_ts": "2026-07-20T14:32:00Z"
}
```
**404** `{"error": "conversacion_no_encontrada"}` si el número no existe todavía.

**Actualizar (parcial)** — `PATCH /api/v1/conversaciones/<telefono>/`
Mandá **solo** los campos que cambian (nunca todos juntos). Campos aceptados:
`estado_flujo`, `personas`, `tipo_propuesta`, `fecha_solicitada` (puede ir `null` para
limpiarla), `intentos_fecha`, `horario_confirmado`, `datos_contacto`, `reserva_creada`,
`override_regla`, `bot_bloqueado`. `estado_flujo` posibles: `nuevo`, `menu`, `turno_personas`,
`turno_fecha`, `turno_datos_contacto`, `turno_pago`, `derivado`.
```json
{"estado_flujo": "turno_datos_contacto", "horario_confirmado": "2026-07-25 (mañana)", "intentos_fecha": 0, "fecha_solicitada": null}
```
**200** → el objeto de estado actualizado.

> **Bloqueo automático:** cuando `estado_flujo` pasa a `"derivado"` **o** `reserva_creada`
> pasa a `true`, el CRM pone `bot_bloqueado: true` (apaga el bot). Mientras esté bloqueado, el
> bot no debe responder — solo guardar los mensajes (abajo). En el CRM, el staff lo reactiva
> con el botón **"Prender bot"** en el inbox (o el bot puede mandar `{"bot_bloqueado": false}`).

**Guardar un mensaje sin responder** — `POST /api/v1/conversaciones/<telefono>/mensajes/`
```json
{"texto": "hola, sigo interesada", "de": "cliente"}
```
Con el bot bloqueado, igual guardá el mensaje entrante para que el staff lo vea en el inbox.
`de`: `cliente` (entrante) u otro valor (saliente). **201** `{"ok": true, "mensaje_id": ..., "conversacion_id": ...}`.

**Conversaciones para seguimiento** — `GET /api/v1/conversaciones/?inactiva_desde_horas=72&reserva_creada=false&estado_flujo_distinto_de=derivado`
1 vez por día: "¿qué conversaciones llevan 72hs sin respuesta, sin reserva y sin haber pasado
a un asesor?". Todos los filtros son opcionales.
**200** → `[{"telefono": "...", "nombre_contacto": "..."}]`.

---

## 8. Flujo recomendado de reserva (en n8n)

1. Llega mensaje → nodo Webhook. Chequear `bot_n8n_activo` (si false, cortar) y
   `fuera_de_horario` (si true, auto-reply).
   - Leé el estado del flujo: `GET /conversaciones/<telefono>/` (o `POST /conversaciones/`
     si es la primera vez). Si `bot_bloqueado: true`, guardá el mensaje con
     `POST /conversaciones/<telefono>/mensajes/` y no respondas.
2. Interpretar la intención (NLU / prompt). Guardá el avance con `PATCH /conversaciones/<telefono>/`.
3. Ofrecer circuitos: `GET /circuitos/?fecha=...` → mostrar `precio` y `monto_sena`.
4. Ver horarios: `GET /disponibilidad/?circuito_id=&fecha=` → ofrecer turnos con cupo.
5. Crear reserva con el medio de pago: `POST /reservas/bot/`.
   - **Transferencia** → mandá `comprobante_base64`; queda `pendiente_aprobacion`. El staff la
     aprueba en el CRM y te llega el webhook `reserva-aprobada` (§7.5) → confirmás al cliente.
   - **Mercado Pago** → pasá `link_pago`; queda `pendiente_pago`. Cuando MP acredita, llamás a
     `POST /reservas/confirmar-pago/` con el teléfono → se confirma y llega el webhook.
6. Si el cliente quiere cambiar: `POST /reservas/<id>/reprogramar/`.
7. Si no entendés o es un reclamo: `POST /whatsapp/api/handoff/`.

> Para reservas cargadas por recepción (no por el bot) se sigue usando `POST /reservas/` +
> `confirmar-sena/`. El flujo del bot con medio de pago es `/reservas/bot/`.

---

## 9. Resumen de endpoints

| Método | Endpoint | Auth | Para qué |
|---|---|---|---|
| GET | `/api/v1/contactos/buscar/` | X-Api-Key | Buscar cliente por teléfono |
| POST | `/api/v1/contactos/` | X-Api-Key | Crear/completar cliente |
| GET | `/api/v1/circuitos/` | X-Api-Key | Circuitos con precio+seña por fecha |
| GET | `/api/v1/disponibilidad/` | X-Api-Key | Cupo por turno de un circuito/fecha |
| GET | `/api/v1/disponibilidad/rango/` | X-Api-Key | Días con lugar en un rango (mes / alternativas) |
| GET | `/api/v1/turnero/` | X-Api-Key | Ocupación cruda por (fecha, turno), sin reglas |
| POST | `/api/v1/reservas/` | X-Api-Key | Crear reserva (recepción) |
| POST | `/api/v1/reservas/bot/` | X-Api-Key | Crear reserva del bot (con medio de pago) |
| POST | `/api/v1/reservas/confirmar-pago/` | X-Api-Key | Confirmar pago MP por teléfono |
| GET | `/api/v1/reservas/agenda/` | X-Api-Key | Reservas confirmadas de una fecha (recordatorios) |
| GET | `/api/v1/reservas/<id>/` | X-Api-Key | Ver reserva |
| POST | `/api/v1/reservas/<id>/confirmar-sena/` | X-Api-Key | Registrar seña y confirmar |
| POST | `/api/v1/reservas/<id>/reprogramar/` | X-Api-Key | Cambiar fecha/turno |
| POST | `/api/v1/reservas/<id>/cancelar/` | X-Api-Key | Cancelar (con política de seña) |
| GET | `/api/v1/reservas/por-telefono/` | X-Api-Key | Historial del cliente |
| POST | `/api/v1/conversaciones/` | X-Api-Key | Crear conversación |
| GET | `/api/v1/conversaciones/` | X-Api-Key | Conversaciones para seguimiento |
| GET | `/api/v1/conversaciones/<telefono>/` | X-Api-Key | Leer estado del flujo del bot |
| PATCH | `/api/v1/conversaciones/<telefono>/` | X-Api-Key | Actualizar estado del flujo (parcial) |
| POST | `/api/v1/conversaciones/<telefono>/mensajes/` | X-Api-Key | Guardar mensaje con el bot bloqueado |
| GET | `/api/v1/vouchers/<codigo>/` | X-Api-Key | Validar gift card |
| POST | `/api/v1/vouchers/canjear/` | X-Api-Key | Canjear gift card |
| POST | `/whatsapp/api/enviar/` | X-Api-Key | Enviar mensaje al cliente |
| POST | `/whatsapp/api/handoff/` | X-Api-Key | Derivar a humano |
| POST | `/whatsapp/webhook/evolution/` | webhook token | Entrada de mensajes (Evolution) |
| POST | `{N8N_RESERVA_APROBADA_URL}` | (webhook n8n) | **CRM → n8n**: reserva confirmada, avisar al cliente |

> **Variable de entorno nueva:** `N8N_RESERVA_APROBADA_URL` — la URL del webhook de n8n que el
> CRM llama al confirmar una reserva (§7.5). Configurala en el `.env` del backend.
