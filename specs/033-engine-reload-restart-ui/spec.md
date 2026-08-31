# Feature Specification: El motor aplica los cambios solo — reload supervisado + estado visible en la UI

**Feature Branch**: `033-engine-reload-restart-ui`

**Created**: 2026-08-18

**Status**: Sellada — D1 = a (JF, 24-ago-2026; constancia en PR #242, comment 5392294627) · plan.md + tasks.md en este directorio

**Anclas**: las citas `archivo:línea` de este documento están medidas contra `origin/main@5fae89a`. Una cita sin su árbol es ambigua: `compose.prod.yml` ya corrió +7 líneas una vez (#267). Ante «esa línea dice otra cosa», comparar contra ESTE árbol antes de dudar del diseño.

**Input**: research del 30-jul sellado en el issue [#50](https://github.com/DrZuzzjen/sentinel-guardian/issues/50)
(veredicto: wrapper-supervisor; socket-proxy DESCARTADO por seguridad) + issue
[#70](https://github.com/DrZuzzjen/sentinel-guardian/issues/70) (botón de reinicio, puente a la 033) +
prerrequisito de escritura atómica YA PAGO (`1151b1e`, en `main`) + dolor documentado del piloto
(`deploy/release/INSTALL-CAMARA.md`).

---

## El problema, con evidencia (18-ago, líneas verificadas en el código)

1. **El alta de modelo por UI escribe un config que el motor no relee**: el instalador tiene la
   instrucción en rojo *«🔴 CLAVE — tras CADA alta de modelo por la UI, reiniciar el motor:
   `docker restart camara-litellm-1`»* (`INSTALL-CAMARA.md`, paso eliminado por T008 — PR #311) y su tabla de troubleshooting
   dedica una fila al síntoma (*«Playground "no hace nada" tras alta de modelo»*). El propio código
   lo llama **GOTCHA OPERATIVO** (`backend/src/api/chat.py:2118-2119`) y el compose lo documenta:
   *«la UI escribe acá y el motor lo toma en su próximo restart»* (`deploy/docker/compose.prod.yml:118-123`).
2. **El restart manual exige SSH al host del cliente** — rompe la promesa de Fase 0 «el partner
   configura todo solo» en su caso más frecuente: dar de alta un modelo. Es el dolor #1 nombrado
   del onboarding del piloto (paquete 033/034, `ROADMAP-guardian.md`).
3. **«Que lo haga el motor» no existe**: LiteLLM NO tiene hot-reload del config sin DB — verificado
   leyendo el código de la imagen pinneada en el research de #50. La opción file-based + relanzamiento
   es la única real con la decisión vigente (config como archivo, sin DB del motor para modelos).
4. **Lo que ya está pago y lo que hay hoy**: los 4 escritores del config escriben ATÓMICO desde
   `1151b1e` (`backend/src/services/atomic_file.py`: temporal en el mismo dir + fsync + `os.replace`) —
   sin eso, un reload podía leer YAML cortado. El motor monta el config **`:ro`**
   (`compose.prod.yml:220`) y arranca con entrypoint directo `litellm --config …` (`compose.prod.yml:225`).
   `docker.sock` no aparece en `backend/` ni `deploy/` (grep = 0). `GET /models/status` no existe
   en ningún plano (grep = 0).
5. **Restricción heredada, dura**: montar `docker.sock` al backend — aun detrás de un proxy acotado —
   quedó **DESCARTADO por seguridad** en el veredicto de #50 (un backend comprometido podría matar
   contenedores del cliente). Esta spec la hereda como restricción de diseño, no como preferencia.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - El alta de modelo termina en modelo usable, sin SSH (Priority: P1)

Como admin del partner, doy de alta un modelo por la UI y en menos de un minuto ese modelo responde
en el Playground — sin tocar consola, sin avisar a nadie. El flujo documentado del instalador
«alta → restart → probar» pasa a ser «alta → probar».

**Why this priority**: es el nodo P1 del tech tree («Alta de modelos sin reiniciar») y la causa del
paso manual más frágil de la operación del piloto.

**Acceptance Scenarios**:

1. **Given** una instalación viva, **When** el admin da de alta un modelo por la UI, **Then** el
   supervisor detecta el config nuevo, lo valida, relanza el motor con drenaje y el modelo nuevo
   responde en el Playground — cero intervención manual.
2. **Given** tres altas seguidas en ráfaga, **When** el supervisor coalesce los cambios, **Then**
   hay UN solo relanzamiento, no tres.
3. **Given** un config inválido (YAML roto o esquema que el motor rechazaría), **When** el supervisor
   valida, **Then** NO relanza: el motor viejo sigue sirviendo con el config anterior y el error se
   ve en la UI (US3). Un YAML roto jamás deja el motor caído.

### User Story 2 - «Aplicar cambios ahora»: el botón honesto (Priority: P1 — alcance según D1)

Como admin, tengo en Modelos & Ollama un botón que fuerza el ciclo de aplicación a demanda — para
cuando no quiero esperar la ventana de coalescencia o el watch automático quedó apagado
(`SENTINEL_ENGINE_AUTORELOAD=off`). Mismo mecanismo del supervisor, cero privilegios nuevos.

**Acceptance Scenarios**:

1. **Given** cambios de config pendientes, **When** el admin pulsa «Aplicar cambios», **Then** el
   estado pasa a `applying` y vuelve a `idle` con el motor sirviendo el config nuevo.
2. **Given** un config inválido, **When** se pulsa el botón, **Then** el motor sigue vivo y el error
   de validación aparece con su causa real.

### User Story 3 - «Aplicando cambios…»: el estado deja de ser invisible (Priority: P1)

Como admin, veo en la página Modelos qué está haciendo el motor (aplicando / listo / error, con la
causa) en vez del silencio actual — hoy el síntoma de un alta fallida es que el Playground «no hace
nada» (un 400 que la UI no muestra, `INSTALL-CAMARA.md` troubleshooting).

**Acceptance Scenarios**:

1. **Given** un apply en curso, **When** el admin mira Modelos & Ollama, **Then** ve el banner
   «Aplicando cambios…» hasta que el estado vuelve a listo.
2. **Given** una validación fallida, **When** el admin mira la página, **Then** ve el error con su
   texto real y el timestamp.
3. `GET /api/v1/models/status` responde `idle|applying|error` + timestamp + último error + hash del
   config aplicado — consumible por la UI y por el harness de La ITV.

---

## Requirements *(mandatory)*

- **FR-001 — Supervisor como entrypoint del motor** (~50-80 líneas, viaja en la imagen/bundle del
  motor): watch por mtime de `config.yaml` → **coalescencia** (default 5 s) → **validación** del
  YAML con el intérprete de la propia imagen (`python -c "yaml.safe_load(…)"` — PyYAML ya es
  dependencia de LiteLLM; cero deps nuevas) → `SIGTERM` graceful al proceso litellm con **drenaje**
  (default 30 s) → relanzamiento. Config inválido ⇒ NO relanza y publica el error. Cero privilegios
  nuevos sobre el host; `docker.sock` prohibido (restricción #50).
- **FR-002 — Estado observable sin hablar con Docker**: volumen chico nuevo `engine_status`
  (motor **rw** / backend **ro** — el config conserva su `:ro` deliberado de `compose.prod.yml:220`).
  El supervisor escribe `status.json` (`state`, `ts`, `last_error`, `config_hash`); el backend lo
  expone en `GET /api/v1/models/status` con el mismo gating de rol que la página Modelos. Deslinde:
  `GET /analytics/engine-status` sigue siendo el vivo/muerto; el endpoint nuevo dice **qué está
  haciendo**.
- **FR-003 — Disparo a demanda por el mismo canal de datos**: el backend escribe un sentinel
  (`apply.trigger`) en el volumen `litellm_config` que ya monta **rw** (`compose.prod.yml:123`); el
  supervisor lo consume desde su lado `:ro`. El botón de la UI llama `POST /api/v1/models/apply` →
  sentinel. Jamás backend→Docker.
- **FR-004 — UI**: banner «Aplicando cambios…» + error real en Modelos & Ollama, derivado de
  `/models/status` (polling simple mientras haya cambios pendientes).
- **FR-005 — Perillas y sus lectores en la misma ronda**: `SENTINEL_ENGINE_AUTORELOAD` (default `on`;
  `off` = solo botón), `SENTINEL_ENGINE_APPLY_DEBOUNCE_SECONDS` (default 5),
  `SENTINEL_ENGINE_DRAIN_SECONDS` (default 30) — documentadas en `compose.prod.yml`, los `.env.example`
  de `deploy/clients/` y la página de docs de producto correspondiente (superficie 1 del DevFlow).
- **FR-006 — Alcance del botón = D1** (menú al pie). Con la reco (a), el issue #70 se cierra con
  esta spec y el nodo del tech tree se re-lee como «aplicar cambios del motor desde la UI».
- **FR-007 — Costura Factory/Falime**: el supervisor viaja en la imagen del motor ⇒ retest E2E del
  bundle amd64. La Cámara corre hoy la imagen ANTERIOR a `1151b1e`: el próximo drop lleva las dos
  piezas JUNTAS (escritura atómica + supervisor) — un supervisor sobre escritura no-atómica leería
  YAML cortado. `INSTALL-CAMARA.md` pierde el paso de restart manual EN el mismo PR de
  implementación que lo haga verdad.

---

## Success Criteria *(mandatory)*

- **SC-001**: alta de modelo por UI → usable en Playground en **≤60 s** sin intervención manual
  (stack dev, evidencia E2E en el PR de implementación).
- **SC-002**: un YAML roto **jamás** tumba el motor — test: config inválido ⇒ proceso viejo sirve,
  `status=error`, la UI muestra la causa.
- **SC-003**: ráfaga de N altas ⇒ **1** relanzamiento (log del supervisor como evidencia).
- **SC-004**: streams en vuelo reciben cierre limpio dentro de la ventana de drenaje — cero cortes
  secos. Medible en la receta fría de La ITV pre-gate-250 (misma pasada que mide arranque en frío).
- **SC-005**: cero privilegios nuevos — el diff de compose no monta `docker.sock` ni agrega
  capabilities (revisable por diff).

---

## Decisión — SELLADA por JF el 24-ago-2026: **D1 = a**

(Canal guardian-manager, msg `c929cbb0`; constancia en PR #242, comment 5392294627. Menú
original conservado como registro de la decisión.)

**D1 — Alcance del botón** (nodo «Reinicio de contenedores desde la UI», issue #70):

- **(a) ★ RECO**: el botón es **«Aplicar cambios del motor»** — permanente, SOLO motor, vía el
  mecanismo de esta spec (cero privilegios nuevos). El dolor documentado del piloto es 100 % motor;
  el reinicio de otros servicios sigue siendo operación de host (instalador/soporte, no partner).
  El #70 se cierra con esta spec y el nodo del árbol se re-lee así.
- **(b)** botón multi-servicio (nlp-analyzer, backend, workers): exige un mecanismo backend→Docker
  que el research de #50 **descartó por seguridad**, o replicar N supervisores — superficie de
  ataque y costo crecen sin dolor documentado que los pague.

Sello esperado: **«033: tu reco»** o **«D1: b»**.

---

## Out of scope

- Reinicio de servicios distintos del motor (si D1 = a).
- Hot-reload nativo de LiteLLM / config DB-backed del motor — no existe sin DB (verificado en #50)
  y la decisión file-based sigue vigente.
- Semántica de recarga distinta al relanzamiento completo (extensiones/guardrails incluidos): el
  relanzamiento ES la semántica — parcialidades quedan fuera.
- El tarifario #73 — comparte nodo padre en el árbol («alta completa») pero es alcance aparte.

## Dependencies

- `1151b1e` (escritura atómica) — **pago, en `main`**.
- Retest E2E del bundle amd64 — costura con Factory/Falime (FR-007).
- Issue [#70](https://github.com/DrZuzzjen/sentinel-guardian/issues/70) — lo cierra esta spec (D1=a).
- Nodos del tech tree: «Alta de modelos sin reiniciar (y completa)» + «Reinicio de contenedores
  desde la UI» (`specs/ROADMAP-pisos.md`).

**Estimación heredada del research (#50)**: ~2-2.5 días, incluido el retest del bundle.
