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
- **Precio** según día: `precio_semana` (lun-vie) o `precio_finde` (sáb-dom). Un **feriado**
  puede marcarse como *"abre con tarifa de fin de semana"* (ese día se atiende y cobra
  `precio_finde`) o *"cerrado"* (no se atiende). También hay feriados recurrentes anuales.
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

### Política de cancelación

`cancelar_reserva` mira `horas_cancelacion_con_reembolso` (config, default 24h):
- Cancelación **en término** → `sena_reembolsable = true`.
- Cancelación **tardía** → `sena_reembolsable = false` (seña retenida).
El resultado queda en el campo `sena_reembolsable` y en `notas`.

### Vencimiento de seña

Una reserva `pendiente_sena` tiene `vencimiento_sena`. Si vence sin pagar, la automatización
`reclamo_sena` la cancela y **libera el cupo** para que otro pueda tomarlo.

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
