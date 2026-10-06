---
description: "Tareas de la 057 — porte de la redirección de modelos (Sentinel 068), en tramos T-A a T-G"
---

# Tasks: Porte de la política de redireccionamiento de modelos (Sentinel 068) a Eleia

**Input**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md).
**Fuentes de solo lectura**: Sentinel `6a70855` y el HANDOFF `8c525db` (rama `docs/handoff-068-elea`).

**Tests**: TDD donde hay código nuevo (regla del repo y constitución, Development Workflow 3): cada
test se escribe primero y tiene que fallar antes de su implementación. Los cherry-picks traen sus
propios tests.

**Organización**: por **tramos** (pedido del coordinador), cada uno de ≤ 15 tareas salvo T-B, que tiene
16 por la tarea de D12 (T087) que agregó el owner el 2026-10-06, con su lista de archivos (plan §Tramos)
y su gate.

**Decisiones legales del owner (2026-10-06)**, ya en la spec (Clarifications, Session 2026-10-06,
decisiones legales) y en research R14, R23–R26: reglas de bloqueo vacías en Eleia (D1, T028), postura
por defecto `masked_all` (D2, T053, T064), relajación explícita por destino o región (D5, T053, T057,
T060, T063), entidad responsable y jurisdicción de control (D12, T087, T054, T060), y textos de producto
con «seudonimización reversible» y residencia 🟡 (D3/D10, T079, T080, T086). Orden: **A → B → C → D → E → F → G**; D puede correr en paralelo con
E. Dentro de un tramo, las etiquetas `[USn]` atan cada tarea a su historia de la spec.

**Docker**: toda tarea marcada **🐳** usa Docker y se corre **solo después de avisar al owner con
`orca orchestration ask` y esperar su respuesta** (prepara la PC).

**Base compartida con el motor**: ninguna tarea arranca una base nueva con el backend antes que el
motor ni cambia la imagen del motor; las pruebas en vivo siguen quickstart §0 (research R5).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede correr en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: historia de la spec (US1–US5); sin etiqueta en los tramos de fundación (T-A, T-B) y en el de cierre (T-G)

---

## Phase 1: Tramo T-A — Costuras de base por cherry-pick (fundación, bloquea todo)

**Goal**: la base de Eleia con S1–S7, S12, S2-OpenAI y ADAPT-024 traídas tal cual de Sentinel, sin
cambiar nada para quien no tiene la extensión (FR-001, FR-002, FR-004, FR-053; SC-001, SC-002), con la
enmienda constitucional aprobada que habilita el 403 de residencia (T001, primera tarea).

**Independent Test**: la batería de no-regresión (T003) y la suite completa quedan verdes **sin
modificar tests existentes**, sin ninguna variable de la extensión definida.

**Archivos del tramo**: plan §Tramos fila T-A. Cada commit se trae con `git cherry-pick -x`; cada
conflicto *modify/delete* sobre `docs/sentinel/04-REGISTRO-DE-CAMBIOS.md` se resuelve con `git rm` de
ese archivo y `git cherry-pick --continue` (HANDOFF §1(a)). Las adaptaciones se anotan en el mensaje del
commit (`ADAPT-0xx`, plan de salida) para que T084 las consolide.

- [ ] T001 **Primera tarea.** Enmienda constitucional **aprobada por el owner el 2026-10-06**, aplicada con el skill `speckit-constitution` (research R21), **gate antes de integrar T-B** (el código que copia T-B ya responde 403 de residencia): versión MINOR con 403 `permission_error` para los rechazos de residencia de la política de redirección, aclaración de §VII (nombres de proveedor solo como datos cargados por el administrador o donde el protocolo de la herramienta los exige) y default de residencia por región del perfil, redactado genérico y configurable, con la precedencia del enmascarado forzado sobre `nlp_fail_mode=degrade` y `redact_enabled=false` mientras rige (FR-027, FR-031; plan §Constitution Check, Principio I); aplica la decisión del owner registrada en research R21 en `.specify/memory/constitution.md` con su Sync Impact Report; no fija los valores de Eleia (reglas vacías, `masked_all`), que son datos del seed (T028, T064)
- [ ] T002 Preparar la rama de trabajo desde `main` y agregar Sentinel como remoto de **solo lectura** (`git remote add sentinel …` + `git fetch sentinel main docs/handoff-068-elea`); verificar que `6a70855` y `8c525db` existen y que la cadena del backend tiene una sola cabeza `199fe429762a` (`backend/alembic/versions/199fe429762a_users_must_change_password.py:22-23`)
- [ ] T003 Escribir **antes** de cualquier cherry-pick la batería de no-regresión de la pasarela con motor falso: `/gw/v1/messages` (llave del producto y suscripción, stream y no-stream), `/gw/v1/messages/count_tokens` y `/gw/v1/models`, comparando cuerpo, estado y fila de auditoría contra lo grabado hoy, en `backend/tests/contract/test_gw_no_regresion_057.py` (tiene que quedar verde antes y después del tramo; SC-001, US2 esc. 1–2)
- [ ] T004 `git cherry-pick -x 1021c8e` (S4: `backend/src/migration_locations.py`, `backend/alembic/env.py`, `backend/src/main.py`, `backend/Dockerfile`, `deploy/docker/entrypoint/backend.sh`, `.env.example`); confirmar que sin `ALEMBIC_EXTRA_VERSION_LOCATIONS` el arranque sigue en `upgrade head` y pasa `backend/tests/unit/test_alembic_extra_versions.py`
- [ ] T005 `git cherry-pick -x 7a4f65c` (S6) resolviendo el hunk de `update_model_credential` en `backend/src/api/chat.py`: se quedan el `engine_params` de Eleia **y** el `_visible_entries(...)` de Sentinel (research R2); pasa `backend/tests/unit/test_models_hidden_entries.py`
- [ ] T006 `git cherry-pick -x 891d4d0` y `git cherry-pick -x 6161bf0` (S1): en `backend/src/main.py` queda **solo** `mount_plugin_routers(app)` antes de CORS, sin `TrialReadOnlyMiddleware`; resolver el hunk trivial de `docs/docs/api-reference/configuration.md`; ajustar el nombre del logger de `backend/src/plugins.py` si no coincide con el prefijo de Eleia; pasa `backend/tests/unit/test_plugin_routers.py`
- [ ] T007 `git cherry-pick -x e3a5297` (S2) con la resolución mínima ensayada de los 3 hunks en `backend/src/api/gateway.py`: import `from . import gateway_plugins as gp` sin `require_not_trial_expired`; `_byok_proxy` suma `ctx=None`; respuesta no-stream con `_respuesta_destino(ctx, …)` y el mensaje de error de Eleia (research R2); pasa `backend/tests/unit/test_gateway_plugins.py` y T003
- [ ] T008 `git cherry-pick -x 933c513` (S12: `deploy/docker/compose.prod.yml`, `deploy/Makefile`, `deploy/release/checks/test_compose_extra_env_file.sh`) y `git cherry-pick -x 1a454ed` (S5b: `masking_report` en `litellm/extensions/sentinel_guardrail.py`, **sin** S5a); pasan `deploy/release/checks/test_compose_extra_env_file.sh` y el test de `masking_report`
- [ ] T009 `git cherry-pick -x 9c7bf08` y `git cherry-pick -x 8ceab22` (S7: `backend/src/api/internal.py`, `litellm/extensions/sentinel_audit_logger.py`, `litellm/extensions/sentinel_guardian_policy.py`); pasa `backend/tests/unit/test_audit_routing_decision.py`
- [ ] T010 `git cherry-pick -x faf94de 5a2d1aa 66dfa61 0669e03` (S2: `map_response` y la identidad de la llave en `/v1/models` y `count_tokens`) sobre `backend/src/api/gateway.py` y `backend/src/api/gateway_plugins.py`; pasan `backend/tests/unit/test_gateway_plugins.py` y T003
- [ ] T011 `git cherry-pick -x f63144d adb53d9 1d8a3b7` (S3 y ADAPT-026: `frontend/src/App.tsx`, `frontend/src/plugins/**`, `frontend/{tailwind.config.js, vite.config.ts, vitest.config.ts}`, `deploy/release/INSTALL-CAMARA.md`), con `git rm` de `specs/069-…/tasks.md`; correr `cd frontend && npm test` (incluye `frontend/src/plugins/registry.test.ts`)
- [ ] T012 `git cherry-pick -x 9c17500` y después `git cherry-pick -x efb2c94` (S2-OpenAI, HANDOFF Anexo A): firma `_byok_proxy(…, ruta_motor: str = "/v1/messages", error_fn=None, ctx=None)`, `(error_fn or _anthropic_error)(…)` con `sanitize_engine_error` en no-stream y stream, en `backend/src/main.py` primero `gateway_openai` y después `mount_plugin_routers`, ambos antes de CORS; `git rm` de `deploy/clients/nix/config.yaml.tmpl` y `specs/045-…/tasks.md`; **no** traer `9fe188f` ni `fd515ff`; pasa `backend/tests/contract/test_gateway_openai_route.py` y queda idéntico al de `efb2c94` (HANDOFF §A.4)
- [ ] T013 ADAPT-024: `git checkout 14edbc7 -- backend/src/services/encryption_service.py backend/tests/unit/test_encryption_multifernet.py` (nunca el commit entero: trae symlinks); pasa `backend/tests/unit/test_encryption_multifernet.py` y los tests existentes de cifrado
- [ ] T014 Pantalla de descubrimiento neutra (FR-004, Diagnóstico #16): primero el test que falla `backend/tests/contract/test_gw_info_neutral.py` (ningún nombre de `deploy/release/checks/prohibited_names.txt` en `GET /api/v1/gw`), después el texto neutro en `gw_info` de `backend/src/api/gateway.py` (hoy `:2047-2069`)
- [ ] T015 Gate del tramo: 🐳 `make -C deploy docs-refs` (regenera `docs/docs/api-reference/openapi.json` con `/gw/v1/chat/completions` y `configuration.md` con las variables nuevas de `.env.example`); 🐳 `docker compose run --rm --no-deps backend pytest tests/ -q`; `cd frontend && npm test`; `cd client && npm test`; 🐳 `make -C deploy check` (white-label y secretos incluidos); dejar las salidas resumidas en el cuerpo del PR del tramo

**Checkpoint**: base con costuras, idéntica sin extensión. PR del tramo T-A.

---

## Phase 2: Tramo T-B — Paquete de la extensión, migraciones y entrega (fundación)

**Goal**: `sentinel/` de `6a70855` funcionando en Eleia, sus migraciones como segunda cabeza, S9/S11
en el camino de despliegue, catálogo de Azure verificable y la base del requisito de modelos chinos y
económicos (FR-004a–FR-004c, FR-011–FR-014, FR-020, FR-029; research R4–R9, R14, R17).

**Independent Test**: con las variables de la extensión, el backend arranca con `heads =
['199fe429762a', '<hash>']`; sin ellas, una sola cabeza; las suites de la extensión pasan.

**Archivos del tramo**: plan §Tramos fila T-B.

- [ ] T016 Test que falla primero, en `sentinel/tests/integration/test_migraciones_cadena_base.py`: con `alembic.script.ScriptDirectory`, sin `ALEMBIC_EXTRA_VERSION_LOCATIONS` hay una sola cabeza del backend; con la variable, dos (la del backend y la de la extensión), la rama de la extensión cuelga de `010`; ninguna migración de `sentinel/migrations/` crea, altera ni borra tablas `LiteLLM_*` ni `_prisma_migrations`, todas las tablas tienen prefijo `sentinel_redirect_` o `ext_` y las FKs apuntan solo a `tenants`, `groups` o tablas propias (research R5; obtener las cabezas por cálculo, no fijas)
- [ ] T017 Copiar la extensión: `git checkout 6a70855 -- sentinel`, borrar `sentinel/onboarding/` y `sentinel/migrations/b8c4d7e2a915_wizard_profile.py`; marcar `skip` con motivo y referencia a `fd515ff` el test `test_listado_generico_suma_auto_para_los_servicios` de `sentinel/tests/integration/test_redirect_gateway_e2e.py` (HANDOFF §A.4); corregir con TDD el import latente de `ApiKey` desde `src.models.budget` en `sentinel/access/api/admin.py` (~:439 y :519, HANDOFF §1(b)) al nombre real de la clase de llaves de la base, con su test en `sentinel/tests/unit/test_access_apikey_import.py`; T016 pasa
- [ ] T018 [P] No-regresión **con la extensión montada y la política apagada** (SC-001, US2 esc. 1–4) en `sentinel/tests/integration/test_no_regresion_con_extension.py`: la batería de T003 (reusando sus fixtures) da las mismas respuestas y filas de auditoría con `GATEWAY_PLUGINS`/`PLUGIN_PACKAGES` definidos y sin ninguna fila de política ni postura; un id publicado solo para otro grupo da el mismo error de modelo inexistente que hoy; los destinos de otra empresa no aparecen en `/gw/v1/models`
- [ ] T019 🐳 Spike D14 sobre el motor fijado (`litellm/Dockerfile:6`, research R7): familias `rdx-*` con comodín y sin credencial, credencial y base fijadas por pedido desde el guard, `rdx-*` sin autorización rechazado; usar `spike053/` de la 068 como guion y registrar versión real del motor, comandos y resultado en `specs/057-porte-sentinel-068-redireccion-modelos/verificacion-d14.md`. **Si falla: parar y escalar (gate de re-plan)**
- [ ] T020 S9 y S11 [BASE, nuevas] con TDD: primero `deploy/release/checks/test_extension_delivery.sh` (sin `EXTRA_ENGINE_EXTENSIONS`/`PROFILE_FRAGMENTS`, volumen, paquete y `config.yaml` renderizado idénticos por hash; con ellas, los `redirect_*.py` copiados y el fragmento fusionado al final; un `model_name` o `guardrail_name` duplicado hace fallar el render), después la implementación en `deploy/release/populate_volumes.sh` (hoy `:45-46`), `deploy/release/bundle.sh` (hoy `:98-99`, `:186-187`) y `deploy/release/render_profile.sh` (hoy `:29`) con un fusionador de base nuevo `deploy/release/fragment_merge.py`, genérico y con el mismo contrato que `sentinel/engine/fragment_merge.py` (la base no depende de la ruta de la extensión; contrato en contracts/costuras-base.md)
- [ ] T021 [P] Entrega en desarrollo: `sentinel/docker/compose.dev.yml` (override con `-f`: `./sentinel` → `/opt/sentinel-ext/sentinel` y `PYTHONPATH` en el backend; `sentinel/engine/redirect_*.py` y `config.yaml` fusionado en el motor; `DISABLE_SCHEMA_UPDATE=true` en el motor) y `sentinel/extensions.env.example` sin secretos con las variables de HANDOFF §2.1 y `SENTINEL_ENTITY_REGION=latam_ar` (research R5, R6)
- [ ] T022 Catálogo de Azure con TDD (FR-020, research R9): primero `sentinel/tests/contract/test_catalog_azure_despliegue.py` (credencial adoptada `AZURE_API_KEY` con `allow_any_env` + `api_version`, sin duplicar el secreto; un `real_model` sin despliegue deja la entrada `inactive` con «El despliegue `<x>` no existe en el recurso configurado»; `POST …/entries/{id}/check` re-verifica), después la verificación en `sentinel/catalog/validation.py` y `sentinel/catalog/api/admin.py` (contracts/admin-api.md §azure)
- [ ] T023 [P] Datos de ejemplo [ELEIA] `deploy/redirect-seeds/catalog-seed.azure-demo.yaml`: entradas `gpt-5.6-luna`, `gpt-5.1-chat`, `gpt-5.4-mini` y `gpt-4o-mini` (provider `azure`, `real_model` = nombre del despliegue, credencial adoptada, ventana y precio reales), con la jurisdicción de inferencia, la entidad responsable y las jurisdicciones de entidad y de control **vacías y marcadas obligatorias** (no se presume la región; FR-028a); validar que `python -m sentinel.catalog.seed` lo carga de forma idempotente
- [ ] T024 [P] **Test de modelos chinos y económicos (requisito del owner)** en `sentinel/tests/integration/test_catalogo_modelos_chinos_economicos.py`, con upstream falso: alta de DeepSeek (`deepseek`), Qwen y Kimi (`openai_compatible` con su `api_base`), GLM (`zai`) y los mismos vía `openrouter`; el guard los manda a la familia correcta (`rdx-deepseek`, `rdx-chatcompat`, `rdx-zai`) con la credencial y la base del destino; una regla con estrategia `cheapest` elige el destino de menor precio del catálogo y el costo registrado es el del destino real (research R17)
- [ ] T025 [P] Test de habilitación explícita por datos (FR-029, research R14) en `sentinel/tests/unit/test_catalog_habilitacion_explicita.py` y `sentinel/frontend/catalog/__tests__/habilitacion.test.tsx`: reglas `provider`, `api_host` (con comodín de un nivel) y `jurisdiction` (contra inferencia, entidad **o control** de la ficha) marcan `blocked_by_default`; cambiar `provider`/`api_base`/ficha re-evalúa; **con las tres listas vacías ninguna entrada nace bloqueada y alta, publicación y pedido funcionan**; la habilitación desde el panel exige motivo y rol permitido y queda en el registro de cambios; con el seed de paridad `provider: deepseek` el comportamiento es el de Sentinel; las reglas de nivel empresa no se ven ni aplican en otra empresa (RLS, FR-051)
- [ ] T026 Migración nueva [BASE] por `alembic revision` en la rama `sentinel_redirect` colgada de `f7a3c1d9e508`: tablas `sentinel_redirect_region` (con `default_posture`), `ext_catalog_enablement_rule` y `sentinel_redirect_masking_relaxation` con `tenant_id` y RLS, y la columna `control_jurisdiction` en `ext_compliance_sheet`, según data-model §1–§4; modelos en `sentinel/redirect/models.py` y `sentinel/catalog/models.py`, archivo `sentinel/migrations/<hash>_redirect_region_y_habilitacion.py`; T016 sigue verde con la cabeza nueva
- [ ] T027 Regla de bloqueo por datos (hace pasar T025): módulo nuevo `sentinel/catalog/habilitacion.py` y reemplazo del `provider == "deepseek"` fijo en `sentinel/catalog/api/admin.py` (hoy `:503`), `sentinel/catalog/seed.py` (`:86`), `sentinel/catalog/api/legacy.py` (`:157`) y `sentinel/catalog/migrate.py` (`:101`); API de reglas según contracts/admin-api.md; cargador idempotente del seed de reglas `python -m sentinel.catalog.habilitacion <archivo>`
- [ ] T028 Sembrado [ELEIA] de `deploy/redirect-seeds/habilitacion-explicita.yaml` con la decisión del owner del 2026-10-06 (D1 del análisis legal; research R14, opción (a)): las tres listas **vacías** y un encabezado que cita la decisión; validar con T025 que con este seed ninguna entrada nace bloqueada y que una regla cargada después desde el panel bloquea como se espera
- [ ] T087 **Entidad responsable y jurisdicción de control en el catálogo (D12, FR-028a; research R25)** con TDD: primero los tests que fallan en `sentinel/tests/unit/test_catalog_jurisdiccion_control.py` (la ficha acepta y devuelve `control_jurisdiction`; `provider_legal_entity` se expone como entidad responsable; `in_region` de la entrada es verdadero solo si inferencia, entidad **y** control están en la región efectiva; con control vacío o fuera, `in_region = false`; cambiar el campo queda en el registro de cambios, re-evalúa reglas de habilitación y revoca una relajación por destino cuya ficha deja de cumplir las precondiciones (`revoke_reason = precondicion_incumplida`, data-model §3); ningún código nombra un país) y en `sentinel/frontend/catalog/__tests__/ficha.control.test.tsx` (el formulario de la ficha muestra «Entidad responsable», «Jurisdicción de la entidad» y «Jurisdicción de control» y avisa cuando falta el control); después el campo en `sentinel/catalog/models.py` (columna de T026), la validación en `sentinel/catalog/validation.py`, la API en `sentinel/catalog/api/admin.py` (contracts/admin-api.md §Ficha) y el formulario en `sentinel/frontend/catalog/**`
- [ ] T029 Panel del MVP (FR-005, FR-010, research R15): test que falla primero en `sentinel/frontend/redirect/__tests__/PolicyTab.mvp.test.tsx` (el estado *sombra* no se ofrece; la pantalla «Modelos» queda en el menú junto a Gobernanza), después el ajuste en `sentinel/frontend/redirect/PolicyTab.tsx` y `sentinel/frontend/pages/modelos.tsx`
- [ ] T030 Gate del tramo: tests de la extensión sin Docker (venv del backend con `PYTHONPATH=.:backend`, `pytest sentinel/tests -q`, incluidos `test_redirect_propagation.py` para SC-009 y el aislamiento por empresa de FR-051), `cd frontend && npx vitest run --config ../sentinel/frontend/vitest.config.mts` (o el comando que fije `sentinel/frontend`), `deploy/release/checks/test_extension_delivery.sh`; 🐳 suite del backend y `make -C deploy check`

**Checkpoint**: extensión montada y apagada; con las variables, migrada y operable desde el panel.

---

## Phase 3: Tramo T-C — Cara Claude para Claude Code y Claude Desktop (US1 P1, US4 P3)

**Goal**: Claude Code y Claude Desktop contra `/gw/v1/messages` con el destino que elige el
administrador, incluidos T139 y T094 que Sentinel no hizo (FR-033–FR-042; contracts/cara-claude.md).

**Independent Test**: con la política encendida en un grupo y destinos Azure, Claude Desktop y Claude
Code listan los tiers y completan una conversación con herramientas y streaming; la auditoría registra
id pedido y destino real (US1 Independent Test).

**Archivos del tramo**: plan §Tramos fila T-C.

- [ ] T031 [P] [US1] Corpus de pedidos de la herramienta en `sentinel/tests/fixtures/harness_corpus/claude/`: Claude Code con `?beta=true`, `safeguards`, cabeceras `anthropic-beta`, `count_tokens` y herramientas; sondeo `max_tokens: 1` de Claude Desktop; Cowork con varios turnos (sin datos reales de personas; T080 de Sentinel)
- [ ] T032 [P] [US1] Test T139 que falla primero en `sentinel/tests/unit/test_face_claude_campos_desconocidos.py`: hacia un traducido solo pasan los campos de la lista permitida de contracts/cara-claude.md §1, `safeguards` y cualquier campo desconocido se quitan sin error y sus **nombres** quedan en `dropped_fields`; hacia un nativo no se filtra
- [ ] T033 [P] [US1] Test T094 y FR-042 que falla primero en `sentinel/tests/unit/test_face_claude_betas.py`: betas por lista permitida hacia nativos, todas descartadas hacia traducidos (`betas_dropped`); credencial de suscripción personal hacia destino de otro proveedor ⇒ 401 `authentication_error`
- [ ] T034 [P] [US1] Test T093 que falla primero en `sentinel/tests/contract/test_face_claude_count_tokens.py`: nativo ⇒ reenvío; traducido ⇒ `{"input_tokens": N}` estimado; sin estimador ⇒ 404 `not_found_error`; `count_tokens_mode` en la auditoría (contracts/cara-claude.md §3)
- [ ] T035 [P] [US1] Test de contrato en `sentinel/tests/contract/test_face_claude_contract.py` (T081/T082 de Sentinel): `/gw/v1/models` vista Anthropic < 1 s con etiqueta «<Tier> · servido por <destino>» y ventana real; `Bearer` y `x-api-key`; `?beta=true`; `HEAD /api/hello` → 404; id no publicado ⇒ 404; regla por tier; destino sin credencial ⇒ fallback o error claro; `rdx-*` o `api_base` del cliente rechazados o ignorados; 503 reintentable si falla la resolución; 529 `overloaded_error` con `x-should-retry` ante saturación del destino; 429 con `retry-after` ≤ 60; función que el destino no soporta (PDF sin visión) o exclusiva del proveedor original (búsqueda web o ejecución de código del proveedor) ⇒ 400 `capability_rejected: …`, nunca ignorada en silencio; ningún texto con nombres de `prohibited_names.txt`; la fila de auditoría no contiene texto del pedido ni secretos (US1 esc. 1–6, US4 esc. 3–4, FR-009, FR-014, FR-016, FR-018, FR-038, FR-047, SC-008)
- [ ] T036 [P] [US4] Test de stream que falla primero en `sentinel/tests/integration/test_face_claude_stream.py` (T085/T091): `ping` con > 15 s de silencio; `message_start.model` = id público; `usage` con los cuatro contadores; error después de `message_start` ⇒ `event: error` y cierre sin `message_stop`; en la cara genérica, comentario `: keep-alive` (FR-037–FR-039, FR-056, SC-007)
- [ ] T037 [P] [US4] Test de razonamiento que falla primero en `sentinel/tests/unit/test_face_claude_razonamiento.py` (T084): firma HMAC de los bloques `thinking` de un traducido, reconstrucción en el turno siguiente, firma ajena descartada sin error, sin rastros de otro destino (FR-036)
- [ ] T038 [P] [US1] Test del sondeo de arranque contra Azure en `sentinel/tests/unit/test_guard_azure_parametros.py`: `max_tokens: 1` ⇒ 16 y `max_tokens` ⇒ `max_completion_tokens` para gpt-5.x en Azure, con `adjusted_params` (US1 esc. 8; el guard copiado ya lo hace)
- [ ] T039 [US1] T139: lista permitida de campos en `normalize_for_translated` de `sentinel/redirect/faces/claude.py` (hoy ~`:255`) con `dropped_fields` (hace pasar T032; research R10)
- [ ] T040 [US1] T094 y FR-042 en `pre_request` y `forward_headers_allowlist` de `sentinel/redirect/plugin.py`, con la lista permitida de betas como dato de la extensión (hace pasar T033; research R11)
- [ ] T041 [US1] T093: respuesta temprana de `count_tokens` para traducidos en `sentinel/redirect/plugin.py` con `tiktoken` `o200k_base` (hace pasar T034; research R12)
- [ ] T042 [US4] T091: `wrap_stream` en `sentinel/redirect/stream.py` (pings, `model` público, `usage` completo, evento de error, `: keep-alive` de la cara genérica) (hace pasar T036)
- [ ] T043 [US4] T090: firma y reconstrucción de razonamiento en `sentinel/redirect/faces/claude.py` y `sentinel/redirect/stream.py` (hace pasar T037)
- [ ] T044 [P] [US1] Medición de SC-010 en `sentinel/tests/perf/test_redirect_overhead.py`: demora agregada hasta el primer contenido con la política encendida ≤ 50 ms p95 contra upstream falso instantáneo
- [ ] T045 [US1] 🐳 Prueba en vivo con Azure siguiendo quickstart §1–§4 (Claude Code CLI y Claude Desktop Chat/Cowork/Code; opus → gpt-5.6-luna, sonnet → gpt-5.1-chat, haiku → gpt-5.4-mini): batería de T031 con ≥ 95 % sin errores visibles y el resto como rechazo explícito (SC-004, parte traducida), cambio de destino en < 1 min (SC-009); evidencia sin contenido en `specs/057-porte-sentinel-068-redireccion-modelos/verificacion-cara-claude.md`

**Checkpoint**: MVP utilizable con la cara Claude sobre Azure.

---

## Phase 4: Tramo T-D — Cara OpenAI genérica (US5 P3)

**Goal**: CLIs y harness con formato OpenAI contra `/gw/v1/chat/completions` con alias propios
(FR-053–FR-056; contracts/cara-generica.md). Puede correr en paralelo con T-E.

**Independent Test**: con la política encendida en un grupo, una CLI genérica lista los alias y
completa una conversación con streaming y herramientas contra un destino Azure; un usuario de otro
grupo no ve los alias.

**Archivos del tramo**: plan §Tramos fila T-D.

- [ ] T046 [P] [US5] Test de contrato que falla primero en `sentinel/tests/contract/test_face_generic_eleia.py`: `GET /gw/v1/models` sin `anthropic-version` devuelve solo alias `openai_generic` del alcance con `owned_by` neutro; con `anthropic-version`, la vista Claude; otro grupo no ve los alias (US5 esc. 1, FR-055)
- [ ] T047 [P] [US5] Test que falla primero en `sentinel/tests/integration/test_face_generic_e2e_eleia.py`: alias → destino, `model` de la respuesta = alias, cambio de destino sin tocar el cliente, `model_not_found` (404), `region_not_allowed` (403) y `masking_required` (403, enmascarado forzado con el analizador caído) con textos neutros, `max_tokens` ⇒ `max_completion_tokens` hacia gpt-5.x de Azure (US5 esc. 2–4, FR-054, FR-056)
- [ ] T048 [P] [US5] Test en `backend/tests/contract/test_gateway_openai_policy_off_057.py`: con la política apagada, `/gw/v1/chat/completions` aplica la misma política de seguridad base que `/gw/v1/messages` (bloqueos, secretos, enmascarado reversible, auditoría) y sirve el modelo pedido (US5 esc. 5, FR-053)
- [ ] T049 [P] [US5] Test en `sentinel/tests/integration/test_face_generic_restauracion.py`: con enmascarado, los chunks OpenAI vuelven restaurados por el arreglo de Eleia `f8118e7` (sin marcadores en la respuesta) por la cara genérica redirigida
- [ ] T050 [US5] Ajustes en `sentinel/redirect/faces/generic.py` que pidan T046–T049 (si no hace falta ninguno, dejar constancia en el PR)
- [ ] T051 [US5] 🐳 Primera prueba en vivo de la cara genérica (HANDOFF Anexo A) con opencode y Aider (modo OpenAI) contra Azure siguiendo quickstart §6 (SC-014); evidencia en `specs/057-porte-sentinel-068-redireccion-modelos/verificacion-cara-generica.md`

**Checkpoint**: las dos caras del MVP andan sobre Azure.

---

## Phase 5: Tramo T-E — Residencia AMERICAS, postura y semáforo por perfil (US3 P2)

**Goal**: la región del perfil como dato (`AMERICAS`) con su postura por defecto configurable (en Eleia,
enmascarado forzado en todo destino), las relajaciones explícitas de cumplimiento, la regla «en región»
con entidad y control, las posturas aplicadas en todo el tráfico de pasarela, el enmascarado forzado
verificado, OpenRouter con cero retención y el semáforo evaluado contra la región (FR-021–FR-032,
FR-028a, FR-031a; research R13, R16, R19, R23–R26).

**Independent Test**: dos usuarios con posturas distintas piden el mismo tier cuyo destino es de otra
jurisdicción: el de *solo jurisdicciones permitidas* recibe el fallback (o el rechazo); el de *fuera de
región* recibe el principal con enmascarado verificado; con el analizador caído, el segundo se bloquea.

**Archivos del tramo**: plan §Tramos fila T-E.

- [ ] T052 [P] [US3] Test que falla primero en `sentinel/tests/unit/test_residency_region_data.py`: la región sale de `sentinel_redirect_region` (empresa > instalación > respaldo fijo de `region_codes`); `latam_ar` ⇒ `AMERICAS`; una jurisdicción `US` o `BR` satisface `AMERICAS`, una de la UE no; `is_zone` permite usar `AMERICAS` como código; un país satisface a su zona y no al revés; las regiones de nivel empresa no se ven ni aplican desde otra empresa (RLS); todo cambio a una región queda en el registro de cambios con motivo (FR-008, FR-021, FR-030, FR-051)
- [ ] T053 [P] [US3] Tests que fallan primero en `sentinel/tests/unit/test_residency_default_posture.py` (research R23) y `sentinel/tests/unit/test_residency_relajacion.py` (research R24). Postura por defecto, sin postura y redirigido: `reject_offregion` ⇒ fuera de región 403 «Modelo no disponible para tu región.» / `region_not_allowed`; `masked_offregion` ⇒ forzado solo fuera; `masked_all` ⇒ forzado y fail-closed para destinos en EE. UU., Brasil y la UE por igual; `allow` ⇒ sin forzado; con cualquier valor, destino sin jurisdicción de inferencia ⇒ 403; con filas explícitas, la postura efectiva sale de las filas pero el forzado de `masked_all`/`masked_offregion` se mantiene como piso (una `allowlist` restringe el alcance y los destinos de la lista siguen enmascarados); el tráfico no redirigido sin postura queda `off`; `default_posture_applied` en la auditoría; ningún error nombra destinos. Relajaciones: por región (cambiar `default_posture` de `masked_all` a `masked_offregion`) quita el forzado solo a destinos en región (FR-028a); por destino exige jurisdicciones de inferencia, entidad y control, `zero_data_retention = true` y, en `openrouter`, lista de proveedores (si no, 422); no habilita un destino sin jurisdicción, no relaja el fail-closed mientras el forzado rige ni vuelve alcanzable un destino fuera de una *solo jurisdicciones permitidas*; una relajación cuya ficha ya no cumple no tiene efecto al resolver; `masking_relaxation` en la auditoría; ningún override del cliente, la conexión, las cabeceras o la llave la reemplaza (US3 esc. 5, 8–10, FR-027, FR-031, FR-031a, T072 de Sentinel)
- [ ] T054 [P] [US3] Test que falla primero en `sentinel/tests/unit/test_redirect_residency.py` (T066 de Sentinel): allowlist sobre destino y fallbacks, sin jurisdicción ⇒ fuera, modelos no registrados inalcanzables con allowlist, más restrictiva gana, intersección de listas, entidad ajena y su aceptación; **jurisdicción de control** fuera de la lista o sin cargar ⇒ entidad ajena (`foreign_entity`) bajo allowlist y fuera de región bajo `offregion_masked` (FR-024, FR-026, FR-028, FR-028a; US3 esc. 1–2, 11)
- [ ] T055 [P] [US3] Test que falla primero en `sentinel/tests/unit/test_redirect_posture_roles.py` (T067): cumplimiento y super-admin escriben y relajan; el admin de empresa solo agrega filas y, con `masked_all` vigente, una fila suya (incluida una `allowlist`) no quita el forzado a ningún destino; cambiar `default_posture` o crear una relajación por destino con rol admin de empresa ⇒ 403; `reason` obligatorio (FR-023, FR-031a; US3 esc. 7; Edge Cases)
- [ ] T056 [P] [US3] Test que falla primero en `sentinel/tests/integration/test_residency_forced_masking.py` (T070): con *fuera de región con enmascarado forzado* **y con la postura por defecto `masked_all` hacia un destino dentro de `AMERICAS`**, texto, resultados de herramientas y adjuntos analizables salen enmascarados (incluidos DNI, CUIT/CUIL y CBU del perfil `latam_ar`) y vuelven restaurados; `redact_enabled=false`, analizador caído con `nlp_fail_mode=degrade` o contenido no analizable ⇒ bloqueo; ningún override lo relaja (FR-027; US3 esc. 3–5; SC-006)
- [ ] T057 [P] [US3] **Test de residencia de modelos chinos y económicos (requisito del owner y decisiones D1, D2, D5, D12)** en `sentinel/tests/integration/test_residency_modelos_chinos.py`: con el seed de Eleia (reglas vacías, `masked_all`), un destino de API oficial china se da de alta **sin** bloqueo y sale enmascarado, y se bloquea con el analizador caído; los mismos modelos alojados en América (`azure_ai` o `bedrock` con inferencia, entidad y control `US`; `openrouter` con lista de proveedores de EE. UU.) salen **enmascarados por defecto** y sin forzado solo con una relajación por destino con retención cero; una entrada con inferencia `US` y control fuera de `AMERICAS` no pierde el forzado con una relajación por región (`default_posture = masked_offregion`); los cuatro valores de `default_posture` se comportan como en T053 (FR-028a, FR-029–FR-031a)
- [ ] T058 [P] [US3] Test que falla primero en `sentinel/tests/unit/test_guard_openrouter_zdr.py` (T077 de Sentinel, research R19): todo pedido a un destino `openrouter` sale con cero retención, sin recolección de datos y solo a la lista de proveedores permitidos, sin fallbacks fuera de ella; las preferencias de proveedor que mande el cliente se ignoran; alta sin lista ⇒ 422; `openrouter_zdr: true` en la auditoría (FR-032). Verificar antes los nombres de parámetros contra la referencia de la API de OpenRouter y citarla en el test
- [ ] T059 [P] [US3] Tests que fallan primero en `sentinel/tests/unit/test_semaforo_region.py` (semáforo contra la región del perfil, valor interno `eu_ok`, etiqueta «Dentro de <región>», nunca «Admisible» ni «Cumple», research R16, R26; FR-030a) y `sentinel/tests/integration/test_residency_subscription.py` (T069: en el camino de suscripción la redirección no aplica y la postura sí, con la jurisdicción del proveedor original; FR-025; US3 esc. 6)
- [ ] T060 [US3] Región como dato: resolución en `sentinel/redirect/residency.py` (`region_codes`; `effective_posture` con `default_posture`, `masked_all` como `offregion_masked` con casa vacía, el piso de enmascarado con filas explícitas (data-model §1) y rechazo de destinos sin jurisdicción de inferencia; `evaluate` con la regla «en región» de inferencia, entidad y control y con las relajaciones vigentes; zonas desde datos), instantánea con regiones y relajaciones en `sentinel/redirect/store.py`, y API de regiones, relajaciones y el control de rol de la escritura de regiones y relajaciones en `sentinel/redirect/api/admin.py` según contracts/admin-api.md (hace pasar T052–T055)
- [ ] T061 [US3] Guard del motor en `sentinel/engine/redirect_guard.py`: postura y verificación del enmascarado forzado con `masking_report` (T074 de Sentinel; ya bloquea con 403 `masking_required`, `sentinel:sentinel/engine/redirect_guard.py:328-330`), también cuando el forzado viene de la postura por defecto y preferencias de OpenRouter forzadas (T077); `provider` agregado a `CLIENT_CREDENTIAL_FIELDS` de `sentinel/engine/redirect_credentials.py` (hace pasar T056–T058)
- [ ] T062 [US3] Postura en el camino de suscripción en `pre_request` de `sentinel/redirect/plugin.py` (T075; hace pasar T059, parte suscripción)
- [ ] T063 [US3] Semáforo por región en `sentinel/catalog/semaforo.py` (hoy `{"EU"}` fijo, `:47-118`) y `sentinel/catalog/store.py`; panel: etiqueta por región en `sentinel/frontend/catalog/**` y pre-completado de *solo jurisdicciones permitidas* con la región en `sentinel/frontend/redirect/ResidencyTab.tsx` con la etiqueta «Dentro de <región>» (nunca «Admisible» ni «Cumple»; research R16, R26); en `ResidencyTab.tsx`, además, la postura por defecto de la región (cambiarla de `masked_all` a `masked_offregion` es la relajación por región) y la lista de relajaciones por destino con su motivo, visibles y editables solo para cumplimiento y super-admin (hace pasar T059, parte semáforo; `sentinel/tests/contract/test_semaforo_parity.py` sigue verde)
- [ ] T064 [US3] Cargador idempotente de regiones `python -m sentinel.redirect.regions_seed <archivo>` en `sentinel/redirect/regions_seed.py` [BASE] y sembrado [ELEIA] de `deploy/redirect-seeds/regions.americas.yaml` (data-model §1: `AMERICAS` con Norte, Centro, Caribe y Sur, `region_profiles` ⊇ `latam_ar`) con **`default_posture: masked_all`**, decisión del owner del 2026-10-06 (D2 del análisis legal; research R23), y un comentario que diga que `AMERICAS` es criterio de riesgo, no de legalidad; test del cargador en `sentinel/tests/unit/test_residency_regions_seed.py` (idempotente; valor desconocido de `default_posture` ⇒ error)
- [ ] T065 [US3] Gate del tramo: `pytest sentinel/tests -q`, Vitest de `sentinel/frontend`, auditoría de SC-005 (0 % fuera de la allowlist) y SC-006 sobre la batería de T056; 🐳 suite del backend

**Checkpoint**: la redirección es vendible a clientes regulados de la región.

---

## Phase 6: Tramo T-F — Caché del proveedor completa con la costura S13 (US4 P3)

**Goal**: que las tareas agénticas redirigidas aprovechen la caché del proveedor sin bajar la
protección del enmascarado, y que el costo registrado refleje lo cobrado (FR-043–FR-046, FR-048,
FR-049; SC-011, SC-012; research R18, R20).

**Independent Test**: una tarea de Cowork de ≥ 10 pasos con un dato personal en el primer mensaje
contra un destino Azure con caché implícita: desde el 2.º paso, ≥ 60 % de la entrada sale de la caché,
y el costo registrado difiere ≤ 5 % del informado.

**Archivos del tramo**: plan §Tramos fila T-F.

- [ ] T066 [US4] 🐳 Spike de caché sobre Azure (T123 de Sentinel): repetir una tarea de Cowork con y sin dato personal y con y sin identificador de sesión, medir tokens de caché por paso y confirmar o descartar las causas de D22; resultado en `specs/057-porte-sentinel-068-redireccion-modelos/verificacion-cache.md`
- [ ] T067 [P] [US4] Test S13 [BASE] que falla primero en `backend/tests/unit/test_masking_nonce_conversacion.py` (T126): con `sentinel_conversation_ref` y `MASKING_NONCE_KEY`, dos pedidos de la misma conversación dan el mismo historial enmascarado byte a byte; otra conversación, otra llave u otra empresa, otro sufijo; sin alguna de las dos, aleatorio como hoy; el valor que mande el cliente se descarta; el sufijo no se puede reproducir sin la clave; restauración intacta en stream y en chunks OpenAI (FR-045; contracts/costuras-base.md §S13)
- [ ] T068 [P] [US4] Test que falla primero en `sentinel/tests/unit/test_redirect_session_affinity.py` (T124): con `x-claude-code-session-id`, un destino con `session_affinity` recibe un identificador estable derivado con clave del servidor, distinto del original y entre empresas y subagentes; sin cabecera o sin la capacidad, nada (FR-043)
- [ ] T069 [P] [US4] Test que falla primero en `sentinel/tests/unit/test_face_claude_cache_control.py` (T125): con `cache_control` declarado en el destino, las marcas se conservan en `system`, mensajes y bloques sin aplanar el `system`; sin la capacidad se quitan como hoy (FR-044)
- [ ] T070 [P] [US4] Test que falla primero en `sentinel/tests/unit/test_redirect_cache_costos.py` (T127/T128): precio de lectura y escritura de caché por destino, costo y descuento de presupuesto con los tokens informados y una única fuente de precios, sin precio de caché ⇒ precio de entrada y `price_cache_missing`, tokens de caché en la auditoría (FR-046, FR-049)
- [ ] T071 [P] [US4] Test que falla primero en `sentinel/tests/integration/test_response_cache_isolation.py` (research R20): la caché de respuestas del motor no devuelve una respuesta de otro destino ni con marcadores de otra conversación (FR-048)
- [ ] T072 [US4] S13 [BASE] en `litellm/extensions/sentinel_guardrail.py` (creación del `PlaceholderMap`, hoy `:626`) y `litellm/extensions/sentinel_guardian_policy.py` (`PlaceholderMap`, hoy `:776-784`): derivación con `MASKING_NONCE_KEY` y la referencia de conversación; sin ellas, comportamiento actual (hace pasar T067); documentar `MASKING_NONCE_KEY` como opcional en `.env.example` (después de T-A; T082 regenera la referencia) y pasarla al motor en `sentinel/docker/compose.dev.yml` (después de T-B)
- [ ] T073 [US4] Referencia de conversación desde la extensión (T132): `pre_engine` de `sentinel/redirect/plugin.py` deriva `sentinel_conversation_ref` con clave del servidor desde el identificador de sesión de la herramienta y descarta el que mande el cliente
- [ ] T074 [US4] Afinidad de sesión (T129) en `sentinel/engine/redirect_guard.py` y la capacidad `session_affinity` en las capacidades del destino (hace pasar T068)
- [ ] T075 [US4] Conservar `cache_control` (T130) en `sentinel/redirect/faces/claude.py` cuando el destino lo declara (hace pasar T069)
- [ ] T076 [US4] Precio y tokens de caché (T133/T134) en `sentinel/engine/redirect_credentials.py` (`cost_params`), `sentinel/engine/redirect_guard.py` y la escritura en `routing_decision.extensions.redirect` (hace pasar T070; T071 queda verde o el guard marca los redirigidos como no cacheables por respuesta)
- [ ] T077 [US4] Panel (T135): casillas «marcas de caché» y «afinidad de sesión», campos de precio de caché y aprovechamiento por destino en `sentinel/frontend/redirect/DestinationsTab.tsx`, con su test Vitest en `sentinel/frontend/redirect/__tests__/DestinationsTab.cache.test.tsx`
- [ ] T078 [US4] 🐳 Verificación en vivo de SC-011 y SC-012 con un destino Azure (Cowork, ≥ 10 pasos, dato personal en el primer mensaje); los demás proveedores quedan 🟡; evidencia en `specs/057-porte-sentinel-068-redireccion-modelos/verificacion-cache.md`

**Checkpoint**: costo razonable en sesiones agénticas, con el enmascarado intacto.

---

## Phase 7: Tramo T-G — Documentación, quickstart y HANDOFF de vuelta (Polish & Cross-Cutting)

**Goal**: Definition of Done de `AGENTS.md`: documentación de producto honesta y verde, quickstart
validado con Azure y lo nuevo de base entregado a Sentinel (FR-003, FR-052; SC-013).

**Archivos del tramo**: plan §Tramos fila T-G.

- [ ] T079 [P] **Sitio de docs de producto (OBLIGATORIO, DoD)**, integraciones: páginas nuevas `docs/docs/integrations/claude-desktop.md`, `docs/docs/integrations/claude-code.md` y `docs/docs/integrations/cli-formato-openai.md` (configuración de cada herramienta, ids publicados, síntomas conocidos), marca neutra, el enmascarado descrito como «seudonimización reversible de identificadores detectados» (nunca «anonimización» ni «cumple con X»), template GUÍA/RUNBOOK de `docs/README.md`, leyenda 🟢/🟡/🔵 honesta (cara genérica 🟢 solo si T051 pasó); índice en `docs/docs/integrations/index.md`
- [ ] T080 [P] **Docs de administración**: `docs/docs/administration/redireccionamiento.md` (política, catálogo, publicados, reglas, estrategia «más barato», residencia `AMERICAS`, postura por defecto con enmascarado forzado en todo destino, relajaciones de cumplimiento por región y por destino, entidad responsable y jurisdicción de control, habilitación explícita con motivo y reglas vacías de fábrica) con matriz de compatibilidad por herramienta y proveedor: Azure 🟢 según T045/T051; DeepSeek, Qwen, GLM, Kimi, MiniMax y OpenRouter 🟡 hasta tener credencial. Textos (D3, D10; research R26): «seudonimización reversible», nunca «anonimización», «cumple con X» ni «transferencia lícita»; `AMERICAS` como criterio de riesgo, no de legalidad; la base legal de las transferencias la cubre Elea por fuera del sistema; toda la sección de residencia con 🟡 hasta la revisión legal. Enlace desde `docs/docs/administration/gobernanza.md`
- [ ] T081 [P] **Docs de operación**: activación de la extensión (`EXTRA_ENV_FILE`, variables de HANDOFF §2.1, S9/S11), rollback no soportado después de migrar (FR-004b), precauciones de la base compartida con el motor, en `docs/docs/operations/index.md` y `docs/docs/install-deploy/index.md`
- [ ] T082 🐳 `make -C deploy check-docs` verde (estructura, naming, 0-egress, deriva de references) y, si algún tramo tocó la API o `.env.example` después de T015, `make -C deploy docs-refs`
- [ ] T083 🐳 Ejecutar quickstart.md de punta a punta con Azure (incluida la medición de SC-003) y registrar resultados en `specs/057-porte-sentinel-068-redireccion-modelos/verificacion-quickstart.md`
- [ ] T084 [P] Registro de adaptaciones de Eleia (FR-003, research R3) en `specs/057-porte-sentinel-068-redireccion-modelos/CHANGELOG.md`: ADAPT-017, -022, -024, -026 reescritas, ADAPT-018 «no se trae (Eleia tiene `f8118e7`)», los desvíos anotados en los commits de T-A a T-F, cada uno con plan de salida
- [ ] T085 [P] `specs/057-porte-sentinel-068-redireccion-modelos/HANDOFF-elea-a-sentinel.md` (formato de los HANDOFF de 053–055): S9/S11, S13, T139/T094/T093/T090/T091, región como dato con `default_posture` (fábrica `reject_offregion`), relajaciones del enmascarado forzado, `control_jurisdiction` y la regla «en región» con su cambio de comportamiento para fichas sin control, semáforo por perfil, habilitación explícita por datos, OpenRouter con cero retención, verificación de despliegue de Azure, corrección del import `ApiKey`, `compose.dev.yml`, la migración nueva y su id, el riesgo de la base compartida y el resultado de la primera prueba en vivo de la cara genérica; sin editar nada del repo de Sentinel
- [ ] T086 Gate final antes de pedir merge: 🐳 `docker compose run --rm --no-deps backend pytest tests/ -q`, `pytest sentinel/tests -q`, `cd frontend && npm test`, Vitest de `sentinel/frontend`, `cd client && npm test`, 🐳 `make -C deploy check`, y `grep -rniE 'anonimiz|cumple con|conforme a|transferencia l[ií]cita' docs/docs sentinel/frontend` revisado a mano: ninguna coincidencia en lo nuevo describe el enmascarado como anonimización ni afirma cumplimiento (D10, research R26); salidas resumidas en el PR

---

## Dependencies & Execution Order

### Tramos

- **T-A** (Phase 1): sin dependencias; **bloquea todo**.
- **T-B** (Phase 2): depende de T-A; **bloquea C–G**. T019 (spike D14) es gate: si falla, se para y se
  re-planea.
- **T-C** (Phase 3, US1/US4): depende de T-B.
- **T-D** (Phase 4, US5): depende de T-C (usa `stream.py` de T042); **puede correr en paralelo con T-E**.
- **T-E** (Phase 5, US3): depende de T-C (re-toca `plugin.py` después de T040/T041).
- **T001** (enmienda constitucional aprobada por el owner, primera tarea de T-A) es gate de la integración de T-B: sin aplicarla, T-B no entra a `main`. La enmienda no fija los valores de Eleia del análisis legal (reglas vacías y `masked_all`), que son datos del seed (T028, T064).
- **T087** (D12) depende de T026 (columna) y alimenta a T054 y T060 en T-E.
- **T-F** (Phase 6, US4): depende de T-E (re-toca `redirect_guard.py` y `redirect_credentials.py`) y de
  T-C (`faces/claude.py`, `plugin.py`).
- **T-G** (Phase 7): depende de todos.

### Historias

- **US2** (P1, sin regresión): se cumple en T-A (T003, T014, T015) y se re-verifica en cada gate.
- **US1** (P1): T-B (catálogo) + T-C. Es el MVP mínimo.
- **US3** (P2): T-E (usa T026/T027 de T-B).
- **US4** (P3): T-C (stream, razonamiento) + T-F (caché).
- **US5** (P3): T-A (puerta) + T-D.

### Dentro de cada tramo

- Tests antes que implementación y fallando primero (TDD).
- Modelos y migración (T026) antes que la lógica que los usa (T027, T060).
- El gate del tramo cierra el tramo; el PR lo abre el coordinador.

## Parallel Opportunities

- **T-A**: T001 primero; después secuencial (cherry-picks en orden fijo); T014 puede escribirse en paralelo a T004–T013.
- **T-B**: T018, T021, T023, T024, T025 en paralelo después de T017; T087 después de T026.
- **T-C**: T031–T038 y T044 (tests y corpus) en paralelo; después T039–T043.
- **T-D ∥ T-E**: archivos disjuntos (plan §Tramos).
- **T-E**: T052–T059 en paralelo; después T060–T063.
- **T-F**: T067–T071 en paralelo; después T072–T077.
- **T-G**: T079–T081, T084, T085 en paralelo.

```text
# Ejemplo T-C: tests primero, en paralelo
T032 test_face_claude_campos_desconocidos.py
T033 test_face_claude_betas.py
T034 test_face_claude_count_tokens.py
T035 test_face_claude_contract.py
T036 test_face_claude_stream.py
```

## Implementation Strategy

1. **MVP**: T-A → T-B → T-C (US2 + US1 sobre Azure). Parar y validar con quickstart §1–§5.
2. **Incremento 2**: T-D (US5) en paralelo con T-E (US3).
3. **Incremento 3**: T-F (US4, caché).
4. **Cierre**: T-G (DoD).

Cada tramo termina con su gate y en un PR propio; ningún commit a `main`.

## Trazabilidad FR / SC → tareas

| Requisito | Tareas |
|---|---|
| FR-001, FR-002 | T003–T013, T015 |
| FR-003 | T084, T085 |
| FR-004 | T014 |
| FR-004a | T017 |
| FR-004b | T004, T016, T026, T081 |
| FR-004c | T020, T021 |
| FR-005, FR-010 | T029 |
| FR-006, FR-007 | T003, T018, T053 |
| FR-008 | T025, T060 (registro de cambios de la copia de `sentinel/`) |
| FR-009, FR-014, FR-016, FR-018 | T035 |
| FR-011, FR-012, FR-013 | T013, T017, T022, T030 |
| FR-015, FR-017, FR-019 | T030 (tests copiados), T035 |
| FR-020 | T022, T023 |
| FR-021, FR-030 | T052, T060, T063, T064, T080 |
| FR-022–FR-026, FR-028 | T053, T054, T055, T059, T060, T062 |
| FR-027 | T053, T056, T061 |
| FR-028a | T087, T054, T057, T060, T063 |
| FR-029 | T025, T027, T028, T057 |
| FR-030a | T059, T063 |
| FR-031 | T053, T057, T060, T064 |
| FR-031a | T053, T055, T057, T060, T063 |
| FR-032 | T058, T061 |
| FR-033, FR-034 | T035 |
| FR-035 | T032, T038, T039 |
| FR-036 | T037, T043 |
| FR-037–FR-039 | T036, T042 |
| FR-040, FR-042 | T033, T040 |
| FR-041 | T034, T041 |
| FR-043 | T068, T074 |
| FR-044 | T069, T075 |
| FR-045 | T067, T072, T073 |
| FR-046, FR-049 | T070, T076, T077 |
| FR-047 | T035, T053 |
| FR-048 | T071, T076 |
| FR-050 | T014, T015, T035 |
| FR-051 | T026, T030 |
| FR-052 | T079–T082, T086 (textos D3/D10) |
| FR-053–FR-056 | T012, T046–T051 |
| SC-001, SC-002 | T003, T015, T018 |
| SC-003 | T083 |
| SC-004 | T045 |
| SC-005, SC-006 | T054, T056, T065 |
| SC-007 | T036 |
| SC-008 | T035 |
| SC-009 | T030, T045 |
| SC-010 | T044 |
| SC-011, SC-012 | T066, T078 |
| SC-013 | T015, T082 |
| SC-014 | T051 |
| Requisito del owner (modelos chinos y económicos) | T024, T025, T027, T028, T057, T058, T080 |
| Decisiones legales del owner (D1, D2, D5, D12, D3/D10) | T028 (D1), T053 y T064 (D2), T053 y T057 (D5), T087 (D12), T079, T080 y T086 (D3/D10) |
