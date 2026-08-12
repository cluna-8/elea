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
    // El contrato C1 exige la fila durable ANTES del 503 → sigue siendo auditable.
    metrics.auditable_events.add(1);
  } else if (res.status === 402) {
    // Presupuesto agotado (cohorte 402 del gate): HOY el producto responde SIN escribir
    // fila de auditoría (chat.py hace raise antes de auditar — issue #157). NO es evento
    // auditable ni latencia de servicio: se cuenta en su propio Counter y la cifra queda
    // en reconciliation.json. El día que el backend escriba fila para el 402, la paridad
    // saldrá con «sobran filas» y se verá — ajustar el guion en ese mismo ciclo.
    metrics.budget_402.add(1);
  } else {
    recordLatency('chat', phase, elapsed);
    // Toda request servida o bloqueada por política deja fila de auditoría.
    metrics.auditable_events.add(1);
  }

  // Un bloqueo por PII (fail-closed) es un resultado LEGÍTIMO del examen, no un error del
  // guion: 4xx de política no invalida nada. Un 503 de admisión también es legítimo (el
  // producto se defiende); solo el 5xx SIN el header de rechazo es fallo del producto.
  check(res, {
    'chat sin 5xx (salvo saturación)': function (r) {
      return r.status < 500 || saturatedRejection(r);
    },
  });
}
