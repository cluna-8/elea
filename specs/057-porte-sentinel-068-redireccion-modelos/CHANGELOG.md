# CHANGELOG — spec 057 (porte de la redirección de modelos de Sentinel 068): registro de adaptaciones de Eleia

> T084 (FR-003, research R3). Consolida **todo lo que Eleia hizo distinto de Sentinel** (`cluna-8/sentinel`
> `6a70855`, con su HANDOFF `8c525db`) en los tramos T-A a T-F, cada entrada con su **plan de salida**: qué
> habría que hacer para volver a ser idéntico a la base, o por qué no hace falta. Eleia no tiene
> `docs/sentinel/04-REGISTRO-DE-CAMBIOS.md` (se borra en cada cherry-pick, HANDOFF §1(a)): este archivo lo
> reemplaza. Lo que Eleia **agregó** a la base (S9, S11, S13–S17, la migración nueva, etc.) y tiene que
> volver a Sentinel está en [`HANDOFF-elea-a-sentinel.md`](./HANDOFF-elea-a-sentinel.md); acá solo se
> anotan las **adaptaciones** (lo que se tocó al traer) y los **desvíos** (lo que no se trajo o se cambió).
>
> Convenciones: `archivo:línea` es del árbol de este repo al cierre de T-G. «Plan de salida: ninguno»
> = la adaptación es genérica y Sentinel puede adoptarla tal cual (candidata a la base). Los ids de commit
> son los de la rama `cluna-8/057-*`; los de Sentinel van con el prefijo `sentinel:`.

## Estado al cierre del tramo T-G (docs)

- **Hecho**: T079, T080, T081 (documentación de producto), T084 (este archivo) y T085 (HANDOFF). Marcados
  `[x]` con evidencia en `tasks.md`.
- **Pendiente del coordinador, con Docker** (T082, T083, T086) **y de las pruebas en vivo** (T019 —hecha el 2026-10-06, `verificacion-d14.md`—, T045, T051, T066,
  T078): hasta que se corran, **toda la sección de residencia, las dos caras y la caché del proveedor figuran 🟡
  en la documentación**, y ninguna página sube un estado que el código no respalde.
- **Pendiente de T-H** (repo `cluna-8/elea-installer`: T089, T100–T103): el instalador no activa todavía la
  extensión; la documentación lo marca 🔵. **Superado el 2026-10-07**: T100, T101 y T103 están hechas en el
  instalador y T102 se probó con contenedores reales; queda abierta T089 (ver §4d).

## 1. Adaptaciones al traer las costuras de base (T-A)

Todos los commits de Sentinel entraron por `git cherry-pick -x` (línea `(cherry picked from commit …)` en el
mensaje). Lo de abajo es lo que se resolvió distinto del commit de origen.

| ID | Qué | Dónde | Commit de Eleia | Plan de salida |
|---|---|---|---|---|
| **ADAPT-017** (reescrita) | Puerta de chat estándar (`/gw/v1/chat/completions`, spec 045): `_byok_proxy` queda con la firma `(…, ruta_motor="/v1/messages", error_fn=None, ctx=None)`; en no-stream y en el error del stream se usa `(error_fn or _anthropic_error)(…)` con `sanitize_engine_error(str(exc))` **de Eleia** (el texto de Sentinel sin sanear no se trae) y `_respuesta_destino(ctx, …, exito_mapeable=True)` de S2. Archivo nuevo `gateway_openai.py` (preámbulo delgado: saneo del modelo declarado, corte por auditoría en la puerta, resolución de «auto»; solo con llave virtual, 401 honesto sin ella) | `backend/src/api/gateway.py:1605-1607` (firma), `backend/src/api/gateway_openai.py:47` (`_openai_error`), `:71` (`gw_chat_completions`) | `29c66fe` (`9c17500`), `1e5ea48` (`efb2c94`, hooks S2 en la puerta) | Ninguno: genérica, candidata a la base. El `git rm` de `deploy/clients/nix/config.yaml.tmpl` es del perfil de cliente de Sentinel y no se trae |
| **ADAPT-018** (no se trae) | `sentinel:9fe188f` (restauración de marcadores en el stream OpenAI): **Eleia ya tiene `f8118e7`** (spec 050) con el mismo arreglo; traer el de Sentinel duplicaría el comportamiento. El contrato de la cara genérica nombra `f8118e7` | `litellm/extensions/sentinel_guardrail.py` (sin cambios de T-A) | — | Cuando Sentinel adopte `f8118e7` (HANDOFF de la 050, §2) se descarta su `9fe188f`. No hay nada que hacer en Eleia |
| **ADAPT-022** (orden de montaje y S2) | En `main.py` se monta **primero** `gateway_openai` y **después** `mount_plugin_routers(app)`, ambos antes de CORS y **sin** el `TrialReadOnlyMiddleware` de la 065 de Sentinel (Eleia no tiene trial). En `gateway.py`: el import queda `gateway_plugins as gp` + `require_not_hard_blocked` (**sin** `require_not_trial_expired`) | `backend/src/main.py:140-149` | `d16cd37` (`6161bf0`), `5684e6f` (`e3a5297`), `6832276`/`48a7bd9`/`e42f017`/`b61b392` (`map_response` e identidad de la llave en `/v1/models` y `count_tokens`) | Ninguno (genérico; el arreglo de identidad va también a `guardian-secure#351`). El orden se anota para que Sentinel no lo «corrija» |
| ADAPT-022 (S3, panel) | Las páginas de plugin del panel se registran sin editar `App.tsx`; conflicto resuelto conservando el ítem «Espacios sin asignar» de Eleia; el `package-lock` queda el de Eleia (vitest ya estaba); tailwind escanea el árbol del plugin si hay `VITE_PLUGIN_PAGES_DIR` e ignora `node_modules` | `frontend/src/plugins/registry.ts`, `frontend/tailwind.config.js`, `frontend/vitest.config.ts` | `a382654` (`f63144d`), `3f8c77c` (`adb53d9`) | Ninguno |
| **ADAPT-024** | `encryption_service` con `MultiFernet` (`FERNET_SECRET_KEY` + `FERNET_PREVIOUS_KEYS` solo para descifrar), `descifrar_estricto`, `rotar`. **Solo dos archivos** (`git checkout 14edbc7 -- …`, nunca el commit entero: arrastra los symlinks `backend/.venv` y `*/node_modules`). El contrato de `encrypt`/`decrypt` (`None` ante fallo) no cambia | `backend/src/services/encryption_service.py:28-32`, `:97`; test `backend/tests/unit/test_encryption_multifernet.py` | `13f2a28` | Ninguno. `FERNET_PREVIOUS_KEYS` se declaró después en `.env.example:58` (T015) |
| **ADAPT-026** | El ítem base del menú pasa de «Modelos & Ollama» a **«Modelos»** (reemplazo de ítem por una página de plugin, costura S3 `replaces`). **Cambio visible aunque no haya extensión**; cuadra con la regla de marca neutra (el menú nombraba un proveedor). Conflicto *modify/delete* de `specs/069-…/tasks.md` resuelto con `git rm` | `frontend/src/App.tsx:66` | `55977c5` (`1d8a3b7`) | Ninguno (genérico; a proponer a la base). **Deuda anotada, sin arreglar**: `frontend/e2e/029-screens.mjs:22` (script manual de capturas, fuera de `npm test`) todavía busca el rótulo viejo |
| S1 (`PLUGIN_PACKAGES`) | `main.py`: un solo hunk (solo `mount_plugin_routers`). `docs/docs/api-reference/configuration.md`: un hunk trivial; se conservan las filas de Eleia (`SENTINEL_ENTITY_REGION=latam_ar`, bóveda de PII) y se suma solo `PLUGIN_PACKAGES`. El logger de `plugins.py` (`sentinel-secure-gateway.plugins`) coincide con el prefijo de Eleia: sin cambio | `backend/src/main.py:147-149` | `d16cd37` | Ninguno |
| S2 (`GatewayContext.body`) | La costura S2 ya dejaba responder `count_tokens` desde `pre_request`, pero el plugin no veía ni el modelo ni el cuerpo: se agrega `GatewayContext.body` (opcional, `None`) y la lectura del cuerpo de `count_tokens` **solo con plugins y en POST**; `ctx.model` saneado con `sanear_modelo_declarado`. Sentinel `main` tiene el mismo hueco (sin esto, su T093 no se puede hacer) | `backend/src/api/gateway_plugins.py`, `backend/src/api/gateway.py` (`_plain_passthrough`) | `ba7d030` | Ninguno (retrocompatible; batería T003 sin cambios). `contracts/costuras-base.md` fila S2 debería sumar «cuerpo de `count_tokens`» |
| S6 (`update_model_credential`) | Un hunk en conflicto, resolución mínima: se queda el `engine_params = body.resolved_engine_params()` de Eleia y se usa `_visible_entries(config_data)` de Sentinel en el bucle | `backend/src/api/chat.py` | `36c44ec` (`7a4f65c`) | Ninguno |
| S5b (informe de enmascarado) | Se aplica **sin S5a** (`sentinel:76ab37a`: choca con `f8118e7`). **Cambio de camino (QA M11)**: con `redact_enabled=false` el guardrail ahora corre el analizador **una vez y solo para contar** (`masked=0`); suma latencia y carga del analizador para las empresas con el enmascarado apagado, y un analizador caído ahí **no bloquea ni degrada** (`completed=False`). Fijado con un test (T008) | `litellm/extensions/sentinel_guardrail.py`; test `backend/tests/unit/test_guardrail_redact_off_057.py` | `b920de0`, `839ae6a` | Ninguno; el cambio de latencia se avisa a Sentinel en su HANDOFF |
| S12 (`EXTRA_ENV_FILE`) | Se corrió **solo la parte de estructura** (a) de `test_compose_extra_env_file.sh`; la parte (b) usa `docker compose config` y queda para el gate con Docker | `deploy/release/checks/test_compose_extra_env_file.sh` | `3f79838` | Se cierra en el gate (T086) |
| S4 (migraciones extra) | Sin desvío de código. **Extensión de Eleia**: la imagen **publicada** (`Dockerfile.standalone`) también migra a `heads` solo con `ALEMBIC_EXTRA_VERSION_LOCATIONS`, y el arranque **aborta** si una migración falla cuando hay ramas de extensión (QA B1, T088). Sentinel no migraba en la imagen publicada | `backend/Dockerfile.standalone:35-37`, `backend/src/main.py` | `c9289a2` (`1021c8e`), `fee163b` (T088) | Ninguno: es genérico y vuelve a Sentinel (HANDOFF §S4) |
| `git rm` de `docs/sentinel/04-REGISTRO-DE-CAMBIOS.md` | *modify/delete* en cada pick que lo tocaba (HANDOFF §1(a)); Eleia no lo tiene | — | todos los picks de T-A | Este archivo lo reemplaza |

**No se portan** (decisión de R1/R3): S10 (descartada en la 068), S5a `76ab37a`, `9fe188f` (ADAPT-018 arriba) y
`fd515ff` (modelo «auto» por la puerta genérica; el test `test_listado_generico_suma_auto_para_los_servicios` queda en
`skip` con referencia).

### Cambios propios de Eleia en T-A (no vienen de Sentinel)

| Qué | Dónde | Commit | Plan de salida |
|---|---|---|---|
| Enmienda constitucional **2.2.0 → 2.3.0** (D13: 403 `permission_error` para rechazos de residencia; D14: aclaración del Principio VII, nombres de proveedor solo como datos del administrador o literales del protocolo; D15: default de residencia por región y precedencia del enmascarado forzado sobre `nlp_fail_mode=degrade` y `redact_enabled=false`). **Divergencia de numeración**: Sentinel ya tiene sus propias 2.3.0 y 2.4.0 (`sentinel:6a70855:.specify/memory/constitution.md:3`); el Sync Impact Report lo avisa | `.specify/memory/constitution.md` | `4012ee4` | Ninguno de código. A Sentinel solo le sirve como precedente: su 2.4.0 ya enmendó el 403 |
| Batería de no-regresión de la pasarela con motor falso (26 casos contra un JSON grabado), escrita **antes** de cualquier pick | `backend/tests/contract/test_gw_no_regresion_057.py` | `6023079`, `36a4d4e` (ignora los kwargs de auditoría en su valor por defecto) | Ninguno; es genérica y vuelve a Sentinel |
| Pantalla de descubrimiento neutra: `GET /api/v1/gw` deja de nombrar el motor interno (FR-004; Principio VII). Solo cambia el texto del modo byok | `backend/src/api/gateway.py:2249` (`gw_info`); test `backend/tests/contract/test_gw_info_neutral.py` | `405f3fd` | Ninguno; genérico |
| `docs-refs`: `openapi.json` con `/gw/v1/chat/completions` y `configuration.md` con `FERNET_PREVIOUS_KEYS` y `GATEWAY_PLUGINS` (leída con literal para el gate de deriva) | `docs/docs/api-reference/`, `.env.example` | `3757a7e`, `9eab054`, `a889b9f` | Ninguno |

## 2. La extensión `sentinel/` (T-B): copia con recortes

`git checkout 6a70855 -- sentinel` (a1b0049), **sin** `sentinel/onboarding/` ni la migración del wizard
(`b8c4d7e2a915`): Eleia no usa el onboarding del wizard (Principio IV: el onboarding son datos). Se quitan los tests
del wizard. Se conservan los nombres internos `sentinel_*` (paquete, tablas, etiqueta de migraciones, rutas
internas): son invisibles al cliente (FR-050) y mantienen la paridad con Sentinel (HANDOFF §4.5).

| Desvío | Detalle | Plan de salida |
|---|---|---|
| **Costuras de la consola que Eleia no tiene** (QA T-B H4): `src.services.residency_heuristic`, `src.services.access_hook` (ADAPT-027 de Sentinel) y `src.services.model_route_hook` (ADAPT-028) no existen en Eleia; `sentinel/catalog/api/__init__.py:4-31` y `access/bridge.py:113-118` se tragan el `ImportError` y la extensión **se degrada en silencio**. Efecto: los perfiles de acceso del catálogo rigen en la pasarela, **no** en el chat de la consola (un perfil que quita un modelo gobernado no lo corta ahí); el chat de la consola no sirve las entradas del catálogo (FR-006 «la consola queda fuera» se cumple por ausencia, no por diseño); la residencia de proyectos de la base no consulta el semáforo del catálogo. Saltos visibles: `test_chat_route.py:15`, `test_unsupported_params.py:223`, `test_semaforo_parity.py:239`. Dicho en la documentación (límite 🟡 de `administration/redireccionamiento.md`) | Portar ADAPT-027/028 y `residency_heuristic` a la base de Eleia en una spec propia, con un test «sin costura ⇒ sin error ni efecto» (hoy lo cubren por casualidad los saltos). **Va por HANDOFF** como lo que Sentinel debe saber de su propia extensión |
| Tests de Sentinel en `skip` con motivo (13, ninguno crítico) | Despliegue `nix`, `release.yml`, `residency_heuristic`, canal de atribución de la 069, `fd515ff` | Se levantan si Eleia adopta esa pieza; ninguno protege código que Eleia use |
| Import latente `ApiKey` → `APIKey` en `sentinel/access/api/admin.py` | Defecto de Sentinel (HANDOFF §1(b)): corregido con su test | Ninguno: **vuelve a Sentinel** (HANDOFF) |
| Panel: `mergeNav` (base, retrocompatible) deja que una página que sustituye un ítem base se enlace después de una sección distinta; la política ofrece solo *apagada* y *encendida* (sin estado *sombra*, reservado a F6) | `frontend/src/plugins/registry.ts:84` (`mergeNav`), `sentinel/frontend/redirect/PolicyTab.tsx` | Ninguno; el recorte del panel es del MVP |
| Reglas de habilitación por datos **reemplazan** el `provider == "deepseek"` fijo (`catalog/api/admin.py`, `catalog/seed.py`, `catalog/api/legacy.py`) | Migración nueva `sentinel/migrations/89a92524eef6_redirect_region_y_habilitacion.py`, rama `sentinel_redirect`, colgada de `f7a3c1d9e508`, generada con `alembic revision` | Vuelve a Sentinel con un seed `provider: deepseek` que conserva su comportamiento |
| Las reglas de habilitación de una **empresa** aplican solo a las entradas de esa empresa (opción A, confirmada por el coordinador; research R14) | `sentinel/catalog/habilitacion.py` | Ninguno |
| `catalog/migrate.py` (migración única de la 068) copia `api_base` de filas existentes **sin validarla** (H1 no la cubre) | `sentinel/catalog/migrate.py:101` | Cerrar en Sentinel si esa migración todavía corre allá |

### Datos propios de Eleia (no son código: seeds)

| Dato | Archivo | Decisión |
|---|---|---|
| Región `AMERICAS` (continente completo, `region_profiles` = `latam_ar`, `latam`, `us`; `default_posture = masked_all`) | `deploy/redirect-seeds/regions.americas.yaml` | D2 (2026-10-06): todo lo redirigido sale enmascarado, fail-closed, dentro y fuera de la región; D3: criterio de riesgo, no de legalidad |
| Reglas de habilitación explícita **vacías** | `deploy/redirect-seeds/habilitacion-explicita.yaml` | D1: ningún destino nace bloqueado; las jurisdicciones de preocupación son reglas que carga el cliente desde el panel |
| Catálogo de ejemplo de Azure con credencial **adoptada** (`env:AZURE_API_KEY` + `api_version`) y jurisdicciones de entidad y control **vacías y marcadas obligatorias** | `deploy/redirect-seeds/catalog-seed.azure-demo.yaml` | FR-020: no se presumen datos de cumplimiento |
| `SENTINEL_ENTITY_REGION=latam_ar` en el entorno de desarrollo de la extensión | `sentinel/extensions.env.example`, `sentinel/docker/compose.dev.yml` | Línea América (perfil Argentina) |

## 3. Cambios de comportamiento de la base de Sentinel que Eleia introdujo (⚠)

Marcados «⚠ cambia» porque **Sentinel verá un comportamiento distinto** al adoptarlos. El detalle y el plan de adopción
están en el HANDOFF; acá solo el registro.

| # | Cambio | Dónde | Commit |
|---|---|---|---|
| 1 | Sin fila de región, el redirigido sale **forzado y limitado a `region_codes(región)`** (antes: `allowlist[región]` sin forzado). Sentinel debe sembrar su fila `reject_offregion` para conservar el comportamiento | `sentinel/redirect/residency.py:296` (`effective_posture`) | `4cd1ced` |
| 2 | La regla «en región» exige también la **jurisdicción de control**: una ficha sin ella deja de contar como en región | `sentinel/redirect/residency.py:365` (`evaluate`), `sentinel/catalog/region.py` | `5a03fc4`, `4cd1ced` |
| 3 | Un destino **sin jurisdicción de inferencia** se rechaza con **cualquier** postura, fila o relajación (antes, `off` lo dejaba pasar) | `sentinel/redirect/residency.py:365` | `4cd1ced` |
| 4 | `tenant_region`, `list_postures` y `run_fidelity` **no caen a `eu`**: una sola función, `residency.resolve_profile` | `sentinel/redirect/residency.py:109` | `4cd1ced` |
| 5 | `masking_ok(report, forced=True)` exige `scope == "full"` y `unanalyzable == 0`; un informe sin esos campos bloquea | `sentinel/engine/redirect_guard.py:198` | `0a0be3f` |
| 6 | Bajo forzado, el análisis previo por tipo (BLOCK vs MASK) corre **por segmento** (los mismos que recorre el enmascarado), no sobre el texto unido y recortado a `INSPECT_CAP`; AI-Act y secretos siguen mirando el texto unido | `litellm/extensions/sentinel_guardian_policy.py:1856` (`cached_analyze`) | `3117fe5` |
| 7 | **La fila de auditoría del no-stream sale después de `map_response`/`map_error` y en un `try/finally`**: si el enganche lanza, la fila sale igual con la decisión que haya y estado `upstream_error`. Sin plugins la fila es la de siempre (test). Autorizado por el coordinador (2026-10-06) para que un plugin sume lo que lee de la respuesta (tokens de caché) a su `routing_decision` | `backend/src/api/gateway.py:1996-2012`; test `backend/tests/unit/test_gateway_audit_after_map_response.py` | `d990825` |
| 8 | La fila del camino con llave del producto (byok) **no** lleva tokens de caché: la escribe el logger del motor con la decisión que el guard fijó antes de la respuesta (decisión A del coordinador: sin tocar el logger) | `litellm/extensions/sentinel_audit_logger.py` (sin cambios) | `d990825` |
| 9 | Con `redact_enabled=false`, el guardrail corre el analizador solo para contar (S5b, ver §1) | `litellm/extensions/sentinel_guardrail.py` | `b920de0` |
| 10 | El firmado del razonamiento queda atado al **destino** (precisión sobre D7 de la 068, donde era «sobre el texto»): el razonamiento de un destino nunca llega a otro | `sentinel/redirect/thinking.py:50` (`sign`) | `a090ee9` |
| 11 | Un id `claude-*` no publicado cae a la regla por tier (`infer_tier`) solo con la política `on` y llave del producto; sin regla, 404 neutro (el `data-model` de Sentinel lo preveía y el plugin no lo hacía) | `sentinel/redirect/faces/claude.py` | `0295e45` |
| 12 | `_select_by_capability` actualiza la decisión **en el lugar** (antes la reasignaba tras una sustitución y la auditoría perdía `omitted`, `dropped_fields`, etc.): defecto latente corregido | `sentinel/redirect/plugin.py` | `2bcba41` |
| 13 | **Falla a mitad del stream en la cara Claude**: ya no propaga; sale `event: error` neutro y cierre sin `message_stop` (sigue propagando en la genérica). Cambia un test heredado | `sentinel/redirect/stream.py:206` (`wrap_sse`) | `ba7d030` |
| 14 | La relajación por destino se **revoca** si cambian `provider`, `api_base`, `real_model`, `is_aggregator` o la lista de proveedores (H2); `api_base` de empresa validada: https y hosts públicos (H1; `CATALOG_ALLOW_PRIVATE_API_BASE` para on-prem) | `sentinel/catalog/relaxation.py`, `sentinel/catalog/api_base.py` | `c876536` |
| 15 | Los campos de residencia y retención de la ficha (`provider_legal_entity`, `entity_jurisdiction`, `control_jurisdiction`, `inference_jurisdiction`, `zero_data_retention`) los escribe solo cumplimiento o super admin, por **rol real** | `sentinel/catalog/api/admin.py` | `ee12f89` |

## 4. Porte posterior de Sentinel (F1, T107) y desvíos de T-F

- **F1** (`sentinel:c974dc5`, `sentinel:6ca0419`, spec 069 de Sentinel, merge `5e7576e`): entraron por `cherry-pick -x`
  (`3ebfe4a`, `96d131e`): el puente chat + herramientas + razonamiento → Responses hacia OpenAI/Azure (conserva el
  `reasoning_effort` del cliente, incluido `none`) y `context_length`/`max_output` en `/gw/v1/models` genérico.
  **Desvío**: no se trajeron `docs/docs/integrations/redireccionamiento.md` (no existe en Eleia; el contenido
  quedó incorporado en [`cli-formato-openai.md`](../../docs/docs/integrations/cli-formato-openai.md)) ni
  `specs/069-*/tasks.md`. Plan de salida: ninguno; los tests portados (`test_redirect_guard`,
  `test_unsupported_params`, `test_face_generic`) pasan.
  - *Evidencia local*: Sentinel midió que el motor puentea solo `gpt-5.4+`; el `gpt-6-*` quedaba afuera y respondía
    400 «Function tools with reasoning_effort are not supported». **Sin verificación en vivo en Eleia.**
- **T108**: el guard lee `masking_report.signed_thinking` (era el provisional `signed_thinking_detections`) y registra el
  resolutor de forzado al importarse, en las dos copias del módulo de política que pueden convivir en el motor
  (`sentinel/engine/redirect_guard.py:121`, `:161-177`). Antes de esto todo pedido forzado se bloqueaba con
  `masking_required` (falla cerrada). Commit `ebf7114`.
- **S17** (caché de análisis, decisión del owner del 2026-10-06; research R34) y **S13** (marcadores estables por conversación):
  costuras nuevas de Eleia que vuelven a Sentinel; ver HANDOFF.
- `MASKING_NONCE_KEY` protegida: `ENV_DENYLIST` (`sentinel/engine/redirect_credentials.py:81`), generada distinta por
  instalación (`deploy/release/gen_secrets.sh:46`) y verificada por `test_no_default_secrets.sh`. En el instalador la genera T100.
- `.env.example`: las variables opcionales del motor (`MASKING_PDF_*`, `MASKING_ANALYSIS_CACHE_*`, `MASKING_EXEMPT_*`,
  `MASKING_NONCE_KEY`) están **comentadas**: una variable real que solo lee el motor en Python haría fallar el gate de deriva
  (`docs/tools/drift_gate.py`, «declarada y ningún plano la consume»). Cuando T100 las pase por el compose, T082 las
  descomenta y regenera la referencia.

## 4b. Cowork, etiqueta y OpenRouter (2026-10-07; research R39 y R40; T119–T123)

Desvíos de Eleia respecto de la base, todos retrocompatibles y registrados en `HANDOFF-elea-a-sentinel.md`:

- **Binarios de herramienta bajo el forzado** (R39): una imagen, un audio o un documento no analizable dentro de un `tool_result` se cambia por una nota y no bloquea
  (`litellm/extensions/sentinel_guardian_policy.py:1476`); la auditoría registra `unanalyzable_replaced` (`sentinel/engine/redirect_guard.py:658-663`). Lo que adjunta la persona
  sigue bloqueando. Plan de salida: ninguno; es una excepción de S14 que Sentinel puede adoptar tal cual.
- **Etiqueta por defecto `requested`** (R40): `sentinel/redirect/models.py:138`, `sentinel/redirect/api/admin.py:279`, migración `0529902015ad`. Sentinel conserva `destination`
  si quiere. Plan de salida: cambiar el default de vuelta (otra migración de default); las filas no se tocaron.
- **Alta guiada de OpenRouter** (R40): `provider_options.providers_allowlist` desde el formulario. Plan de salida: ninguno; corrige un hueco de la base.
- **Numeración**: FR-057 y FR-058 de esta spec son los de la etiqueta y el alta de OpenRouter; los FR-053 a FR-056 siguen siendo los de la cara genérica.

## 4c. Ajuste de imágenes bajo el forzado (2026-10-07; research R43; T125–T128)

Desvío de Eleia respecto de la base, retrocompatible y registrado en `HANDOFF-elea-a-sentinel.md`:

- **`MASKING_IMAGES=pass|filter`** (R43): con `pass` —**default de Eleia**— las imágenes salen tal cual bajo el forzado y la auditoría las cuenta (`images_unmasked`, solo conteo y tipo);
  con `filter`, R39. Valor desconocido ⇒ `filter`. `litellm/extensions/sentinel_guardian_policy.py:1305-1317`, `:1516`, `:2224`; `sentinel_guardrail.py:745`; `sentinel/engine/redirect_guard.py:258-284`, `:678`.
  Solo por instalación (variable de entorno); por grupo/panel no (R43). Plan de salida: Sentinel fija su propio `IMAGES_DEFAULT`; si Eleia quisiera volver al comportamiento de R39, `MASKING_IMAGES=filter`.
  La cara Claude (`sentinel/redirect/faces/claude.py`) no cambió: la capacidad `images` del destino se respeta antes del motor.

## 4d. Revisión de punta a punta de la documentación y estado en vivo (2026-10-07)

Revisión de `docs/docs/**` contra el código de `cluna-8/057-int` y contra el README del instalador. Es solo documentación, specs y los
tests de runbook del instalador: no cambia código de producto.

**Pasó a 🟢 (verificado en vivo el 7-oct-2026, Claude Desktop contra Azure, instalación de prueba con el instalador y `ELEA_REDIRECT=1`)**: conexión por gateway
(URL `/api/v1/gw`, `bearer`, llave estática, descubrimiento); chat con `haiku` → `gpt-5.4-mini`, `sonnet` → `gpt-5.1-chat` y `opus` → `gpt-5.6-luna`; cambio de destino de `sonnet` en *Reglas*
sin tocar el cliente; DNI enmascarado hacia Azure; Cowork con PDF y presentación; diseño SVG; lectura de imágenes (`MASKING_IMAGES=pass`; `sonnet` tras marcar *Imágenes*); llave con 1 000 000 tpm / 120 rpm por *Editar límites*;
esfuerzo ajustado (`gpt-5.1-chat` solo `medium`); etiqueta «id pedido»; credencial de Azure del catálogo con `api_version` `2025-04-01-preview`; alta de modelos y ficha; instalación con el instalador y `ELEA_REDIRECT=1` (T102: activación,
salud, `404` del canal interno, nivel 1).
**Sigue 🟡/🔵 (no probado en vivo)**: OpenRouter/Kimi u otro proveedor que no sea Azure, Bedrock, grupos «Todos» y «Solo Azure» (solo tests), kit `managed-settings.json` instalado en una PC, Claude Code real, la cara genérica, el filtro de imágenes
(`MASKING_IMAGES=filter`), la llave que emite el kit, la vuelta atrás de nivel 2, la región real del recurso de Azure (US, a confirmar); 🔵 generación de imágenes (no existe) y OCR (no existe).

**Contradicciones corregidas** (doc ↔ doc y doc ↔ código):

| Dónde | Decía | Ahora |
|---|---|---|
| `administration/redireccionamiento.md` (límites) y `integrations/claude-desktop.md` (límites) | «OCR no existe; las imágenes se bloquean / se omiten» | Con `MASKING_IMAGES=pass` (default) salen sin enmascarar su contenido (`litellm/extensions/sentinel_guardian_policy.py:1305-1317`, R43); OCR y generación de imágenes no existen; el PDF escaneado sigue bloqueándose |
| `redireccionamiento.md` (Destinos) | La credencial de Azure «se adopta» de una variable del servidor | La credencial se carga desde el panel (clave + versión de API), la dirección va en cada modelo y es de solo escritura; la adopción por `env:` queda para el catálogo de ejemplo del operador (`sentinel/catalog/credentials.py:101`, `deploy/redirect-seeds/catalog-seed.azure-demo.yaml`) |
| `redireccionamiento.md`, `administration/index.md`, README del instalador | El administrador ve y archiva los destinos de ejemplo | Las entradas de **instalación** solo las ven y administran cumplimiento o el super admin hasta que las ofrece (`sentinel/catalog/store.py:124-137`, `sentinel/catalog/api/admin.py:221-222`, `:1012-1017`; EVIDENCIA T102: `admin` → vacío, cumplimiento → 4) |
| `claude-desktop.md` | Cada pedido manda 35 000–40 000 tokens | 35 000–67 000 (§10 de `verificacion-quickstart.md`); el default de 100 000 tpm / 60 rpm es el de la llave generada a mano (`backend/src/api/keys.py:40-41`), no el del kit (`sentinel/redirect/kits.py:28`) |
| `redireccionamiento.md` (ids publicados) | Frase rota sobre la etiqueta («es del tipo el id pedido») | La etiqueta por defecto es el id pedido (`sentinel/redirect/models.py:138`) |
| `claude-desktop.md` | Cowork crea «imágenes»; las skills de documentos «no llegan» | Crea documentos y diseños SVG/HTML (los modelos no generan imágenes); las skills del proveedor original no llegan, pero Cowork igual crea PDF y presentaciones ejecutando código 🟢 |
| `claude-desktop.md` (síntomas) | La nota «imagen omitida» se atribuía al enmascarado forzado | Solo con destino sin visión, ficha sin *Imágenes* o `filter` |
| `operations/index.md` §7, `install-deploy/index.md` (fila y paso 11), `operations` §7.5 | Instalador, proxy y servidor «🔵 en curso» | 🟢 activación local con contenedores reales (7-oct-2026); 🟡 servidor real y nivel 2 |
| `administration/gobernanza.md` | «Lo no analizable se bloquea», sin matiz | Las imágenes se rigen por `MASKING_IMAGES` |
| `integrations/index.md`, `overview/index.md`, `release-notes/index.md` | Toda la redirección «sin verificación en vivo» | Claude Desktop (Chat y Cowork) con Azure 🟢; el resto 🟡 |
| README del instalador (Paso 9), vs `claude-desktop.md` | 35 000–67 000 vs 35 000–40 000; «Estado 🟡 nada verificado en vivo» | Unificados (ver el commit del instalador) |

**Abierto** (no se cierra acá): T089 (falta `sentinel/tests/unit/test_internal_rutas_extension_origen.py`); T102 (nivel 2, respaldo en código, migración rota); T045 (Claude Code y Code de Claude Desktop), T051, T066, T078, T083, T086.

## 5. Documentación de producto (T079, T080, T081)

| Página | Cambio |
|---|---|
| `docs/docs/administration/redireccionamiento.md` (nueva) | Política, catálogo, ids publicados, reglas, estrategia «más barato», residencia `AMERICAS`, postura por defecto (`masked_all`), respaldo en código (`region_unresolved` / `region_row_missing`), relajaciones, enmascarado de alcance completo (S14) con sus causas de bloqueo, habilitación explícita, matriz por herramienta y proveedor |
| `docs/docs/integrations/{claude-desktop,claude-code,cli-formato-openai}.md` (nuevas) | Configuración, ids publicados y síntomas por contrato de cada herramienta (incluido el «Failed to authenticate» que Claude Desktop antepone a todo 403 frente al 400 propio del bloqueo por enmascarado) |
| `docs/docs/integrations/index.md` | Filas de matriz, §3.6 y límites; la fila de Claude Desktop deja de afirmar que «no expone override de `base_url`» (el modo de gateway de terceros sí) |
| `docs/docs/operations/index.md` §7, `docs/docs/install-deploy/index.md` (fila + paso 11) | Activación, variables, `GET /api/v1/redirect/health`, seeds, topes de PDF, canal interno, vuelta atrás en dos niveles |
| `docs/docs/compliance/index.md`, `dpa-dsr-retention.md`, `overview/index.md`, `release-notes/index.md` (M13) | Se **declara fuera, con motivo**, que GDPR y EU AI Act no rigen en la línea América; el marco es la Ley 25.326/AAIP (mapeo del módulo 🔵). «Forzar región EU» queda descrito como control heredado que **no** es el de residencia de esta línea |
| `docs/mkdocs.yml` | Nav: cuatro páginas nuevas |

Estado honesto: **todo 🟡** salvo lo que la base garantiza sin la extensión (🟢, batería T003/T018). El gate con Docker
(`make -C deploy check-docs`) no se corrió (T082); en su lugar se corrieron sin Docker: `docs/test_gen_config_reference.py`,
`docs/tools/test_drift_gate.py`, `docs/tools/drift_gate.py`, `deploy/release/checks/test_docs_structure.sh`, un
`mkdocs build --strict` local y un linter propio de enlaces, anclas, marcadores internos y nombres prohibidos.
