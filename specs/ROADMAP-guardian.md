# Roadmap — Basa Guardian (producto-core)

**Última actualización**: 2026-07-13 (+ specs 019/020/021: integraciones, deploy white-label, licencias — con `research.md`)
**Base**: forkeado de gatelite "Basa Secure AI Gateway" v1.0.0 + feature/012 (ver [`ROADMAP.md`](./ROADMAP.md) para la deuda heredada A–F).
**Gobierna**: [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) v2.0.0.

Este roadmap encadena el producto-core de **Basa Guardian** a partir del spec **013**, respetando las
specs 001-012 heredadas. Convierte el giro demo→prod (multi-tenant, client-as-data, firewall LiteLLM-native)
en una secuencia SDD, y **absorbe** items pendientes de Cris que ahora son parte del core (C2 Presidio, C3-C5
SSO, D5 env vars).

## Principio de secuenciación

`013` es el **bedrock** (sin multi-tenant + client model nada del resto encaja). `014` es el **titular**
(el firewall que da las demos). El resto son endurecimientos que dependen de esos dos.

## Features del core

| Spec | Título | Prioridad | Estado | Constitución | Absorbe de A–F |
|------|--------|-----------|--------|--------------|----------------|
| **013** | **Multi-Tenant Foundation & Client Model** | P1 | **Implementada** (2026-07-10, ver [implementation-notes](./013-multi-tenant-foundation/implementation-notes.md)) — desbloquea 014/015/017 | III, IV, VII | — |
| **014** | **LiteLLM-Native Firewall (base_url clients)** | P1 | **Implementada** (US1-US5, 2026-07-10, [notes](./014-litellm-native-firewall/implementation-notes.md)); sólo resta Polish T034-T037 | I, II(exc.), VI, VIII | — |
| 015 | Scoped SecurityPolicy (per-group/per-client) | P2 | Roadmap | I, II | gap "SecurityPolicy global" |
| 016 | Real NLP Masking (Presidio) + streaming unmask hardening | P2 | Roadmap | I, SC-2 | **C2** |
| 017 | Auth hardening & Multi-Tenant RBAC + SSO | P2 | Roadmap | III, SC-3 | **C3, C4, C5**, D5 |
| 018 | Compliance Enforcement Tiers + retention purge | P3 | Roadmap | II [D3] | A4 |
| 019 | Integration Surfaces & Client Compatibility | P2 | Roadmap (spec+plan+tasks+research; impl. probada en gatelite-demo, a portar) | VI, VIII, II(exc.), IV | promueve browser-DLP del "later" |
| 020 | White-Label Packaging & Deploy (OpenTofu + k3s/Zarf) | P2 | Roadmap (greenfield) | VII, IV, III | D5 |
| 021 | Licensing & Seat Enforcement (offline Ed25519) | P2 | Roadmap (greenfield) | VII, III, II | — |
| 022 | Product Documentation Site (MkDocs Material, contenedor `docs` air-gap) | P2 | Roadmap (greenfield) | VII, VIII, II | — |

### 013 — Multi-Tenant Foundation & Client Model (P1, bedrock)
El aislamiento por tenant + el modelo de "client" como dato. `tenant_id` en todas las entidades + RLS Postgres;
entidad `Tenant`; jerarquía Tenant→Group→Client→Connection; reconciliación de roles (super-admin/tenant-admin +
`role="client"` + `client_type`; clinician/developer → labels); onboarding como config+seed. Migración Alembic
con default-tenant backfill (single-tenant sigue funcionando). **Precondición de todo lo demás.**

### 014 — LiteLLM-Native Firewall (P1, titular)
Portar el gateway del demo (`gatelite .../api/gateway.py`) **bien**, como extensión nativa de LiteLLM:
`CustomGuardrail` (AI-Act + secretos + PII mask/unmask reversible sobre SSE), `custom_auth` (identidad por
User-Agent + virtual key → tenant/client/tool), `CustomLogger` (audit metadata-only), `/v1/messages` nativo.
**Excepción propia:** passthrough OAuth de suscripción en el backend. Router GDPR = N/A (excepción acotada del
Principio II). Incluye el monitor en vivo para demos.

### 015 — Scoped SecurityPolicy (P2)
Reemplazar `get_or_create_default_policy` (singleton global) por resolución en cascada
`client > group > tenant > default`, calcando el patrón per-cliente de `ComplianceProject`. Unicidad de política
activa por scope.

### 016 — Real NLP Masking + streaming hardening (P2)
Activar Presidio NLP real (analyzer+anonymizer, fallback regex) — hoy es scaffolding inactivo (SC-2). Endurecer
la reversibilidad del masking sobre streaming (los 12 bugs del demo ya resueltos se formalizan como tests de
contrato). Gap PHI clínico español (CIE-10, nº historia clínica).

### 017 — Auth hardening & Multi-Tenant RBAC + SSO (P2)
Cerrar el fallback a admin sin token (SC-3). RBAC scopeado por tenant. SSO real OIDC/SAML (Azure AD, Google
Workspace, Keycloak — C3/C4/C5). Revocación de sesión server-side. Credenciales a env vars (D5).

### 018 — Compliance Enforcement Tiers + retention purge (P3)
Decidir/implementar qué "evidencia" pasa a "gate duro" (consent/retención). Job de purga de retención real
(hoy nunca ejecuta). Cerrar tests de integración compliance (A4).

### 019 — Integration Surfaces & Client Compatibility (P2)
Portar y formalizar el **lado cliente** del firewall (probado en gatelite-demo): Claude Code (passthrough de
suscripción + identidad `X-Basa-Key`), VS Code/Copilot (auto-byok, key-in-URL, modo Ask), extensión browser MV3
(mask/unmask en ChatGPT/Claude web). Matriz de compatibilidad: Cursor=parcial (solo chat/plan, como Copilot Ask),
Gemini web=vía DOM-hook (spike), Claude Desktop=MCP tool-plane only. Research: no hay "LiteLLM del browser-DLP";
el approach de Basa es el patrón dominante — **moat: des-enmascarar en vez de bloquear** (mantiene UX). Docs de
training/soporte en `docs/integration-surfaces.md`.

### 020 — White-Label Packaging & Deploy (P2)
Empaquetado para el modelo distribuidor marca-blanca: Dockerfiles de producción + imágenes / tarball air-gapped,
branding **config-as-data** (never fork), perfil por cliente, módulo IaC portable. Research build-vs-buy: **OpenTofu**
(no Terraform, por BSL + HashiCorp=IBM al entregar a terceros); v1 = VM + docker compose + Caddy + SOPS/age;
v2 = **k3s + Helm + Zarf** (ECS Anywhere **no** corre air-gapped). Secretos por instalación (D5). Runbook en
`docs/whitelabel-deployment.md`.

### 021 — Licensing & Seat Enforcement (P2)
Enforcement de licencias **offline** para el modelo "install + N seats" (el cliente corre la caja, sin phone-home).
Research build-vs-buy: **DIY Ed25519** — no hay producto que aplique por el air-gap; `seat = Connection activa`
contada en Postgres. Licencia firmada `.lic` (tenant_id, max_seats, expiry, `kid`) verificada en 2 gates fail-closed
(arranque + creación de Connection); anti-tamper vía **true-up sobre el audit inmutable**. Complementa la 020.

### 022 — Product Documentation Site (P2)
Sitio de documentación de producto como **contenedor `docs` propio** (estático, air-gapped, 0 egress en runtime),
separado de la app. Research build-vs-buy: **MkDocs + Material** (air-gap de primera clase vía plugins `offline`+
`privacy`, Python-nativo, white-label por YAML, versionado `mike`, i18n `static-i18n`); plan B **Starlight+Pagefind**.
Audiencia **distribuidor+operador** (install/deploy, admin, API reference, compliance, troubleshooting); sembrada de
`docs/*.md`. **API reference single-source del OpenAPI de FastAPI** (no derivar de las specs — audiencias distintas).
White-label por config (imagen-por-marca), búsqueda offline (nunca Algolia). Runbook/decisión en `docs/whitelabel-deployment.md`.

## Fuera de scope del core (siguen como research/later)
- **Browser-DLP web** (ChatGPT/Claude/Gemini) — **promovido a spec 019** (viable: el body no está firmado →
  extensión MV3 mask/unmask). La interceptación de **apps desktop nativas** (Claude Desktop) sigue como gap:
  bloqueada por cert-pinning, gobernable solo vía **MCP tool-plane** (ver 019).
- Guardianes cloud reales Lakera/Azure (D1), export PDF firmado (D2), alertas email (D3).
