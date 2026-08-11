// common.js — utilidades compartidas de los guiones k6 del harness ITV (spec 035, T024).
//
// Frontera: los guiones GENERAN la carga (modelo ABIERTO, research R1); el veredicto lo
// computa el evaluador Python del k6 summary + producto + stub (NUNCA de k6 en vivo). Este
// módulo no decide PASS/FAIL: solo mide y escribe el summary en el esquema que el evaluador
// consume (`basa-harness/k6-summary@1`).
//
// Modelo abierto: cada superficie corre como `constant-arrival-rate` (rate=N_s sobre
// timeUnit=cadencia_media). El threshold `dropped_iterations==0` (definido en gate.js) es la
// evidencia dura: si k6 no sostuvo la tasa, el run es inválido.
//
// Compatibilidad goja (motor JS de k6): se evitan `?.` y `??`; solo ES2015 + helpers.

import http from 'k6/http';
import exec from 'k6/execution';
import { SharedArray } from 'k6/data';
import { Trend, Counter } from 'k6/metrics';

// ── config del run (el orquestador la inyecta como JSON en GATE_CONFIG) ────────────────
export const CONFIG = JSON.parse(__ENV.GATE_CONFIG || '{}');
export const BASE_URL = CONFIG.base_url || __ENV.BASE_URL || 'http://localhost:8000';
export const API = BASE_URL + '/api/v1';

// Nombres de modelo/alias que el perfil itv-examen mapea al stub (openai/<alias>).
export const MODEL_CHAT = __ENV.MODEL_CHAT || 'chat';
export const MODEL_CODING = __ENV.MODEL_CODING || 'coding';

// ── pool de identidades (SharedArray: una copia compartida entre todas las VUs) ────────
export const identities = new SharedArray('identities', function () {
  const path = __ENV.POOL_FILE || CONFIG.pool_file || 'pool.json';
  return JSON.parse(open(path));
});

// ── corpus (canarios del run + docs PII deterministas) ─────────────────────────────────
const corpusBox = new SharedArray('corpus', function () {
  const path = __ENV.CORPUS_FILE || CONFIG.corpus_file || 'corpus.json';
  return [JSON.parse(open(path))]; // SharedArray exige array: envolvemos el objeto
});
export function corpusData() {
  return corpusBox.length ? corpusBox[0] : { canaries: [], docs: [] };
}

// ── pools filtrados por superficie (afinidad de identidad sin cerrar el modelo) ────────
function filterPool(pred) {
  const out = [];
  for (let i = 0; i < identities.length; i++) {
    if (pred(identities[i])) out.push(identities[i]);
  }
  return out.length ? out : identities;
}
const POOLS = {
  chat: filterPool(function (u) { return u.role === 'client'; }),
  extension: filterPool(function (u) { return u.client_type === 'desktop'; }),
  coding: filterPool(function (u) { return u.client_type === 'base_url'; }),
  admin: filterPool(function (u) {
    return u.role === 'tenant_admin' || u.role === 'compliance_officer';
  }),
  login: identities,
};

export function pickIdentity(surface) {
  const pool = POOLS[surface] || identities;
  if (!pool.length) throw new Error('pool de identidades vacío para ' + surface);
  // afinidad por iteración global del scenario: la sesión mantiene identidad.
  return pool[exec.scenario.iterationInTest % pool.length];
}

// ── fase del scenario actual (nombre `<superficie>__<fase>`, ver gate.js) ──────────────
export function phaseOf() {
  const name = exec.scenario.name || '';
  const parts = name.split('__');
  return parts.length > 1 ? parts[1] : 'sustained';
}

// ── métricas (globales por superficie + por fase, para el desglose 250/500) ────────────
const SURFACES = ['chat', 'extension', 'coding', 'admin', 'login'];

function phaseList() {
  const seen = {};
  const out = [];
  const scenarios = CONFIG.scenarios || [];
  for (let i = 0; i < scenarios.length; i++) {
    const ph = scenarios[i].phase || 'sustained';
    if (!seen[ph]) { seen[ph] = true; out.push(ph); }
  }
  return out.length ? out : ['sustained'];
}
export const PHASES = phaseList();

function buildMetrics() {
  const lat = {};
  const ttft = { global: new Trend('ttft_coding', true), phase: {} };
  // Cronómetro APARTE de los rechazos de admisión (C1): un 503 rápido no es latencia de
  // servicio y hundiría los percentiles de la superficie. Mismo patrón que lat_<superficie>.
  const rejection = { global: new Trend('lat_rejection', true), phase: {} };
  for (let s = 0; s < SURFACES.length; s++) {
    const name = SURFACES[s];
    lat[name] = { global: new Trend('lat_' + name, true), phase: {} };
    for (let p = 0; p < PHASES.length; p++) {
      lat[name].phase[PHASES[p]] = new Trend('lat_' + name + '__' + PHASES[p], true);
    }
  }
  for (let p = 0; p < PHASES.length; p++) {
    ttft.phase[PHASES[p]] = new Trend('ttft_coding__' + PHASES[p], true);
    rejection.phase[PHASES[p]] = new Trend('lat_rejection__' + PHASES[p], true);
  }
  return {
    lat: lat,
    ttft: ttft,
    rejection: rejection,
    stream_cuts: new Counter('coding_stream_cuts'),
    auditable_events: new Counter('auditable_events'),
    provoked_blocks: new Counter('provoked_blocks'),
    observed_blocks: new Counter('observed_blocks'),
    saturated_rejections: new Counter('saturated_rejections'),
    harness_errors: new Counter('harness_errors'),
  };
}
export const metrics = buildMetrics();

export function recordLatency(surface, phase, ms) {
  const slot = metrics.lat[surface];
  if (!slot) return;
  slot.global.add(ms);
  if (slot.phase[phase]) slot.phase[phase].add(ms);
}
export function recordTTFT(phase, ms) {
  metrics.ttft.global.add(ms);
  if (metrics.ttft.phase[phase]) metrics.ttft.phase[phase].add(ms);
}
export function recordRejection(phase, ms) {
  metrics.rejection.global.add(ms);
  if (metrics.rejection.phase[phase]) metrics.rejection.phase[phase].add(ms);
}

// ── rechazo de admisión por saturación (nodo C1 del core) ──────────────────────────────
// Contrato de wire SELLADO: TODO 503 de saturación lleva el header
// `X-Basa-Rejected: saturated`, en los dos caminos (chat del panel y /gw). Ese header ES
// la llave: un 503 SIN él NO es rechazo de admisión (puede ser Caddy o cualquier proxy de
// la sede) y NO debe contarse como tal. En chat el body además trae
// `code: "rejected_saturated"`, pero el body es EXTRA — acá no se parsea.
export function saturatedRejection(res) {
  if (!res || res.status !== 503) return false;
  const h = res.headers;
  if (!h) return false;   // xk6-sse devuelve {error} sin headers si la conexión ni abrió
  const v = h['X-Basa-Rejected'] || h['x-basa-rejected'];
  if (typeof v !== 'string') return false;
  // Comparación por TOKENS: si el header se escribe en dos capas (backend + un middleware
  // de la sede), Go los junta en un solo valor separado por ', ' ('saturated, saturated')
  // y una igualdad estricta lo daría por NO-rechazo — se perderían los 503 que sí lo son.
  const parts = v.split(',');
  for (let i = 0; i < parts.length; i++) {
    if (parts[i].trim().toLowerCase() === 'saturated') return true;
  }
  return false;
}

// ── autenticación por superficie ───────────────────────────────────────────────────────
// Cache de tokens POR VU (cada VU es un runtime aislado): evita re-loguear cada iteración.
const tokenCache = {};

export function loginToken(id) {
  if (tokenCache[id.username]) return tokenCache[id.username];
  const res = http.post(API + '/users/login',
    JSON.stringify({ username: id.username, password: id.password }),
    { headers: { 'Content-Type': 'application/json' }, tags: { op: 'login' } });
  if (res.status === 200) {
    const tok = res.json('access_token');
    tokenCache[id.username] = tok;
    return tok;
  }
  return null;
}

// chat/admin/login → JWT Bearer; extension/coding → X-Basa-Key (la Connection del seat).
export function authHeaders(id, surface) {
  if (surface === 'extension' || surface === 'coding') {
    if (!id.basa_key) return null; // el pool debe traer la key de la Connection (ver README)
    return { 'X-Basa-Key': id.basa_key };
  }
  const tok = loginToken(id);
  if (!tok) return null;
  return { Authorization: 'Bearer ' + tok };
}

// ── construcción de prompts (PII sintética + canarios del run) ──────────────────────────
// Un canario cada `canaryEvery` iteraciones: en un gate con masking ON no debe fugarse; en
// fault_injection (masking off) fuga y el stub lo caza (SLO c).
const CANARY_EVERY = parseInt(__ENV.CANARY_EVERY || '7', 10);

export function promptFor(surface) {
  const data = corpusData();
  const docs = data.docs || [];
  const iter = exec.scenario.iterationInTest;
  let text = docs.length ? docs[iter % docs.length].text : 'Consulta de prueba del harness.';
  const canaries = data.canaries || [];
  if (canaries.length && iter % CANARY_EVERY === 0) {
    const c = canaries[iter % canaries.length];
    text = text + ' ' + c.value; // se siembra el canario en claro en el tráfico
  }
  return text;
}

// ── construcción del summary (esquema que consume el evaluador) ─────────────────────────
function num(x, d) { return typeof x === 'number' ? x : d; }

function metricValues(data, name) {
  const m = data.metrics && data.metrics[name];
  return m && m.values ? m.values : null;
}

function pct(v) {
  if (!v) return { p50: 0, p95: 0, p99: 0, max: 0, count: 0 };
  return {
    p50: num(v['med'], num(v['p(50)'], 0)),
    p95: num(v['p(95)'], 0),
    p99: num(v['p(99)'], 0),
    max: num(v['max'], 0),
    count: num(v['count'], 0),
  };
}

function counterVal(data, name) {
  const v = metricValues(data, name);
  return v ? num(v['count'], 0) : 0;
}

function droppedFor(data, surface) {
  // suma de los submetrics dropped_iterations{scenario:<surface>__<fase>}.
  let total = 0;
  for (let p = 0; p < PHASES.length; p++) {
    const sub = 'dropped_iterations{scenario:' + surface + '__' + PHASES[p] + '}';
    total += counterVal(data, sub);
  }
  return total;
}

function surfaceEntry(data, surface, phase) {
  const metricBase = phase ? 'lat_' + surface + '__' + phase : 'lat_' + surface;
  const lat = pct(metricValues(data, metricBase));
  const entry = { latency_ms: lat, requests: lat.count, dropped_iterations: droppedFor(data, surface) };
  if (surface === 'coding') {
    const ttftName = phase ? 'ttft_coding__' + phase : 'ttft_coding';
    entry.ttft_ms = pct(metricValues(data, ttftName));
    entry.stream_cuts = counterVal(data, 'coding_stream_cuts');
  }
  return entry;
}

export function buildSummary(data) {
  const surfaces = {};
  for (let s = 0; s < SURFACES.length; s++) {
    surfaces[SURFACES[s]] = surfaceEntry(data, SURFACES[s], null);
  }
  const by_phase = {};
  for (let p = 0; p < PHASES.length; p++) {
    const ph = PHASES[p];
    const surf = {};
    for (let s = 0; s < SURFACES.length; s++) {
      surf[SURFACES[s]] = surfaceEntry(data, SURFACES[s], ph);
    }
    by_phase[ph] = {
      surfaces: surf,
      dropped_iterations_total: counterVal(data, 'dropped_iterations'),
      rejection_ms: pct(metricValues(data, 'lat_rejection__' + ph)),
    };
  }
  // `saturated_rejections` y `rejection_ms` son ADITIVOS: el esquema sigue siendo
  // `basa-harness/k6-summary@1` (un summary sin rechazos trae 0 y percentiles en 0).
  return {
    schema: 'basa-harness/k6-summary@1',
    gate: CONFIG.gate,
    version: CONFIG.version,
    surfaces: surfaces,
    by_phase: by_phase,
    dropped_iterations_total: counterVal(data, 'dropped_iterations'),
    auditable_events: counterVal(data, 'auditable_events'),
    provoked_blocks: counterVal(data, 'provoked_blocks'),
    observed_blocks: counterVal(data, 'observed_blocks'),
    saturated_rejections: counterVal(data, 'saturated_rejections'),
    rejection_ms: pct(metricValues(data, 'lat_rejection')),
    harness_errors: counterVal(data, 'harness_errors'),
  };
}
