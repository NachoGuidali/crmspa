#!/usr/bin/env node
// Compara dos versiones del flujo con los mismos casos y muestra SOLO lo que cambia.
// Sirve antes de importar una versión nueva: lo que cambió tiene que ser lo que quisiste cambiar.
//   node comparar.js "flujo-viejo.json" "flujo-nuevo.json"
const { codigoDelFlujo, correr } = require('./banco.js');
const CASOS = require('./casos.js');

const [, , viejo, nuevo] = process.argv;
if (!nuevo) { console.error('Uso: node comparar.js <flujo viejo .json> <flujo nuevo .json>'); process.exit(2); }
const codA = codigoDelFlujo(viejo), codB = codigoDelFlujo(nuevo);

const CAMPOS = ['personas', 'tipo_propuesta', 'nivel', 'fecha_solicitada', 'turno_pedido',
  'menu_especial', 'medio_pago', 'nombre_cliente', 'telefono_cliente', 'email_cliente',
  'solicita_info', 'entendido', 'requiere_humano', 'confirma_fecha', 'confirma_resumen',
  'pregunta_aclaracion', 'fallback_dias_por_no_entendido', 'fallos_consecutivos', 'rearmar_resumen'];

let distintos = 0;
for (const caso of CASOS) {
  const a = (() => { try { return correr(codA, caso); } catch (e) { return { ERROR: e.message }; } })();
  const b = (() => { try { return correr(codB, caso); } catch (e) { return { ERROR: e.message }; } })();
  const cambios = CAMPOS.filter(c => JSON.stringify(a[c] ?? null) !== JSON.stringify(b[c] ?? null))
    .map(c => `${c}: ${JSON.stringify(a[c] ?? null)} → ${JSON.stringify(b[c] ?? null)}`);
  if (cambios.length) { distintos++; console.log(`\n${caso.nombre}\n   ` + cambios.join('\n   ')); }
}
console.log(`\n${distintos} caso(s) con diferencias de ${CASOS.length}`);
