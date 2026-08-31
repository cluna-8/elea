# Spec 016 — Notas de implementación

**Fecha**: 2026-07-22 · **Estado**: **Lista para merge** — US1 + US2 + US3 + US4 + US5
implementadas y verificadas (unit/contract/integration/e2e, suite completa dentro del
container real del backend: 293 passed, 10 skipped). `make -C deploy check-docs` verde
(incl. naming neutro). Rama rebaseada sobre `main` y pusheada (`--force-with-lease`); PR
#21 en `MERGEABLE`/`CLEAN`. Único punto diferido: T024 (ver "Qué queda" al final).

## Qué se entregó

- **Motor NLP real** (US1/US2): sidecar propio `presidio-analyzer/` (Presidio Analyzer +
  spaCy `es_core_news_md`, imagen propia — la oficial no trae español), servicio compose
  `nlp-analyzer` (ver "Naming neutro" abajo), expone `/analyze` con soporte de
  `ad_hoc_recognizers` (patterns + deny_list + context).
- **`STRUCTURED_ID_PATTERNS_BY_REGION`** (`sentinel_guardian_policy.py`): reemplaza los dos
  diccionarios `PII_PATTERNS` duplicados (research §3). Región `"eu"` (default,
  `SENTINEL_ENTITY_REGION`): solo `PASSPORT` ad-hoc — `ES_NIF`/`ES_NIE` son built-in de
  Presidio con checksum, no se reimplementan. Región `"latam_ar"` (inactiva, preparada):
  `DNI`/`CUIL`/`PASSPORT`. **Corrección post-review**: el despliegue objetivo es Europa
  (España primero), no Argentina — el research/spec originales asumían DNI/CUIL como
  ejemplo y se corrigieron.
- **`build_ad_hoc_recognizers`/`presidio_analyze`/`resolve_overlaps`/`resolve_entity_action`**
  (`sentinel_guardian_policy.py`, librería PURA compartida motor+backend): única fuente de
  patrones y de resolución de solapamientos/acción por tipo. `resolve_overlaps` usa
  clustering de intervalos (no comparación par-a-par) — resuelve correctamente 3+
  entidades solapadas en cadena. `mask_text` ahora llama `resolve_overlaps` internamente
  (defensa en profundidad — antes confiaba en que el `analyze` inyectado ya lo hubiera
  hecho, contrato implícito y frágil; expuesto por un stress test nuevo, T031).
- **Fail-closed real** (US3): `NlpUnavailableError` — timeout/5xx/conexión rechazada del
  Analyzer ya NO produce `[]` silencioso (fail-open heredado); el guardrail retorna motivo
  de bloqueo `nlp_unavailable` por el mismo canal que AI-Act/secretos.
- **`entity_configs` conectado al firewall real** (US2): `custom_auth._IDENTITY_SQL`
  extendida para traer la `SecurityPolicy` activa; `SentinelGuardrail.async_pre_call_hook`
  resuelve MASK/BLOCK por tipo vía `resolve_entity_action` ANTES de tocar el body (un solo
  preview de detección, no se enmascara para bloquear después).
- **Consistencia panel/playground vs firewall** (US4, T028/T029): `presidio_service.py`
  reescrito para consumir la misma librería PURA (elimina su propio `PATTERNS` duplicado),
  deja de fail-open en `analyze_text_http`. `guardian_service.py` migra el catálogo de
  entidades del Guardian por defecto de Argentina (`DNI`/`CUIL`) a EU (`PERSON`, `ES_NIF`,
  `ES_NIE`, `PASSPORT`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IBAN_CODE`, `CREDIT_CARD`) con
  migración-on-read (mismo patrón que la migración existente de `custom_names`); degradación
  a regex de dev **visible** (trigger `DEGRADED` auditado), nunca silenciosa, si
  `NLP_ANALYZER_URL` no está configurada.
- **Catálogo de entidades custom con asistente de IA** (US5): `entity_catalog_service.py`
  — `draft_entity()` pide a un modelo barato (`gemini-2.5-flash-lite`) un patrón regex a
  partir de una descripción en lenguaje natural; **nunca se auto-activa**. `create_custom_entity()`
  es el único punto de activación: valida seguridad del patrón (ReDoS), normaliza/valida
  `entity_type` (`^[A-Z][A-Z0-9_]*$`), rechaza duplicados activos, usa `SELECT ... FOR UPDATE`
  para lectura-modificación-escritura segura sin optimistic locking. 4 endpoints en
  `backend/src/api/guardians.py` bajo `/guardians/custom-entities/*`.
- **ReDoS real, no heurístico-only**: `_NESTED_QUANTIFIER_RE` (heurística estática, caso
  común) + verificación real en un **proceso** separado (`multiprocessing`, contexto
  `spawn`, `backend/src/services/_redos_worker.py`) con timeout real y `terminate()`/`kill()`.
  Se descartaron 3 approaches previos: `signal.alarm` (falla fuera del hilo principal —
  las rutas sync de FastAPI corren en threadpool), el módulo `regex` con su `timeout=`
  nativo (motor de matching distinto a `re`, falsos negativos en backtracking catastrófico),
  y `re` + `ThreadPoolExecutor.result(timeout=)` (`re` no libera el GIL durante backtracking
  catastrófico, el hilo watchdog también queda bloqueado). `test_pattern()` (usado por el
  draft de IA) ahora tiene la misma protección de timeout que `validate_pattern_safety`
  (antes sin protección — hallazgo de review).

## Naming neutro (Principio VII) — hallazgo post-review

`make -C deploy check-docs` (`test_docs_neutral_naming.sh`) falló al regenerar la doc
publicada: el env var `PRESIDIO_ANALYZER_URL` (nombre de variable) y su valor default
`http://presidio-analyzer:3000` (hostname del servicio compose) filtraban el nombre del
motor/internals al sitio publicado (`configuration.md`, autogenerado desde `.env.example`).
Fix en dos pasos:
1. Rename del env var: `PRESIDIO_ANALYZER_URL` → `NLP_ANALYZER_URL` (7+ archivos:
   `.env.example`, `docker-compose.yml`, `contract_checks.py`, `sentinel_guardrail.py`,
   `sentinel_guardian_policy.py` (comentario), `guardian_service.py`, tests e2e, specs internas).
2. Rename del servicio/hostname compose: `presidio-analyzer` → `nlp-analyzer` (service key,
   `container_name: sentinel-nlp-analyzer`, `depends_on`, todas las URLs `http://…:3000`) — el
   directorio interno de build `presidio-analyzer/` se dejó **sin cambiar** (no es
   customer-facing, solo estructura de repo).

Verificado: `make -C deploy docs-refs` + `make -C deploy check-docs` full (9 checks) verdes
tras el rename.

## Nota de Contrato — regional fallback (hallazgo de review, ver `spec.md` FR-003)

El regex de dev/demo (`default_analyze`, sin NLP real levantado) es un piso de cobertura
genérico, **no** una réplica por región del motor NLP. Con `SENTINEL_ENTITY_REGION=eu`
(default) ese fallback ya no produce un tipo `DNI` distinguible — un DNI español cae
dentro del patrón genérico `PHONE_NUMBER` del fallback. Esto **no** es un bug: la
detección precisa por región depende del motor NLP real (built-in con checksum), y el
fallback nunca es el camino que valida FR-003 en producción (FR-004 bloquea si no está
disponible). 3 archivos de test asumían el tipo `DNI` distinguible en el fallback y se
corrigieron: `tests/contract/test_route_parity.py`, `tests/integration/test_gw_inspect.py`,
`tests/e2e/test_browser_dlp_e2e.py`.

## Verificación

| Caso | Resultado |
|---|---|
| Suite completa (`pytest tests/`, dentro del container real del backend) | **293 passed, 10 skipped** |
| `contract_checks.py` (dentro de la imagen litellm pinneada) | OK, incl. checks nuevos de 016 |
| `docker exec` — `PERSON` sin prefijo + `ES_NIF` tras migración EU | detectados correctamente (verificado live) |
| Fail-closed real (Presidio caído) | bloqueo `nlp_unavailable`, no `[]` silencioso |
| `entity_configs` BLOCK vs MASK (e2e real, `custom_auth` + política real) | BLOCK rechaza, MASK enmascara y continúa |
| Overlap resolution (T031, stress test con `analyze` "ingenuo") | expuso y corrigió el gap de `mask_text` |
| `make -C deploy check-docs` | 9/9 checks verdes (incl. naming neutro) |

## Qué queda

- **T024** (contract test dedicado en `tests/contract/test_presidio_analyzer_contract.py` contra el
  `nlp-analyzer` real) **diferido por decisión de producto** (2026-07-22, no técnica) — lo esencial
  ya está cubierto por `contract_checks.py` (T033), que corre contra el Analyzer real cuando
  `NLP_ANALYZER_URL` está seteada. No bloquea el merge de este PR.
- Gap PHI clínico español (CIE-10, nº historia clínica) queda fuera de alcance — no pedido
  en las user stories de esta spec.

## Cierre de bloqueantes de la review (2026-07-23, lado JF)

Los dos bloqueantes del review del PR #21 se cerraron desde este lado para no frenar
el merge — el primero era íntegramente de `deploy/`, módulo nuestro.

1. **El analizador NLP no existía en el camino de producción.** El sidecar estaba solo
   en el compose de DEV: `deploy/` no lo definía en ningún lado, así que una instalación
   real levantaba el motor sin `NLP_ANALYZER_URL` y detectaba PII con las regex de
   dev/demo — en silencio, con la UI reportando enmascaramiento normal. Se agregó el
   servicio `nlp-analyzer` a `compose.prod.yml` (imagen `${NLP_ANALYZER_IMAGE:?}` +
   healthcheck + `depends_on` del motor), el build/push en `publish.sh`, la imagen en el
   `images.tar` del bundle air-gapped, y la variable en el módulo OpenTofu → cloud-init.
   La variable es `:?` a propósito: sin la imagen, la instalación **falla explícito** en
   vez de enmascarar de mentira. Verificado con `docker compose config` (con y sin la var).

   Ojo: son **dos** planos, no uno. Además del motor, el backend tiene su propio camino
   de detección (panel/playground, `guardian_service.analyze_prompt`) que también lee
   `NLP_ANALYZER_URL`, y ahí el degradado es peor: la rama `else` (variable ausente)
   escanea con regex y ni siquiera registra el trigger `DEGRADED` — solo lo hace el caso
   "URL puesta pero servicio caído". El compose de dev le pasaba la variable a los dos
   servicios; el de prod ahora también.

2. **La migración-on-read pisaba la configuración del cliente.**
   `get_or_create_default_guardians` corre en CADA `GET /api/v1/guardians`, y reescribía
   `entities` incondicionalmente: el administrador guardaba su lista y al siguiente refresco
   de la UI le volvía el default. Ahora se migra **solo** desde el default argentino viejo
   exacto (`PERSON/DNI/CUIL/EMAIL_ADDRESS/PHONE_NUMBER`) o cuando la clave nunca existió;
   cualquier otra lista es una elección del cliente y se respeta. Mismo criterio para
   `custom_names` (los nombres del piloto se siembran una vez; si el admin los borra, no
   resucitan). Cubierto por `backend/tests/unit/test_guardian_seed_migration.py` — 9 tests
   que fallan 6 contra el código anterior.

También se aplicó el punto 4 de la review (medio): `draft_entity` corría
`validate_pattern_safety`/`test_pattern` en línea dentro de un endpoint `async def`, y esas
funciones esperan subprocesos con `join(timeout)` — hasta ~15-20s con un patrón malicioso,
congelando el event loop del backend entero. Ahora van por `asyncio.to_thread`, así el
bloqueo queda contenido en la request que lo provocó. (`create_custom_entity` no necesita
el cambio: su endpoint es `def` sincrónico, que FastAPI ya corre en su threadpool.)

Suite completa tras los cambios: **303 passed, 7 skipped, 2 failed** — los dos fallos son
`test_browser_dlp_e2e`/`test_engine_roundtrip_e2e`, ambientales (401 contra el stack de dev
local, que corre otra rama) y **reproducidos idénticos sobre el código sin estos cambios**.

## Cierre

Rama rebaseada sobre `main` dos veces (main avanzó con el PR #38 en paralelo) con
`--force-with-lease`; suite completa reverificada en ambas (293 passed, 10 skipped) y
`check-docs`/`contract_checks.py` verdes. PR #21 en estado `MERGEABLE`/`CLEAN`, sin bloqueos
pendientes del lado técnico.
