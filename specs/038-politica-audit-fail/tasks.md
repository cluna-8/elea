# Tasks: Política de auditoría cuando NO se puede auditar — por riesgo, no global

**Input**: spec.md (D1-D5 selladas 18-ago) + plan.md (anclas medidas @85c9c55)

**Ejecuta**: equipo de Jeff (Ola 2, sprint al 5-sep). Jeff descompone entre sus coders con
la regla de siempre: brief cerrado + worktree propio + tests RED→verde en el MISMO PR +
1ª línea merged-green de Jeff antes del gate cross-familia del manager.

**Tests**: obligatorios en cada PR (código nuevo = tests nuevos, backend sin excepciones).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable (archivos distintos, sin dependencia)
- **[GATE]**: no es código de esta spec — es condición de arranque/cierre

---

## Phase 0: Precondiciones FR-007 (estado 18-ago)

- [x] T000 [GATE] #176 (402 del motor sin fila) — CERRADO 17-ago ✅
- [ ] T001 [GATE] **#207 (`model` no-string en `/gw` = 200 sin fila) se cierra ANTES o en
      el mismo ciclo.** Bloquea el checkpoint de US1: sin esto la política decide sobre un
      camino de escritura que se traga filas en silencio.
- [ ] T002 [GATE] **#212 (422 del literal contado como `passed`)** — fix por call-site SOLO
      en `/gw` (estado propio, precedente `STATUS_SATURATED` en `gateway.py:1199`),
      **coordinado con La ITV** (su reconcile cuenta literales exactos — el manager
      coordina la ventana). No bloquea US1; SÍ bloquea el cierre de la spec.

---

## Phase 1: Foundational (bloquea todas las stories)

**Purpose**: el parser y la matriz existen, testeados, sin que ningún plano los use aún.

- [ ] T003 [P] Parser de modo en `backend/src/services/audit_service.py`:
      `BASA_AUDIT_FAIL ∈ {open, closed, policy}`, ausente/ilegible ⇒ `policy` (D1).
      `audit_fail_mode()` conserva nombre y contrato string. Tests unit RED→verde en
      `backend/tests/unit/`: los 3 valores + ausente + basura (`"POLICY "`, `"abierto"`,
      vacío) ⇒ `policy`.
- [ ] T004 [P] `audit_fail_decision(risk_level) -> bool` en el mismo módulo — ÚNICO lugar
      de la matriz D2: `minimal`/`limited` sirve · `annex1`/`annex3` corta ·
      `None`/desconocido corta (fail-closed hacia lo reversible) · clase `config_audit`
      no entra (FR-002). Tests unit: los 4 niveles + None + string desconocido + la
      mutación «matriz invertida» debe romper los tests.
- [ ] T005 Aserción del tier (D3) en `backend/src/services/basa_governance.py`: con
      `enforcement_tier_estricto=on`, `policy` es incoherencia igual que `open` (degrada
      health, no corta boot). Test integration sobre el camino existente de la 018.

**Checkpoint**: matriz y parser en main sin consumidores nuevos — cero cambio de
comportamiento (suite completa verde lo demuestra).

---

## Phase 2: User Story 1 — La instalación decide por riesgo (P1) 🎯 MVP

**Goal**: con auditoría caída y modo `policy`: `minimal` se sirve y se cuenta,
`annex3` recibe el 503 honesto — en los tres planos.

**Independent Test**: SC-001 contra stack real (base de auditoría tumbada a mano).

- [ ] T006 [US1] Plano **chat**: en `backend/src/api/chat.py` (donde hoy consulta
      `audit_fail_mode()`, contexto `_applied_risk_level` ya resuelto en `:1319`), modo
      `policy` ⇒ `audit_fail_decision(...)`; servir sin fila ⇒ `INCR basa:audit:lost`
      (camino existente). Integration tests: ambos niveles × auditoría caída.
- [ ] T007 [US1] Plano **`/gw`**: ídem en `backend/src/api/gateway.py`. Integration tests
      espejo de T006.
- [ ] T008 [US1] Plano **motor byok**: el probe `/api/v1/internal/audit/probe` gana
      contexto de credencial y responde la DECISIÓN ya tomada (la matriz no se duplica en
      el motor). `litellm/extensions/basa_guardrail.py` (`_audit_fail_mode():164`, cache
      5 s `:280`) y `litellm/extensions/basa_audit_logger.py` (`audit_fail_mode():88`) —
      **los DOS lectores** consumen el resultado nuevo. Regla de cache: en modo `policy`
      jamás cachear la decisión de un pedido para otro (cachear modo, no decisión).
      Contract test del probe + integration del plano motor.
- [ ] T009 [US1] **SC-001 E2E real**: stack levantado, Postgres de auditoría tumbado a
      mano, `policy` activo: pedido `minimal` → 200 + contador incrementa; pedido
      `annex3` → 503. Evidencia (comandos + salida) al PR — capa 4 del merge autónomo.

**Checkpoint US1**: requiere T001 (#207) cerrado para declararse honesto.

---

## Phase 3: User Story 2 — Compat total con lo que corre (P1)

**Goal**: `open`/`closed` explícitos = bit-a-bit lo de hoy; el examen ITV pasa sin cambios.

- [ ] T010 [US2] Tests de no-regresión: `open` explícito y `closed` explícito reproducen
      la semántica actual EXACTA en los tres planos (los tests existentes de 031 siguen
      verdes sin editar — si uno hubiera que editarlo, eso es una regresión, no un test
      viejo). SC-002: la config de `deploy/clients/itv-examen/client.env.example:43-45`
      corre tal cual — **ese archivo NO se toca**.

---

## Phase 4: User Story 3 + FR-005 — Honestidad a máquina (P2)

- [ ] T011 [P] [US3] Marcador D5 en `/gw`: toda respuesta servida sin fila lleva el header
      machine-readable (propuesto `X-Basa-Audit-Lost: 1`; nombre final se documenta en el
      contrato en el MISMO PR). Precedente `X-Basa-Rejected` (#135). Integration test:
      header presente al servir sin fila, ausente en camino normal.
- [ ] T012 [P] FR-005/D4 (cierra #165): 400/422 de validación previa ⇒ CERO filas en
      `audit_logs` + contador estructurado por tenant/endpoint + log sin cuerpo. SC-003
      demostrado en integration test (cero filas nuevas + contador observable).

---

## Phase 5: Polish & barrido de lectores (mismo ciclo, no después)

- [ ] T013 [P] **Docs de producto (DoD)**: `docs/docs/api-reference/errors.md:84-90`
      (los tres modos + marcador D5) + la referencia colgada a `configuration.md` +
      `make -C deploy check-docs` verde.
- [ ] T014 [P] Barrido de lectores de `BASA_AUDIT_FAIL` en el MISMO ciclo:
      `.env.example` (documentarla POR PRIMERA VEZ — hueco del #190: los 3 valores +
      default `policy`) · `docker-compose.yml:91,178-179` (comentario y default del
      template) · contrato `specs/031-durable-audit/contracts/audit-durable.md:31-35`
      (tercer modo + puntero a esta spec) · **`frontend/src/services/api.ts`** (lector
      encontrado en el barrido del 18-ago — verificar qué muestra y actualizar).
- [ ] T015 Actualización de `specs/ROADMAP-pisos.md` (`:32`, `:115`, `:129`: la pregunta
      abierta queda respondida por esta spec) — coordinar con el tracking visual de Jeff
      (doble escritor conocido).

---

## Dependencies & Execution Order

- **Phase 1 (T003-T005)**: arranca YA; T003/T004 paralelos, T005 tras T004.
- **Phase 2 (US1)**: tras Phase 1. T006/T007 paralelos; T008 necesita el probe (secuencia
  interna: contrato probe → guardrail/logger). T009 al final de la fase. Checkpoint
  honesto requiere T001 (#207).
- **Phase 3 (US2)**: tras Phase 1; paralelizable con US1 (solo tests + testigo ITV).
- **Phase 4 (T011/T012)**: tras Phase 2 en `/gw`; T012 puede ir en paralelo desde Phase 1
  (no depende de la matriz).
- **Phase 5**: T013/T014 en el PR que cambia cada superficie (no un PR-escoba al final);
  T015 al flip del nodo.
- **Slicing sugerido para PRs** (Jeff decide el corte final): PR-A = Phase 1 completa ·
  PR-B = US1 backend (T006+T007) + US2 (T010) · PR-C = motor (T008) + SC-001 (T009) ·
  PR-D = T011+T012+docs. Cada PR con su tajada de T013/T014.

## Notas para el que descompone

- La matriz vive UNA vez (T004); si un plano la re-implementa aunque sea «igualita», es
  NO_APTO en el gate.
- Fail-closed hacia lo reversible: todo camino nuevo con duda corta (503), jamás sirve.
- `None`/desconocido corta: un pedido sin riesgo resuelto es un pedido que no demostró ser
  de bajo riesgo.
- El gate del manager es cross-familia con linaje Pro (superficie de compliance — misma
  vara que auth).
