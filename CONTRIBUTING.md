# Cómo trabajamos — Sentinel Guardian

Convención operativa del equipo. Dueño del documento: Cristian. Cambios a este archivo: PR con aprobación de Cristian.

## Ramas

- `main` es la única rama permanente y está **siempre instalable**.
- Ramas cortas (< 3 días de vida). Una rama = una tarea. Prohibido rama por persona o por país.
- Nombres: `NNN-descripcion` (tareas de spec), `fix/...`, `chore/...`, `docs/...`.
- Todo merge entra por PR. La rama muere al mergear.

## Commits y títulos de PR

Conventional Commits: `tipo(scope): descripción en imperativo`.

Tipos: `feat`, `fix`, `docs`, `chore`, `spec`, `refactor`, `test`.
Scopes: `gateway`, `motor`, `extension`, `frontend`, `presidio`, `licensing`, `deploy`, `cli`, `docs`.

Ejemplo: `fix(presidio): fallar en voz alta cuando NLP degrada a regex (#63)`

## PRs

1. PR < 400 líneas netas **de código**. Si no entra, se parte. El tope no aplica a specs/planes SDD ni docs (`specs/**`, `docs/**`, `*.md`): son largos por diseño. Cualquier chequeo automatizado futuro debe excluir esas rutas.
2. Un PR = un propósito. No mezclar refactor con feature.
3. Todo PR linkea su issue (`Closes #NN`). Sin issue no hay PR.
4. Labels `depto:guardian` / `depto:factory` (ambas si es costura).
5. Review: el otro jefe técnico si toca su área o una costura. **Gate de Cristian** obligatorio si toca claves de firma, keyset, RBAC de firma o auth.
6. PR que mueve archivos entre áreas actualiza CODEOWNERS en el mismo PR.

## Definition of Done

- `pytest tests/ -q` verde.
- Docs afectadas en `docs/docs/**` actualizadas y `make -C deploy check-docs` verde. Doc desactualizada = bug de severidad alta.
- Checklist del template de PR completa.

## Decisiones estructurales

- Repo nuevo solo si despliega y versiona independiente con equipo propio (hoy: solo `guardian-factory`). Todo lo demás, monorepo.
- Plugins/integraciones nuevas = módulo en el monorepo con dueño en CODEOWNERS.
- **País nuevo = perfil de configuración** (policy pack de compliance, precios, idioma) en `deploy/clients/`. Nunca rama ni fork por país.
- Toda decisión de este tipo se registra como ADR en `docs/adr/` (template ahí). Si la duda ya tiene ADR, la respuesta es el link.

## Licencias e instalaciones

La emisión de licencias es de **Falime** (Install & Factory), con gate de Cristian cuando toca custodia o claves. Cristian define las políticas de compliance por país (policy packs). Runbook completo de instalación: `Structure/guardian-metodologia/references/organizacion.md`.

## Ciclos

Trabajamos en ciclos de 2 semanas con fecha fija: se recorta alcance, no se mueve la fecha. Cristian shapea las apuestas (brief de 1 página), se decide qué entra en una reunión corta, y cada dev descompone sus tareas con autonomía. Operativa diaria (soporte, bugs de piloto) va por fuera, con límite de trabajo en curso.

## Organización

División de departamentos, router de responsabilidades y reglas de operación: `Structure/ManosALaObra-SentinelGuardian.html`. Roadmaps: `specs/ROADMAP-guardian.md` (producto, JF) y `deploy/ROADMAP-factory.md` (Factory, Falime).

## Entorno local (varios worktrees)

`docker-compose.yml` fija `container_name: ${STACK_PREFIX:-sentinel}-<svc>`. El default `sentinel-*` deja intactos a los lectores (`deploy/release/checks/test_profile_renders.sh`, `backend/tests/e2e/test_guardrail_behavior_e2e.py`).

- Un worktree paralelo: `STACK_PREFIX=<id> docker compose up …` (p. ej. `jeff223`, `qa`). **No quitar** `container_name`: Compose pasaría a `<proyecto>-<svc>-N` y rompe esos scripts.
- `-p <proyecto>` solo aísla red y volúmenes. No despega nombres ni puertos de host.
- Los puertos publicados (5433/8091/8090/4010) siguen globales. Si chocan, override **local no commiteado** de `ports` (`!reset []` o reasignar). Ya no hace falta override de `container_name` (el patrón `docker-compose.jeff018.yml`).
- Los `sentinel-backend:prod` de `deploy/` son tags de imagen, no `container_name`.

Detalle operativo: `tech-team/DevFlow-SentinelGuardian.md` § 8. Check: `scripts/check_stack_prefix.sh` (CI lo corre antes de `docker compose up`).
