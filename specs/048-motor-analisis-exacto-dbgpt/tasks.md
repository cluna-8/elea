---

description: "Task list — spec 048: Motor de análisis exacto de datos (DB-GPT)"

---

# Tasks: Motor de análisis exacto de datos (DB-GPT) para Eleia Hub

**Input**: Design documents from `specs/048-motor-analisis-exacto-dbgpt/` (plan.md, spec.md,
research.md, data-model.md, contracts/, quickstart.md)

**Numeración**: continúa la secuencia global de tasks del repo (última usada: T069, spec 044).

**Tests**: se piden explícitamente (Development Workflow #3 de la constitución: "todo cambio con
lógica no trivial lleva tests automatizados").

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup (Shared Infrastructure)

- [ ] T070 Crear migración `020_workspace_kind_exact_analysis.py` en `backend/alembic/versions/`:
      `ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS kind VARCHAR NOT NULL DEFAULT 'rag'` + CHECK
      `kind IN ('rag','exact_analysis')` (idempotente, mismo criterio que 018/019 — ver
      data-model.md)
- [ ] T071 [P] Agregar servicio `exact-analysis-engine` a `docker-compose.yml`: imagen
      `eosphorosai/dbgpt-openai` pinneada por digest, `expose` (NUNCA `ports`), red Docker nueva
      `exact-analysis-net`, volumen dedicado para el estado de DB-GPT (SQLite+Chroma) — mitiga
      FR-002/CVE-2026-80104 (ver research.md R4)
- [ ] T072 [P] Agregar `backend` a la red `exact-analysis-net` en `docker-compose.yml` (único
      servicio con esa doble membresía de red)

**Checkpoint**: el contenedor levanta, sin puertos publicados, solo alcanzable desde `backend`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: ningún User Story puede empezar hasta cerrar esta fase.

- [ ] T073 Script `backend/scripts/bootstrap_dbgpt_service_key.py`: crea el usuario
      `svc.dbgpt-excel` (`account_type='service'`) y su `APIKey` (`tool_type='servicio'`,
      `can_act_on_behalf=True`) — mismo patrón que las llaves de AnythingLLM (data-model.md)
- [ ] T074 **Descubrir el contrato real de DB-GPT (research.md R2, OBLIGATORIO antes de T077)**:
      levantar `exact-analysis-engine` local, inspeccionar con las herramientas de red del
      navegador (Browser pane) los llamados reales de su web UI al subir una planilla y preguntar
      — documentar rutas/payloads/forma de respuesta en
      `specs/048-motor-analisis-exacto-dbgpt/contracts/02-dbgpt-real-api.md`. NO adivinar el
      contrato.
- [ ] T075 Configurar el `.toml`/env de DB-GPT (`LLM_MODEL_PROVIDER=proxy/openai`,
      `OPENAI_API_BASE=http://engine:4000/v1`, `OPENAI_API_KEY=<llave de svc.dbgpt-excel>`,
      `LLM_MODEL_NAME=<deployment real del catálogo>`) — verificado contra research.md R1
- [ ] T076 Router base `backend/src/api/exact_analysis.py`: prefijo `/exact-analysis`, `Depends
      (get_current_user)` fail-closed en todas las rutas (mismo criterio que el resto de la API)
- [ ] T077 [P] Servicio `backend/src/services/exact_analysis_service.py`: cliente HTTP hacia
      `exact-analysis-engine` usando el contrato descubierto en T074 (httpx, mismo patrón que
      otras integraciones del backend)

**Checkpoint**: infraestructura y contrato real confirmados — los User Stories pueden empezar.

---

## Phase 3: User Story 1 - El motor responde con la identidad y el costo de la persona real (Priority: P1)

**Goal**: cada pregunta de análisis exacto atribuye modelo/costo a la persona real, vía el motor
interno de Eleia — nunca una credencial ni cuenta de servicio anónima.

**Independent Test**: preguntar algo que dispare una llamada de modelo desde DB-GPT y confirmar en
Costos → "Gasto por usuario" que aparece bajo la persona real, con un modelo del catálogo.

### Tests for User Story 1

- [ ] T078 [P] [US1] Contract test en
      `backend/tests/contract/test_exact_analysis_atribucion_costo.py`: con un doble HTTP del
      motor DB-GPT, confirmar que la llamada saliente hacia LiteLLM lleva el header "en nombre de"
      con el id de la persona real (no de `svc.dbgpt-excel`)
- [ ] T079 [P] [US1] Integration test en
      `backend/tests/integration/test_exact_analysis_costos_by_user.py`: una pregunta completa deja
      una fila en `AuditLog` con `acted_for_user_id` = persona real, visible en
      `GET /costs/summary` → `by_user` (reusa el patrón de
      `test_costs_by_user_attribution_043.py`)

### Implementation for User Story 1

- [ ] T080 [US1] Endpoint `POST /api/v1/exact-analysis/workspaces/{id}/query` en
      `exact_analysis.py`: valida membresía (403), valida presupuesto (402, ANTES de reenviar —
      FR-008), reenvía a `exact_analysis_service.py` con el header de atribución
- [ ] T081 [US1] `exact_analysis_service.py`: agrega el header "en nombre de" (mismo mecanismo que
      `X-Guardian-Acting-User`, contrato 2 de la 043) a la llamada hacia DB-GPT/hacia LiteLLM
      según dónde corresponda según el contrato real descubierto en T074
- [ ] T082 [US1] Restringir `LLM_MODEL_NAME` de DB-GPT al catálogo real de Eleia — ningún modelo
      fuera de los deployments configurados en `litellm/config.yaml` (FR de "solo puede elegir
      entre los del catálogo")

**Checkpoint**: User Story 1 funciona y se prueba de forma independiente.

---

## Phase 4: User Story 2 - Aislamiento entre personas, cruce dentro del mismo espacio (Priority: P1)

**Goal**: cada persona solo analiza SUS archivos (cruzados entre sí), nunca los de otra; DB-GPT
nunca alcanzable salvo desde el backend.

**Independent Test**: dos personas, dos espacios, ninguna pregunta de una ve datos de la otra; dos
planillas del mismo espacio SÍ se cruzan en una pregunta.

### Tests for User Story 2

- [ ] T083 [P] [US2] Integration test en
      `backend/tests/integration/test_exact_analysis_aislamiento.py`: dos personas, dos espacios,
      confirma 403 en acceso cruzado y respuesta correcta en cruce dentro del mismo espacio (mismo
      patrón que `test_workspaces_api_043.py`)
- [ ] T084 [P] [US2] Test de red (script bash o pytest con `docker network inspect`/intento de
      conexión desde un contenedor de otra red) en
      `backend/tests/integration/test_exact_analysis_red_aislada.py` — confirma SC-003 (0 puertos
      alcanzables desde fuera)

### Implementation for User Story 2

- [ ] T085 [US2] Endpoint `POST /api/v1/exact-analysis/workspaces` (crea `Workspace
      kind='exact_analysis'`, reusa `workspace_service.py` de la 043 con el nuevo `kind`)
- [ ] T086 [US2] Endpoint `POST /api/v1/exact-analysis/workspaces/{id}/files` — valida membresía,
      valida extensión tabular (`.csv`/`.xlsx`/`.xls`), reenvía a DB-GPT con el `file_id` scopeado
      al espacio
- [ ] T087 [US2] `exact_analysis_service.py`: soporte de pregunta que referencia múltiples
      archivos del mismo espacio (FR-010, cierra el hallazgo #1 de la investigación — DB-GPT solo
      soporta un archivo nativo, así que esto puede requerir cargar ambos en la misma sesión/
      dataset de DB-GPT según lo que confirme T074)

**Checkpoint**: User Stories 1 y 2 funcionan juntas de forma independiente.

---

## Phase 5: User Story 3 - El enmascarado vigente protege lo que entra a DB-GPT (Priority: P1)

**Goal**: ningún dato personal llega en claro a DB-GPT; el SQL ejecutado se audita como evidencia
de solo-lectura.

**Independent Test**: subir una planilla con una columna de DNI/nombre, preguntar algo que no la
involucre directamente, confirmar por log que la columna protegida no viajó en claro.

### Tests for User Story 3

- [ ] T088 [P] [US3] Contract test en
      `backend/tests/contract/test_exact_analysis_enmascarado.py`: la subida de una planilla con
      PII pasa por el mismo pipeline de enmascarado que el resto del Hub antes de llegar al doble
      HTTP de DB-GPT
- [ ] T089 [P] [US3] Contract test en
      `backend/tests/contract/test_exact_analysis_sql_readonly.py`: `sqlglot` rechaza/marca
      cualquier SQL auditado que no sea `SELECT`/`WITH` (research.md R3)

### Implementation for User Story 3

- [ ] T090 [US3] `exact_analysis_service.py`: enmascarar la planilla (reusar el pipeline existente
      de `client/server.js`/backend, según dónde viva la subida) ANTES de mandarla a T086
- [ ] T091 [US3] Auditoría: guardar el SQL ejecutado (si el contrato real de T074 lo expone) en
      `AuditLog`, `surface='exact_analysis'` (agregar al vocabulario `_SURFACES_BACKFILL` si
      corresponde)
- [ ] T092 [US3] Validación `sqlglot` sobre el SQL auditado — alarma/log si aparece algo que no
      sea solo-lectura (defensa en capas, no bloqueo garantizado — ver research.md R3)

**Checkpoint**: los 3 User Stories P1 funcionan juntos, de forma independiente entre sí.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T093 Mensajes de error neutros en todo el flujo (sin nombrar "DB-GPT") — motor caído,
      timeout, 502 (FR-009, mismo estándar del bug ya corregido en el chat RAG, CHANGELOG 044 §14)
- [ ] T094 [P] `elea-installer/docker-compose.yml`: mismo servicio `exact-analysis-engine` para
      producción, con la misma restricción de red
- [ ] T095 [P] **Sitio de docs de producto (OBLIGATORIO, DoD)**: actualizar `docs/docs/**` con el
      modo de análisis exacto (curado marca-neutro — nunca "DB-GPT" en la doc pública, mismo
      criterio que el resto del producto) y correr `make -C deploy check-docs`
- [ ] T096 Correr `quickstart.md` completo contra un despliegue local real — los 8 pasos, cada uno
      mapea a un `SC-00X` de `spec.md`
- [ ] T097 Regresión completa del backend (`pytest`) — confirmar 0 regresiones sobre el baseline
      conocido (9 fallos preexistentes sin relación)

---

## Dependencies & Execution Order

- **Setup (T070-T072)**: sin dependencias, arranca de inmediato.
- **Foundational (T073-T077)**: depende de Setup. **T074 (descubrir el contrato real) bloquea
  T077 y todo lo que dependa del contrato de DB-GPT** — es la tarea de mayor riesgo/incertidumbre
  de todo el plan, se hace primero dentro de esta fase.
- **User Story 1 (T078-T082)**: depende de Foundational. Sin dependencia de US2/US3.
- **User Story 2 (T083-T087)**: depende de Foundational. Puede correr en paralelo con US1 (archivos
  distintos), aunque comparten `exact_analysis_service.py` — coordinar si se paraleliza.
- **User Story 3 (T088-T092)**: depende de Foundational. Mismo criterio que US2.
- **Polish (T093-T097)**: depende de que los 3 User Stories estén completos.

## Implementation Strategy

**MVP**: Setup + Foundational + User Story 1 — ya demuestra el pedido explícito de esta ronda
("que use a Eleia para los modelos y el costo") de punta a punta, aunque sin aislamiento
multi-persona probado todavía (eso lo cierra US2) ni la garantía de enmascarado (US3). Dado que
los tres User Stories son P1, la entrega completa (no solo el MVP de US1) es la meta antes de
considerar esta spec "lista para probar" en el sentido que pidió el dueño del producto.
