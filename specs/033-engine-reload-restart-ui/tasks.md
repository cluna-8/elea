# Tasks: El motor aplica los cambios solo — reload supervisado + estado en la UI

**Input**: spec.md (D1=a sellada 24-ago) + plan.md (anclas medidas @f6a5f30)

**Ejecuta**: equipo de Jeff. Regla de siempre: brief cerrado + worktree propio + tests RED→verde
en el MISMO PR + 1ª línea merged-green de Jeff antes del gate del manager.

**Tests**: obligatorios en cada PR (código nuevo = tests nuevos, backend sin excepciones).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable (archivos distintos, sin dependencia)
- **[GATE]**: no es código de esta spec — es condición de costura/cierre

---

## Phase 1: Foundational — el supervisor existe y es inofensivo (bloquea todo)

- [ ] T001 **Supervisor** (`litellm/supervisor.py`) — **lo escribe Jeff** (drenaje de streams =
      streaming-adyacente): watch mtime `config.yaml` + sentinel → coalescencia
      (`BASA_ENGINE_APPLY_DEBOUNCE_SECONDS=5`) → `yaml.safe_load` → `SIGTERM` + drenaje
      (`BASA_ENGINE_DRAIN_SECONDS=30`) → relanzamiento; `BASA_ENGINE_AUTORELOAD=off` ⇒ solo
      sentinel. Escribe `status.json` (`state/ts/last_error/config_hash`). Config inválido ⇒
      NO relanza + `state=error` con causa. Tests unit RED→verde (proceso hijo fake): válido ⇒
      1 relanzamiento · inválido ⇒ 0 relanzamientos + error publicado · ráfaga de N cambios ⇒
      1 relanzamiento (SC-003 a nivel unit) · el drain espera la ventana. La mutación
      «valida DESPUÉS de matar» debe romper los tests.
- [ ] T002 **Compose + bundle**: entrypoint del motor (`compose.prod.yml:218`) pasa al
      supervisor · volumen nuevo `engine_status` (motor **rw** / backend **ro**) · knobs FR-005
      documentadas en el bloque del MOTOR con deslinde explícito de la familia de admisión
      `BASA_ENGINE_*` del backend (`:43-51`). **SC-005 por diff**: cero `docker.sock`, cero
      capabilities nuevas.

**Checkpoint**: stack dev levanta con supervisor y sin cambios de config se comporta idéntico a
hoy (suite completa verde + smoke del stack).

---

## Phase 2: User Story 1 — alta → usable sin SSH (P1) 🎯 MVP

- [ ] T003 [US1] **E2E contra stack dev real** (evidencia: comandos + salida al PR):
      alta de modelo por UI → responde en Playground **≤60 s** sin intervención (SC-001) ·
      YAML roto ⇒ el proceso viejo sigue sirviendo + `state=error` (SC-002) · ráfaga de 3 altas
      ⇒ 1 relanzamiento en el log del supervisor (SC-003). SC-004 (cero cortes secos en drenaje)
      queda medible en la receta fría de La ITV pre-gate-250 — no bloquea este checkpoint.

---

## Phase 3: User Stories 2+3 — botón y estado visibles (P1)

- [ ] T004 [P] [US3] Backend `GET /api/v1/models/status`: lee `status.json` del volumen ro y
      responde `idle|applying|error` + `ts` + `last_error` + `config_hash`. En
      `router_config.py` (ya gateado `config_producto`); **fila nueva en `matrix.py` EN el
      mismo PR** — el harness FR-005 de la 017 la exige (endpoint sin fila = rojo). Contract +
      integration tests (status presente / volumen ausente ⇒ respuesta honesta, no 500).
- [ ] T005 [P] [US2] Backend `POST /api/v1/models/apply`: escribe sentinel `apply.trigger` vía
      `escribir_atomico` en `litellm_config` (rw). Fila en matriz ídem T004. **Wizardable**: es
      un POST puro — el wizard podrá dispararlo sin UI; test de que el sentinel aparece y de que
      el rol sin permiso recibe 403 (dependency, no inline — regla #251).
- [ ] T006 [US3+US2] UI `ModelsPage.tsx`: banner «Aplicando cambios…» + error real con
      timestamp + botón **«Aplicar cambios del motor»** (D1=a) con polling de `/models/status`
      hasta `idle`. **QA Bob por personas** en este PR (superficie visible, DevFlow §5.6).

---

## Phase 4: Barrido de lectores + costura (mismo ciclo, no después)

- [ ] T007 [P] Knobs FR-005 en `deploy/clients/*/client.env.example` + docs de producto de la
      página Modelos + `make -C deploy check-docs` verde. (Superficie 1 del DevFlow: perilla
      nueva = TODOS sus lectores en la misma ronda.)
- [ ] T008 `INSTALL-CAMARA.md` pierde el paso de restart manual (`:115`) y la fila de
      troubleshooting (`:207`) **EN el PR que lo hace verdad**; el GOTCHA de `chat.py:2154` se
      reescribe apuntando al supervisor. Issue #70 se cierra acá.
- [ ] T009 [GATE] **Retest E2E del bundle amd64** (Factory/Falime): el próximo drop lleva
      JUNTAS `1151b1e` + supervisor (la Cámara corre la imagen anterior). Lo coordina el
      manager — no bloquea los merges, SÍ el cierre de la spec.
- [ ] T010 Flip de los 2 nodos en `specs/ROADMAP-pisos.md` al mergear el último PR — coordinar
      con el tracking visual de Jeff (doble escritor conocido).

---

## Dependencies & Execution Order

- **Phase 1**: T001 → T002 (el compose apunta a un script que ya existe). Arranca cuando Jeff
  libere manos del SSO — el SSO no se frena por esto.
- **Phase 2**: T003 tras Phase 1 (es la evidencia del PR que la cierra).
- **Phase 3**: T004/T005 paralelos tras T002 (necesitan los volúmenes definidos); T006 tras
  T004/T005. No-caliente: Junior puede tomarlos con 1ª línea de Jeff.
- **Phase 4**: T007/T008 en el PR que cambia cada superficie (no PR-escoba); T009/T010 al cierre.
- **Slicing sugerido** (corte final lo decide Jeff): **PR-A** = T001+T002+T003 (motor+compose+E2E,
  Jeff) · **PR-B** = T004+T005 + su tajada de T007 (backend, Junior) · **PR-C** = T006+T008
  (UI+docs, Junior; QA Bob). GLM: NO en esta spec (supervisor = proceso/streaming; backend =
  filas de matriz auth-adyacentes).

## Notas para el que descompone

- La validación corre SIEMPRE antes de matar el proceso viejo — un YAML roto jamás deja el motor
  caído. Si un test puede pasar con el orden invertido, el test está mal.
- El supervisor jamás escribe en `litellm_config` (su lado es `:ro`); el backend jamás habla con
  Docker. SC-005 se revisa por diff en CADA PR de la spec.
- Estimación heredada del research #50: ~2-2.5 días, incluido el retest del bundle.
