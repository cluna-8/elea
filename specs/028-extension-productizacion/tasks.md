---
description: "Task list — 028 Productización de la extensión de navegador"
---

# Tasks: Productización de la extensión de navegador (028)

**Input**: [spec.md](./spec.md), [plan.md](./plan.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: incluidos donde aportan (contrato whoami, regresión expires, gate white-label). La extensión MV3 se verifica **viva en Chrome** contra un gateway real (patrón de la 019/024), no por unit tests del navegador.

**Orden**: por prioridad del piloto — US1/US3 (entregable) → US2 (conexión) → US4/US5 (honestidad/bloqueos) → US6/US8a (sesión/endurecimiento).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede correr en paralelo (archivo distinto, sin dependencia)
- Rama: `028-extension-productizacion` (worktree desde `dev-fran`). Nunca commit directo a `main`.

---

## Phase 1: Setup

- [ ] **T001** [Setup] Crear/actualizar `deploy/clients/camara-comercio/brand.json` con la marca **cc-guardian**: nombre visible, descripción (≤132 chars, sin "PoC"), íconos 16/48/128 del partner. Es la fuente del render de la extensión (US1).
- [ ] **T002** [P] [Setup] Generar par RSA por partner para `manifest.key` (ID estable); pública base64 → al render, privada **fuera del repo** (misma custodia que las claves de licencia). Documentar dónde vive.

## Phase 2: Foundational (baseline verificado en dev-fran)

- [ ] **T003** [Foundational] Confirmar en `dev-fran` el baseline que la 028 asume: `gw_inspect` bloquea con `{ok:false, blocked, blocked_by_layer, motivo}` (027, inspect.py) y `whoami` existe (inspect.py:134). Si algo no está, es dependencia de la 027, no de esta feature.

**Checkpoint**: base lista — las historias pueden arrancar.

---

## Phase 3: User Story 1 - Paquete white-label por partner + bundle (P1) 🎯 entregable

**Goal**: un comando produce `extension-<slug>.zip` con la marca del partner (sin URL) y viaja en el bundle.

**Independent Test**: `make -C deploy build-extension-brand BRAND=camara-comercio` produce un zip instalable con la identidad de Cámara y con `manifest.key`; aparece en el MANIFEST del bundle con su sha256.

- [ ] **T004** [US1] `deploy/release/render_extension_brand.sh <slug> <brand.json>`: copia `extension/` a `deploy/clients/<slug>/rendered/extension/`, sustituye `manifest.name`/`description`/`icons` desde el brand-pack, **no** hornea URL, emite `extension-<slug>.zip`.
- [ ] **T005** [US1] Embeber `manifest.key` (pública base64 de T002) en el render → ID de extensión estable entre carpetas.
- [ ] **T006** [P] [US1] Target `build-extension-brand` en `deploy/Makefile` que invoca el render.
- [ ] **T007** [US1] `deploy/release/bundle.sh`: incluir `extension-<slug>.zip` en el bundle y listarlo en el MANIFEST con sha256; actualizar `checks/test_airgapped_bundle.sh`.
- [ ] **T008** [US1] Versión de la extensión con **fuente única** (`manifest.version`); quitar cualquier duplicación.

**Checkpoint**: el entregable ya lleva la extensión del partner.

---

## Phase 4: User Story 3 - Cero marca del fabricante + US7 gate (P1 / P2)

**Goal**: el zip del partner no filtra la marca del fabricante; un gate lo verifica.

**Independent Test**: un commit que reintroduzca "Basa Guard" en el zip pone `make check-whitelabel` en rojo.

- [ ] **T009** [US3] Parametrizar por marca los textos horneados de `extension/` que hoy dicen el fabricante: `manifest.default_title` ("Basa Guard"), comentarios/strings visibles, `README.md`. Lo no-visible (nombres de variables internas) queda.
- [ ] **T010** [US7] `deploy/release/checks/test_extension_whitelabel.sh`: descomprime el zip y falla ante `prohibited_names.txt` **+** lista de marca del fabricante (`basa`, `basa guard`, `PoC`, `localhost`); ampliar `prohibited_names.txt` o lista separada de fabricante; engancharlo en `make check-whitelabel`.

**Checkpoint**: white-label verificado por gate.

---

## Phase 5: User Story 2 - Conexión configurada por el usuario (P1)

**Goal**: la URL editable conecta de verdad (agnóstico) vía permiso de host en runtime.

**Independent Test**: instalar el zip, ingresar URL+key, conceder el permiso, enmascarar; repetir con otro gateway.

- [ ] **T011** [US2] `extension/manifest.json`: agregar `optional_host_permissions` (patrón que cubra https/http hosts); quitar el `host_permissions` clavado a `localhost:8091`.
- [ ] **T012** [US2] `extension/background.js` / `popup.js`: en el gesto **Conectar**, `chrome.permissions.request({origins:[host+"/*"]})` para el host ingresado; el SW usa el host de storage para el fetch; cambiar de host vuelve a pedir permiso.
- [ ] **T013** [US2] Validación: rechazar URL remota no-`https` (permitir `http` solo local); mensaje claro si el usuario deniega el permiso (no fallo silencioso).
- [ ] **T014** [US2] `extension/config.js`: default de URL **editable** (no fijo); pre-cargable con la URL de Cámara. Actualizar el comentario "tocar 2 cosas" (ya no aplica: host por permiso en runtime).

**Checkpoint**: agnóstico y conectando contra un gateway real.

---

## Phase 6: User Story 4 - Chip de honestidad (P1)

**Goal**: el panel muestra el nivel real ("detección por patrones"), tomado del server.

**Independent Test**: con la extensión conectada, el chip es ámbar "Detección por patrones · cobertura parcial", no verde.

- [ ] **T015** [P] [US4] Contract test `backend/tests/contract/test_whoami_proteccion.py`: `whoami` devuelve `proteccion.deteccion=="patrones"`, `detalle.endswith(_PISO_SIGUE)`, sin nombres de motor. (Escribir primero, debe fallar.)
- [ ] **T016** [US4] `backend/src/api/inspect.py` `gw_whoami`: agregar bloque `proteccion` (regla plano gateway + `pii_detection.requires_service is None` ⇒ "patrones"; copy desde `governance_status`; `capas_delegadas` de las delegables en suscripción). Ver [contracts/whoami-proteccion.md](./contracts/whoami-proteccion.md).
- [ ] **T017** [US4] Extensión (`popup.js` + panel de `guardia-main.js`): render del chip **ámbar** desde `whoami.proteccion`; **fallback "patrones"** si el campo falta; nunca hardcodear el `detalle`.

**Checkpoint**: honestidad-por-plano en la superficie navegador.

---

## Phase 7: User Story 5 - Motivo real de bloqueo (P1) — server ya hecho (027)

**Goal**: un bloqueo de política muestra el motivo del server, no "servicio no disponible".

**Independent Test**: disparar un bloqueo (AI-Act/secreto) y ver el motivo; un fallo sin `blocked` muestra "servicio no disponible".

- [ ] **T018** [US5] `extension/guardia-main.js`: ante la respuesta de `/inspect`, distinguir `{ok:false, blocked:true, motivo}` (mostrar `motivo` del server) de `ok:false` sin `blocked` (mostrar "servicio no disponible"); **nunca** renderizar `blocked_by_layer` crudo; conservar el fail-closed actual (`basa-guard.js:115-118`) para respuestas viejas.
- [ ] **T019** [P] [US5] Verificación e2e viva: los dos caminos (bloqueo con motivo vs servicio caído) contra el `camara-ensayo` con 027 activa.

**Checkpoint**: la ventana de mentira 027↔extensión queda cerrada (se instalan juntas).

---

## Phase 8: User Story 6 - Sesión (P1)

**Goal**: distinguir sin-red de sin-permiso; revalidar sola; un solo dueño del estado.

**Independent Test**: cortar red (conserva key), revocar plaza (borra key, mensaje propio), reabrir navegador (revalida).

- [ ] **T020** [US6] `extension/background.js`: tres estados `conectado`/`no_verificado`(red, key conservada)/`desconectado`(401 **o** 403, key borrada); 403 con mensaje distinto ("tu plaza ya no está activa") del 401 ("key inválida"); corte de red **no** borra key.
- [ ] **T021** [US6] `chrome.alarms` (~30 min) + `chrome.runtime.onStartup` revalidan la sesión. **No** keepalive artificial (el SW ya es correcto).
- [ ] **T022** [US6] Dueño único del estado = **service worker**; `popup.js` deja de escribir `basa_connected` (solo lee/observa).

**Checkpoint**: offboarding por revocación funciona; red intermitente no desloguea.

---

## Phase 9: User Story 8a - Backend rechaza keys vencidas (P2)

**Goal**: una key vencida es rechazada, indistinguible de una inexistente.

**Independent Test**: key con `expires_at` pasado → mismo 401 que una key inválida.

- [ ] **T023** [P] [US8] Regresión `backend/tests/...`: key vencida → 401 indistinguible (sin oráculo).
- [ ] **T024** [US8] `backend/src/api/gateway.py` `_resolve_attribution` (línea 356): sumar `expires_at IS NULL OR expires_at > now()` al filtro.

> **US8b / US9 (rechazo por superficie navegador)**: DIFERIDO — depende de un `tool_type` de navegador que no existe (coordinar con Cristian antes del freeze 027). Fuera del alcance del piloto.

**Checkpoint**: offboarding por expiración.

---

## Phase 10: Polish & Cross-Cutting

- [ ] **T025** [P] **Docs DoD (OBLIGATORIO)**: actualizar `docs/docs/integrations/index.md` §3.3 + `docs/docs/operations/index.md` (config URL+key, prompt de permiso de host, chip de honestidad, motivos de bloqueo, offboarding) marca-neutro; `make -C deploy check-docs` 9/9.
- [ ] **T026** `speckit-analyze` — consistencia spec↔plan↔tasks antes de implementar.
- [ ] **T027** Validar `quickstart.md` end-to-end en `camara-ensayo` (compose selfhosted con 027 + extensión cargada).
- [ ] **T028** [P] Revisión adversarial (Codex local) + gate white-label + suite backend verde antes de merge a dev-fran.

---

## Dependencies & Execution Order

- **Setup (T001-T002)** → **Foundational (T003)** → historias.
- **US1 (T004-T008)** primero: es el entregable y no depende de otras.
- **US3/US7 (T009-T010)** derivan de US1 (necesitan el render).
- **US2 (T011-T014)** independiente; se puede paralelizar con US1.
- **US4 (T015-T017)**: server (T016) antes del chip (T017); test T015 primero.
- **US5 (T018-T019)**: solo extensión (server hecho); independiente.
- **US6 (T020-T022)** independiente.
- **US8a (T023-T024)** independiente, chico.
- **Polish (T025-T028)** al final.

### Parallel Opportunities (con workflows/minions)

- US1, US2, US5, US6 tocan archivos distintos → paralelizables una vez hecho el Setup.
- US4 server (T016, backend) ‖ US1 (deploy) ‖ US6 (extensión) → tres zonas distintas.
- Los tests marcados [P] corren juntos.

## Implementation Strategy (MVP piloto)

1. Setup + Foundational.
2. **US1+US3 (entregable)** → el bundle ya lleva la extensión de Cámara → **STOP & VALIDATE**.
3. US2 → conecta contra el gateway real.
4. US4+US5 → honestidad + bloqueos.
5. US6 → sesión/offboarding.
6. US8a si hay tiempo.
7. Polish (docs, analyze, ensayo, review) → merge a `dev-fran`.

## Fuera de alcance (recordatorio)

- **Gemini** (adapter nuevo) — fast-follow post-piloto.
- **US9** (superficie canónica de navegador + migración + Cristian) — fast-follow.
- **Fixes de piloto** (timeout local→param, costo local=0, `sk-proj-`) — batch directo aparte (tarea #59), no SDD.
- **Hot-reload** — diferido (solución de Cris, después del plan).
