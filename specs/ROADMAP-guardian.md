# Roadmap — Basa Guardian (producto-core)

**Última actualización**: 2026-07-22 (módulo JF cerrado hasta 025: 020/021/022 implementadas + mergeadas, 024 fix de unmask bridged, 025 partner-enablement; 016 de Cris en review)
**Base**: forkeado de gatelite "Basa Secure AI Gateway" v1.0.0 + feature/012 (ver [`ROADMAP.md`](./ROADMAP.md) para la deuda heredada A–F).
**Gobierna**: [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) v2.0.0.

Este roadmap encadena el producto-core de **Basa Guardian** a partir del spec **013**, respetando las
specs 001-012 heredadas. Convierte el giro demo→prod (multi-tenant, client-as-data, firewall LiteLLM-native)
en una secuencia SDD, y **absorbe** items pendientes de Cris que ahora son parte del core (C2 Presidio, C3-C5
SSO, D5 env vars).

## Principio de secuenciación

`013` es el **bedrock** (sin multi-tenant + client model nada del resto encaja). `014` es el **titular**
(el firewall que da las demos). El resto son endurecimientos que dependen de esos dos.

## Módulos y owners (reunión 2026-07-15)

El equipo core trabaja en paralelo por módulos, una spec por vez, con el flujo SDD del repo
(branch por spec → PR → merge humano de otro; ver [CODEOWNERS](../.github/CODEOWNERS)):

- **JF (@DrZuzzjen)** — clientes, integraciones y producto/distribución: 019 (spikes), 020, 021, 022, 024 (fix bridged), 025 (partner-enablement).
- **Cristian (@cluna-8)** — seguridad y guardianes: 015, 016, 017, 018 (+ anti-jailbreak del "later").
- **Falime (@FalimeJ)** — datos, costes y ruteo: 023 (generaliza la 012 al plano firewall).

Punto de contacto entre módulos: el **motor LiteLLM** (`litellm/`) — ahí conviven la política de
seguridad (Cristian) y la optimización de costes (Falime); los cambios piden review cruzado. La 015
define el patrón de resolución por scope que la 023 reutiliza: coordinar orden de merge.

## Features del core

| Spec | Título | Owner | Prioridad | Estado | Constitución | Absorbe de A–F |
|------|--------|-------|-----------|--------|--------------|----------------|
| **013** | **Multi-Tenant Foundation & Client Model** | — (core) | P1 | **Implementada** (2026-07-10, ver [implementation-notes](./013-multi-tenant-foundation/implementation-notes.md)) — desbloquea 014/015/017 | III, IV, VII | — |
| **014** | **LiteLLM-Native Firewall (base_url clients)** | — (core) | P1 | **Implementada** (US1-US5, 2026-07-10, [notes](./014-litellm-native-firewall/implementation-notes.md)); sólo resta Polish T034-T037 | I, II(exc.), VI, VIII | — |
| 015 | Scoped SecurityPolicy (per-group/per-client) | Cristian | P2 | Roadmap | I, II | gap "SecurityPolicy global" |
| 016 | Real NLP Masking (Presidio) + streaming unmask hardening | Cristian | P2 | **En review** ([PR #21](https://github.com/DrZuzzjen/basa-guardian/pull/21), en rebase sobre main — 3 contract tests del DNI pendientes) | I, SC-2 | **C2** |
| 017 | Auth hardening & Multi-Tenant RBAC + SSO | Cristian | P2 | Roadmap | III, SC-3 | **C3, C4, C5**, D5 |
| 018 | Compliance Enforcement Tiers + retention purge | Cristian | P3 | Roadmap | II [D3] | A4 |
| 019 | Integration Surfaces & Client Compatibility | JF | P2 | **Implementada** (US1-US5, 2026-07-14, [notes](./019-integration-surfaces/implementation-notes.md)); spikes batch 1 mergeados ([PR #29](https://github.com/DrZuzzjen/basa-guardian/pull/29)) + registro de superficies vivo; resta E2E de la extensión en navegador + spike Cline/Continue en vivo (#15) | VI, VIII, II(exc.), IV | promueve browser-DLP del "later" |
| 020 | White-Label Packaging & Deploy (OpenTofu + k3s/Zarf) | JF | P2 | **Implementada** (US1-US6, 2026-07-20, [PR #23](https://github.com/DrZuzzjen/basa-guardian/pull/23)); resta T040 (tofu apply e2e sandbox) | VII, IV, III | D5 |
| 021 | Licensing & Seat Enforcement (offline Ed25519) | JF | P2 | **Implementada** (US1-US5, 2026-07-20, stack [PR #18](https://github.com/DrZuzzjen/basa-guardian/pull/18)→#19→#20→[#22](https://github.com/DrZuzzjen/basa-guardian/pull/22)) | VII, III, II | — |
| 022 | Product Documentation Site (MkDocs Material, contenedor `docs` air-gap) | JF | P2 | **Implementada** (US1-US7, 2026-07-20, [PR #25](https://github.com/DrZuzzjen/basa-guardian/pull/25) + [#26](https://github.com/DrZuzzjen/basa-guardian/pull/26) docs-en-DoD) | VII, VIII, II | — |
| 023 | Ahorro de Costes IA en el plano firewall (perfiles + ruteo coste-consciente) | Falime | P2 | **Spec mergeada** ([PR #6](https://github.com/DrZuzzjen/basa-guardian/pull/6)); implementación pendiente (#16) | II, IV, VI | generaliza **012** al plano firewall |
| 024 | Unmask + atribución en respuestas byok (rutas bridged) | JF | P2 | **Implementada** (2026-07-21, [PR #31](https://github.com/DrZuzzjen/basa-guardian/pull/31), cierra #27); promueve 3 superficies de 019 a FUNCIONA | I, VI, VIII | fix-spec de #27 |
| 025 | Partner Enablement (capacitación + certificación del partner) | JF | P2 | **Implementada** (2026-07-22, [PR #36](https://github.com/DrZuzzjen/basa-guardian/pull/36)); doc oficial del ciclo de onboarding | VII, IV | — |

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
`docs/whitelabel-deployment.md`. **Addendum 2026-07-14**: tarball air-gap **validado por el mercado**
(Harbor/GitLab/Replicated hacen lo mismo); registry privado autenticado = watch-item v2 como canal de entrega
para clientes conectados, **nunca** como enforcement (post-pull un `docker save` lo anula — el gate de pago es
la licencia 021 en runtime). Segundo punto de contacto con la 021: el deploy provisiona el **volumen/secret de
la deployment key** (par del install que firma los true-up; FR-032/T042), sin lógica de licencias acá.

### 021 — Licensing & Seat Enforcement (P2)
Enforcement de licencias **offline** para el modelo "install + N seats" (el cliente corre la caja, sin phone-home).
Research build-vs-buy: **DIY Ed25519** — no hay producto que aplique por el air-gap; `seat = Connection activa`
contada en Postgres. Licencia firmada `.lic` (tenant_id, distributor_id, pool_id, max_seats, expiry, `kid`)
verificada en 2 gates fail-closed (arranque + creación de Connection); anti-tamper vía **cadena de hashes +
export de true-up firmado** (deployment key). **Addendum 2026-07-14** (prior-art validado: GitLab/Grafana/
Directus/Replicated): tier distribuidor = **firma CENTRAL de Basa + cupo de emisión** (nunca clave delegada);
per-seat capturado en emisión + true-up en renovación; expiry **degrada** (grace → read-only-creación), nunca
mata el box; seat-gate etiquetado best-effort honor-system (ancla real = contrato). Complementa la 020.

### 022 — Product Documentation Site (P2)
Sitio de documentación de producto como **contenedor `docs` propio** (estático, air-gapped, 0 egress en runtime),
separado de la app. Research build-vs-buy: **MkDocs + Material** (air-gap de primera clase vía plugins `offline`+
`privacy`, Python-nativo, white-label por YAML, versionado `mike`, i18n `static-i18n`); plan B **Starlight+Pagefind**.
Audiencia **distribuidor+operador** (install/deploy, admin, API reference, compliance, troubleshooting); sembrada de
`docs/*.md`. **API reference single-source del OpenAPI de FastAPI** (no derivar de las specs — audiencias distintas).
White-label por config (imagen-por-marca), búsqueda offline (nunca Algolia). Runbook/decisión en `docs/whitelabel-deployment.md`.

### 023 — Ahorro de Costes IA en el plano firewall (P2)
Generalizar la **012** (compresión determinista, ahorro neto, KPI — hoy solo en el path legacy del panel)
al **plano byok del firewall**, donde pasa el tráfico real: la cascada `compression_mode` (key > group >
tenant) ya se resuelve en la identidad del motor pero **nada la consume**. Perfiles de optimización por
scope (default developer: coding tools intocables), ahorro medible en presupuesto + audit metadata-only,
y **ruteo coste-consciente** opt-in por reglas de equivalencia con guardia de calidad (nunca sustitución
silenciosa). Plano passthrough fuera de alcance (coste de suscripción fijo). Spec: [PR #6](https://github.com/DrZuzzjen/basa-guardian/pull/6).

### 024 — Unmask + atribución en respuestas byok, rutas bridged (P2, fix-spec de #27)
Cerrar el round-trip mask→unmask en el camino byok del **motor** para modelos no-Claude (local vía Ollama
y cloud puenteados) y devolver la **identidad** a los eventos del monitor de ese camino. Tres root causes
verificados en vivo (la evidencia refutó la hipótesis inicial): (1) streaming — `safe_split` soltaba un `[`
pelado y los bridges con deltas de 1-3 chars partían el placeholder ahí (bug latente también en passthrough);
(2) no-streaming — la respuesta bridged es un `dict` plano que el `getattr` ignoraba; (3) atribución — el
logger leía la identidad de un solo metadata-home. Todo en `litellm/extensions/` (Principio VI), con e2e
contra el motor vivo que antes no existía. **Promueve a FUNCIONA** las 3 superficies que la 019 había dejado
en PARCIAL (Ollama upstream, Claude Code → modelo propio, Aider).

### 025 — Partner Enablement (P2, doc oficial)
Página GUÍA del programa de capacitación y certificación del partner en la documentación de producto:
etapas (formación → práctica → 2-3 installs acompañados → certificación), prerequisitos del ingeniero,
checklist de autonomía y tabla quién-hace-qué post-certificación. **Filtro editorial FR-007**: la doc se
vende → cero economía interna del fabricante (FTE/horas/costos); esa parte vive solo en el doc ejecutivo.

## Mantenimiento de este roadmap

Esta tabla es la **fuente de verdad del estado** y debe actualizarse en el **mismo PR que mergea cada spec**
(pasar el Estado a *Implementada* con el link al PR, o *En review* con el link, y cerrar el issue de tracking
con `Closes #NN`). Un roadmap que dice "Roadmap (greenfield)" sobre algo ya mergeado es un bug de proceso.

## Fuera de scope del core (siguen como research/later)
- **Browser-DLP web** (ChatGPT/Claude/Gemini) — **promovido a spec 019** (viable: el body no está firmado →
  extensión MV3 mask/unmask). La interceptación de **apps desktop nativas** (Claude Desktop) sigue como gap:
  bloqueada por cert-pinning, gobernable solo vía **MCP tool-plane** (ver 019).
- Guardianes cloud reales Lakera/Azure (D1), export PDF firmado (D2), alertas email (D3).
