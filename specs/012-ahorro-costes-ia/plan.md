# Plan — Spec 012: Ahorro de Costes IA — Compresión de Tokens y Reducción de Costes

> **Estado**: Draft / propuesta. Las decisiones marcadas *(a confirmar)* están abiertas hasta revisión con el usuario. Este plan describe la arquitectura objetivo, no código aún implementado.
>
> **Renombrado**: la feature se llamaba "Headroom" (nombre de terceros). Ahora se llama **"Ahorro de Costes IA"**; la técnica es "compresión de contexto/tokens". El flag `headroom_mode` pasa a `compression_mode`; las columnas `headroom_*` pasan a `compression_*`.

## Summary

Convertir la compresión de contexto en un mecanismo real de reducción de costes: compresor determinista seguro con conteo `tiktoken` (base), una sección dedicada de Costos con **calculadora interactiva que recomienda activar o no** (cara visible), ahorro medido y reflejado en el presupuesto (lazo cerrado), config rica por Policy/Group, y una capa LLM opcional con ROI y caché Redis para prompts grandes (promesa 60–95%).

## Technical Context

- **Language/Version**: Python 3.11 (backend), TypeScript + React/Vite (frontend)
- **Primary Dependencies**: FastAPI, SQLAlchemy, Alembic, Redis (ya en 006/007), LiteLLM (motor IA), **tiktoken (nueva)**, librería externa de compresión (opcional, capa LLM)
- **Storage**: PostgreSQL (audit_logs, policy, group) + Redis (caché capa LLM)
- **Testing**: manual e2e vía Docker Compose (contenedores `eu-*`); tests Pytest pendientes de decidir (relacionado con roadmap D4)
- **Target Platform**: Linux server (Docker)
- **Project Type**: web-service (backend + frontend)
- **Performance Goals**: compresión determinista < 10ms para prompts de hasta ~8k tokens; capa LLM latencia < 2s y solo cuando ROI > 0
- **Constraints**: fail-open (nunca romper el chat); preservar placeholders PII; no exponer naming interno (white-label); respetar doble capa presupuestaria (spec 011)
- **Scale/Scope**: 1 servicio backend, 1 página frontend nueva, 1 migración Alembic, 6 user stories

## Constitution Check

- **I. Privacy & PHI/PII Masking-First**: ✅ la compresión se aplica **después** del enmascaramiento; los placeholders `[PII_N]` se tratan como tokens atómicos intocables.
- **II. Strict Compliance (GDPR & AI Act)**: ✅ el prompt comprimido enviado al LLM no contiene PII en claro; si el compresor LLM es cloud, el routing GDPR (spec 005) sigue aplicando (modelo UE-compliant cuando el proyecto lo exija).
- **III. Budget & Resource Enforcement**: ✅ el descuento se hace por **tokens netos** (post-compresión), respetando la doble capa secuencial del spec 011.
- **IV. Containerized & White-label**: ✅ sin cambios de infraestructura; el modelo compresor interno no se expone en UI ni exports. El feature se llama "Ahorro de Costes IA" (sin nombres de terceros).
- **V. Explanatory & Interactive Playground**: la calculadora y el KPI de ahorro extienden la transparencia del pipeline (mostrar el efecto de la capa 1.5 y la decisión de activación).

## Project Structure

### Documentation (this feature)

```text
specs/012-ahorro-costes-ia/
├── spec.md          # este feature spec
├── plan.md          # este archivo
├── tasks.md         # breakdown por user story
└── changelog.md     # entradas por versión (draft inicial)
```

### Source Code (previsto)

```text
backend/
├── src/
│   ├── services/
│   │   └── optimization_service.py   # reescritura: determinista seguro + tiktoken + umbral + LLM/ROI + caché
│   ├── api/
│   │   ├── chat.py                    # capa 1.5: aplicar estrategia, persistir ahorro, descuento neto
│   │   ├── analytics.py               # KPIs de ahorro
│   │   └── costs.py                   # NUEVO: visualización de costes + calculadora (con veredicto)
│   └── models/
│       ├── policy.py                  # config rica de compresión (compression_*)
│       ├── group.py                   # config rica de compresión por grupo
│       └── audit.py                   # columnas tokens_saved, cost_saved_usd
└── alembic/versions/                  # migración de columnas + config + renombrado flag

frontend/
└── src/
    ├── pages/
    │   ├── CostsPage.tsx              # NUEVO: sección Costos + calculadora (veredicto) + toggle/config
    │   └── DashboardPage.tsx          # KPI "Ahorro de Costes IA"
    ├── services/api.ts                # métodos de costes/calculadora/config compresión
    └── App.tsx                        # ruta "Costos" + RBAC
```

**Structure Decision**: web app existente (backend + frontend). Se añade `api/costs.py` y `pages/CostsPage.tsx`; se reescribe `optimization_service.py`; se amplían `policy.py`, `group.py`, `audit.py` con una migración Alembic. Se renombra el flag `headroom_mode` → `compression_mode` y las columnas `headroom_*` → `compression_*`.

## Arquitectura — capa 1.5 (compresión)

Orden del pipeline (sin cambios respecto a hoy, se robustece el contenido de la capa 1.5):

```
1. Auth (RBAC / llave virtual)            [spec 009]
2. Rate limiting (Redis, RPM pre-call)    [spec 007]
3. Guardianes + enmascaramiento PII       [spec 003/010]  → placeholders [PII_N]
4. Layer 1.5 — Ahorro de Costes IA (este spec)  ← compresión tras enmascaramiento
5. GDPR routing + compliance              [spec 005]
6. Budget check (pre-call)                [spec 011]
7. LiteLLM call (con fallbacks)           [spec 002/010]
8. Budget deduct (neto, post-respuesta)   [spec 011]  ← descuento por tokens netos
9. Restauración de placeholders + audit   [spec 001/005]
```

### Resolución de estrategia de compresión

```
resolve_compression_config(api_key, user, group):
  1. Override de usuario (si existe) > override de grupo > global (Policy)
  2. Devuelve: { strategy, threshold_tokens, aggressiveness, compressor_model, cache_enabled }

compresión:
  if strategy == off or tokens(prompt) < threshold:
      return prompt_original, tokens_saved=0
  if strategy == deterministic or (strategy == llm and ROI <= 0):
      return determinista_safe(prompt), tokens_saved_determinista
  if strategy == llm and ROI > 0:
      cached = redis.get(hash(prompt))  if cached and cache_enabled: return cached
      compressed = llm_compress(prompt, compressor_model)  # fail-open a determinista
      if cache_enabled: redis.setex(hash, ttl, compressed)
      return compressed, tokens_saved_llm
```

### Cálculo de ROI (capa LLM)

```
ahorro_esperado_usd = tokens_ahorrados_estimados × rate_modelo_caro
coste_compresion_usd = tokens(prompt) × rate_modelo_compresor + tokens_compressed × rate_modelo_compresor
ROI = ahorro_esperado_usd - coste_compresion_usd
→ si ROI <= 0: no usar LLM (caer a determinista u off)
```

### Calculadora de decisión (US2)

```
POST /costs/calculator  { prompt, model }
  → tokens_original = tiktoken(prompt)
  → tokens_compressed, tokens_saved = comprimir(prompt)  # estimación con la estrategia determinista
  → cost_saved_usd = tokens_saved × rate(modelo)         # si rate conocido
  → veredicto:
       "conviene"     si tokens_saved/tokens_original > ratio_min  Y  tokens_original >= threshold
       "no_conviene"  si ahorro marginal o por debajo del umbral
       "usd_no_disponible" si no hay rate del modelo
  → devuelve { tokens_original, tokens_compressed, tokens_saved, cost_saved_usd, would_compress, veredicto }
```

### Descuento neto en presupuesto (integración con spec 011)

```
tokens_originales = tiktoken(prompt_enmascarado)
tokens_netos      = tiktoken(prompt_comprimido)  # o tokens reales de la respuesta del LLM
tokens_saved      = max(0, tokens_originales - tokens_netos)
cost_saved_usd    = tokens_saved × rate_modelo_caro

descuento_budget(tokens_netos, cost_usd_netos):
  → respeta orden secuencial [personal, grupo] del spec 011 (break tras el primero con crédito)

audit_log: tokens_saved, cost_saved_usd  (metadata, sin contenido)
```

## Archivos previstos (resumen)

| Archivo | Cambio |
|---------|--------|
| `backend/src/services/optimization_service.py` | Reescritura: compresor determinista seguro + tiktoken + umbral + LLM con ROI + caché Redis; preservar placeholders `[PII_N]` |
| `backend/src/api/chat.py` | Capa 1.5: resolver config, aplicar estrategia, persistir `tokens_saved`/`cost_saved_usd`, descuento neto |
| `backend/src/api/costs.py` | **NUEVO**: `GET /costs/summary` (gasto por usuario/grupo/modelo/período), `POST /costs/calculator` (tokens → tras compresión → ahorro USD + **veredicto**), `GET/PUT /costs/compression-config` |
| `backend/src/api/analytics.py` | KPI "Ahorro de Costes IA", ratio por modelo |
| `backend/src/models/policy.py`, `models/group.py` | Columnas: `compression_strategy`, `compression_threshold_tokens`, `compression_aggressiveness`, `compression_compressor_model`, `compression_cache_enabled`; renombrar `headroom_mode` → `compression_mode` |
| `backend/src/models/audit.py` | Columnas `tokens_saved`, `cost_saved_usd` |
| `backend/alembic/versions/` | Migración con nuevas columnas + renombrado de flag (idempotente) |
| `frontend/src/pages/CostsPage.tsx` | **NUEVO**: sección Costos (KPIs gasto + selector período + calculadora con veredicto + toggle/config compresión) |
| `frontend/src/pages/DashboardPage.tsx` | KPI "Ahorro de Costes IA" |
| `frontend/src/services/api.ts` | Métodos: `getCostsSummary`, `calculateCompression`, `getCompressionConfig`, `updateCompressionConfig` |
| `frontend/src/App.tsx` | Ruta "Costos" + RBAC (admin/compliance_officer) |

## Decisiones clave

1. **Determinista primero (P1), LLM opcional (P2)**: el determinista entrega valor sin dependencias ni coste; el LLM se añade después solo para prompts grandes con ROI positivo. *(A confirmar)*
2. **tiktoken para conteo real**: reemplaza el `chars//4` actual. Rate por modelo desde el catálogo de precios (spec 010 `GET /chat/models/pricing`).
3. **Descuento neto en presupuesto**: el budget se cobra por tokens netos, respetando la doble capa secuencial del spec 011.
4. **Caché solo en capa LLM**, por `hash(prompt)`, TTL configurable. El determinista es barato y no cachea.
5. **Placeholders `[PII_N]` son atómicos**: el compresor no los toca, fusiona ni separa — garantiza la restauración posterior.
6. **Fail-open**: cualquier fallo del compresor (determinista o LLM) cae al prompt original; el chat nunca se rompe.
7. **Calculadora = decisión de activación**: la calculadora devuelve un **veredicto** (conviene / no conviene / usd no disponible) basado en ratio de ahorro, umbral y rate del modelo. El usuario decide a partir de ahí; puede forzar la activación aunque el veredicto sea "no conviene".
8. **Guardia de calidad (US6)**: heurística de longitud/anomalía en la respuesta; reversión al prompt original si se detecta degradación.
9. **White-label**: el modelo compresor interno no se expone en UI ni exports. El feature se llama "Ahorro de Costes IA".

## Complejidad / violaciones de constitution

Ninguna. El spec extiende la capa 1.5 existente y reusa Redis (006/007), el catálogo de precios (010), la doble capa presupuestaria (011) y el routing GDPR (005) sin introducir nuevos servicios ni nuevos principios.

## Orden de implementación sugerido (para "probarlo" cuanto antes)

1. **US2 parcial (shell)**: `CostsPage` shell + visualización de gasto (reusa datos existentes) → visible sin backend nuevo.
2. **US1**: compresor determinista seguro + tiktoken + umbral (arregla bug del regex).
3. **US2 completa**: calculadora interactiva en Costos con **veredicto** (usa US1).
4. **US3**: ahorro medido en audit + descuento neto + KPI.
5. **US4**: toggle de compresión + config rica por Policy/Group.
6. **US5**: compresión LLM asistida + ROI + caché Redis (el caro/opcional).
7. **US6**: telemetría + guardia de calidad.
8. **F1 (roadmap)**: verificar/mover presupuestos de users a Costos.

## Dependencias con otros specs

- **Spec 011** (doble capa presupuestaria): el descuento neto debe respetar el modelo secuencial `personal → grupo`.
- **Spec 010** (`GET /chat/models/pricing`): rates por modelo para calcular ahorro USD, ROI y el veredicto de la calculadora.
- **Spec 005** (GDPR routing): el modelo compresor LLM cloud debe ser UE-compliant cuando el proyecto lo exija.
- **Spec 003/010** (guardianes/Presidio): la compresión se aplica **después** del enmascaramiento, sobre placeholders seguros.
- **Spec 007** (rate limiting Redis): reusa la conexión Redis para la caché de capa LLM.