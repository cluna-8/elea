# Tasks: Restauración de PII y atribución en respuestas byok (rutas bridged)

**Input**: Design documents from `/specs/024-unmask-bridged-routes/`
**Prerequisites**: plan.md ✓, research.md ✓ (D1-D5), data-model.md ✓, contracts/unmask-roundtrip.md ✓, quickstart.md ✓

**Organización**: TDD por user story — los tests de cada historia se escriben ANTES y se
ven fallar (RED) contra el código actual; la evidencia viva del spike es el baseline.
El MVP es la US1 sola (streaming = el camino de todas las coding tools).

## Phase 1: Setup

- [ ] T001 Verificar el entorno de evidencia vivo: stack dev arriba (backend :8091, motor
      :4010), Ollama con `qwen3:4b` y `OLLAMA_CONTEXT_LENGTH=32768`, virtual key byok del
      seed vigente (`specs/019-integration-surfaces/spikes-batch1.md`); reproducir el
      defecto con `quickstart.md` #1-#2 y dejar el output como baseline RED.

## Phase 2: Foundational (bloquea a todas las user stories)

- [ ] T002 **Evidencia de shapes (D2)**: instrumentación TEMPORAL de los post hooks en el
      stack dev para capturar (a) el tipo y estructura EXACTOS de los items del stream
      bridged (campos de deltas de texto/razonamiento/tools) y (b) el shape completo de la
      respuesta no-streaming dict. Registrar lo observado como apéndice en `research.md` y
      REVERTIR la instrumentación (patrón del spike: evidencia antes que código).
- [ ] T003 [P] **Tests RED de los tres root causes** en
      `backend/tests/unit/test_unmask_shapes.py` (importando las extensiones como hace
      `tests/contract/test_route_parity.py`): (1) `_unmask_response_inplace` con respuesta
      dict raíz shape-Anthropic → hoy no restaura; (2) iterator hook con items parseados
      (shapes de T002 fabricados) → hoy los cede tal cual; (3) extracción de identidad del
      audit logger con metadata en `litellm_metadata` → hoy devuelve vacío. Los tres DEBEN
      fallar contra el código actual (RED verificado y anotado).

**Checkpoint**: shapes documentados + RED suite en rojo por las razones correctas.

## Phase 3: User Story 1 — Restauración en streaming (P1) 🎯 MVP

- [ ] T004 [US1] Si el rewrite por campo lo requiere, helper en
      `litellm/extensions/basa_guardian_policy.py` que aplique el carry-split compartido a
      un valor de campo suelto (mismo estado carry/carry_field que `rewrite_sse_block`);
      unit del helper junto a los existentes de la lib.
- [ ] T005 [US1] Adaptador de items parseados en
      `litellm/extensions/basa_guardrail.py::async_post_call_streaming_iterator_hook`:
      para items no-bytes con shape conocido (T002), restaurar los campos de deltas de
      texto/razonamiento/fragmentos de tools con el carry compartido y re-emitir el item
      mutado; shape desconocido → passthrough intacto (contrato #7, FR-005). La ruta
      bytes/SSE existente (passthrough) no se toca.
- [ ] T006 [US1] Tests unit de streaming en VERDE: placeholder entero en un item,
      partido entre dos items, multibyte partido, stream truncado con carry pendiente,
      múltiples placeholders en un item, item de shape desconocido intacto
      (contrato #4-#7).
- [ ] T007 [US1] Verificación viva (quickstart #2 y #3): el email vuelve en claro en los
      deltas Y el modelo sigue viendo solo el placeholder (SC-003, no-regresión de ida).
      Evidencia anotada en quickstart o en el PR.

**Checkpoint**: US1 entregable sola — Claude Code/modelo propio sin placeholders en streaming.

## Phase 4: User Story 2 — Round-trip no-streaming (P2)

- [ ] T008 [US2] `_unmask_response_inplace` acepta respuesta **dict raíz** (D1):
      `content` lista shape-Anthropic y `choices` shape-OpenAI leídos con get/setitem,
      manteniendo intacta la rama de objetos con atributos (contrato #1-#3).
- [ ] T009 [US2] Tests unit no-streaming en VERDE: dict-Anthropic con text/thinking/
      tool-input, dict-OpenAI con choices, objeto actual (no-regresión), respuesta sin
      placeholders intacta, sin mapping → tal cual (FR-005).
- [ ] T010 [US2] Verificación viva (quickstart #1): respuesta JSON con el valor original;
      diff contra el baseline RED de T001.

## Phase 5: User Story 3 — Atribución en el monitor (P3)

- [ ] T011 [US3] `litellm/extensions/basa_audit_logger.py`: la identidad
      (`user_api_key_metadata`) se busca en AMBOS metadata-homes con el mismo patrón que
      el archivo ya usa para `basa_masked_entities` (D3); el scrub de `pii_tokens` se
      re-asserta sin cambios (contrato #9).
- [ ] T012 [US3] Test unit del logger con metadata en `litellm_metadata` (VERDE) +
      verificación viva (quickstart #4): evento con `tool/client/tenant` no-nulos y
      conteo de entidades cuando hubo masking.

## Phase 6: Evidencia e2e + Polish

- [ ] T013 **e2e contra motor vivo (FR-007)** en
      `backend/tests/e2e/test_engine_roundtrip_e2e.py`, convención de
      `test_gateway_routing_e2e.py` (stack vivo, jamás verde por simulación): byok
      streaming y no-streaming con PII → valor original al cliente + evento con identidad
      y entidades; documentado como el assert que faltaba cuando el defecto llegó a la
      matriz (SC-006).
- [ ] T014 Gate completo: `make -C deploy check` + suite backend entera
      (`docker compose run --rm --no-deps backend pytest tests/ -q`) verdes.
- [ ] T015 [P] **Sitio de docs de producto (OBLIGATORIO, DoD)**: actualizar las páginas de
      `docs/docs/**` que esta feature toca — G9 pasa a gotcha resuelto (histórico con la
      versión), §3.5 y §1 de integraciones pierden el caveat, la matriz refleja las
      promociones — con curado marca-neutro, template de docs/README.md y leyenda
      🟢/🟡/🔵 honesta; correr `make -C deploy check-docs`.
- [ ] T016 [P] **Registro 019 (FR-009)**: promover en
      `specs/019-integration-surfaces/compatibility.md` las filas cuyo único freno era el
      unmask (Ollama upstream, Claude Code → modelo propio, Aider) de PARCIAL a FUNCIONA
      con la evidencia nueva; actualizar `spikes-batch1.md` (Spike 1 veredicto) y cerrar
      el issue #27 desde el PR.
- [ ] T017 Review adversarial del branch (ultracode) + PR con review pedida a @cluna-8
      (superficie compartida `litellm/`, frontera con seguridad) y merge solo con OK de JF.

## Dependencies & Execution Order

- **Phase 2 → todo lo demás**: T002 (shapes) bloquea T005; T003 (RED) bloquea T005/T008/T011.
- **US1 (P3) / US2 (P4) / US3 (P5) son independientes entre sí** tras Phase 2 — el orden
  P1→P2→P3 es de prioridad, no técnico; T011 puede ir en paralelo con T005/T008.
- **Phase 6 exige US1+US2+US3** (el e2e asserta las tres).
- [P] = paralelizable dentro de su fase.

## Notas de implementación

- Principio VI: NADA fuera de `litellm/extensions/` en el motor; el gateway no se toca.
- FR-003/contrato #5: el framing SSE del cliente lo produce el motor aguas abajo del
  hook — el adaptador muta SOLO contenido textual de los items, jamás su estructura.
- La suite corre en el contenedor backend (los unit importan las extensiones por path
  compartido, patrón de `tests/contract/`).
