---
description: "Task list for feature 019 — Integration Surfaces & Client Compatibility"
---

# Tasks: Integration Surfaces & Client Compatibility

**Input**: Design documents from `/specs/019-integration-surfaces/`

**Prerequisites**: plan.md (required), spec.md (required for user stories). Depende del **bedrock 013**
(Tenant, `role="client"`, `client_type`, APIKey=Connection con `tenant_id`/`tool_type`/`upstream_mode`) y
del **port 014** (el gateway/firewall al que apuntan estos clientes).

**Tests**: SÍ incluidos. El ruteo de superficies (passthrough vs auto-byok vs key-in-URL, exclusión
`x-basa-*`) y el mask/unmask de la extensión llevan tests; la matriz se valida como documentación. Los
tests marcados ⚠️ se escriben ANTES de la implementación y deben FALLAR primero.

**Organization**: Tareas agrupadas por user story para implementación y test independientes.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Puede correr en paralelo (archivos distintos, sin dependencias)
- **[Story]**: US1..US5 (o SETUP/FOUND/POLISH)
- Rutas de archivo exactas incluidas

## Path Conventions

- Backend: `backend/src/api/` (gateway/ruteo + endpoints de la extensión), `backend/src/services/` (reusados)
- Extensión MV3: `extension/` (a portar de `basa-browser-dlp/`)
- Config/models: `backend/src/models/` (de la 013)
- Tests: `tests/integration/`, `tests/unit/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Estructura del paquete de la extensión y del ruteo de superficies en el backend.

- [ ] T001 [SETUP] Crear el directorio `extension/` en `basa-guardian` y copiar la base de la extensión MV3
      desde `basa-browser-dlp/` (`manifest.json`, `basa-guard.js`, `bridge.js`, `background.js`,
      `popup.html`, `popup.js`) como punto de partida del port.
- [ ] T002 [P] [SETUP] Configurar linting/formato para `extension/` (JS) y `tests/` (reusar la config del
      repo); documentar cómo cargar la extensión sin empaquetar (dev unpacked).
- [ ] T003 [SETUP] Preparar el esqueleto de `tests/integration/` y `tests/unit/` para esta feature
      (ruteo de superficies + adapters de la extensión).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Phase 0 research (comportamiento real por cliente) + criterios de la matriz. TODO lo demás
depende de tener estos hechos verificados (la spec hace claims de compatibilidad que hay que fundamentar).

**⚠️ CRITICAL**: Ningún user story cierra hasta confirmar los hechos de esta fase.

- [ ] T004 [FOUND] Phase 0 research (`research.md`): confirmar contra el demo y contra cada cliente real
      (a) Ask vs Agent en Copilot (el 400 por input UUID + `tool_use_failed` con modelos no-Claude), (b)
      que ChatGPT/Claude web NO firman el body (aceptan reescritura), (c) respuesta por WebSocket vs `fetch`
      hookeado (unmask en DOM), (d) los gaps concretos de Gemini (host + adapter) y de iframe
      (`all_frames:false`). *(alimenta US1/US2/US3/US4/US5)*
- [ ] T005 [FOUND] Fijar los **criterios de estado** de la matriz de compatibilidad
      (FUNCIONA/PARCIAL/NO/MCP-ONLY) en `compatibility.md`: qué evidencia mínima exige cada estado. Bloquea
      la consolidación de US4.

**Checkpoint**: Hechos de compatibilidad verificados + criterios de la matriz → los user stories pueden
cerrar sus claims.

---

## Phase 3: User Story 1 - Claude Code passthrough de suscripción + identidad (Priority: P1) 🎯 MVP

**Goal**: Verificar/portar el modo `subscription-passthrough` (OAuth verbatim → suscripción paga) +
detección por UA + identidad por `X-Basa-Key` (atribución, no credencial).

**Independent Test**: Apuntar `ANTHROPIC_BASE_URL` de Claude Code al gateway en modo `anthropic`; verificar
OAuth verbatim a `api.anthropic.com`, `tool_type`="Claude Code", PII enmascarada→des-enmascarada, y ciclo
Agent (tool_use) intacto.

### Tests for User Story 1 ⚠️

- [ ] T006 ⚠️ [P] [US1] Integration test en `tests/integration/test_passthrough_subscription.py`: en modo
      `subscription-passthrough`, el `Authorization`/OAuth se reenvía **verbatim** a `api.anthropic.com`
      (upstream mockeado) y NO se consume como credencial del gateway. *(FR-001, SC-001)*
- [ ] T007 ⚠️ [P] [US1] Integration test en `tests/integration/test_passthrough_headers.py`: los headers de
      Claude Code (`anthropic-version`, `anthropic-beta`, User-Agent, `x-app`) se reenvían sin alterar
      (porta `_passthrough_headers`). *(FR-003)*
- [ ] T008 ⚠️ [P] [US1] Unit test en `tests/unit/test_tool_detection.py`: UA con "claude" → "Claude Code";
      UA desconocido → "Desconocido" sin crash (porta `_TOOL_UA`/`_detect_tool`). *(FR-004)*

### Implementation for User Story 1

- [ ] T009 [US1] Portar/verificar en `backend/src/api/gateway.py` el ruteo `subscription-passthrough`:
      reenvío OAuth verbatim + `_passthrough_headers`; selección de modo por `X-Basa-Upstream` /
      `BASA_GW_UPSTREAM_DEFAULT`. *(FR-001, FR-002, FR-003)*
- [ ] T010 [US1] Portar la resolución de identidad por `X-Basa-Key` (`_resolve_identity`: sha256 →
      tenant/cliente/equipo) tratándola como **atribución, no credencial** (no viaja al upstream). *(FR-006, FR-007)*
- [ ] T011 [US1] Documentar/verificar que Claude Code aguanta **modo Agent** (tool_use round-trip intacto
      con modelos Claude); dejarlo asentado como estado FUNCIONA para la matriz (US4). *(FR-005)*

**Checkpoint**: Passthrough de suscripción verificado + identidad como atribución; demo titular lista.

---

## Phase 4: User Story 2 - VS Code / Copilot auto-byok + key-in-URL + Ask (Priority: P1)

**Goal**: Auto-byok por virtual key (`_BASA_KEY_RE`) **con la exclusión load-bearing de `x-basa-*`** +
key-in-URL; documentar Ask (soportado) vs Agent (no soportado, no-Claude).

**Independent Test**: Copilot **sin** header de control, key `sk-basa-…` en la URL → enruta a byok +
atribuye identidad; Ask completa mask/unmask; Agent no-Claude falla (documentado).

### Tests for User Story 2 ⚠️

- [ ] T012 ⚠️ [P] [US2] Integration test en `tests/integration/test_auto_byok.py`: virtual key `sk-basa-…`
      en `x-api-key`/`authorization` (sin `X-Basa-Upstream`) → enruta a **byok** + atribuye identidad.
      *(FR-008, SC-003)*
- [ ] T013 ⚠️ [P] [US2] Integration test (coexistencia) en `tests/integration/test_xbasa_exclusion.py`:
      Claude Code con `X-Basa-Key` que contiene `sk-basa-…` (atribución) **permanece** en passthrough (el
      scan excluye `x-basa-*`); test **negativo**: sin la exclusión, se desviaría a byok. *(FR-009, SC-002)*
- [ ] T014 ⚠️ [P] [US2] Integration test en `tests/integration/test_key_in_url.py`: Copilot con `x-api-key`
      vacío + `?k=sk-basa-…` en la URL → enruta a byok por fallback. *(FR-010, SC-003)*

### Implementation for User Story 2

- [ ] T015 [US2] Portar el **auto-byok** en `gateway.py`: scan de headers de auth por `_BASA_KEY_RE`
      **excluyendo** `x-basa-*` (load-bearing); enrutar a byok + atribuir identidad sin header de control.
      *(FR-008, FR-009)*
- [ ] T016 [US2] Portar el **key-in-URL** (`?k=sk-basa-…`, sobre `request.url`) como fallback de Copilot;
      marcar en código/doc que es **atajo de demo** (prod = input seguro/SSO). *(FR-010, Constraint C5)*
- [ ] T017 [US2] Verificar que en **byok** se enruta al motor LiteLLM con la key de Basa (cost tracking +
      budgets) — reusa el ruteo de la 014. *(FR-011)*
- [ ] T018 [US2] Documentar VS Code/Copilot como **PARCIAL**: Ask soportado; Agent no-Claude falla
      (tool_use_failed / 400 por input UUID). Asentar para la matriz (US4). *(FR-012)*

**Checkpoint**: Auto-byok + exclusión `x-basa-*` + key-in-URL verificados; coexistencia passthrough/byok
protegida por test.

---

## Phase 5: User Story 3 - Extensión de navegador MV3 mask/unmask (Priority: P1)

**Goal**: Portar la extensión MV3 (hook `window.fetch` → mask vía `/gw/inspect` → reescribe body → unmask
DOM), con la key aislada en el service worker y los adapters chatgpt + claude (incl. `/title`).

**Independent Test**: Instalar la extensión, conectar la key; prompt con PII en ChatGPT → el body sale con
placeholders y el DOM muestra los valores reales; sin key → fail-closed; monitor con `surface="browser"`;
en Claude.ai el título también se des-enmascara.

### Tests for User Story 3 ⚠️

- [ ] T019 ⚠️ [P] [US3] Integration test en `tests/integration/test_gw_inspect.py`: `POST /gw/inspect`
      enmascara el texto, devuelve `replacements`, empuja al monitor con `surface="browser"` y audita
      **metadata-only** (sin texto de prompt ni PII cruda); sin key válida → 401 (fail-closed).
      *(FR-014, FR-015, FR-019, SC-004, SC-005, SC-007)*
- [ ] T020 ⚠️ [P] [US3] Unit test en `tests/unit/test_extension_adapters.py`: adapter `chatgpt`
      (`/backend-api/f/conversation`, `parts[]`) y adapter `claude` (`/completion` **y** `/title`) leen/
      escriben el texto correcto; `unmask` y `unmaskTitle` restauran los valores; sin key el MAIN no envía.
      *(FR-016, FR-017, FR-018)*

### Implementation for User Story 3

- [ ] T021 [US3] Portar `extension/basa-guard.js` (mundo MAIN): hook de `window.fetch`, mask vía
      `/gw/inspect`, reescritura del body con `replacements`, unmask del DOM con `MutationObserver`
      (`unmask` + `unmaskTitle`). *(FR-013, FR-014, FR-016)*
- [ ] T022 [US3] Portar `extension/bridge.js` (ISOLATED) + `extension/background.js` (service worker): la
      key vive **sólo** en el service worker; el mundo MAIN nunca la ve. *(FR-017, SC-005)*
- [ ] T023 [US3] Portar los **adapters** (`chatgpt` + `claude`) en `basa-guard.js`, con el `claude` cubriendo
      `/completion` **y** `/title` para cerrar la fuga de título. *(FR-018)*
- [ ] T024 [US3] Portar/verificar los endpoints en `backend/src/api/inspect.py`: `GET /gw/whoami` (valida
      key → user/team, fail-closed) y `POST /gw/inspect` (mask + `surface="browser"` + `_log_tx`
      metadata-only). *(FR-015, FR-019)*
- [ ] T025 [US3] Portar `extension/popup.html`/`popup.js` (login del popup contra `/gw/whoami`); documentar
      `manifest.json` (content scripts MAIN + ISOLATED, host_permissions, `all_frames:false`). *(FR-013, FR-017)*

**Checkpoint**: Extensión demostrable en ChatGPT y Claude web (incl. título), fail-closed, monitor común.

---

## Phase 6: User Story 4 - Matriz de compatibilidad + no soportados (Priority: P2)

**Goal**: Consolidar la matriz (FUNCIONA/PARCIAL/NO/MCP-ONLY) con razón técnica concreta por entrada,
incluyendo Cursor=PARCIAL (sólo chat/plan, como Copilot Ask) y Claude Desktop=MCP-ONLY (tool-plane).

**Independent Test**: La matriz cubre ≥7 herramientas con estado + mecanismo + razón; toda entrada NO/
MCP-ONLY tiene razón concreta; FUNCIONA/PARCIAL coinciden con US1–US3.

### Tests / Implementation for User Story 4

- [ ] T026 [US4] Consolidar la **matriz de compatibilidad** en `compatibility.md` (viva) y sincronizarla con
      la tabla de la spec: Claude Code=FUNCIONA, Copilot=PARCIAL, ChatGPT web=FUNCIONA, Claude web=FUNCIONA,
      Gemini web=NO(roadmap, viable vía DOM-hook), Cursor=PARCIAL, Claude Desktop=MCP-ONLY. *(FR-020)*
- [ ] T027 [US4] Documentar las superficies **parciales/no soportadas** con su razón técnica: **Cursor**
      (Override OpenAI Base URL honrado sólo en chat/plan, como Copilot Ask; el agente Composer/inline/
      autocomplete no rutea por el endpoint custom y el Override Anthropic rompe con 422) y **Claude Desktop**
      (sin `ANTHROPIC_BASE_URL` ni hook interceptable; sólo MCP, alcance tool-plane). *(FR-021)*
- [ ] T028 [US4] Verificación cruzada: cada estado de la matriz mapea a evidencia (US1–US3) o a un gap
      documentado (US5); 0 entradas con razón "pendiente". *(SC-006)*

**Checkpoint**: Matriz honesta y verificable como contrato de onboarding.

---

## Phase 7: User Story 5 - Gemini web como extensión futura (Priority: P3)

**Goal**: Documentar el patrón para sumar Gemini (adapter + host match) como aditivo/roadmap, sin entregarlo.

**Independent Test**: La spec/`compatibility.md` documenta los dos gaps concretos (host en
`manifest.matches`, adapter en `basa-guard.js`) y marca Gemini como NO/roadmap.

### Tests / Implementation for User Story 5

- [ ] T029 [US5] Documentar en `compatibility.md` el patrón de extensión para **Gemini web**: nuevo adapter
      `{ id:"gemini", vendor, match, read, write }` en `basa-guard.js` + el host añadido a
      `manifest.matches`; marcarlo explícitamente como **NO implementado / roadmap** con los dos gaps.
      *(FR-022, SC-006)*

**Checkpoint**: Gemini documentado como aditivo/roadmap; ninguna promesa de hecho.

---

## Phase N: Polish & Cross-Cutting Concerns

- [ ] T030 [P] [POLISH] Generar `compatibility.md` (matriz viva + criterios de estado) y `quickstart.md`
      (apuntar Claude Code / Copilot → gateway; instalar la extensión unpacked; ver el monitor).
- [ ] T031 [POLISH] Verificación end-to-end (Principio VII): Claude Code (passthrough) + Copilot (byok) sobre
      el mismo gateway (coexistencia) + la extensión sobre ChatGPT/Claude web; confirmar el monitor común.
- [ ] T032 [P] [POLISH] Confirmar **onboarding as data** (Principio IV): sumar/quitar una superficie
      **soportada** (una `Connection`/`APIKey` con `tool_type`/`upstream_mode`) es config+seed, 0 código. *(SC-008)*
- [ ] T033 [POLISH] Documentar las limitaciones conocidas (iframe `all_frames:false`, cap de inspección en
      la cola del último turno, key-in-URL como atajo de demo) y actualizar `spec/plan/tasks/changelog`
      (Dev Workflow — Documentación viva).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias (más allá de tener el demo `basa-browser-dlp/` como fuente).
- **Foundational (Phase 2)**: depende de Setup. Verifica los hechos de compatibilidad y los criterios de la
  matriz; bloquea las claims de US1/US2/US4.
- **US1 (Phase 3)**: depende de Foundational + del gateway de la 014. Superficie titular.
- **US2 (Phase 4)**: depende de Foundational + US1 (coexistencia passthrough/byok en el mismo gateway).
- **US3 (Phase 5)**: depende de Foundational; usa `/gw/inspect`/`/gw/whoami` del gateway. Independiente de
  US1/US2 (otra superficie).
- **US4 (Phase 6)**: depende de US1–US3 (para asentar FUNCIONA/PARCIAL) y de US5 (para NO/roadmap de Gemini).
- **US5 (Phase 7)**: depende de US3 (mismo patrón de adapters); documentación/roadmap.
- **Polish (Phase N)**: depende de los user stories deseados.

### User Story Dependencies

- **US1 (P1)**: tras Foundational. Superficie base_url titular.
- **US2 (P1)**: tras Foundational + US1 (la exclusión `x-basa-*` protege la coexistencia con US1).
- **US3 (P1)**: tras Foundational; superficie browser, testeable independiente.
- **US4 (P2)**: tras US1–US3 (+ US5 para la entrada Gemini).
- **US5 (P3)**: tras US3; aditivo/roadmap.

### Within Each User Story

- Tests (⚠️) escritos y FALLANDO antes de implementar.
- El ruteo base_url (US1/US2) antes que la consolidación de la matriz (US4).
- Los adapters de la extensión antes de la consolidación de Gemini (US5).

### Parallel Opportunities

- Setup: T002 [P].
- Tests de cada story marcados [P] corren en paralelo (archivos distintos).
- US3 (extensión) puede desarrollarse en paralelo a US1/US2 (base_url) una vez cerrada Foundational
  (otra superficie, mismo monitor).

---

## Parallel Example: User Story 2

```bash
# Tests de US2 juntos (distintos archivos):
Task: "Integration auto-byok por virtual key en tests/integration/test_auto_byok.py"
Task: "Integration exclusión x-basa-* / coexistencia en tests/integration/test_xbasa_exclusion.py"
Task: "Integration key-in-URL de Copilot en tests/integration/test_key_in_url.py"
```

---

## Implementation Strategy

### MVP First (US1 + US2 + US3)

1. Phase 1 Setup → Phase 2 Foundational (hechos de compatibilidad + criterios de la matriz).
2. Phase 3 US1 (Claude Code passthrough) + Phase 4 US2 (Copilot auto-byok) → superficies base_url con
   coexistencia protegida.
3. Phase 5 US3 (extensión MV3) → superficie browser.
4. **STOP & VALIDATE**: Claude Code paga por suscripción y se firewallea; Copilot en byok (Ask); la
   extensión enmascara ChatGPT/Claude web (incl. título); todo en el mismo monitor.

### Incremental Delivery

1. Foundational → hechos verificados.
2. US1 + US2 → base_url (passthrough + auto-byok), **MVP** de coding tools.
3. US3 → extensión (web apps), **MVP** de browser.
4. US4 → matriz de compatibilidad (contrato de onboarding).
5. US5 → Gemini roadmap (aditivo).

### Parallel Team Strategy

Tras Foundational: Dev A → US1+US2 (base_url en el backend); Dev B → US3 (extensión MV3 + endpoints); Dev C
→ US4 (matriz) a medida que A/B asientan estados. US5 lo documenta quien cierra la extensión.

---

## Notes

- [P] = archivos distintos, sin dependencias.
- [Story] mapea cada tarea a su user story para trazabilidad.
- Verificar que los tests ⚠️ fallan antes de implementar.
- **Evidencia del demo**: `gatelite-salud-eu/backend/src/api/gateway.py` (ruteo, auto-byok, identidad,
  detección por UA, `/gw/whoami`, `/gw/inspect`) y `basa-browser-dlp/` (extensión MV3). Esta feature
  **porta** ese comportamiento; no inventa superficies nuevas.
- **Excepción única ya acotada**: el passthrough de suscripción (proxy propio) lo autorizó la 014; esta
  spec lo consume desde el cliente sin abrir proxy propio nuevo.
- **Honestidad SDD**: Gemini web y Claude Desktop (MCP) son **roadmap documentado** en la matriz, no
  entregables de esta feature.
