// Corre el nodo "Code: parsear interpretacion IA" del flujo de n8n acá, sin n8n.
// Ese nodo es el cerebro del bot: decide qué entendió, qué dato guarda y si deriva a una
// persona. Probarlo suelto evita tener que mandar WhatsApps reales para cada cambio.
const fs = require('fs');
const { DT } = require('./luxon-min.js');

const NODO = 'Code: parsear interpretacion IA';

function codigoDelFlujo(rutaJson, nombreNodo = NODO) {
  const flujo = JSON.parse(fs.readFileSync(rutaJson, 'utf8'));
  const nodo = flujo.nodes.find(n => n.name === nombreNodo);
  if (!nodo) throw new Error(`No encontré el nodo "${nombreNodo}" en ${rutaJson}`);
  return nodo.parameters.jsCode;
}

// Simula lo que n8n le pasa al nodo: $() para leer nodos anteriores, $json, $input y $now.
function correr(codigo, caso, hoy = '2026-10-13T14:30:00-03:00') {
  const respuestaIA = { choices: [{ message: { content: JSON.stringify(caso.ia || {}) } }] };
  const nodos = {
    'Normalizar payload del CRM': {
      telefono: '5491100000000', texto: caso.texto,
      texto_lower: (caso.texto || '').toLowerCase(), nombre_contacto: caso.contacto || 'Cliente',
    },
    'Code: MEDIOS DE PAGO HABILITADOS (editar aca)': caso.conversacion,
    'Code: armar historial para IA': { ultimo_mensaje_bot: caso.ultimo_mensaje_bot || '', contexto_ia: '' },
    'POST Groq: interpretar mensaje del cliente': respuestaIA,
    'Config CRM': {},
  };
  const $ = (n) => ({ item: { json: nodos[n] || {} }, first: () => ({ json: nodos[n] || {} }) });
  const $input = { all: () => [{ json: respuestaIA }], first: () => ({ json: respuestaIA }) };
  const fn = new Function('$', '$json', '$input', '$now', codigo);
  return fn($, respuestaIA, $input, new DT(hoy))[0].json;
}

// Atajo para escribir casos: estado del flujo + lo que ya sabe el CRM de esa conversación.
function conversacion(estado, extra = {}) {
  return Object.assign({
    estado_flujo: estado, personas: 3, tipo_propuesta: 'grupal', nivel: 'premium',
    fallos_consecutivos: '', menu_especial: null,
  }, extra);
}

module.exports = { codigoDelFlujo, correr, conversacion, NODO };
