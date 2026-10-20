#!/usr/bin/env node
// Le hace las MISMAS preguntas a varios modelos, con el prompt real del bot, y muestra las
// respuestas lado a lado. Sirve para decidir con qué modelo conviene quedarse: el precio a
// esta escala no decide nada, lo que decide es cuál entiende mejor a la gente.
//
//   export GROQ_API_KEY=...        (si no está, se usa la del flujo)
//   export OPENAI_API_KEY=...
//   node comparar-modelos.js "<flujo .json>" [modelo ...]
//
// Sin modelos, compara el que está en producción contra tres candidatos baratos.
const fs = require('fs');
const CASOS = require('./casos-modelos.js');

const PROVEEDORES = {
  groq: { url: 'https://api.groq.com/openai/v1/chat/completions', key: () => process.env.GROQ_API_KEY || claveDelFlujo() },
  openai: { url: 'https://api.openai.com/v1/chat/completions', key: () => process.env.OPENAI_API_KEY },
};
// Precio por millón de tokens (entrada, salida), para estimar el costo de cada respuesta.
const PRECIOS = {
  'openai/gpt-oss-120b': [0.15, 0.60], 'gpt-5-nano': [0.05, 0.40],
  'gpt-4.1-nano': [0.10, 0.40], 'gpt-4o-mini': [0.15, 0.60], 'gpt-5-mini': [0.25, 2.00],
};
const POR_DEFECTO = ['groq:openai/gpt-oss-120b', 'openai:gpt-5-nano', 'openai:gpt-4.1-nano', 'openai:gpt-5-mini'];

const rutaFlujo = process.argv[2];
if (!rutaFlujo) { console.error('Uso: node comparar-modelos.js "<flujo .json>" [proveedor:modelo ...]'); process.exit(2); }
const flujo = JSON.parse(fs.readFileSync(rutaFlujo, 'utf8'));

function nodo(nombre) {
  const n = flujo.nodes.find(x => x.name === nombre);
  if (!n) throw new Error(`No encontré el nodo "${nombre}"`);
  return n;
}
// El prompt vive dentro de la expresión del nodo de Groq: se saca de ahí para comparar
// siempre contra el prompt que está realmente en producción.
function promptDelSistema() {
  const cuerpo = nodo('POST Groq: interpretar mensaje del cliente').parameters.jsonBody;
  const i = cuerpo.indexOf('"content":') + '"content":'.length;
  return JSON.parse(cuerpo.slice(i).trim().match(/^"(?:[^"\\]|\\.)*"/s)[0]);
}
function claveDelFlujo() {
  const m = JSON.stringify(nodo('Config CRM').parameters).match(/gsk_[A-Za-z0-9_-]+/);
  return m ? m[0] : null;
}

const SISTEMA = promptDelSistema();
const hoy = new Date();
const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];

function contexto(c) {
  return [
    `Hoy es ${hoy.toISOString().slice(0, 10)} (${DIAS[hoy.getDay()]})`,
    `Paso actual: ${c.paso}`,
    `Datos ya conocidos de la reserva en curso: ${c.datos}`,
    `Ya vio el catalogo: ${c.catalogo}`,
    `Ultimo mensaje del bot: ${JSON.stringify(c.ultimo_mensaje_bot)}`,
    `Historial reciente:\n${c.historial}`,
    `Mensaje del cliente: ${JSON.stringify(c.mensaje)}`,
  ].join('\n');
}

async function preguntar(destino, caso) {
  const [proveedor, ...resto] = destino.split(':');
  const modelo = resto.join(':');
  const p = PROVEEDORES[proveedor];
  if (!p) return { error: `proveedor desconocido: ${proveedor}` };
  const key = p.key();
  if (!key) return { error: `falta la API key de ${proveedor} (export ${proveedor.toUpperCase()}_API_KEY=...)` };

  const inicio = Date.now();
  try {
    const r = await fetch(p.url, {
      method: 'POST',
      headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: modelo, temperature: 0, response_format: { type: 'json_object' },
        messages: [{ role: 'system', content: SISTEMA }, { role: 'user', content: contexto(caso) }],
      }),
    });
    const cuerpo = await r.json();
    if (!r.ok) return { error: `HTTP ${r.status}: ${JSON.stringify(cuerpo).slice(0, 160)}` };
    const u = cuerpo.usage || {};
    const [pe, ps] = PRECIOS[modelo] || [0, 0];
    return {
      json: JSON.parse(cuerpo.choices[0].message.content),
      ms: Date.now() - inicio,
      tokens: `${u.prompt_tokens || '?'}+${u.completion_tokens || '?'}`,
      costo: (u.prompt_tokens || 0) * pe / 1e6 + (u.completion_tokens || 0) * ps / 1e6,
    };
  } catch (e) { return { error: e.message }; }
}

const INTERESANTES = ['personas', 'tipo_propuesta', 'nivel', 'fecha', 'tipo_rango', 'dia_semana_mencionado',
  'mes_mencionado', 'turno', 'menu_especial', 'medio_pago', 'solicita_info', 'confirma_fecha',
  'confirma_resumen', 'pregunta_aclaracion', 'requiere_humano', 'entendido'];

(async () => {
  const destinos = process.argv.slice(3).length ? process.argv.slice(3) : POR_DEFECTO;
  const resumen = {};
  for (const caso of CASOS) {
    console.log('\n' + '━'.repeat(100));
    console.log(`CASO: ${caso.nombre}`);
    console.log(`paso: ${caso.paso}  |  mensaje: ${JSON.stringify(caso.mensaje)}`);
    console.log(`se espera: ${JSON.stringify(caso.espera)}\n`);
    for (const destino of destinos) {
      const r = await preguntar(destino, caso);
      if (r.error) { console.log(`  ${destino.padEnd(32)} ERROR: ${r.error}`); continue; }
      const campos = INTERESANTES
        .filter(k => r.json[k] !== null && r.json[k] !== undefined && r.json[k] !== false && !(k === 'entendido' && r.json[k] === true))
        .map(k => `${k}=${JSON.stringify(r.json[k])}`).join('  ');
      console.log(`  ${destino.padEnd(32)} ${campos || '(todo null)'}`);
      console.log(`  ${''.padEnd(32)} ${r.ms} ms · ${r.tokens} tokens · US$ ${r.costo.toFixed(5)}`);
      const s = resumen[destino] || (resumen[destino] = { ms: 0, costo: 0, n: 0 });
      s.ms += r.ms; s.costo += r.costo; s.n++;
    }
  }
  console.log('\n' + '━'.repeat(100) + '\nPROMEDIOS');
  for (const [destino, s] of Object.entries(resumen)) {
    console.log(`  ${destino.padEnd(32)} ${Math.round(s.ms / s.n)} ms por respuesta · US$ ${(s.costo / s.n).toFixed(5)} por mensaje`
      + ` · US$ ${(s.costo / s.n * 20).toFixed(3)} por reserva`);
  }
  console.log('\nLas respuestas las juzgás vos: lo que importa es si el modelo entendió lo que la');
  console.log('persona quiso decir, no si el JSON es prolijo.');
})();
