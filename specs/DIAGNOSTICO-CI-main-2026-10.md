# Diagnóstico — CI de `main` rojo (31-ago → 5-oct-2026)

**Tipo**: spike de diagnóstico. No arregla nada, no abre spec ni numeración, no toca código
de producto. **Fecha**: 5-oct-2026. **Rama**: `cluna-8/fix-ci-main-diag`.
**Job**: `pytest (suite completa, Postgres real) + check-docs` (`.github/workflows/ci.yml:32-33`,
pasos «Suite completa» `:51-52` y «check-docs» `:70-72`).
**Log base**: job `107216111181` (run `35871397897`, push `docs(specs): spec 056…`, 23-sep) —
`18 failed, 2767 passed, 21 skipped` en la suite + `FALLÓ — 1 fallo(s)` en check-docs.

Convención de marcas: **[verificado]** = lo vi yo en esta sesión (log del CI, `git log`/`blame`,
lectura del código, o corrida local sin Docker). **[no verificado]** = deducción o hipótesis;
la sección final «No verificado» las junta.

---

## 0. Resumen de veredictos

| # | Grupo | Fallas | Causa en una línea | Veredicto | Introducido por |
|---|---|---|---|---|---|
| 1 | Marca blanca | 2 | El docstring de `POST /chat/rag-usage` nombra «AnythingLLM» y FastAPI lo publica como descripción en el OpenAPI | **Bug en el código** (el test es correcto) | `a73aa75` (17-sep, spec 053) |
| 2 | Catálogo + auto-router | 1 + 7 | Los tests exigen `gpt-4o`, `gpt-4o-mini` y `ollama-qwen3-4b` en `litellm/config.yaml`; el catálogo de dev ya es solo Azure | **Tests viejos** — el catálogo es decisión de producto vigente | `c9a98a8` + `484b5a9` (ambos 31-ago) |
| 3 | Migraciones | 8 (1 causa + 3 en cascada) | `7a6fee614cfd` usa `op.add_column` sin `IF NOT EXISTS`; los tests de idempotencia re-corren el cuerpo sobre un esquema ya migrado | **Bug en el código** (la migración rompe la convención del repo; tests correctos) | `29b6667` (17-sep, spec 054) |
| 4 | Política latam_ar | 1 | El test espera `{DNI, CUIL, PASSPORT}` y el perfil ahora emite además `CBU` | **Test viejo** — CBU es decisión de producto vigente | `c9a98a8` (31-ago) |
| 5 | check-docs | 1 | `openapi.json` publicado quedó con 3 rutas `/exact-analysis/*` cuyo router se borró | **Documentación vieja** (falta regenerar) — y detrás hay más deriva oculta | `904dd37` (13-sep, spec 050) |

Hallazgos que el log **no** muestra pero que aparecen en cuanto se arreglen los de arriba
(sección 7): (a) la migración `199fe429762a` (spec 055) tiene el mismo defecto que `7a6fee614cfd`;
(b) `check-docs` corta en el primer fallo y **no corrió** el resto de sus pasos — dos de ellos
(`test_docs_apiref.sh` por deriva del openapi y de `configuration.md`) van a fallar también;
(c) regenerar el openapi sin arreglar antes el grupo 1 publica el nombre del motor de documentos
en la referencia pública.

---

## 1. Cronología: por qué «rojo desde el 31-ago» y por qué recién ahora se ven los fallos

- Último verde de `main`: `97b8c5f` / `c03046b` (31-ago). [verificado: `gh run list`]
- Desde `668ced5` (31-ago) hasta `f76a8c8` (9-sep) **todos** los runs de `main` cayeron en un paso
  anterior a la suite: `scripts/check_stack_prefix.sh` (`ci.yml:44-45`). El perfil `full` del compose
  suma `frontend` y el script no lo pedía; el log dice «render distinto al esperado» con
  `sentinel-frontend` faltando. [verificado: logs de los runs `33411012163`, `33667311467`,
  `33675792803`, y `git show f76a8c8`]. Ese rojo **tapó la suite** durante ~10 días: `docker compose up`,
  migraciones, `pytest` y `check-docs` no se ejecutaban (`ci.yml:46-72` quedan detrás del paso fallido).
  [verificado: el log del run `33411012163` termina en el paso de prefijos sin llegar a `Suite completa`]
- Primer run con la suite ejecutada después del arreglo de prefijos: `34587674806` (11-sep, merge PR #2):
  `9 failed` = grupo 2 (8) + grupo 4 (1). [verificado]. Es decir, **los grupos 2 y 4 llevaban rojos
  desde el 31-ago sin que nadie lo viera**; la fecha del commit culpable es la del 31-ago, no la del
  primer run rojo. [la atribución al 31-ago es deducida del diff de `c9a98a8`/`484b5a9` y del último run con suite ejecutada (`33377922910`, previo a ambos, sin estos fallos); no se midió porque la suite no corría — [no verificado] como medición]
- Grupo 5 aparece desde `904dd37` (13-sep): primer run inspeccionado con el `FAIL test_rutas_en_paridad…` es
  `34861318024` (14-sep). Antes (run `34587674806`) `check-docs` no tenía ese fallo. [verificado]
- Grupo 1 aparece en el run de `a73aa75` (`35197658049`, 17-sep: 2 fallos de branding, 0 de migraciones);
  grupo 3 aparece en el run de `29b6667` (`35201937183`, 17-sep: suman los 8 de migraciones → `18 failed`).
  [verificado]
- Hubo un fallo suelto el 31-ago, `test_fallback_escala_lineal_no_redos` (run `33377922910`, `1 failed`),
  que no volvió a aparecer en ninguno de los runs inspeccionados — por nombre y contexto es un test de
  tiempos (posible flaky). [verificado que falló una vez y no reaparece en los 13 runs que bajé; la causa
  «flaky» es [no verificado]]
- Estado actual: el run del merge del PR #4 (`37374302720`, 5-oct) estaba *queued* al empezar este
  diagnóstico; no lo usé. Todo lo de abajo sale del log del 23-sep (commit `ec03a6f`), que es el pedido.
  Entre `ec03a6f` y `HEAD` **no hay cambios** en `backend/`, `litellm/`, `docs/`, `deploy/`, `.github/`, `.env.example`,
  `docker-compose.yml` ni `scripts/` (solo specs y `AGENTS.md`/atlas: 8 archivos, +916 líneas). [verificado: `git diff --stat ec03a6f HEAD -- <rutas>` vacío]

---

## 2. Grupo 1 — Marca blanca: «anythingllm» en el OpenAPI público

**Tests**: `backend/tests/contract/test_branding_neutral_043.py::test_openapi_publico_sin_terminos_prohibidos`
y `::test_openapi_json_export_no_contiene_el_termino_como_json_crudo[anythingllm]`.
Los otros dos parámetros (`litellm`, `presidio`) y el de nombres de guardianes pasan. [verificado: log + corrida local]

### Causa
- El test recorre `app.openapi()` completo buscando `("litellm", "anythingllm", "presidio")`
  (`test_branding_neutral_043.py:11, 47-55, 73-84`).
- Ese schema contiene **una sola** operación con un término prohibido: `POST /api/v1/chat/rag-usage`.
  [verificado: script desechable que itera `app.openapi()['paths']` — única coincidencia: `anythingllm POST /api/v1/chat/rag-usage`]
- FastAPI usa el **docstring** de la función como `description` de la operación. El docstring de
  `report_rag_usage` (`backend/src/api/chat.py:2060-2085`, decorador en `:2054`) dice «…por el motor de
  DOCUMENTOS (AnythingLLM), reportado por el Hub — spec 053…» (`:2060-2061`) y repite «AnythingLLM» en
  `:2066`, `:2073` y `:2074`, además de nombrar archivos internos (`sentinel_audit_logger.py`, `custom_auth.py`,
  `tabular/app/llm.py`) y el número de spec. [verificado: lectura de `chat.py`; `anythingllm` aparece en el
  JSON exportado — log línea del `E   'anythingllm' is contained here`]

### Commit que lo introdujo
`a73aa75` — «fix(053): cierra la atribución del chat de documentos (RAG)», 17-sep-2026.
[verificado: `git log -S'(AnythingLLM), reportado por el Hub'`, `git blame -L2055,2065`]. El run de ese
commit (`35197658049`) ya muestra los dos fallos. [verificado]

### Veredicto
**Bug en el código, no test viejo.** La regla (Constitución VII; spec 043 contrato 6) es que nada visible
al cliente nombra el motor de documentos, y el OpenAPI es lo que ve un integrador y `/docs`. El docstring
es documentación *para desarrolladores* que se filtró a la superficie pública por un mecanismo implícito
de FastAPI. No hay decisión de producto que defienda publicarlo. Observación relacionada: `anythingllm`
**no** está en `deploy/release/checks/prohibited_names.txt` (solo `litellm`, `berriai`, `presidio`), así
que ni `check-whitelabel` ni el check de naming del sitio lo detectan; hoy solo lo ataja este test.
[verificado: lectura de `prohibited_names.txt`] Además `docs/docs/api-reference/configuration.md` ya lista
`ANYTHINGLLM_API_KEY` (generado de `.env.example`) — es un hecho para la decisión D4, no parte de este fallo.
[verificado: `grep`]

### Arreglo propuesto (mínimo y retrocompatible)
Archivo: `backend/src/api/chat.py` (base Guardian → anotar en HANDOFF).
- Pasar el texto largo del docstring a comentario `#` sobre la función (se conserva para mantenedores) y
  dejar en el decorador un `description=` neutro de una o dos líneas: «Registra el consumo (modelo y tokens)
  de un turno de chat de documentos, reportado por el Hub con la sesión de la persona.» Es el parámetro
  `description` de `@router.post("/rag-usage", …)` (`:2054`); FastAPI lo prefiere al docstring.
- Sin cambio de contrato HTTP, de schema ni de comportamiento. El test `test_rag_usage_053.py` no depende
  del docstring. [no verificado: no corrí ese test porque requiere Postgres; es un test de comportamiento
  sobre `/rag-usage`]
- **No** agregar `anythingllm` a `EXCEPCIONES` del test (`:18-21`): ocultaría fugas futuras.

### Cómo verificarlo
- **Sin Docker** [verificado que corre y reproduce]: desde `backend/` con el venv del checkout principal,
  `pytest tests/contract/test_branding_neutral_043.py -q` → hoy `2 failed, 3 passed` en ~13 s (importar
  `src.main` intenta `alembic upgrade` contra `db`, falla sin ruido y la app igual carga —
  `backend/src/main.py:40-61`). Tras el arreglo debe dar `5 passed`.
- **Remoto/CI**: `test_rag_usage_053.py` (Postgres) y la regeneración del openapi (grupo 5).

---

## 3. Grupo 2 — Catálogo del motor y auto-router

**Tests**: `tests/contract/test_catalogo_motor_paralelismo.py::test_el_catalogo_tiene_deployments_del_runtime_local`
(1) y 7 de `tests/integration/test_chat_auto_router.py`:
`test_auto_rutea_a_la_ruta_ganadora_y_registra_la_decision`, `test_el_coste_es_el_del_modelo_que_contesto_no_el_del_pedido`,
`test_un_id_versionado_del_proveedor_no_dispara_la_tarifa_por_defecto`, `test_models_antepone_auto_y_esconde_el_modelo_de_embeddings`,
`test_alta_de_modelo_cloud_nace_con_respaldo_al_local`, `test_fallback_con_origen_local_se_rechaza`,
`test_el_exito_del_chat_publica_evento_con_el_ruteo`. [verificado: log]

### Causa
- El catálogo de dev, `litellm/config.yaml`, hoy tiene exactamente cuatro entradas: `azure-gpt-4o-mini`
  (`:39`), `azure-gpt-5.1-chat` (`:50`), `azure-gpt-5.4-mini` (`:59`) y `router-embeddings` →
  `azure/text-embedding-3-large` (`:74`); fallbacks solo entre los dos «mini» (`:93-`). [verificado: `yaml.safe_load`]
- **Contract**: `_deployments_locales` filtra por prefijo `ollama_chat/` (`test_catalogo_motor_paralelismo.py:67-81`) y el
  test guarda `assert _deployments_locales(...)` (`:105-110`) — el «anti-verde-por-casualidad». Con 0 deployments
  locales ese test falla, y los otros tres (`:113-157`) iteran una lista vacía y pasan sin mirar nada
  (exactamente lo que el guard advierte). [verificado: corrida local: `1 failed, 3 passed`]
- **Integración**: el módulo fija `PREMIUM = "gpt-4o"`, `ECONOMICO = "gpt-4o-mini"`, `LOCAL = "ollama-qwen3-4b"`
  (`test_chat_auto_router.py:50-52`) con el comentario «existen de verdad en el catálogo del motor (`litellm/config.yaml`)»
  (`:47-49`). El router valida el destino contra el catálogo real: si falta, degrada a `target_missing` y sirve el
  `default_model` (`backend/src/services/auto_router_service.py:418-424`). Los asserts del log lo muestran: se
  esperaba `['gpt-4o']` y se obtuvo `['ollama-qwen3-4b']` (el default del test, `:81`). [verificado: log
  `assert ['ollama-qwen3-4b'] == ['gpt-4o']`]. Las otras fallas son la misma ausencia vista desde otro ángulo:
  `LOCAL not in nombres` (`:526`), el alta no encuentra un local al que respaldar (`:554-564`, en el log
  `None == 'ollama-qwen3-4b'`), y la regla «local → cloud» no se aplica porque `LOCAL` no es una entrada local del
  catálogo (`:612-627`; en el log `200 == 422`). [verificado el mecanismo para `target_missing`; el detalle
  de cada uno de los otros fallos es [no verificado] a nivel de traza porque requieren Postgres]
- El fixture `catalogo_temporal` copia el catálogo real (`:213-227`, `shutil.copyfile(chat._get_config_path(), …)`),
  así que el test **hereda** lo que tenga el catálogo de dev.

### Commits que lo introdujeron
La sospecha del encargo (`484b5a9`) es correcta **a medias**:
- `c9a98a8` (31-ago 14:06, «3 hallazgos P0 para prueba multi-usuario») **sacó el deployment `ollama_chat/qwen3:4b`**
  (`ollama-qwen3-4b`, el que llevaba `max_parallel_requests: 20` y `num_retries: 0`) y reescribió fallbacks y rutas
  del auto-router. [verificado: `git show c9a98a8 -- litellm/config.yaml`; `git log -S'ollama_chat/' -- litellm/config.yaml`]
- `484b5a9` (31-ago 17:53, «catálogo alineado a producción») sacó `gemini/*`, `openai/gpt-4o*`, `claude-3-5-sonnet`,
  agregó los tres Azure y pasó las embeddings del router a Azure; reescribió `auto_router.json`. [verificado]
- Ninguno de los dos tocó los tests; el último cambio a ambos archivos de test fue anterior
  (`f40d586` 12-ago y `34caf6c` 28-jul; `a371c89` solo renombró). [verificado: `git log` de los dos archivos]

### Veredicto
**Tests viejos; el catálogo es una decisión de producto explícita y documentada en los commits** («Sacados
gemini/openai/claude/ollama del catálogo de dev… mantenerlos vivos acá invitaba a probar contra un catálogo que no
es el real», comentario en `litellm/config.yaml:28-32`; y azure-gpt-5.1-chat sin fallback «decisión explícita del
usuario»). El código de producto que los tests cubren (`chat.py:797-815` reconocimiento de modelo local por prefijo
`ollama*`, `auto_router_service.py:418-424`) **no está roto**: lo que se rompió es el supuesto de los tests de que el
catálogo de dev trae un local y dos OpenAI. Matiz de producto (D1): en el catálogo de producción no hay runtime
local, así que la función «el alta de un cloud nace con respaldo al local» (spec 030 US3) hoy queda inerte en esa
instalación — sigue válida para clientes con local (la plantilla `deploy/clients/camara-comercio/config.yaml.tmpl:41-47`
sí declara `ollama_chat/${CLIENT_OLLAMA_MODEL}` con `max_parallel_requests: 20` y `num_retries: 0`). [verificado]
El check de despliegue equivalente, `deploy/release/checks/test_engine_local_limits.sh`, ya recorre `litellm/config.yaml`
**y todas** las plantillas de `deploy/clients/*/config.yaml.tmpl` (`:94-96`) y exige ≥1 local en alguna (`:105-108`),
por eso ese gate sigue verde. El contract de pytest no puede hacer lo mismo: el contenedor del backend monta solo
`./backend` y `./litellm` (`docker-compose.yml:221-223`) y los tests ya documentan que la raíz del repo no existe para
pytest (`test_catalogo_motor_paralelismo.py:49-53`). [verificado]

### Arreglo propuesto
Archivos (solo tests; cero cambios de producto):
1. `backend/tests/integration/test_chat_auto_router.py`: que `catalogo_temporal` (`:213-227`) arme un catálogo
   **de prueba autocontenido** —copia del real + inyección de tres entradas sintéticas `gpt-4o` (premium),
   `gpt-4o-mini` (economía) y `ollama-qwen3-4b` con `model: ollama_chat/qwen3:4b`— y que los tests que hoy
   usan `harness` sin ese fixture lo usen (el router lee `chat._get_config_path()`; hay que apuntarlo siempre a la
   copia). Alternativa equivalente: cambiar las constantes `PREMIUM/ECONOMICO/LOCAL` (`:50-52`) a nombres del
   catálogo real (`azure-gpt-5.1-chat`, `azure-gpt-4o-mini`) y crear solo el local sintético. Recomiendo la
   inyección: el test deja de depender del contenido del catálogo de dev.
2. `backend/tests/contract/test_catalogo_motor_paralelismo.py`: el catálogo de dev ya no es el sitio donde vive el
   deployment local; opciones en D2 (recomendada: si `litellm/config.yaml` no declara ningún `ollama_chat/`,
   `pytest.skip` con motivo que apunte a `test_engine_local_limits.sh`, que sí ve las plantillas; los otros tres
   tests siguen siendo vacuos hoy y con el skip dejan de aparentar cobertura).
- No restaurar `ollama-qwen3-4b`/OpenAI en `litellm/config.yaml`: revierte la decisión de producto y reintroduce el
  cuelgue de 30 s por request que motivó `c9a98a8`.

### Cómo verificarlo
- **Sin Docker**: el contract corre local [verificado]: hoy `1 failed, 3 passed`; con el cambio debe quedar
  `skipped`/verde. También se puede comprobar la premisa con `python3 -c "import yaml…"` (los nombres del catálogo,
  arriba). [verificado]
- **No corre sin Postgres**: `test_chat_auto_router.py` hace `require_postgres()` a nivel de módulo
  (`:40`; `tests/migration_harness.py:54-66`) y se **salta entero** localmente (verificado: `1 skipped` en mi corrida).
  Su verde solo se ve en CI remoto, o en la PC del owner con Docker.

---

## 4. Grupo 3 — Migraciones: `DuplicateColumn groups.is_active`

**Tests**: `test_migration_010.py::test_upgrade_is_idempotent_rerun_of_010_body` y `::test_downgrade_reverts_consistently_and_roundtrips`;
`test_migration_012.py::test_upgrade_body_is_idempotent`; `test_migration_013.py::test_upgrade_body_is_idempotent`;
`test_migration_014.py::test_la_migracion_no_toca_la_hash_chain_de_licencias` y `::test_downgrade_vuelve_a_la_escala_vieja_y_reupgrade_es_limpio`;
`test_migration_017.py::test_upgrade_body_is_idempotent`. [verificado: log]

### Causa — una sola raíz, tres de los ocho son cascada
- Los tests de idempotencia hacen `stamp <rev vieja>` sobre una base ya migrada a head y luego `upgrade head`,
  o sea **vuelven a ejecutar todas las migraciones posteriores** (`test_migration_012.py:313-314`, `_013.py:181-182`,
  `_017.py:300-301`, `_010.py:113`, `_014.py:156-157`). Así deben fallar si alguna migración no es idempotente.
- Cadena actual: `… 019 → 020 → 7a6fee614cfd → 199fe429762a (head)`. [verificado: `alembic heads` local → `199fe429762a (head)`;
  `down_revision` de cada una]
- `backend/alembic/versions/7a6fee614cfd_groups_deactivation.py:28-30` usa `op.add_column('groups', sa.Column('is_active', …))`
  y `op.add_column('groups', sa.Column('deactivated_at', …))` **sin `IF NOT EXISTS`**. El DDL que emite es, textualmente, el del
  error del CI: `ALTER TABLE groups ADD COLUMN is_active BOOLEAN DEFAULT true NOT NULL`. [verificado: lo generé en modo SQL
  offline con un script desechable y coincide con el `[SQL: …]` del log]. En el log, cada fallo termina en
  `7a6fee614cfd_groups_deactivation.py:28` (traceback). [verificado]
- **Cascada** (3 fallos que no son raíz): el `stamp` queda aplicado (`Running stamp_revision 199fe429762a -> 009`) aunque el
  `upgrade` posterior aborte; el módulo comparte `engine`/base (`scope="module"`: `test_migration_010.py:19`,
  `test_migration_014.py:37`). El test siguiente encuentra la tabla `alembic_version` en 009/013 y su `downgrade` no hace nada:
  `test_migration_010::…roundtrips` ve `to_regclass('tenants')` todavía presente y `test_migration_014::…escala_vieja…` ve
  `(14, 8) == (10, 4)` (la escala nunca bajó). [verificado: los mensajes del log y los `stamp_revision` previos; el mecanismo de
  arrastre es deducción coherente con ambos — [no verificado] sin Postgres]

### Commit que lo introdujo
`29b6667` — «feat(054): baja de equipos», 17-sep-2026 (migración creada con id por hash, `alembic revision`). [verificado: `git log`]
El run de ese commit (`35201937183`) es el primero con los 8 fallos de migración. [verificado]

### Veredicto
**Bug en el código, no tests viejos.** La convención del repo es que toda migración sea re-ejecutable: `ADD COLUMN IF NOT EXISTS` en
`002`, `003`, `005`, `006`, `007`, `015`; `CREATE TABLE IF NOT EXISTS` en `001` [verificado: `grep` de `alembic/versions`], y los
tests de idempotencia existen justamente para exigirlo; la `015` lo dice en su docstring («aditiva e idempotente, mismo patrón que
la 002»). La `7a6fee614cfd` es la primera que lo rompe. No hay decisión de producto en contra.
**Por qué importa más que un test rojo**: una base sin `groups.is_active` pero con la versión adelantada (o un re-aplicado) falla al
arrancar; el backend traga ese error en `_run_alembic_upgrade_head` (`main.py:40-43`, «Alembic auto-run failed (schema may be
stale)») y sigue con el esquema desactualizado. [verificado: lectura de `main.py:40-43`]

### Arreglo propuesto
Archivos: `backend/alembic/versions/7a6fee614cfd_groups_deactivation.py` y —ver sección 7— `…/199fe429762a_users_must_change_password.py`.
- `upgrade()`: `op.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true")` y
  `… ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMP`; `downgrade()`: `DROP COLUMN IF EXISTS` en ambas. Mismo patrón que `015`.
- **No cambia el id de revisión** ni el `down_revision`; en bases ya en `head` (producción, que ya aplicó ambas) es un no-op.
  Retrocompatible. No hace falta una migración nueva: el fallo ocurre *dentro* de las existentes.
- Sentinel: ambas migraciones son «Base» en sus `HANDOFF-elea-a-sentinel.md` (054 `:19-27`, 055 `:21-33`); el arreglo hay que
  anotarlo para que Sentinel no importe la versión sin `IF NOT EXISTS`. Ver D7/D9.

### Cómo verificarlo
- **Sin Docker, parcial** [verificado]: (a) `alembic heads` (venv local) → un solo head; (b) el script desechable que ejecuta
  `upgrade()` de cada migración con `MigrationContext(as_sql=True)` imprime el DDL — después del arreglo debe contener
  `IF NOT EXISTS`. No hay Postgres local ni binarios de Postgres (verificado: `which postgres initdb` vacío).
- **Solo CI/PC con Docker**: los 7 archivos `test_migration_*.py` (todos hacen `require_postgres()`). Resultado esperado: los 8 verdes;
  si tras arreglar la 054 sigue rojo algo, lo siguiente en la cadena es la 055 (sección 7).

---

## 5. Grupo 4 — `test_build_ad_hoc_recognizers_latam_region_adds_dni_cuil`

### Causa
- Test: `backend/tests/test_policy_unit.py:346-349` →
  `assert entities == {"DNI", "CUIL", "PASSPORT"}`. Log: `Extra items in the left set: 'CBU'`. [verificado]
- Código: la tabla `STRUCTURED_ID_PATTERNS_BY_REGION["latam_ar"]` en `litellm/extensions/sentinel_guardian_policy.py:143-151` tiene
  hoy cuatro entradas: `DNI`, `CUIL`, `PASSPORT` y `CBU` (`:151`: `r"\b\d{22}\b"`, 0.85, contexto «cbu», «clave bancaria»,
  «cuenta bancaria»). `build_ad_hoc_recognizers` emite un reconocedor por entrada de la región (`:581-601`). [verificado]

### Commit que lo introdujo
`c9a98a8` (31-ago): «Enmascarado de CBU (latam_ar) — nunca estaba implementado, solo DNI/CUIL. Verificado en vivo: un CBU real ahora
sale como [CBU_0_...]». Tocó `litellm/extensions/sentinel_guardian_policy.py` y no el test. [verificado: `git show c9a98a8`;
`git log -S'"CBU"'`]. Enmascarado en el RAG que se pidió tras la prueba multi-usuario de Elea (hallazgo real de producto, no un cambio accidental).

### Veredicto
**Test viejo; CBU es decisión de producto vigente** (perfil Argentina, Ley 25.326). El resto del código ya asume CBU: el paracaídas
lo espeja (`sentinel_guardian_policy.py:225`, `_desde_principal("latam_ar", "DNI", "CUIL", "CBU", "PASSPORT")`) y tests más nuevos
(15-sep) ya están escritos **tolerantes al perfil**: `test_policy_unit.py:1195-1221`
(«un perfil sin CBU (Sentinel hoy) pasa igual»). El test del grupo 4 es el único que quedó con la igualdad exacta. [verificado]
Cuidado base/Sentinel: la tabla `latam_ar` es distinta en las dos líneas (Eleia tiene CBU, Sentinel no —`:202-203`), así que el test, que
vive en la base, no debe afirmar CBU.

### Arreglo propuesto
Archivo: `backend/tests/test_policy_unit.py:349`. Cambiar a un subconjunto: `assert {"DNI", "CUIL", "PASSPORT"} <= entities`
(el perfil mínimo argentino, igual criterio que `:1221`), y opcionalmente un assert aparte «si `CBU` está en la tabla principal,
el reconocedor lo trae con su patrón de 22 dígitos». Sin cambios de producto. Retrocompatible con Sentinel (sin CBU sigue verde).

### Cómo verificarlo
- **Sin Docker** [verificado]: `pytest tests/test_policy_unit.py -q` desde `backend/` con el venv local → hoy `1 failed, 288 passed`
  (~7 s). Es un test unitario puro; con el cambio debe dar `289 passed`. Nada queda para el CI remoto salvo la corrida completa.

---

## 6. Grupo 5 — `make -C deploy check-docs`: rutas `/exact-analysis/*`

### Causa
- `deploy/Makefile:65-66` ejecuta `python3 docs/test_gen_config_reference.py && python3 docs/tools/test_drift_gate.py && python3 docs/tools/drift_gate.py`
  **antes** de los checks con imágenes. El fallo es `docs/tools/test_drift_gate.py:144-149`
  (`test_rutas_en_paridad_con_el_openapi_publicado`): el eje A de `drift_gate.py` compara decoradores del backend con
  `docs/docs/api-reference/openapi.json` y reporta `documentado_no_existe`. [verificado]
- Las tres rutas son `/api/v1/exact-analysis/workspaces` (`openapi.json:6863`), `…/{workspace_id}/files` (`:6920`) y
  `…/{workspace_id}/query` (`:6987`). El backend ya no las sirve: el router `backend/src/api/exact_analysis.py` se **borró** (con su
  servicio y su test) en `904dd37`. [verificado: `git show --stat 904dd37`; `ls backend/src/api` no lo lista; `grep exact_analysis backend/src`
  solo encuentra el campo `kind` de workspaces]
- El `openapi.json` publicado se había regenerado por última vez en `22c70a6` (10-sep, «3 endpoints nuevos de /exact-analysis»),
  **antes** de borrar el router (13-sep). [verificado: `git log -- docs/docs/api-reference/openapi.json`]

### Commit que lo introdujo
`904dd37` — «Spec 050: Eleia Hub conector fino, motor tabular (DuckDB)…», 13-sep-2026: «Retirado el código de DB-GPT (api/exact_analysis,
service, test, compose, red, volumen)» **sin** correr `make docs-refs`. [verificado]. Es un olvido del Definition of Done del `AGENTS.md`
(«si la feature cambió la API… `make -C deploy docs-refs` corrido»), y el CI lo marcó rojo desde el primer run, pero estaba
sepultado bajo el rojo del grupo 2/4.

### Veredicto
**Documentación vieja, no código roto**: el backend está bien (el endpoint se retiró a propósito por la spec 050 FR-040/041); lo que
miente es la referencia del producto. Es la «mentira» que el gate fue diseñado para atrapar. Pero el arreglo no es solo borrar tres
rutas: ver los otros desvíos que la regeneración revela (abajo y sección 7).

### Estado real de la deriva (medido regenerando localmente, sin Docker)
Con `BRAND_NAME="AI Gateway" python scripts/export_openapi.py` (el mismo script y env de `make docs-refs` y de
`test_docs_apiref.sh:16`), comparado contra el publicado — **401 líneas distintas**: [verificado, en el scratchpad, sin tocar el repo]
- Sobran en el publicado (3 rutas): `/api/v1/exact-analysis/workspaces`, `…/{workspace_id}/files`, `…/{workspace_id}/query`;
  y 2 schemas: `ExactAnalysisWorkspaceCreate`, `Body_upload_exact_analysis_file_…`.
- Faltan en el publicado (2 rutas + 1 schema): `/api/v1/chat/rag-usage` (spec 053) y `/api/v1/users/groups/{group_id}` (spec 054, DELETE);
  schema `RagUsageReportSchema`. `drift_gate.py` ya lo reporta como `existe_no_documentado` (sin bloquear: sale 1 solo por las 3 mentiras).
- Cambiados: `/api/v1/users/groups`, schemas `WorkspaceCreate` (campo `kind`) y `GroupResponse` (`is_active`).

### Arreglo propuesto
1. **Primero** el arreglo del grupo 1: regenerar con el docstring actual publicaría «AnythingLLM», el número de spec y nombres de archivos
   internos en la referencia pública (`rag-usage` entraría con esa descripción). [verificado que la regeneración local incluye 4 apariciones de
   «AnythingLLM»]
2. Regenerar con `make -C deploy docs-refs` (archivo: `docs/docs/api-reference/openapi.json`; el target también corre
   `python3 docs/gen_config_reference.py`, ver sección 7-b).
3. Revisar las páginas de `docs/docs/**` que describan estos endpoints (hoy no hay referencias a `exact-analysis` en `docs/docs/**` salvo el
   openapi [verificado: `grep`]) y que la leyenda 🟢/🟡/🔵 de grupos/rag-usage sea honesta (DoD del `AGENTS.md`).
4. No editar el `openapi.json` a mano ni «borrar las 3 rutas»: `test_docs_apiref.sh:18-19` compara byte a byte contra el export del backend.

### Cómo verificarlo
- **Sin Docker** [verificado]: `python3 docs/tools/test_drift_gate.py && python3 docs/tools/drift_gate.py` (stdlib pura, ~1 s) reproduce hoy
  `FAIL test_rutas_en_paridad…` y `drift_gate.py` sale con 1. Tras regenerar deben dar verde y exit 0. También se puede regenerar el openapi
  con el venv (arriba) para inspeccionar el diff, pero **no commitear esa salida**: el CI/`docs-refs` lo genera dentro de la imagen
  del backend con dependencias fijadas y el check es byte-exacto; que el venv local produzca bytes idénticos es [no verificado].
- **Solo con Docker/CI**: `test_docs_apiref.sh` (usa `docker compose run … backend` y la imagen `sentinel-docs:prod`), y el resto de los
  pasos de `check-docs` (`deploy/Makefile:67-75`: imagen, build estricto, contenido, naming, white-label, búsqueda offline, estructura,
  versionado). Requieren aviso previo al owner (no se corrieron).

---

## 7. Hallazgos ocultos: lo que va a aparecer al arreglar lo anterior

**a) `199fe429762a` (spec 055, `must_change_password`) tiene el mismo defecto que la 054.**
`backend/alembic/versions/199fe429762a_users_must_change_password.py:25-27`: `op.add_column('users', sa.Column('must_change_password', …))`,
sin `IF NOT EXISTS`. DDL emitido: `ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT false NOT NULL`. [verificado: modo SQL
offline]. Hoy no se ve en el log porque la cadena aborta en la 054 antes de llegar a ella. Es head (`down_revision = 7a6fee614cfd`), introducida por `a536820`
(21-sep). Debe arreglarse junto con la 054 o los ocho tests seguirán rojos. [verificado el defecto; que sea lo único que quede rojo es [no verificado]]

**b) `check-docs` corta en el primer fallo**: la receta de `deploy/Makefile:66` encadena con `&&`, y `make` aborta en el primer
comando que falla. Pasos posteriores nunca corrieron en estos 5 semanas, y al menos uno falla con certeza:
- `deploy/release/checks/test_docs_apiref.sh:16-19` (openapi vs backend): falla hoy por la deriva medida en el grupo 5. [verificado: la regeneración local difiere en 401 líneas]
- `test_docs_apiref.sh:22-27` (`configuration.md` vs `.env.example`): al correr `python3 docs/gen_config_reference.py` localmente, `configuration.md` **cambió**
  (28 líneas): desaparece la sección escrita a mano «Eleia Hub y motores (perfiles `rag`, `tabular`, `presentations`; spec 050)» y se agregan al final
  `TABULAR_INTERNAL_TOKEN`, `TABULAR_URL`, `TABULAR_ENGINE_VIRTUAL_KEY`, `TABULAR_MODEL`… con la descripción pegada al banner del `.env.example`
  («── Motor tabular (spec 050, perfil `tabular`) ───… Token interno Hub → tabular…»). [verificado: `git diff` del archivo, que **revertí** (`git checkout`) —
  el árbol quedó limpio]. Causa: `configuration.md` fue editado a mano en `fc1b311`/`cafbacd` (14-sep) y no sale de `.env.example` (último cambio `904dd37`, 13-sep).
  Dos consecuencias: el gate de deriva fallaría, y la regeneración filtraría «spec 050» y el banner a la documentación pública. Ver D5.
- Los otros 8 pasos de `check-docs` (neutralidad de nombres, white-label, estructura, versionado, etc.): [no verificado] — no corrieron en el CI ni los corrí (necesitan imágenes).

**c) Orden obligatorio**: grupo 1 antes que la regeneración del grupo 5 (si no, se publica el nombre del motor de documentos).

**d) Cobertura que se pierde en silencio (grupo 2)**: mientras el contract de paralelismo siga contra un catálogo sin `ollama_chat/`,
`test_el_deployment_local_declara_su_tope_de_paralelismo` y `…no_reintenta` pasan sin mirar nada (`:113-157`); la verificación real de esos límites
queda solo en `test_engine_local_limits.sh` (`make check-engine-local-limits`). [verificado]

**e) Proceso**: cinco semanas de `main` rojo (tres causas independientes) sin bloquear merges: 39 de los últimos 40 runs de `main` terminaron en `failure` (el restante estaba en cola).
[verificado: `gh run list --limit 40`]. Un rojo temprano (prefijos) tapó la suite y los fallos reales se acumularon sin atribución. Ver D8.

---

## 8. Plan de arreglo sugerido (en PRs chicos, orden recomendado)

| PR | Contenido | Archivos | Toca base (Sentinel)? |
|---|---|---|---|
| A | Tests viejos: grupos 2 y 4 | `backend/tests/integration/test_chat_auto_router.py`, `backend/tests/contract/test_catalogo_motor_paralelismo.py`, `backend/tests/test_policy_unit.py` | Sí (tests de base; anotar) |
| B | Migraciones idempotentes: grupo 3 + 7a | `backend/alembic/versions/7a6fee614cfd_groups_deactivation.py`, `…/199fe429762a_users_must_change_password.py` | **Sí** — ambas «Base» en sus HANDOFF |
| C | Marca blanca: grupo 1 | `backend/src/api/chat.py` (decorador `description=` + docstring→comentario) | Sí (mínimo) |
| D | Referencias del sitio: grupo 5 + 7b | `docs/docs/api-reference/openapi.json`, `docs/docs/api-reference/configuration.md`, y según D5 `.env.example`; páginas de `docs/docs/**` afectadas | Eleia (docs/.env) |

Dependencias: C antes que D; A, B y C son independientes entre sí. Cada PR con TDD donde haya código (solo B y C son producto; B ya está cubierto por los
tests rojos —serían el «red» del TDD—, C por `test_branding_neutral_043`). Cada arreglo es «fix de causa clara → rama corta sin spec» según `AGENTS.md`.
Tras D: `make -C deploy check-docs` y la suite en CI remoto como gate.

---

## 9. Decisiones para el owner

Cada una con recomendación.

**D1. ¿El catálogo de dev Azure-only (sin modelo local ni OpenAI) es la decisión vigente?**
Los commits de 31-ago dicen que sí (alineado a producción, sin Ollama en el entorno). *Recomendación: sí; adaptar los tests (PR A), no el catálogo.* Consecuencia a aceptar:
en esa instalación el «respaldo al local» (spec 030 US3) queda inerte, y solo se ejerce en instalaciones con runtime local (plantillas de cliente).

**D2. ¿Qué hace el contract de paralelismo cuando el catálogo de dev no trae un local?**
Opciones: (i) `pytest.skip` con motivo que apunte a `test_engine_local_limits.sh`, que sí cubre las plantillas; (ii) montar `deploy/` en el contenedor del backend (cambia
`docker-compose.yml:221-223`) para que pytest lea las plantillas; (iii) restaurar un deployment local en dev. *Recomendación: (i)* —menor superficie y es lo que el comentario
del propio test dice sobre el límite de lo que pytest ve—; (iii) revierte D1.

**D3. ¿Se confirma `CBU` como entidad permanente del perfil `latam_ar` de Eleia?**
Está en producción y verificado en vivo (31-ago). *Recomendación: sí; test tolerante a perfil (`⊇`) para que valga también en Sentinel.* Si en cambio se quisiera sacarlo, habría que
revertir `sentinel_guardian_policy.py:151` y `:225`, lo que reabre el hueco de enmascarado que `c9a98a8` cerró.

**D4. ¿Cómo se neutraliza `POST /chat/rag-usage` en el OpenAPI?**
Opciones: (i) `description=` neutro en el decorador y el texto largo a comentario; (ii) `include_in_schema=False` por ser un endpoint del Hub y no de integradores (el gate de deriva respeta ese flag a nivel de router —`drift_gate.py:243-263`—; a nivel de ruta suelta es [no verificado]); (iii) agregar `anythingllm` a `EXCEPCIONES` del test. *Recomendación: (i)*; (ii) es defendible si el equipo no quiere documentar un endpoint interno
del Hub; (iii) no. Decisión conexa: **¿sumar `anythingllm` a `prohibited_names.txt`?** Hoy no está y hay una aparición pública legítima de la variable `ANYTHINGLLM_API_KEY` en
`configuration.md` —sumarlo sin resolver eso rompe `check-docs`. *Recomendación: no tocar la lista en este ciclo; abrir un tema aparte.*

**D5. ¿Cómo se resuelve `configuration.md` ↔ `.env.example`?**
Opciones: (i) mover el contenido de la sección escrita a mano «Eleia Hub y motores» a banners/comentarios de `.env.example` en el formato que entiende `docs/gen_config_reference.py`
(sin números de spec) y regenerar; (ii) regenerar tal cual y perder la sección. *Recomendación: (i)* — es la fuente única de verdad y evita que «spec 050» llegue a la doc pública. Toca
`.env.example` → `make -C deploy docs-refs` obligatorio.

**D6. ¿Autoriza el owner correr Docker para el cierre?**
Necesario para: `make -C deploy docs-refs` (regenerar el openapi con las dependencias del contenedor — la salida local puede diferir en bytes), `make -C deploy check-docs`, y
`docker compose run --rm --no-deps backend pytest tests/ -q` (migraciones y auto-router necesitan Postgres). *Recomendación: sí, una sola ventana al final de los PRs A–D; el resto
se verifica sin Docker.* No se corrió nada con Docker en este diagnóstico.

**D7. ¿Se edita en el lugar las migraciones `7a6fee614cfd` y `199fe429762a`?**
Alternativa: dejarlas y cambiar los tests de idempotencia para que hagan `stamp` desde `020`. *Recomendación: editarlas en el lugar* (`IF NOT EXISTS`, mismo id, no-op en bases ya migradas):
es lo que exige la convención del repo y evita normalizar migraciones no re-ejecutables; ocultar el problema en los tests dejaría una base a medio migrar rompiendo el arranque (hoy
`main.py:40-43` solo lo loguea).

**D8. ¿Política de merge con CI rojo?**
Hubo 5 semanas de `main` rojo con tres causas apiladas, la primera tapando la suite. *Recomendación: hacer `backend-tests` check requerido en `main` (branch protection) y que el
primer rojo bloquee hasta ser atribuido; considerar partir `check-docs` en pasos separados con `if: !cancelled()` —o quitar el `&&` de `deploy/Makefile:66`— para que un fallo no esconda a los otros.*
(Es decisión de proceso del owner; no la toca este spike.)

**D9. Handoff a Sentinel.** Los arreglos de PR A, B y C tocan archivos base (`backend/src/api/chat.py`, migraciones 054/055, tests de base). *Recomendación: un solo
`HANDOFF-elea-a-sentinel.md` «fix-ci-main» después del merge, con: (1) las dos migraciones deben traerse con `IF NOT EXISTS`; (2) `test_policy_unit.py` tolerante a perfil; (3) `description=`
neutro en `rag-usage` (si Sentinel adopta el endpoint); (4) los fixtures de catálogo del test del auto-router.* El archivo de handoff lo redacta el coordinador (fuera del alcance de este spike).

---

## 10. Cómo se midió (comandos corridos, todos locales y sin Docker)

- `gh api repos/cluna-8/elea/actions/jobs/107216111181/logs` (log base); `gh run list --branch main --limit 100`; logs de 13 runs de `main` por `gh api …/jobs/<id>/logs`
  para ubicar cuándo apareció cada grupo.
- `git log -S`, `git log --format`, `git show --stat`, `git blame` sobre `backend/`, `litellm/`, `docs/`, `.github/`, `deploy/`.
- Venv del checkout principal (`/home/drexgen/Documents/ELEA/LLMADMIN-Elea/elea/backend/.venv/bin/pytest`) desde `backend/` de este worktree:
  - `pytest tests/contract/test_branding_neutral_043.py` → `2 failed, 3 passed` (reproduce el grupo 1).
  - `pytest tests/contract/test_catalogo_motor_paralelismo.py tests/test_policy_unit.py::test_build_ad_hoc_recognizers_latam_region_adds_dni_cuil tests/integration/test_chat_auto_router.py` →
    `2 failed, 3 passed, 1 skipped` (grupos 2-contract y 4 reproducidos; el auto-router se salta por falta de Postgres).
  - `pytest tests/test_policy_unit.py` → `1 failed, 288 passed`.
  - Suite completa local: `13 failed, 1552 passed, 112 skipped` en 56 s (sin Postgres: 112 skip). Los 13 = 2 (grupo 1) + 1 (grupo 2 contract) + 1 (grupo 4) + **9 solo-locales** que **no** aparecen
    en el CI (`tests/contract/test_route_parity.py` ×6 y `tests/integration/test_surface_routing.py` ×3, `KeyError: 'url'`/`'headers'`): se deben a este entorno, causa [no verificado]
    (probablemente variables del contenedor/compose que acá no existen); no son parte de este diagnóstico.
  - Scripts desechables (en el scratchpad de sesión, fuera del repo): lista de operaciones del OpenAPI con términos prohibidos; export del OpenAPI vivo y diff contra el publicado; DDL en modo SQL offline de
    las migraciones `7a6fee614cfd` y `199fe429762a`.
- `python3 docs/tools/test_drift_gate.py` y `python3 docs/tools/drift_gate.py` (stdlib): reproducen el grupo 5. `python3 docs/gen_config_reference.py` (modificó `configuration.md`; revertido con `git checkout`).
- Restricciones respetadas: ningún `docker`/`docker compose`/`make check*`; ningún cambio fuera de este archivo (el árbol de trabajo quedó limpio salvo este documento).

---

## 11. No verificado

1. **Todo lo que requiere Postgres**: los 8 tests de migración, los 7 de `test_chat_auto_router.py` y `test_rag_usage_053.py` no se ejecutaron. Los veredictos de los grupos 2 (integración) y 3 salen del log del CI, del código y de la
   salida SQL offline; que los arreglos propuestos los pongan en verde es una predicción, no una medición.
2. El **mecanismo de cascada** en los tests 010-downgrade y 014-downgrade (el `stamp` residual) es una deducción consistente con los mensajes del log; no se reprodujo.
3. Que tras arreglar 054 y 055 **no queden más fallos** en la cadena de migraciones (p. ej. un `downgrade` roto en alguna intermedia): no verificable sin Postgres.
4. **`check-docs` completo**: los pasos posteriores al drift gate (`deploy/Makefile:67-75`) nunca corrieron en el CI y no los corrí (requieren imágenes). Solo está verificado el fallo de `test_docs_apiref.sh` por la
   regeneración local, y no byte a byte contra la salida del contenedor.
5. Que el **export del OpenAPI con el venv local** sea byte-idéntico al del contenedor (versiones de FastAPI/Pydantic pueden diferir). Por eso no se commitea esa salida.
6. Que `test_fallback_escala_lineal_no_redos` (falló una vez el 31-ago) sea un test de tiempos/flaky.
7. La causa de los 9 fallos **solo-locales** (`test_route_parity`, `test_surface_routing`).
8. El resultado del run `37374302720` (merge del PR #4, 5-oct), que estaba en cola: no lo esperé. Como no hay cambios de código desde `ec03a6f`, se espera el mismo conjunto de fallos, pero no lo medí.
9. Cuál es la política real de branch protection de `main` (no tengo acceso a esa configuración desde acá); D8 asume que `backend-tests` no es requerido.

---

## 12. Estado de los grupos (arreglos aplicados, 5-oct-2026)

Decisiones del owner: se aprobaron todas las recomendaciones de la §9 (D1–D9). D6 (Docker) solo en una
ventana final coordinada por Atlas. Un commit por grupo, en el orden de la §8 (grupo 1 antes de regenerar docs).

| Grupo | Commit | Estado | Qué queda verificado | Qué queda para CI/ventana |
|---|---|---|---|---|
| 4 — policy latam_ar | `f71ccd6` | Arreglado | `pytest tests/test_policy_unit.py` → 290 passed (venv local) | — |
| 2 — catálogo + auto-router | `2975234` | Arreglado | contract: `1 passed, 3 skipped` (skip por D2 i); lógica del fixture simulada sin DB | 7 de `test_chat_auto_router.py` (Postgres) |
| 3 — migraciones | `05511a9` | Arreglado (7a + 7a' = 199fe429762a) | `alembic upgrade 020:head --sql` emite `IF NOT EXISTS`; un solo head | 7 archivos `test_migration_*.py` (Postgres) |
| 1 — marca blanca | `266b644` | Arreglado | `test_branding_neutral_043.py` → 5 passed | `test_rag_usage_053.py` (Postgres) |
| D8 — `check-docs` no se corta | `34fba21` | Hecho | mecanismo probado con un makefile de juguete | corrida real de `make -C deploy check-docs` |
| 5 — referencias del sitio | `82f56b1` | Arreglado, **por confirmar con Docker** | `docs/test_gen_config_reference.py` (13 ok), `docs/tools/test_drift_gate.py` y `drift_gate.py` (VERDE, exit 0), `test_docs_structure.sh`, `test_engine_admission_wiring.sh` | `make -C deploy docs-refs` debe dejar `git diff` vacío; `make -C deploy check-docs` |

Notas del grupo 5:
- `openapi.json` se regeneró con el venv local (fastapi 0.111.0, pydantic 2.13.4: los pins de `backend/requirements.txt`)
  y el diff contra el publicado fueron exactamente las 3 rutas + 2 schemas sobrantes y las 2 rutas + 1 schema
  faltantes (+ `GroupResponse`/`WorkspaceCreate`), sin ruido en el resto. Que sea byte-idéntico al del contenedor sigue
  siendo [no verificado] hasta la ventana.
- Resuelto D5 (i): `configuration.md` ya sale por completo de `.env.example` (sección «Eleia Hub y motores» en un banner
  con los datos que estaban solo en la doc: defaults del historial, puerto de plantillas, `SENTINEL_NLP_TIMEOUT_S=60`).
- Residuos conocidos, **no tocados** (D4: no se toca `prohibited_names.txt` este ciclo): la página pública sigue
  mostrando las variables `ANYTHINGLLM_API_KEY` y `PRESENTON_*` y el default `http://presenton:80` (antes estaba
  en la descripción); el título de la sección RAG sigue diciendo «spec 040». Es el mismo tema aparte de D4.
- Verificación local de la suite completa (venv, sin Postgres): `9 failed, 1554 passed, 115 skipped`. Los 9 son los
  «solo-locales» de la §10 (`test_route_parity` ×6, `test_surface_routing` ×3: «could not translate host name db»),
  los mismos de antes y fuera de este diagnóstico. Antes: `13 failed, 1552 passed, 112 skipped`.

### Ventana con Docker (la coordina Atlas), comandos en orden

```
make -C deploy docs-refs                                   # regenera openapi.json y configuration.md; git diff debe quedar vacío
make -C deploy check-docs                                  # ahora corre todos los pasos y lista todos los fallos
make -C deploy check                                       # gate de artefactos
docker compose run --rm --no-deps backend alembic upgrade head
docker compose run --rm --no-deps backend pytest tests/ -q # suite completa con Postgres (migraciones, auto-router, rag-usage)
```

Si `docs-refs` deja diff en `openapi.json`, commitearlo (es lo que manda el contenedor). Si la suite deja rojo algo en la
cadena de migraciones tras la 054/055, ver §11.3.

## 13. Para el handoff a Sentinel

Archivos **base** tocados (Atlas redacta `HANDOFF-elea-a-sentinel.md` «fix-ci-main»; Sentinel no debe importar las versiones anteriores):

1. **Migraciones** (`backend/alembic/versions/`): `7a6fee614cfd_groups_deactivation.py` y
   `199fe429762a_users_must_change_password.py` quedan con `ADD COLUMN IF NOT EXISTS` / `DROP COLUMN IF EXISTS`. Mismo id y
   mismo `down_revision`; no-op en bases ya migradas. Ambas son «Base» en los handoffs de 054 y 055: traerlas con el arreglo.
2. **`backend/src/api/chat.py`** (`report_rag_usage`, `POST /chat/rag-usage`): `description=` neutro en el decorador y el
   docstring pasa a comentario `#`. Aplica solo si Sentinel adopta el endpoint (spec 053); retrocompatible.
3. **Tests de base**: `backend/tests/test_policy_unit.py` (latam_ar con `⊇` en vez de igualdad: la tabla de Sentinel no
   trae CBU y debe seguir verde); `backend/tests/integration/test_chat_auto_router.py` (fixture `catalogo_temporal` autouse y
   autocontenido con deployments sintéticos); `backend/tests/contract/test_catalogo_motor_paralelismo.py` (skip si el
   catálogo de dev no declara un `ollama_chat/`, con motivo que apunta a `test_engine_local_limits.sh`).
4. **`.env.example` / `docs/`** son de Eleia, **no** base: la sección «Eleia Hub y motores» y `docs/docs/api-reference/*`
   no se portan. `docs/gen_config_reference.py` y el drift gate no se tocaron.
5. **`deploy/Makefile`** (`check-docs`): ya no corta en el primer fallo; si Sentinel comparte ese Makefile, conviene
   adoptarlo, pero es de proceso y no cambia contratos.
