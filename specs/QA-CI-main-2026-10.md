# Reporte de QA — Verificación de arreglos del CI de `main` (Octubre 2026)

**Fecha**: 2026-10-06  
**Rama**: `cluna-8/fix-ci-main-diag`  
**Referencia base**: `specs/DIAGNOSTICO-CI-main-2026-10.md`  
**Rol**: QA — Primer nivel de verificación  
**Veredicto General**: **APROBADO (VERDE)**  

---

## 1. Resumen Ejecutivo

Se realizó la revisión exhaustiva, grupo por grupo, del diff introducido en la rama `cluna-8/fix-ci-main-diag` contra el diagnóstico aprobado en `specs/DIAGNOSTICO-CI-main-2026-10.md` y las decisiones de diseño/producto del owner (§9, D1–D9).

1. **Revisión del diff**: Ningún test fue relajado sin justificación válida. Los cambios en los tests corresponden estrictamente a decisiones de producto vigentes aprobadas (perfil Argentina con CBU en Grupo 4; catálogo Azure-only en Grupo 2). En el Grupo 1 y Grupo 3 los tests no fueron modificados y se corrigió el código de producto y migraciones.
2. **Ejecución local**: Se ejecutaron con el entorno virtual local (`/home/drexgen/Documents/ELEA/LLMADMIN-Elea/elea/backend/.venv`) todos los tests y linters sin dependencia de base de datos Postgres de los 5 grupos y checks de despliegue/documentación. Todos pasaron satisfactoriamente.
3. **Restricción Docker**: No se invocó ningún comando Docker ni targets de Makefile que construyen imágenes de contenedor, respetando la política de ejecución local previa a la ventana coordinada.

---

## 2. Verificación Detallada Grupo por Grupo

### Grupo 1 — Marca blanca: Neutralización de `POST /chat/rag-usage` en OpenAPI

* **Commit**: `266b6440253e9a99b452642693753a62e0b5e025`
* **Archivos modificados**: `backend/src/api/chat.py:2054-2095`
* **Veredicto del diagnóstico (§2, D4)**: Bug en el código (FastAPI exponía el docstring técnico interno en el OpenAPI público).
* **Análisis del diff**:
  * En [`backend/src/api/chat.py:2054-2081`](file:///home/drexgen/orca/workspaces/elea/fix-ci-main-diag/backend/src/api/chat.py#L2054-L2081), el texto explicativo para mantenedores que mencionaba al motor de documentos («AnythingLLM»), archivos internos y número de spec se movió a comentarios `#` antes de la función.
  * En [`backend/src/api/chat.py:2082-2086`](file:///home/drexgen/orca/workspaces/elea/fix-ci-main-diag/backend/src/api/chat.py#L2082-L2086), se agregó el parámetro `description` con redacción neutra en el decorador `@router.post("/rag-usage", ...)`.
  * No se modificó el contrato HTTP, los tipos de schemas ni la lógica de negocio.
  * **Control de relajación de tests**: Los tests en [`backend/tests/contract/test_branding_neutral_043.py`](file:///home/drexgen/orca/workspaces/elea/fix-ci-main-diag/backend/tests/contract/test_branding_neutral_043.py) **NO fueron modificados**. No se agregaron excepciones a `EXCEPCIONES` ni se alteró `prohibited_names.txt`.
* **Evidencia de ejecución**:
  ```bash
  $ pytest tests/contract/test_branding_neutral_043.py -q
  .....                                                                    [100%]
  5 passed, 16 warnings in 1.68s
  ```
  *(Previamente: 2 failed, 3 passed).*

---

### Grupo 2 — Catálogo del motor y auto-router

* **Commit**: `2975234`
* **Archivos modificados**:
  * `backend/tests/contract/test_catalogo_motor_paralelismo.py:84-110, 131-135, 141, 170`
  * `backend/tests/integration/test_chat_auto_router.py:44-70, 224-250`
* **Veredicto del diagnóstico (§3, D1, D2)**: Tests viejos; el catálogo de dev (`litellm/config.yaml`) es Azure-only por decisión de producto documentada en `c9a98a8` y `484b5a9`.
* **Análisis del diff**:
  * **Contrato de paralelismo** ([`backend/tests/contract/test_catalogo_motor_paralelismo.py`](file:///home/drexgen/orca/workspaces/elea/fix-ci-main-diag/backend/tests/contract/test_catalogo_motor_paralelismo.py)):
    * En líneas `:84-104`, se definió `MOTIVO_SIN_LOCAL` y la función `_locales_o_skip()`. Si el catálogo no contiene deployments `ollama_chat/`, se invoca `pytest.skip(MOTIVO_SIN_LOCAL)` explicando que el runtime local reside en `deploy/clients/*/config.yaml.tmpl` y es verificado por `deploy/release/checks/test_engine_local_limits.sh`.
    * En línea `:131-135`, `test_el_catalogo_tiene_deployments_del_runtime_local` mantiene el assert explícito `assert catalogo.get("model_list")` y luego evalúa `_locales_o_skip()`.
    * Los tests `:141` y `:170` iteran `_locales_o_skip()`. Esto elimina la falsa sensación de cobertura previa (donde iteraban una lista vacía y pasaban sin evaluar nada).
  * **Auto-router** ([`backend/tests/integration/test_chat_auto_router.py`](file:///home/drexgen/orca/workspaces/elea/fix-ci-main-diag/backend/tests/integration/test_chat_auto_router.py)):
    * En líneas `:58-67`, se definieron `_DEPLOYMENTS_DE_PRUEBA` (`PREMIUM`, `ECONOMICO`, `LOCAL` con límites de paralelismo y reintentos).
    * En líneas `:224-250`, el fixture `catalogo_temporal` pasó a `autouse=True` e inyecta sintéticamente los modelos requeridos en la copia temporal de `config.yaml` sin alterar el archivo físico de desarrollo ni depender de su contenido.
  * **Control de relajación de tests**: Ningún assert de ruteo, costos o fallbacks fue eliminado o debilitado en `test_chat_auto_router.py`. En `test_catalogo_motor_paralelismo.py`, el skip está condicionado a la ausencia de deployments locales en dev y remite formalmente al script de gate de release que sí inspecciona las plantillas de cliente.
* **Evidencia de ejecución**:
  ```bash
  $ pytest tests/contract/test_catalogo_motor_paralelismo.py -rs
  s...
  =========================== short test summary info ============================
  SKIPPED [3] tests/contract/test_catalogo_motor_paralelismo.py:103: el catálogo de dev (`litellm/config.yaml`) es solo Azure desde c9a98a8/484b5a9 y no declara ningún deployment `ollama_chat/`: el runtime local vive en las plantillas `deploy/clients/*/config.yaml.tmpl`, que pytest no ve...
  1 passed, 3 skipped, 16 warnings in 1.30s
  ```
  ```bash
  $ pytest tests/integration/test_chat_auto_router.py -rs
  SKIPPED [1] tests/migration_harness.py:63: Postgres no disponible en localhost:5433 — levantar `docker compose up -d db`
  1 skipped in 0.86s
  ```
  ```bash
  $ deploy/release/checks/test_engine_local_limits.sh
  Catálogos del motor revisados:
     · litellm/config.yaml: 0 deployment(s) local(es)
     · camara-comercio/config.yaml.tmpl: 1 deployment(s) local(es)
     · example/config.yaml.tmpl: 0 deployment(s) local(es)
     · itv-examen/config.yaml.tmpl: 0 deployment(s) local(es)
     · motor 1.92.0: max_parallel_requests → Semaphore(20) ✔ · num_retries → 1 intento ✔
  ✅ límites del runtime local OK: declarados en todo catálogo conversable
     y honrados por la imagen pinneada del motor (techo real + un solo intento)
  ```

---

### Grupo 3 — Migraciones: Idempotencia en `7a6fee614cfd` y `199fe429762a`

* **Commit**: `05511a930c9f751af5e7abd73b212cfcadd53108`
* **Archivos modificados**:
  * `backend/alembic/versions/7a6fee614cfd_groups_deactivation.py:28-39`
  * `backend/alembic/versions/199fe429762a_users_must_change_password.py:25-34`
* **Veredicto del diagnóstico (§4, §7a, D7)**: Bug en el código (falta de cláusulas `IF NOT EXISTS` violando la convención de idempotencia del repositorio).
* **Análisis del diff**:
  * En [`backend/alembic/versions/7a6fee614cfd_groups_deactivation.py:29-39`](file:///home/drexgen/orca/workspaces/elea/fix-ci-main-diag/backend/alembic/versions/7a6fee614cfd_groups_deactivation.py#L29-L39):
    * `upgrade()` ejecuta `ALTER TABLE groups ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true` y `ALTER TABLE groups ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMP`.
    * `downgrade()` ejecuta `ALTER TABLE groups DROP COLUMN IF EXISTS deactivated_at` e `is_active`.
  * En [`backend/alembic/versions/199fe429762a_users_must_change_password.py:26-34`](file:///home/drexgen/orca/workspaces/elea/fix-ci-main-diag/backend/alembic/versions/199fe429762a_users_must_change_password.py#L26-L34):
    * `upgrade()` ejecuta `ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT false`.
    * `downgrade()` ejecuta `ALTER TABLE users DROP COLUMN IF EXISTS must_change_password`.
  * Se mantuvieron los mismos identificadores de revisión y grafo de `down_revision`.
  * **Control de relajación de tests**: Los tests de migración (`test_migration_*.py`) **NO fueron tocados**. La suite exigirá idempotencia real en la ventana con Postgres.
* **Evidencia de ejecución**:
  ```bash
  $ alembic heads
  199fe429762a (head)

  $ alembic upgrade 020:head --sql
  BEGIN;
  -- Running upgrade 020 -> 7a6fee614cfd
  ALTER TABLE groups ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
  ALTER TABLE groups ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMP;
  UPDATE alembic_version SET version_num='7a6fee614cfd' WHERE alembic_version.version_num = '020';

  -- Running upgrade 7a6fee614cfd -> 199fe429762a
  ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT false;
  UPDATE alembic_version SET version_num='199fe429762a' WHERE alembic_version.version_num = '7a6fee614cfd';
  COMMIT;

  $ alembic downgrade head:020 --sql
  BEGIN;
  -- Running downgrade 199fe429762a -> 7a6fee614cfd
  ALTER TABLE users DROP COLUMN IF EXISTS must_change_password;
  UPDATE alembic_version SET version_num='7a6fee614cfd' WHERE alembic_version.version_num = '199fe429762a';

  -- Running downgrade 7a6fee614cfd -> 020
  ALTER TABLE groups DROP COLUMN IF EXISTS deactivated_at;
  ALTER TABLE groups DROP COLUMN IF EXISTS is_active;
  UPDATE alembic_version SET version_num='020' WHERE alembic_version.version_num = '7a6fee614cfd';
  COMMIT;
  ```

---

### Grupo 4 — Política `latam_ar`: Tolerancia a perfiles regionales (CBU)

* **Commit**: `f71ccd66a955110d30a499579d1e411e9c46797f`
* **Archivos modificados**: `backend/tests/test_policy_unit.py:346-363`
* **Veredicto del diagnóstico (§5, D3)**: Test viejo; la entidad `CBU` en `latam_ar` fue incorporada intencionalmente en `c9a98a8` bajo los requerimientos de Eleia (Ley 25.326/AAIP).
* **Análisis del diff**:
  * En [`backend/tests/test_policy_unit.py:349`](file:///home/drexgen/orca/workspaces/elea/fix-ci-main-diag/backend/tests/test_policy_unit.py#L349), la aserción de igualdad exacta `assert entities == {"DNI", "CUIL", "PASSPORT"}` se reemplazó por la aserción de subconjunto:
    `assert {"DNI", "CUIL", "PASSPORT"} <= entities`.
  * En [`backend/tests/test_policy_unit.py:353-363`](file:///home/drexgen/orca/workspaces/elea/fix-ci-main-diag/backend/tests/test_policy_unit.py#L353-L363), se agregó la prueba `test_build_ad_hoc_recognizers_latam_region_cbu_si_la_tabla_lo_trae`, verificando específicamente que si `CBU` está en la tabla `STRUCTURED_ID_PATTERNS_BY_REGION["latam_ar"]`, se emite el reconocedor y su expresión regular reconoce adecuadamente un CBU de 22 dígitos.
  * **Control de relajación de tests**: La modificación está plenamente justificada. La igualdad estricta asumía que no existirían entidades adicionales en la región. El paso a subconjunto permite compatibilidad compartida de base entre Eleia (con CBU) y Sentinel (sin CBU), y la adición del segundo test garantiza que en Eleia el reconocedor de CBU no se degrade ni desaparezca.
* **Evidencia de ejecución**:
  ```bash
  $ pytest tests/test_policy_unit.py -q
  ........................................................................ [ 24%]
  ........................................................................ [ 49%]
  ........................................................................ [ 74%]
  ........................................................................ [ 99%]
  ..                                                                       [100%]
  290 passed in 7.42s
  ```
  *(Previamente: 1 failed, 288 passed).*

---

### D8 — Mecanismo `check-docs` no corta en el primer error

* **Commit**: `34fba2155337959f02ff34613aae77999035ac33`
* **Archivos modificados**: `deploy/Makefile:62-87`
* **Veredicto del diagnóstico (§7b, D8)**: Mejora de observabilidad de linters (evitar que un fallo temprano oculte fallos subsiguientes).
* **Análisis del diff**:
  * En [`deploy/Makefile:67-85`](file:///home/drexgen/orca/workspaces/elea/fix-ci-main-diag/deploy/Makefile#L67-L85), se encapsuló la invocación de cada paso bajo una función `run()`, acumulando errores y saliendo con código de error al final con un resumen legible de los pasos fallidos.
  * **Control de relajación**: No se suprimió ninguna verificación; se garantiza la ejecución integral de todas.

---

### Grupo 5 — Referencias del sitio: Eliminación de deriva doc ↔ código

* **Commit**: `82f56b123c3859fadef2dee05a8fc825590ba5b2`
* **Archivos modificados**:
  * `.env.example:19-21, 25-28, 64-92`
  * `docs/docs/api-reference/configuration.md:82-105`
  * `docs/docs/api-reference/openapi.json`
* **Veredicto del diagnóstico (§6, §7b, D5)**: Documentación y referencias desactualizadas tras la remoción del router `/exact-analysis` (spec 050) y cambios de endpoints de specs 053/054.
* **Análisis del diff**:
  * `docs/docs/api-reference/openapi.json`: Removidas las 3 rutas obsoletas de `/exact-analysis` (`/workspaces`, `/{workspace_id}/files`, `/{workspace_id}/query`); incorporados `POST /api/v1/chat/rag-usage` (con descripción neutra) y `DELETE /api/v1/users/groups/{group_id}`.
  * `.env.example`: Formateadas las secciones y comentarios para `Eleia Hub y motores` con banners reconocibles por `docs/gen_config_reference.py` sin exponer números de spec internos en la documentación generada.
  * `docs/docs/api-reference/configuration.md`: Regenerado a partir de `.env.example`.
  * **Control de relajación de tests**: Ningún linter de documentación fue alterado.
* **Evidencia de ejecución**:
  ```bash
  $ python3 docs/test_gen_config_reference.py && python3 docs/tools/test_drift_gate.py && python3 docs/tools/drift_gate.py
  ✅ 13 tests
  VERDE — 0 fallo(s)

  GATE DE DRIFT DOC ↔ CÓDIGO — PASS
  | Eje | Código | Doc | Δ |
  |---|---|---|---|
  | rutas | 92 | 92 | +0 |
  | config | 94 | 45 | +49 |
  | contratos | 17 | 14 | +3 |

  MENTIRAS — la doc lo promete y el código no lo tiene: 0
  HUECOS — el código lo hace y nadie lo escribió: 31
  ORQUESTACIÓN — informativo, no cuenta como hueco: 21
  ```
  ```bash
  $ deploy/release/checks/test_docs_structure.sh
  ✅ estructura OK: template de GUÍA/RUNBOOK cumplido, diagramas presentes, 0 huérfanas

  $ deploy/release/checks/test_engine_admission_wiring.sh
  ✅ perillas de admisión cableadas en prod y dev (5/5), defaults dentro
     del rango del código, documentadas en .env.example y en la referencia del sitio

  $ deploy/release/checks/test_no_engine_name.sh
  ✅ marca blanca OK: motor no expuesto; marca como config en runtime
  ```

---

## 3. Corrida Completa de la Suite Local

Se ejecutó la totalidad de la suite de tests de `backend/` en el entorno local (sin base Postgres activa):
```bash
$ pytest tests/ -q
FAILED tests/contract/test_route_parity.py::test_endpoint_masks_upstream_and_unmasks_reply
FAILED tests/contract/test_route_parity.py::test_endpoint_redact_off_header_is_ignored
FAILED tests/contract/test_route_parity.py::test_endpoint_redact_on_header_forces_masking
FAILED tests/contract/test_route_parity.py::test_endpoint_streaming_unmask[False]
FAILED tests/contract/test_route_parity.py::test_endpoint_streaming_unmask[True]
FAILED tests/contract/test_route_parity.py::test_endpoint_forwards_oauth_verbatim
FAILED tests/integration/test_surface_routing.py::test_passthrough_routes_to_anthropic_verbatim_oauth
FAILED tests/integration/test_surface_routing.py::test_passthrough_forwards_anthropic_headers
FAILED tests/integration/test_surface_routing.py::test_xsentinel_key_excluded_stays_passthrough
=================== 9 failed, 1554 passed, 115 skipped, 130 warnings in 39.97s ===================
```

* **Diagnóstico de los 9 fallos**: Son exactamente los 9 fallos solo-locales documentados en `DIAGNOSTICO-CI-main-2026-10.md` §10 y §12 (`test_route_parity` ×6 y `test_surface_routing` ×3 causados por resolución de host `db` ausente en el host sin red Docker).
* **Comparativa con el punto de partida**:
  * Antes de los arreglos: `13 failed, 1552 passed, 112 skipped` (los 9 locales + 2 de Grupo 1 + 1 de Grupo 2 contract + 1 de Grupo 4).
  * Tras los arreglos: `9 failed, 1554 passed, 115 skipped` (los 4 fallos de los grupos 1, 2 y 4 quedaron 100% resueltos).

---

## 4. Estado para la Ventana con Docker y Merge

Todos los puntos verificables sin Docker están en verde. Para la ventana coordinada por Atlas con Docker y Postgres levantado, quedan únicamente las verificaciones finales:
1. `make -C deploy docs-refs` (verificar que `git diff` quede vacío en `openapi.json`).
2. `make -C deploy check-docs` (ejecución completa con imágenes `sentinel-docs:prod`).
3. `make -C deploy check` (gate de artefactos).
4. `docker compose run --rm --no-deps backend pytest tests/ -q` (verificar verde de los 7 tests de `test_migration_*.py`, los 7 de `test_chat_auto_router.py` y `test_rag_usage_053.py`).

**Conclusión QA**: La rama `cluna-8/fix-ci-main-diag` cumple estrictamente con el diagnóstico aprobado y los criterios de aceptación. No se relajó ningún test sin justificación y los resultados locales coinciden al 100% con lo proyectado.
