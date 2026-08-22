// Cartel emergente (popup) de promos y fechas especiales, administrado desde el CRM.
//
// La web es estática, así que el contenido no vive acá: se pide a
// GET /api/v1/publico/popup/ cada vez que carga la página. Prender, apagar, cambiar el texto
// o la foto se hace en el CRM (Configuración → Popups de la web) y se ve al instante, sin
// tocar HTML ni volver a deployar. Si no hay ninguno vigente, la API devuelve null y este
// script no dibuja nada.
//
// Uso: <script src="./crm-popup.js"></script> en el <head>. No necesita nada más.
(function () {
  'use strict';

  var API = 'https://crm.spacuatroestaciones.com/api/v1/publico/popup/';
  var DEMORA_MS = 1200;           // que el visitante vea la página antes del cartel
  var CLAVE = 'crm_popup_visto';  // { "<id>:<version>": <timestamp de cierre> }

  // ── localStorage sin romper nada ───────────────────────────────────────────
  // En navegación privada o con cookies bloqueadas, el solo hecho de tocarlo tira excepción.
  // Ante la duda, mostramos el cartel: es preferible a no mostrarlo nunca.
  function leerVistos() {
    try { return JSON.parse(localStorage.getItem(CLAVE) || '{}') || {}; }
    catch (e) { return {}; }
  }
  function marcarVisto(clave) {
    try {
      var v = leerVistos();
      v[clave] = Date.now();
      // No dejamos crecer el registro para siempre: alcanza con los últimos 20 popups.
      var claves = Object.keys(v).sort(function (a, b) { return v[b] - v[a]; }).slice(0, 20);
      var podado = {};
      claves.forEach(function (k) { podado[k] = v[k]; });
      localStorage.setItem(CLAVE, JSON.stringify(podado));
    } catch (e) { /* sin storage: se volverá a mostrar, y está bien */ }
  }

  function hayQueMostrar(p) {
    var horas = Number(p.repetir_horas);
    if (!horas) return true;                       // 0 = siempre
    // La clave incluye la versión: si el dueño edita el cartel, vuelve a aparecer aunque
    // el visitante ya lo hubiera cerrado. Un cartel nuevo es una novedad nueva.
    var cerradoEn = leerVistos()[p.id + ':' + p.version];
    if (!cerradoEn) return true;
    return (Date.now() - cerradoEn) > horas * 3600 * 1000;
  }

  // ── Estilos ───────────────────────────────────────────────────────────────
  function inyectarEstilos() {
    if (document.getElementById('crm-popup-css')) return;
    var css = document.createElement('style');
    css.id = 'crm-popup-css';
    css.textContent = [
      '.crmpop-fondo{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;',
      'justify-content:center;padding:20px;background:rgba(40,24,12,.62);',
      'backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);opacity:0;',
      'transition:opacity .28s ease}',
      '.crmpop-fondo.crmpop-visible{opacity:1}',
      '.crmpop-caja{position:relative;background:#fdf5ed;color:#3b2415;border-radius:14px;',
      'max-width:420px;width:100%;max-height:88vh;overflow-y:auto;box-shadow:0 18px 50px rgba(0,0,0,.35);',
      'transform:translateY(14px) scale(.98);transition:transform .28s ease;text-align:center}',
      '.crmpop-fondo.crmpop-visible .crmpop-caja{transform:none}',
      '.crmpop-img{display:block;width:100%;height:auto;border-radius:14px 14px 0 0}',
      '.crmpop-cuerpo{padding:22px 26px 26px}',
      ".crmpop-titulo{font-family:'Bodoni Moda','Playfair Display',Georgia,serif;font-size:1.5rem;",
      'line-height:1.25;margin:0 0 10px;color:#3b2415}',
      ".crmpop-msg{font-family:'Montserrat',system-ui,sans-serif;font-size:.94rem;line-height:1.55;",
      'margin:0;color:#6b5344;white-space:pre-line}',
      ".crmpop-cta{display:inline-block;margin-top:18px;padding:12px 26px;border-radius:999px;",
      "background:#eb5f11;color:#fff;font-family:'Montserrat',system-ui,sans-serif;font-weight:600;",
      'font-size:.9rem;text-decoration:none;transition:background .2s ease}',
      '.crmpop-cta:hover{background:#ef8627;color:#fff}',
      '.crmpop-x{position:absolute;top:10px;right:10px;width:34px;height:34px;border:0;',
      'border-radius:50%;background:rgba(253,245,237,.92);color:#3b2415;font-size:20px;',
      'line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;',
      'box-shadow:0 2px 8px rgba(0,0,0,.18)}',
      '.crmpop-x:hover{background:#fff}',
      '@media (prefers-reduced-motion:reduce){.crmpop-fondo,.crmpop-caja{transition:none}}'
    ].join('');
    document.head.appendChild(css);
  }

  // ── Render ────────────────────────────────────────────────────────────────
  function mostrar(p) {
    inyectarEstilos();
    var focoPrevio = document.activeElement;

    var fondo = document.createElement('div');
    fondo.className = 'crmpop-fondo';
    fondo.setAttribute('role', 'dialog');
    fondo.setAttribute('aria-modal', 'true');
    fondo.setAttribute('aria-label', p.titulo || 'Novedades');

    var caja = document.createElement('div');
    caja.className = 'crmpop-caja';

    var cerrar = document.createElement('button');
    cerrar.className = 'crmpop-x';
    cerrar.type = 'button';
    cerrar.setAttribute('aria-label', 'Cerrar');
    cerrar.innerHTML = '&times;';
    caja.appendChild(cerrar);

    if (p.imagen) {
      var img = document.createElement('img');
      img.className = 'crmpop-img';
      img.src = p.imagen;
      img.alt = p.titulo || '';
      // Si la foto no carga (borrada del CRM, red caída), que no quede un roto en el medio.
      img.onerror = function () { img.remove(); };
      caja.appendChild(img);
    }

    var cuerpo = document.createElement('div');
    cuerpo.className = 'crmpop-cuerpo';

    if (p.titulo) {
      var h = document.createElement('h2');
      h.className = 'crmpop-titulo';
      h.textContent = p.titulo;          // textContent, no innerHTML: nada de inyección
      cuerpo.appendChild(h);
    }
    if (p.mensaje) {
      var msg = document.createElement('p');
      msg.className = 'crmpop-msg';
      msg.textContent = p.mensaje;
      cuerpo.appendChild(msg);
    }
    if (p.cta_texto && p.cta_url) {
      var a = document.createElement('a');
      a.className = 'crmpop-cta';
      a.href = p.cta_url;
      a.textContent = p.cta_texto;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.addEventListener('click', function () { cerrarPopup(false); });
      cuerpo.appendChild(a);
    }

    caja.appendChild(cuerpo);
    fondo.appendChild(caja);
    document.body.appendChild(fondo);

    var scrollPrevio = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    requestAnimationFrame(function () { fondo.classList.add('crmpop-visible'); });
    cerrar.focus();

    function cerrarPopup(registrar) {
      if (registrar !== false) marcarVisto(p.id + ':' + p.version);
      fondo.classList.remove('crmpop-visible');
      document.body.style.overflow = scrollPrevio;
      document.removeEventListener('keydown', onTecla);
      setTimeout(function () { fondo.remove(); }, 300);
      if (focoPrevio && focoPrevio.focus) focoPrevio.focus();
    }

    function onTecla(e) {
      if (e.key === 'Escape') cerrarPopup(true);
    }

    cerrar.addEventListener('click', function () { cerrarPopup(true); });
    fondo.addEventListener('click', function (e) {
      if (e.target === fondo) cerrarPopup(true);   // clic afuera de la caja
    });
    document.addEventListener('keydown', onTecla);
  }

  // ── Arranque ──────────────────────────────────────────────────────────────
  function iniciar() {
    fetch(API)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        var p = data && data.popup;
        if (!p) return;                  // no hay nada prendido: la web queda igual que siempre
        if (!hayQueMostrar(p)) return;
        setTimeout(function () { mostrar(p); }, DEMORA_MS);
      })
      .catch(function () { /* CRM caído: la web sigue andando sin popup */ });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
