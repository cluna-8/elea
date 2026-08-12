// chat.js — superficie chat (spec 035, T024). POST /api/v1/chat/completions con JWT, JSON
// SIN streaming (verificado): una latencia por request (request/response completo).
//
// OJO con el WIRE (cazado en el examen del 12-ago, run 20260812-g125-01): el path se llama
// `/chat/completions` pero el cuerpo NO es el de OpenAI. `ChatRequest` (backend/src/api/
// chat.py) es `{message: str, model: str}` — `message` SINGULAR y string plano, no una
// lista `messages`. Un cuerpo estilo OpenAI devuelve 422 ANTES de cualquier auditoría, así
// que el 60% del tráfico del gate desaparecía sin dejar fila. Y `model` tiene que ser un
// alias REAL del catálogo del motor (`model_list` del config.yaml del perfil): un alias
// inexistente devuelve 400 «El modelo solicitado no está disponible en el gateway».
import http from 'k6/http';
import { check } from 'k6';
import {
  API, MODEL_CHAT, pickIdentity, authHeaders, promptFor,
  recordLatency, recordRejection, saturatedRejection, policyBlock, phaseOf, metrics,
} from './common.js';

export function chat() {
  const id = pickIdentity('chat');
  const headers = authHeaders(id, 'chat');
  if (!headers) { metrics.harness_errors.add(1); return; }

  const body = JSON.stringify({ model: MODEL_CHAT, message: promptFor('chat') });
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
    // Presupuesto agotado (cohorte 402 del gate): post-#177 (463801d) el producto escribe
    // fila durable `compliance_status='rejected_budget'` ANTES de responder el 402 en el
    // PLANO CHAT (el plano motor —coding tools/byok vía custom_auth— sigue sin fila,
    // issue #176), así que ES evento auditable y entra en la paridad. NO es latencia de
    // servicio —igual que el 503 saturado, un «no» barato hundiría los percentiles—, así
    // que no va a recordLatency. `budget_402` se mantiene como conteo de la cohorte: es la
    // evidencia del tamaño del grupo y lo que hace reconciliable el balde rejected_budget
    // del producto contra lo que vio el guion.
    metrics.budget_402.add(1);
    metrics.auditable_events.add(1);
  } else if (policyBlock(res)) {
    // Bloqueo de política (PII prohibida, clave privada, o fail-closed del NLP): es un
    // RESULTADO legítimo del examen y deja fila durable — cuenta como evento auditable y
    // como bloqueo provocado, que es lo que hace verificable el SLO (d). Sin esto, el
    // producto bloqueaba y el guion no se enteraba: el 12-ago el reconcile abortó con 60
    // filas `blocked%` y 0 bloqueos declarados.
    metrics.observed_blocks.add(1);
    metrics.provoked_blocks.add(1);
    metrics.auditable_events.add(1);
    recordLatency('chat', phase, elapsed);
  } else if (res.status === 400 || res.status === 404 || res.status === 422) {
    // El pedido NO llegó a la lógica del producto: cuerpo mal formado, alias de modelo
    // inexistente, ruta equivocada. Es un fallo del INSTRUMENTO (o de su configuración),
    // no un resultado del examen — y es exactamente el que se coló el 12-ago: 422 en masa
    // por un cuerpo estilo OpenAI, contado como "auditable" y sin fila del lado del
    // producto. Cuenta como harness_error, que INVALIDA el run: es preferible no tener
    // veredicto a tener uno que midió 3 superficies creyendo que midió 4.
    metrics.harness_errors.add(1);
  } else {
    recordLatency('chat', phase, elapsed);
    // Toda request servida o bloqueada por política deja fila de auditoría.
    metrics.auditable_events.add(1);
  }

  // Un bloqueo por PII (fail-closed) es un resultado LEGÍTIMO del examen, no un error del
  // guion: 4xx de política no invalida nada. Un 503 de admisión también es legítimo (el
  // producto se defiende); solo el 5xx SIN el header de rechazo es fallo del producto.
  // El 4xx de "ni llegué a la lógica" (400/404/422) se chequea aparte: sin esto, un guion
  // desalineado con el wire aprobaba el examen sin haber ejercitado la superficie.
  check(res, {
    'chat sin 5xx (salvo saturación)': function (r) {
      return r.status < 500 || saturatedRejection(r);
    },
    'chat llegó a la lógica del producto (no 400/404/422)': function (r) {
      return r.status !== 400 && r.status !== 404 && r.status !== 422;
    },
  });
}
