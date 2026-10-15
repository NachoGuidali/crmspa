#!/usr/bin/env node
// Corre todos los casos contra un flujo exportado de n8n.
//   node probar.js "../../../Bot WhatsApp - nuevo flujo nacho (v2 revisado).json"
const { codigoDelFlujo, correr } = require('./banco.js');
const CASOS = require('./casos.js');

const ruta = process.argv[2];
if (!ruta) { console.error('Uso: node probar.js <flujo exportado de n8n .json>'); process.exit(2); }
const codigo = codigoDelFlujo(ruta);

let fallaron = 0;
for (const caso of CASOS) {
  let salida;
  try { salida = correr(codigo, caso); }
  catch (e) { console.log(`FALLA  ${caso.nombre}\n         explotó: ${e.message}`); fallaron++; continue; }

  const errores = [];
  for (const [campo, esperado] of Object.entries(caso.espera || {})) {
    const real = salida[campo];
    if (JSON.stringify(real) !== JSON.stringify(esperado)) {
      errores.push(`${campo}: esperaba ${JSON.stringify(esperado)}, devolvió ${JSON.stringify(real)}`);
    }
  }
  if (caso.tieneQueRepreguntar && !salida.pregunta_aclaracion) {
    errores.push('tenía que repreguntar y no lo hizo');
  }
  if (errores.length) { fallaron++; console.log(`FALLA  ${caso.nombre}\n         ` + errores.join('\n         ')); }
  else console.log(`ok     ${caso.nombre}`);
}
console.log(`\n${CASOS.length - fallaron}/${CASOS.length} bien${fallaron ? `, ${fallaron} para revisar` : ''}`);
process.exit(fallaron ? 1 : 0);
