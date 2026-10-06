# Implementation Plan: Porte de la política de redireccionamiento de modelos (Sentinel 068) a Eleia

**Branch**: `057-porte-sentinel-068-redireccion-modelos` (plan escrito en `cluna-8/057-plan`) | **Date**: 2026-10-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/057-porte-sentinel-068-redireccion-modelos/spec.md` (aprobada; enmendada el 2026-10-06 por `speckit-clarify` con las decisiones legales del owner).
**Fuentes de solo lectura**: Sentinel `origin/main` `6a70855` (spec 068, paquete `sentinel/`) y el
HANDOFF `specs/HANDOFF-068-sentinel-a-elea.md` de la rama `docs/handoff-068-elea` (`8c525db`, con el
Anexo A de la cara genérica). Donde este plan dice «HANDOFF §x», se refiere a ese documento.

## Summary

Que Claude Desktop (Chat, Cowork, Code), Claude Code y las CLIs con formato OpenAI usen la pasarela
de Eleia pidiendo el modelo que conocen, mientras el administrador decide en el panel qué destino
real los sirve, con residencia para América. El enfoque técnico es el de la 068 (lógica en una capa
de extensión separada y la base solo con costuras) y se porta **tal cual** desde Sentinel en siete
tramos chicos y secuenciales:

| Tramo | Qué entrega | Origen |
|---|---|---|
| **T-A** | Enmienda constitucional aprobada (403 de residencia) y costuras de base por `cherry-pick -x`: los 16 commits de HANDOFF §1(a), después `9c17500` y `efb2c94` (Anexo A), y los dos archivos de ADAPT-024; con la suite verde y la pasarela idéntica sin extensión | HANDOFF §1(a), Anexo A |
| **T-B** | Paquete `sentinel/` copiado de `6a70855` (redirect, common, catalog, access), sus migraciones como segunda cabeza junto a `199fe429762a`, S9/S11 en el despliegue de Eleia, catálogo de Azure, entidad responsable y jurisdicción de control en la ficha (FR-028a, D12) y la base del requisito de modelos chinos y económicos | HANDOFF §1(b), §1(c), §2.1 |
| **T-C** | Cara Claude endurecida para Claude Code: T139 (campos desconocidos, `safeguards`), T094 (betas por lista permitida), T093 (`count_tokens`), stream y errores, más la prueba en vivo | 068 Phase 5, HANDOFF §2.4 |
| **T-D** | Cara OpenAI genérica sobre `/gw/v1/chat/completions` con alias, y su primera prueba en vivo | Anexo A, 068 contrato `cara-generica.md` |
| **T-E** | Residencia `AMERICAS` como dato del perfil de país con su postura por defecto (en Eleia, enmascarado forzado en todo destino, D2), relajaciones explícitas de cumplimiento por región o por destino (D5), regla «en región» con entidad y control (D12), semáforo por perfil y OpenRouter con cero retención | 068 Phase 4, HANDOFF §4.2; decisiones legales del owner |
| **T-F** | Caché del proveedor completa con la costura S13 (marcadores estables por conversación) | 068 Phase 9, research D22 |
| **T-G** | Documentación de producto, quickstart con Azure y HANDOFF de vuelta a Sentinel | DoD de `AGENTS.md`, spec FR-003 |

**Requisito del owner al aprobar la spec** (el cliente va a usar modelos chinos y modelos más
económicos en Claude Desktop y Claude Code). Queda con tarea y test explícitos (ver
[research.md §R14, §R17, §R19, §R23](./research.md) y `tasks.md`):

1. El catálogo admite destinos compatibles con OpenAI (DeepSeek, Qwen, GLM, Kimi, MiniMax…) y vía
   OpenRouter, y una regla puede elegir el más barato (T024).
2. La API oficial de proveedores chinos **puede** quedar bloqueada por defecto y habilitarse desde el
   panel con motivo registrado (FR-029): el **mecanismo** es por datos (listas editables de proveedores,
   hosts de `api_base` y jurisdicciones; T025–T027). **En Eleia las listas se siembran vacías** (D1 del
   análisis legal, decidida por el owner el 2026-10-06; T028): ningún destino nace bloqueado (T025).
3. Sin postura explícita rige la **postura por defecto** de la región, configurable
   (`reject_offregion` · `masked_offregion` · `masked_all` · `allow`; de fábrica `reject_offregion`, paridad
   con Sentinel). **En Eleia, `masked_all`** (D2): todo el tráfico redirigido sale con enmascarado
   forzado y analizador fail-closed, dentro y fuera de `AMERICAS`; se rechaza solo lo que no tiene
   jurisdicción de inferencia (FR-027, FR-031; research R23; T053, T064).
4. Los mismos modelos alojados en América (por ejemplo, en Azure o AWS en EE. UU., o por OpenRouter
   con proveedores de EE. UU.) **pueden** usarse sin enmascarado forzado solo con una relajación
   explícita de cumplimiento por destino, que exige alojador nombrado, jurisdicciones de inferencia,
   entidad y control cargadas y retención cero (D5; FR-031a; research R24; T053, T057). Una nube de una
   entidad controlada desde fuera de la región no cuenta como en región (D12; FR-028a; research R25;
   T087).
5. Para OpenRouter, cada pedido exige cero retención y la lista de proveedores permitidos (FR-032, T058).
6. La prueba real con esos proveedores queda 🟡 hasta tener credencial; la aceptación del MVP es solo
   con Azure (Clarifications P5).

## Technical Context

**Language/Version**: Python 3.12 (backend, `backend/Dockerfile:1`; extensiones del motor),
TypeScript + React 18 (panel, `frontend/package.json:19`).

**Primary Dependencies**: FastAPI, SQLAlchemy y Alembic (backend); motor LiteLLM fijado por digest
(`litellm/Dockerfile:6`; el spike de bases leyó en esa imagen `litellm 1.92.0` y
`litellm-proxy-extras 0.4.74`, pero la spec 053 cita 1.95.1 instalado: se re-verifica en T-B, ver
research R7); Vite y Vitest (panel); `httpx` (pasarela → motor); `tiktoken` (estimación local de
`count_tokens`, ya presente por la compresión del Principio V).

**Storage**: PostgreSQL. Las tablas de la extensión (`sentinel_redirect_*`, `ext_*`) viven en la base
del backend, en una rama de migraciones propia con etiqueta `sentinel_redirect` colgada de `010`
(HANDOFF §1(c)). Redis ya existe para la caché de respuestas del motor (`litellm/config.yaml:19-25`).

**Testing**: `pytest` (backend: `backend/tests/{unit,contract,integration}`; extensión:
`sentinel/tests/{unit,contract,integration}`), Vitest (`frontend`, `sentinel/frontend`), checks de shell
del release (`deploy/release/checks/*.sh`). Suite completa en contenedor: `docker compose run --rm
--no-deps backend pytest tests/ -q`, **solo con aviso previo al owner** (Docker).

**Target Platform**: servidor Linux on-premise con Docker Compose (instalación de Eleia, una empresa);
el código conserva el multi-tenant completo de la 068.

**Project Type**: aplicación web (backend + panel + motor) con una capa de extensión separada
(`sentinel/`), entregada por costuras.

**Performance Goals**: demora agregada por la pasarela hasta el primer contenido ≤ 50 ms p95 con la
política encendida (SC-010); `GET /gw/v1/models` < 1 s (FR-034); cambio de destino visible en < 1 min
(SC-009; `REDIRECT_CACHE_TTL_S=5`, HANDOFF §2.1).

**Constraints**: sin extensión, comportamiento idéntico (FR-001, FR-007, SC-001, SC-002); marca neutra
en todo lo visible (FR-050, `deploy/release/checks/prohibited_names.txt`); auditoría metadata-only
(FR-047, SC-008); credenciales cifradas (FR-013); nada de Docker sin aviso al owner; cambios a la base
mínimos, genéricos y retrocompatibles; las migraciones de la extensión no pueden empeorar el riesgo de
la base compartida con el motor (research R5).

**Scale/Scope**: una empresa, decenas de usuarios; 18 commits de base + 2 archivos; paquete `sentinel/`
de ~150 archivos copiado; 7 migraciones de la extensión más una nueva (research R13); 7 tramos de ≤ 15
tareas.

**NEEDS CLARIFICATION**: ninguna abierta en el plan. Las cuatro decisiones de diseño con opciones
(D1–D4 del plan: research R13–R16) las respondió el owner el 2026-10-06 (D2, D3, D4 = A; D1 = mecanismo
A). Los dos **valores de Eleia** que quedaban pendientes del análisis legal
(`specs/ANALISIS-TRANSFERENCIAS-AMERICA-2026-10.md`, rama `cluna-8/spike-transferencias-america`) los
decidió el owner el mismo día y la spec los recoge por `speckit-clarify` (Session 2026-10-06, decisiones
legales): reglas de bloqueo **vacías** (D1 del análisis, R14, T028) y postura por defecto **`masked_all`**
(D2 del análisis, R23, T064). Las decisiones D5 (relajación por destino, R24), D12 (entidad y control,
R25) y D3/D10 (textos, R26) agregan requisitos FR-028a y FR-031a.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitución 2.2.0 (`.specify/memory/constitution.md`). Según la spec (§Assumptions «Constitución»),
el Principio II se lee como la normativa del **perfil de país** (Ley 25.326 / AAIP), no GDPR ni EU AI Act.

| Principio | Cómo lo cumple el plan | Estado |
|---|---|---|
| I. Masking-first | El enmascarado reversible no cambia de dueño (guardrail del motor). S5b deja el informe de enmascarado que el guard de la extensión verifica (D16 de la 068); el forzado no se puede relajar con overrides del cliente (FR-027) y en Eleia es el **default de todo el tráfico redirigido** (`masked_all`, D2); solo cumplimiento lo quita, explícito y registrado (FR-031a), y nunca el fail-closed mientras rige. **Precedencia**: mientras el forzado rige, gana sobre `nlp_fail_mode=degrade` y `redact_enabled=false` de la instalación y la empresa ([D10] de la constitución), igual que la postura forzada de la 068 (D16); es más estricto, no una excepción, y la enmienda de T001 lo deja escrito. S13 (T-F) hace determinista el sufijo **por conversación** con clave del servidor: sigue impredecible para el usuario y no se comparte entre conversaciones ni personas (FR-045, research R18). Sin conversación, sufijo aleatorio como hoy | ✅ |
| II. Compliance (perfil de país) | Residencia como dato (FR-021), región `AMERICAS` editable (FR-030), postura más restrictiva gana (FR-024); `AMERICAS` se presenta como criterio de riesgo, no de legalidad, y el enmascarado como seudonimización reversible (D3, D10; research R26). El texto dice «violación de residencia … → 503»; la 068 y esta spec usan **403** `permission_error` para los rechazos de residencia de esta política (Sentinel lo enmendó en su 2.4.0). **Enmienda aprobada por el owner el 2026-10-06** (research R21); la aplica T001 con `speckit-constitution`, primera tarea y gate antes de integrar T-B | ✅ (enmienda aprobada, pendiente de aplicar) |
| III. Multi-tenant | Todas las tablas nuevas con `tenant_id` y RLS con el patrón de `010` (068 data-model); datos de instalación visibles a una empresa solo por oferta (FR-051) | ✅ |
| IV. Onboarding como datos | Destinos, ids públicos, reglas, posturas, región `AMERICAS` con su postura por defecto, reglas de bloqueo (vacías en Eleia), relajaciones, entidad y jurisdicción de control de cada destino y los destinos de Azure de la demo son **datos** (seed + panel), nunca código; ningún código nombra un país de preocupación (FR-020, FR-028a, FR-029, FR-030) | ✅ |
| V. Costos honestos | Precio único por destino, con lectura y escritura de caché; sin precio de caché se cobra a precio de entrada y se marca (FR-046, FR-049) | ✅ |
| VI. LiteLLM-native | Familias comodín `rdx-*` y guardrail `pre_call` (puntos de extensión documentados), sin parchear el motor; versión fijada sin cambios; el spike D14 se repite sobre esta versión (gate de re-plan, T019) | ✅ |
| VII. Container y white-label | Extensión entregada por imagen/montaje y variables (S1, S2, S4, S9, S11, S12), sin fork; respuestas neutras (FR-004, FR-050); los nombres internos `sentinel_*` de la extensión se conservan por paridad y no son visibles (spec §Assumptions «Nombres internos»); la aclaración de §VII (nombres de proveedor solo como datos del administrador o donde el protocolo los exige) entra en la misma enmienda aprobada (T001) | ✅ |
| VIII. Transparencia | La decisión de ruteo viaja a `audit_logs.routing_decision` por S7 con `extensions.redirect` (destino, cara, fidelidad, ajustes, postura, tokens de caché), sin contenido | ✅ |
| Security C-3 (sin fallback de auth) | `/v1/models` y `count_tokens` resuelven la identidad de la llave (66dfa61, 0669e03); sin llave válida no hay redirección | ✅ |
| Security C-5 (Fernet) | ADAPT-024: MultiFernet con rotación y descifrado estricto para las credenciales del catálogo | ✅ |

**Re-check post-diseño (Phase 1)**: sin violaciones nuevas. El data-model agrega una tabla de región
(con `default_posture`), una de reglas de habilitación explícita, una de relajaciones del enmascarado
forzado y una columna `control_jurisdiction` en la ficha del catálogo (D2-A y D1-A del plan; D2, D5 y
D12 del análisis legal), todas con `tenant_id` + RLS donde corresponde, sin contenido de pedidos, en una
sola migración nueva de la extensión. La postura por defecto de Eleia (`masked_all`) endurece el
Principio I; las relajaciones son explícitas, con motivo, de cumplimiento y auditadas (metadata-only).
El único desvío era el 403 de residencia: enmienda aprobada por el owner, la aplica T001. Re-check del
2026-10-06 tras las decisiones legales: sin violaciones nuevas.

## Project Structure

### Documentation (this feature)

```text
specs/057-porte-sentinel-068-redireccion-modelos/
├── spec.md              # aprobada; solo la enmiendan decisiones del owner por speckit-clarify (2026-10-06, decisiones legales)
├── plan.md              # este archivo
├── research.md          # Phase 0: decisiones R1–R26 (D1–D4 del plan con respuesta del owner; decisiones legales en R14, R23–R26)
├── data-model.md        # Phase 1: herencia de la 068 + deltas de Eleia
├── quickstart.md        # Phase 1: validación de punta a punta con Azure
├── contracts/
│   ├── costuras-base.md      # S1–S13 tal como quedan en Eleia (incluye S9/S11 y S13 nuevas)
│   ├── cara-claude.md        # delta de Eleia sobre el contrato de la 068 (T139, T094, T093)
│   ├── cara-generica.md      # delta de Eleia sobre el contrato de la 068
│   └── admin-api.md          # delta: región, reglas de habilitación, habilitación con motivo
├── checklists/requirements.md
├── tasks.md             # Phase 2 (speckit-tasks)
├── CHANGELOG.md         # T-G: registro de adaptaciones de Eleia (FR-003), creado en implementación
├── verificacion-{d14,cara-claude,cara-generica,cache,quickstart}.md  # evidencias, una por tramo (B, C, D, F, G)
└── HANDOFF-elea-a-sentinel.md  # T-G: lo nuevo de base para Sentinel, creado en implementación
```

### Source Code (repository root)

```text
.specify/memory/constitution.md    # T-A (T001): enmienda aprobada, por speckit-constitution
backend/
├── src/
│   ├── main.py                    # T-A: S4 (upgrade heads condicional), S1 (routers), montaje gateway_openai
│   ├── plugins.py                 # T-A: S1 (nuevo, 6161bf0)
│   ├── migration_locations.py     # T-A: S4 (nuevo, 1021c8e)
│   ├── api/gateway.py             # T-A: S2 + discovery neutro (FR-004)
│   ├── api/gateway_plugins.py     # T-A: S2 (nuevo)
│   ├── api/gateway_openai.py      # T-A: puerta /gw/v1/chat/completions (9c17500 + efb2c94)
│   ├── api/chat.py                # T-A: S6 (entradas ocultas)
│   ├── api/internal.py            # T-A: S7
│   └── services/encryption_service.py   # T-A: ADAPT-024
├── alembic/env.py                 # T-A: S4
└── tests/{unit,contract}/…        # T-A: tests de cada costura + no-regresión de la pasarela
litellm/extensions/
├── sentinel_guardrail.py          # T-A: S5b · T-F: S13
├── sentinel_guardian_policy.py    # T-A: S7 · T-F: S13
└── sentinel_audit_logger.py       # T-A: S7
frontend/src/{App.tsx, plugins/**} # T-A: S3 + ADAPT-026
deploy/
├── docker/compose.prod.yml, docker/entrypoint/backend.sh, Makefile   # T-A: S4, S12
├── release/{populate_volumes.sh, bundle.sh, render_profile.sh, fragment_merge.py}  # T-B: S9/S11
├── release/checks/test_extension_delivery.sh                         # T-B (nuevo)
└── redirect-seeds/                                                   # [ELEIA] datos de ejemplo
    ├── catalog-seed.azure-demo.yaml      # T-B: destinos de Azure de la demo (FR-020)
    ├── habilitacion-explicita.yaml       # T-B: reglas de bloqueo por defecto, vacías en Eleia (FR-029; D1 del análisis legal)
    └── regions.americas.yaml             # T-E: lista AMERICAS con default_posture masked_all (FR-030, FR-031; D2 del análisis legal)
sentinel/                          # T-B: copia de 6a70855 (sin onboarding/ ni la migración del wizard)
├── redirect/{plugin,resolver,residency,store,stream,regions_seed,…}.py, faces/{claude,generic}.py, api/
├── engine/{redirect_guard,redirect_authz,redirect_credentials,redirect_catalog,fragment_merge}.py, profile-fragment.yaml
├── catalog/ (incluye habilitacion.py nuevo), access/, common/
├── migrations/                    # rama `sentinel_redirect` (cabeza f7a3c1d9e508 → +1 en T-B: región, habilitación, relajaciones, control)
├── frontend/                      # pantalla única «Modelos» (replaces: models)
├── docker/{backend,frontend}.Dockerfile, docker/compose.dev.yml (nuevo, T-B), extensions.env.example (nuevo, T-B)
└── tests/                         # tests de la extensión + los nuevos de Eleia
```

**Structure Decision**: aplicación web con capa de extensión separada, igual que la 068 (research D1
de Sentinel). La base (`backend/`, `frontend/`, `litellm/extensions/`, `deploy/`) solo recibe costuras
**traídas tal cual** (T-A) o nuevas y genéricas que vuelven por HANDOFF (S9/S11 en T-B, S13 en T-F).
La lógica vive en `sentinel/`, copiada con sus nombres para mantener la paridad (HANDOFF §4.5). Lo
propio de Eleia (datos `AMERICAS`, seeds de Azure, textos, documentación) se marca **[ELEIA]** y vive
fuera de `sentinel/` cuando es dato (`deploy/redirect-seeds/`).

## Tramos, dependencias y propiedad de archivos

Orden obligatorio: **A → B → C → D → E → F → G**. T-A y T-B son prerrequisito duro de todo lo demás
(base y paquete). D puede correr en paralelo con E (no comparten archivos); el resto va en serie.

| Tramo | Archivos que **solo** ese tramo modifica (entre los tramos que pueden correr a la vez) | Gate de salida |
|---|---|---|
| T-A | `.specify/memory/constitution.md` (por `speckit-constitution`, T001), `backend/src/{main.py, plugins.py, migration_locations.py}`, `backend/src/api/{gateway.py, gateway_plugins.py, gateway_openai.py, chat.py, internal.py}`, `backend/src/services/encryption_service.py`, `backend/alembic/env.py`, `backend/Dockerfile`, `backend/tests/**` (de las costuras), `litellm/extensions/{sentinel_guardrail.py, sentinel_audit_logger.py, sentinel_guardian_policy.py}`, `frontend/src/{App.tsx, plugins/**}`, `frontend/{tailwind.config.js, vite.config.ts, vitest.config.ts}`, `deploy/docker/{compose.prod.yml, entrypoint/backend.sh}`, `deploy/Makefile`, `deploy/release/{INSTALL-CAMARA.md, checks/test_compose_extra_env_file.sh}`, `.env.example`, `docs/docs/api-reference/{configuration.md, openapi.json}`, `docs/docs/install-deploy/index.md` | suite backend + panel + Hub verdes; `make -C deploy check` (Docker, con aviso) |
| T-B | `sentinel/**` (copia + ajustes de catálogo, acceso y panel, incluida la ficha con entidad y control de T087), `sentinel/migrations/<hash>_redirect_region_y_habilitacion.py` (nueva), `deploy/release/{populate_volumes.sh, bundle.sh, render_profile.sh, fragment_merge.py}`, `deploy/release/checks/test_extension_delivery.sh`, `deploy/redirect-seeds/{catalog-seed.azure-demo.yaml, habilitacion-explicita.yaml}`, `specs/057…/verificacion-d14.md` | suites de la extensión verdes; spike D14 ok |
| T-C | `sentinel/redirect/{faces/claude.py, plugin.py, stream.py}`, `sentinel/tests/{fixtures/harness_corpus/claude/**, unit/test_face_claude_*.py, unit/test_guard_azure_parametros.py, contract/test_face_claude_*.py, integration/test_face_claude_stream.py, perf/**}`, `specs/057…/verificacion-cara-claude.md` | prueba en vivo con Claude Code y Claude Desktop sobre Azure |
| T-D | `sentinel/redirect/faces/generic.py`, `sentinel/tests/{contract,integration}/test_face_generic_*.py`, `backend/tests/contract/test_gateway_openai_policy_off_057.py`, `specs/057…/verificacion-cara-generica.md` | prueba en vivo con 2 harness sobre Azure |
| T-E | `sentinel/redirect/{residency.py, store.py, api/admin.py, regions_seed.py}`, `sentinel/redirect/plugin.py` (solo el camino de suscripción, después de T-C), `sentinel/engine/redirect_guard.py`, `sentinel/engine/redirect_credentials.py` (solo `CLIENT_CREDENTIAL_FIELDS`), `sentinel/catalog/{semaforo.py, store.py}`, `sentinel/frontend/{redirect/ResidencyTab.tsx, catalog/**}`, `deploy/redirect-seeds/regions.americas.yaml`, `sentinel/tests/**/test_residency_*.py`, `sentinel/tests/unit/{test_semaforo_region.py, test_guard_openrouter_zdr.py, test_redirect_residency.py, test_redirect_posture_roles.py}` | SC-005/SC-006 verificables en auditoría |
| T-F | `litellm/extensions/{sentinel_guardrail.py, sentinel_guardian_policy.py}` (S13), `sentinel/engine/{redirect_guard.py, redirect_credentials.py}` (después de T-E), `sentinel/redirect/{faces/claude.py, plugin.py}` (después de T-C), `sentinel/frontend/redirect/{DestinationsTab.tsx, __tests__/DestinationsTab.cache.test.tsx}`, `sentinel/catalog/models.py` (solo `FEATURES`, después de T-B), `.env.example` y `sentinel/docker/compose.dev.yml` (solo `MASKING_NONCE_KEY`, después de T-A y T-B), `backend/tests/unit/test_masking_nonce_conversacion.py`, `sentinel/tests/**/test_*cache*.py`, `sentinel/tests/unit/test_redirect_session_affinity.py`, `specs/057…/verificacion-cache.md` | SC-011/SC-012 medidos sobre Azure |
| T-G | `docs/docs/**` (incluido `docs/docs/install-deploy/index.md`, re-tocado después de T-A), `specs/057…/{CHANGELOG.md, HANDOFF-elea-a-sentinel.md, verificacion-quickstart.md}` | `make -C deploy check-docs` verde (Docker, con aviso) |

Los archivos que se re-tocan en serie (marcados «después de …») nunca están abiertos en dos tramos a
la vez: el tramo posterior arranca recién cuando el anterior está integrado.

## Riesgos y cómo los cubre el plan

| Riesgo | Mitigación en el plan |
|---|---|
| **Base compartida motor/backend** (HANDOFF §4.4; spike `specs/ANALISIS-SEPARAR-BASES-MOTOR-2026-10.md` en `cluna-8/spike-separar-bases-motor`): el migrador del motor puede borrar tablas ajenas en una base nueva o al subir la imagen del motor | Las migraciones de la extensión van solo a la base del backend, con prefijos `sentinel_redirect_`/`ext_`, sin tocar tablas `LiteLLM_*` ni `_prisma_migrations` (test T016); no cambian el orden de arranque ni la imagen del motor; el motor de la extensión no lee la base (habla por HTTP interno). Las pruebas en vivo se hacen sobre una base existente con su libro de migraciones del motor o con bases separadas, nunca sobre una base nueva con el backend primero (quickstart §0). Research R5 |
| Spike D14 no válido en la versión fijada del motor | T019 lo repite antes de las caras; si falla, gate de re-plan |
| Rollback imposible una vez aplicadas las migraciones de la extensión (HANDOFF §1(c)) | Documentado en operación (T-G) como «no soportado» (FR-004b) |
| Cara genérica nunca probada en vivo (Anexo A) | T-D hace la primera prueba en vivo con dos harness; hasta entonces 🟡 |
| `test_listado_generico_suma_auto_para_los_servicios` falla sin `fd515ff` (Anexo A §A.4) | T017 lo marca `skip` con motivo y referencia a `fd515ff` (fuera del MVP) |
| Bug latente `ApiKey` en `sentinel/access/api/admin.py` (HANDOFF §1(b)) | T017 lo corrige genérico con test; vuelve por HANDOFF |
| Valores de Eleia del análisis legal (bloqueo de APIs chinas, postura por defecto) | **Cerrado** el 2026-10-06: el owner decidió listas vacías (D1) y `masked_all` (D2); son datos del seed (T028, T064), con test de que todo funciona con listas vacías (T025) y con cada valor de `default_posture` (T053) |
| Que la documentación prometa cumplimiento legal | Textos con «seudonimización reversible», `AMERICAS` como criterio de riesgo, residencia 🟡 hasta la revisión legal (D3, D10; research R26; T080, T086) |
| Fichas sin jurisdicción de control al portar la regla «en región» a Sentinel | Cambio de comportamiento explicado en el HANDOFF (T085), con la sugerencia de cargar el dato antes de adoptarlo (research R25) |

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Rechazo de residencia con 403 en lugar del 503 del Principio II | Las herramientas reintentan un 503 (`x-should-retry`) y un rechazo de residencia no es reintentable; la 068 y Sentinel 2.4.0 ya lo usan | Mantener 503 haría que Claude Code y Desktop reintenten en bucle un pedido que nunca va a salir. Enmienda aprobada por el owner el 2026-10-06; la aplica T001 con `speckit-constitution` antes de integrar T-B |
| Una migración nueva en la rama de la extensión (región, reglas de habilitación, relajaciones y jurisdicción de control; D2-A y D1-A del plan, D2/D5/D12 del análisis legal) | La región, su postura por defecto, el bloqueo por defecto, las relajaciones y la jurisdicción de control tienen que ser datos editables (FR-021, FR-028a, FR-029, FR-030, FR-031a, Principio IV, research R23–R25) | Un archivo de datos sin tabla no es editable desde el panel (research R13 opción B) |
| Costura S13 nueva en la base | La caché del proveedor exige el mismo historial enmascarado byte a byte dentro de una conversación (FR-045, decisión del owner) | Desactivar el enmascarado para cachear rompe el Principio I; un sufijo fijo por persona crearía un seudónimo estable entre conversaciones |
