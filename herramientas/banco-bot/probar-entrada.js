#!/usr/bin/env node
// Prueba el nodo "juntar mensajes": el que decide, cuando el cliente escribe en varias tandas,
// cuál ejecución contesta y con qué texto. Si esto falla, el bot contesta de a tres o se calla.
//   node probar-entrada.js "<flujo .json>"
const { codigoDelFlujo } = require('./banco.js');
const cod = codigoDelFlujo(process.argv[2], 'juntar mensajes');
function correr(body, mensajes) {
  const hook = { body };
  const $ = (n) => ({ item: { json: n.includes('Webhook') ? hook : {} } });
  const $json = { mensajes };
  return new Function('$', '$json', cod)($, $json);
}
const M = (id, de, texto, tipo = 'texto') => ({ id, de, texto, tipo });
const CASOS = [
  ['mensaje único, soy el último',
   { phone: '1', message: 'hola', mensaje_id: 10 },
   [M(9, 'nosotros', '¿Qué día buscás?'), M(10, 'cliente', 'hola')],
   'pasa el mensaje solo', 'hola'],
  ['tres tandas, soy la PRIMERA → me callo',
   { phone: '1', message: 'hola', mensaje_id: 10 },
   [M(9, 'nosotros', '...'), M(10, 'cliente', 'hola'), M(11, 'cliente', 'queria saber'), M(12, 'cliente', 'para el sabado')],
   'no contesta: contesta la última', null],
  ['tres tandas, soy la ÚLTIMA → junto todo',
   { phone: '1', message: 'para el sabado', mensaje_id: 12 },
   [M(9, 'nosotros', '...'), M(10, 'cliente', 'hola'), M(11, 'cliente', 'queria saber'), M(12, 'cliente', 'para el sabado')],
   'junta las tres', 'hola\nqueria saber\npara el sabado'],
  ['sin mensaje_id (CRM viejo), comparo por texto',
   { phone: '1', message: 'para el sabado' },
   [M(9, 'nosotros', '...'), M(10, 'cliente', 'hola'), M(12, 'cliente', 'para el sabado')],
   'junta comparando por texto', 'hola\npara el sabado'],
  ['comprobante (foto) no se junta',
   { phone: '1', message: '', mensaje_id: 12 },
   [M(10, 'nosotros', 'Mandame el comprobante'), M(12, 'cliente', '', 'image')],
   'el comprobante pasa tal cual', ''],
  ['el CRM no responde (lista vacía)',
   { phone: '1', message: 'hola', mensaje_id: 10 }, [],
   'nunca deja sin respuesta', 'hola'],
];
let fallaron = 0;
for (const [nombre, body, mensajes, esperado, espera] of CASOS) {
  const r = correr(body, mensajes);
  const salida = r.length === 0 ? null : r[0].json.body.message;
  const bien = JSON.stringify(salida) === JSON.stringify(espera);
  if (!bien) fallaron++;
  console.log(`${bien ? 'ok    ' : 'FALLA '} ${nombre.padEnd(44)} → ${JSON.stringify(salida)}`);
  if (!bien) console.log(`         esperaba ${JSON.stringify(espera)} (${esperado})`);
}
console.log(`\n${CASOS.length - fallaron}/${CASOS.length} bien`);
process.exit(fallaron ? 1 : 0);
