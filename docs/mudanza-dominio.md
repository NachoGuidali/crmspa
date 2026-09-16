# Mudanza de dominio: spacuatroestaciones.com → spacuatroraices.com.ar

| Nombre | Qué hace después de la mudanza |
|---|---|
| **spacuatroraices.com.ar** | Web pública. **El principal**: el único que indexa Google. |
| www.spacuatroraices.com.ar | Redirige (301) al principal. |
| spacuatroraices.com · www.spacuatroraices.com | Redirigen (301) al principal. |
| **crm.spacuatroraices.com.ar** | CRM. |
| spacuatroestaciones.com (+ www) | **Redirige (301) al principal.** Queda vivo para que los links viejos no se rompan. |
| crm.spacuatroestaciones.com | Sigue atendiendo el CRM mientras se mudan los webhooks. |

> **El orden importa.** Cada fase deja todo funcionando antes de pasar a la siguiente. Hasta la
> fase 5 el dominio viejo sigue exactamente igual que hoy: si algo falla a mitad de camino, la web
> y el bot siguen andando.

---

## Fase 1 — DNS

En el proveedor de **cada** dominio (`.com.ar` y `.com`), registros tipo **A** apuntando al VPS:

| Nombre | Tipo | Valor |
|---|---|---|
| `spacuatroraices.com.ar` (o `@`) | A | `149.50.153.81` |
| `www.spacuatroraices.com.ar` | A | `149.50.153.81` |
| `crm.spacuatroraices.com.ar` | A | `149.50.153.81` |
| `spacuatroraices.com` (o `@`) | A | `149.50.153.81` |
| `www.spacuatroraices.com` | A | `149.50.153.81` |

Esperá a que resuelvan (minutos a unas horas). Verificalo desde el server:

```bash
for h in spacuatroraices.com.ar www.spacuatroraices.com.ar crm.spacuatroraices.com.ar \
         spacuatroraices.com www.spacuatroraices.com; do
  printf "%-30s %s\n" $h "$(getent hosts $h | awk '{print $1}')"
done
```

Los cinco tienen que mostrar `149.50.153.81`. **No sigas hasta que estén todos**: certbot falla si
alguno no resuelve.

## Fase 2 — nginx y SSL para los dominios nuevos

Es un archivo **nuevo**; no toca el de `spacuatroestaciones` que ya tiene los certificados.

```bash
cd /opt/crmspa && git pull
sudo cp deploy/nginx-spacuatroraices.conf /etc/nginx/sites-available/spacuatroraices
sudo ln -s /etc/nginx/sites-available/spacuatroraices /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d spacuatroraices.com.ar -d www.spacuatroraices.com.ar \
     -d spacuatroraices.com -d www.spacuatroraices.com -d crm.spacuatroraices.com.ar
```

Cuando certbot pregunte si redirigir HTTP a HTTPS, **sí**.

Abrí `https://spacuatroraices.com.ar` en el navegador: tiene que verse la web con candado.
El CRM todavía no — eso es la fase 3.

## Fase 3 — el CRM atiende en los dos dominios

En `/opt/crmspa/.env`:

```
ALLOWED_HOSTS=crm.spacuatroraices.com.ar,crm.spacuatroestaciones.com
CSRF_TRUSTED_ORIGINS=https://crm.spacuatroraices.com.ar,https://crm.spacuatroestaciones.com
CORS_ALLOWED_ORIGINS=https://spacuatroraices.com.ar,https://www.spacuatroraices.com.ar,https://spacuatroestaciones.com,https://www.spacuatroestaciones.com
```

Los dos CRM a la vez a propósito: los webhooks de Meta y Evolution siguen apuntando al viejo hasta
la fase 4, y **un webhook no sigue redirects** — un POST redirigido se pierde en el camino.

```bash
docker compose up -d --build web celery celery-beat
```

(Aplica la migración que pasa el link de políticas del WhatsApp de confirmación al dominio nuevo.)

Verificá:

- `https://crm.spacuatroraices.com.ar` → carga el login del CRM.
- `https://crm.spacuatroestaciones.com` → **también** carga.
- `https://spacuatroraices.com.ar` → los precios de los circuitos se ven (si aparecen los de
  respaldo del HTML, falta el CORS).

## Fase 4 — mover las integraciones

El CRM atiende en los dos dominios, así que esto va en el orden que quieras y sin apuro.

**n8n** — importá el flujo nuevo. El nodo *Config CRM* ya apunta a
`https://crm.spacuatroraices.com.ar/`. Mandá un WhatsApp de prueba y fijate que conteste.

**Evolution API** — en la configuración del webhook de la instancia:

```
https://crm.spacuatroraices.com.ar/whatsapp/webhook/evolution/
```

**Meta** (si está activo) — tu app → WhatsApp → Configuración → Webhook → Editar:

```
https://crm.spacuatroraices.com.ar/whatsapp/webhook/meta/
```

El *Verify Token* es el mismo. Tiene que quedar en verde.

Después de cada cambio, mandá un WhatsApp al número del spa y mirá que llegue al inbox:

```bash
docker compose logs web -f | grep webhook
```

Tenés que ver el POST llegando al host **nuevo**.

## Fase 5 — el dominio viejo redirige

Solo cuando las fases 1 a 4 anden. A partir de acá quien entre a `spacuatroestaciones.com` termina
en `spacuatroraices.com.ar`.

No pises `/etc/nginx/sites-available/spacuatroestaciones` con el template: tiene los bloques de
certbot. Lo cambia un script que toca **solo** los bloques de la web (los del CRM quedan byte por
byte iguales), hace backup, corre `nginx -t` y si falla restaura el backup sin recargar nada:

```bash
cd /opt/crmspa && git pull
sudo python3 deploy/redirigir-dominio-viejo.py --solo-mostrar   # revisá el diff, no escribe
sudo python3 deploy/redirigir-dominio-viejo.py                  # aplica, prueba y recarga
curl -sI https://spacuatroestaciones.com/spa-grupal.html | grep -i "^location"
```

Si preferís hacerlo a mano: en los bloques `server` de `spacuatroestaciones.com` y
`www.spacuatroestaciones.com` que tienen `root`, sacá `root`, `index` y los `location`, y poné
`return 301 https://spacuatroraices.com.ar$request_uri;`. **No toques el de
`crm.spacuatroestaciones.com`.**

Tiene que responder `location: https://spacuatroraices.com.ar/spa-grupal.html` — la ruta se
conserva, así cada link viejo cae en su página equivalente.

## Fase 6 — Google y redes

**Search Console** — el paso a paso para el dueño está en `docs/search-console.md`, ya actualizado:

1. Agregar la propiedad de tipo **Dominio** para `spacuatroraices.com.ar` (TXT en el DNS del
   `.com.ar`) y enviar `sitemap.xml`.
2. En la propiedad **vieja**: *Configuración → Cambio de dirección* → elegir la nueva. Solo deja
   hacerlo con la fase 5 hecha y las dos propiedades verificadas. Le avisa a Google que traslade el
   posicionamiento.

**Perfil de Google (Maps)** — cambiar el link del sitio web al dominio nuevo.

**Instagram y Facebook** — actualizar el link de la bio.

## Fase 7 — más adelante

- **No dejes vencer `spacuatroestaciones.com`.** Los redirects dependen de que siga activo. Como
  mínimo un año, idealmente para siempre: es barato y hay links viejos en todos lados.
- Cuando los webhooks lleven un tiempo andando en el dominio nuevo, podés sacar
  `crm.spacuatroestaciones.com` de `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS`.
- La URL de privacidad cargada en la app de Meta sigue en el dominio viejo (funciona por el
  redirect). Actualizala en el panel de la app cuando termine la revisión.
