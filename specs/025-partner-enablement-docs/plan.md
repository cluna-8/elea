# Implementation Plan: Página de Partner Enablement en la doc de producto

**Branch**: `025-partner-enablement-docs` | **Date**: 2026-07-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/025-partner-enablement-docs/spec.md`

## Summary

Agregar una página tipo GUÍA a la sección Install/Deploy del sitio de documentación de
producto (spec 022) que documente el **programa de enablement del partner**: etapas
(formación → práctica → installs acompañados → certificación), prerequisitos del
ingeniero, reparto fabricante/partner por etapa, expectativas de duración como rangos y
checklist de autonomía. Contenido de cara al partner: **cero economía interna del
fabricante** (FR-007). El programa formal es nuevo → leyenda de estado honesta (FR-010).

## Technical Context

**Language/Version**: Markdown (MkDocs Material, sitio de la spec 022, Python 3 build)

**Primary Dependencies**: sitio docs existente (`docs/mkdocs.yml`, tema Material,
plugins privacy+offline); diagramas Mermaid nativos del sitio

**Storage**: N/A (contenido estático)

**Testing**: gate de docs del release — `make -C deploy build-docs && make -C deploy
check-docs` (estructura Diátaxis, naming marca-neutro, 0-egress, strict build,
white-label, búsqueda offline)

**Target Platform**: imagen `sentinel-docs:<brand>-<version>`, 100% estática, air-gap-first

**Project Type**: documentación de producto (se vende con el producto)

**Performance Goals**: N/A

**Constraints**: template GUÍA obligatorio (H1 → resumen 2-4 líneas → `**Para
quién**:` → sección conceptual con ≥1 Mermaid → secciones → límites con leyenda
🟢/🟡/🔵 → `## Relacionado` con ≥2 links y 1 línea de contexto; ≥3 links internos);
contenido marca-neutro idéntico entre marcas (never fork); honestidad de estado (jamás
declarar existente lo que no lo es)

**Scale/Scope**: 1 página nueva + 1 entrada de nav + 1 link desde el índice de
Install/Deploy. Sin cambios de código, API ni `.env.example` (no aplica `docs-refs`).

## Constitution Check

- **IV Containerized & White-Label (KEEP)**: contenido marca-neutro, sin nombres de
  motor; usa "fabricante/partner", jamás marcas. ✅
- **Client Onboarding as Data**: la página documenta el camino humano (enablement del
  partner) que complementa el onboarding-as-data existente; no introduce proceso que
  contradiga "config + seed, nunca fork". ✅
- **II Strict Compliance / honestidad**: leyenda 🟢/🟡/🔵 obligatoria — el programa
  formal se marca en formalización (🟡), apoyado en lo que sí existe (runbook 🟢,
  perfil por cliente 🟢, compose reproducible 🟢). ✅
- Sin impacto en enforcement, datos ni runtime → no aplican gates de seguridad/budget.

## Project Structure

### Documentation (this feature)

```text
specs/025-partner-enablement-docs/
├── spec.md
├── plan.md              # este archivo
├── tasks.md
└── checklists/
    └── requirements.md
```

### Source (repository)

```text
docs/
├── mkdocs.yml                                  # + entrada nav bajo Install / Deploy
└── docs/
    └── install-deploy/
        ├── index.md                            # + link a la página nueva (páginas de la sección)
        └── partner-enablement.md               # NUEVA — página GUÍA del programa
```

## Diseño de la página (estructura GUÍA)

1. **H1** "Partner enablement" + resumen 2-4 líneas (qué es el programa, para qué).
2. **Para quién**: el ingeniero del partner que va a instalar + el responsable que
   asigna la dedicación. Primera aparición: "partner (en esta documentación,
   «distribuidor»)" (FR-009).
3. **Sección conceptual + Mermaid**: flujo del programa
   formación → práctica en sandbox → installs acompañados → certificación → autonomía,
   con el reparto fabricante/partner visible.
4. **Prerequisitos** del ingeniero (contenedores/Docker, IaC básico, SQL, shell; y
   acceso a la infra objetivo del cliente). Edge case: sin el perfil, la formación se
   alarga — el programa no es curso de las tecnologías base.
5. **Las etapas** — una subsección por etapa: objetivo, actividades, qué provee cada
   parte, criterio de salida. Duraciones como rangos marcados estimados (FR-005):
   formación 2–4 días, práctica ~1 día, installs acompañados 2–3 reales (el 1º lo
   lidera el fabricante; primeros installs a 2–3× de un install maduro), certificación
   ~medio día.
6. **Checklist de autonomía** (FR-004): capacidades demostrables (armar y renderizar
   perfil, desplegar por el camino objetivo, seed + licencia + smoke test, triage con
   el runbook de operaciones, conocer los gotchas).
7. **Después de la certificación**: qué opera el partner (installs, training a su
   cliente, soporte L1/L2) y qué queda siempre en el fabricante (emisión/renovación de
   licencias, bugs de producto) (FR-006).
8. **Límites** con leyenda 🟢/🟡/🔵 (FR-010): programa formal 🟡 en formalización;
   material de soporte hoy = runbook + perfil ejemplo + compose (🟢); certificación
   con artefacto formal 🔵.
9. **## Relacionado** (≥2): install-deploy/index.md, operations/index.md,
   licensing.md, integrations/index.md.

**Filtro FR-007 (verificación)**: la página no contiene FTE, horas internas del
fabricante, costos, capacidad del equipo ni cuellos operativos. Las únicas cifras son
expectativas de cara al partner (duración de SUS etapas). SC-003 se verifica con grep.

## Verification

1. `make -C deploy build-docs && make -C deploy check-docs` verde (SC-001) — nota: el
   gate ya encadena build antes de check (fix post-024).
2. Grep de términos internos sobre la página nueva (`FTE`, horas internas, costo,
   capacidad del equipo, staffing) → 0 hits (SC-003).
3. Nav + link desde el índice de la sección presentes (SC-004).
4. Lectura de revisión por un integrante que no escribió la página (SC-002) — queda
   para el review del PR.

## Complexity Tracking

Sin desvíos: no se agrega tooling, no se toca código, no hay dependencias nuevas. La
única decisión editorial (terminología partner/distribuidor) está resuelta en FR-009
con migración global fuera de alcance.
