// coding-sse.js — superficie coding tools (spec 035, T024). ÚNICA superficie SSE:
// POST /api/v1/gw/v1/messages con stream:true, vía xk6-sse (`k6/x/sse`). Mide TTFT (primer
// evento) y cortes (close/error a mitad). k6 core bufferea SSE y NO puede medir TTFT — por
// eso xk6-sse es imprescindible aquí (research R1); NO usar k6 v2.x (rompió xk6-sse).
import sse from 'k6/x/sse';
import {
  API, MODEL_CODING, pickIdentity, authHeaders, promptFor,
  recordLatency, recordTTFT, recordRejection, saturatedRejection, phaseOf, metrics,
} from './common.js';

export function coding() {
  const id = pickIdentity('coding');
  const headers = authHeaders(id, 'coding'); // { 'X-Basa-Key': ... } (byok/subscription)
  if (!headers) { metrics.harness_errors.add(1); return; }

  const phase = phaseOf();
  const payload = JSON.stringify({
    model: MODEL_CODING,
    stream: true,
    max_tokens: 256,
    messages: [{ role: 'user', content: promptFor('coding') }],
  });
  const params = {
    method: 'POST',
    body: payload,
    headers: Object.assign(
      { 'Content-Type': 'application/json', Accept: 'text/event-stream' }, headers),
    tags: { surface: 'coding', phase: phase },
  };

  const t0 = Date.now();
  let firstTokenAt = null;   // INSTANTE del primer evento (null = nunca hubo)
  let cut = false;
  let sawStop = false;

  // `sse.open` devuelve el HTTPResponse del intento: xk6-sse v0.1.12 expone `status` y
  // `headers` (struct HTTPResponse{url,status,headers,error}; su propio test
  // TestOpenWrongStatusCode afirma `res.status` sobre un 404). Por eso el rechazo de
  // admisión se clasifica acá igual que en chat, y no a ciegas.
  const res = sse.open(API + '/gw/v1/messages', params, function (client) {
    client.on('event', function (ev) {
      // Acá SOLO se captura el instante: el TTFT se emite después de clasificar la
      // respuesta. Emitirlo desde el handler contaminaría `ttft_coding` con los 503
      // saturados cuyo body se parsee como SSE (a sse.go v0.1.12 le basta una línea en
      // blanco para despachar un `event`): un rechazo de ~5 s entraría como «primer token
      // lentísimo» y hundiría el percentil de una superficie que ni llegó a servirse.
      if (!firstTokenAt) firstTokenAt = Date.now();
      // fin limpio del stream Anthropic: message_stop.
      if (ev && ev.name === 'message_stop') sawStop = true;
      if (ev && ev.name === 'error') cut = true;
    });
    client.on('error', function () { cut = true; });
  });

  const elapsed = Date.now() - t0;

  // Rechazo de admisión (C1): 503 con `X-Basa-Rejected: saturated`. El early-return va
  // ANTES de la lógica de cortes a propósito — un rechazo NO es un corte de stream: nunca
  // hubo stream que cortar, y contarlo como corte culparía al streaming de una defensa
  // que funcionó. La fila durable sí existe → sigue siendo evento auditable.
  if (saturatedRejection(res)) {
    metrics.saturated_rejections.add(1);
    recordRejection(phase, elapsed);
    metrics.auditable_events.add(1);
    return;                    // sin TTFT: no hubo primer token, hubo un no rápido
  }

  // Bloqueo del gateway. `/gw` escribe la fila durable ANTES de responder (gateway.py:
  // «Registrar → bloquear», FR-001) y sale por `_anthropic_error` con 400. xk6-sse NO
  // expone el cuerpo de la respuesta —sólo url/status/headers/error—, así que acá no se
  // puede leer el «[Basa Gateway]» que sí distingue chat. Lo que hace defendible tratar
  // ese 400 como bloqueo es la PRUEBA DE HUMO: el orquestador sirvió esta misma superficie
  // con este mismo cuerpo antes de abrir la ventana, así que un 400 en régimen no es un
  // pedido mal armado por nosotros. Sin el humo esto sería adivinar.
  // Un bloqueo NO es corte de stream (nunca hubo stream) ni emite TTFT.
  if (res && res.status === 400) {
    metrics.observed_blocks.add(1);
    metrics.provoked_blocks.add(1);
    metrics.auditable_events.add(1);
    return;
  }
  // El resto de los 4xx sí son fallo del instrumento: ruta cambiada, cuerpo desalineado,
  // key inválida. Invalidan el run en vez de contarse como examen (contrato del 12-ago).
  if (res && res.status >= 400 && res.status < 500) {
    metrics.harness_errors.add(1);
    return;
  }

  // Recién acá se sabe que la respuesta fue servicio y no rechazo: el TTFT es legítimo.
  if (firstTokenAt) { recordTTFT(phase, firstTokenAt - t0); }
  recordLatency('coding', phase, elapsed);
  metrics.auditable_events.add(1);
  // corte = error explícito, o el stream nunca abrió, o cerró sin message_stop.
  if (cut || !firstTokenAt || !sawStop) { metrics.stream_cuts.add(1); }
}
