# Content Map — IA detallada del sitio de producto (022, T004)

**Fecha**: 2026-07-20 · **Regla de fuentes**: SEMILLA (corpus `docs/*.md` migrado) · AUTO (derivado en
build de OpenAPI/`.env.example`) · NUEVO (redactado en US2, marca-neutro). Las specs de Spec Kit
(`specs/0XX-*`) **jamás** se derivan al sitio (FR-018). Los internos `docs/COORDINATION-*.md` y
`docs/retros/` quedan **fuera** de `docs_dir` por construcción (delta F4).

Leyenda de estado por página: la migración **conserva** 🟢 HOY / 🟡 PARCIAL / 🔵 OBJETIVO (FR-006).

## Árbol del sitio (`docs/docs/**`)

| Página | Fuente | Semilla exacta | Estado |
|---|---|---|---|
| `index.md` (landing por rol) | NUEVO | — | hecho (Setup) |
| **overview/** `index.md` — qué es el producto, stack en containers, pipeline masking→…→unmask | NUEVO | constitución (resumen marca-neutro) + `docker-compose` (stack) | US2 |
| **install-deploy/** `index.md` — modelo de entrega + flujo punta a punta | SEMILLA | `whitelabel-deployment.md` §0-§2, §4 | US2 |
| **install-deploy/** `infrastructure.md` — arquitectura objetivo, OpenTofu, secretos, air-gap | SEMILLA | `whitelabel-deployment.md` §3 + `deploy/README.md` (020 real) | US2 |
| **install-deploy/** `licensing.md` — licenciamiento offline + postura de IP | SEMILLA | `whitelabel-deployment.md` §5/§5.b | US2 |
| **white-label/** `index.md` — brand-pack, config-as-data, never fork | SEMILLA | `whitelabel-deployment.md` §branding + `deploy/branding/` (020 real) | US2 |
| **administration/** `index.md` — multi-tenant, RBAC, guardrails, budgets, SSO, licencias/seats | NUEVO | relación 013/021 (redacción marca-neutra) | US2 |
| **integrations/** `index.md` — superficies + tabla de compatibilidad | SEMILLA | `integration-surfaces.md` §1-§2 | US2 |
| **integrations/** `gotchas.md` — G1-G8 verificados (causa → fix) | SEMILLA | `integration-surfaces.md` §3 | US2 |
| **api-reference/** `index.md` — Swagger UI embebido (single-source OpenAPI) | AUTO | `openapi.json` exportado del backend (US5, delta F5) | US5 |
| **api-reference/** `configuration.md` — variables de entorno | AUTO | `.env.example` (US5) | US5 |
| **compliance/** `index.md` — visión general + proyectos | SEMILLA | `compliance-policies.md` §1-§2 | US2 |
| **compliance/** `dpa-dsr-retention.md` — DPA, DSR, retención, panel DPO | SEMILLA | `compliance-policies.md` §3-§7 | US2 |
| **operations/** `index.md` — runbook operativo + troubleshooting | SEMILLA+NUEVO | `whitelabel-deployment.md` §6 (gotchas a-f) + `integration-surfaces.md` §4 | US2 |
| **release-notes/** `index.md` — una entrada por versión (mike) | NUEVO | — (US6) | US6 |

## Post-migración de la semilla (anti doble-fuente, Dev Workflow "Documentación viva")

Los tres archivos semilla (`whitelabel-deployment.md`, `integration-surfaces.md`,
`compliance-policies.md`) se **reemplazan por stubs** que apuntan a su nueva ubicación en el sitio
(los links internos del repo no se rompen; el contenido vive en UN solo lugar). `COORDINATION-*` y
`retros/` no se tocan (internos, nunca publican).

## Roadmap: docset end-user clínico (US7/T039 — FR-021, NO en v1)

Segundo nav-tree bajo el mismo contenedor (p.ej. `docs/docs/clinical/**` + pestaña propia), reusando
white-label + i18n + versionado, con **audiencia y tono propios** (persona no técnica que usa la IA
gobernada en un centro sanitario). Estado: **🔵 NO implementado — roadmap P3**. Ninguna página
clínica se publica en v1; esta reserva de IA es el único artefacto.
