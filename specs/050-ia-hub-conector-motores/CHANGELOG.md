# CHANGELOG — spec 050 (IA Hub: Hub conector + motores)

## 13-sep-2026 — Cambio en Guardian: restitución de placeholders en streaming de la API OpenAI

**Fuera del alcance original de la 050 ("NO toca `litellm/`"), aprobado explícitamente por el
dueño el 13-sep tras el diagnóstico.**

- **Síntoma real (hito 4, Presenton):** las diapositivas generadas traían `[PERSON / 0 / 66a5]`
  en vez de "OTC"/"FASON" (términos que el NLP tomó por nombres de persona).
- **Causa raíz, verificada con la llave `svc.presenton` directo contra `engine:4000`:** sin
  streaming, texto, JSON (`response_format`) y tool calls volvían restituidos; **con
  `stream: true` los tres volvían con placeholders**. El hook
  `async_post_call_streaming_iterator_hook` de `litellm/extensions/sentinel_guardrail.py` solo
  reescribía frames SSE crudos (ruta `/v1/messages` de Anthropic); los chunks de
  `/v1/chat/completions` llegan como objetos `ModelResponseStream` y caían en la rama "objeto ya
  parseado: se entrega tal cual". Presenton usa streaming y no permite apagarlo.
- **Arreglo:** `sentinel_guardian_policy.unmask_openai_chunk()` + `flush_openai_carries()`
  (reutilizan `unmask_text` y `safe_split`; carry por choice y por tool call para placeholders
  partidos entre deltas; el carry pendiente se vuelca en el chunk con `finish_reason` o en un
  chunk extra si el stream se trunca). El hook aplica esto a la rama de objetos/dicts. La ruta
  SSE de Anthropic no cambia.
- **Pruebas:** `backend/tests/unit/test_unmask_openai_stream_050.py` (9 casos: entero, partido,
  partido en el corchete, tool call, dict, sin placeholders, truncado, finish con carry, hook
  completo). Suite de unmask/guardrail existente: 345 verdes, la única falla es la regional
  preexistente. En vivo: los tres modos de streaming restituidos; presentación regenerada sin
  tokens y con los valores reales.
- **Segundo caso (13-sep, hito 5):** con `response_format` JSON por streaming, restituir un
  original con salto de línea o comillas dentro de la cadena JSON rompía el parseo del cliente
  (Presenton: "Invalid control character at: line 1 column 67"). Ahora, si la petición pidió
  JSON (`request_wants_json`) o se trata de `arguments` de un tool call, el original se
  restituye escapado como contenido de cadena JSON (`json_string_map`). Texto plano no cambia.
  4 tests más (30 en total en el archivo).
- **Alcance no cubierto:** la bóveda (placeholders ecoados de requests pasados) sigue aplicando
  solo al camino no-streaming, igual que antes.

## 13-sep-2026 — Hito 5: encadenado y plantillas modelo

- `POST /api/handoff`: respuesta + pregunta a un espacio de planillas → presentación. Si la
  consulta a planillas falla, no se genera nada y se avisa (FR-014). Probado real: investigación
  del chat + "ventas por unidad de negocio 2025" → PPTX de 6 slides con plantilla `executive`,
  43 s, sin tokens.
- Plantillas modelo (pedido del dueño): `GET /api/presentations/templates` lista las integradas
  de Presenton y las propias del cliente (primero); `template` en generate y handoff; selector
  en el modal. Crear plantillas propias desde el PPTX corporativo queda pendiente (acción admin).
- Flags por motor ausente verificados con test (Hub solo con Guardian).

## 12-sep-2026 — Hitos 1 a 4 (ver memoria del proyecto y `git log` de la rama)

- Hito 1: enmascarado eliminado del Hub; DB-GPT retirado; FR-041 (`kind` al crear espacio).
- Hito 2: motor `tabular/` (DuckDB) con alias `tN`, detección de encabezado real, modelo
  `azure-gpt-5.4-mini` (5/5 con planillas reales de Elea vs 3/5 de 4o-mini).
- Hito 3: Hub `/api/tabular/*`, `/api/features`, UI de planillas igual al chat.
- Hito 4: Presenton v0.9.7-beta (puerto 80, `DISABLE_AUTH=true`), `/api/presentations/generate`,
  artefactos por persona, botón "Crear presentación", panel "Mis archivos".
