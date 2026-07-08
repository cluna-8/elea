# Changelog — Spec 012: Ahorro de Costes IA — Compresión de Tokens y Reducción de Costes

## [0.5.0] — 2026-07-08

### Cierre del spec — US5-resto + US6 (spec 012 CERRADO)

> **Decisión de producto (restricción verbatim)**: la estrategia `llm` de US5 (un
> modelo barato comprime el prompt, 60–95% ahorro) está **descartada** por la
> restricción "no gastar tokens para ahorrar tokens" — es circular (gasta tokens
> para ahorrar tokens). Lo que sí se implementa de US5 es la **caché Redis por hash**
> (no gasta tokens: evita recomprimir duplicados) + el guard fail-open.

- **US5-resto — Caché Redis por hash (`optimization_service.py`)**:
  - `compress_context` ahora cachea por `sha256(strategy|aggressiveness|prompt)` en
    Redis (TTL `COMPRESSION_CACHE_TTL=86400`, gate `COMPRESSION_CACHE_ENABLED=true`).
    Fail-open: sin Redis comprime sin caché. **No gasta tokens** — solo evita recomputar.
  - `strategy="llm"` → **descartado**: cae a `headroom` (si JSON) o `deterministic`
    con warning, sin llamar a ningún modelo. Cumple "no gastar tokens".
- **US6 — Telemetría + guardia de calidad**:
  - **Telemetría por modelo** (`analytics.py`): `models[]` ahora incluye
    `prompt_tokens`, `tokens_saved`, `cost_saved_usd`, `compression_ratio` y
    `reversions`; el `summary` añade `compression_reversions` (total). Permite ver
    ratio de compresión y ahorro USD por modelo + detectar reversiones por estrategia.
  - **Guardia de reversión** (`chat.py`): tras una respuesta 200 con `tokens_saved>0`,
    si `OptimizationService.response_is_anomalous(content, completion_tokens)`
    (vacía / < `COMPRESSION_REVERSAL_MIN_CHARS=5` / 0 tokens), reintenta UNA vez con
    el prompt original (sin comprimir); si mejora, restaura la respuesta, anula el
    ahorro y marca `compression_reversed=True`. Gate `COMPRESSION_REVERSAL_GUARD=true`.
    Fail-open: nunca rompe el flujo. `pipeline_metadata.layer_optimization.reversed`
    expuesto en la respuesta.
- **Migración 009** (idempotente, `008→009`): `audit_logs.compression_strategy`
  (`deterministic|headroom|none`) + `audit_logs.compression_reversed` (BOOLEAN).
  Modelos + `AuditService.log_transaction` actualizados.
- **Tests** (`test_optimization.py`): +4 tests (20 total) — `llm` cae a local sin
  gastar tokens (mismo ahorro que deterministic), caché store+hit real contra Redis,
  detección de anomalía (vacío/corto/0-tokens) y respuesta normal no anómala.

### Verified (E2E)
- `pytest tests/` → **20 passed**. Alembic en head `009`.
- Calculadora headroom: JSON 200-ítems → 6617→2426 tokens (4589 saved, ratio 69%, "conviene").
- Analytics E2E: audit sintético `compression_reversed=true, tokens_saved=300` →
  `compression_reversions=1`, `ratio=0.2095`, `cost_saved=4.5e-05` (limpiado tras prueba).
- Caché: Redis reachable desde backend; test de cache HIT real verificado.

### Nota
La guardia de reversión (US6.2) y el path de chat con compresión no se prueban E2E
en vivo porque el motor IA (Ollama/azure/gemini) no está disponible en este entorno
(sin Ollama corriendo / sin API keys). La lógica de detección está unit-testeada y la
telemetría E2E (DB→endpoint) verificada con dato sintético. El reintento en vivo
queda cableado y fail-open.

## [0.4.1] — 2026-07-08

### Fixes — frontend (acceso + datos) + headroom persistente

- **Dashboard "no se pudieron cargar las métricas"**: el frontend guardaba un JWT stale
  (el `JWT_SECRET` cambió en sesión 6) y `isLoggedIn()` solo chequea que exista un token,
  no que sea válido → el dashboard renderizaba pero toda llamada daba 401. Cableado de
  `handleExpiredSession(res)` en `getAnalyticsSummary`, `getEngineStatus`, `getGuardians`
  y `getAuditLogs`: un 401 ahora limpia el token y recarga → manda al login (auto-heal).
- **`API_BASE` dinámico**: era `http://localhost:8081` hardcodeado → no funcionaba por IP LAN.
  Ahora `http://${window.location.hostname}:8081/api/v1` (funciona por localhost o IP).
- **Audit Logs "Total: 0 registros" con datos sí presentes**: `AuditPage.fetchLogs` hacía
  `fetch('http://localhost:8081/...')` **sin header Authorization** → 401 tragado en silencio
  por un `if (res.ok)` sin rama else → tabla vacía sin error. Reemplazado por
  `api.getAuditLogs({filtros})` (con auth + handleExpiredSession + `API_BASE`). Auditado:
  no hay más `localhost:8081` hardcodeados en el frontend.
- **`headroom-ai` no estaba en el contenedor runtime**: la imagen del backend se buildó
  2026-07-03, **antes** de que `headroom-ai` entrara en `requirements.txt` (07-06). El
  contenedor montea el código pero NO reinstala deps al arrancar → faltaba. Fix: rebuild
  de la imagen con `requirements.txt` actualizado. Conflicto de deps resuelto:
  `headroom-ai==0.30.0` arrastra `litellm` (necesita `httpx>=0.28`, `pydantic 2.13`).
  Pines actualizados a versiones probadas (16/16 tests + arranque limpio):
  `pydantic 2.7.4→2.13.4`, `httpx 0.27.0→0.28.1`, `tiktoken 0.7.0→0.13.0`.
  Trade-off: imagen del backend ahora incluye `litellm`+`openai`+`tokenizers`+`huggingface-hub`
  (transitivos de headroom-ai) → **imagen más pesada**. Headroom comprime LOCAL sin tokens.
- **Verificado**: stack completo up; login 200; calculadora headroom con JSON 200-ítems
  → **6617→2426 tokens (4589 ahorrados, ratio 69%, $0.000688, "conviene")**; determinista
  prosa 45→40 (5 ahorrados); `pytest tests/` → 16 passed; Audit Logs → 85 registros.

## [0.4.0] — 2026-07-07

### Hardening — Fase 0 cierre (F0-7 tests + F0-8 LiteLLM-first leverage)

- **F0-7 — Smoke tests (`backend/tests/`)**: suite pytest con `conftest.py` (sys.path +
  JWT secret de test, fail-closed probado explícitamente limpiando el env). **16 tests**
  (13 unitarias + 3 integración viva contra `http://localhost:8000/api/v1`):
  - `test_optimization.py` (4): compresor determinista preserva URLs/placeholders
    (`https://example.com/path?q=1#frag`, `<PERSON_1>`, `<EMAIL_ADDRESS>`), threshold gate,
    headroom ahorra en JSON estructurado, idempotencia en prosa limpia.
  - `test_compliance.py` (5): pharma `flagged_high_risk`, RRHH credit scoring `flagged`,
    social scoring `blocked_prohibited`, marketing copy `passed`, `ai_act_mode=False` → passed.
  - `test_session.py` (4): round-trip JWT con secret ≥32 chars, `RuntimeError` cuando falta/corto
    (fail-closed, nunca clave hard-codeada), token adulterado → `None`.
  - `test_chat_smoke.py` (3): `/users` anónimo → 401 (RBAC fail-closed), login → `access_token`,
    `/chat/completions` → 200 real **o** 502 "motor de IA no disponible" (contrato F0-3: cero
    fallback simulado, independiente del entorno).
  - `requirements.txt`: `pytest==8.2.2`, `pytest-asyncio==0.23.7`.
- **F0-8 — LiteLLM-first leverage (USE-LITE / DROP-DUP / KEEP-WITH-REASON)**:
  - **Cache**: `cache:true` + Redis TTL 3600 a nivel proxy → **USE-LITE** (ya en config, sin
    código por-request). La compresión corre tras el enmascaramiento PII, y la caché opera
    sobre el prompt ya enmascarado.
  - **Budget hard-ceiling**: `/key/generate` ya reenvía `max_budget`+`budget_duration` y los
    teams también → LiteLLM techa el gasto por llave (backstop duro). Nuestra doble capa
    secuencial personal→grupo (spec 011) queda como capa soft de UX → **USE-LITE backstop +
    KEEP-WITH-REASON** soft.
  - **Rate limit rpm/tpm**: `ai_engine_client.generate_key` ahora reenvía `rpm_limit`/`tpm_limit`
    a LiteLLM → el proxy impone rpm/tpm en el borde como backstop duro. Nuestro Redis rate-limiter
    se mantiene porque cubre JWT sessions (no solo llaves sk-), alimenta los headers
    `X-RateLimit-Remaining-*` y el audit → **USE-LITE backstop + KEEP-WITH-REASON**.
  - **Fallbacks ampliados**: cadenas por modelo-group (`gpt-4o→azure-gpt-4o-mini→ollama`,
    `claude-3-5-sonnet→gemini-2.5-flash→ollama`, `gemini-2.5-flash→gemini-2.5-flash-lite→ollama`,
    `gpt-4o-mini→ollama`, `ollama-gemma4-31b→ollama-qwen3-2b`) sumadas a las existentes.
    `num_retries:2`, `timeout:30`, `disable_cooldowns:true` confirmados.

### Verified (E2E)
- `pytest tests/` → **16 passed**. Backend up (openapi 200), anon `/users`→401, login→token,
  admin `/users`→200, `/chat/completions`→502 fail-closed sin simulación (motor sin ollama),
  litellm `health/readiness`→healthy con fallbacks cargados, compliance gate vía unit tests.

## [0.3.0] — 2026-07-07

### Implemented — US3 (ahorro medible en presupuesto) + US4 (toggle + config rica por grupo)

- **Migración 008** (idempotente, aplicada `007→008`): `audit_logs.cost_saved_usd NUMERIC(10,6)`,
  `groups.compression_mode/strategy/threshold_tokens/aggressiveness/cache_enabled`,
  `security_policies.compression_mode` (BOOLEAN, migra `headroom_mode`).
- **Modelos**: `AuditLog.cost_saved_usd`; `Group.compression_*`; `SecurityPolicy.compression_mode`
  (manteniendo `headroom_mode` deprecado); `processing_purpose` reframe a
  `marketing | expense_processing | pharmacovigilance | research | administrative`.
- **chat.py (capa 1.5)**: resolución de config en cascada
  `override request > grupo > política global > default`. Auto-detección de estrategia:
  `headroom` si el contenido empieza con `{`/`[`, si no `deterministic`. Cálculo de
  `cost_saved_usd = (tokens_saved / 1_000_000) × pricing_input[routed_model]`, persistido en
  `audit_log` y expuesto en `pipeline_metadata.layer_optimization`. Bug fixed: `Decimal` era
  local-shadowed → importado a nivel de módulo (UnboundLocalError en `cost_saved_usd`).
- **costs.py**: `cost_saved_usd` en `summary`/`by_user`/`by_group` (SUM agregada) + 4 endpoints
  nuevos US4: `GET/PUT /costs/config` (toggle global), `GET/PUT /costs/groups/{id}/compression`
  (mode/strategy/threshold/aggressiveness/cache por grupo).
- **analytics/dashboard**: KPI "Ahorro de Costes IA" (`cost_saved_usd` agregado).
- **Frontend**: `api.ts` (tipos `CostConfig`/`GroupCompressionConfig` + 4 métodos);
  `CostsPage.tsx` (4.º KPI "Ahorro real" + panel config global + tabla por grupo con
  selectores mode/strategy/threshold/aggressiveness); `DashboardPage.tsx` (fila Ahorro).

### Verified (E2E)

- `GET /costs/config` → `{enabled:false, default_strategy:"deterministic", default_threshold:256, default_aggressiveness:"medium"}`.
- Chat con `override_headroom_mode:true` + prompt JSON estructurado (250 items, 35.8 KB):
  `strategy_applied:"headroom"`, `tokens_saved:8483`, `cost_saved_usd:0.000636`.
- `audit_logs` persiste la fila: `model=gemini-2.5-flash-lite, tokens_saved_by_optimization=8483, cost_saved_usd=0.000636`.
- `GET /costs/summary?range=month` → `cost_saved_usd:0.000636`, `by_group[0].cost_saved_usd:0.000636`.
- Config por grupo: `PUT /costs/groups/{cardiologia}/compression {mode:"headroom",strategy:"headroom",threshold_tokens:128,aggressiveness:"high",cache_enabled:true}` → persiste y lee correcto; restaurado a `off` para dejar estado limpio.
- Frontend compila limpio (`vite build` 1868 módulos, 3.31s).
- Backend compila limpio (`ast.parse` OK en los 9 archivos tocados).

### Pendiente (siguientes slices)

- US5 (compresión LLM asistida con ROI + caché Redis por hash): módulo local headroom ya cableado
  para contenido estructurado; falta el path LLM barato + caché + guardia de degradación.
- US6 (telemetría fina: ratio de compresión por modelo + guardia de reversión por anomalía).

## [0.2.0] — 2026-07-06

### Decisión de motor (con evidencia) — headroom como módulo LOCAL, sin tokens

Investigación empírica del motor de compresión (US5):

- **`headroom`** (PyPI, paquete equivocado) — CLI assistant, sin `compress()`. Descartado.
- **LLMLingua** (Microsoft) — librería real de compresión, PERO en este contenedor solo-CPU
  traga torch+CUDA (~1GB) y el solo cargar el modelo se pasó de 5 min. Impracticable. Descartado.
- **`headroom-ai`** (headroomlabs-ai/headroom, el correcto) — base 17.7MB, core Rust, importa y
  corre en 0.1s sin torch. Su compresión de **prosa libre** necesita el modelo Kompress (torch).
  PERO su **SmartCrusher** comprime **contenido estructurado** (JSON, logs, tool outputs, RAG,
  arrays de items repetidos) de forma **100% local, sin llamar a ningún LLM, sin torch**.

**Decisión del usuario**: *"no voy a gastar tokens para economizar tokens"* → se descarta la
capa LLM-asistida (vía motor IA) por ser circular. El motor es **headroom como módulo local**
(SmartCrusher) + el compresor determinista propio para prosa. **Cero tokens gastados.**

### Implemented — US5 (parcial: módulo local headroom) + mejora US2 (desglose usuario/grupo + selector)

**Backend**
- `backend/requirements.txt`: añadido `headroom-ai==0.30.0` (base, sin extras ML/torch).
- `backend/src/services/optimization_service.py`:
  - Eliminada la capa LLM-vía-LiteLLM (ROI + caché + llamada al motor) — gastaba tokens.
  - Añadida estrategia **`headroom`**: `_headroom_compress()` usa `SmartCrusher.compact_document_json`
    sobre contenido JSON/estructurado, **local, sin tokens, sin torch**, fail-open al determinista.
  - `compress_context` y `analyze` ahora soportan `strategy="deterministic"|"headroom"`.
  - Lazy-init del módulo headroom (`_get_headroom_crusher`), desactivable con
    `COMPRESSION_HEADROOM_ENABLED=false`. Módulo opcional (fail-open si no está instalado).
- `backend/src/api/costs.py`:
  - `GET /costs/summary` ahora devuelve `by_user` (gasto por usuario, JOIN `users.username`) y
    `by_group` (gasto por grupo, JOIN `groups.name` vía `audit_logs.user_group_id`), top 10 c/u.
  - `POST /costs/calculator`: `strategy` ahora `deterministic|headroom` (sin `llm`).

**Frontend**
- `frontend/src/services/api.ts`: `CostEntityBreakdown`; `CostSummary` con `by_user`/`by_group`;
  `CompressionAnalysis` con `strategy_applied`; `calculateCompression` con `strategy`.
- `frontend/src/pages/CostsPage.tsx`:
  - Componente `BreakdownTable` reutilizable; 3 tablas (Top modelos / Gasto por usuario / Gasto por grupo).
  - Calculadora a ancho completo con **selector de estrategia** (Determinista / Headroom).
  - Info de resultado: qué estrategia se aplicó + badge "Sin gastar tokens · 100% local" para headroom.

### Verified
- `headroom SmartCrusher` funciona con `pydantic==2.7.4` (no fuerza upgrade; solo requiere `pydantic>=2.0.0`).
- Calculadora `strategy=headroom` sobre JSON con 250 items repetidos: **9871 → 6138 tokens (37.8% ahorro,
  3733 tokens saved), `applied=headroom`, veredicto `conviene`, $0.0093** — 100% local, sin tokens.
- Calculadora `strategy=deterministic` sobre prosa: sigue funcionando (cae con elegancia, sin ahorro).
- `/costs/summary` devuelve `by_user` (admin $0.0955/70 req, doctor_basa, …) y `by_group` (cardiologia
  $0.0314/18 req, test_clinica, …) con datos reales.
- Frontend compila limpio (`vite build ✓ 1868 módulos`).

### Descartado (no implementado, por decisión del usuario)
- Capa LLM asistida vía motor IA (US5 original "llm") — *"no voy a gastar tokens para economizar tokens"*.

## [0.1.0] — 2026-07-03

### Implemented — US1 (compresor determinista seguro) + US2 (sección Costos + calculadora)

Primer slice tryable. Base determinista + cara visible (calculadora de decisión). Sin migraciones de DB (se reutiliza `tokens_saved_by_optimization` de `audit_logs`).

**Backend**
- `backend/requirements.txt`: añadida `tiktoken==0.7.0`.
- `backend/src/services/token_counter.py` (NUEVO): `count_tokens(text, model)` con tiktoken (`cl100k_base`), fallback `chars//4` si tiktoken no está. Nunca lanza.
- `backend/src/services/optimization_service.py` (reescrito): compresor determinista seguro que **preserva URLs, headings markdown (`#`), comentarios (`//`) y placeholders `[PII_N]`/`[PHI_N]`** (tokens atómicos). Normaliza solo espacios en blanco. Umbral mínimo (`COMPRESSION_THRESHOLD_TOKENS`, default 256). Conteo real con tiktoken. Fail-open. Eliminado `import headroom` (nombre de terceros fuera del producto). Nuevo helper `analyze()` para la calculadora.
- `backend/src/api/costs.py` (NUEVO):
  - `GET /costs/summary?range=day|week|month` — gasto total, tokens ahorrados, ahorro estimado USD, top modelos por gasto.
  - `POST /costs/calculator` — calculadora de decisión: `{tokens_original, tokens_compressed, tokens_saved, cost_saved_usd, would_compress, veredicto, ratio, threshold}`. Veredicto `conviene` / `no_conviene` / `usd_no_disponible` según ratio (≥10%), umbral y rate de input del modelo (vía `/model/info`).
- `backend/src/api/__init__.py`: registrado `costs_router`.

**Frontend**
- `frontend/src/services/api.ts`: interfaces `ModelPricing`, `CostSummary`, `CompressionAnalysis`; métodos `getCostsSummary`, `calculateCompression`.
- `frontend/src/pages/CostsPage.tsx` (NUEVO): sección Costos con KPIs (gasto, requests, tokens ahorrados, ahorro estimado), selector de período, top modelos por gasto y **calculadora interactiva con veredicto** (textarea + selector modelo + agresividad + resultado tokens/ahorro USD + badge Conviene/No conviene/USD no disponible).
- `frontend/src/App.tsx`: ruta "Costos" + RBAC (admin, compliance_officer).

### Verified
- `GET /costs/summary` devuelve datos reales (75 requests, $0.098 gasto semana).
- `POST /costs/calculator`: prompt 25 tokens → `no_conviene` (sub-umbral); prompt 1460 tokens → 1160 (20.5% ahorro), `cost_saved_usd` con rate de `gemini-2.5-flash`, veredicto `conviene`.
- US1 preservación verificada: `https://example.com/path?x=1`, `www.test.io/a`, `# Heading markdown`, `// comentario codigo`, `[PII_1]`, `[PII_2]` todos intactos tras compresión; sub-umbral no comprime.
- Frontend compila (vite transform `CostsPage.tsx` 200, sin errores).

### Bug fixed
- El regex anterior borraba `#.*$` y `//.*$` y corrompía URLs, headings markdown y código. Arreglado: el compresor determinista ya no toca `#` ni `//`; solo normaliza espacios en blanco y blinda URLs/placeholders.

### Pendiente (siguientes slices)
- US3 (ahorro medible en presupuesto + KPI) — requiere Alembic para `cost_saved_usd` y descuento neto.
- US4 (toggle + config rica por Policy/Group) — requiere Alembic para `compression_*` y renombrado `headroom_mode`.
- US5 (compresión LLM asistida + ROI + caché Redis).
- US6 (telemetría + guardia de calidad).
- Decisiones abiertas (motor compresor, integración de coste) a confirmar antes de US3/US5.

## [0.0.0-draft] — 2026-07-03

### Renombrado
- La feature se llamaba "Headroom" (nombre de terceros, no white-label). Se renombra a **"Ahorro de Costes IA"**. La técnica subyacente sigue siendo "compresión de contexto/tokens".
- Flag `headroom_mode` → `compression_mode`; columnas `headroom_*` → `compression_*`.
- Rama: `feature/012-headroom-cost-reduction` → `feature/012-ahorro-costes-ia`.
- Carpeta del spec: `012-headroom-cost-reduction` → `012-ahorro-costes-ia`.

### Added (documentación inicial)
- `spec.md` — feature spec completo con 6 user stories (US1 compresor determinista seguro, US2 sección Costos + calculadora de decisión, US3 ahorro medible en presupuesto, US4 toggle + config rica, US5 LLM asistida con ROI + caché, US6 telemetría + guardia de calidad), edge cases y módulos afectados.
- `plan.md` — arquitectura de la capa 1.5, resolución de estrategia, cálculo de ROI, calculadora con veredicto de activación, descuento neto integrado con la doble capa del spec 011, archivos previstos y decisiones de diseño.
- `tasks.md` — breakdown de 45 tasks (T-001–T-045) en 9 phases organizadas por user story.
- `specs/ROADMAP.md` — backlog consolidado A–F del proyecto entero, con orden sugerido para probar lo nuevo.

### Calculadora como decisión de activación
- US2 recalca que la calculadora no solo informa tokens/ahorro, sino que emite un **veredicto** (`conviene` / `no_conviene` / `usd_no_disponible`) para que el usuario decida si activa la compresión antes de gastar. El usuario puede forzar la activación aunque el veredicto sea "no conviene".

### Contexto
La compresión existía como implementación parcial con bug: `optimization_service.py` usaba un regex que borraba `#.*$` y `//.*$` (corrompiendo URLs, headings markdown y código), la librería externa no se instalaba, el conteo de tokens era `chars//4`, y `tokens_saved` no se persistía ni reflejaba en el presupuesto. Este spec convierte la compresión en un mecanismo real de reducción de costes medible y seguro.

### Decisiones abiertas (a confirmar)
- **Motor compresor**: determinista seguro + LLM opcional (recomendado) / solo LLM / solo determinista.
- **Integración de coste**: presupuesto + dashboard (recomendado) / solo telemetría / solo fix del bug.
- **Caché Redis**: confirmada en la capa LLM por hash del prompt.

### Estado
**Draft** — sin código implementado. Pendiente de revisión y confirmación de decisiones antes de iniciar Phase 1.