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
- **Cancelación:** la seña se reembolsa **solo si se cancela dentro de las 24 hs posteriores
  al pago** (no a la fecha del turno). Pasado ese plazo queda **retenida**. Antes de apretar
  "Cancelar", la ficha de la reserva te dice si corresponde reembolso y hasta cuándo.
- **No-show:** la seña queda retenida.

Todo esto es automático. El plazo se cambia en *Configuración → Configuración del negocio* →
**Horas de reembolso desde el pago**.

### Precios según el día

- **Días de semana** y **fin de semana** tienen su propio precio por circuito. Qué días cuentan
  como "finde" se configura (en este spa: viernes, sábado y domingo).
- **Feriados: se cobra el precio del día + un recargo.** El feriado **no** cambia la tarifa,
  le suma un porcentaje encima:

  | Si el feriado cae… | Se cobra |
  |---|---|
  | Un sábado | precio de fin de semana **+ 10%** |
  | Un miércoles | precio de semana **+ 10%** |

  Ese 10% se cambia en *Configuración → Configuración del negocio* → **Recargo por feriado (%)**.

### Los dos números de plata del dashboard

No son lo mismo y conviene no confundirlos:

| Tarjeta | Qué mide |
|---|---|
| **Plata que entró** | Lo cobrado **en el período**, sin importar para qué fecha es el turno. Es lo que entró a la caja. |
| **Turnos del período** | El valor de las reservas **de esas fechas**, esté cobrado o no, con cuánto falta cobrar. |

Como la seña se cobra con meses de anticipación, casi nunca coinciden: cobrás en septiembre
una reserva de octubre. La primera te dice cuánta plata movió el mes; la segunda, cuánto vale
lo que se presta en esas fechas.

**Caja del día** (`Dashboard → Caja del día`) es el detalle de "plata que entró" de un día
puntual, abierto por medio de pago. Es lo que se usa para el cierre.

### Verificar transferencias

Cuando un cliente paga por transferencia, la reserva queda en **pendiente de aprobación** hasta
que alguien mire el comprobante. Mientras tanto el cliente está esperando y el cupo está tomado.

**Dónde aparece el aviso:** arriba de todo en el **Dashboard** y en el **Turnero de hoy**, con
cuántas hay, quiénes son y cuánto pagaron. Se toca y te lleva a las reservas. Desaparece solo
cuando no queda ninguna.

**El comprobante se ve en la ficha de la reserva**, sin ir a la conversación: entrás desde el
aviso o desde el tablero, y la imagen está ahí con el botón *Aprobar y confirmar* al lado.

Si el aviso dice **"sin comprobante"**, esa imagen no llegó con la reserva y hay que buscarla en
el chat del cliente, en el Inbox.

También llega un mail por cada reserva nueva del bot, a los destinatarios de *Configuración →
Configuración del negocio → Email de notificaciones*. Si ese campo está vacío no se manda nada.

### Cuándo contesta el bot y cuándo no

El bot deja de contestar en dos situaciones, y se vuelve a prender distinto en cada una:

| Por qué se apagó | Se prende solo cuando… | Botón "Prender bot" |
|---|---|---|
| Creó la reserva y espera que verifiques la transferencia | **Confirmás la reserva** | también sirve |
| Se derivó a una persona (queja, cancelación, pidió hablar con alguien, o no entendió 3 veces seguidas el mismo paso) | **Nunca solo** | es la única forma |

O sea: si la conversación está derivada, confirmar la reserva **no** vuelve a prender el bot.
Es a propósito — si alguien se quejó o pidió cancelar, hay una persona ocupándose y el bot no
tiene que meterse. Ahí lo prendés vos desde la conversación cuando el tema esté cerrado.

Al prenderlo, la conversación arranca de cero: el bot se olvida de la reserva que estaba
armando, pero **se acuerda del nombre, teléfono y email** del cliente.

### Cuando confirmás una reserva, el cliente recibe un WhatsApp

Apenas la reserva pasa a **confirmada**, el CRM le manda solo al cliente la confirmación con
los datos, cómo llegar y qué traer. Pasa por los tres caminos:

- Aprobás el comprobante de transferencia desde la ficha de la reserva.
- Mercado Pago acredita el pago (cuando lo usen).
- Cobrás la seña a mano desde la ficha del contacto.

Si tocás "Aprobar" dos veces, **el mensaje sale una sola vez**.

**El texto se edita** en *Configuración → Plantillas* → "Confirmación de reserva". Los datos
que cambian (nombre, circuito, fecha, turno, personas) se completan solos con `{{variables}}`;
no las borres.

**La dirección, el mapa, las referencias para llegar y el link a las políticas** no se escriben
dentro del mensaje: salen de *Configuración → Configuración del negocio*. Se cargan una vez y
los reusan también los recordatorios, así que si algo cambia lo tocás en un solo lugar.

### Cargar los feriados

En *Configuración → Feriados*, por cada fecha:

| Campo | Para qué |
|---|---|
| **Fecha** y **Descripción** | Ej. 9 de julio — "Día de la Independencia". |
| **Modo** | *Abre con recargo* (se atiende y se cobra el plus) o *Cerrado* (no se atiende ese día). |
| **Recargo propio (%)** | Dejalo **vacío** y usa el 10% general. Completalo solo si ese feriado cobra distinto (ej. 31 de diciembre al 50%). |
| **Recurrente anual** | Tildalo para los que caen siempre el mismo día (25 de Mayo, Navidad). Se repiten solos todos los años, no hay que volver a cargarlos. |

En la lista, la columna **Recargo** te muestra qué está cobrando cada uno: `10% (general)` o
`50% (propio)`. En el **calendario del turnero** los feriados aparecen marcados con su recargo.

El bot toma todo esto solo: al ofrecer una fecha feriada avisa el recargo, y cotiza con el
precio ya recargado. No hay que avisarle nada aparte.

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
- **Popups de la web** (`Configuración → Popups de la web`): el cartel que aparece sobre
  spacuatroestaciones.com para anunciar una promo o una fecha especial. Ver abajo.

### Popups de la web (promos y fechas especiales)

Sirve para avisar algo en la web sin depender de nadie: *"Promo Día de la Madre"*,
*"Cerrado del 24 al 26"*, *"Últimos lugares para San Valentín"*.

**Cómo se carga:** `Configuración → Popups de la web → Nuevo`.

| Campo | Para qué |
|---|---|
| **Título** | El renglón grande del cartel. |
| **Mensaje** | El texto de abajo. Podés dejarlo vacío si la foto ya lo dice todo. |
| **Imagen** | El flyer o la foto de la promo. Va arriba de todo. Opcional. |
| **Texto / Link del botón** | El botón naranja. Ej. "Reservar por WhatsApp" + el link de WhatsApp del spa. Van los dos o ninguno. |
| **Activo** | La llave maestra. Apagado, no se muestra aunque esté en fecha. |
| **Mostrar desde / hasta** | Dejalo vacío para que se muestre ya y sin fecha de fin. Si las cargás, el cartel **arranca y termina solo**: podés dejar la promo del Día de la Madre lista en septiembre. |
| **Repetir cada (horas)** | Si alguien lo cierra, cuánto esperar antes de volver a mostrárselo. 24 está bien. `0` = en cada visita (molesto). |
| **Orden** | Solo importa si tenés varios prendidos a la vez: se muestra el de **menor** orden. |

**Cosas para tener en cuenta:**

- Los cambios se ven **al instante**: no hay que avisarle a nadie ni volver a publicar la web.
- La columna **Estado** de la lista te dice qué está pasando con cada cartel: `EN VIVO`,
  `Apagado`, `Programado (12/10 09:00)` o `Vencido (20/10 23:59)`.
- Si **editás** un cartel que ya estaba dando vueltas, les vuelve a aparecer también a quienes
  ya lo habían cerrado (es una novedad nueva).
- Para **bajarlo ya**, destildá *Activo*. No hace falta borrarlo: te queda guardado para el
  año que viene.
- La **imagen es pública**: la ve cualquiera que entre a la web. No subas nada privado ahí.
- Aparece en la home y en las tres páginas de circuitos. **No** aparece en las páginas de
  políticas, términos y privacidad, a propósito: quien está leyendo eso no quiere una promo.

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
