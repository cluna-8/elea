// extension.js — superficie extensión navegador (spec 035, T024).
// GET /api/v1/gw/whoami (login del popup) + POST /api/v1/gw/inspect (aplica política),
// autenticadas con X-Sentinel-Key (la Connection del seat, tool_type=desktop).
import http from 'k6/http';
import { check } from 'k6';
import {
  API, pickIdentity, authHeaders, promptFor, recordLatency, phaseOf, metrics,
} from './common.js';

export function extension() {
  const id = pickIdentity('extension');
  const headers = authHeaders(id, 'extension'); // { 'X-Sentinel-Key': ... }
  if (!headers) { metrics.harness_errors.add(1); return; }

  const phase = phaseOf();
  const t0 = Date.now();

  // 1) whoami: valida la key → identidad (fail-closed sin key válida).
  const who = http.get(API + '/gw/whoami', {
    headers: headers, tags: { surface: 'extension', op: 'whoami', phase: phase },
  });

  // 2) inspect: enmascara el texto del navegador (piso completo desde la 027) y audita.
  const body = JSON.stringify({ text: promptFor('extension'), tool: 'chatgpt' });
  const ins = http.post(API + '/gw/inspect', body, {
    headers: Object.assign({ 'Content-Type': 'application/json' }, headers),
    tags: { surface: 'extension', op: 'inspect', phase: phase },
  });

  recordLatency('extension', phase, Date.now() - t0);
  metrics.auditable_events.add(1); // inspect empuja al monitor + audita

  // `/gw/inspect` sí trae marcador limpio: `blocked` booleano en el cuerpo (200). Un
  // bloqueo deja fila durable, así que cuenta para el SLO (d) — sin esto el producto
  // bloqueaba y el guion no lo declaraba (el reconcile del 12-ago abortó por eso).
  // El `catch` NO puede tragarse el error: un cuerpo ilegible significa que no sabemos si
  // el producto bloqueó, y "no sé" jamás debe leerse como "no bloqueó" (el gate ciego del
  // core cazó justo eso). Se cuenta como harness_error, que invalida el run.
  let bloqueado = null;
  try {
    const v = ins.json('blocked');
    if (v === true || v === false) bloqueado = v;
  } catch (e) { bloqueado = null; }
  if (bloqueado === null) {
    metrics.harness_errors.add(1);
  } else if (bloqueado) {
    metrics.observed_blocks.add(1);
    metrics.provoked_blocks.add(1);
  }
  // Los 4xx de inspect son fallo del instrumento (key inválida, cuerpo desalineado): el
  // bloqueo de política viaja como 200 con `blocked: true`, no como 4xx.
  if (ins.status >= 400 && ins.status < 500) { metrics.harness_errors.add(1); }
  if (who.status >= 400 && who.status < 500) { metrics.harness_errors.add(1); }

  check(who, { 'whoami sin 5xx': function (r) { return r.status < 500; } });
  check(ins, { 'inspect sin 5xx': function (r) { return r.status < 500; } });
}
