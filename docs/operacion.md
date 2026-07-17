# Guía de operación diaria

Para el **dueño** y el equipo de **recepción**. Cómo usar el CRM en el día a día.
No hace falta saber nada técnico.

---

## Roles

- **Dueño:** ve todo, incluida la facturación (dashboard), el panel de salud y la
  configuración del negocio.
- **Recepción:** trabaja con el inbox, el turnero, las reservas, los contactos y las tareas.
  No ve la facturación ni la configuración.

---

## El día típico

### 1. Empezar el día — el Turnero
`Turnero` (calendario). Hacé clic en un día para ver todos los turnos y quién viene.

- Cada turno muestra el **cupo** (ocupado / total) y las reservas.
- Colores: verde = hay lugar · amarillo = último lugar · rojo = completo · gris = bloqueado.

### 2. Atender WhatsApp — el Inbox
`Inbox WhatsApp` (estilo WhatsApp Web: conversaciones a la izquierda, chat a la derecha).

- El **bot responde solo** las consultas comunes (vía n8n).
- Si querés **tomar una conversación**, entrá y respondé: el bot se calla hasta que lo
  reactives (*handoff*).
- **Respuestas rápidas:** botones con textos predefinidos (precios, ubicación, etc.). Se
  editan en *Configuración → Respuestas rápidas*.
- Las conversaciones marcadas **"requiere atención humana"** son las que el bot te derivó
  (o que quedaron sin responder porque n8n se cayó). Atendelas primero.

### 3. Gestionar reservas
`Reservas` (tablero por estado). Arrastrá una tarjeta para cambiar el estado, o entrá al
detalle para:

- **Reprogramar** (cambiar fecha/turno; conserva la seña).
- **Cancelar** (aplica la política de seña automáticamente).

### 4. Cerrar el día — Asistió / No vino
Al final del día, en el `Turnero` del día, marcá cada reserva:

- **Asistió** → queda como completada y (si está activada) recibe la encuesta.
- **No vino** → queda como no-show y la seña queda **retenida**.

> Esto es importante: si no cerrás el día, esas reservas quedan "sin cerrar" (te lo recuerda
> el panel de salud) y no se envían encuestas.

---

## Reservas: cómo funciona la plata

- Al reservar, se calcula la **seña** (según circuito y día). La reserva queda
  **pendiente de seña** con un vencimiento.
- Si el cliente **no paga la seña a tiempo**, el sistema **libera el cupo** solo.
- Al **confirmar la seña**, la reserva pasa a **confirmada**.
- **Cancelación:** si el cliente cancela con la anticipación configurada (por defecto 24h),
  la seña es **reembolsable**; si cancela tarde, queda **retenida**.
- **No-show:** la seña queda retenida.

Todo esto es automático. La ventana de cancelación se cambia en
*Configuración → Configuración del negocio*.

---

## Lista de espera

Si un turno está completo, anotá al cliente en la **lista de espera**
(`Reservas → Lista de espera`). Cuando se libera un lugar, el sistema le avisa **al primero
de la fila** por WhatsApp y le da unas horas para confirmar antes de pasar al siguiente.

---

## Marketing

- **Campañas** (`Campañas`): mandá un mensaje de WhatsApp a un **segmento** de clientes
  (por etiqueta, por inactividad, por circuito) o a una lista manual. Podés enviarla al
  momento o programarla.
- **Vouchers / Gift cards** (`Vouchers`): vendé un circuito para regalar. Genera un código
  `SPA-XXXX-XXXX`. Cuando lo canjean (por el bot o a mano), crea una reserva ya confirmada.

---

## Tareas internas
`Tareas`: pendientes del equipo (llamar a un cliente, etc.), con responsable y fecha. Se
marcan como completadas y las vencidas se resaltan.

---

## Para el dueño

- **Dashboard:** ingresos del período, señas pendientes, ocupación por circuito, clientes
  nuevos vs recurrentes, circuito más vendido, horarios pico.
- **Salud del sistema** (`Dashboard → Salud del sistema`): un vistazo para saber si todo
  está funcionando. Si "Automatizaciones / Celery" aparece en **rojo**, el sistema puede
  estar sin enviar recordatorios ni procesar el bot → avisá al técnico.
- **Configuración:** circuitos, turnos, feriados, bloqueos, plantillas de mensajes,
  respuestas rápidas, datos del negocio, automatizaciones.

---

## Preguntas frecuentes

**¿Dos clientes pueden quedarse con el mismo último lugar?**
No. El sistema bloquea el cupo a nivel base de datos: solo uno entra, el otro recibe
"sin cupo".

**¿Qué pasa si el bot no entiende?**
Deriva la conversación a una persona (aparece en el inbox como "requiere atención humana").

**¿Y si se cae internet / n8n?**
Los mensajes igual quedan guardados en el inbox y la conversación se marca para atención
humana, así nadie queda sin respuesta.

**¿Recepción puede ver cuánto factura el spa?**
No. El dashboard de facturación es solo para el dueño.
