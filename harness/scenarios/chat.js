// chat.js — superficie chat (spec 035, T024). POST /api/v1/chat/completions con JWT, JSON
// SIN streaming (verificado): una latencia por request (request/response completo).
import http from 'k6/http';
import { check } from 'k6';
import {
  API, MODEL_CHAT, pickIdentity, authHeaders, promptFor,
  recordLatency, recordRejection, saturatedRejection, phaseOf, metrics,
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
  const elapsed = Date.now() - t0;

  // Rechazo de admisión (C1): el backend está saturado y contesta 503 RÁPIDO. No es
  // latencia de servicio — si entrara en lat_chat hundiría los percentiles del gate. Se
  // cronometra en su propia Trend.
  if (saturatedRejection(res)) {
    metrics.saturated_rejections.add(1);
    recordRejection(phase, elapsed);
  } else {
    recordLatency('chat', phase, elapsed);
  }
  // Toda request de chat debe dejar fila de auditoría — TAMBIÉN la rechazada: el contrato
  // exige la fila durable ANTES de responder el 503, así que sigue contando para la
  // reconciliación.
  metrics.auditable_events.add(1);

  // Un bloqueo por PII (fail-closed) es un resultado LEGÍTIMO del examen, no un error del
  // guion: 4xx de política no invalida nada. Un 503 de admisión también es legítimo (el
  // producto se defiende); solo el 5xx SIN el header de rechazo es fallo del producto.
  check(res, {
    'chat sin 5xx (salvo saturación)': function (r) {
      return r.status < 500 || saturatedRejection(r);
    },
  });
}
