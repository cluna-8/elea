# Tasks: Auditoría durable — bloqueos registrados, escritura ruidosa, UI honesta

**Input**: Design documents from `/specs/031-durable-audit/`

**Prerequisites**: plan.md, spec.md, research.md (D1-D8), contracts/audit-durable.md, quickstart.md

**Tests**: incluidos (la spec es de garantías de registro — sin tests no hay spec).

**Organization**: por user story. Deadline: demo JUEVES 30-jul; MVP = US1 (bloqueos durables).

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [x] T001 Config `BASA_AUDIT_FAIL` (contrato §Config): env con default `open` leída por
      backend y extensiones; cablear en `deploy/docker/compose.prod.yml` (backend + motor),
      `docker-compose.yml` (dev) y perfil camara (`open` explícito). Helper único de
      lectura en backend (`audit_service`); las extensiones leen os.environ directo.

## Phase 2: Foundational (bloquea US1 y US2)

- [x] T002 `backend/src/services/audit_service.py` — núcleo D5: retry acotado (2×,
      backoff 0.2/0.5 s) en la escritura; al agotar → `logger.error` + `INCR
      basa:audit:lost` + `SET basa:audit:last_fail` (tolerante a Redis caído);
      `audit_writable()` (SELECT 1 con timeout corto) para el modo closed; adiós al
      return-None-que-nadie-mira (:117-120): en `open` el fallo queda contado, en `closed`
      se propaga excepción tipada. Unit tests
      `backend/tests/unit/test_audit_service_retry.py` (mock de sesión que falla N veces:
      retry absorbe 1 fallo transitorio sin pérdida; agotamiento incrementa contador; Redis
      caído no rompe; closed propaga).
- [x] T003 [P] `backend/src/api/internal.py` — contrato §internal: campos opcionales
      nuevos de `AuditEntry` (+columnas en el INSERT :90, retrocompatible: payload viejo
      sigue insertando igual) + `GET /internal/audit/probe` (secreto interno, 200/503).
      Tests en el fichero de tests del plano interno existente (buscarlo por
      `internal/audit`).

**Checkpoint**: escritor con retry+contador verde en unit; plano interno extendido.

## Phase 3: User Story 1 — bloqueos durables en 3 planos (P1) 🎯 MVP

**Goal**: registrar→bloquear en chat, motor y passthrough; filtro «Bloqueados» honesto.

**Independent Test**: quickstart SC-001 — un bloqueo por plano → 3 filas correctas.

- [x] T004 [US1] `backend/src/api/chat.py` — D2: en los 3 puntos de bloqueo (~598 AI-Act,
      ~728 guardián, ~839 residencia; anclar por contenido) escribir la fila durable ANTES
      del raise vía `log_transaction` (tokens 0, coste 0, `compliance_status=blocked_*`
      alineado con el motivo del monitor — D1/riesgo R3, `blocked_by_layer` del punto,
      conteos si los hay, `routing_decision` si era «auto»); el evento efímero se conserva.
      Modo closed: pre-check `audit_writable()` ANTES de la llamada al motor en el camino
      feliz → 503 honesto (contrato §closed). Integration tests
      `backend/tests/integration/test_chat_block_audit.py` (patrón test_chat_audit_row_pii):
      bloqueo AI-Act → fila blocked con capa y atribución; bloqueo guardián ídem; fila
      sobrevive aunque el monitor Redis esté caído; closed+DB caída → 503 sin llamada al
      motor (mock httpx cuenta 0 llamadas).
- [x] T005 [P] [US1] `litellm/extensions/basa_guardrail.py` — D3: en cada punto de bloqueo,
      POST al plano interno (identidad de la Connection del `user_api_key_dict`, capa,
      motivo, conteos; 1 reintento) ANTES de rechazar; en closed, pre-check a
      `/internal/audit/probe` (cache 5 s si hace falta — riesgo R2) → rechazo honesto si no
      escribible. Tests unit-style importando la extensión con mocks (mirar cómo se testean
      hoy las extensiones en backend/tests o litellm/; si no hay patrón, crear
      `backend/tests/unit/test_guardrail_block_audit.py` con sys.path a litellm/extensions).
- [x] T006 [P] [US1] `backend/src/api/gateway.py` — D5/D8: `_audit` del passthrough deja de
      tragar (:603-604 delega en el escritor con retry; en open captura para no romper el
      request); camino closed en passthrough y byok (pre-check antes de reenviar). Test:
      bloqueo passthrough con escritor que falla 1 vez → fila igual (retry); closed → 503.
- [x] T007 [P] [US1] `backend/src/api/audit.py` + frontend `AuditPage.tsx` — FR-006:
      parámetro de filtro `estado=bloqueados` (LIKE 'blocked%') en el endpoint de listado +
      control de filtro en la UI + badge rojo por fila bloqueada (estado explícito). Test
      API del filtro.
- [x] T008 [US1] **CHECKPOINT VIVO** (orquestador, stack camara): quickstart SC-001 — un
      bloqueo por plano → 3 filas con plano/capa/atribución correctos, visibles con el
      filtro; SC-005 (encontrarlo en <30 s desde la UI).

## Phase 4: User Story 2 — auditoría ruidosa + fail-closed opcional (P2)

**Goal**: pérdidas visibles (contador+banner+health); closed = 503 honesto pre-proveedor.

**Independent Test**: quickstart SC-002 (integración con mock + contador/banner en vivo).

- [x] T009 [US2] `backend/src/api/health.py` — bloque `audit {mode, lost_events,
      last_failure_at}` del contrato; en closed con auditoría caída el health global
      refleja degradado. `litellm/extensions/basa_audit_logger.py`: prints→logging real,
      retry acotado, contador Redis (D5 — mismas claves). Tests: health con contador
      poblado en Redis; logger sin prints (grep en el gate).
- [x] T010 [P] [US2] `frontend/src/pages/AuditPage.tsx`: banner ámbar «N eventos no
      registrados desde HH:MM» cuando `health.audit.lost_events > 0` (poll al health
      existente de la página o fetch ligero al cargar).
- [x] T011 [US2] **CHECKPOINT VIVO**: simular pérdida (parar DB en ensayo o inyectar
      contador en Redis) → banner + health; restaurar → constancia queda.

## Phase 5: User Story 3 — UI honesta (P3)

**Goal**: guardianes cloud = catálogo incoming sin toggle; reales con plano; retención sin
checkbox mentiroso.

**Independent Test**: checklist SC-004 contra la tabla de consumo real.

- [x] T012 [US3] Guardianes — D7: backend rechaza activar guardianes sin guardrail cargado
      (usar `governance_status`/`probe_loaded_guardrails` — FR-007) + frontend (página de
      guardianes, nombre real a localizar): 5 cloud como tarjetas «próximamente / no
      instalado» SIN toggle; 3 reales con badge de plano(s) («chat interno + API byok» /
      «chat interno»). Copy: features incoming del catálogo, no promesas rotas (marco JF).
- [x] T013 [P] [US3] Retención (frontend pestaña en CompliancePage o equivalente): chip
      «purga automática: llega con la 018», política editable intacta, sin fecha inventada.
- [x] T014 [US3] **CHECKPOINT**: checklist SC-004 página por página.

## Phase 6: Polish

- [x] T015 Gate final: suite completa verde (salvo 3 preexistentes) + SC-003 explícito
      (`-k "hash or chain or licensing"`) + grep sin `print(` en extensiones + INSTALL:
      nota de `BASA_AUDIT_FAIL` (default open) en la sección de operación.

## Dependencies

```text
T001 → T002/T003 [P] → US1: T004/T005/T006/T007 [P entre sí] → T008 (vivo)
US2: T009 (necesita T002) → T010 [P] → T011 (vivo)
US3: T012/T013 [P] (independientes de US1/US2) → T014
T015 al final
```

## Implementation Strategy

- MVP = Fases 1-3 (US1): la demo del jueves necesita «intento bloqueado → fila visible».
- US3 es paralelizable con US1/US2 (ficheros disjuntos: guardianes/retención vs audit).
- Los checkpoints vivos los corre el orquestador contra el stack camara; los agentes NO
  tocan contenedores camara-*.
- Coordinación 016/Cristian: NO se coordina antes (decisión JF) — la review llega vía PR.
  Los ficheros de Cristian que se tocan (guardrail/logger) se tocan quirúrgicamente y con
  tests, deduciendo el contrato del código (D3/D5).
