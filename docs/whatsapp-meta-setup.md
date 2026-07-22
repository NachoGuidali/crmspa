# Conectar WhatsApp por Meta Cloud API (oficial)

Guía práctica para conectar el CRM con la **API oficial de Meta**, con los problemas reales que
aparecen y cómo resolverlos. Al final, el paso de **número de prueba → número productivo**.

> El CRM soporta dos proveedores (Evolution / Meta), se elige en **Configuración → WhatsApp**.
> Esta guía es para **Meta**. El proveedor es transparente para n8n (ver `api-n8n.md`).

---

## 1. Qué se carga en el CRM (Configuración → WhatsApp → Meta)

| Campo | De dónde sale |
|---|---|
| **Phone Number ID** | Meta → WhatsApp → API Setup (o Paso 1). Es el ID del número, **no** el número. |
| **WhatsApp Business Account ID (WABA)** | Misma pantalla de API Setup. |
| **Access Token** | Token del número. **Usar el permanente** (System User, ver §3), no el temporal. |
| **App Secret** | Meta → tu app → **Configuración → Básica** → "Clave secreta de la app" (Mostrar). Valida la firma de los webhooks. |
| **Verify Token** | **Lo inventás vos** (cualquier string). El mismo valor va en el CRM y en Meta al configurar el webhook. |
| **Versión de la Graph API** | `v21.0` (default). |

---

## 2. Configurar el webhook en Meta

1. Meta → tu app → **WhatsApp → Configuración** → sección **Webhook** → **Editar**.
2. **URL de devolución de llamada (Callback URL):**
   `https://crm.spacuatroestaciones.com/whatsapp/webhook/meta/`
3. **Identificador de verificación (Verify Token):** el mismo que pusiste en el CRM.
4. **Verificar y guardar.** Meta pega un `GET` al CRM; si el token coincide, queda verde.
   - Requiere **HTTPS con certificado válido** en el dominio del CRM.
5. En **Campos del webhook** → **Administrar** → suscribir **`messages`**.

> **Chequear que llega:** `docker compose logs web -f` mientras verificás → tenés que ver un
> `GET`/`POST` a `/whatsapp/webhook/meta/` respondiendo `200`.

---

## 3. Access Token permanente (que no se vence)

El token temporal de "API Setup" **dura ~24 hs** → después da `401 Session has expired`. Hacé el
permanente **una vez**:

1. **business.facebook.com** → **Configuración del negocio** → **Usuarios → Usuarios del sistema**.
2. **Agregar** usuario del sistema (rol Administrador).
3. **Agregar activos** → asignale la **App** y la **WABA** con control total.
4. **Generar token nuevo** → elegí la app → **Caducidad: Nunca** → permisos:
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
5. Copiá el token (aparece una sola vez) → pegalo en el CRM → **Guardar**.

---

## 4. Problemas reales que aparecieron (y su fix)

### a) `401 Unauthorized` en el test de conexión del CRM
El access token venció o está mal pegado. Verificalo con:
```bash
curl -s "https://graph.facebook.com/v21.0/PHONE_NUMBER_ID?fields=display_phone_number&access_token=TOKEN"
```
- `"Session has expired"` → token vencido → usar el **permanente** (§3).
- `"Cannot parse access token"` → mal pegado/incompleto.
- Devuelve el número → token OK.

### b) Recibo mensajes en el panel de Meta pero NO llegan al CRM
La WABA está suscripta a la **app de muestra de Meta** ("WA DevX Webhook Events 1P App"), no a la
tuya. Verificá y suscribí **tu** app:
```bash
# ¿Qué apps están suscriptas?
curl -s "https://graph.facebook.com/v21.0/WABA_ID/subscribed_apps?access_token=TOKEN"

# Suscribir tu app (el token es de tu app):
curl -X POST "https://graph.facebook.com/v21.0/WABA_ID/subscribed_apps?access_token=TOKEN"
# → {"success":true}
```
Después de esto, en el `GET` tiene que aparecer **tu** app en la lista.

### c) Al enviar da `131030 Recipient phone number not in allowed list`
Con **número de prueba** solo se puede enviar a números **agregados a la lista de permitidos**
(Meta → Paso 1 → "Para" → agregar + verificar con el código). Con número productivo real este
límite no existe.

### d) Argentina: el `9` de los celulares
El wa_id entrante trae el `9` (`549 11 ...`), pero Meta espera el número **sin el `9`** para
enviar (`54 + área + número`). El CRM ya lo saca solo al enviar por Meta
(`sender_meta._normalize_phone`, prefijo `549` → `54`). No hay que hacer nada, pero si aparece un
`131030` con un número que sí está en la lista, es por esto.

---

## 5. Checklist de conexión (número de prueba)

- [ ] Credenciales cargadas en el CRM (Phone Number ID, WABA, Access **permanente**, App Secret, Verify Token).
- [ ] Webhook en Meta: Callback URL + Verify Token → **verde**.
- [ ] Campo **`messages`** suscripto.
- [ ] **Tu app** suscripta a la WABA (`subscribed_apps` → `{"success":true}`).
- [ ] Tu celular agregado a la lista de destinatarios permitidos.
- [ ] Test de conexión del CRM en **✓ verde** con el número.
- [ ] Recibís (POST a `/whatsapp/webhook/meta/` → 200, contacto creado solo).
- [ ] Enviás desde el inbox sin `131030`.

---

## 6. Pasar de número de prueba → número productivo

1. En Meta: **Paso 2. Configuración de producción** → agregá tu **número real** a la WABA
   (verificación por SMS/llamada) y cargá un **método de pago**.
2. Si tenés que **verificar el negocio** (Paso 3), subí la documentación.
3. En el CRM → Configuración → WhatsApp → **Meta**: cambiá el **Phone Number ID** por el del
   número productivo (y la **WABA** si es otra). El resto (App Secret, Verify Token) queda igual.
4. Re-suscribí la WABA a la app si cambió:
   `curl -X POST ".../WABA_ID/subscribed_apps?access_token=TOKEN"`.
5. Con número productivo **desaparecen** los dos límites del número de prueba: ya podés escribirle
   a **cualquier** cliente sin agregarlo a ninguna lista.

> **Plantillas (templates):** con el número productivo, para iniciar conversación **fuera de la
> ventana de 24 hs** (ej. recordatorios), Meta exige **plantillas aprobadas**. El envío de
> plantillas por Meta todavía no está implementado en el CRM — si se van a usar recordatorios por
> Meta, hay que sumarlo (con Evolution no hace falta).
