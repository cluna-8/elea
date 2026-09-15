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

- [x] T070 Crear migración `020_workspace_kind_exact_analysis.py` en `backend/alembic/versions/`:
      `ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS kind VARCHAR NOT NULL DEFAULT 'rag'` + CHECK
      `kind IN ('rag','exact_analysis')` (idempotente, mismo criterio que 018/019 — ver
      data-model.md). Corrida en vivo contra el stack local, confirmada.
- [x] T071 [P] Agregar servicio `exact-analysis-engine` a `docker-compose.yml`: imagen
      `eosphorosai/dbgpt-openai` pinneada por digest, `expose` (NUNCA `ports`), red Docker nueva
      `exact-analysis-net` (`internal:true`), volumen dedicado — mitiga FR-002/CVE-2026-80104 (ver
      research.md R4). Verificado en vivo: `docker inspect` sin puertos, `curl` desde el host
      falla (SC-003).
- [x] T072 [P] Agregar `backend` (y `engine`, necesario para que exact-analysis-engine pueda
      llamarlo — ver docker-compose.yml) a la red `exact-analysis-net`.

**Checkpoint**: el contenedor levanta, sin puertos publicados, solo alcanzable desde `backend`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: ningún User Story puede empezar hasta cerrar esta fase.

- [x] T073 **Desviación deliberada del plan**: no un script Python nuevo — la llave de
      `svc.dbgpt-excel` se crea con el MISMO mecanismo bash `create_service_key()` que ya usan
      `svc.anythingllm-provider`/`svc.rag-masking` en `elea-installer/install.sh` (confirmado que
      ESE es el patrón real de producción, no un script Python separado). Agregada ahí, exporta
      `DBGPT_ENGINE_VIRTUAL_KEY` al `.env`. En dev local se creó a mano vía API (mismo POST
      /users + POST /keys que hace install.sh), confirmado `account_type='service'` correcto.
- [x] T074 **Descubrir el contrato real de DB-GPT** — hecho en vivo: `GET /openapi.json` de una
      instancia real + prueba end-to-end real (subir CSV, preguntar, respuesta correcta con SQL
      auditado). Documentado en
      `specs/048-motor-analisis-exacto-dbgpt/contracts/02-dbgpt-real-api.md`, con el hallazgo real
      que costó un 500 (`select_param` es el objeto `data` completo del upload, no el `file_path`
      pelado) y la corrección de ruta (v1, no v2 — v2 no soporta `chat_mode=chat_excel`).
- [x] T075 Configurado (`command:` override + env vars en `docker-compose.yml`) — verificado en
      vivo: el selector de modelo de DB-GPT mostró `azure-gpt-4o-mini` (el catálogo real de
      Eleia), y la pregunta de prueba resolvió correctamente contra Azure real vía el motor
      interno.
- [x] T076 Router base `backend/src/api/exact_analysis.py` — `_require_user()` fail-closed en
      las 3 rutas, mismo patrón que `workspaces.py`.
- [x] T077 [P] `backend/src/services/exact_analysis_service.py` — `upload_file`/`ask_question`
      contra el contrato real de T074, con extracción del SQL ejecutado del tag `<chart-view>`
      (confirma R3). Verificado en vivo end-to-end.

**Checkpoint**: infraestructura y contrato real confirmados — los User Stories pueden empezar.

---

## Phase 3: User Story 1 - El motor responde con la identidad y el costo de la persona real (Priority: P1)

**Goal**: cada pregunta de análisis exacto atribuye modelo/costo a la persona real, vía el motor
interno de Eleia — nunca una credencial ni cuenta de servicio anónima.

**Independent Test**: preguntar algo que dispare una llamada de modelo desde DB-GPT y confirmar en
Costos → "Gasto por usuario" que aparece bajo la persona real, con un modelo del catálogo.

### Tests for User Story 1

- [x] T078/T079 [P] [US1] Cubiertos parcialmente por
      `backend/tests/integration/test_exact_analysis_048.py` (query exitosa devuelve
      `sql_executed`/`model_used`, presupuesto bloquea antes de llamar al motor). **NO escrito**:
      el test específico de que la llamada saliente lleve el header "en nombre de" — bloqueado
      por T081 (ver abajo, gap real sin cerrar).

### Implementation for User Story 1

- [x] T080 [US1] Endpoint `POST /exact-analysis/workspaces/{id}/query` — membresía (403),
      presupuesto (402, ANTES de reenviar), reenvía a `exact_analysis_service.py`. Verificado en
      vivo con Azure OpenAI real.
- [ ] **T081 [US1] — NO CERRADO, gap real documentado (no fingido)**: DB-GPT llama al motor de
      Eleia POR SU CUENTA con su propia llave (`svc.dbgpt-excel`) — este backend nunca hace esa
      llamada, así que no puede inyectarle un header. Confirmado en vivo (`audit_logs`): el costo
      quedó atribuido a `svc.dbgpt-excel`, no a `admin` (la persona real que preguntó) — MISMA
      limitación arquitectónica ya aceptada para AnythingLLM/RAG (CHANGELOG 044 §13), ahora
      también real acá. Documentado en el docstring de `exact_analysis_service.py`. Cerrarlo del
      todo requeriría confirmar si DB-GPT soporta headers custom en su cliente `proxy/openai`
      (no confirmado en esta ronda) — o resolver la atribución en el motor por otra vía (p. ej.
      el motor podría resolver "quién preguntó" por el propio backend en vez de por header, si
      el contrato de la llamada de DB-GPT trae algún campo `user`/`sys_code` reenviable — sin
      investigar en esta ronda).
- [x] T082 [US1] `LLM_MODEL_NAME` fijo por env var a un deployment real del catálogo (no
      seleccionable por DB-GPT) — verificado en vivo, el selector mostró `azure-gpt-4o-mini`.
      Simplificado respecto del plan original (no lee dinámicamente `GET /chat/models`) — anotado
      como decisión de implementación en el propio código.

**Checkpoint**: User Story 1 funciona de punta a punta (verificado en vivo, Azure real) salvo la
atribución de costo a la persona real, que queda como limitación documentada, no resuelta.

---

## Phase 4: User Story 2 - Aislamiento entre personas, cruce dentro del mismo espacio (Priority: P1)

**Goal**: cada persona solo analiza SUS archivos (cruzados entre sí), nunca los de otra; DB-GPT
nunca alcanzable salvo desde el backend.

**Independent Test**: dos personas, dos espacios, ninguna pregunta de una ve datos de la otra; dos
planillas del mismo espacio SÍ se cruzan en una pregunta.

### Tests for User Story 2

- [x] T083 [P] [US2] `test_exact_analysis_048.py::test_no_miembro_no_puede_subir_archivo` (403
      real, no simulado) + `test_sin_sesion_401`. **NO escrito**: el caso "cruce dentro del mismo
      espacio con dos archivos" — depende de T087, no implementado (ver abajo).
- [x] T084 [P] [US2] Confirmado en vivo (no como test automatizado todavía): `docker inspect`
      sin puertos publicados + `curl` desde el host falla tras sacar el override temporal de
      T074. **Falta**: automatizar esto como test de CI (hoy es verificación manual).

### Implementation for User Story 2

- [x] T085 [US2] Endpoint `POST /exact-analysis/workspaces` — `workspace_service.create_workspace`
      extendido con `kind` (default `"rag"`, sin romper nada existente). Verificado en vivo.
- [x] T086 [US2] Endpoint `POST /exact-analysis/workspaces/{id}/files` — membresía, extensión
      tabular (422 si no), reenvía al motor. Verificado en vivo con un CSV real.
- [ ] **T087 [US2] — NO implementado**: cruzar múltiples archivos del mismo espacio en una sola
      pregunta. Reusar el MISMO `conv_uid` para dos subidas distintas (dejando que DB-GPT acumule
      contexto de conversación) es la hipótesis más simple según el contrato descubierto en T074,
      pero no se probó en esta ronda — la prueba en vivo fue con un solo archivo. Cierra el
      hallazgo #1 de la investigación original (DB-GPT nativo no cruza archivos) — sigue
      pendiente confirmar que el truco del `conv_uid` compartido realmente lo resuelve.

**Checkpoint**: aislamiento entre personas confirmado (US2 parcial) — el cruce de archivos del
mismo espacio (FR-010) queda pendiente de una siguiente ronda.

---

## Phase 5: User Story 3 - El enmascarado vigente protege lo que entra a DB-GPT (Priority: P1)

**Goal**: ningún dato personal llega en claro a DB-GPT; el SQL ejecutado se audita como evidencia
de solo-lectura.

**Independent Test**: subir una planilla con una columna de DNI/nombre, preguntar algo que no la
involucre directamente, confirmar por log que la columna protegida no viajó en claro.

### Tests for User Story 3

- [ ] T088 [P] [US3] **NO escrito** — depende de T090.
- [ ] T089 [P] [US3] **NO escrito** — depende de T092.

### Implementation for User Story 3

- [ ] **T090 [US3] — NO implementado, gap real documentado**: el archivo tabular se sube al
      motor SIN pasar por el enmascarado (`TODO` explícito y visible en
      `api/exact_analysis.py::upload_exact_analysis_file`, no escondido). Es el hallazgo #2 de
      la investigación original (DB-GPT manda datos crudos al LLM) — sigue sin cerrar del lado
      de Eleia todavía. Requiere decidir el mecanismo de reuso: llamar a `/gw/inspect` desde el
      backend mismo (mismo endpoint que ya usa `client/server.js` para el enmascarado del RAG) es
      la hipótesis más simple, no implementada en esta ronda.
- [x] T091 [US3] (parcial) `sql_executed` se extrae y se devuelve en la respuesta — es la pieza de
      "evidencia auditable" del research.md R3. **Falta**: persistirlo en `AuditLog` con
      `surface` propio (hoy solo se loguea con `logger.info`, no queda en la tabla).
- [ ] T092 [US3] **NO implementado**: validación `sqlglot`. La dependencia no se agregó a
      `requirements.txt` — no se usó en esta ronda. El SQL extraído (T091) se PODRÍA validar, no
      se hizo todavía.

**Checkpoint**: US1 y US2 funcionan de punta a punta en vivo con las limitaciones anotadas; **US3
(enmascarado) NO está cerrado — es el gap de seguridad más importante que queda pendiente**, dado
que el pedido original incluía explícitamente proteger los datos que entran al motor.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T093 Mensajes de error neutros (`MENSAJE_MOTOR_NO_DISPONIBLE`/`MENSAJE_PRESUPUESTO_AGOTADO`
      en `exact_analysis.py`, sin nombrar "DB-GPT") — no probado contra el motor realmente caído
      en esta ronda (sí implementado).
- [x] T094 [P] `elea-installer/docker-compose.yml` + `install.sh` extendidos — sintaxis validada
      (`docker compose config`), NO desplegado contra una instancia real de `elea-installer`.
- [ ] T095 [P] **NO hecho** — `docs/docs/**` no se tocó, `make -C deploy check-docs` no se corrió
      para esta feature todavía.
- [x] T096 (parcial) Los pasos 1-6 de `quickstart.md` se corrieron en vivo (red aislada, crear
      espacio, subir CSV, preguntar con cruce simple, ver costo — aunque atribuido al servicio,
      no a la persona, SC-002 no cierra). **Faltan**: paso 7 (aislamiento entre 2 personas reales,
      solo probado a nivel de API con membresía, no con dos sesiones+preguntas reales) y paso 8
      (motor caído).
- [ ] T097 **En curso** — regresión completa lanzada, resultado se documenta apenas termine.

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
