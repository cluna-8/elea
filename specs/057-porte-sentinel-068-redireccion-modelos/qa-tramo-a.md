# QA crítico del tramo T-A — 057 porte de la redirección de modelos (Sentinel 068)

**Rol**: qa-critico (segundo nivel: seguridad, datos sensibles, permisos, dominio crítico). **Fecha**: 2026-10-06.
**Rama**: `cluna-8/057-tramo-a` (`0f07819`), base de la rama `8999e27` (`main` avanzó a `8c96c2e`; no afecta al tramo).
**Alcance**: T001–T014 de `tasks.md` contra el HANDOFF de Sentinel (`8c525db:specs/HANDOFF-068-sentinel-a-elea.md`, 572 líneas, leído completo desde el
remoto `sentinel` ya fetcheado), `research.md` (R1, R2, R3, R21), `contracts/costuras-base.md`, la constitución 2.3.0 y las reglas de `AGENTS.md`.
**Método**: solo lectura y tests locales con el venv existente (`backend/.venv` del checkout principal; sin Docker, sin Postgres). Los experimentos auxiliares
(mutaciones, bisect por commit, export de OpenAPI, `gen_config_reference.py`) corrieron sobre copias en el scratchpad; el repo no se tocó salvo este reporte.
**Límite**: lo que usa Docker (`make -C deploy check`, `check-docs`, `docs-refs`, `test_compose_extra_env_file.sh` parte (b), la suite del backend en contenedor) **no se corrió**
(regla del coordinador: nada de Docker sin aviso al owner); queda como el gate T015 del tramo.

## Veredicto

**Sin bloqueantes en T001–T014.** Los 18 cherry-picks son exactamente los commits del HANDOFF, en su orden, con `-x`; las resoluciones de conflicto son las
«mínimas ensayadas» del HANDOFF §1(a)/§A.1 y de research R2, y la diferencia de cada commit contra su original se reduce a eso y a los `git rm` previstos. La
batería T003 es sensible (4 mutaciones sobre la pasarela la ponen en rojo) y pasa en los 18 commits del tramo sin tocar el JSON grabado. Los tests del tramo
(147), unit+contract completo, frontend (23) y client (43) están verdes salvo 6 tests de `test_route_parity.py` que piden Postgres y **fallan igual en la base
`8999e27`** (verificado). Hay **4 hallazgos medios**, **6 bajos** y 1 informativo (abajo); ninguno obliga a rehacer un cherry-pick.

**worker_done: succeeded** (no hay bloqueantes). Condiciones para abrir el PR del tramo, que **no** son hallazgos de código sino trabajo abierto del propio tramo:
T015 (gate 🐳 con `docs-refs`, ver H1) y T088 (`Dockerfile.standalone`, ver H5) siguen sin hacerse.

## Resumen de hallazgos

| Id | Sev. | Qué | Dónde | Requisito |
|---|---|---|---|---|
| H1 | Media (gate) | `openapi.json` deriva: falta `/api/v1/gw/v1/chat/completions` (confirmado exportando el OpenAPI en local) | `docs/docs/api-reference/openapi.json`; ruta en `backend/src/api/gateway_openai.py:70`, montada en `backend/src/main.py:131` | AGENTS.md DoD 3; T015; `check-docs` |
| H2 | Media | `FERNET_PREVIOUS_KEYS` y `GATEWAY_PLUGINS` son variables nuevas de operación que ni `.env.example` ni `configuration.md` documentan, y ninguna tarea abierta las cubre | `backend/src/services/encryption_service.py:28-32`, `backend/src/api/gateway_plugins.py:35`, `.env.example` (sin entradas) | AGENTS.md DoD 1 y 3; FR-003 |
| H3 | Media (aceptada) | Con `redact_enabled=false` el guardrail ahora llama al analizador solo para contar (antes no lo llamaba): latencia y carga nuevas sin extensión | `litellm/extensions/sentinel_guardrail.py:563-572` | FR-001 («idéntico»), QA M11, T084/T085 |
| H4 | Media | La ruta `/gw/v1/chat/completions` queda **siempre montada** (superficie pública nueva sin la extensión) y el sitio de docs no la menciona ni la pantalla de descubrimiento la lista | `backend/src/main.py:124-138`, `backend/src/api/gateway.py:2198` | FR-001/FR-004; contracts/costuras-base.md S2-OpenAI; AGENTS.md DoD 1 |
| H5 | Baja (abierta) | `Dockerfile.standalone` sigue con `upgrade head` | `backend/Dockerfile.standalone:35` | FR-004d, T088 (QA B1) |
| H6 | Baja | `_plain_passthrough` leyó el cuerpo **dentro** del `try` (→502); ahora lo lee fuera: una desconexión del cliente ya no se traduce en 502 | `backend/src/api/gateway.py:2152` | FR-001 (sin extensión, idéntico) |
| H7 | Baja | El script manual de capturas sigue buscando el rótulo viejo del menú | `frontend/e2e/029-screens.mjs:22` | ADAPT-026 (anotado en `55977c5`, sin arreglar) |
| H8 | Baja | La evidencia de T012 en `tasks.md` («unit+contract: 1314 passed, 12 skipped») no es reproducible tal cual: sin Postgres fallan 6 tests de `test_route_parity.py` (preexistentes) | `tasks.md:78,87` | veracidad de la evidencia (constitución, nota de honestidad SDD) |
| H9 | Baja | Referencias de numeración de Sentinel en comentarios y docstrings (spec 045/049/069/030…) que en Eleia apuntan a **otras** specs | `backend/src/api/gateway_openai.py:1`, mensajes de `29c66fe`, `323555b` | HANDOFF §4.3; T084 |
| H10 | Baja | Textos visibles nuevos con «Sentinel» en la ruta nueva; una frase («virtual key de Sentinel») no tiene paralelo en `gateway.py` | `backend/src/api/gateway_openai.py:100,108,122` | white-label (ver §4: no viola `prohibited_names.txt`) |
| H11 | Info | Con plugin `replaces`, el ítem base «Modelos» se oculta a **todos** los roles aunque la página de plugin sea solo `admin` (hoy `developer` ve «Modelos») | `frontend/src/App.tsx:66,140,220`; `frontend/src/plugins/registry.ts` | decisión de roles de la spec (anotada); a vigilar en T-F |

---

## 1. Cherry-picks: ¿es cada uno el commit esperado, con `-x`?

Método: de cada commit de `8999e27..HEAD` se leyeron los trailers `(cherry picked from commit …)`, se compararon con la lista del HANDOFF §1(a) + Anexo A + research R1,
y se comparó `git show` de cada commit contra `git show` del original (sin líneas `index`, sin números de hunk).

| # | HANDOFF | Pick en la rama | Trailer `-x` | Diferencia contra el original |
|---|---|---|---|---|
| 1 | `1021c8e` S4 | `c9289a2` | ✔ | **ninguna** (patch idéntico) |
| 2 | `7a4f65c` S6 | `36c44ec` | ✔ | 1 hunk de `chat.py` (`update_model_credential`): conserva `engine_params = body.resolved_engine_params()` de Eleia **y** `_visible_entries(...)` de Sentinel (`backend/src/api/chat.py:2413-2414`) = HANDOFF fila 2, R2 |
| 3 | `891d4d0` doc S12 | `ef5c228` | ✔ | ninguna salvo contexto de hunk |
| 4 | `6161bf0` S1 | `d16cd37` | ✔ | `main.py` solo con `mount_plugin_routers(app)` y **sin** `TrialReadOnlyMiddleware`; `configuration.md` con las filas de Eleia (el `.env.example` de Eleia conserva `SENTINEL_ENTITY_REGION=latam_ar`); `git rm` del registro de Sentinel. Logger `sentinel-secure-gateway.plugins` coincide con el prefijo de Eleia (`backend/src/main.py:18`) |
| 5 | `e3a5297` S2 | `5684e6f` | ✔ | `gateway.py`: sin `require_not_trial_expired`; `_byok_proxy` suma solo `ctx=None` (resolución mínima ensayada, R2); respuesta no-stream con `_respuesta_destino(ctx, …)` y mensaje de error de Eleia con `sanitize_engine_error`; comentarios de Eleia (specs 043/044) conservados |
| 6 | `933c513` S12 | `3f79838` | ✔ | ninguna salvo `git rm` |
| 7 | `1a454ed` S5b | `b920de0` | ✔ | ninguna; **sin** S5a (confirmado: `litellm/extensions/sentinel_guardrail.py:20` sigue diciendo que `/v1/responses` no está cubierto) |
| 8 | `9c7bf08` S7 | `323555b` | ✔ | solo comentarios de Eleia (spec 043); `git rm` |
| 9 | `8ceab22` S7 | `db4ba4a` | ✔ | ninguna |
| 10 | `faf94de` | `6832276` | ✔ | ninguna |
| 11 | `5a2d1aa` | `48a7bd9` | ✔ | falta `(error_fn or …)` en una línea: consecuencia de la firma mínima de #5; `9c17500` lo reincorpora |
| 12 | `66dfa61` | `e42f017` | ✔ | ninguna |
| 13 | `0669e03` | `b61b392` | ✔ | ninguna |
| 14 | `f63144d` S3 | `a382654` | ✔ | conserva `CambiarMiPasswordModal` de Eleia y el comentario Spec 044 de `vitest.config.ts` |
| 15 | `adb53d9` | `3f8c77c` | ✔ | **ninguna** |
| 16 | `1d8a3b7` ADAPT-026 | `55977c5` | ✔ | `git rm` de `specs/069-…/tasks.md`; conserva `flex h-screen` de Eleia (sin el banner de trial de Sentinel) |
| 17 | `9c17500` A.1 | `29c66fe` | ✔ | firma `ruta_motor="/v1/messages", error_fn=None, ctx=None`; `(error_fn or _anthropic_error)(…)` con `sanitize_engine_error` en no-stream y stream; en `main.py` primero `gateway_openai` (`:131`) y después `mount_plugin_routers` (`:138`), ambos antes de CORS; `git rm` de `deploy/clients/nix/config.yaml.tmpl` y `specs/045-…/tasks.md` |
| 18 | `efb2c94` A.1 | `1e5ea48` | ✔ | ninguna salvo `git rm` |
| — | `14edbc7` (2 archivos) | `13f2a28` | n/a (`checkout`) | `git diff 14edbc7 HEAD -- encryption_service.py test_encryption_multifernet.py` = **vacío**; no hay symlinks en el diff completo (`git diff --raw` sin modo `120000`) |

- **Orden**: igual al del HANDOFF (16 + `9c17500` + `efb2c94`, luego el `checkout` de ADAPT-026/024). ✔
- **Archivos que deben faltar** (todos ausentes): `docs/sentinel/04-REGISTRO-DE-CAMBIOS.md`, `specs/069-…/tasks.md`, `specs/045-clientes-y-herramientas-sentinel/tasks.md`,
  `deploy/clients/nix/config.yaml.tmpl`, el árbol `sentinel/` (es de T-B). ✔
- **Commits que NO deben traerse** (ausentes): `9fe188f` (`unmask_openai_chunk` sigue siendo el de `f8118e7`: `litellm/extensions/sentinel_guardian_policy.py:1105`,
  `sentinel_guardrail.py:721`); `fd515ff` (no hay `_resolver_auto`, `_con_auto_en_listado` ni `X-Guardian-Acting-User` nuevo fuera de `inspect.py`/`custom_auth.py` previos);
  `76ab37a` S5a. `TrialReadOnlyMiddleware` y `require_not_trial_expired`: 0 apariciones. ✔
- **Equivalencia de la cara genérica (HANDOFF §A.4)**: `git diff efb2c94 HEAD -- backend/src/api/gateway_openai.py backend/tests/contract/test_gateway_openai_route.py` = **vacío**. ✔
- **Trailers dobles**: cada pick lleva dos `(cherry picked from commit …)` (el de la base `guardian-secure` heredado del commit de Sentinel y el de Sentinel). Es esperable
  y trazable; no es defecto.
- **Mensajes de commit** (R3: ADAPT y «plan de salida» para T084): los picks con resolución manual o con cambio de camino o visible los traen (`5684e6f`, `36c44ec`, `d16cd37`,
  `55977c5`, `29c66fe`, `b920de0`, `323555b`, `3f79838`). Los picks sin conflicto de código solo anotan el `git rm`.
- **Otras ediciones fuera de los picks**: `4012ee4` (T001), `6023079`/`36a4d4e` (T003), `839ae6a` (T008), `13f2a28` (T013), `405f3fd` (T014): todas dentro del alcance de `tasks.md`.

## 2. Resoluciones de conflicto contra HANDOFF y research

| Conflicto | Debe quedar (HANDOFF / R2) | Estado |
|---|---|---|
| `chat.py` `update_model_credential` | `engine_params` de Eleia + `_visible_entries(...)` | ✔ `chat.py:2413-2414` |
| `main.py` (S1) | solo `mount_plugin_routers(app)` antes de CORS | ✔ `main.py:138` |
| `gateway.py` (i) import | `from . import gateway_plugins as gp` sin `require_not_trial_expired` | ✔ `gateway.py:77` |
| `gateway.py` (ii) firma | `ctx=None` (mínima) y luego, con `9c17500`, `ruta_motor`, `error_fn`, `ctx` | ✔ `gateway.py:1583` |
| `gateway.py` (iii) no-stream | `_respuesta_destino(ctx, …)` con el mensaje de Eleia | ✔ `gateway.py:1639-1641` |
| `main.py` (9c17500) | primero `gateway_openai`, después `mount_plugin_routers`, antes de CORS | ✔ `main.py:131,138` |
| `configuration.md` | filas de Eleia + las nuevas | ✔ (sin deriva contra `.env.example`: `gen_config_reference.py` en copia da el mismo archivo) |
| ADAPT-024 | solo 2 archivos, sin symlinks | ✔ |

Las ADAPT/desvíos de cada commit quedan en su mensaje para que T084 los consolide (R3). No hay todavía `CHANGELOG.md` de la 057: es T084 (T-G), no un defecto del tramo.

## 3. ¿La base queda idéntica sin la extensión?

Inventario de lo que cambia **sin** `GATEWAY_PLUGINS`/`PLUGIN_PACKAGES`/`ALEMBIC_EXTRA_VERSION_LOCATIONS`/`EXTRA_ENV_FILE`:

| Cambio | Idéntico | Evidencia |
|---|---|---|
| S1 `mount_plugin_routers` | ✔ con la variable vacía no importa ni monta nada | `backend/src/plugins.py:81-90`, `test_plugin_routers.py` |
| S2 hooks | ✔ con `ctx=None` cada helper hace lo de antes (`_respuesta_destino`, `routing_of`, `wrap_stream` solo con ctx) | `gateway.py:1541-1585,1685,2101`; batería T003 |
| S4 `upgrade heads` | ✔ sin variable: `head` y una cabeza (`199fe429762a`, calculada con `ScriptDirectory` en este árbol); sin cambios en `backend/alembic/versions` | `migration_locations.py:43-45`, `Dockerfile`, `entrypoint/backend.sh` (`set -e` verificado: `[ -n … ] && …` no aborta) |
| S5b `masking_report` | ⚠ **no idéntico con `redact_enabled=false`** (H3) | `sentinel_guardrail.py:563-572` |
| S6 entradas ocultas | ✔ sin `model_info.plugin_owner` no se filtra nada | `chat.py:777-799`, `test_models_hidden_entries.py` |
| S7 `routing_decision` confiable | ✔ clave ausente ⇒ payload y fila idénticos; sanea por vocabulario cerrado y acota `extensions` (≤8 espacios × 24 claves, ≤4 KB, escalares) | `internal.py:259-329`, `sentinel_audit_logger.py:333-342,399-401`; columna ya existe (`backend/src/models/audit.py:47`) |
| S12 `EXTRA_ENV_FILE` | ✔ por defecto `/dev/null`, `required: false` (el test (b) con `docker compose config` **no se corrió**: Docker) | `compose.prod.yml` |
| ADAPT-024 MultiFernet | ✔ aditivo: sin `FERNET_PREVIOUS_KEYS` es un `MultiFernet` de una clave; formato de token de Fernet | `encryption_service.py:6-33` |
| S2-OpenAI `/gw/v1/chat/completions` | ⚠ **ruta nueva siempre montada** (H4), aceptada por contrato | `main.py:131` |
| ADAPT-026 «Modelos & Ollama» → «Modelos» | ⚠ **cambio visible sin extensión**, anotado en `55977c5` y en docs (`INSTALL-CAMARA.md`, `install-deploy/index.md`) | `frontend/src/App.tsx:66` |
| `gw_info` neutro (T014) | cambio de texto intencional (FR-004) | `gateway.py:2201` |
| `_plain_passthrough` | ⚠ lectura del cuerpo fuera del `try` (H6) | `gateway.py:2152` |

No hay cambios de esquema, de migraciones ni de variables obligatorias. Los otros cinco cambios visibles o de camino están anotados o aceptados por contrato (H3, H4,
ADAPT-026); H6 es un matiz que nadie documentó.

## 4. White-label y secretos

- **`prohibited_names.txt`** (`litellm`, `berriai`, `presidio`): 0 apariciones nuevas en cadenas visibles. Las 5 líneas añadidas que contienen esos términos son
  identificadores internos (`_LITELLM_UPSTREAM`, `litellm_metadata`, `_PRESIDIO_URL`, `presidio_analyze`). `GET /api/v1/gw` no nombra ninguno
  (`test_gw_info_neutral.py`, rojo→verde con `405f3fd`; el respaldo de la lista se vigila contra el archivo). `litellm` aparece **una** vez en el `openapi.json`
  committed y en el recién exportado (preexistente, igual en ambos).
- **«Sentinel» en lo visible**: no está en `prohibited_names.txt` ni en `prohibited_brand.txt` aplicado a este repo (esa lista solo gobierna el zip de la extensión de
  navegador). Las cadenas nuevas siguen el patrón preexistente `[Sentinel Gateway] …` del `gateway.py` de Eleia (la propia constitución VII nombra «Sentinel Gateway»
  como el nombre neutro de los prefijos `litellm.*`). Único matiz: «virtual key de Sentinel» (`gateway_openai.py:100`), sin paralelo en `gateway.py` (H10).
- **Marca de Eleia en la base**: ninguna línea añadida a `backend/src`, `litellm`, `frontend/src`, `deploy`, `.env.example` nombra Elea/Eleia ni `latam_ar`. ✔ (regla de base genérica).
- **Secretos**: búsqueda de patrones (`sk-…`, `AKIA…`, `BEGIN`, JWT, `password=`) en el diff sin `specs/`: solo el literal de fixture
  `sk-ABCDEFGHIJ0123456789` de la batería (el dato falso que dispara el bloqueo por secreto). `.env.example` solo suma variables vacías. ✔
- **Auditoría metadata-only**: `masking_report` es solo conteos (`{completed, degraded, detected, masked}`); `routing_decision` se sanea a etiquetas y escalares acotados
  y solo se acepta si la escribió código del motor (la marca es el tipo `EngineRoutingDecision`, no una clave que el cliente pueda sembrar:
  `sentinel_guardian_policy.py:400-430`). Ningún cambio escribe texto de prompt, PII ni tokens. ✔

## 5. La batería de no-regresión cubre lo que dice T003

`backend/tests/contract/test_gw_no_regresion_057.py` (26 casos) + `gw_no_regresion_057.golden.json`.

| Pide T003 | Cobertura |
|---|---|
| `/gw/v1/messages` llave del producto, no-stream y stream | `byok_mensajes_no_stream`, `byok_mensajes_stream`, `byok_llave_en_authorization`, errores del motor (429, stream 503), motor caído, sin llave (401), `auto` |
| `/gw/v1/messages` suscripción, no-stream y stream | `suscripcion_no_stream`, `suscripcion_stream`, anónima, PII enmascarada y restituida, bloqueo por secreto, error del proveedor, proveedor caído, cuerpo no-JSON, modelo reservado |
| `/gw/v1/messages/count_tokens` | `count_tokens_byok`, `count_tokens_suscripcion`, `…sin_llave_es_401` |
| `/gw/v1/models` | `models_byok`, `models_suscripcion`, `…sin_llave_es_401`, `models_con_query_se_reenvia` |
| cuerpo, estado, fila de auditoría | `observar()` compara estado, tipo, cuerpo (normalizando marcadores), lo que llegó al upstream (URL, cabeceras de contrato, cuerpo), filas de `_audit` (modelo, tokens, estado, entidades, capas, bloqueo, tenant, llave, kwargs) y eventos de monitor |
| «contra lo grabado hoy» | JSON grabado en `6023079`, **antes** del primer cherry-pick (`c9289a2`), y sin cambios después (`git log --follow` = un solo commit) |

Verificación independiente:
- **Bisect por commit**: la batería (versión de `HEAD` + JSON grabado) corrida contra el árbol de cada uno de 18 commits del tramo (`6023079`, `c9289a2`, `36c44ec`,
  `d16cd37`, `5684e6f`, `3f79838`, `b920de0`, `323555b`, `db4ba4a`, `6832276`, `48a7bd9`, `e42f017`, `b61b392`, `a382654`, `29c66fe`, `1e5ea48`, `13f2a28`, `405f3fd`):
  **26 passed en todos**.
- **Mutación** sobre una copia de `HEAD`: alterar un byte semántico del cuerpo en `_respuesta_destino` → 6 casos rojos; `routing_of(None)` devolviendo un dict → 8 rojos;
  cambiar la URL al motor → 7 rojos; 5xx→502 sin `ctx` → 2 rojos. Restaurada → 26 verdes. Un detalle: agregar un espacio final al JSON **no** se detecta
  (el cuerpo se compara parseado); es una decisión razonable de la batería, no un hueco que importe.
- La edición posterior `36a4d4e` (la batería ignora kwargs de auditoría con valor `None`, `test_gw_no_regresion_057.py:271`) queda justificada: `routing_decision=None` es el default del
  escritor y la fila escrita es la misma; una regresión que pase un valor distinto de `None` sigue siendo roja (mutación M2).
- **Límites** (no son defectos): la batería monta `gateway.router` solo (no `src.main:app`: el orden de montaje lo cubren `test_plugin_routers.py` y
  `test_gateway_openai_route.py`), usa dobles para `_audit` (la forma real de la fila exige Postgres) y no incluye `/gw/v1/chat/completions` (tiene su propio contract test).
  T018 la reutiliza para el caso «extensión montada, política apagada» (T-B).

## 6. Tests corridos (venv local, sin Docker)

| Qué | Resultado |
|---|---|
| Tests del tramo (`test_gw_no_regresion_057`, `test_gw_info_neutral`, `test_gateway_openai_route`, `test_alembic_extra_versions`, `test_models_hidden_entries`, `test_plugin_routers`, `test_gateway_plugins`, `test_guardrail_masking_report`, `test_guardrail_redact_off_057`, `test_audit_routing_decision`, `test_encryption_multifernet`) | **147 passed** en 22,6 s |
| `pytest tests/unit tests/contract` (HEAD) | **1339 passed, 12 skipped, 6 failed** en 263 s; los 6 son `tests/contract/test_route_parity.py` (`masks_upstream_and_unmasks_reply`, `redact_off_header_is_ignored`, `redact_on_header_forces_masking`, `streaming_unmask[False/True]`, `forwards_oauth_verbatim`): el pre-check de auditoría da 503 porque el host `db` no resuelve |
| Los mismos 6 en la base `8999e27` (`git archive` a scratchpad) | **6 failed, 15 passed** (222 s): **preexistentes, no regresión** |
| Alembic (`ScriptDirectory`, sin variable) | `heads = ['199fe429762a']` |
| `cd frontend && npm test` | 7 archivos, **23 passed** (incluye `src/plugins/registry.test.ts`); `npx tsc --noEmit` limpio |
| `cd client && npm test` | **43 passed**, 0 failed |
| Deriva de `configuration.md` (`docs/gen_config_reference.py` sobre copia) | sin deriva (47 variables) |
| Deriva de `openapi.json` (`backend/scripts/export_openapi.py` local, `BRAND_NAME="AI Gateway"`) | **deriva**: falta la ruta `/api/v1/gw/v1/chat/completions` (único path distinto; 63 líneas; esquemas iguales) → H1 |
| Resto de `backend/tests` (`--ignore=tests/unit --ignore=tests/contract`, sin Postgres) | **362 passed, 103 skipped, 3 failed** en 169 s; los 3 son `tests/integration/test_surface_routing.py` (`passthrough_routes_to_anthropic_verbatim_oauth`, `passthrough_forwards_anthropic_headers`, `xsentinel_key_excluded_stays_passthrough`), los mismos 3 preexistentes que declara T003 (piden Postgres para el pre-check de auditoría) |

## 7. Hallazgos en detalle

### H1 — `openapi.json` desactualizado (media; es el gate T015, no un defecto de T001–T014)
- **Evidencia**: exportar el OpenAPI de `HEAD` en local y compararlo con `docs/docs/api-reference/openapi.json` da una sola diferencia: el path nuevo
  `/api/v1/gw/v1/chat/completions` (`backend/src/api/gateway_openai.py:70`, montado en `backend/src/main.py:131`). `test_docs_apiref.sh` (a) lo marcaría rojo.
- **Requisito**: AGENTS.md DoD 3 («si cambió la API… `make -C deploy docs-refs` corrido»), HANDOFF §A.3, T015.
- **Corrección**: T015 (🐳, con aviso al owner). No regenerar a mano.

### H2 — Variables de operación nuevas sin documentar (media)
- **Evidencia**: `FERNET_PREVIOUS_KEYS` se lee en `encryption_service.py:28-32` y `GATEWAY_PLUGINS` en `gateway_plugins.py:35`; ninguna está en `.env.example` ni en
  `docs/docs/api-reference/configuration.md` (`grep` = 0). `FERNET_SECRET_KEY` sí (`.env.example:49`). El `.env.example` de Sentinel `6a70855` sí trae `FERNET_PREVIOUS_KEYS`
  (línea 53): se perdió porque T013 trajo solo 2 archivos de `14edbc7`. `EXTRA_ENV_FILE` sí está documentada (`install-deploy/index.md`, cabecera de `compose.prod.yml`).
  Ninguna tarea abierta menciona `FERNET_PREVIOUS_KEYS` (T081 cubre `EXTRA_ENV_FILE` y las variables de HANDOFF §2.1, sin esta; T104 solo documenta `on_startup`).
- **Requisito**: AGENTS.md DoD 1 y 3 (la doc de producto es parte de la feature; si cambió `.env.example`, `docs-refs`), HANDOFF §2.1.
- **Corrección** (por `speckit-tasks`, no a mano): sumar a T015/T081 la entrada de ambas en `.env.example` (comentario genérico, valor vacío) y regenerar con
  `docs-refs`. El valor por defecto vacío no cambia comportamiento.

### H3 — Camino nuevo con `redact_enabled=false` (media, aceptada y anotada)
- **Evidencia**: antes de S5b, con el enmascarado apagado el guardrail no llamaba al analizador; ahora llama a `_analyze(inspect_text)` solo para contar
  (`sentinel_guardrail.py:563-572`). Un fallo del analizador no bloquea ni degrada (`presidio_analyze` convierte todo error en `NlpUnavailableError`,
  `sentinel_guardian_policy.py:714-725`; verificado por `test_guardrail_redact_off_057.py`). Pero con el analizador lento o caído **cada pedido de una empresa con
  enmascarado apagado espera hasta `SENTINEL_NLP_TIMEOUT_S`** (15 s por defecto en `sentinel_guardian_policy.py:74`; el compose de Eleia lo fija en 60 s, `docker-compose.yml:100`) antes de seguir; y sin `NLP_ANALYZER_URL` suma un
  `WARNING` por pedido (`:558`) aun con el enmascarado apagado.
- **Requisito**: FR-001/SC-001 («idéntico sin extensión»), QA M11 (`tasks.md:83`: «se anota para T084/T085»).
- **Estado**: anotado en `b920de0` y en T008; **falta** que T085 lo mida (latencia y carga) y que T084 lo registre. Corrección posible, genérica y vuelve por HANDOFF:
  contar con un tope de tiempo corto propio cuando `redact_enabled=false`.

### H4 — Ruta nueva siempre montada, sin documentar ni anunciar (media)
- **Evidencia**: `main.py:124-138` monta `gateway_openai` sin variable (contracts/costuras-base.md S2-OpenAI: «siempre montada»; HANDOFF §A.3: «se monta siempre»). Es una
  superficie pública nueva para **toda** instalación (con virtual key y byok, 401 sin llave; `gateway_openai.py:93-101`). Ni `GET /api/v1/gw` la lista
  (`gateway.py:2198`; `test_gw_info_neutral.py` fija que la lista de endpoints no cambie) ni `docs/docs/**` la mencionan (`grep chat/completions` = solo `openapi.json` tras
  regenerar). Su verificación en vivo está marcada 🟡 en Sentinel (HANDOFF §A, «Estado real»).
- **Requisito**: FR-001 (retrocompatibilidad), AGENTS.md DoD 1 (páginas afectadas actualizadas, leyenda 🟢/🟡/🔵 honesta), T079.
- **Estado**: aceptado por contrato y por el owner (cara genérica en el MVP). Corrección: que T079 la documente con **🟡** (no 🟢) y decidir en T014/T079 si
  `endpoints` de la pantalla de descubrimiento la lista; mientras no se verifique en vivo, ningún texto del sitio debe prometerla como verificada.

### H5 — `Dockerfile.standalone` (baja, trabajo abierto del tramo)
- **Evidencia**: `backend/Dockerfile.standalone:35` sigue en `alembic upgrade head`; con `ALEMBIC_EXTRA_VERSION_LOCATIONS` en la imagen publicada habría dos cabezas y el
  arranque fallaría con «Multiple head revisions». `main.py:21-43` además traga el error de migración (el arranque sigue).
- **Requisito**: FR-004d, T088 (QA B1). No es de T001–T014; T088 queda en la fase del tramo (`tasks.md:90`) y T-A no está completo hasta cerrarla.

### H6 — Lectura del cuerpo fuera del `try` en `_plain_passthrough` (baja)
- **Evidencia**: antes, `await request.body()` corría dentro del `try … except Exception → 502` (`up = await client.post(url, headers=up_headers, content=await request.body())`);
  ahora se lee antes del `try` (`gateway.py:2152`). Una desconexión del cliente en `count_tokens` pasa de 502 a una excepción no capturada. Es el patrón de `e3a5297` tal como
  está en Sentinel (no es una resolución de Eleia) y la batería no lo ve (el cuerpo siempre llega).
- **Requisito**: FR-001 («idéntico»). **Corrección** (opcional, retrocompatible y genérica): mover la lectura al `try` o capturar el error en el mismo `except`.

### H7 — Script de capturas con el rótulo viejo (baja)
- `frontend/e2e/029-screens.mjs:22` busca `nav: 'Modelos & Ollama'`; con ADAPT-026 deja de existir. Anotado en `55977c5` y sin arreglo; no corre en `npm test`.
  Corregir al pasar por T-F (cuando se defina el rótulo definitivo) para no dejar una prueba manual rota.

### H8 — Evidencia de `tasks.md` no reproducible tal cual (baja)
- `tasks.md:78` (T003) y `:87` (T012) declaran «unit+contract: 1203 / 1314 passed, 12 skipped» sin fallos; `pytest tests/unit tests/contract` sin Postgres da 1339 passed, 12 skipped y **6 failed** (los de
  `test_route_parity.py`, que fallan igual en `8999e27`). Probablemente se excluyó ese archivo o la corrida tenía una base alcanzable; conviene decirlo. La nota de honestidad SDD de la constitución pide que lo declarado como
  verificado lo sea en las condiciones declaradas. En cambio, la línea base de T003 para el resto (3 failed de `test_surface_routing.py`) **sí** se reproduce (§6).

### H9 — Numeración de Sentinel en comentarios (baja)
- Los picks traen referencias a la numeración de Sentinel: «spec 045» en `gateway_openai.py:1` y en el asunto de `29c66fe` (en Eleia la 045 es
  `045-generacion-carga-documentos-eleia-hub`), «spec 049» (en Eleia, `049-motor-generacion-documentos`), «069», «030». Es lo previsto por HANDOFF §4.3 («registrar el alias»)
  y por R3 (T084), pero hoy ningún artefacto de la 057 lo deja dicho; T084 debe incluir la tabla de alias para que nadie siga una referencia a la spec equivocada.

### H10 — Textos visibles con «Sentinel» en la ruta nueva (baja)
- `gateway_openai.py:100` («virtual key de Sentinel (sk-sentinel-…)»), `:108` y `:122` (`[Sentinel Gateway] …`). El prefijo es el del producto y ya está en 11 mensajes de `gateway.py` (p. ej. `:1604`, `:2146`);
  no viola `prohibited_names.txt`. Si el owner quiere neutralidad total, es una decisión aparte y coordinada con Sentinel (HANDOFF §4.5: no renombrar al portar). Para paridad
  con `gateway.py:1604` («byok requiere una virtual key (sk-sentinel-…)») se podría quitar «de Sentinel».

### H11 — `replaces` y roles (informativo)
- `replacedBaseIds(pluginPages)` se calcula sobre **todas** las páginas de plugin, no solo las visibles (`App.tsx:140`), y `ModelsPage` se oculta con `!replaced.has("models")`
  (`:220`). Si la página de plugin que sustituye «Modelos» se declara solo `admin` (default fail-closed, `registry.ts`), `developer` —que hoy ve «Modelos»
  (`App.tsx:66`: `legacyRoles: ["admin","developer"]`)— pierde la pantalla. El comentario de `App.tsx:138-139` lo declara como decisión de la spec. No afecta sin extensión;
  T-F debe declarar `roles` que incluya a `developer` si se quiere conservar ese acceso, y T-F/T085 verificarlo en el panel.

## 8. Lo que no se pudo verificar y por qué

- **Docker**: `make -C deploy check`, `check-docs`, `docs-refs`, `docker compose run … pytest tests/`, `test_compose_extra_env_file.sh` parte (b) y los `test_*_whitelabel.sh` que
  hacen `docker build`. Sustitutos locales usados: export de OpenAPI y `gen_config_reference.py` sobre copias, búsqueda manual de nombres prohibidos y de secretos.
- **Postgres**: los tests de integración que lo piden (y 6 de `test_route_parity.py`) no corren en esta máquina; se verificó que fallan igual en la base.
- **Evidencia de T-A «antes y después de cada cherry-pick»**: reproducida con el bisect de §5 para la batería T003; no se repitió el resto de la suite por commit.
- La corrida de `tests/integration` y demás se hizo sin Postgres: 103 tests se saltan solos y 3 fallan por el pre-check de auditoría (preexistentes, ver §6); lo que esos tests cubren de verdad (filas de `audit_logs`, RLS, migraciones contra una base real) **no está verificado** aquí y queda para T015 en contenedor.

## 9. Resumen de comandos corridos

```
git log / git show / git diff            # trailers -x, diff pick-vs-original (18 pares), diff 8999e27..HEAD, archivos ausentes y presentes
cd backend && pytest <11 archivos del tramo>                  # 147 passed
cd backend && pytest tests/unit tests/contract                # 1339 passed, 12 skipped, 6 failed (route_parity, sin Postgres)
cd <git archive 8999e27>/backend && pytest tests/contract/test_route_parity.py   # 6 failed, 15 passed (preexistente)
cd backend && pytest tests --ignore=tests/unit --ignore=tests/contract           # 362 passed, 103 skipped, 3 failed (preexistentes)
bisect.sh: batería T003 (versión HEAD) contra 18 commits del tramo                 # 26 passed en todos
mutaciones M1–M4 sobre copia de HEAD                                               # rojo (6/8/7/2 casos); restaurada: 26 verdes
cd frontend && npm test && npx tsc --noEmit                   # 23 passed; tsc limpio
cd client && npm test                                         # 43 passed
backend/scripts/export_openapi.py (local) vs docs/.../openapi.json                 # 1 path de diferencia (H1)
docs/gen_config_reference.py sobre copia                      # sin deriva
alembic ScriptDirectory (sin variable)                        # heads = ['199fe429762a']
```
