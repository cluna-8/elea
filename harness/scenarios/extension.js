// extension.js — superficie extensión navegador (spec 035, T024).
// GET /api/v1/gw/whoami (login del popup) + POST /api/v1/gw/inspect (aplica política),
// autenticadas con X-Basa-Key (la Connection del seat, tool_type=desktop).
import http from 'k6/http';
import { check } from 'k6';
import {
  API, pickIdentity, authHeaders, promptFor, recordLatency, phaseOf, metrics,
} from './common.js';

export function extension() {
  const id = pickIdentity('extension');
  const headers = authHeaders(id, 'extension'); // { 'X-Basa-Key': ... }
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

  check(who, { 'whoami sin 5xx': function (r) { return r.status < 500; } });
  check(ins, { 'inspect sin 5xx': function (r) { return r.status < 500; } });
}
