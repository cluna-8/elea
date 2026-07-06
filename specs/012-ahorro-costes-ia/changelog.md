# Changelog — Spec 012: Ahorro de Costes IA — Compresión de Tokens y Reducción de Costes

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