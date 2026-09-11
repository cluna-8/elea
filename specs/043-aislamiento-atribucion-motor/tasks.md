# Tasks: Aislamiento por usuario, atribución de gasto y enmascarado determinista (motor + backend + instalador)

**Input**: Design documents from `specs/043-aislamiento-atribucion-motor/`
(`plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`, `diagnostico.md`)

**Marca**: en este repo (`cluna-8/elea`) todo lo de cara al cliente es **Eleia** — nunca "Sentinel".
El producto/motor base compartido (código interno, no personalizado por cliente) se nombra
"Guardian" a secas. Ver `.claude/.../memory/branding-nomenclatura.md` si hace falta el detalle.

**Tests**: incluidos — el workflow del proyecto (`.specify/memory/constitution.md`, Development
Workflow #3) exige tests automatizados para todo cambio no trivial, y la reversibilidad del
enmascarado + los hooks del motor llevan tests de contrato. Se extiende la suite existente
(`backend/tests/{unit,contract,integration}`), no se reemplaza.

**Organization**: por historia de usuario (US1-US6 de `spec.md`), en orden de prioridad P1→P2.
Repos/carpetas tocadas: `backend/`, `litellm/extensions/`, `elea-installer/`. **NO se toca
`frontend/` ni `client/`** (son la spec 044) — donde un contrato menciona algo de esos repos
(p. ej. contrato 6, renombrar `litellm_params` en `frontend/src/services/api.ts`), es tarea de la
044, no de acá.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede correr en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: a qué historia de usuario pertenece (US1-US6)

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Crear el esqueleto de la migración Alembic nueva (upgrade/downgrade vacíos) en `backend/alembic/versions/018_workspaces_service_accounts_audit_surface.py`, encadenada al `down_revision` de `017_sso_providers.py`
- [X] T002 [P] Agregar el valor `"servicio"` al enum/constante `SURFACES` existente en `litellm/extensions/sentinel_governance.py`
- [X] T003 [P] Agregar fixtures de prueba (usuario `service`, workspace, membership) a `backend/tests/conftest.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: esquema y modelos que bloquean **US1, US2, US4 y US5**. **US3 y US6 NO dependen de
esta fase** (son cambios de código sin migración) y pueden empezar apenas termine el Setup — ver
nota en Dependencies.

**⚠️ CRITICAL**: US1/US2/US4/US5 no pueden empezar hasta que esta fase esté completa.

- [X] T004 Completar la migración `018_...py`: `CREATE TABLE workspaces, workspace_memberships, workspace_threads` según `data-model.md` (`backend/alembic/versions/018_workspaces_service_accounts_audit_surface.py`, depende de T001)
- [X] T005 En la misma migración: `ALTER TABLE users ADD account_type, deactivated_at, deactivated_reason`; `ALTER TABLE audit_logs ADD acted_for_user_id, surface, event_type, document_group_id`; `ALTER TABLE api_keys ADD can_act_on_behalf` — todas nullable/con default, sin downtime (`backend/alembic/versions/018_...py`, depende de T004)
- [X] T006 En la misma migración: backfill de una pasada — `account_type='service'` para `username LIKE 'svc.%'`; `event_type='license_evidence'` donde `model='license'`; `surface=model, model=NULL` donde `model` esté en `SURFACES` (`backend/alembic/versions/018_...py`, depende de T005; ver R5 de `research.md` para la decisión de `NULL` vs. sentinel value)
- [X] T007 Crear los modelos SQLAlchemy `Workspace`, `WorkspaceMembership`, `WorkspaceThread` en `backend/src/models/workspace.py` (según `data-model.md`)
- [X] T008 [P] Agregar `account_type`, `deactivated_at`, `deactivated_reason` al modelo `User` en `backend/src/models/user.py`
- [X] T009 [P] Agregar `acted_for_user_id`, `surface`, `event_type`, `document_group_id` al modelo `AuditLog` en `backend/src/models/audit.py`
- [X] T010 [P] Agregar `can_act_on_behalf` al modelo de `APIKey`/`Connection` en `backend/src/models/budget.py`
- [X] T011 Crear schemas Pydantic `WorkspaceOut`, `WorkspaceMembershipIn/Out`, `WorkspaceThreadOut` en `backend/src/schemas/workspace.py` (depende de T007)
- [X] T012 Aplicar la migración contra la base local (`alembic upgrade head`) y verificar que el backfill es idempotente corriéndolo dos veces sin error (depende de T004-T006)

**Checkpoint**: esquema y modelos listos — US1, US2, US4, US5 pueden arrancar. US3 y US6 ya podían arrancar desde el Setup.

---

## Phase 3: User Story 1 - Espacios de trabajo con miembros (Priority: P1) 🎯 MVP

**Goal**: cada usuario ve y opera solo los espacios de los que es miembro; los hilos son privados por usuario; ninguna operación de espacio/hilo funciona sin verificación en el backend.

**Independent Test**: dos usuarios en dos sesiones — A crea un espacio y sube un documento; B no lo ve ni puede leer su historial aunque conozca el id; A lo agrega como miembro; B lo ve y sus hilos no se cruzan con los de A. Ver `quickstart.md` §1.

### Tests for User Story 1

- [X] T013 [P] [US1] Contract test de `GET/POST /workspaces`, `GET /workspaces/{id}`, members CRUD y `transfer-owner` (200/401/403/409 según contrato 1) en `backend/tests/contract/test_workspaces_contract.py`
- [X] T014 [P] [US1] Integration test: acceso cruzado denegado + alta de miembro + hilos privados por usuario en `backend/tests/integration/test_workspace_isolation.py`

### Implementation for User Story 1

- [X] T015 [US1] Implementar `workspace_service.py`: `list_for_user`, `get_with_access_check`, `add_member`, `remove_member`, `transfer_owner` en `backend/src/services/workspace_service.py` (depende de T007, T011)
- [X] T016 [US1] Implementar `sync_existing_workspaces()` (backfill de instalaciones existentes: todo `engine_slug` que AnythingLLM ya tenga y el backend no conozca → `Workspace(status='unassigned')`, idempotente) en `backend/src/services/workspace_service.py` (depende de T015)
- [X] T017 [US1] Implementar endpoints `GET/POST /workspaces`, `GET /workspaces/{id}`, `GET/POST/DELETE /workspaces/{id}/members`, `PATCH /workspaces/{id}/transfer-owner` en `backend/src/api/workspaces.py` (depende de T015)
- [X] T018 [US1] Implementar endpoints `GET/POST/DELETE /workspaces/{id}/threads` scopeados a `owner_user_id = usuario autenticado`, con caso especial de hilo principal (`engine_thread_slug=NULL`) en `backend/src/api/workspaces.py`
- [X] T019 [US1] Registrar el router de `workspaces.py` en `backend/src/main.py`
- [X] T020 [US1] Auditar los intentos de acceso denegado (sin membresía) — fila de `AuditLog` con identidad del solicitante y recurso, sin contenido — en `backend/src/api/workspaces.py` (FR-005)
- [X] T021 [US1] Fijar la versión de la imagen del motor de documentos (quitar `latest`) en `elea-installer/docker-compose.yml` (FR-007)
- [X] T021b [US1] Quitar el mapeo de puerto del motor de documentos al host en `elea-installer/docker-compose.yml` — verificado 08-sep
- [X] T022 [US1] Correr el guion `quickstart.md` §1 contra un stack local y registrar el resultado en `specs/043-aislamiento-atribucion-motor/CHANGELOG.md` (crear el archivo si no existe)

**Checkpoint**: US1 funcional y testeable de forma independiente — el aislamiento de espacios/hilos ya cierra la fuga prioritaria reportada por Tomás.

---

## Phase 4: User Story 2 - Atribución de gasto y presupuesto aplicado (Priority: P1)

**Goal**: todo pedido hecho por una llave de servicio en nombre de un usuario queda auditado y presupuestado a esa persona; el 402 se evalúa antes de consumir; el enmascarado de un documento entero es una operación, no N filas de "modelo" `chat-ui`.

**Independent Test**: con presupuesto de $1, dos preguntas atribuidas a un usuario final consumen su presupuesto real; la cuarta se rechaza con 402 antes de llamar al proveedor; nada queda bajo las cuentas de servicio. Ver `quickstart.md` §3.

### Tests for User Story 2

- [X] T023 [P] [US2] Contract test de la cabecera `X-Guardian-Acting-User` (aceptada solo con `can_act_on_behalf=true`, mismo `tenant_id`, ignorada/auditada si no) en `backend/tests/contract/test_acting_user_header.py`
- [X] T024 [P] [US2] Contract test de `GET /users/me/budget` (autoservicio, sin sesión de admin) en `backend/tests/contract/test_self_budget.py`
- [X] T025 [P] [US2] Integration test: 402 pre-request + atribución de gasto real a `acted_for_user_id` en `backend/tests/integration/test_attribution_budget.py`

### Implementation for User Story 2

- [X] T026 [US2] Leer y validar `X-Guardian-Acting-User` en `litellm/extensions/custom_auth.py`: solo si la llave tiene `can_act_on_behalf=true` y el `user_id` pertenece al mismo `tenant_id`; si no, ignorar y auditar el intento
- [X] T027 [US2] Propagar `acted_for_user_id` dentro de `sentinel_identity["metadata"]` en `litellm/extensions/custom_auth.py` (depende de T026)
- [X] T028 [US2] Cambiar la firma de `gateway._audit()` para recibir `model`, `surface` y `acted_for_user_id` por separado (ya no `superficie` pisando `model`) en `backend/src/api/gateway.py` (depende de T009)
- [X] T029 [US2] Actualizar `/gw/inspect` para leer `X-Guardian-Acting-User` y el nuevo campo `document_id`/`document_group_id` del body, y pasarlos a `gateway.evaluate_request_policy`/`_audit` en `backend/src/api/inspect.py` (depende de T027, T028)
- [X] T030 [US2] Implementar el gate 402 pre-request evaluando presupuesto de `acted_for_user_id` (o `user_id` si no hay "en nombre de") antes de llamar al proveedor, en `backend/src/api/gateway.py` (cierra la constraint de seguridad #3 de la constitución)
- [X] T031 [US2] Implementar `GET /users/me/budget` (autoservicio) en `backend/src/api/users.py`
- [X] T032 [US2] En `elea-installer/install.sh`, cambiar `create_service_key()` para las dos llaves de servicio: `tool_type="servicio"` (ya no `"chat-ui"`) y `can_act_on_behalf=true`
- [X] T033 [US2] Agregar/actualizar `GET /costs/by-user` para agrupar por `COALESCE(acted_for_user_id, user_id)` en `backend/src/api/costs.py` (depende de T028)
- [X] T034 [US2] Correr `quickstart.md` §3 y registrar el resultado en el `CHANGELOG.md` de la feature

**Checkpoint**: US1 + US2 funcionan juntas — un usuario ve sus espacios Y su gasto real, con presupuesto aplicado.

---

## Phase 5: User Story 3 - Enmascarado determinista por documento (Priority: P1)

**Goal**: el mismo valor recibe el mismo placeholder en todos los chunks de un documento; documentos distintos siguen recibiendo placeholders distintos; sin `document_id`, cero regresión.

**Independent Test**: mismo valor en dos chunks simulados con el mismo `document_id` → mismo placeholder; con `document_id` distinto → placeholder distinto; sin `document_id` → comportamiento actual. Ver `quickstart.md` §2. **No depende de la Fase 2 (Foundational)** — es cambio de código puro en el motor, puede desarrollarse en paralelo desde que termina el Setup.

### Tests for User Story 3

- [X] T035 [P] [US3] Contract test: mismo `document_id` en 2+ chunks → mismo placeholder para el mismo valor en `backend/tests/contract/test_masking_determinism.py`
- [X] T036 [P] [US3] Contract test: sin `document_id` → nonce aleatorio como hoy, sin regresión, en `backend/tests/contract/test_masking_no_regression.py`
- [X] T037 [P] [US3] Contract test: `document_id` distinto para el mismo valor → placeholder distinto (no hay seudónimo entre documentos) en `backend/tests/contract/test_masking_cross_document.py`

### Implementation for User Story 3

- [X] T038 [US3] Aceptar `document_id: Optional[str]` en `mask_body()`/`evaluate_request_policy()` en `litellm/extensions/sentinel_guardian_policy.py`
- [X] T039 [US3] Implementar la derivación HMAC de nonce+índice a partir de `document_id` (por documento, según R4 de `research.md`) en la construcción de `PlaceholderMap`, en `litellm/extensions/sentinel_guardian_policy.py` (depende de T038)
- [X] T040 [US3] Aceptar el campo `document_id` opcional en el body de `POST /gw/inspect` y pasarlo a `gateway.evaluate_request_policy` en `backend/src/api/inspect.py`
- [X] T041 [P] [US3] Test de regresión: gramática del placeholder (`PH_TYPE_RE`, `PLACEHOLDER_TOKEN_RE`, `MAX_CARRY`) y compatibilidad con la bóveda/desenmascarado sin cambios, en `backend/tests/unit/test_policy_unit.py`
- [X] T042 [US3] Correr `quickstart.md` §2 con el CSV real del cliente (o uno equivalente) y registrar el resultado en el `CHANGELOG.md` de la feature

**Checkpoint**: US3 funciona de forma completamente independiente de US1/US2 — puede entregarse aunque las otras no estén listas.

---

## Phase 6: User Story 4 - Vistas de modelos y costos sin ruido de servicio (Priority: P2)

**Goal**: "modelos" muestra solo modelos reales; "usuarios" excluye cuentas de servicio por defecto; ninguna cuenta ocupa asiento de licencia.

**Independent Test**: instalación con las 2 cuentas de servicio y 1 usuario humano — `GET /users` devuelve 1 por defecto, 3 con `include_service=true`; `GET /costs/top-models` no incluye `license` ni `chat-ui`; el conteo de asientos es 1. Ver `quickstart.md` §4.

### Tests for User Story 4

- [X] T043 [P] [US4] Contract test: `GET /users` excluye cuentas de servicio por defecto, las incluye con `?include_service=true` (con `purpose`) en `backend/tests/contract/test_users_service_filter.py`
- [X] T044 [P] [US4] Contract test: `GET /costs/top-models` / desglose de analytics no devuelve `license` ni valores de `SURFACES` en `backend/tests/contract/test_costs_models_filter.py`

### Implementation for User Story 4

- [X] T045 [US4] Actualizar `GET /users` (`backend/src/api/users.py`) con el query param `include_service` (default `false`) y el campo `purpose` en la respuesta para cuentas de servicio
- [X] T046 [US4] Actualizar `count_active_seats()` en `backend/src/licensing/seat_counter.py` para excluir `account_type='service'` y usuarios con `deactivated_at IS NOT NULL`
- [X] T047 [US4] Filtrar `event_type='traffic' AND model IS NOT NULL` en las queries de "modelos"/desglose en `backend/src/api/costs.py` (`top_models`, línea ~135-150) y `backend/src/api/analytics.py` (línea ~219-234) — ya no hace falta excluir `license` a mano, viene resuelto por `event_type`/`surface` (T006)
- [X] T048 [US4] Correr `quickstart.md` §4 y registrar el resultado en el `CHANGELOG.md` de la feature

**Checkpoint**: el panel deja de mostrar `license`/`chat-ui` como modelos y las cuentas de servicio como personas (aunque el panel en sí sea spec 044, esta fase deja los endpoints listos para que lo consuma).

---

## Phase 7: User Story 5 - Ciclo de vida completo de usuarios (Priority: P2)

**Goal**: editar rol/email/nombre/equipo con actualización parcial; dar de baja (revoca llaves, libera asiento, cierra membresías) sin permitir auto-baja ni bajar al último admin.

**Independent Test**: `PATCH` de un solo campo dos veces seguidas, cada una cambia solo lo tocado; `DELETE` de un usuario que era dueño de un espacio lo deja en `unassigned`; el usuario dado de baja no puede autenticar. Ver `quickstart.md` §5.

### Tests for User Story 5

- [X] T049 [P] [US5] Contract test de `PATCH /users/{id}` con actualización parcial (un campo por vez, validación de unicidad) en `backend/tests/contract/test_users_patch.py`
- [X] T050 [P] [US5] Contract test de `DELETE /users/{id}` (baja): 200 caso normal, 409 auto-baja, 409 último admin, en `backend/tests/contract/test_users_delete.py`

### Implementation for User Story 5

- [X] T051 [US5] Agregar schema `UserPatch` (todos los campos opcionales) en `backend/src/schemas/user.py`
- [X] T052 [US5] Implementar `PATCH /users/{id}` con validación de unicidad por `tenant_id` y auditoría de `AUTH_ROLE_CHANGED` cuando cambia `role`, en `backend/src/api/users.py` (depende de T051)
- [X] T053 [US5] Implementar `DELETE /users/{id}`: setea `deactivated_at`, revoca llaves/sesiones, guarda contra auto-baja y contra bajar al último admin activo, en `backend/src/api/users.py` (depende de T008)
- [X] T054 [US5] Implementar el efecto en cascada de la baja sobre `Workspace.owner_user_id`/`status` (→ `unassigned`) en `backend/src/services/workspace_service.py` (depende de T015, T053)
- [X] T055 [US5] Rechazar login y autenticación de llaves para usuarios con `deactivated_at` seteado, con el mismo mensaje 401 que credenciales inválidas, en `backend/src/api/users.py` y `litellm/extensions/custom_auth.py`
- [X] T056 [US5] Correr `quickstart.md` §5 y registrar el resultado en el `CHANGELOG.md` de la feature

**Checkpoint**: el ciclo de vida de usuarios queda completo — la 044 puede exponer editar/desactivar/dar de baja sin tocar el backend.

---

## Phase 8: User Story 6 - Ningún nombre de motor ni proveedor de cara al cliente (Priority: P2)

**Goal**: mensajes de error, API pública, documentación generada y nombres sembrados quedan sin nombres de motor/proveedor en ambos planos (chat interno y `/gw`). **No depende de la Fase 2** — es cambio de código puro, puede desarrollarse en paralelo desde el Setup.

**Independent Test**: un error del motor en el plano `/gw` llega sin nombre de motor/proveedor; el OpenAPI generado no lleva `litellm_params`; el guardián NLP sembrado tiene nombre neutro. Ver `quickstart.md` §6.

### Tests for User Story 6

- [X] T057 [P] [US6] Test de regresión: recorre el OpenAPI generado y los nombres de guardianes buscando términos prohibidos (`litellm`, `anythingllm`, `presidio`), con lista de excepciones explícita, en `backend/tests/contract/test_branding_neutral.py`

### Implementation for User Story 6

- [X] T058 [US6] Extraer `sanitize_engine_error(text) -> str` como helper único (hoy duplicado en `chat.py:1616,1677`) en `backend/src/services/error_sanitizer.py` (nuevo)
- [X] T059 [US6] Aplicar `sanitize_engine_error()` en `backend/src/api/chat.py` (reemplaza el `.replace()` inline existente) y en `backend/src/api/gateway.py`/`backend/src/api/inspect.py` (hoy sin sanitizar) — depende de T058
- [X] T060 [US6] Renombrar el campo público `litellm_params` → `engine_params` en el schema de `backend/src/api/chat.py` (líneas ~2260, 2277-2279), aceptando ambos nombres de entrada por compatibilidad durante al menos una versión
- [X] T061 [US6] Renombrar el guardián NLP sembrado: `name="Detección lingüística de datos personales"` en `backend/src/services/guardian_service.py:179-180`, y agregar el `UPDATE` de renombrado de instalaciones existentes a la migración `018_...py` (depende de T006)
- [X] T062 [US6] Agregar al instalador un comando propio de logs/diagnóstico sin banner del motor (`elea-installer/logs.sh` o equivalente, invocado en vez de `docker compose logs engine` en los mensajes del `install.sh`)
- [X] T063 [US6] Correr `quickstart.md` §6 y registrar el resultado en el `CHANGELOG.md` de la feature

**Checkpoint**: branding neutro verificado con una prueba automática — insumo directo para el gate CI que la 044 debe replicar del lado de las UIs.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T064 [P] **Sitio de docs de producto (OBLIGATORIO, DoD)**: actualizar `docs/docs/**` (curado marca-neutro — usar "Eleia"/"Guardian" según corresponda, nunca "Sentinel") con los endpoints y conceptos nuevos (`workspaces`, `X-Guardian-Acting-User`, `document_id`, `PATCH/DELETE /users`) y correr `make -C deploy check-docs`
- [X] T065 Revisar y limpiar los cambios cruzados en `gateway.py`/`inspect.py`/`custom_auth.py` tocados por US2/US3/US6 (evitar duplicación entre las tres historias)
- [X] T066 [P] Tests unitarios adicionales de edge cases: chunks concurrentes del mismo documento (T039), baja de usuario con hilos activos (T054), colisión de placeholder dentro del mismo documento, en `backend/tests/unit/`
- [X] T067 Test adversarial: confirmar que `X-Guardian-Acting-User` es ignorado/rechazado cuando lo manda una llave sin `can_act_on_behalf=true`, en `backend/tests/integration/test_attribution_budget.py` (extiende T025)
- [ ] T068 Correr `quickstart.md` completo (los 6 bloques) de punta a punta contra un `docker compose up` desde cero y registrar el resultado en `specs/043-aislamiento-atribucion-motor/CHANGELOG.md`
- [ ] T069 Reconstruir y taggear las imágenes (`ghcr.io/cluna-8/elea-guardian-backend`, `elea-guardian-engine`) y actualizar `elea-installer` para apuntar a las versiones verificadas en T068

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias, arranca de inmediato.
- **Foundational (Phase 2)**: depende de Setup. **Bloquea US1, US2, US4, US5.** NO bloquea US3 ni US6 (ver abajo).
- **US1, US2, US4, US5**: dependen de Foundational.
- **US3, US6**: dependen solo de Setup — pueden implementarse en paralelo con Foundational/US1/US2/US4/US5 sin esperar a nadie.
- **Polish (Phase 9)**: depende de que las historias que se vayan a entregar estén completas.

### User Story Dependencies

- **US1 (P1)**: tras Foundational. Sin dependencia de otras historias.
- **US2 (P1)**: tras Foundational. Usa el `document_group_id` que US3 define en el body de `/gw/inspect` (T029 referencia T038/T040) — si US3 no está lista, T029 puede implementarse aceptando el campo sin usarlo aún (no bloqueante, solo un poco de trabajo duplicado si el orden se invierte).
- **US3 (P1)**: tras Setup únicamente. Completamente independiente — es la historia más chica y rápida de entregar sola.
- **US4 (P2)**: tras Foundational; se apoya en la separación `model`/`surface` que T028 (US2) ya deja hecha en `gateway._audit()` — si US2 no está lista, T047 puede hacerse igual leyendo directo `event_type`/`surface` de T006 (backfill), sin depender del código de US2, solo del esquema.
- **US5 (P2)**: tras Foundational y tras T015 de US1 (para el efecto cascada de T054). Si US1 no está lista, T053/T055 (baja sin cascada de espacios) se pueden entregar igual; T054 queda pendiente hasta que exista `workspace_service.py`.
- **US6 (P2)**: tras Setup únicamente. Independiente.

### Parallel Opportunities

- Todas las tareas `[P]` de Setup y Foundational en paralelo entre sí.
- Una vez cerrada Foundational: US1, US2, US4, US5 pueden repartirse entre distintas personas en paralelo (con las dependencias cruzadas menores anotadas arriba).
- US3 y US6 pueden arrancar el mismo día que el Setup, en paralelo con todo lo demás — son los candidatos ideales para la primera entrega si se quiere paralelizar el equipo desde el día 1.
- Dentro de cada historia, los tests marcados `[P]` corren en paralelo entre sí antes de la implementación.

---

## Parallel Example: User Story 3 (independiente, sin Foundational)

```bash
# Tests en paralelo:
Task: "Contract test mismo document_id -> mismo placeholder en backend/tests/contract/test_masking_determinism.py"
Task: "Contract test sin document_id -> sin regresión en backend/tests/contract/test_masking_no_regression.py"
Task: "Contract test document_id distinto -> placeholder distinto en backend/tests/contract/test_masking_cross_document.py"

# Implementación secuencial (mismo archivo):
Task: "Aceptar document_id en mask_body() en litellm/extensions/sentinel_guardian_policy.py"
Task: "Derivar nonce+índice por HMAC(document_id) en litellm/extensions/sentinel_guardian_policy.py"
```

---

## Implementation Strategy

### MVP first (las tres P1: US1 + US2 + US3)

1. Setup (Phase 1).
2. Foundational (Phase 2) — habilita US1/US2. En paralelo, empezar US3 (no depende de Foundational).
3. US1 (Phase 3) — cierra la fuga prioritaria de Tomás.
4. US2 (Phase 4) — cierra la atribución de gasto y el 402 real.
5. US3 (Phase 5, si no se hizo en paralelo antes) — cierra el enmascarado no determinista.
6. **STOP y VALIDAR**: correr `quickstart.md` §1-3 contra el stack completo. Esto ya responde a los dos mails de Tomás en su parte de backend/motor — falta la integración con la 044 (Hub/panel) para que la persona lo vea.

### Entrega incremental

1. Setup + Foundational → base lista.
2. US3 puede salir primero si se paraleliza (no depende de nada más) → demo del enmascarado ya arreglado.
3. US1 → demo de aislamiento de espacios.
4. US2 → demo de costos y presupuesto reales.
5. US4, US5, US6 (P2) → refinamiento, en cualquier orden, todas independientes entre sí salvo las notas de dependencia liviana ya anotadas.
6. Polish (Phase 9) → verificación end-to-end y release de imágenes.

### Estrategia de equipo en paralelo

Con varias personas: Setup+Foundational en conjunto; luego una persona en US1, otra en US2, otra en US3 (puede arrancar antes que las demás), y en una segunda ronda US4/US5/US6 repartidas. Los checkpoints de cada fase son los puntos de integración.

---

## Notes

- `[P]` = archivos distintos, sin dependencias pendientes entre sí.
- `[Story]` mapea cada tarea a su historia para trazabilidad contra `spec.md`.
- US3 y US6 son las dos historias que NO dependen de la migración — son las más rápidas de entregar solas y las mejores candidatas para paralelizar desde el día 1.
- Verificar que los tests fallan antes de implementar (TDD, según el workflow del proyecto).
- Commitear después de cada tarea o grupo lógico; usar la atribución de commits vigente para esta sesión.
- Ningún archivo de `frontend/` ni `client/` se toca en esta lista — son la spec 044, que consume los 6 contratos de `contracts/` una vez que las historias correspondientes de acá estén cerradas.
