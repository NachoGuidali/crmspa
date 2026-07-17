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
- `ocupado_por_otro_circuito: true` → (solo en **modo spa exclusivo**) el turno ya está
  reservado por otro circuito, así que no hay lugar aunque sea otro servicio.
- **404** `{"error": "circuito_not_found"}`.

> **Modo spa exclusivo** (configurable, activo por defecto): cada turno admite **una sola
> reserva en todo el spa**. Si la mañana del 10/7 ya tiene una reserva de "Pareja", la
> disponibilidad de cualquier otro circuito para esa mañana viene con `cupo_disponible: 0`.
> El cupo del grupo se limita a la capacidad del circuito.

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

### Estados de una reserva
`pendiente_sena` → `confirmado` → `completado` · o `cancelado` · o `no_show`.
(`completado`/`no_show` los marca recepción desde el turnero al cierre del día.)

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

---

## 8. Flujo recomendado de reserva (en n8n)

1. Llega mensaje → nodo Webhook. Chequear `bot_n8n_activo` (si false, cortar) y
   `fuera_de_horario` (si true, auto-reply).
2. Interpretar la intención (NLU / prompt).
3. Ofrecer circuitos: `GET /circuitos/?fecha=...` → mostrar `precio` y `monto_sena`.
4. Ver horarios: `GET /disponibilidad/?circuito_id=&fecha=` → ofrecer turnos con cupo.
5. Crear reserva: `POST /reservas/` → responder con seña y datos de pago.
6. Cuando el cliente paga: `POST /reservas/<id>/confirmar-sena/`.
7. Si el cliente quiere cambiar: `POST /reservas/<id>/reprogramar/`.
8. Si no entendés o es un reclamo: `POST /whatsapp/api/handoff/`.

---

## 9. Resumen de endpoints

| Método | Endpoint | Auth | Para qué |
|---|---|---|---|
| GET | `/api/v1/contactos/buscar/` | X-Api-Key | Buscar cliente por teléfono |
| POST | `/api/v1/contactos/` | X-Api-Key | Crear/completar cliente |
| GET | `/api/v1/circuitos/` | X-Api-Key | Circuitos con precio+seña por fecha |
| GET | `/api/v1/disponibilidad/` | X-Api-Key | Cupo por turno de un circuito/fecha |
| POST | `/api/v1/reservas/` | X-Api-Key | Crear reserva |
| GET | `/api/v1/reservas/<id>/` | X-Api-Key | Ver reserva |
| POST | `/api/v1/reservas/<id>/confirmar-sena/` | X-Api-Key | Registrar seña y confirmar |
| POST | `/api/v1/reservas/<id>/reprogramar/` | X-Api-Key | Cambiar fecha/turno |
| POST | `/api/v1/reservas/<id>/cancelar/` | X-Api-Key | Cancelar (con política de seña) |
| GET | `/api/v1/reservas/por-telefono/` | X-Api-Key | Historial del cliente |
| GET | `/api/v1/vouchers/<codigo>/` | X-Api-Key | Validar gift card |
| POST | `/api/v1/vouchers/canjear/` | X-Api-Key | Canjear gift card |
| POST | `/whatsapp/api/enviar/` | X-Api-Key | Enviar mensaje al cliente |
| POST | `/whatsapp/api/handoff/` | X-Api-Key | Derivar a humano |
| POST | `/whatsapp/webhook/evolution/` | webhook token | Entrada de mensajes (Evolution) |
