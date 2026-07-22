<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at specs/025-partner-enablement-docs/plan.md
<!-- SPECKIT END -->

# Acuerdo de trabajo del equipo (humanos + agentes)

Reglas que TODA sesión de trabajo en este repo respeta, sea de JF, Cristian o Falime
(módulos y ownership: `.github/CODEOWNERS`; roadmap: `specs/ROADMAP-guardian.md`).

## SDD siempre

Toda feature va por Spec-Kit completo: spec → plan → tasks → implement, con los
skills `.agents/skills/speckit-*` (no ediciones manuales de los artefactos). TDD
por user story; el trabajo termina en PR — jamás commits directos a main.

## Definition of Done — la documentación de producto es PARTE de la feature

La doc de `docs/docs/**` **se vende** con el producto. Una feature NO está terminada
hasta que:

1. Las páginas del sitio que su cambio afecta están **actualizadas** (curado
   marca-neutro, template GUÍA/RUNBOOK de `docs/README.md`, leyenda 🟢/🟡/🔵 honesta —
   jamás subir un estado que el código no respalde).
2. `make -C deploy check-docs` está **verde** (estructura, naming, 0-egress, deriva
   de references — el linter hace cumplir el template, no hace falta memorizarlo).
3. Si la feature cambió la API o `.env.example`: `make -C deploy docs-refs` corrido
   (el check de deriva lo exige igual).

El template de tasks (`.specify/templates/tasks-template.md`) ya genera esta task en
la fase Polish de toda spec nueva — si tu spec en vuelo no la tiene, agregala.

**Por qué es regla dura**: en la review de la 022 (2026-07-20), la doc describía como
"🔵 sin wirear" un módulo que llevaba HORAS mergeado y fail-closed. Doc stale en un
producto que se vende por su honestidad = bug de severidad alta.

## El gate del release es la verdad

`make -C deploy check` (artefactos) + `docker compose run --rm --no-deps backend
pytest tests/ -q` (suite) verdes antes de pedir merge. Los checks de white-label
(naming neutro, lista compartida `deploy/release/checks/prohibited_names.txt`) y de
secretos aplican a TODO artefacto publicado, docs incluida.
