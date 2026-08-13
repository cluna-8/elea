# Tasks: Retención con dientes — purga programada + tiers de enforcement

**Input**: Design documents from `/specs/018-retencion-tiers/` (plan.md, research.md, data-model.md, contracts/, quickstart.md — sellados 13-ago; gate de producto JF sellado 13-ago).

**Tests**: OBLIGATORIOS por DevFlow del depto («código nuevo = tests nuevos en el mismo PR», tests-que-muerden verificados por mutación donde aplique). Codex-gate en cada PR con código.

**Quién**: implementa el equipo de **Jeff 2** (coders Opus 5); Cristian = gate de review de seguridad; el manager gatea y mergea. Frontera: NADA de `litellm/extensions/` salvo el alta de UNA clave en el registry de `basa_governance.py` (T016 — cambio de código puro, sin lógica de motor). El terreno 036/037 de Cristian no se toca.

**Ramas/PRs**: ramas cortas colgadas de main (la spec ya está mergeada), PR < 400 líneas, un PR por fase o módulo coherente. `Closes #NNN` en inglés donde aplique.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [ ] T001 Crear paquete `backend/src/services/retention/` (`__init__.py`, esqueletos `classifier.py` / `purger.py` con docstrings de contrato — ver `contracts/clasificador-identidad-tier.md`) + `backend/src/services/retention_scheduler.py` esqueleto.
- [ ] T002 [P] Los 5 envs de purga (tabla del plan) declarados en `.env.example` con comentario de contrato — OJO: el gate de drift de docs (main) exige paridad con `docs/docs/.../configuration.md`: correr `make -C deploy docs-refs` en el mismo PR.

**Checkpoint**: esqueleto compilable, suite existente verde.

## Phase 2: Foundational (bloquea todo lo demás)

- [ ] T003 `classifier.py` completo — Contrato 1: `clases()`, `predicado()`, `clase_de()`; mapeo fiel al seed 004:100-109 y a los emisores vigentes; exclusión estructural `model='license'`.
- [ ] T004 `tests/unit/test_retention_classifier.py`: **test de partición total** sobre dataset sembrado que cubre todos los emisores actuales (blocked%, rejected%, config_change_*, license, tráfico normal, budget_402) — un emisor nuevo sin clase DEBE romperlo.
- [ ] T005 [P] Refactor `api/audit.py:36-64`: constantes locales → clasificador, con test de **paridad exacta** de la vitrina pre/post refactor (dataset sembrado; la vitrina es superficie viva del cliente).
- [ ] T006 [P] Fixture de harness «mundo post-017» en `tests/conftest.py` o módulo propio: dropea `tenant_isolation_bootstrap` + conecta con rol NOSUPERUSER creado ad-hoc en la DB de test (Contrato 2, SC-004). Documentar en el docstring que esto es el estado que la 017 activa después.
- [ ] T007 Fix del emisor de la cadena: `licensing/audit_events.py:213-218` `SessionLocal` pelado → `tenant_context(bypass=True)`; test bajo la fixture T006.

**Checkpoint**: PR Foundational (clasificador + vitrina + fixture + emisor). Codex-gate. Merge del manager antes de arrancar US1.

## Phase 3: US1 — La promesa del día 91 se cumple (P1) 🎯 MVP

- [ ] T008 `purger.py`: corrida por clase — cutoff contra reloj de DB, DELETE por lotes (`BATCH_SIZE`, pausa entre lotes), respeto de ventana horaria + TZ, flag `--run-now` para tests/operación; idempotencia por diseño (predicado «vencida ahora»).
- [ ] T009 [US1] FR-004: al purgar `prompt_content`, `UPDATE human_reviews SET response_text=NULL` para reviews vencidas (fila persiste); mismo lote/ventana.
- [ ] T010 [US1] FR-005: escritura de `purge_log` (JSONB, cap 50 corridas/clase) + fila resumen `config_audit` en `audit_logs` por corrida — todo metadata-only, vía Contrato 2.
- [ ] T011 [US1] `retention_scheduler.py`: thread daemon (patrón `reconcile.py:240-281`), wiring en startup del backend, `BASA_PURGE_ENABLED` maestro.
- [ ] T012 [US1] `tests/integration/test_retention_purge.py`: SC-001 completo (200 días sintéticos → cero vencidas purgables, cero no-vencidas afectadas, license intactas, `verify_chain` + true-up verdes) + edge cases: plazo acortado en caliente, cadena intercalada, corrida interrumpida (idempotencia), reloj de DB.
- [ ] T013 [US1] Seed de test `tests/seeds/seed_retention_dataset.py` (usado por T012 y quickstart §1).
- [ ] T014 [US1] Los tests de purga corren TAMBIÉN bajo la fixture post-017 (`test_purge_post017.py`) — SC-004.

**Checkpoint**: PR US1. **STOP & VALIDATE**: quickstart §1-§3 en vivo sobre compose antes de pedir gate. Este PR ES el MVP de la spec.

## Phase 4: US2 — Tiers de enforcement (P2)

- [ ] T015 [US2] FR-007: validación de rangos en `PUT /compliance/retention` (`compliance.py:319-334`): mínimos por clase + pisos/topes del tier vigente (tabla research.md D7); fuera de rango → 422 con detalle del piso; test por clase y por tier.
- [ ] T016 [US2] Alta de la capa `enforcement_tier_estricto` en el registry 027 (`basa_governance.py` — código puro, la ÚNICA línea fuera del backend) + resolución desde el backend.
- [ ] T017 [US2] Consumidores del tier: aserción `BASA_AUDIT_FAIL=closed` cuando estricto (incoherencia → health degradado + evento auditado; NO se reescribe env, NO se toca el espejo del motor) + cambio de tier auditado con valor anterior/nuevo (SC-006).
- [ ] T018 [US2] `tests/integration/test_retention_tiers.py`: escenarios US2 completos + invariante «la capa de piso AI-Act se evalúa SIEMPRE» (regresión sobre el test 027 existente).

**Checkpoint**: PR US2. Codex-gate (toca superficie de gobernanza).

## Phase 5: US3 — La purga no le cuesta el examen a nadie (P2)

- [ ] T019 [US3] Encargo a **La ITV** (vía manager): corrida del perfil 125 con purga concurrente + backlog real; criterio = 4 SLOs de oro verdes (SC-003). La ITV mide, no parchea; si reprueba, vuelve como issue a este equipo (tuning de BATCH_SIZE/pausa/ventana).

## Phase 6: Polish + tarea suelta

- [ ] T020 [P] Docs vendibles: actualizar `docs/docs/compliance/dpa-dsr-retention.md` — retención pasa de «configurable» a «enforced» SOLO tras el merge de US1 (regla de honestidad; el gate de drift de docs vigila).
- [ ] T021 [P] ROADMAP-guardian.md: marcar 018 en implementación; FR-010 (retención por tenant) anotada como deuda con dueño.
- [ ] T022 [P] **Tarea suelta (no bloquea nada)**: fix del 500 del export DSAR — `reports.py:89` `User.id.cast(str)` (issue #193, `Closes #193`); test de que el export responde 200 con su alcance actual (audit_logs, limit 1000). NO ampliar alcance: el DSAR completo es spec propia en C3.

**Dependencias**: T003→T004→T005; T006→T007→(T012,T014); US1 completa antes de US2 (los pisos del tier validan contra clases del clasificador); T019 tras US1 mergeada. T022 es independiente de todo.
