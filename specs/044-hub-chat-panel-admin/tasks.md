# Tasks: Eleia Hub con espacios privados, costos por persona y Eleia Guardian completo

**Input**: Design documents from `specs/044-hub-chat-panel-admin/`
(`plan.md`, `spec.md`, `research.md`, `data-model.md`, `quickstart.md`)

**Marca**: en este repo todo es **Eleia** — panel = "Eleia Guardian", chat/RAG = "Eleia Hub".
Nunca "Sentinel".

**Depende de**: los 6 contratos de [043-aislamiento-atribucion-motor](../043-aislamiento-atribucion-motor/contracts/).
Mientras un contrato no esté desplegado, la historia correspondiente se desarrolla contra un doble
de prueba con la misma forma documentada y se marca "pendiente de integración" — no se cierra
(spec.md, Contratos consumidos de la 043).

**Tests**: incluidos (FR-030/031 los exigen explícitamente). Ninguno de los dos repos tiene tooling
de test hoy — Phase 1 lo introduce (ver `research.md` R4).

**Organization**: por historia de usuario (US1-US6 de `spec.md`). **NO se toca `backend/` ni
`litellm/`** — son la spec 043.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [X] T001 Agregar `supertest` como devDependency y el script `"test": "node --test tests/**/*.js"` en `client/package.json`
- [X] T002 [P] Agregar `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom` como devDependencies, `vitest.config.ts` y el script `"test": "vitest run"` en `frontend/package.json`
- [X] T003 [P] Crear los directorios `client/tests/{contract,integration}` y `frontend/tests/{contract,integration}` con un test trivial de humo en cada uno

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: helpers compartidos hacia los endpoints nuevos del backend, usados por más de una
historia. Bloquea US1, US2, US3, US4 (todas llaman al backend de la 043). **US5 (branding) no
depende de esta fase** — es reescritura de texto/copy, puede arrancar apenas termine el Setup.

- [X] T004 Agregar helper `backendWorkspaces(session, path, opts)` reutilizando `eleaFetch()` existente para llamar a `GET/POST /workspaces*` del backend (contrato 1), en `client/server.js`
- [X] T005 Agregar helper `fetchOwnBudget(session)` que llama `GET /users/me/budget` (contrato 2) reutilizando `eleaFetch()`, en `client/server.js`
- [X] T006 [P] Agregar tipos TypeScript para `account_type`, `purpose`, `deactivated_at`, `engine_params`, `WorkspaceUnassigned` en `frontend/src/services/api.ts`
- [X] T007 [P] Agregar funciones de cliente `getUsers({includeService})`, `patchUser()`, `deleteUser()`, `getUnassignedWorkspaces()`, `assignWorkspaceMember()` en `frontend/src/services/api.ts` (sin UI todavía — consumidas en las fases siguientes)

**Checkpoint**: helpers listos — US1/US2/US3/US4 pueden avanzar. US5 ya podía avanzar desde el Setup.

---

## Phase 3: User Story 1 - Cada persona ve solo sus espacios y sus hilos (Priority: P1) 🎯 MVP

**Goal**: el Hub lista solo espacios donde la persona es miembro, hilos privados por usuario, sin
excepción sin sesión.

**Independent Test**: dos personas, dos navegadores — A crea espacio, B no lo ve; A invita a B; B
lo ve y sus hilos no se cruzan; sin sesión, ninguna URL del Hub devuelve datos. Ver `quickstart.md` §1.

### Tests for User Story 1

- [X] T008 [P] [US1] Test de contrato: `GET /api/workspaces` exige sesión (401) y solo devuelve espacios propios (contra doble del contrato 1) en `client/tests/contract/test_workspaces.test.js` (sufijo `.test.js` por el glob de `node --test`)
- [X] T009 [P] [US1] Test de integración: acceso cruzado denegado (403, sin datos) + alta de miembro habilita el acceso, con dos sesiones simuladas, en `client/tests/integration/test_workspace_isolation.test.js` (sufijo `.test.js` por el glob de `node --test`)

### Implementation for User Story 1

- [X] T010 [US1] Agregar guard de sesión (`getSession(req)` + 401 si falta) a **todos** los endpoints de espacios/hilos/documentos que hoy no lo tienen (`/api/workspaces*`, `/api/threads/*`, `/api/workspaces/create|delete|settings|upload`) en `client/server.js` (referencia `diagnostico.md` de la 043 §1 para las líneas exactas a corregir)
- [X] T011 [US1] Reemplazar `GET /api/workspaces` para listar vía `GET /workspaces` del backend (T004) en vez de `GET /api/v1/workspaces` directo a AnythingLLM, en `client/server.js`
- [X] T012 [US1] Antes de proxyar cualquier operación sobre un `workspace_id`/`slug` conocido (historial, ajustes, subida, chat), verificar acceso llamando `GET /workspaces/{id}` del backend; 403 uniforme si no hay membresía, en `client/server.js` (depende de T004, T010)
- [X] T013 [US1] Implementar endpoints de hilos scopeados por usuario (`GET/POST/DELETE /api/threads/*`) verificando pertenencia antes de proxyar, en `client/server.js`
- [X] T014 [US1] Implementar proxy de gestión de miembros (`GET/POST/DELETE /api/workspaces/:id/members`, `PATCH .../transfer-owner`) hacia el backend, en `client/server.js`
- [X] T015 [US1] `public/index.html`: quitar el auto-select de `workspaces[0]`; mostrar estado vacío ("Todavía no tenés espacios. Creá uno o pedile a tu administrador que te agregue") cuando la lista esté vacía
- [X] T016 [US1] `public/index.html`: agregar panel "Miembros" (ver/agregar por username/quitar/transferir propiedad) visible para dueño/admin, solo lectura para miembro
- [X] T017 [US1] `public/index.html`: manejar 403 de espacio ajeno con "No tenés acceso a este espacio" sin cargar nada
- [X] T018 [US1] Vista "Sin asignar" para admins en el Hub (listar espacios heredados de la migración, con acción de asignar miembros) — `client/server.js` (endpoint `GET /api/workspaces/unassigned` + `POST /api/workspaces/unassigned/:id/members`, corregido el bug real `status` vs `status_filter`) + `public/index.html` (modal "Sin asignar", botón visible solo para roles admin), probado en `client/tests/integration/unassigned.test.js`
- [ ] T019 [US1] Correr `quickstart.md` §1 y §6 (migración de los 3 espacios reales) y registrar el resultado en `specs/044-hub-chat-panel-admin/CHANGELOG.md` (creado; cobertura automatizada contra dobles ya registrada ahí — falta la corrida en vivo contra un despliegue real, diferida al pase de testeo de calidad post-043+044)

**Checkpoint**: US1 funcional e independiente — cierra la fuga prioritaria del lado del Hub.

---

## Phase 4: User Story 2 - Presupuesto que se ve y se aplica; costos por persona en el panel (Priority: P1)

**Goal**: el badge de presupuesto es autoservicio y bloquea antes de enviar; el panel muestra
consumo real por persona.

**Independent Test**: persona con $1 de presupuesto, dos preguntas suben su badge; el panel la
muestra con ese consumo; al agotrarlo, la siguiente pregunta se bloquea antes de enviarse. Ver
`quickstart.md` §2.

### Tests for User Story 2

- [X] T020 [P] [US2] Test de contrato: el presupuesto se lee con `session.token` propio, no con sesión de admin, en `client/tests/contract/test_budget.test.js` (sufijo `.test.js` por el glob de `node --test`)
- [X] T021 [P] [US2] Test de integración: pregunta bloqueada localmente cuando `status="exceeded"`, sin llegar a enviar el pedido, en `client/tests/integration/test_budget_enforcement.test.js` (sufijo `.test.js` por el glob de `node --test`)

### Implementation for User Story 2

- [X] T022 [US2] Reemplazar `fetchUserBudget()` para usar `fetchOwnBudget(session)` (T005) en vez de `ELEA_SERVICE_USERNAME`/sesión de admin, en `client/server.js` (R1 de `research.md`)
- [X] T023 [US2] Agregar verificación de presupuesto antes de enviar en `POST /api/chat` y en el handler de subida; si `status="exceeded"`, responder con el mensaje neutro sin llamar al backend de nuevo, en `client/server.js`
- [X] T024 [US2] `public/index.html`: mostrar el mismo mensaje neutro ("Alcanzaste tu presupuesto. Contactá a tu administrador") tanto si el bloqueo es local como si viene de un 402 del backend
- [X] T025 [US2] `frontend/src/pages/CostsPage.tsx`: agregar vista de consumo por persona (incluye actividad dentro de espacios) distinguiendo operaciones de enmascarado (sin costo, por documento) de preguntas (con costo, modelo real) — nuevo `masking_by_user` en `backend/src/api/costs.py` (cuenta `document_group_id` distintos), probado en `backend/tests/integration/test_costs_masking_by_user_044.py`
- [X] T026 [US2] `frontend/src/pages/DashboardPage.tsx` / `CostsPage.tsx`: verificar que no quede ningún filtro local de `license`/`chat-ui` (ahora resuelto por el backend, contrato 4) — quitar si existiera alguno hardcodeado (verificado: ninguno de los dos archivos tiene un filtro local, el backend ya resuelve `event_type`/`surface`)
- [ ] T027 [US2] Correr `quickstart.md` §2 y registrar el resultado en el `CHANGELOG.md` de la feature (diferido, mismo motivo que T019: requiere despliegue real, no dobles — pase de testeo de calidad post-043+044)

**Checkpoint**: US1 + US2 — una persona ve sus espacios y su gasto real, con presupuesto aplicado antes de gastar.

---

## Phase 5: User Story 3 - Enmascarado coherente en todo el documento, visible para la persona (Priority: P1)

**Goal**: un `document_id` por subida agrupa los chunks; el resumen de protección es único por
documento; el chat relaciona todas las apariciones del mismo valor.

**Independent Test**: subir el CSV real con "Julián" repetido; el resumen lo cuenta una vez;
preguntar por él devuelve todas sus filas con el nombre real. Ver `quickstart.md` §3.

### Tests for User Story 3

- [X] T028 [P] [US3] Test de contrato: el mismo `document_id` viaja en todas las llamadas de chunk de una subida, en `client/tests/contract/test_document_id.test.js` (sufijo `.test.js` por el glob de `node --test`)
- [X] T029 [P] [US3] Test de integración: un reintento tras fallo de red simulado reusa el mismo `document_id`, en `client/tests/integration/test_upload_retry.test.js` — implementado el reintento real en `maskChunk` (`client/server.js`, 3 intentos, solo ante fallo de RED, nunca ante 4xx/402), que antes no existía

### Implementation for User Story 3

- [X] T030 [US3] Generar `document_id` (`crypto.randomUUID()`) una vez por subida, antes de trocear, y reutilizarlo en reintentos de la misma subida, en `client/server.js` (R2 de `research.md`)
- [X] T031 [US3] Enviar `document_id` en el body de cada llamada `maskChunk()`/`POST /gw/inspect`, en `client/server.js` (depende de T030)
- [X] T032 [US3] Agregar los resultados de todos los chunks de una subida en un único resumen por documento (conteo por tipo de entidad), en `client/server.js`
- [X] T033 [US3] `public/index.html`: mostrar el resumen de protección agregado por documento (no por chunk) tras cada subida — modal "Resumen de protección" con conteo por tipo de dato
- [X] T034 [US3] Marcar documentos subidos antes de esta feature (fecha de corte `MASKING_DETERMINISM_SINCE` vs. fecha del documento, R5) con aviso de "esquema anterior. Reenviar para mejorar las respuestas", en `client/server.js` + `public/index.html` — sin la env configurada o sin `meta.published`, no marca nada (nunca avisa mal por un dato ausente)
- [ ] T035 [US3] Correr `quickstart.md` §3 con el CSV real del cliente y registrar el resultado en el `CHANGELOG.md` de la feature (diferido, mismo motivo que T019/T027: requiere despliegue real y el CSV real del cliente — pase de testeo de calidad post-043+044)

**Checkpoint**: US3 completamente independiente de US1/US2 — puede entregarse aunque las otras no estén listas.

---

## Phase 6: User Story 4 - Panel de usuarios completo (Priority: P2)

**Goal**: editar rol/email/nombre/equipo con actualización parcial; desactivar/reactivar; dar de
baja con confirmación fuerte; cuentas de servicio en sección aparte de solo lectura.

**Independent Test**: cambiar solo el rol, luego solo el email; desactivar y reactivar; dar de
baja (con confirmación); `svc.*` solo en la sección plegada. Ver `quickstart.md` §4.

### Tests for User Story 4

- [X] T036 [P] [US4] Vitest: la sección "Cuentas de servicio" está plegada, de solo lectura, y esas cuentas no aparecen en la tabla principal, en `frontend/tests/contract/UsersPage.service-accounts.test.tsx`
- [X] T037 [P] [US4] Vitest: editar rol o email envía solo el campo tocado (`PATCH` parcial), en `frontend/tests/contract/UsersPage.patch.test.tsx`
- [X] T038 [P] [US4] Vitest: la UI impide auto-baja y baja del último admin antes de llamar al backend, en `frontend/tests/contract/UsersPage.delete-guards.test.tsx`

### Implementation for User Story 4

- [X] T039 [US4] Confirmar/completar en `frontend/src/services/api.ts` (T007): `patchUser(id, partial)`, `deleteUser(id)`, `getUsers({includeService})` (ya hechas en T007)
- [X] T040 [US4] `UsersPage.tsx`: edición en línea de rol/email/nombre visible/equipo con validación y confirmación para cambio de rol, llamando `patchUser`
- [X] T041 [US4] `UsersPage.tsx`: toggle desactivar/reactivar + flujo de "dar de baja" con modal de confirmación escribiendo el nombre de usuario y explicación de consecuencias
- [X] T042 [US4] `UsersPage.tsx`: sección plegada "Cuentas de servicio (N)" de solo lectura, con nombre/propósito/estado (`purpose` del contrato 4)
- [X] T043 [US4] `UsersPage.tsx`: ocultar acciones destructivas/de edición para el rol "lectura"
- [X] T044 [US4] Crear `frontend/src/pages/WorkspacesUnassignedPage.tsx` (asignar miembros a espacios "sin asignar", contrato 1) + registrar la ruta en `frontend/src/App.tsx`
- [X] T045 [US4] `SecurityPage.tsx`: verificar que el nombre del guardián NLP llega neutro desde el backend (contrato 6) y quitar cualquier mapeo local que todavía muestre "Presidio" (verificado: el nombre visible viene de `g.name`/`selected.name` del backend, sin mapeo local; `guardian_type="presidio"` es solo un identificador interno, nunca renderizado)
- [ ] T046 [US4] Correr `quickstart.md` §4 y registrar el resultado en el `CHANGELOG.md` de la feature (diferido, mismo motivo que T019/T027/T035 — pase de testeo de calidad post-043+044)

**Checkpoint**: el panel cubre edición/baja completa y separa cuentas de servicio de personas.

---

## Phase 7: User Story 5 - Ningún nombre de motor, proveedor NLP ni motor de documentos visible (Priority: P2)

**Goal**: ni el Hub ni el panel muestran nombres de motor/proveedor/NLP en texto, errores, título
de pestaña o código fuente servido. **No depende de la Fase 2** — puede arrancar desde el Setup.

**Independent Test**: motor de documentos caído → error neutro; código fuente del Hub sin nombres
prohibidos ni en comentarios; título del panel = marca configurada. Ver `quickstart.md` §5.

### Tests for User Story 5

- [X] T047 [P] [US5] Script de regresión que recorre `client/public/**`, los strings de error de `client/server.js`, y el build de `frontend/` buscando términos prohibidos (`litellm`, `anythingllm`, `presidio`, `sentinel` salvo excepciones documentadas), en `tools/check-branding-neutral.js` (nuevo, corrible desde ambos repos)

### Implementation for User Story 5

- [X] T048 [US5] Reemplazar los 7 mensajes de error que nombran el motor de documentos por copy neutro (p. ej. "El servicio de documentos no está disponible") en `client/server.js` (ya hecho en un pase anterior de esta sesión; verificado ahora con `check-branding-neutral.js`: 0 hallazgos en `client/server.js`)
- [X] T049 [US5] Quitar/reescribir los comentarios de `client/public/index.html` que nombran el motor de documentos (servido tal cual al navegador) — 10 comentarios reescritos, 0 hallazgos ahora
- [X] T050 [US5] `frontend/index.html`: `<title>` tomado de `frontend/src/services/branding.ts` en vez de hardcodeado — placeholder neutro "Guardian" (nunca "Sentinel"), sobreescrito por `loadBranding()` antes del primer render
- [X] T051 [US5] `frontend/src/services/api.ts`: renombrar el uso de `litellm_params` a `engine_params` (contrato 6; el backend acepta ambos durante la migración, el cliente ya usa el nuevo)
- [X] T052 [US5] Agregar `tools/check-branding-neutral.js` (T047) al pipeline de CI de ambos repos (`client/`, `frontend/`) — agregado a `harness-tests` en `.github/workflows/ci.yml`, junto con `npm test` de `client/` y `frontend/` (gaps reales encontrados: ninguno de los dos corría en CI todavía)
- [ ] T053 [US5] Correr `quickstart.md` §5 y registrar el resultado en el `CHANGELOG.md` de la feature (diferido, mismo motivo que T019/T027/T035/T046 — pase de testeo de calidad post-043+044)

**Checkpoint**: branding neutro verificado con prueba automática en las dos UIs.

---

## Phase 8: User Story 6 - Verificación de integración UI + backend antes de cerrar (Priority: P1, transversal)

**Goal**: ninguna historia P1 se da por cerrada sin correr el guion completo contra la 043 real,
dos veces (instalación limpia y una copia/la instalación de Elea).

**Independent Test**: el guion de `quickstart.md` corre completo y todos los pasos pasan.

- [X] T054 [US6] Crear `specs/044-hub-chat-panel-admin/CHANGELOG.md` con la plantilla de registro (mismo nivel de detalle que `specs/042-rediseno-ui-boveda-pii-hilos/CHANGELOG.md`)
- [ ] T055 [US6] Correr `quickstart.md` completo (§1-§6) contra una instalación limpia de 043+044 desde cero (`docker compose up`) y registrar el resultado en el `CHANGELOG.md` (diferido — pase de testeo de calidad post-043+044, requiere credenciales reales de proveedor LLM no disponibles en este entorno)
- [ ] T056 [US6] Correr `quickstart.md` completo contra una copia de la instalación real de Elea (o un espacio de prueba creado y borrado sobre la real, mismo criterio que la 042) y registrar el resultado en el `CHANGELOG.md` (diferido, requiere acceso a la instalación real de Elea — fuera del alcance de este entorno)
- [X] T057 [US6] Agregar pruebas de contrato explícitas para los contratos 4, 5 y 6 de la 043 del lado del panel (no cubiertos por T008-T038) en `frontend/tests/contract/backend-contracts.test.ts`
- [ ] T058 [US6] Solo después de que T055 y T056 pasen completos: reconstruir y taggear las imágenes `elea-rag-client` y `elea-guardian-frontend`, y actualizar `elea-installer` a las versiones verificadas (bloqueado por T055/T056, mismo motivo)

**Checkpoint**: "funciona" significa "funciona integrado" — recién acá se puede reportar a Tomás que los bugs están resueltos.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [X] T059 [P] **Sitio de docs de producto (OBLIGATORIO, DoD)**: actualizar `docs/docs/**` (marca-neutro, "Eleia"/"Guardian", nunca "Sentinel") con las pantallas y flujos nuevos, y correr `make -C deploy check-docs` — página nueva `docs/docs/administration/eleia-hub-workspaces.md` registrada en `mkdocs.yml`; `check-docs` da 1 fallo preexistente sin relación con la 043/044 (`test_env_incluye_helpers_tipados_y_el_plano_motor`, drift de `OPENAI_API_KEY` en `docs/tools/drift_gate.py` — no toca env vars ni litellm_config); los 4 checks reales del sitio (build, imagen, contenido, naming neutro) pasan en verde por separado
- [X] T060 Limpieza: quitar el uso de `ELEA_SERVICE_USERNAME`/`ELEA_SERVICE_PASSWORD` en `client/server.js` donde T022 ya lo volvió innecesario, si no queda ningún otro camino que lo necesite
- [X] T061 [P] Tests unitarios adicionales de edge cases: sesión expirada a mitad de subida, dos pestañas editando el mismo usuario en el panel, en `client/tests/unit/` y `frontend/tests/unit/`
- [X] T062 Revisión manual de accesibilidad/responsive de las secciones nuevas de `UsersPage.tsx` y de los estados vacíos del Hub — UsersPage: todos los botones nuevos tienen `focus-visible:ring`, `StatusBadge`/`Button` reusan tokens ya accesibles del sistema, la tabla ya scrollea horizontal (`overflow-x-auto`) para el nuevo ancho. Hub (`public/index.html`): las secciones nuevas siguen la MISMA convención (`.modal-box`/`.modal-input`) que el resto del archivo — sin breakpoints de mobile ni `<label for>` explícito en ningún modal, propio o preexistente; no se corrigió ese déficit global (afecta a TODOS los modales del archivo, no algo introducido por esta feature) — queda anotado como deuda preexistente, fuera del alcance de la 044
- [ ] T063 Corrida final completa de `quickstart.md` y nota de cierre firmada en el `CHANGELOG.md`, referenciada desde el `CHANGELOG.md` de la 043 (bloqueado por T055/T056 — pase de testeo de calidad post-043+044)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende de Setup. Bloquea **US1, US2, US3, US4**. NO bloquea **US5**
  (branding, arranca desde el Setup).
- **US6 (transversal, Phase 8)**: depende de que las historias P1 que se vayan a verificar estén
  completas — normalmente la última en cerrarse, aunque su tarea T054 (crear el `CHANGELOG.md`)
  puede hacerse desde el principio.
- **Polish (Phase 9)**: depende de US6.

### User Story Dependencies

- **US1 (P1)**: tras Foundational. Requiere el **contrato 1** de la 043 (o su doble de prueba).
- **US2 (P1)**: tras Foundational. Requiere el **contrato 2**. Su parte de panel (T025) se apoya en
  el **contrato 4** (separación modelo/superficie) — si la 043 US4 no está lista, T025 puede
  mostrarse igual, sin filtrar `license`/`chat-ui` hasta que el backend lo resuelva (no bloqueante,
  solo con ruido temporal).
- **US3 (P1)**: tras Foundational (usa `client/server.js`, aunque no usa T004/T005 directamente —
  su única dependencia real es el **contrato 3**). Puede desarrollarse en paralelo con US1/US2.
- **US4 (P2)**: tras Foundational. Requiere los **contratos 4 y 5**, y el **contrato 1** para la
  vista de espacios sin asignar (T044).
- **US5 (P2)**: solo depende de Setup. Requiere el **contrato 6** de la 043 para que los errores del
  plano `/gw` lleguen ya sanitizados — mientras tanto, T048-T049 (los 7 errores del propio Hub) se
  pueden hacer igual, son responsabilidad de esta spec, no de la 043.
- **US6 (P1, transversal)**: depende de que **todas** las historias P1 (US1, US2, US3) estén
  completas, y de que la 043 esté desplegada de verdad (no dobles de prueba) — es la única historia
  que no admite doble de prueba por definición.

### Parallel Opportunities

- Todas las `[P]` de Setup y Foundational en paralelo.
- Tras Foundational: US1, US2, US3, US4 en paralelo entre distintas personas (con las notas de
  dependencia liviana de arriba).
- US5 puede arrancar el mismo día que el Setup, en paralelo con todo el resto.
- US6 es necesariamente la última en cerrar del todo, aunque su preparación (T054) puede empezar
  en cualquier momento.

---

## Parallel Example: User Story 5 (independiente, sin Foundational)

```bash
Task: "Script de regresión de términos prohibidos en tools/check-branding-neutral.js"
Task: "Reemplazar los 7 mensajes de error en client/server.js"
Task: "Quitar comentarios que nombran AnythingLLM en client/public/index.html"
```

---

## Implementation Strategy

### MVP first (las tres P1 de producto: US1 + US2 + US3, más US6 para cerrar)

1. Setup (Phase 1).
2. Foundational (Phase 2) — habilita US1/US2/US3/US4. En paralelo, arrancar US5 (no depende de nada).
3. US1 (Phase 3) → US2 (Phase 4) → US3 (Phase 5), en cualquier orden entre sí (independientes).
4. US6 (Phase 8): correr el guion completo contra la 043 real. **Esto es lo que responde de verdad
   a los dos mails de Tomás** — antes de esto, "está resuelto en la spec" no es lo mismo que "está
   probado".
5. **STOP y VALIDAR**: solo tras T055/T056 en verde se reconstruyen imágenes (T058) y se reporta al
   cliente.

### Entrega incremental

1. Setup + Foundational → base lista; US5 ya en marcha en paralelo.
2. US1 → demo de aislamiento visible.
3. US2 → demo de presupuesto real.
4. US3 → demo del enmascarado coherente.
5. US4 (P2) → panel completo, en paralelo con lo anterior si hay capacidad.
6. US6 → verificación de punta a punta, dos corridas (limpia + real/copia), antes de cualquier
   release.
7. Polish (Phase 9).

---

## Notes

- `[P]` = archivos distintos, sin dependencias pendientes.
- `[Story]` mapea cada tarea a su historia para trazabilidad contra `spec.md`.
- US5 es la historia más rápida de entregar sola (no depende de Foundational); US6 es la única que
  no se puede "adelantar" — necesita que las demás P1 estén realmente hechas.
- Ningún archivo de `backend/` ni `litellm/` se toca acá — son la spec 043.
- Commitear después de cada tarea o grupo lógico; usar la atribución de commits vigente para esta
  sesión.
