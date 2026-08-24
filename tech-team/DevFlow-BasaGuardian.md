# DevFlow — Guardian App Ecosystem

Operativa de desarrollo del departamento Guardian. Capa **encima** de [`CONTRIBUTING.md`](../CONTRIBUTING.md) (convención común del equipo, dueño Cristian): todo lo de ahí aplica; esto añade el *cómo* interno. Si algo contradice al CONTRIBUTING, gana el CONTRIBUTING.

Alcance: solo depto Guardian. Factory (Falime) tiene su propia operativa.

## 1 · Orquestación con agentes

| Rol | Quién | Qué hace |
|---|---|---|
| Orquestación | Fable 5 (sesión principal) | Planifica, parte el trabajo, decide, verifica resultados, redacta PRs |
| Coding | **Coders del equipo de Jeff — Sonnet 5** (ruteo sellado por JF el 17-ago) | Implementación de tareas acotadas (una tarea = un agente con brief cerrado + worktree propio). Es el único equipo que codea producto con agentes: ITV mide, DevRel documenta, el wizard 037 lo lleva Cristian |
| Superficies calientes | **El líder del equipo (Jeff)**, no un coder | Auth, streaming, borrado y persistencia las escribe el líder, no se reparten. Corre sobre el tope real del runtime de agentes: **Opus 4.8** (Claude Code 2.1.217; un picker más nuevo puede ofrecer otra cosa, lo que ejecuta es esto) |
| Review adversarial | Workflow multi-agente (find → verify) | Cambios de riesgo: hallazgos independientes + verificación cruzada antes de dar por bueno |
| Aprobación | Jefe de depto (JF) | Última palabra en merges de features; en modo autónomo, OK explícito por móvil |

## 2 · SDD (Spec-Driven Development)

| Caso | Camino |
|---|---|
| Feature con superficie, contrato o decisión de diseño nueva | Spec en `specs/NNN-*/` con speckit: specify → plan → tasks → analyze |
| Bug con causa raíz clara / cambio trivial (un texto, un estilo) | Directo a rama corta, sin spec |

Criterio único: si la spec no obligaría a tomar ninguna decisión, no se escribe. (Regla vigente desde jul-2026.)

## 3 · Testing

| Regla | Detalle |
|---|---|
| Código nuevo = tests nuevos | En el mismo PR, sin excepciones para backend. Un PR de feature sin tests no está terminado aunque la suite vieja pase |
| Suites backend | `backend/tests/` — unit + `contract/` + `integration/` + `e2e/` (78 archivos). Comando real: `cd backend && pytest tests/ -q` |
| Frontend / extensión | Gap conocido: sin framework de tests. Mínimo hoy: `tsc --noEmit` verde + smoke manual descrito en el PR («cómo probar»); ESLint sin config aún (#86) — al cerrarse, entra al gate. Meta: vitest en fase 1 |
| Pre-release | Test integral E2E (routing + fallback + auditoría durable; precedente 28-jul) + ensayo de instalación si el cambio toca deploy |
| Capacidad | Gates 125/250/500 del harness = DoD de fase 0 (`specs/ROADMAP-pisos.md`). No aplican por-PR |

## 4 · Documentación — las 3 superficies

Al cerrar una feature, preguntarse SIEMPRE cuáles de las tres toca. La doc desactualizada es bug de severidad alta (regla desde la 022).

| Superficie | Audiencia | Cuándo se toca | Gate |
|---|---|---|---|
| `docs/` (mkdocs producto) | Partner/admin — **se vende** con el producto | La feature cambia API, config, operación o superficies | Ya en el DoD del CONTRIBUTING: páginas afectadas actualizadas + `make -C deploy check-docs` verde. FR-007: cero economía interna |
| `docs-cliente/` (mkdocs usuario final) | Usuario final del cliente — viaja en el kit de sede | La feature cambia lo que el usuario final VE (extensión, portal/chat, mensajes de bloqueo, onboarding) | Páginas afectadas en el MISMO PR + `mkdocs build --strict` del sitio verde |
| Interna (`tech-team/` + README + AGENTS.md) | El equipo | La feature cambia el mapa: módulos, arquitectura, flujo, roles | Doc afectado actualizado en el mismo PR (o issue linkeado si es un doc grande) |

Los kits de instalación del partner (spec 025 y `deploy/`) son de Factory: costura docs = JF contenido / Falime entrega brandeada.

## 5 · Review de PRs

Orden de gates para todo PR del depto:

1. **DoD del CONTRIBUTING** completo (suite verde, docs, checklist).
2. **codex-gate**: scan de `codex-security` CLI sobre el PR — obligatorio si el PR toca código. Sin crédito disponible → se anota en el PR y queda **pendiente**, nunca se da por pasado en silencio. PRs solo-docs: exentos.
3. **Review adversarial multi-agente** además del scan si toca área de riesgo: auth/RBAC, licensing, masking/PII, streaming, migraciones.
4. **Área propia no exime**: aunque nadie más revise (regla de review cruzada del CONTRIBUTING), los gates 1-3 aplican igual. Auto-merge solo con todos los gates verdes.
5. **Gate de Cristian** cuando el CONTRIBUTING lo manda (claves de firma, keyset, RBAC de firma, auth).
6. **Gate de QA por personas (Bob)** — si el PR toca superficie visible (UI de panel/portal,
   wizard, respuestas o mensajes que ve un usuario/partner/instalador): el veredicto de QA
   (pasada por personas — admin · usuario final · officer · partner · instalador — con
   evidencia) es **input requerido del gate del manager** antes del merge *(regla de JF,
   17-ago-2026)*. Alcance proporcional: pasada completa para nodos nuevos con superficie,
   dirigida para bugfixes chicos. Sin pasada posible → se anota **pendiente** en el PR,
   nunca se da por pasado en silencio. PRs sin superficie visible y solo-docs: exentos.

## 6 · Modo autónomo (jefe de depto ausente)

| Regla | Detalle |
|---|---|
| Features | NO se mergean sin OK explícito de JF (mensaje desde el móvil vale) |
| Docs / chore con DoD verde | Merge con precedente de OK (establecido 05-ago) |
| Evidencia en el PR | Comandos corridos con salida, resultado del codex-gate, capturas si hay UI, veredicto QA por personas (Bob) si tocó superficie visible |
| Bloqueos | Si un gate no se puede pasar (crédito, entorno), el PR queda abierto con el estado anotado — nunca se degrada el gate |

## 7 · CI

**Existe y gatea** — el issue [#82](https://github.com/DrZuzzjen/basa-guardian/issues/82) está CERRADO. `.github/workflows/ci.yml` corre en cada PR: `pytest` de la suite completa contra Postgres real · `check-docs` (build + linter del sitio que se vende) · `pytest` del harness · `tsc --noEmit`. Sumado a GitGuardian, son **5 checks** por PR.

Lo que sigue valiendo del criterio viejo: la evidencia se pega igual en el PR, y **lo que el CI no corre se corre en local y se dice cuál fue** (ejemplo: `make -C deploy build-docs` necesita el daemon de Docker; si está caído, el `mkdocs --strict` se hace en venv y se aclara). El CI no reemplaza la verificación de primera línea — la cubre por abajo.

## 8 · Stacks paralelos (worktrees)

Varios worktrees en la misma máquina no se aíslan con `docker compose -p <proyecto>`: ese flag solo scopea red y volúmenes. Los `container_name` del compose base van templados:

```
container_name: ${STACK_PREFIX:-basa}-<svc>
```

| Situación | Qué hacer |
|---|---|
| Stack raíz / lectores | `STACK_PREFIX` sin setear → `basa-db`, `basa-litellm`, … Los scripts `deploy/release/checks/test_profile_renders.sh` y `backend/tests/e2e/test_guardrail_behavior_e2e.py` siguen haciendo `docker exec basa-*` |
| Worktree paralelo | `STACK_PREFIX=jeff223 docker compose up -d` (o `qa`, `grok223`, …). **No** quitar `container_name` del base: Compose nombraría `<proyecto>-<svc>-1` y rompe los lectores |
| Choque de puertos de host | Siguen globales (5433/8091/8090/4010). Override **local no commiteado** solo de `ports` (`!reset []` si los tests corren dentro de la red). El override de `container_name` (`docker-compose.jeff018.yml`) queda obsoleto |

Check automatizado: `scripts/check_stack_prefix.sh` (también en CI, job `backend-tests`, antes de `docker compose up`). Clava el render de `docker compose config`, no el texto fuente.

Los `basa-backend:prod` en `deploy/` son tags de imagen, no nombres de contenedor.

---

Dueño del documento: depto Guardian (JF). Cambios: PR con label `depto:guardian`. Creado 2026-08-07 (issue #81).
