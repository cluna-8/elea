// gate.js — guion PRINCIPAL de k6 (spec 035, T024). El orquestador Python invoca:
//
//   k6 run --env GATE_CONFIG='<json>' --env POOL_FILE=pool.json \
//          --env CORPUS_FILE=corpus.json --env SUMMARY_FILE=summary.json gate.js
//
// GATE_CONFIG trae los scenarios ya calculados por el gate (surface_arrival_rates de R1);
// k6 SOLO los ejecuta — el math del modelo abierto vive en Python. Cada (superficie, fase)
// es un `constant-arrival-rate` (rate=N_s, timeUnit=cadencia_media). El threshold
// `dropped_iterations==0` es la evidencia dura de modelo abierto: si k6 no sostuvo la tasa,
// el run es inválido (lo sella el evaluador).
import { CONFIG, buildSummary } from './common.js';

// Re-export de las funciones exec (k6 resuelve `exec: '<nombre>'` contra el módulo raíz).
export { chat } from './chat.js';
export { extension } from './extension.js';
export { coding } from './coding-sse.js';
export { admin } from './admin.js';
export { login } from './login_storm.js';

// Percentiles que el summary necesita (p50=med, p95, p99, max) — deben pedirse acá o k6 no
// los calcula.
const TREND_STATS = ['avg', 'min', 'med', 'p(50)', 'p(95)', 'p(99)', 'max', 'count'];

function buildOptions() {
  const scenarios = {};
  const thresholds = {};
  const list = CONFIG.scenarios || [];
  for (let i = 0; i < list.length; i++) {
    const sc = list[i];
    const name = sc.surface + '__' + sc.phase; // separador `__` que lee phaseOf()
    const def = {
      executor: sc.executor || 'constant-arrival-rate',
      exec: sc.exec,
      rate: sc.rate,
      timeUnit: sc.timeUnit,
      duration: sc.duration,
      preAllocatedVUs: sc.preAllocatedVUs || Math.max(10, sc.rate * 2),
      maxVUs: sc.maxVUs || Math.max(20, sc.rate * 6),
      startTime: sc.startTime || '0s',
      // Sin esto k6 usa 30 s y CORTA las iteraciones en vuelo al terminar la fase: un
      // stream más largo que ese margen deja al guion sin contar su evento mientras el
      // producto ya escribió la fila, y la reconciliación reporta «sobran filas» sin que
      // se haya perdido nada (visto en el drill del 12-ago: +15). El margen lo calcula el
      // orquestador desde la duración máxima de stream del gate.
      gracefulStop: sc.gracefulStop || '30s',
      tags: { surface: sc.surface, phase: sc.phase },
    };
    scenarios[name] = def;
    // evidencia de modelo abierto por scenario: k6 no debe descartar iteraciones.
    thresholds['dropped_iterations{scenario:' + name + '}'] = ['count==0'];
  }
  // threshold global (además de los por-scenario): red de seguridad del modelo abierto.
  thresholds['dropped_iterations'] = ['count==0'];
  return { scenarios: scenarios, thresholds: thresholds, summaryTrendStats: TREND_STATS };
}

export const options = buildOptions();

// El summary en el esquema del evaluador (`sentinel-harness/k6-summary@1`) — fuente del
// veredicto junto al producto y el stub (NUNCA la observabilidad, R3).
export function handleSummary(data) {
  const summary = buildSummary(data);
  const file = __ENV.SUMMARY_FILE || CONFIG.summary_file || 'summary.json';
  const out = {};
  out[file] = JSON.stringify(summary, null, 2);
  out['stdout'] = '\nharness: summary escrito en ' + file + '\n';
  return out;
}
