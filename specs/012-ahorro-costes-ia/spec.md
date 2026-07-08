# Spec 012 — Ahorro de Costes IA: Compresión de Tokens y Reducción de Costes

**Status**: ✅ CERRADO — US1–US6 implementados (v0.5.0, en rama feature). Fase 0 hardening CERRADA. **20/20 tests pasan**. US5: estrategia `llm` descartada por restricción "no gastar tokens para ahorrar tokens" (circular); implementada caché Redis por hash (sin tokens) + guard fail-open. US6: telemetría ratio de compresión por modelo + guardia de reversión ante respuesta anómala.
**Branch**: `feature/012-ahorro-costes-ia` (merged US3/US4 a master 2026-07-07)
**Created**: 2026-07-03

## Contexto

> **Dominio del producto**: el gateway sirve a **pharma + gastos + marketing** (no hospitales /
> atención al paciente). Que el sector sea "salud" no implica que los prompts traten sobre
> pacientes: los casos de uso típicos son copy de campañas, análisis de gastos, reportes de
> performance de ads, catálogos de producto y RAG regulatorio. La compresión brilla en
> **contenido estructurado** (líneas de gasto, items de campaña, chunks de RAG, tool outputs) —
> que es justo lo que estos flujos ensamblan. El motor PII/PHI (GDPR) se mantiene: los datos
> sensibles son sobre todo **PII comercial** (rep, empleados, HCP) y, cuando aplica, **PHI**
> (farmacovigilancia / ensayos clínicos).

La compresión de contexto existe hoy como una **implementación parcial y con bugs**:

- `backend/src/services/optimization_service.py`: fallback regex que **borra `#.*$` y `//.*$`** → corrompe URLs (`https://…`), headings markdown y código embebido. Una librería externa de compresión se importa opcionalmente pero **nunca se instala**, así que solo corre el fallback naïve.
- `backend/src/api/chat.py` (capa 1.5): aplica la compresión tras el enmascaramiento PII y antes del routing. Correcto en orden, pero `tokens_saved` **no se persiste ni refleja en el presupuesto**.
- `backend/src/models/policy.py`: flag booleano `headroom_mode` (a renombrar `compression_mode`) — solo on/off global, sin umbral, sin estrategia, sin ROI.
- Estimación de tokens: `chars // 4` — inexacta, sin `tiktoken`.
- La promesa de producto ("ahorro entre 60% y 95% de tokens") **no se cumple** en el estado actual.

Paralelamente, la gestión de costes está dispersa: el gasto se ve en el dashboard (spec 004) y los presupuestos en `UsersPage` (spec 011), pero no hay un espacio único donde el usuario **visualice costes, calcule el ahorro y decida si activa la compresión**.

> **Nota de renombrado**: la feature se llamaba "Headroom" (nombre de terceros, no white-label). Se renombra a **"Ahorro de Costes IA"**. La técnica subyacente sigue siendo "compresión de contexto/tokens"; el nombre del producto/feature es "Ahorro de Costes IA".

## Objetivos

1. **Compresión segura y determinista**: reemplazar el regex peligroso por un compresor que preserve placeholders PII, URLs, código y markdown, con conteo de tokens real (`tiktoken`) y umbral mínimo. Sin dependencias externas.
2. **Sección dedicada de Costos con calculadora de decisión**: nueva página donde visualizar el gasto (por usuario / grupo / modelo / período) y una **calculadora interactiva** que muestre tokens actuales → tokens tras compresión → ahorro en tokens y USD, con una **recomendación explícita de activar o no**, para que el usuario decida antes de gastar.
3. **Ahorro medible en presupuesto**: persistir `tokens_saved` y `cost_saved_usd` por request en `audit_logs`; descontar del presupuesto solo los tokens **netos enviados** (post-compresión); mostrar ahorro acumulado como KPI.
4. **Control y configuración rica**: mover el flag a una config por `Policy`/`Group` con estrategia (off / deterministic / llm), umbral de tokens, agresividad, modelo compresor y caché on/off. Activar/desactivar desde la sección Costos.
5. **Compresión LLM asistida con ROI**: para prompts grandes, usar un modelo barato vía LiteLLM (p.ej. `gpt-4o-mini` u Ollama local) que comprima preservando semántica. Solo se activa si `ahorro_esperado × rate_modelo_caro > coste_modelo_barato`. Caché en Redis por hash del prompt.
6. **Telemetría y guardia de calidad**: KPI de "Ahorro de Costes IA", ratio de compresión por modelo, y guardia que revierte al prompt original si la respuesta degrada (heurística de longitud/anomalía).

## User Scenarios & Testing

### User Story 1 — Compresor determinista seguro (Priority: P1)

Como ingeniero del gateway, quiero un compresor de contexto determinista que no corrompa el prompt (URLs, código, markdown, placeholders PII) y que cuente tokens reales, para que la compresión sea segura y medible sin dependencias externas.

**Why this priority**: es la base de todo el spec. Arregla un bug real (regex que rompe URLs/código) y habilita el conteo real que usan la calculadora, el presupuesto y la telemetría. Entrega valor sin coste extra ni infraestructura.

**Independent Test**: dado un prompt con una URL (`https://example.com/path`), un heading (`# Título`) y un placeholder PII (`[PII_1]`), el compresor devuelve el texto con todos esos elementos intactos y un `tokens_saved` calculado con `tiktoken` (no `chars//4`).

**Acceptance Scenarios**:

1. **Given** un prompt con `https://example.com/foo` y `# Sección`, **When** se comprime con estrategia determinista, **Then** la URL y el `#` se preservan íntegros.
2. **Given** un prompt con placeholders `[PII_1]`, `[PII_2]`, **When** se comprime, **Then** los placeholders no se pierden ni se fusionan.
3. **Given** un prompt de 50 tokens, **When** el umbral es 256 tokens, **Then** no se comprime (devuelve el original, `tokens_saved=0`) — evita overhead en prompts cortos.
4. **Given** un prompt de 2000 tokens, **When** se comprime, **Then** `tokens_saved` se calcula con `tiktoken` y es > 0.
5. **Given** sin librería externa instalada, **When** se ejecuta, **Then** el compresor determinista funciona sin error (fallback nativo, nunca rompe el flujo).

---

### User Story 2 — Sección Costos + calculadora de decisión (Priority: P1) 🎯 visible

Como administrador/DPO, quiero una página única de Costos donde ver el gasto desglosado y una **calculadora que me muestre cuántos tokens consumiría un prompt, cuántos quedarían tras compresión y cuánto ahorraría en USD**, con una **recomendación de activar o no**, para decidir si enciendo la compresión antes de gastar.

**Why this priority**: es la cara visible del spec — lo que el usuario "prueba". Reusa datos existentes (analytics + budgets) y el compresor de US1, entregando una demo concreta sin riesgo. La calculadora es el centro de la decisión de activación.

**Independent Test**: abro la sección Costos, veo el gasto por usuario/grupo/modelo/período, pego un prompt en la calculadora, selecciono un modelo, y veo tokens actuales, tokens tras compresión, ahorro en USD y un veredicto "Conviene activar / No conviene (poco ahorro o bajo umbral)".

**Acceptance Scenarios**:

1. **Given** la sección Costos abierta, **When** la cargo, **Then** veo KPIs de gasto (total, por usuario, por grupo, por modelo) y un selector de período (día/semana/mes).
2. **Given** la calculadora visible, **When** pego un prompt de 1500 tokens y selecciono `gpt-4o`, **Then** veo "1500 tokens → ~X tokens tras compresión", "Ahorro estimado: $Y" y un veredicto de activación.
3. **Given** la calculadora, **When** cambio de modelo a uno más caro, **Then** el ahorro en USD y el veredicto se recalculan según el rate del modelo.
4. **Given** un prompt por debajo del umbral o con ahorro marginal, **When** lo evalúo, **Then** la calculadora indica "No conviene activar" (menos ahorro que el overhead / por debajo del umbral).
5. **Given** un prompt grande con ahorro significativo, **When** lo evalúo, **Then** la calculadora indica "Conviene activar" y muestra el % de ahorro.
6. **Given** un modelo sin rate conocido, **When** lo selecciono, **Then** la calculadora muestra el ahorro en tokens y un aviso de "USD no disponible" en vez de fallar.
7. **Given** la sección Costos, **When** no hay datos de gasto, **Then** muestro estado vacío claro sin errores.

---

### User Story 3 — Ahorro medible en presupuesto (Priority: P1)

Como administrador, quiero que el ahorro real de tokens y USD de cada request comprimida se registre y reduzca lo que se descuenta del presupuesto, para que la compresión se traduzca en coste real y visible.

**Why this priority**: sin esto la compresión es cosmética. Es lo que cierra el lazo "comprimir → ahorrar → verlo en el presupuesto y el dashboard".

**Independent Test**: hago una request con compresión activa; el `audit_log` registra `tokens_saved` y `cost_saved_usd`; el presupuesto se descuenta por los tokens netos enviados (no los originales); el KPI "Ahorro de Costes IA" sube en el dashboard.

**Acceptance Scenarios**:

1. **Given** una request de 2000 tokens comprimida a 1200, **When** se procesa, **Then** `audit_log` guarda `tokens_saved=800` y `cost_saved_usd` según el rate del modelo.
2. **Given** la misma request, **When** se descuenta el presupuesto, **Then** se descuentan los **1200 tokens netos**, no los 2000 originales.
3. **Given** varias requests comprimidas, **When** abro el dashboard/Costos, **Then** el KPI "Ahorro de Costes IA" muestra el ahorro acumulado en USD.
4. **Given** compresión inactiva, **When** se procesa una request, **Then** `tokens_saved=0` y el descuento es por tokens completos.
5. **Given** un presupuesto de grupo y personal (doble capa), **When** se descuenta el neto, **Then** la lógica secuencial del spec 011 se respeta (personal primero, grupo fallback) sobre el neto.

---

### User Story 4 — Control de compresión desde Costos + config rica (Priority: P2)

Como administrador, quiero activar/desactivar la compresión y configurar su comportamiento por grupo/usuario (estrategia, umbral, agresividad, modelo compresor, caché) desde la sección Costos, en vez de un flag global.

**Why this priority**: da control fino y por contexto (un equipo de marketing con campañas largas quiere headroom; un equipo de gastos con prompts cortos quiere off). Depende de US1 (compresor) y se beneficia de US2 (Costos).

**Independent Test**: desde Costos activo compresión headroom para el grupo "Marketing Q3" con umbral 512; las requests de ese grupo se comprimen, las de otro grupo no.

**Acceptance Scenarios**:

1. **Given** la sección Costos, **When** activo compresión para un grupo con estrategia `deterministic` y umbral 512, **Then** esa config se persiste en `Policy`/`Group` y aplica a las requests de ese grupo.
2. **Given** config por grupo, **When** un usuario de ese grupo hace una request, **Then** se aplica la estrategia/umbral del grupo (o su override de usuario si existe).
3. **Given** estrategia `off`, **When** se procesa una request, **Then** no se comprime y `tokens_saved=0`.
4. **Given** agresividad alta, **When** se comprime, **Then** se aplican transformaciones más agresivas (mayor ahorro, más riesgo de pérdida semántica) — validado por la guardia de US6.
5. **Given** un cambio de config, **When** se guarda, **Then** aplica a la siguiente request sin reiniciar el backend.

---

### User Story 5 — Compresión LLM asistida con ROI y caché (Priority: P2)

Como administrador de un grupo con prompts muy largos, quiero que un modelo barato comprima el prompt preservando semántica (60–95% ahorro), pero solo cuando el ahorro supere el coste de comprimir, y cachear resultados para no recomprimir prompts repetidos.

**Why this priority**: es donde se cumple la promesa de producto (60–95%). Es opcional y costoso, por eso va después de la base determinista. Caché confirmada en esta capa.

**Independent Test**: con estrategia `llm` y un prompt de 8000 tokens, la compresión usa un modelo barato y devuelve un prompt mucho menor; el ROI se calcula y si es negativo (prompt corto) no se comprime con LLM (cae a determinista o off); un prompt idéntico repetido sale de caché.

**Acceptance Scenarios**:

1. **Given** estrategia `llm`, umbral 2000 tokens y un prompt de 8000, **When** se comprime, **Then** se llama al modelo compresor barato y el resultado preserva la semántica clave del prompt.
2. **Given** el rate del modelo caro y del compresor, **When** se evalúa el ROI, **Then** si `ahorro_esperado_usd <= coste_compresion_usd` no se usa LLM (cae a determinista).
3. **Given** un prompt ya comprimido con LLM, **When** llega un prompt idéntico (mismo hash), **Then** se devuelve el resultado desde Redis sin llamar al modelo.
4. **Given** el modelo compresor no responde, **When** se comprime, **Then** cae al compresor determinista sin romper el flujo (fail-open).
5. **Given** compresión LLM activa, **When** el prompt contiene placeholders PII, **Then** los placeholders se preservan en el resultado (la compresión se hace tras el enmascaramiento).

---

### User Story 6 — Telemetría y guardia de calidad (Priority: P3)

Como administrador/DPO, quiero ver métricas de compresión por modelo y una guardia que revierta al prompt original si la respuesta degrada, para confiar en que la compresión no perjudica la calidad de las respuestas.

**Why this priority**: confianza y observabilidad. Cierra el spec con seguridad de calidad.

**Independent Test**: el dashboard muestra ratio de compresión y ahorro por modelo; una request cuya respuesta sea anómalamente corta/vacía tras compresión se reintenta con el prompt original y se marca el evento.

**Acceptance Scenarios**:

1. **Given** historial de requests comprimidas, **When** abro telemetría, **Then** veo ratio de compresión promedio y ahorro USD por modelo.
2. **Given** una request comprimida cuya respuesta es vacía o drásticamente más corta de lo esperado, **When** se detecta la anomalía, **Then** se reenvía con el prompt original y se registra el evento de reversión.
3. **Given** reversiones repetidas para una estrategia, **When** superan un umbral, **Then** se sugiere bajar la agresividad o desactivar LLM para ese grupo.
4. **Given** la guardia activa, **When** una compresión es segura (respuesta normal), **Then** no hay reintento y el ahorro se contabiliza.

---

### Edge Cases

- **Placeholders PII colisionan tras compresión**: si dos placeholders se fusionan por whitespace-stripping adyacente, la restauración fallaría. El compresor determinista debe tratar los placeholders `[PII_N]` como tokens atómicos intocables.
- **Prompt por debajo del umbral**: no se comprime (overhead > ahorro). `tokens_saved=0`.
- **Fallo del modelo compresor LLM**: cae a determinista; nunca rompe el flujo de chat.
- **ROI negativo en prompts cortos con LLM**: no se usa LLM; cae a determinista u off según config.
- **Prompts duplicados**: caché Redis por hash evita recomprimir (solo capa LLM).
- **Compresión que degrada respuesta**: guardia de US6 revierte al prompt original.
- **Modelo seleccionado en la calculadora sin rate conocido**: mostrar ahorro en tokens sin USD (o caer a un rate por defecto con aviso) y un veredicto "USD no disponible".
- **Calculadora con veredicto "No conviene"**: el usuario igual puede forzar la activación (decisión humana), pero el sistema avisa del bajo ahorro esperado.
- **Config por grupo y por usuario en conflicto**: el override de usuario gana sobre el del grupo; ambos ganan sobre el global.
- **Compresión + doble capa presupuestaria (spec 011)**: el descuento neto debe respetar el orden secuencial (personal → grupo fallback).
- **Streaming**: `tokens_saved` se conoce tras la respuesta (los tokens reales llegan al final); el descuento neto se ajusta post-respuesta, igual que el TPM en el spec 007.

## Módulos afectados

### Backend
- `backend/src/services/optimization_service.py` — reescritura: compresor determinista seguro + tiktoken + umbral + estrategia LLM con ROI + caché Redis.
- `backend/src/api/chat.py` — capa 1.5: aplicar estrategia resuelta, persistir `tokens_saved`/`cost_saved_usd`, descuento neto en presupuesto.
- `backend/src/models/policy.py` / `backend/src/models/group.py` — config rica: `compression_strategy`, `compression_threshold_tokens`, `compression_aggressiveness`, `compression_compressor_model`, `compression_cache_enabled` (renombrar el flag `headroom_mode` → `compression_mode`).
- `backend/src/models/audit.py` — columnas `tokens_saved`, `cost_saved_usd`.
- `backend/src/api/analytics.py` — endpoints de ahorro: KPI "Ahorro de Costes IA", ratio por modelo, desglose por usuario/grupo/período.
- `backend/src/api/costs.py` (nuevo) — endpoints de visualización de costes y calculadora (`POST /costs/calculator` → tokens, tras compresión, ahorro USD + veredicto de activación).
- Alembic migration — nuevas columnas + renombrado del flag.

### Frontend
- `frontend/src/pages/CostsPage.tsx` (nuevo) — sección Costos: KPIs de gasto, selector de período, **calculadora interactiva con veredicto activar/no**, toggle de compresión y config por grupo/usuario.
- `frontend/src/services/api.ts` — métodos de costes, calculadora y config de compresión.
- `frontend/src/App.tsx` — nueva ruta "Costos" + RBAC (admin/compliance_officer).
- `frontend/src/pages/DashboardPage.tsx` — KPI "Ahorro de Costes IA".

### Dependencias
- `tiktoken` (conteo real de tokens) — nueva dependencia backend.
- Librería externa de compresión (opcional, capa LLM) — solo si se elige esa vía; el determinista no la requiere.
- Redis (ya desplegado en spec 006/007) — caché de capa LLM.

## Decisiones de diseño (propuesta — a confirmar)

1. **Motor compresor**: **Determinista seguro (P1) + LLM opcional (P2)** — recomendado. El determinista entrega valor sin dependencias; el LLM se añade después para prompts grandes. *(A confirmar)*
2. **Integración de coste**: **Presupuesto + dashboard** — recomendado. Descuento neto + KPI. *(A confirmar)*
3. **Caché Redis**: solo en la capa LLM, por hash del prompt. El determinista no cachea (es barato). *(Confirmado)*
4. **Calculadora como decisión de activación**: la calculadora no solo informa, **recomienda** activar/no activar según el ahorro estimado vs overhead y el umbral. El usuario puede aceptar la recomendación o forzar la decisión.
5. **Compresión tras enmascaramiento PII**: se mantiene el orden actual (capa 1.5 tras PII, antes de routing). Los placeholders `[PII_N]` son tokens atómicos.
6. **Fail-open**: si el compresor (determinista o LLM) falla, se usa el prompt original; el chat nunca se rompe.
7. **White-label**: el nombre del modelo compresor interno no se expone en la UI pública ni en exports. El feature se llama "Ahorro de Costes IA" (sin nombres de terceros).
8. **Descuento neto + doble capa (spec 011)**: el presupuesto se descuenta por tokens netos respetando el orden secuencial personal → grupo.

## EU Compliance / GDPR

- La compresión ocurre **después** del enmascaramiento PII, por lo que el prompt comprimido enviado al LLM nunca contiene datos personales en claro.
- Si el compresor LLM es un modelo cloud, debe ser un modelo UE-compliant (Azure EU / Vertex EU / Ollama on-prem) cuando el proyecto lo exija — el routing GDPR (spec 005) sigue aplicando.
- `audit_logs` registra `tokens_saved`/`cost_saved_usd` (metadata de optimización, no contenido) — conforme a la regla de metadata-only auditing de la constitución.