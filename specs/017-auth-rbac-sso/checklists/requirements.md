# Specification Quality Checklist: Identidad con dientes — matriz RBAC definitiva, SSO Entra y RLS despierta

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-13
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) — los `path:line` del contexto son evidencia del as-is, no diseño. Menciones mecánicas deliberadas y acotadas: JWT/GUC/Fernet/Redis son hechos del sistema existente que la spec reusa por contrato (mismo criterio que la 018), no decisiones nuevas.
- [x] Focused on user value and business needs — cada capítulo se ancla a una promesa del roadmap piso 0 (SSO escalonado, rol Lectura), a la deuda escrita en el propio código (shim «transicional hasta 017», mandato de la migración 010) o al modelo comercial (feature_flags 021).
- [x] Written for non-technical stakeholders — historias en lenguaje de operación/compra; lo técnico vive en contexto/evidencia.
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain — las decisiones abiertas del research se resolvieron con el recorte sellado por JF (13-ago) o quedaron como confirmaciones nombradas del gate de producto (ver Notes), no como huecos anónimos.
- [x] Requirements are testable and unambiguous — cada FR tiene verbo verificable; FR-005 y FR-013 son los dos harnesses que hacen falsables al resto.
- [x] Success criteria are measurable — SC-001..007 con condiciones binarias.
- [x] Success criteria are technology-agnostic — se miden por API/suite/dump sin conocer implementación.
- [x] All acceptance scenarios are defined — 4 historias, 18 escenarios Given/When/Then.
- [x] Edge cases are identified — 7, incluidos los tres que cruzan specs/planos (bootstrap sin dueño creable, purga 018 vs auth events, token sin tenant en rotación).
- [x] Scope is clearly bounded — Out of scope con 7 exclusiones nombradas, cada una con destino (C3, release siguiente, 018, o «cuando haya segundo tenant»).
- [x] Dependencies and assumptions identified — costura 018 (3 puntos), merge-order Cristian #137/#147, tenant Entra de DevOps, gate de producto JF.

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows — matriz (P1), SSO (P1), RLS partida (P2), hardening (P2).
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Pendiente de gate de producto (JF), 3 confirmaciones: (1) auditor read-only con única excepción reviews y sin probar dueño; (2) rol `lectura` con superficie propuesta (no chatea, no seat, no dueño); (3) SSO gateado por feature_flag de licencia firmada (primer consumidor; Cámara sigue sin re-emisión).
- Precondición de tasks (no de spec): orden de merge #137/#147 sellado con Cristian antes del 24-ago — FR-017 toca `custom_auth.py`.
- La decisión FR-002 es conjunta con la 018 (su FR-009): si una cambia la semántica del auditor o del escritor de retención, revalidar ambas antes de tasks.
