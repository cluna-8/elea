# Convenciones de ramas, commits y PRs

## Ramas (GitHub Flow)

- `main` es la única rama permanente y debe estar siempre instalable.
- Ramas cortas: vida ideal < 3 días. Si una tarea necesita más, se parte en tareas mergeables.
- Una rama = una tarea. Prohibido rama por persona (`dev-fulano`) o por país.
- Nombres: `NNN-descripcion` si implementa tareas de una spec (ej. `033-engine-reload`), `fix/masking-fallback`, `chore/ci-minima`, `docs/runbook-windows`.
- La rama muere al mergear. Merge por PR siempre, incluso entre jefes técnicos.

## Commits y títulos de PR (Conventional Commits)

Formato: `tipo(scope): descripción en imperativo`

Tipos: `feat` (funcionalidad), `fix` (bug), `docs` (documentación), `chore` (mantenimiento/build), `spec` (specs y planes), `refactor`, `test`.

Scopes útiles del repo: `gateway`, `motor`, `extension`, `frontend`, `presidio`, `licensing`, `deploy`, `cli`, `docs`.

Ejemplos:
- `feat(motor): reload de config sin restart (spec 033, T01-T04)`
- `fix(presidio): fallar en voz alta cuando NLP degrada a regex (#63)`
- `chore(deploy): purgar scripts de licencias de imagen prod`
- `spec(017): auth hardening y RBAC multi-tenant`

## Reglas de PR

- **Tamaño**: < 400 líneas netas de **código**. Arriba de eso la review pierde efectividad (evidencia: estudios de Cisco/SmartBear). Si no entra, partir en cadena de PRs. El tope NO aplica a specs/planes SDD ni docs (`specs/**`, `docs/**`, `*.md`): son largos por diseño y no se recortan para cumplir un lint. Si algún día se automatiza el chequeo, debe excluir esas rutas.
- **Contenido**: un PR = un propósito. No mezclar refactor con feature.
- **Issue**: todo PR linkea su issue (`Closes #NN`). Sin issue no hay PR (crear el issue primero, aunque sea de 2 líneas).
- **Template**: usar `.github/PULL_REQUEST_TEMPLATE.md` (qué / por qué / cómo probar / checklist DoD).
- **Review**: 1 aprobación del otro jefe técnico si toca su área o una costura; gate de Cristian si toca claves/firma/auth (regla 3).
- **Etiquetas**: `depto:guardian` o `depto:factory`; ambas si es costura.
- **CODEOWNERS**: PR que mueve archivos entre áreas lo actualiza en el mismo PR (regla 5).

## Definition of Done

Un PR está terminado cuando:

1. `pytest tests/ -q` verde (~297 tests).
2. `make -C deploy check-docs` verde y páginas de `docs/docs/**` afectadas actualizadas. Doc desactualizada = bug de severidad alta (regla desde review de 022, 20-jul-2026).
3. Checklist del template completa.
4. Si la feature cambia el onboarding o la instalación: runbook actualizado.

Para el corte de release el gate es `make -C deploy check` completo + pytest verdes antes de pedir merge.

## Cadencia de comunicación

- Async primero: decisiones en issues/PRs/ADRs, no en Slack. Slack es para coordinar, no para decidir — si en Slack se tomó una decisión, alguien la copia al issue o ADR.
- Weekly de 30 min entre los 3: estado de apuestas, bloqueos, próximo betting.
- Fin de ciclo: demo corta de lo entregado (aunque sea entre los 3).
