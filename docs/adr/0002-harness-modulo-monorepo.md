# ADR-0002: El harness de carga vive como módulo del monorepo (`harness/`)

**Fecha:** 2026-08-08 · **Estado:** aceptado
**Decisores:** JF · propuesto por La ITV (spec 035, issue #95)

## Contexto

La Fase 0 de Guardian se examina con gates de carga (125/250/500). El instrumento que
los corre (spec 035) es código nuevo con superficie propia: generador k6, proveedor
simulado, seeder, corpus etiquetado, evaluador de SLO. Surgió dónde alojarlo: repo
propio del team ITV, subcarpeta de `backend/tests/` o de `deploy/`, o módulo raíz del
monorepo. El CONTRIBUTING fija que un repo nuevo solo se justifica si despliega y
versiona independiente con equipo propio (hoy: solo guardian-factory), y que las
integraciones/módulos nuevos viven en el monorepo con dueño en CODEOWNERS.

## Decisión

El harness es un **módulo raíz del monorepo: `harness/`**, con dueño propio en CODEOWNERS
(`harness/ @DrZuzzjen`, label de equipo `team:itv`). Layout coherente con el precedente
`backend/` (src + tests espejo + config-as-data): gates y corpus como datos versionados,
código Python en `src/`, tests del instrumento en `tests/`.

## Alternativas consideradas

- **Repo propio (`sentinel-guardian-harness`)**: descartada — viola la regla estructural
  del CONTRIBUTING; el harness versiona CONTRA el stack (compose, seeds, semántica de
  seats, reconocedores PII como oráculo del corpus) y separado se desincroniza; pierde
  el compose de test y el oráculo compartido con `sentinel_guardian_policy`.
- **Bajo `backend/tests/load/`**: descartada — es la suite que CI corre por-PR; los
  gates de carga explícitamente NO aplican por-PR (DevFlow §3) y contaminarían la suite.
- **Bajo `deploy/`**: descartada — es territorio de Factory (@FalimeJ); mezclaría
  departamentos en cada PR del harness. (El perfil de cliente del examen,
  `deploy/clients/itv-examen/`, sí vive ahí por ser deploy — con review de Falime.)

## Consecuencias

- El corpus PII etiquetado es un artefacto compartido del departamento (issue #107): lo
  produce el harness, lo consume también el gate de calidad de detección del core.
- Los tests del instrumento entran a un job de CI sin stack (`harness-tests`, pytest sin
  Docker; desde #289 ese job comparte runner con `tsc --noEmit` para no pagar dos
  redondeos al minuto — la decisión de este ADR no cambia, sólo el empaquetado);
  los gates NO corren en CI (necesitan el entorno de examen dedicado).
- Agregar una superficie o un gate = editar data versionada + código del módulo, sin
  tocar el producto. El módulo no entra en artefactos que se venden (no aplica
  white-label ni check-docs).
