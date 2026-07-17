# CRM Spa — Estancia Cuatro Estaciones

CRM de reservas para spa de circuitos, con bot de WhatsApp orquestado por n8n.

## Documentación

| Documento | Para quién | Contenido |
|---|---|---|
| [`api-n8n.md`](./api-n8n.md) | Quien arma los flujos de n8n | Contrato completo de la API: endpoints, auth, ejemplos, errores |
| [`arquitectura.md`](./arquitectura.md) | Técnico / mantenimiento | Cómo funciona por dentro: bot, automatizaciones, cupo, roles, seguridad |
| [`deploy.md`](./deploy.md) | Quien lo instala | Docker, variables de entorno, WhatsApp, n8n, checklist de producción |
| [`operacion.md`](./operacion.md) | Dueño y recepción | Uso diario: turnero, inbox, reservas, cierre del día, campañas |

## En una frase

El cliente escribe por WhatsApp → **n8n** interpreta y usa la **API del CRM** para consultar
disponibilidad, precios y crear reservas → **toda la lógica de negocio** (cupo, seña, precios,
políticas) vive en el **backend Django**, no en n8n. El equipo del spa opera desde una interfaz
web (turnero-calendario, inbox estilo WhatsApp Web, reservas, campañas, vouchers).

## Qué hace, resumido

- **Reservas de circuitos** con validación de cupo **anti-sobreventa** (lock a nivel DB).
- **Bot de WhatsApp** vía Evolution API + n8n, con **handoff** a humano.
- **Automatizaciones**: recordatorios, reclamo de seña, encuestas, reactivación, cumpleaños,
  lista de espera con hold, alertas de cupo.
- **Gestión del día**: turnero-calendario, cierre del día (asistió/no-show), reprogramación,
  política de cancelación, lista de espera.
- **Marketing**: campañas de WhatsApp por segmento, gift cards (vouchers).
- **Visibilidad**: dashboard de ingresos/ocupación/clientes y panel de salud del sistema
  (ambos solo para el dueño).

## Stack

Django 5.1 · DRF · PostgreSQL · Celery + Redis · Evolution API · n8n.
Ver [`arquitectura.md`](./arquitectura.md) para el detalle.
