# DevFlow — Guardian App Ecosystem

Operativa de desarrollo del departamento Guardian. Capa **encima** de [`CONTRIBUTING.md`](../CONTRIBUTING.md) (convención común del equipo, dueño Cristian): todo lo de ahí aplica; esto añade el *cómo* interno. Si algo contradice al CONTRIBUTING, gana el CONTRIBUTING.

Alcance: solo depto Guardian. Factory (Falime) tiene su propia operativa.

## 1 · Orquestación con agentes

| Rol | Quién | Qué hace |
|---|---|---|
| Orquestación | Fable 5 (sesión principal) | Planifica, parte el trabajo, decide, verifica resultados, redacta PRs |
| Coding | Agentes Opus 5 | Implementación de tareas acotadas (una tarea = un agente con brief cerrado) |
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

Pendiente (issue [#82](https://github.com/DrZuzzjen/basa-guardian/issues/82)): workflow de GitHub Actions que corra pytest + check-docs en cada PR. Hasta entonces, todos los gates se corren en local y se pega la evidencia en el PR.

---

Dueño del documento: depto Guardian (JF). Cambios: PR con label `depto:guardian`. Creado 2026-08-07 (issue #81).
