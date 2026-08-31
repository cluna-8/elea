<!-- SPECKIT START -->
Specs activas de C2 (Fase 0): 018 retención con dientes (rama 018-retencion-tiers,
plan vigente specs/018-retencion-tiers/plan.md, research sellado en su research.md)
y 017 identidad con dientes (rama 017-auth-rbac-sso, spec sellada, plan pendiente).
La 035 (La ITV) sigue viva como instrumento de gates. Contexto de ciclo:
specs/ROADMAP-pisos.md (tech tree, gates 125/250/500) y specs/ROADMAP-guardian.md.
<!-- SPECKIT END -->

# Acuerdo de trabajo del equipo (humanos + agentes)

Reglas que TODA sesión de trabajo en este repo respeta, sea de JF, Cristian o Falime
(módulos y ownership: `.github/CODEOWNERS`; roadmap: `specs/ROADMAP-guardian.md`).

## SDD cuando amerita (pragmático)

Feature con superficie, contrato o decisión de diseño nueva → Spec-Kit completo:
spec → plan → tasks → implement, con los skills `.agents/skills/speckit-*` (no
ediciones manuales de los artefactos). Fix de causa clara o cambio trivial → rama
corta directa, sin spec. Criterio: si la spec no obligaría a decidir nada, no se
escribe. En ambos casos: TDD donde hay código nuevo y el trabajo termina en PR —
jamás commits directos a main. Operativa completa del depto Guardian:
`tech-team/DevFlow-SentinelGuardian.md`; convención común: `CONTRIBUTING.md`.

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
