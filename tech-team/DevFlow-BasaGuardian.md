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

## 4 · Review de PRs

Orden de gates para todo PR del depto:

1. **DoD del CONTRIBUTING** completo (suite verde, docs, checklist).
2. **codex-gate**: scan de `codex-security` CLI sobre el PR — obligatorio si el PR toca código. Sin crédito disponible → se anota en el PR y queda **pendiente**, nunca se da por pasado en silencio. PRs solo-docs: exentos.
3. **Review adversarial multi-agente** además del scan si toca área de riesgo: auth/RBAC, licensing, masking/PII, streaming, migraciones.
4. **Área propia no exime**: aunque nadie más revise (regla de review cruzada del CONTRIBUTING), los gates 1-3 aplican igual. Auto-merge solo con todos los gates verdes.
5. **Gate de Cristian** cuando el CONTRIBUTING lo manda (claves de firma, keyset, RBAC de firma, auth).

## 5 · Modo autónomo (jefe de depto ausente)

| Regla | Detalle |
|---|---|
| Features | NO se mergean sin OK explícito de JF (mensaje desde el móvil vale) |
| Docs / chore con DoD verde | Merge con precedente de OK (establecido 05-ago) |
| Evidencia en el PR | Comandos corridos con salida, resultado del codex-gate, capturas si hay UI |
| Bloqueos | Si un gate no se puede pasar (crédito, entorno), el PR queda abierto con el estado anotado — nunca se degrada el gate |

## 6 · CI

Pendiente (issue [#82](https://github.com/DrZuzzjen/basa-guardian/issues/82)): workflow de GitHub Actions que corra pytest + check-docs en cada PR. Hasta entonces, todos los gates se corren en local y se pega la evidencia en el PR.

---

Dueño del documento: depto Guardian (JF). Cambios: PR con label `depto:guardian`. Creado 2026-08-07 (issue #81).
