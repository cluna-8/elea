# Tasks — Spec 012: Ahorro de Costes IA — Compresión de Tokens y Reducción de Costes

**Input**: `spec.md` + `plan.md` de `/specs/012-ahorro-costes-ia/`
**Status**: En implementacion — US1 + US2 hechos (v0.1.0); US3-US6 pendientes. Las decisiones marcadas *(a confirmar)* en `plan.md` pueden cambiar el alcance de las tasks restantes.

## Formato: `[ID] [P?] [Story] Descripción`

- **[P]**: puede correr en paralelo (archivos distintos, sin dependencias)
- **[Story]**: user story (US1–US6)

---

## Phase 1: Setup (infraestructura compartida)

- [x] T-001 [P] Añadir dependencia `tiktoken` a `backend/requirements.txt`
- [~] T-002 [P] Librería externa de compresión (capa LLM, US5) — diferida: la base determinista (US1) no la requiere; se decide al llegar a US5
- [x] T-003 [P] Crear rama `feature/012-ahorro-costes-ia`

**Checkpoint**: dependencias listas.

---

## Phase 2: Foundational (prerrequisitos bloqueantes)

- [ ] T-004 Migración Alembic: columnas `tokens_saved`, `cost_saved_usd` en `audit_logs`; columnas `compression_*` en `policy` y `groups`; renombrado `headroom_mode` → `compression_mode` (idempotente) — `backend/alembic/versions/`
- [ ] T-005 [P] Extender `backend/src/models/audit.py` con `tokens_saved`, `cost_saved_usd`
- [ ] T-006 [P] Extender `backend/src/models/policy.py` y `backend/src/models/group.py` con config rica de compresión (`compression_strategy`, `compression_threshold_tokens`, `compression_aggressiveness`, `compression_compressor_model`, `compression_cache_enabled`); renombrar flag `headroom_mode` → `compression_mode`
- [x] T-007 [P] Helper de conteo de tokens con `tiktoken` por modelo — `backend/src/services/token_counter.py`

**Checkpoint**: foundation lista; las user stories pueden avanzar.

---

## Phase 3: User Story 1 — Compresor determinista seguro (P1) 🎯 base

**Goal**: compresor que no corrompe URLs/código/markdown/placeholders y cuenta tokens reales.
**Independent Test**: prompt con URL + `#` heading + `[PII_1]` se comprime preservando todo; `tokens_saved` con tiktoken.

### Implementation for User Story 1

- [x] T-008 [US1] Reescribir `backend/src/services/optimization_service.py`: compresor determinista seguro (preservar URLs, `#` headings, `//` solo en código, placeholders `[PII_N]` como tokens atómicos)
- [x] T-009 [US1] Integrar `tiktoken` en `compress_context` para `tokens_saved` real (reemplazar `chars//4`)
- [x] T-010 [US1] Añadir umbral mínimo: no comprimir si `tokens(prompt) < threshold`
- [x] T-011 [US1] Fail-open: si el compresor (o librería externa) falla, devolver prompt original sin error
- [x] T-012 [US1] Tests manuales: URL intacta, heading intacto, placeholders preservados, sub-umbral no comprime, tokens_saved > 0 sobre umbral

**Checkpoint**: compresor seguro y medible.

---

## Phase 4: User Story 2 — Sección Costos + calculadora de decisión (P1) 🎯 visible

**Goal**: página única de costes con calculadora interactiva que recomienda activar o no.
**Independent Test**: abrir Costos, ver gasto desglosado, pegar prompt, ver tokens → tras compresión → ahorro USD + veredicto.

### Implementation for User Story 2

- [x] T-013 [US2] **NUEVO** `backend/src/api/costs.py`: `GET /costs/summary?range=day|week|month` (gasto por usuario/grupo/modelo)
- [x] T-014 [US2] `POST /costs/calculator` en `costs.py`: recibe `{prompt, model}`, devuelve `{tokens_original, tokens_compressed, tokens_saved, cost_saved_usd, would_compress, veredicto}` usando US1. Veredicto: `conviene` / `no_conviene` / `usd_no_disponible`
- [x] T-015 [P] [US2] `frontend/src/services/api.ts`: `getCostsSummary`, `calculateCompression`
- [x] T-016 [US2] **NUEVO** `frontend/src/pages/CostsPage.tsx`: KPIs de gasto + selector de período + tabla desglose
- [x] T-017 [US2] Calculadora interactiva en `CostsPage.tsx`: textarea prompt + selector modelo + resultado tokens/ahorro USD + **veredicto (Conviene/No conviene)** + aviso sub-umbral + aviso "USD no disponible"
- [x] T-018 [US2] `frontend/src/App.tsx`: ruta "Costos" + RBAC (admin/compliance_officer)
- [x] T-019 [US2] Estados vacíos y errores en CostsPage

**Checkpoint**: sección Costos + calculadora usables como decisión de activación.

---

## Phase 5: User Story 3 — Ahorro medible en presupuesto (P1)

**Goal**: el ahorro se persiste y reduce el descuento del presupuesto.
**Independent Test**: request comprimida → audit con `tokens_saved`/`cost_saved_usd`, presupuesto descuenta neto, KPI sube.

### Implementation for User Story 3

- [ ] T-020 [US3] `backend/src/api/chat.py` capa 1.5: persistir `tokens_saved` y `cost_saved_usd` en el `audit_log`
- [ ] T-021 [US3] `BudgetService.update_budget` (spec 011): descuento por **tokens netos** (post-compresión), respetando orden secuencial `personal → grupo`
- [ ] T-022 [US3] `backend/src/api/analytics.py`: endpoint KPI "Ahorro de Costes IA" (acumulado USD) + ratio de compresión
- [ ] T-023 [P] [US3] `frontend/src/pages/DashboardPage.tsx`: KPI "Ahorro de Costes IA"
- [ ] T-024 [US3] Tests manuales: descuento neto, KPI acumulado, doble capa respetada sobre neto

**Checkpoint**: lazo cerrado comprimir → ahorrar → ver.

---

## Phase 6: User Story 4 — Toggle + config rica por Policy/Group (P2)

**Goal**: activar/desactivar y configurar compresión por grupo/usuario desde Costos.
**Independent Test**: activar `deterministic`+umbral 512 para un grupo; sus requests se comprimen, las de otro grupo no.

### Implementation for User Story 4

- [ ] T-025 [US4] `backend/src/api/costs.py`: `GET/PUT /costs/compression-config` (resuelve y guarda config por grupo/usuario/global)
- [ ] T-026 [US4] `chat.py`: resolver config por jerarquía usuario > grupo > global antes de comprimir
- [ ] T-027 [P] [US4] `frontend/src/services/api.ts`: `getCompressionConfig`, `updateCompressionConfig`
- [ ] T-028 [US4] `CostsPage.tsx`: panel toggle + config (estrategia off/deterministic/llm, umbral, agresividad, modelo compresor, caché on/off)
- [ ] T-029 [US4] Tests manuales: config por grupo aplica, override de usuario gana, `off` no comprime, cambio aplica sin restart

**Checkpoint**: control fino por contexto.

---

## Phase 7: User Story 5 — Compresión LLM asistida + ROI + caché (P2)

**Goal**: modelo barato comprime prompts grandes con ROI positivo y caché Redis.
**Independent Test**: prompt 8000 tokens → compresión LLM con ahorro alto; ROI negativo → cae a determinista; prompt repetido → caché.

### Implementation for User Story 5

- [ ] T-030 [US5] `optimization_service.py`: estrategia `llm` — llamar al modelo compresor vía LiteLLM (configurable, UE-compliant si aplica), preservar placeholders
- [ ] T-031 [US5] Cálculo de ROI: `ahorro_esperado_usd - coste_compresion_usd`; si <= 0 no usar LLM (cae a determinista)
- [ ] T-032 [US5] Caché Redis por `hash(prompt)` con TTL configurable (solo capa LLM); reusa conexión de spec 007
- [ ] T-033 [US5] Fail-open: si el modelo compresor no responde, caer a determinista
- [ ] T-034 [US5] Tests manuales: ROI positivo comprime, ROI negativo cae a determinista, caché hit, fail-open, placeholders preservados

**Checkpoint**: promesa 60–95% activa (opcional, ROI-gated).

---

## Phase 8: User Story 6 — Telemetría + guardia de calidad (P3)

**Goal**: métricas por modelo y guardia que revierte si la respuesta degrada.
**Independent Test**: dashboard muestra ratio/ahorro por modelo; respuesta anómala → reintento con prompt original.

### Implementation for User Story 6

- [ ] T-035 [US6] `analytics.py`: telemetría de compresión (ratio promedio, ahorro USD, reversiones) por modelo
- [ ] T-036 [US6] Guardia de calidad en `chat.py`: heurística de longitud/anomalía en la respuesta; revertir al prompt original y reintentar si se detecta degradación
- [ ] T-037 [US6] Registrar eventos de reversión; sugerir bajar agresividad/desactivar LLM si reversiones > umbral
- [ ] T-038 [P] [US6] `CostsPage.tsx`/`DashboardPage.tsx`: panel de telemetría de compresión
- [ ] T-039 [US6] Tests manuales: reversión ante respuesta vacía/corta, no-reintento en respuesta normal, contabilidad de ahorro correcta

**Checkpoint**: confianza y observabilidad.

---

## Phase 9: Polish & cross-cutting

- [ ] T-040 [P] Actualizar `USE.md`: sección Costos + calculadora (decisión de activación) + compresión
- [ ] T-041 [P] Actualizar `README.md` si procede (renombrar "Headroom" → "Ahorro de Costes IA")
- [ ] T-042 Actualizar `changelog.md` del spec 012 por versión
- [ ] T-043 [P] Validar white-label: el modelo compresor interno no aparece en UI ni exports; ningún nombre de terceros ("headroom") en la UI
- [ ] T-044 [P] Validar GDPR: prompt comprimido sin PII en claro; modelo compresor cloud UE-compliant cuando aplique
- [ ] T-045 Run quickstart/validation con contenedores `eu-*`

---

## Dependencies & Execution Order

- **Phase 1 (Setup)**: sin dependencias.
- **Phase 2 (Foundational)**: depende de Setup; **bloquea** todas las user stories.
- **US1 (Phase 3)**: base — la calculadora (US2), el descuento (US3) y la capa LLM (US5) dependen de su compresor.
- **US2 (Phase 4)**: la calculadora depende de US1; el shell de Costos puede adelantarse (T-016/T-018) en paralelo.
- **US3 (Phase 5)**: depende de US1 (tokens_saved) y reusa la doble capa de spec 011.
- **US4 (Phase 6)**: depende de US1; el toggle se sitúa en CostsPage (US2).
- **US5 (Phase 7)**: depende de US1 (fallback), US4 (config/estrategia) y spec 010 (rates para ROI).
- **US6 (Phase 8)**: depende de US3 (telemetría) y US5 (reversiones de LLM).
- **Phase 9 (Polish)**: tras las user stories deseadas.

### Orden recomendado para probar cuanto antes

1. T-016/T-018 (Costos shell visible) → 2. US1 (T-008…T-012) → 3. US2 calculadora con veredicto (T-013/14/15/17) → 4. US3 → 5. US4 → 6. US5 → 7. US6 → 8. Phase 9.

## Notes

- Tasks en **Draft**: sin implementar. Confirmar las decisiones *(a confirmar)* de `plan.md` antes de empezar.
- `[P]` = paralelo, archivos distintos.
- Cada user story es independientemente testeable.
- Commit por task o grupo lógico; parar en cada checkpoint para validar.
- Renombrado: feature "Ahorro de Costes IA" (antes "Headroom"); flag `headroom_mode` → `compression_mode`; columnas `headroom_*` → `compression_*`.