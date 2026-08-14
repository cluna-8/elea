# Tasks: Retención con dientes — purga programada + tiers de enforcement

**Input**: Design documents from `/specs/018-retencion-tiers/` (plan.md, research.md, data-model.md, contracts/, quickstart.md — sellados 13-ago; gate de producto JF sellado 13-ago).

**Tests**: OBLIGATORIOS por DevFlow del depto («código nuevo = tests nuevos en el mismo PR», tests-que-muerden verificados por mutación donde aplique). Codex-gate en cada PR con código.

**Quién**: implementa el equipo de **Jeff 2** (coders Opus 5); Cristian = gate de review de seguridad; el manager gatea y mergea. Frontera: NADA de `litellm/extensions/` salvo el alta de UNA clave en el registry de `basa_governance.py` (T016 — cambio de código puro, sin lógica de motor). El terreno 036/037 de Cristian no se toca.

**Ramas/PRs**: ramas cortas colgadas de main (la spec ya está mergeada), PR < 400 líneas, un PR por fase o módulo coherente. `Closes #NNN` en inglés donde aplique.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [x] T001 Crear paquete `backend/src/services/retention/` (`__init__.py`, esqueletos `classifier.py` / `purger.py` con docstrings de contrato — ver `contracts/clasificador-identidad-tier.md`) + `backend/src/services/retention_scheduler.py` esqueleto.
- [x] T002 [P] Los envs de purga declarados en `.env.example` con comentario de contrato — quedaron **7**, no 5: la tabla del plan trae 6 y la enmienda del 13-ago sumó `BASA_PURGE_DRY_RUN`. Paridad con `docs/docs/api-reference/configuration.md` verificada (las 7 filas están en `:21-27`). OJO para el próximo que toque este bloque: `docs/gen_config_reference.py` sólo arrastra los comentarios **inmediatamente** encima de cada `VAR=` (una línea en blanco corta el bloque), así que el encabezado de sección del `.env.example` no viaja a la doc.

**Checkpoint**: esqueleto compilable, suite existente verde.

## Phase 2: Foundational (bloquea todo lo demás)

- [x] T003 `classifier.py` completo — Contrato 1: `clases()`, `predicado()`, `clase_de()`; mapeo fiel al seed 004:100-109 y a los emisores vigentes; exclusión de la cadena **por la FORMA de `guardian_events`** (`es_trafico_demostrable()`): queda fuera de toda purga la fila cuyo primer evento es un objeto con `seq`, `prev_hash` **o** `event_type`, y la columna `model` NO participa en ninguna forma. *(enmienda del manager 14-ago; **DEROGA** la del 13-ago, que pedía `model='license'` **y** `seq` en `guardian_events[0]`. Los dos motivos: anclar en `seq` habría BORRADO irreversiblemente las licencias legítimas pre-US5 —`event_type` sin `seq`, ventana 16→20-jul-2026—, y anclar en el literal —que el cliente escribe en el body, `api/gateway.py:1472`— le regalaba inmortalidad PERMANENTE a los spoofs ya escritos en bases de clientes instalados, porque la Capa B tapa lo nuevo y no puede sanear hacia atrás. Contrato 1, regla 2.)* La vitrina conserva el criterio por literal a propósito: «purga = por forma (irreversible → no confía en nadie); vitrina = por literal (reversible → y el literal ya es nuestro gracias a la Capa B)».
- [x] T004 `tests/unit/test_retention_classifier.py`: **test de partición total** sobre dataset sembrado que cubre todos los emisores actuales (blocked%, rejected%, config_change_*, license, tráfico normal, budget_402) + **censo de emisores del fuente** contra `EMISORES_VIGENTES` — un emisor nuevo sin inventariar DEBE ponerlo en rojo con su `archivo:línea` *(enmienda aprobada por el manager 13-ago: la presión de la regla 4 se ejerce por censo y no por limbo — lo no clasificado cae en la clase MORTAL `usage_metadata`, nunca en «sin clase», porque una fila sin predicado es justamente el bug inmortal que la spec vino a cerrar)*.
- [x] T005 [P] Refactor de las constantes locales de `api/audit.py` (estaban en `:36-64` **antes** de este PR; hoy en su lugar hay el bloque que explica de dónde sale el criterio, y el import del clasificador está en `:19`) → clasificador, con test de **paridad exacta** de la vitrina pre/post refactor (dataset sembrado; la vitrina es superficie viva del cliente). Incluye la migración de `~es_licencia()` a `~dice_licencia()` (`:271`) que ordenó el dictamen del 14-ago.
- [x] T006 [P] Fixture de harness «mundo post-017» en `tests/conftest.py` o módulo propio: dropea `tenant_isolation_bootstrap` + conecta con rol NOSUPERUSER creado ad-hoc en la DB de test (Contrato 2, SC-004). Documentar en el docstring que esto es el estado que la 017 activa después.
- [x] T007 Fix del emisor de la cadena: `SessionLocal` pelado → `tenant_context(None, bypass=True)` con la sesión abierta y cerrada DENTRO del bloque; test bajo la fixture T006. *(enmienda aprobada por el manager 13-ago: la firma pide `tenant_id` posicional y el bypass viaja en un `SET LOCAL` que muere con la transacción, no con el `with` — una sesión abierta afuera se lo lleva puesto fuera del bloque; Contrato 2 (a) y (c).)*

**Checkpoint**: PR Foundational (clasificador + vitrina + fixture + emisor). Codex-gate. Merge del manager antes de arrancar US1.

## Phase 3: US1 — La promesa del día 91 se cumple (P1) 🎯 MVP

- [ ] T008 **PARCIAL — el código NO viaja en el PR Foundational: entra con el PR de US1.** Las referencias `purger.py:NNN` de abajo son de la rama de trabajo, no de `main`; hasta que ese PR entre, el fichero no existe en el árbol. — `purger.py`: corrida por clase. **HECHO**: cutoff contra reloj de DB, DELETE por lotes (`BATCH_SIZE`, pausa entre lotes), ventana horaria + TZ (`en_ventana`), `purgar_clase`, `run_once`, simulacro `BASA_PURGE_DRY_RUN`, idempotencia por diseño, el contador de residuo `filas_no_clasificadas` (dictamen 14-ago, punto c) y **el piso del plazo**: `PLAZO_MINIMO_DIAS = 1` (`purger.py:536`), aplicado en `_plazo_en_dias` (`:579`) y en `cutoff_de_residuo` (`:692`), que rechaza todo plazo `< 1` **abortando esa clase** (no la corrida) antes de resolver el cutoff y también en simulacro — dictamen del manager 14-ago, «el endpoint valida para dar buen error, el purgador valida para no destruir». Es defensa del purgador, NO de la spec: qué tapa y qué NO tapa está en T011, y el que trae los mínimos por clase es T015. **FALTA**: `--run-now` como flag de CLI — hoy es un kwarg de `run_once`/`purgar_clase` y el módulo **no tiene `__main__` ni `argparse`**, así que `python -m src.services.retention.purger --run-now` no ejecuta nada. El quickstart §1 quedó reescrito con la invocación que sí corre; el CLI se cierra en el PR de US1 y esa sección se actualiza con él.
- [ ] T009 [US1] FR-004: al purgar `prompt_content`, `UPDATE human_reviews SET response_text=NULL` para reviews vencidas (fila persiste); mismo lote/ventana.
- [ ] T010 [US1] FR-005: escritura de `purge_log` (JSONB, cap 50 corridas/clase) + fila resumen `config_audit` en `audit_logs` por corrida — todo metadata-only, vía Contrato 2.
- [ ] T011 [US1] **BLOQUEADA POR T015 — sello del manager, 14-ago.** `retention_scheduler.py`: thread daemon (patrón `reconcile.start_scheduler`, `reconcile.py:268-297`, con el `_loop` en `:285` y el `Thread(daemon=True)` en `:294`; el trío start/stop/running llega hasta `:309`), wiring en startup del backend, `BASA_PURGE_ENABLED` maestro.
  **Por qué está bloqueada, y no es una precaución genérica**: hoy `PUT /compliance/retention` no valida rangos — el schema declara `retention_days: int` sin cota (`compliance.py:107`) y el único piso del handler (`update_retention`, `:328`) es `config_audit < 365 → 422` (`:334`), así que para las otras tres clases entra **cualquier entero** y el endpoint devuelve 200.
  **Lo que YA quedó tapado, y por eso este motivo se reescribió** *(el piso del purgador aterrizó el 14-ago, en la misma ronda que este sello)*: `PLAZO_MINIMO_DIAS = 1` (`purger.py:536`) se aplica en `_plazo_en_dias` (`:554`, chequeo en `:579`) — el único paso por el que pasa el plazo de una clase — antes de restar el cutoff y antes de que ninguna consulta toque `audit_logs`; el umbral del contador de residuo tiene el mismo piso (`cutoff_de_residuo`, `:667`, chequeo en `:692`). Con `retention_days` en `0` o en `-30` la clase **aborta sin borrar ni contar**: `result: error`, `cutoff: None`, `rows_deleted: 0`, las otras tres siguen purgando, y el simulacro tampoco devuelve un número. Medido en verde por `tests/integration/test_retention_piso_plazo.py::test_un_plazo_no_positivo_no_borra_ni_una_fila` (`:245`, parametrizado en `0` y `-30`). **El escenario `0`/`-30` ya no sostiene esta dependencia.**
  **El riesgo que QUEDA, y que sí la sostiene**: el piso sólo defiende el presente y el futuro — `1` es un plazo **válido** y el purgador lo ejecuta sin chistar. Un `retention_days=1` tecleado en el PUT (que lo acepta con 200) pone el cutoff en `ahora − 1 día` y se lleva la clase entera salvo las últimas 24 h, irreversiblemente. No es una hipótesis: es lo que asserta hoy, en verde, `test_el_plazo_del_borde_purga_normalmente` (`:395`) — con la política en `PLAZO_MINIMO_DIAS` siembra una fila de 2 días y verifica que muere (`rows_deleted == 1`), y sólo sobrevive la de hoy. O sea que el piso baja el daño de «vaciar la auditoría» a «vaciar la auditoría menos el último día», y ahí se queda: el purgador no tiene cómo distinguir un `1` tecleado de un `1` querido, porque esa distinción es un mínimo POR CLASE y hoy no hay ninguno legible por código (§«Por qué el piso es `> 0`» de `purger.py`). El que sí puede hacerla es T015 — mínimos por clase y pisos del tier, 422 con el piso en el detalle. Encender el scheduler antes deja el runbook de la sede a un typo de perder toda la auditoría menos el último día, de madrugada y sin nadie mirando. T015 primero; T011 después.
- [ ] T012 [US1] `tests/integration/test_retention_purge.py`: SC-001 completo (200 días sintéticos → cero vencidas purgables, cero no-vencidas afectadas, license intactas, `verify_chain` + true-up verdes) + edge cases: plazo acortado en caliente, cadena intercalada, corrida interrumpida (idempotencia), reloj de DB.
- [ ] T013 [US1] Seed de test `tests/seeds/seed_retention_dataset.py` (usado por T012 y quickstart §1).
- [ ] T014 [US1] Los tests de purga corren TAMBIÉN bajo la fixture post-017 (`test_purge_post017.py`) — SC-004.

**Checkpoint**: PR US1. **STOP & VALIDATE**: quickstart §1-§3 en vivo sobre compose antes de pedir gate. Este PR ES el MVP de la spec.

## Phase 4: US2 — Tiers de enforcement (P2)

- [ ] T015 [US2] FR-007: validación de rangos en `PUT /compliance/retention` (`compliance.py:327-341`): mínimos por clase + pisos/topes del tier vigente (tabla research.md D7); fuera de rango → 422 con detalle del piso; test por clase y por tier. **No sustituye al piso del purgador** (`PLAZO_MINIMO_DIAS`, T008): el endpoint valida para dar buen error, el purgador valida para no destruir, y el segundo sigue siendo el SUELO cuando el plazo entre por otra fuente (036) o por SQL a mano. Los mínimos por clase se apilan ENCIMA de `>= 1`; el test del borde (`test_retention_piso_plazo.py:395`) fija que el purgador no invente un piso más alto que el de la fuente.
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

**Dependencias**: T003→T004→T005; T006→T007→(T012,T014); **T015→T011** *(sello del manager 14-ago: el scheduler NO se enciende antes que la validación de rangos — el motivo medido está en la propia T011; es la única dependencia que cruza de US2 a US1 y por eso rompe el orden de fases)*; US1 completa antes de US2 (los pisos del tier validan contra clases del clasificador); T019 tras US1 mergeada. T022 es independiente de todo.

**Estado de los checkboxes (14-ago)**: T001-T007 implementados y verdes (130 tests en `test_retention_classifier.py`, `test_retention_skeleton.py`, `test_retention_purga_ventana.py`, `test_audit_paridad_clasificador.py`, `test_audit_filtro_estado.py`, `test_identidad_batch_post017.py`). T008 va sin marcar a propósito: le falta el CLI, y está dicho en su línea. T009 en adelante, sin empezar.
