# Tasks: Auto-router semántico + rediseño «Modelos & Ollama»

**Input**: Design documents from `/specs/030-semantic-auto-router/`

**Prerequisites**: plan.md, spec.md, research.md (R1-R9), data-model.md, contracts/router-config-api.md, quickstart.md

**Tests**: incluidos (la spec exige SC verificables y el pipeline de chat es crítico).

**Organization**: por user story; cada fase es entregable e independientemente testeable.
Deadline real: demo en sede el JUEVES 30-jul → MVP = Fase 3 (US1) demostrable por API/registro.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable (ficheros distintos, sin dependencia entre sí)
- Paths absolutos desde la raíz del repo

## Phase 1: Setup (catálogo + seeds)

- [x] T001 Motor: entrada `router-embeddings` → `ollama/qwen3-embedding:0.6b` en
      `litellm/config.yaml` (dev). **CHECKPOINT R1 (bloqueante, antes de nada más)**:
      `curl {motor}/v1/embeddings` end-to-end per quickstart.md; si la ruta `ollama/*`
      falla, aplicar plan B (alias openai-compatible `http://host:11434/v1`) y documentar
      en research.md. Verificar también que `router-embeddings` NO aparece como modelo
      conversable en `GET /chat/models` (si aparece, filtrarlo en T007).
- [x] T002 [P] Seeds: `litellm/auto_router.json` (dev — 3 rutas schema data-model.md §1,
      target_model desacoplado, default local) ·
      `deploy/clients/camara-comercio/auto_router.json` (piloto, default=local del perfil) ·
      `deploy/clients/camara-comercio/config.yaml.tmpl` (+`router-embeddings`,
      +`router_settings` base: disable_cooldowns/num_retries 2/timeout 30) ·
      `deploy/release/populate_volumes.sh` copia `auto_router.json` al volumen
      `litellm_config` (chown ya cubierto).

## Phase 2: Foundational (bloquea todas las US)

- [x] T003 `backend/src/services/auto_router_service.py` — port adaptado de
      llm-guardian per research R2/R4/R5 y data-model §1-2: `load_config()` con helper de
      path (patrón `_get_config_path`), `route(message) -> RoutingDecision` (switch OFF =
      cero embeds + reason switch_off; best-of con umbral por ruta; empate = primera
      declarada; below_threshold → default no-degraded; timeout/config/target_missing →
      default degraded con reason), cache Redis `autoroute:emb:*` versión `v3-local-qwen`,
      SIN ascii-fold, timeout de `timeout_seconds`. Más método `embeddings(model, inputs)`
      en `backend/src/services/ai_engine_client.py` (patrón `test_guardrail:303-321`).
- [x] T004 [P] Unit tests `backend/tests/unit/test_auto_router_service.py`: switch OFF sin
      llamadas (mock cuenta invocaciones), best-of y empate determinista, below_threshold,
      timeout→degraded, config corrupta→degraded, target ausente→degraded, cache hit no
      re-embebe, truncado a 500 chars.
- [x] T005 Migración `backend/alembic/versions/013_auto_router_decision.py` (columna
      `routing_decision` JSONB nullable, down_revision = revision de la 012) + columna en
      `backend/src/models/audit.py` + param keyword-only `routing_decision=None` en
      `backend/src/services/audit_service.py::log_transaction`. **Gate**: tests de
      licensing/hash-chain existentes siguen verdes (la columna queda FUERA de la cadena).

**Checkpoint**: servicio ruteando en unit tests + migración aplicando sobre DB fresca.

## Phase 3: User Story 1 — «Auto» en el chat (P1) 🎯 MVP

**Goal**: consulta con model="auto" → premium/económico/local según contenido; decisión
visible en Debugger + vitrina + auditoría; degradación jamás silenciosa.

**Independent Test**: quickstart §"Probar la decisión" — 3 prompts → 3 destinos; benchmark
9 queries ≥8; embed caído → 200 por default con degraded registrado.

- [x] T006 [US1] `backend/src/api/chat.py`: si `request.model == "auto"` → decisión al
      PRINCIPIO del endpoint (research R2); el modelo efectivo fluye por el pipeline
      entero como si el usuario lo hubiera elegido (FR-010, el guardián sensitive_routing
      de :739 conserva prioridad posterior); coste y presupuesto sobre el modelo que
      CONTESTÓ (R7: calculate_cost :1066 y update_budget :1182 — solo camino auto);
      `pipeline_metadata.layer_llm.auto_router` = decisión (ausente si no-auto);
      `log_transaction(routing_decision=...)`; auditoría con modelo efectivo.
- [x] T007 [P] [US1] `GET /chat/models` (chat.py:1278): antepone pseudo-modelo «auto»
      cuando `enabled` (contrato §GET /models); excluye `router-embeddings` y el
      pseudo-modelo de cualquier flujo de gestión.
- [x] T008 [P] [US1] Vitrina: kwarg opcional `routing` en `_publish_monitor`
      (gateway.py:609-648, campo opcional del contrato de 3 productores) + publicación de
      ÉXITO del plano chat (hoy solo publica bloqueos) con tool chat-ui y `routing` si
      aplica + render en `backend/src/api/monitor.py` y en la página «Conexiones en vivo»
      (`frontend/src/pages/FirewallMonitorPage.tsx`): chip ruta+score+degradado.
- [x] T009 [US1] Integration tests `backend/tests/integration/test_chat_auto_router.py`
      (patrón test_chat_attribution: mock httpx en namespace de chat + mock del router o
      de ai_engine_client): auto→ruta premium con layer_llm.auto_router completo; embed
      caído→200 default degraded; fila audit con routing_decision y modelo efectivo;
      switch OFF→default sin embeds; no-auto→sin campo auto_router y routing_decision NULL.
- [x] T010 [US1] **CHECKPOINT VIVO** (stack camara, quickstart): 3 prompts→3 destinos
      visibles en vitrina (SC-004); adaptar `bench_embeddings.py` con modo `--live`
      (motor `/v1/embeddings` + rutas del volumen) y correr SC-001 (≥8/9); medir SC-002
      (p50 frío ≤1,5 s / caliente ≤400 ms) y anotar resultados en quickstart.md.

**Checkpoint**: US1 demostrable por API + registro — el MVP del jueves existe.

## Phase 4: User Story 2 — Panel en «Modelos & Ollama» (P2)

**Goal**: switch global, default, timeout, rutas editables en caliente, estado del modelo
de embeddings, señal de ruta rota; admin-only.

**Independent Test**: quickstart §SC-003 — OFF = cero embeds; editar target de una ruta →
siguiente consulta va al nuevo destino sin restart.

- [x] T011 [US2] `backend/src/api/router_config.py` — GET/PUT `/chat/router-config`
      (contrato completo: computados `*_ok` contra el catálogo, `config_error`, escritura
      atómica tmp+os.replace, validación 422 per data-model §1, admin-only 403) + wiring
      en el api_router (mismo prefijo que chat).
- [x] T012 [P] [US2] Tests `backend/tests/integration/test_router_config_api.py`:
      roundtrip GET→PUT→GET, 422 por umbral/timeout/utterances inválidos, `target_ok:
      false` con ruta rota, 403 no-admin, config corrupta en disco → 200 con
      `config_error` y `enabled: false`.
- [x] T013 [US2] Frontend: `getRouterConfig/putRouterConfig` en
      `frontend/src/services/api.ts` + sección «Ruteo inteligente» en
      `frontend/src/pages/ModelsPage.tsx` (design system 029): switch global, select
      default_model del catálogo real, timeout, editor de rutas (nombre, descripción,
      utterances como chips, umbral, select target_model), badge estado embeddings
      (embedding_model_ok), badge «ruta rota», filtrado del pseudo-modelo «auto» de la
      tabla de gestión. Guardar → PUT → toast + recarga.
- [x] T014 [P] [US2] `frontend/src/pages/PlaygroundPage.tsx` + `UserPortal.tsx`: «Auto»
      llega solo por GET /models (preseleccionado por ser primero); badge del modelo REAL
      que contestó + señal «degradado» (de layer_llm.auto_router / model_used) en la
      respuesta y en el Debugger Técnico (capa 04).
- [x] T015 [US2] **CHECKPOINT VIVO**: switch OFF por panel → SC-003 (cero llamadas en logs
      del motor); edición de utterance/target en caliente aplica a la siguiente consulta;
      no-admin no ve el panel.

## Phase 5: User Story 3 — Fallback siempre-a-local (P3)

**Goal**: todo cloud nace con fallback al local; jamás local→cloud; honestidad del modelo
real en UI.

**Independent Test**: quickstart §US3 — cloud roto → 200 local ≤15 s con modelo real y
badge degradado.

- [x] T016 [US3] `register_model` (chat.py:1306): al dar de alta un modelo NO-ollama con
      ≥1 local en catálogo → escribir `router_settings.fallbacks += {nuevo: [local]}`
      (local = default_model del router si es local, si no primer ollama); rechazar
      fallback con origen ollama en `PUT /chat/fallbacks` (regla local→cloud prohibido,
      ahora enforced). Tests en `backend/tests/integration/test_model_fallback_default.py`.
- [x] T017 [P] [US3] Edge /gw: `model=="auto"` en byok → reescribir al default_model antes
      de reenviar al motor (gateway.py camino byok ~:801, research R9) + test.
- [x] T018 [US3] **CHECKPOINT VIVO**: romper api_base de un cloud + restart motor →
      consulta 200 por local ≤15 s, campo model honesto, badge degradado en Playground
      (SC-005); alta de modelo cloud nuevo por panel → nace con fallback sin acción extra.

## Phase 6: Polish & cross-cutting

- [x] T019 [P] Docs: `deploy/release/INSTALL-CAMARA.md` (+`ollama pull
      qwen3-embedding:0.6b` en prerrequisitos y preflight; nota restart motor tras T002) +
      runbook si menciona modelos; registro de superficies/compatibility si el «Auto»
      cambia la matriz (plano chat solamente).
- [x] T020 Gate final: suite backend completa (verde salvo los 3 preexistentes conocidos),
      build frontend sin errores TS, quickstart.md ejecutado de punta a punta y
      actualizado con los números medidos.

## Dependencies

```text
T001 (checkpoint R1) ──┐
T002 ──────────────────┼─→ T003 → T004
                       │        └→ T005
                       └─→ Fase 3: T006 (necesita T003+T005) · T007/T008 [P] → T009 → T010
Fase 4: T011 → T012/T013 [P] → T014 [P] → T015   (necesita Fase 3 para el checkpoint)
Fase 5: T016/T017 [P] → T018                      (independiente de Fase 4)
Fase 6: T019 [P en cualquier momento] · T020 al final
```

## Implementation Strategy

- **MVP = Fase 1+2+3** (US1): demostrable por API/vitrina/auditoría aunque el panel no
  exista. Si el jueves aprieta, US2 puede demostrarse editando el JSON del volumen.
- Fases 4 y 5 son paralelizables entre sí tras la 3 (backend/frontend tocan ficheros
  distintos salvo chat.py — US3 toca gateway.py y el writer de fallbacks, no el endpoint
  de chat).
- Checkpoints vivos (T001/T010/T015/T018) los corre el orquestador contra el stack camara
  del Mac — los agentes de coding NO tocan el stack vivo.
