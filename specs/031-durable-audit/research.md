# Research (Fase 0) — 031 Auditoría durable

Evidencia base: sección «El problema, con evidencia» de spec.md (file:line verificados
28-jul). Aquí solo las DECISIONES de diseño.

## D1 — Convención de estado: `compliance_status` con prefijo `blocked_*` (ya existe)

**Decisión**: las filas de bloqueo usan la convención QUE YA USA el passthrough:
`blocked_prohibited` (AI-Act) y `blocked_secret` (gateway.py:270-282); se añaden con el
mismo patrón los motivos que falten (`blocked_guardian`, `blocked_residency`,
`blocked_entity`…, alineados con los motivos reales de cada punto). El filtro de UI y API
(FR-006) es `compliance_status LIKE 'blocked%'` — sin columna nueva, sin migración.

**Racional**: el modelo ya documenta el espacio de valores como String libre
(audit.py:27) y el único plano que hoy escribe bloqueos usa este prefijo. Unificar sobre
lo existente = las filas viejas del passthrough entran gratis al filtro nuevo.

## D2 — Chat backend: registrar → bloquear en los 3 puntos, reusando `log_transaction`

**Decisión**: en los 3 puntos de bloqueo de chat.py (~598 AI-Act, ~728 guardián, ~839
residencia) se escribe la fila durable ANTES del `raise`, con el MISMO
`audit_service.log_transaction` del camino feliz: tokens 0/0, coste 0, modelo del request,
`compliance_status=blocked_*`, `blocked_by_layer` (el punto ya conoce su capa — se la
manda al monitor), `applied_layers` según attribution 027 disponible en ese momento,
conteos de entidades si los hay, y `routing_decision` si el request era «auto» (030). El
evento efímero del monitor se CONSERVA tal cual.

**Racional**: es exactamente el pago del corte D6 documentado en chat.py:357-360. Reusar
log_transaction mantiene un solo escritor (donde vive el retry de US2) y la hash-chain no
se toca (los eslabones license van por otro camino — FR-010, gate SC-003).

## D3 — Plano motor: el guardrail registra vía `POST /internal/audit` antes de rechazar

**Decisión**: `sentinel_guardrail.py` (todos sus puntos de bloqueo, :105-166) construye el
payload de bloqueo (identidad de la Connection desde `user_api_key_dict`, capa, motivo,
conteos) y lo POSTea al plano interno EXISTENTE (`internal.py:140 record_audit`,
autenticado con el secreto interno) ANTES de devolver el rechazo. `AuditEntry` se extiende
retrocompatible (campos opcionales: `compliance_status` bloqueado, `blocked_by_layer`;
verificar cuáles ya existen). Reintento: 1 (presupuesto de latencia del plano agentic);
si falla → política D5 (contador+log en open, rechazo honesto en closed).

**Alternativas descartadas**: implementar `async_log_failure_event` en el logger para
capturar bloqueos (el hook de failure de LiteLLM se dispara en errores del PROVEEDOR, no
garantiza disparo en rechazos pre-call del guardrail propio — el guardrail es quien TIENE
el verdict y la identidad; el logger de éxito queda como está). Driver de Postgres en la
imagen (restricción conocida: la imagen no trae pip/uv — por eso existe el plano interno).

## D4 — Config `audit_fail`: env `SENTINEL_AUDIT_FAIL=open|closed` (default open)

**Decisión**: una env leída por backend Y extensiones del motor (compose.prod.yml la
cablea a ambos contenedores; el perfil del piloto la declara `open` explícita en
secrets/env del cliente). En `closed`:
- Plano chat y passthrough: **check de escribibilidad ANTES de llamar al proveedor**
  (SELECT 1 sobre la sesión de auditoría con timeout corto); si falla → 503 honesto con
  motivo (patrón fail-closed licencias 021). La escritura post-respuesta que falle tras un
  check OK → retry+contador (no se puede des-servir una respuesta ya servida; el caso
  streaming queda documentado como en la spec).
- Plano motor: el guardrail hace el mismo pre-check contra el plano interno (endpoint
  probe ligero, ver contrato); si no responde → rechazo honesto (mismo patrón que su
  fail-closed de NLP caído, guardrail:146/166).

**Racional**: «antes de llamar al proveedor» es literal en FR-005 (no gastar dinero en
tráfico inauditable). El pre-check barato evita pagar el retry completo en cada request
durante una caída.

## D5 — Retry acotado + contador Redis (jamás cola, jamás print)

**Decisión**: en `audit_service` (único escritor del backend): 2 reintentos con backoff
0.2 s/0.5 s (total acotado <1,5 s); al agotar → `logger.error` + `INCR sentinel:audit:lost` +
`SET sentinel:audit:last_fail <iso>` (Redis; si Redis también está caído, solo logger — nunca
excepción hacia el request en `open`). Las extensiones del motor replican el patrón en su
proceso (ya tienen Redis: son productoras de la vitrina) y sus `print` (:104-105, 177-180,
192-193) pasan a `logging` con nivel real. `gateway.py:603-604` deja de tragar: delega en
el escritor con retry y solo captura para no romper el request en `open`.

**Racional**: el edge case anti-DoS de la spec — presupuesto fijo, el contador es la
válvula. La pérdida byok del ensayo (documentada en sentinel_audit_logger.py:145-150) habría
sido visible en minutos con el contador+banner.

## D6 — Exposición: health + banner en Logs

**Decisión**: `GET /health` gana bloque
`audit: {mode: open|closed, lost_events: N, last_failure_at: iso|null}` (leyendo Redis);
`AuditPage` muestra banner ámbar si `lost_events > 0` («N eventos no registrados desde
HH:MM») y el filtro nuevo «Bloqueados» (D1) con badge rojo por fila. En `closed` con
auditoría caída, health refleja degradado (edge case de la spec — sin «healthy» mentiroso).

## D7 — US3 UI honesta: derivar de lo que ya calcula la 027

**Decisión**: la página de guardianes deja de pintar toggles para los 5 cloud: se
renderizan como catálogo «próximamente / no instalado» (no activables — el backend además
rechaza activarlos si no hay guardrail cargado, FR-007) usando la disponibilidad REAL que
ya computan `governance_status.py` (D4 de la 027: «deseo, no estado») y
`ai_engine_client.probe_loaded_guardrails` (:249-290). Los 3 reales llevan badge de
plano(s): pii_masking «chat interno + API byok», secret_detection/sensitive_routing «chat
interno» (tabla de consumo real de la spec). «Retención de Datos»: política editable igual
+ estado «purga automática: llega con la 018» (chip, sin checkbox mentiroso).

## D8 — Deduplicación de responsabilidades entre planos

**Decisión**: cada plano registra SOLO sus propios bloqueos — el passthrough no
re-registra bloqueos del motor (imposible por diseño: byok se va del gateway en :801-802
antes de la policy) y el chat no registra bloqueos del motor (si el motor rechaza una
llamada del chat, eso es un error de upstream del camino feliz existente, no un bloqueo
del plano chat). Cero riesgo de fila doble sin necesidad de idempotencia nueva.

## Riesgos abiertos (a tasks como checkpoints)

1. `AuditEntry`/INSERT del plano interno: confirmar qué campos ya acepta y extender
   retrocompatible (el INSERT es SQL crudo con columnas fijas, internal.py:90).
2. Latencia del pre-check `closed` en el guardrail (agentic tools): medir; si el probe
   añade >100 ms p50, cachear el estado del probe 5 s (ventana de riesgo declarada).
3. El valor exacto de `blocked_*` por punto de chat: alinear con los motivos que ya
   muestra el monitor (LAYER_LABELS/decisiones de monitor.py:121-155) para que vitrina y
   durable cuenten la misma historia.
