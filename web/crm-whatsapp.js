// El número de WhatsApp de la web sale del CRM (Configuración → Negocio → WhatsApp de la web).
// Así, cambiar de número es editar un campo y no tocar siete archivos y desplegar.
//
// Lo que está escrito en el HTML queda como respaldo: si el CRM no contesta, o todavía no se
// cargó ningún número, los botones siguen funcionando con el último que se publicó.
(function () {
  function crmBase() {
    var h = (window.location && window.location.hostname || '').replace(/^www\./, '');
    if (!h || h === 'localhost' || /^\d+\.\d+\.\d+\.\d+$/.test(h)) h = 'spacuatroraices.com.ar';
    return 'https://crm.' + h;
  }

  function aplicar(datos) {
    if (!datos || !datos.whatsapp) return;

    // Los links: se cambia solo el número y se respeta el ?text= de cada botón, que es lo que
    // hace que el chat abra con el mensaje del circuito correspondiente.
    var links = document.querySelectorAll('a[href*="wa.me/"]');
    for (var i = 0; i < links.length; i++) {
      links[i].href = links[i].getAttribute('href')
        .replace(/wa\.me\/\d+/, 'wa.me/' + datos.whatsapp);
    }

    // El número escrito (el de la barra de arriba). Se marca en el HTML con data-whatsapp.
    if (datos.whatsapp_visible) {
      var textos = document.querySelectorAll('[data-whatsapp]');
      for (var j = 0; j < textos.length; j++) {
        textos[j].textContent = datos.whatsapp_visible;
      }
    }
  }

  function arrancar() {
    fetch(crmBase() + '/api/v1/publico/contacto/')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(aplicar)
      .catch(function () {});   // sin CRM, queda el número del HTML
  }

  // El framework de la página dibuja los botones después: se espera a que el DOM esté listo.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', arrancar);
  } else {
    arrancar();
  }
})();
