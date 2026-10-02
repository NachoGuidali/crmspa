// Conecta los precios de la web con el CRM (crm.<dominio de la web>).
// Cambiando un precio en el CRM, la web lo toma. Si el CRM no responde, quedan
// los precios escritos en la página como fallback.
//
// Uso en el componente de cada página (framework dc):
//   state = { ..., precios: null };
//   componentDidMount() { var self = this; window.CRM.fetchPrecios(function (p) { self.setState({ precios: p }); }); }
//   renderVals() { return { ..., circuitos: window.CRM.aplicar(circuitos, this.state.precios) }; }
//   (en el home, que muestra las cards como resumen: aplicar(circuitos, precios, { incluyeMax: 5 }))
(function () {
  // El CRM vive en el subdominio crm. del mismo dominio que la página. Se calcula en vez de
  // escribirlo fijo para que ande durante la mudanza de dominio: servida desde
  // spacuatroraices.com.ar pega a crm.spacuatroraices.com.ar, y si todavía se sirve desde el
  // dominio viejo pega al CRM viejo. Abierta como archivo local (sin host), usa el principal.
  function crmBase() {
    var h = (window.location && window.location.hostname || '').replace(/^www\./, '');
    if (!h || h === 'localhost' || /^\d+\.\d+\.\d+\.\d+$/.test(h)) h = 'spacuatroraices.com.ar';
    return 'https://crm.' + h;
  }
  var API = crmBase() + '/api/v1/publico/circuitos/';

  function fmtMoney(n) {
    if (n === null || n === undefined || isNaN(n)) return '';
    return '$' + Math.round(n).toLocaleString('es-AR');
  }

  // Deriva una clave estable (grupal-clasico, pareja-premium, …) del nombre/título,
  // para machear la web con el CRM aunque los textos difieran ("Circuito" vs "Spa").
  function claveCircuito(s) {
    s = (s || '').toLowerCase();
    if (s.normalize) s = s.normalize('NFD').replace(/[̀-ͯ]/g, '');
    var tipo = s.indexOf('grupal') >= 0 ? 'grupal' : (s.indexOf('pareja') >= 0 ? 'pareja' : '');
    var tier = s.indexOf('premium') >= 0 ? 'premium' : (s.indexOf('clasico') >= 0 ? 'clasico' : '');
    return tipo + '-' + tier;
  }

  function fetchPrecios(cb) {
    fetch(API)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data && data.circuitos) cb(data.circuitos); })
      .catch(function () {});
  }

  // opciones.incluyeMax: cuántos ítems de "¿Qué incluye?" mostrar. El home usa las cards como
  // resumen (5 líneas) y las páginas de cada circuito muestran la lista entera.
  function aplicar(circuitos, precios, opciones) {
    if (!precios || !circuitos) return circuitos;
    var incluyeMax = (opciones && opciones.incluyeMax) || 0;
    var porClave = {};
    precios.forEach(function (p) { porClave[claveCircuito(p.nombre)] = p; });

    return circuitos.map(function (c) {
      var api = porClave[claveCircuito(c.titulo || c.categoria)];
      if (!api || !c.flyer) return c;
      var flyer = Object.assign({}, c.flyer);
      var nuevo = Object.assign({}, c);

      // "¿Qué incluye?": si el CRM tiene cargada la lista, manda esa. Vacía en el CRM
      // significa "dejá la de la página", no "no mostrar nada".
      if (api.incluye && api.incluye.length) {
        nuevo.bullets = incluyeMax ? api.incluye.slice(0, incluyeMax) : api.incluye;
      }

      if (api.por_persona && api.tramos && api.tramos.length) {
        flyer.tiers = api.tramos.map(function (t) {
          return {
            rango: t.desde + 'p - ' + t.hasta + 'p',
            lunJue: fmtMoney(t.precio_persona_semana),
            vieSabDom: fmtMoney(t.precio_persona_finde),
          };
        });
        var top = api.tramos[api.tramos.length - 1];
        if (api.precio_persona_adicional_semana) {
          flyer.extra = 'Pasados los ' + top.hasta + ' personas se cobra ' +
            fmtMoney(api.precio_persona_adicional_semana) + ' extra x persona.';
        }
        var desde = Math.min.apply(null, api.tramos.map(function (t) { return t.precio_persona_semana; }));
        nuevo.precioDesde = 'Desde ' + fmtMoney(desde) + ' x persona';
      } else if (!api.por_persona) {
        var cap = api.capacidad_maxima || 2;
        flyer.flatLunJue = fmtMoney(api.precio_total_semana / cap);
        flyer.flatVieSabDom = fmtMoney(api.precio_total_finde / cap);
        flyer.flatLunJue2p = fmtMoney(api.precio_total_semana);
        flyer.flatVieSabDom2p = fmtMoney(api.precio_total_finde);
        nuevo.precioDesde = 'Desde ' + fmtMoney(api.precio_total_semana / cap) + ' c/u';
      }
      nuevo.flyer = flyer;
      return nuevo;
    });
  }

  window.CRM = { fetchPrecios: fetchPrecios, aplicar: aplicar, fmtMoney: fmtMoney };
})();
