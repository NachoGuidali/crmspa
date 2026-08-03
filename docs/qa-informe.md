# Informe de QA y revisión técnica — CRM Spa Cuatro Estaciones

**Fecha:** 2026-07-27 · **Revisor:** QA/Django senior · **Estado del proyecto:** desarrollo (VPS, pre-producción)
**Stack:** Django 5.1 · DRF · Postgres · Celery + Redis · Pillow · WhiteNoise · Docker Compose
**Integraciones:** Meta WhatsApp Cloud API + Evolution API (dispatcher por proveedor) · bot n8n vía API REST con `X-Api-Key`

> Alcance: mapeo del sistema, revisión de código/arquitectura y análisis de los flujos críticos
> (reservas, WhatsApp, integración n8n, seguridad). **No se aplicaron fixes** salvo triviales;
> el resto está propuesto para tu confirmación.

---

## 1. Resumen ejecutivo

El CRM está **bien estructurado y más maduro que un MVP**: apps por dominio, settings dev/prod
separados, secretos fuera del repo (`.env` ignorado, `.env.example` con placeholders), validación de
cupo **atómica** con advisory locks (anti-sobreventa correcto), webhooks con verificación de firma, y
una capa de proveedor (Evolution/Meta) desacoplada. La integración con n8n usa auth por API key con
logging de cada request. La lógica de negocio (precios por día, seña, ventana de 24 hs, plantillas)
vive en el backend, como corresponde.

**Lo que falta para producción** se concentra en 3 frentes:
1. **Cero tests automatizados** — el mayor riesgo de regresión dado todo lo que se movió.
2. **Un par de gaps de seguridad/abuso** — webhook de Meta sin firma obligatoria y endpoint público de
   reservas sin protección.
3. **Correcciones de robustez** — `date.today()` con contenedor en UTC (día equivocado cerca de
   medianoche) e idempotencia en la creación de reservas del bot.

Ninguno es "crítico" en el sentido de RCE/leak de secretos, pero varios son **Altos** y hay que
cerrarlos antes de abrir a producción real.

**Veredicto:** apto para seguir en desarrollo/piloto; **no** apto para producción abierta hasta cerrar
los ítems Alto y montar una base mínima de tests.

---

## 2. Bugs y defectos (por severidad)

### 🔴 ALTO

**A1 — Webhook de Meta acepta requests SIN firma si `meta_app_secret` está vacío**
`apps/whatsapp/views.py` · `MetaWebhookView.post` (~línea 69)
```python
if app_secret and not webhook_meta.verify_signature(...):
    return HttpResponse('Forbidden', status=403)
```
Si `meta_app_secret` no está configurado, la condición es falsa y **se procesa el payload sin validar**.
Un atacante que conozca la URL (`/whatsapp/webhook/meta/`) podría **inyectar mensajes entrantes falsos**
(crear contactos, disparar el bot, ensuciar el inbox). El webhook de Evolution sí rechaza en producción
cuando no hay token — Meta quedó asimétrico.
- **Repro:** con `meta_app_secret` vacío, `POST /whatsapp/webhook/meta/` con un payload de mensaje válido → se guarda.
- **Fix propuesto:** rechazar (403) si `app_secret` no está configurado y `DEBUG=False` (igual que
  `webhook.verify_webhook_token`). Nunca procesar Meta sin firma en producción.

**A2 — Endpoint público de reservas sin auth, throttle ni captcha**
`apps/sitio_publico/views.py` · `reservar()` (POST) → `services.crear_reserva(...)`
Ruta pública `POST /sitio/reservar/<circuito_id>/`. Cualquiera puede crear reservas reales. Como las
reservas **ocupan cupo**, permite **spam y agotamiento de disponibilidad** (DoS sobre la agenda: llenar
todos los turnos con reservas falsas). No es DRF, así que **el throttle global no aplica**.
- **Repro:** `curl -X POST .../sitio/reservar/1/ -d "telefono=...&turno_id=...&fecha=..."` en loop.
- **Fix propuesto:** (a) si la página no se usa (el sitio real es el estático + bot), **deshabilitar la
  ruta**; o (b) throttle por IP + captcha + estado inicial `pendiente_sena` con vencimiento corto; y
  además capturar `KeyError/ValueError` (ver A3).

**A3 — Sin tests automatizados (0 archivos de test)**
No hay `tests.py`/`test_*.py` en ninguna app. Con la cantidad de lógica sensible (cupo, ventana 24 hs,
estados de reserva, dispatcher de proveedor, dedup de webhooks) el riesgo de romper algo sin darse
cuenta es alto.
- **Fix propuesto:** suite mínima con pytest-django cubriendo: cupo/exclusividad y anti-sobreventa,
  estados de reserva y confirmación, parser + firma de ambos webhooks, ventana 24 hs + plantillas,
  dedup de entrantes, y los endpoints de n8n (auth, payloads malformados).

### 🟠 MEDIO

**M1 — `date.today()` en vez de `timezone.localdate()` (día equivocado en UTC)**
`apps/dashboard/views.py:41,47,59` · `apps/turnero/views_ui.py:29,94,114` · `apps/turnero/views.py:42`
· `apps/circuitos/views.py:20` · `apps/sitio_publico/views.py:11`
El contenedor corre en **UTC** (el Dockerfile no setea TZ) y `date.today()` usa la hora del SO, no la
`TIME_ZONE` de Django. Entre ~21:00 y 24:00 de Argentina (00:00–03:00 UTC) el "hoy" salta al día
siguiente: la **agenda del día, el default de disponibilidad y el "es_hoy" del dashboard** muestran la
fecha equivocada.
- **Fix propuesto (bajo riesgo):** reemplazar `date.today()` → `timezone.localdate()` en esas vistas.
  (El core de reservas ya usa `timezone.localdate()`, así que es consistencia.)

**M2 — Sin idempotencia en la creación de reservas del bot**
`apps/reservas/views.py` · `ReservaBotCrearView` / `services.crear_reserva`
Si n8n reintenta `POST /reservas/bot/` (timeout, retry), se crea una **reserva duplicada**. En modo
exclusivo el lock evita la segunda (1 por turno), pero en modo por-circuito no. No hay clave idempotente.
- **Fix propuesto:** aceptar un header/campo `idempotency_key` (o `external_id` del bot) y hacer
  `get_or_create`; o dedup por (contacto, fecha, turno, circuito) en una ventana corta.

**M3 — `reservar()` público no maneja inputs faltantes → 500**
`apps/sitio_publico/views.py` · usa `request.POST['telefono']`, `['turno_id']`, `['fecha']` dentro de un
`try` que **solo** captura `ReservaError`. Un POST sin esos campos lanza `KeyError`/`ValueError` → 500.
- **Fix propuesto:** validar/parsing con manejo de error (o un Form) y devolver 400 con mensaje.

**M4 — `comprobante_base64` sin límite de tamaño**
`apps/reservas/views.py` · `ReservaBotCrearView` decodifica el base64 sin cap. Un payload enorme puede
inflar memoria. Mitigado porque está detrás de `X-Api-Key`, pero conviene un límite (p. ej. 8–10 MB),
como ya tiene `enviar_media` (16 MB).

**M5 — Race en el contador `ApiKey.total_usos`**
`apps/integraciones/authentication.py`
```python
ApiKey.objects.filter(pk=...).update(total_usos=api_key.total_usos + 1)
```
Read-then-write: bajo requests concurrentes subcuenta. Es solo un contador, pero el fix es trivial:
`total_usos=F('total_usos') + 1`.

### 🟡 BAJO

- **B1 — API key en texto plano.** `ApiKey.key` es un UUID guardado sin hashear; si se filtra la DB, se
  filtran las keys. Aceptable para uso interno; ideal hashear (o al menos rotar fácil, que ya se puede).
- **B2 — `WebhookLog` / `LogEnvioWhatsApp` sin rotación.** Se escribe una fila por request/mensaje; sin
  limpieza la tabla crece indefinidamente. Sumar un comando/cron de retención (p. ej. 90 días).
- **B3 — `request.body` en `finalize_response`** puede venir consumido tras el parse de DRF (queda `''`
  por el `try/except`), así que a veces el log no captura el body. Menor.

---

## 3. Riesgos de seguridad (resumen)

| # | Riesgo | Sev | Estado |
|---|---|---|---|
| A1 | Webhook Meta sin firma obligatoria si falta `app_secret` | Alto | **Abrir fix** |
| A2 | Reservas públicas sin auth/throttle/captcha (spam/DoS de cupo) | Alto | **Abrir fix** |
| M4 | `comprobante_base64` sin límite de tamaño | Medio | Proponer |
| B1 | API key sin hashear | Bajo | Opcional |
| — | SSL/HTTPS del CRM | — | Verificar certbot en nginx (mencionado antes) |

**Lo que está bien:** `SECRET_KEY` protegida en prod (falla si es la de dev), `DEBUG=False` en prod,
`.env` fuera del repo, cookies `Secure` + HSTS + `SECURE_PROXY_SSL_HEADER`, auth por API key en todos los
endpoints de n8n, `/media/` servido con `login_required`, verificación de firma del webhook Evolution y
del handshake GET de Meta, y CSRF no aplica a los APIView (sin SessionAuth) — correcto.

---

## 4. Mejoras de UX para el dueño del spa

- **Agenda con navegación por día** y respetando la zona horaria (ver M1) — hoy el default puede
  mostrar el día equivocado de noche.
- **Aviso de ventana de 24 hs por conversación en el inbox** (ya implementado para Meta) — extenderlo a
  un indicador claro de "podés/no podés escribir libre".
- **Creación de usuarios con contraseña** — ya corregido en esta ronda.
- **Confirmación visual al aprobar transferencias** y al enviar plantillas — ya hay mensajes; sumar
  estado visible de la plantilla (PENDING/APPROVED) en el listado (ya está la columna).
- **Vista de "archivos del contacto"** — ya existe; sumar filtro por tipo (foto/audio/doc) sería útil.
- **Feedback de errores de envío** — ahora el inbox/n8n ya muestran el motivo real de Meta (mejorado en
  esta ronda).

---

## 5. Mejoras técnicas / arquitectura

- **Tests + CI:** pytest-django con fixtures/factories; correr en CI antes de cada deploy. Es lo #1.
- **Idempotencia:** clave idempotente en reservas del bot (M2) y, en general, en operaciones que n8n
  puede reintentar.
- **Helper de fecha local:** un único `hoy_local()` = `timezone.localdate()` y prohibir `date.today()`
  (regla de lint) para no repetir M1.
- **Rate limiting en vistas no-DRF** (las de `sitio_publico`) — el throttle de DRF no las cubre.
- **Retención de logs** (`WebhookLog`, `LogEnvioWhatsApp`, `django_celery_results`): comando de limpieza
  programado con Celery beat.
- **Observabilidad:** alertas cuando el `forward_to_n8n` agota reintentos, cuando Meta devuelve errores
  recurrentes, o cuando Celery/worker está caído. Hoy queda en logs, sin alerta.
- **Backups de Postgres** automatizados (no vi nada) — imprescindible para producción.
- **TZ del contenedor:** setear `TZ=America/Argentina/Buenos_Aires` en el compose/Dockerfile ayuda a que
  logs y `date.today()` residuales sean coherentes (además del fix M1).

---

## 6. Checklist para "apto para producción"

**Bloqueantes (Alto):**
- [ ] A1 — Webhook Meta: exigir firma en producción (rechazar si falta `app_secret`).
- [ ] A2 — Reservas públicas: proteger (throttle+captcha) o deshabilitar la ruta si no se usa.
- [ ] A3 — Suite de tests mínima (cupo, webhooks, reservas, plantillas, endpoints n8n).

**Importantes (Medio):**
- [ ] M1 — `date.today()` → `timezone.localdate()` (+ `TZ` en el contenedor).
- [ ] M2 — Idempotencia en `/reservas/bot/`.
- [ ] M3 — Manejo de inputs faltantes en `reservar()` público (evitar 500).
- [ ] M4 — Límite de tamaño en `comprobante_base64`.
- [ ] M5 — `F('total_usos') + 1`.

**Infra / operación:**
- [ ] HTTPS con certificado válido en nginx (certbot) para `crm.spacuatroestaciones.com`.
- [ ] Backups automáticos de Postgres + prueba de restore.
- [ ] Retención/rotación de logs (WebhookLog, LogEnvioWhatsApp, celery results).
- [ ] Monitoreo/alertas (Celery vivo, errores de Meta, reintentos agotados).
- [ ] Confirmar `DEBUG=False`, `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS` reales en el `.env` de prod (ok en código).

**Ya resuelto en esta ronda:**
- [x] Contraseña al crear usuarios (para dar acceso a revisores).
- [x] Error real de Meta expuesto (en vez de "400 Bad Request").
- [x] Dedup de mensajes entrantes en `/conversaciones/<tel>/mensajes/`.
- [x] Rechazo de envío sin texto ni media (`mensaje_vacio`).

---

## Anexo — Mapa del sistema (Fase 1)

- **apps:** `contactos`, `circuitos`, `turnero`, `reservas`, `whatsapp`, `automations`, `integraciones`,
  `configuracion`, `dashboard`, `sitio_publico`, `campanas`, `vouchers`, `tareas`, `usuarios`.
- **WhatsApp:** credenciales en `ConfiguracionWhatsApp` (DB, singleton) con fallback a settings/env;
  `sender.py` = dispatcher → `sender_evolution.py` / `sender_meta.py`; webhooks entrantes en
  `/whatsapp/webhook/evolution/` (header `apikey`) y `/whatsapp/webhook/meta/` (GET challenge + POST
  firma `X-Hub-Signature-256`).
- **n8n ↔ CRM:** API REST bajo `/api/v1/...` y `/whatsapp/api/...`, auth `X-Api-Key`
  (`ApiKeyAuthentication` + `HasApiKey`), cada request logueada en `WebhookLog`. Contrato en
  `docs/api-n8n.md`; flujo de reservas en `docs/flujo-bot-reservas.md`.
- **Reservas:** `services.crear_reserva` con `pg_advisory_xact_lock` por slot (anti-sobreventa),
  `Reserva.clean()` valida mín/máx y exclusividad; estados y ocupación de cupo bien modelados.
