# Roadmap — Basa Guardian (producto-core)

**Última actualización**: 2026-07-10
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

## Fuera de scope del core (siguen como research/later)
- Browser-DLP / interceptación de desktop apps (ChatGPT/Claude Desktop inline) — bloqueado por cert-pinning;
  es el "later" documentado en la memoria de dirección de prod.
- Guardianes cloud reales Lakera/Azure (D1), export PDF firmado (D2), alertas email (D3).
