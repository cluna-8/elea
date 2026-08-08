// chat.js — superficie chat (spec 035, T024). POST /api/v1/chat/completions con JWT, JSON
// SIN streaming (verificado): una latencia por request (request/response completo).
import http from 'k6/http';
import { check } from 'k6';
import {
  API, MODEL_CHAT, pickIdentity, authHeaders, promptFor,
  recordLatency, phaseOf, metrics,
} from './common.js';

export function chat() {
  const id = pickIdentity('chat');
  const headers = authHeaders(id, 'chat');
  if (!headers) { metrics.harness_errors.add(1); return; }

  const body = JSON.stringify({
    model: MODEL_CHAT,
    stream: false,
    messages: [{ role: 'user', content: promptFor('chat') }],
  });
  const phase = phaseOf();
  const t0 = Date.now();
  const res = http.post(API + '/chat/completions', body, {
    headers: Object.assign({ 'Content-Type': 'application/json' }, headers),
    tags: { surface: 'chat', phase: phase },
  });
  recordLatency('chat', phase, Date.now() - t0);
  metrics.auditable_events.add(1); // toda request de chat debe dejar fila de auditoría

  // Un bloqueo por PII (fail-closed) es un resultado LEGÍTIMO del examen, no un error del
  // guion: 4xx de política no invalida nada. Solo 5xx sería un fallo del producto.
  check(res, { 'chat sin 5xx': function (r) { return r.status < 500; } });
}
