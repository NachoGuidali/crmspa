# Despliegue y configuración

Cómo levantar el CRM en local y en producción, y qué configurar.

---

## 1. Servicios (docker-compose)

| Servicio | Imagen | Puerto host | Rol |
|---|---|---|---|
| `db` | postgres:15 | **5435** → 5432 | Base de datos |
| `redis` | redis:7 | **6380** → 6379 | Broker de Celery + caché |
| `web` | build local | **8003** → 8000 | Django (gunicorn) |
| `celery` | build local | — | Worker de automatizaciones y envíos |
| `celery-beat` | build local | — | Scheduler (dispara las automatizaciones) |
| `evolution-api` | evolution-api | **8081** → 8080 | Gateway de WhatsApp |

> Los puertos del host (5435/6380/8003/8081) están elegidos para no chocar con otros
> proyectos que corran en la misma máquina.

**Importante:** para que el bot funcione, **`celery` y `celery-beat` tienen que estar
corriendo**. Sin ellos: no se reenvían mensajes a n8n ni se envían recordatorios.

---

## 2. Variables de entorno

Copiá `.env.example` a `.env` y completá. Las más importantes:

| Variable | Para qué | Nota |
|---|---|---|
| `SECRET_KEY` | Clave de Django | En prod **no** puede empezar con `django-insecure` (falla el arranque) |
| `DEBUG` | Modo debug | `False` en producción |
| `ALLOWED_HOSTS` | Dominios permitidos | Ej. `crm.tuspa.com` |
| `DB_*` | Conexión a Postgres | El contenedor usa `DB_HOST=db`, `DB_PORT=5432` |
| `REDIS_URL` | Broker/caché | Contenedor: `redis://redis:6379/0` |
| `EVOLUTION_API_URL` | URL de Evolution | Ej. `http://evolution-api:8080` |
| `EVOLUTION_API_KEY` | Auth de Evolution | La misma que configurás en Evolution |
| `EVOLUTION_INSTANCE` | Nombre de instancia | Default `crmspa` |
| `N8N_WEBHOOK_URL` | Webhook de n8n | A dónde el CRM reenvía los mensajes |
| `CSRF_TRUSTED_ORIGINS` | HTTPS/CSRF | Ej. `https://crm.tuspa.com` |
| `THROTTLE_*` | Rate limits | Opcionales, tienen default |

> Las credenciales de Evolution también se pueden cargar/editar desde la UI en
> *Configuración WhatsApp* (tienen prioridad sobre las variables de entorno).

---

## 3. Puesta en marcha

### Local (desarrollo)

```bash
# 1. Levantar db y redis
docker compose up -d db redis

# 2. Entorno Python
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Variables
cp .env.example .env        # editar según haga falta

# 4. Migrar y crear usuario dueño
python manage.py migrate
python manage.py createsuperuser
#   luego, en /admin/, poné rol = "dueno" a ese usuario

# 5. Correr
python manage.py runserver 0.0.0.0:8003
# en otra terminal, para automatizaciones:
celery -A config worker -l info
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

`manage.py` usa `config.settings.local` por defecto; wsgi/asgi usan `config.settings.production`.

### Producción (todo dockerizado)

```bash
cp .env.example .env        # completar con valores reales de producción
docker compose up -d --build
```

El contenedor `web` corre `migrate` + `collectstatic` + gunicorn automáticamente. Poné un
**nginx** adelante para terminar TLS (el `SECURE_PROXY_SSL_HEADER` ya está configurado).

---

## 4. Conectar WhatsApp (Evolution API)

1. Levantar `evolution-api` (ya está en el compose).
2. Crear la instancia (nombre = `EVOLUTION_INSTANCE`) y **vincular el número por QR** desde el
   panel de Evolution (`http://<host>:8081`).
3. Configurar el **webhook** de Evolution apuntando a:
   ```
   POST https://<tu-dominio>/whatsapp/webhook/evolution/
   header apikey: <webhook_token>
   ```
4. En el CRM, *Configuración WhatsApp*: cargar la URL, la API key y el **mismo webhook token**.

> En producción, si el webhook token no está configurado, el CRM **rechaza** los webhooks
> (medida de seguridad).

---

## 5. Conectar n8n

1. Setear `N8N_WEBHOOK_URL` con la URL del nodo Webhook de tu flujo.
2. Crear una **API Key** en el admin (*Integraciones → API Keys*) y usarla como header
   `X-Api-Key` en todas las llamadas de n8n al CRM.
3. Armar el flujo siguiendo [`api-n8n.md`](./api-n8n.md) (§8, flujo recomendado).

---

## 6. Checklist de producción

- [ ] `SECRET_KEY` random y secreto (no `django-insecure`).
- [ ] `DEBUG=False`.
- [ ] `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS` con el dominio real.
- [ ] TLS (nginx) delante del contenedor web.
- [ ] `celery` y `celery-beat` corriendo (verificar en `/salud/`).
- [ ] Webhook token de Evolution configurado.
- [ ] API Key creada para n8n.
- [ ] Usuario dueño creado; recepcionistas con `rol=recepcion`.
- [ ] Backups del volumen `postgres_data`.
