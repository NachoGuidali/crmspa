# Darse de alta como Tech Provider en Meta (paso a paso, desde cero)

Guía para registrarte **vos (monotributo)** como **Tech Provider** de la Plataforma de WhatsApp
Business, y después onboardear a **Spa 4 Estaciones** (y otros números) como clientes con
**Coexistence** (el número queda usable en la app del celular **y** en la API/CRM).

> **Expectativa de tiempos:** hay dos revisiones que las controla Meta —**verificación del negocio**
> y **App Review**— que pueden tardar **días o alguna semana**. El resto es rápido.
>
> **Estrategia:** te registrás **una sola vez** como Tech Provider. Después vas sumando números/
> negocios como clientes sin volver a registrarte.

---

## Fase 0 — Juntá esto antes de empezar
- [ ] **Cuenta de Facebook** personal (para entrar a todo).
- [ ] **Datos del negocio (los tuyos, monotributo):** nombre/razón, dirección, teléfono, email, sitio web.
- [ ] **Documento para verificar:** **constancia de inscripción de AFIP** con tu **CUIT** (PDF).
      Que el nombre y la dirección coincidan con lo que cargues.
- [ ] **URL de política de privacidad:** ya está → `https://spacuatroestaciones.com/privacidad.html`.
- [ ] Un **email** al que tengas acceso (te llegan códigos de verificación).

---

## Fase 1 — Cuenta de Facebook
1. Si no tenés, creá una en **facebook.com**. Si ya tenés, usá esa.
2. Confirmá que podés iniciar sesión sin problemas (la vas a usar en todos los pasos).

## Fase 2 — Crear el Business Portfolio (el "negocio" en Meta)
1. Entrá a **business.facebook.com**.
2. **Crear portafolio comercial** (Create business portfolio).
3. Cargá: **nombre del negocio**, tu nombre, y el **email** del negocio. Confirmá el email.

> El "portafolio comercial" (Business Portfolio / Business Manager) es el paraguas donde viven tu
> app, tu WABA y, más adelante, las de tus clientes.

## Fase 3 — Registrarte como desarrollador
1. Entrá a **developers.facebook.com**.
2. Botón **Comenzar / Get Started** (arriba a la derecha) → seguí el registro.
3. Aceptás términos y verificás la cuenta (te puede pedir teléfono/email).

## Fase 4 — Crear la App (caso de uso WhatsApp)
1. En **developers.facebook.com** → **Mis Apps** → **Crear app**.
2. Cuando pregunte el **caso de uso**, elegí **WhatsApp**.
3. **Vinculá el portafolio comercial** de la Fase 2.
4. Se crea la app y te lleva al panel (App Dashboard).

## Fase 5 — Entrar al onboarding de Tech Provider
1. En la app → **Casos de uso (Use cases)** → **Personalizar** (ícono de lápiz) en WhatsApp.
2. En el menú de la izquierda, elegí **"Tech Provider onboarding"**
   (Incorporación como proveedor de tecnología).

## Fase 6 — Verificar el negocio ⏳ (el paso que más tarda)
1. Dentro de "Tech Provider onboarding" → **"Start verification / Iniciar verificación"**.
2. Cargá: nombre del negocio, dirección, teléfono, email y **sitio web**.
3. Elegí un **método de contacto** para que Meta confirme (te manda un código).
4. Si tu negocio **no aparece** en la base de Meta → te pide **documentos**: subí la
   **constancia de AFIP / monotributo**.
5. Queda **"en revisión"**. **No podés avanzar al App Review hasta que esté verificado.**

> **Tip monotributo:** usá exactamente el nombre y domicilio que figuran en la constancia de AFIP.
> Si el negocio opera como "Estancia Cuatro Estaciones", eso va como cliente después; acá va **tu**
> identidad de Tech Provider (tu monotributo).

## Fase 7 — Datos básicos de la app
1. En la app → **Configuración → Básica** (Settings → Basic).
2. Cargá: **ícono** de la app, **categoría**, y la **URL de política de privacidad**
   (`https://spacuatroestaciones.com/privacidad.html`).
3. Guardar.

## Fase 8 — Activar 2FA (obligatorio)
1. En **business.facebook.com → Configuración del negocio → Seguridad** (Security Center).
2. Activá la **autenticación en dos pasos (2FA)**. Es requisito del programa Tech Provider.

## Fase 9 — App Review (pedir permisos) ⏳
1. Volvé a **Tech Provider onboarding** → **"Begin App Review / Comenzar revisión"**.
2. Pedí **"Advanced access / Acceso avanzado"** a:
   - **`whatsapp_business_messaging`** (mandar mensajes por los clientes)
   - **`whatsapp_business_management`** (administrar las WABAs de los clientes)
3. Adjuntá los **videos demostrativos** que pide Meta:
   - Uno mostrando el envío/recepción de un mensaje por tu integración.
   - Uno mostrando la creación de una plantilla.
   - *Sirven grabaciones de pantalla* (incluso de cURL o del WhatsApp Manager).
4. Enviás y **esperás la aprobación** de Meta.

## Fase 10 — Post-aprobación (lo hace el CRM — parte técnica)
Cuando quede aprobado, recién ahí va lo de Coexistence. Esto lo implemento yo en el CRM:
1. **Suscribir los webhooks** de coexistence: `history`, `smb_app_state_sync`, `smb_message_echoes`.
2. **Implementar el Embedded Signup** (página web con el SDK de Meta) para onboardear clientes.
3. Onboardear a **Spa 4 Estaciones** (su número, coexistence) y cargar **método de pago**.
4. Después, cada número/cliente nuevo se onboardea por ese mismo Embedded Signup.

---

## Resumen del orden
Facebook → Business Portfolio → Developer → App (WhatsApp) → Tech Provider onboarding →
**Verificación del negocio** ⏳ → Datos básicos + privacidad → 2FA → **App Review** ⏳ → (CRM) Coexistence.

## Recordatorio de costos (por qué hacemos esto)
- Desde **oct-2026** Meta cobra **todos** los mensajes por la API (también los de servicio).
- La **app del celular sigue gratis** → coexistence deja la **atención manual gratis**.
- El **bot igual paga** por lo que manda por la API. Si en algún momento no compensa, **Evolution**
  deja todo gratis (no oficial).
