# Tasks: Página de Partner Enablement en la doc de producto

**Input**: Design documents from `/specs/025-partner-enablement-docs/`
**Prerequisites**: plan.md (required), spec.md (required)

**Organization**: feature docs-only — las user stories comparten un único artefacto (la
página); se implementan como capas de contenido sobre la misma página y se validan con
el mismo gate.

## Phase 1: Setup

- [x] T001 Verificar build local del sitio de docs (venv + `mkdocs build --strict` o
      `make -C deploy build-docs`) para partir de verde en
      `docs/`

## Phase 2: User Story 1 — El ingeniero del partner se prepara para instalar solo (P1) 🎯 MVP

- [x] T002 [US1] Crear `docs/docs/install-deploy/partner-enablement.md` con la
      estructura GUÍA completa: H1 + resumen, `**Para quién**:`, sección conceptual
      con diagrama Mermaid del flujo del programa (formación → práctica → installs
      acompañados → certificación → autonomía) con reparto fabricante/partner
- [x] T003 [US1] Redactar prerequisitos del ingeniero + comportamiento cuando faltan
      (FR-003), etapas con objetivo/actividades/criterio-de-salida (FR-002) y
      checklist de autonomía verificable (FR-004) en
      `docs/docs/install-deploy/partner-enablement.md`
- [x] T004 [US1] Agregar la página al nav de `docs/mkdocs.yml` (grupo Install /
      Deploy) y linkearla desde la lista de páginas de la sección en
      `docs/docs/install-deploy/index.md` (FR-001, SC-004)

## Phase 3: User Story 2 — El responsable del partner evalúa el compromiso (P2)

- [x] T005 [US2] Sumar a la página las expectativas de duración como rangos estimados
      (programa completo; primeros installs a 2–3×) (FR-005) y el reparto
      fabricante/partner por etapa + qué queda de cada lado post-certificación
      (FR-006), legible para un sponsor no técnico

## Phase 4: User Story 3 — El fabricante ejecuta onboardings consistentes (P3)

- [x] T006 [US3] Cerrar la página como referencia canónica: sección de límites con
      leyenda 🟢/🟡/🔵 honesta (programa formal 🟡, material de soporte 🟢,
      certificación con artefacto formal 🔵) (FR-010) y `## Relacionado` con ≥2 links
      con contexto (FR-008)

## Phase N: Polish & Cross-Cutting Concerns

- [x] T007 [P] **Sitio de docs de producto (OBLIGATORIO, DoD)**: curado marca-neutro +
      template de docs/README.md + leyenda honesta en la página nueva, y correr
      `make -C deploy build-docs && make -C deploy check-docs` en verde (SC-001)
- [x] T008 [P] Verificación del filtro FR-007/SC-003: grep de términos de economía
      interna (`FTE`, horas internas, costo, capacidad del equipo, staffing) sobre
      `docs/docs/install-deploy/partner-enablement.md` → 0 hits
- [x] T009 Abrir PR a `main` con la spec 025 completa (spec/plan/tasks + página + nav)
      — review de un integrante que no escribió la página valida SC-002

## Dependencies & Execution Order

- T001 → T002 → T003 → T004 (US1 = MVP entregable por sí solo)
- T005 (US2) y T006 (US3) suman capas sobre la misma página → secuenciales tras T004
- T007/T008 [P] tras T006 · T009 al final
