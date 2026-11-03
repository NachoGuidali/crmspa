// Mensajes difíciles contra el MODELO DE VERDAD: varias intenciones juntas, cambios de idea,
// typos, impaciencia, audios. Para cada uno muestra qué entendió y por dónde rutea.
//
//   node probar-con-ia.js "<flujo .json>"
//
// Esto NO es el banco: pega contra la API de OpenAI y sale unos centavos por corrida. Pero es
// lo único que prueba la cadena completa (modelo → parser → ruteo), y es lo que encontró los
// bugs que el banco no podía ver: el banco simula la IA, así que nunca la ve equivocarse.
//
// Qué mirar: que ninguna línea termine en un absurdo (el catálogo cuando pidió fechas, la
// lista de días cuando mandó un audio, "¿sobre qué querés info?" cuando preguntó algo
// concreto). No hay asserts a propósito: lo que define "absurdo" es el criterio de quien lee.
const fs = require('fs');
const { DT } = require('/home/nacho/crmspa/crmspa/herramientas/banco-bot/luxon-min.js');
const flujo = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const nodo = (n) => flujo.nodes.find(x => x.name === n);
const key = (nodo('Config CRM').parameters.values.string.find(x => x.name === 'openai_api_key') || {}).value;
const prom = new Function('$json', nodo('Code: prompt + esquema IA (editar aca)').parameters.jsCode)({})[0].json;
const codParser = nodo('Code: parsear interpretacion IA').parameters.jsCode;

async function modelo(texto, estado, conv, ultimoBot, historial) {
  const ctx = ['Hoy es 2026-11-03 (martes)', `Paso actual: ${estado}`,
    `Datos ya conocidos de la reserva en curso: personas=${conv.personas || '(sin dato)'}, tipo_propuesta=${conv.tipo_propuesta || '(sin dato)'}, nivel=${conv.nivel || '(sin dato)'}, fecha_y_turno=${conv.fecha_solicitada || '(sin dato)'}, menu_especial=(sin dato), extras=(sin dato)`,
    `Ya vio el catalogo: ${conv.catalogo_enviado ? 'SI' : 'NO'}`,
    'Feriados proximos: 2026-11-23 (Dia de la Soberania)',
    `Ultimo mensaje del bot: ${JSON.stringify(ultimoBot || '(ninguno)')}`,
    `Historial reciente:\n${historial || '(sin historial)'}`,
    `Mensaje del cliente: ${JSON.stringify(texto)}`].join('\n');
  const r = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST', headers: { Authorization: 'Bearer ' + key, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'gpt-4.1-mini', temperature: 0, response_format: prom.esquema,
      messages: [{ role: 'system', content: prom.prompt }, { role: 'user', content: ctx }] }),
  });
  const b = await r.json();
  if (!r.ok) throw new Error(JSON.stringify(b.error));
  return JSON.parse(b.choices[0].message.content);
}
function parsear(texto, estado, ia, conv, ultimoBot) {
  const resp = { choices: [{ message: { content: JSON.stringify(ia) } }] };
  const nodos = {
    'Normalizar payload del CRM': { telefono: '1', texto, texto_lower: texto.toLowerCase(), nombre_contacto: 'Ana Perez' },
    'Code: MEDIOS DE PAGO HABILITADOS (editar aca)': Object.assign({ estado_flujo: estado, fallos_consecutivos: '' }, conv),
    'Code: armar historial para IA': { ultimo_mensaje_bot: ultimoBot || '' },
    'GET feriados (para el contexto)': { feriados: [{ fecha: '2026-11-23', cerrado: false }] },
    'POST Groq: interpretar mensaje del cliente': resp, 'Config CRM': {},
  };
  const $ = (n) => ({ item: { json: nodos[n] || {} }, first: () => ({ json: nodos[n] || {} }) });
  return new Function('$', '$json', '$input', '$now', codParser)($, resp, { all: () => [{ json: resp }], first: () => ({ json: resp }) }, new DT('2026-11-03T10:00:00-03:00'))[0].json;
}
function ruta(P, estado) {
  if (P.requiere_humano) return 'DERIVA a una persona';
  if (P.entendido === false) return 'nodo del "no entendido" (ahí está el aviso de audio y la respuesta libre)';
  if (P.pregunta_aclaracion) return 'aclara: "' + P.pregunta_aclaracion.slice(0, 70) + '"';
  if (P.apertura_vaga) return 'saluda y pregunta qué busca';
  if (P.solicita_info === 'info_generica') return P.info_sin_precisar
    ? 'pregunta sobre qué quiere saber' : 'respuesta libre de la IA';
  if (P.solicita_info) return 'info: ' + P.solicita_info;
  if (P.pide_disponibilidad && !P.fecha_solicitada) return 'pide la fecha';
  return 'reserva (paso ' + estado + ')';
}
const CASOS = [
  ['varias cosas en un mensaje', 'nuevo', {},
   'hola! somos 4 amigas, queremos el premium para el sabado 14 a la tarde, cuanto sale?'],
  ['cambia de idea (nivel)', 'turno_fecha', { personas: 2, tipo_propuesta: 'pareja', nivel: 'premium' },
   'mejor el clasico, sale menos no?'],
  ['cambia de idea (fecha)', 'turno_confirmar_fecha', { personas: 2, tipo_propuesta: 'pareja', nivel: 'clasico', fecha_solicitada: '2026-11-14' },
   'uy no, mejor para el 21'],
  ['cambia la cantidad', 'turno_fecha', { personas: 2, tipo_propuesta: 'pareja', nivel: 'clasico' },
   'y si somos 6 al final?'],
  ['con errores de tipeo', 'menu', { catalogo_enviado: true },
   'kiero reservr para 2 el sabdo a la tarde'],
  ['impaciencia', 'turno_fecha', { personas: 2, tipo_propuesta: 'pareja', nivel: 'clasico' },
   'hola?? me contestas?'],
  ['pregunta suelta en medio', 'turno_datos_email', { personas: 2, tipo_propuesta: 'pareja', nivel: 'clasico', fecha_solicitada: '2026-11-14' },
   'una duda, se puede fumar ahi?'],
  ['duda de plata en medio', 'turno_pago', { personas: 2, tipo_propuesta: 'pareja', nivel: 'clasico', fecha_solicitada: '2026-11-14' },
   'y si despues no puedo ir, me devuelven la sena?'],
  ['audio', 'turno_fecha', { personas: 2, nivel: 'clasico' }, '[Audio]'],
  ['solo un emoji', 'turno_fecha', { personas: 2, nivel: 'clasico' }, '👍'],
  ['regala la experiencia', 'menu', { catalogo_enviado: true },
   'es para regalarle a mi hermana, se puede?'],
  ['pregunta por otro circuito en medio', 'turno_fecha', { personas: 2, tipo_propuesta: 'pareja', nivel: 'clasico' },
   'y el grupal para 6 cuanto sale?'],
];
(async () => {
  for (const [etiq, estado, conv, texto] of CASOS) {
    try {
      const ia = await modelo(texto, estado, conv, '');
      const P = parsear(texto, estado, ia, conv, '');
      const datos = ['personas', 'tipo_propuesta', 'nivel', 'fecha_solicitada', 'turno_pedido']
        .filter(k => P[k] && P[k] !== conv[k]).map(k => `${k}=${P[k]}`).join(' ');
      console.log(`${etiq}`);
      console.log(`   "${texto}"`);
      console.log(`   → ${ruta(P, estado)}${datos ? '   [nuevo: ' + datos + ']' : ''}`);
    } catch (e) { console.log(`${etiq}: ERROR ${e.message.slice(0, 80)}`); }
  }
})();
