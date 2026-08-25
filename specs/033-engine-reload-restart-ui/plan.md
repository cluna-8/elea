# Implementation Plan: El motor aplica los cambios solo — reload supervisado + estado en la UI

**Branch**: `033-engine-reload-restart-ui` | **Date**: 2026-08-24 | **Spec**: [spec.md](./spec.md)

**Input**: spec.md con **D1 sellada por JF el 24-ago** (`D1 = a`, botón solo-motor; constancia en
PR #242, comment 5392294627). La evidencia de código de la spec fue re-verificada contra
`origin/main@5fae89a` (re-ancladas el 24-ago tras la entrega de los 9 PRs: #267 insertó el
bloque de región y corrió `compose.prod.yml` +7 líneas); donde una línea derivó, acá va la vigente.

## Summary

Un **supervisor** (~50-80 líneas, cero deps nuevas) pasa a ser el entrypoint del motor: vigila el
mtime de `config.yaml`, coalesce cambios, valida el YAML con el intérprete de la propia imagen y
relanza litellm con drenaje. Config inválido ⇒ NO relanza y publica el error. El estado viaja por
un volumen nuevo `engine_status` (motor rw / backend ro) que el backend expone en
`GET /api/v1/models/status`; el disparo a demanda va por sentinel en el volumen `litellm_config`
que el backend ya monta rw (`POST /api/v1/models/apply`). La UI (Modelos & Ollama) muestra
«Aplicando cambios…» / error real y gana el botón **«Aplicar cambios del motor»** (D1=a).
Jamás backend→Docker (restricción #50). Cierra #70 y flipea 2 nodos del árbol.

## Technical Context

**Language/Version**: Python 3.12 (backend FastAPI); supervisor = script Python standalone que
corre DENTRO del container del motor (PyYAML ya es dependencia de LiteLLM — cero deps nuevas);
frontend React (`ModelsPage.tsx`).

**Storage**: sin cambios de schema. Estado = `status.json` en volumen `engine_status`; disparo =
sentinel `apply.trigger` en volumen `litellm_config`.

**Testing**: `cd backend && pytest tests/ -q` (unit + contract + integration); SC-001/002/003
contra stack dev real (evidencia E2E en el PR).

**Constraints**: `docker.sock` prohibido (veredicto #50, restricción dura — SC-005 revisable por
diff de compose) · config del motor conserva su `:ro` deliberado · un YAML roto jamás deja el
motor caído (el proceso viejo sigue sirviendo) · **principio wizardable (JF 24-ago)**: toda la
superficie nueva es API-first — el botón es un `POST` que el wizard podrá disparar sin UI, y las
perillas viven en el env del cliente que el wizard escribe al instalar.

## Puntos de anclaje medidos (origin/main@5fae89a, 24-ago)

| Qué | Dónde |
|---|---|
| Dolor del instalador (paso manual en rojo) | `deploy/release/INSTALL-CAMARA.md` exigía `docker restart camara-litellm-1` tras cada alta — eliminado por T008 (PR #311) + fila *«Playground "no hace nada" tras alta de modelo»* de la tabla **Troubleshooting exprés** |
| GOTCHA en código | `backend/src/api/chat.py:2154` («el motor lee config.yaml al arrancar») |
| Escritores del config — ya atómicos (`1151b1e`) | `escribir_atomico` (`backend/src/services/atomic_file.py`), importado por `chat.py:23` y `auto_router_service.py:39` |
| Mounts | backend `litellm_config` **rw** (`compose.prod.yml:119-123`) · motor `litellm_config:/app/config`**`:ro`** (`:220`) · entrypoint directo `litellm --config …` (`:225`) |
| Imagen del motor | stock pinneada (`LITELLM_IMAGE`, `:164`) — NO hay Dockerfile custom del motor: el supervisor viaja en el **bundle** (mismo canal templado que `litellm/extensions/`), no en imagen nueva |
| Namespace `BASA_ENGINE_*` YA EXISTE | admisión al motor, env del **backend** (`compose.prod.yml:43-51`, `test_engine_admission_wiring.sh`) — mismo componente («engine» = motor), proceso distinto: las perillas nuevas las lee el **supervisor** en el container del motor. Documentar el deslinde donde se documenten |
| Deslinde de liveness | `GET /analytics/engine-status` (`backend/src/api/analytics.py:289`) = vivo/muerto vía `/health/readiness` del motor; el endpoint nuevo dice **qué está haciendo** |
| UI | `frontend/src/pages/ModelsPage.tsx` |
| Gating de rol | vitrina `config_producto` (`backend/src/auth/matrix.py:42` — ya cubre `router_config`); el harness FR-005 de la 017 exige **fila en la matriz por endpoint nuevo** (endpoint sin fila = harness rojo) |
| Vírgenes (grep = 0) | `docker.sock` en `backend/`+`deploy/` · `models/status` en `backend/src`+`frontend/src` |

## Diseño del mecanismo

1. **Supervisor** (`litellm/supervisor.py`, junto a `extensions/` — mismo canal de bundle; Jeff
   puede mover la ubicación si el templado lo pide): loop watch por mtime de
   `/app/config/config.yaml` + sentinel `apply.trigger` → coalescencia
   (`BASA_ENGINE_APPLY_DEBOUNCE_SECONDS`, default 5) → `yaml.safe_load` de validación → `SIGTERM`
   al proceso litellm con drenaje (`BASA_ENGINE_DRAIN_SECONDS`, default 30) → relanzamiento.
   `BASA_ENGINE_AUTORELOAD=off` ⇒ ignora mtime, solo sentinel (botón). Escribe `status.json`
   (`state ∈ idle|applying|error`, `ts`, `last_error`, `config_hash`) en `/app/status`.
2. **Estado observable**: volumen nuevo `engine_status` — motor **rw**, backend **ro**. Backend:
   `GET /api/v1/models/status` lee `status.json` y lo sirve con el gating de `config_producto`.
3. **Disparo a demanda**: `POST /api/v1/models/apply` escribe el sentinel vía `escribir_atomico`
   en el volumen `litellm_config` que el backend ya monta rw. El supervisor lo consume desde su
   lado `:ro` (lo detecta por mtime; el borrado del sentinel lo hace el backend en el próximo
   apply — el supervisor jamás escribe en ese volumen).
4. **Endpoints**: extender `backend/src/api/router_config.py` (ya gateado por `config_producto`)
   antes que estrenar router — si Jeff decide router nuevo, entra al harness FR-005 (15→16
   routers) y a la matriz EN el mismo PR.
5. **UI**: `ModelsPage.tsx` — banner «Aplicando cambios…» + error real con timestamp + botón
   «Aplicar cambios del motor» (D1=a); polling simple de `/models/status` mientras el estado no
   sea `idle`.

## Constitution / Gates

- **Área de riesgo**: disponibilidad del motor + drenaje de streams en vuelo (streaming-adyacente)
  ⇒ **el supervisor lo escribe Jeff** (lead), no un junior. Backend/UI no son superficie caliente.
- **Decisiones de producto**: D1 sellada 24-ago — ningún PR de esta spec introduce decisión nueva
  ⇒ elegible para merge autónomo con CI verde + gate del manager.
- **Gate del manager**: cross-familia proporcional — completo en el PR del supervisor (SC-002/003
  con evidencia), liviano en backend/UI.
- **QA Bob**: SÍ hay superficie visible nueva (banner + botón en Modelos) ⇒ veredicto por
  personas requerido en el PR de UI (DevFlow §5.6).
- **Costura Factory/Falime (FR-007)**: el próximo drop del bundle lleva JUNTAS escritura atómica
  (`1151b1e`) + supervisor — la Cámara corre hoy la imagen anterior a `1151b1e`; un supervisor
  sobre escritura no-atómica leería YAML cortado. Retest E2E del bundle amd64 lo coordina el
  manager.

## Project Structure

### Documentation (this feature)

```text
specs/033-engine-reload-restart-ui/
├── spec.md              # sellada 24-ago (D1=a)
├── plan.md              # este archivo
└── tasks.md             # descomposición para el equipo de Jeff
```

### Source Code (repository root)

```text
litellm/supervisor.py                      # FR-001: watch + coalescencia + validación + drenaje
deploy/docker/compose.prod.yml             # entrypoint :225 → supervisor · volumen engine_status · knobs
backend/src/api/router_config.py           # GET /models/status + POST /models/apply (gating config_producto)
backend/src/auth/matrix.py                 # filas nuevas (harness FR-005 las exige)
frontend/src/pages/ModelsPage.tsx          # banner + error + botón (D1=a)
backend/tests/{unit,contract,integration}/ # RED→verde por fase (ver tasks.md)
deploy/clients/*/client.env.example · docs de producto · INSTALL-CAMARA.md (pierde el restart manual)
```

**Structure Decision**: un script nuevo + un volumen nuevo; cero módulos backend nuevos (se
extiende el router existente), cero deps, cero cambios de schema.

## Complexity Tracking

Sin violaciones. El riesgo real es operativo (relanzar el motor con tráfico en vuelo) — por eso
el drenaje tiene SC propio (SC-004, medible en la receta fría de La ITV pre-gate-250) y el
supervisor es superficie de lead.
