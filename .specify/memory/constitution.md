<!--
Version change: 1.0.0 -> 2.0.0 (basa-guardian: product core, forked from gatelite feature/012)
Modified principles:
- Reframed II as Compliance & Governance FIRST (the product IS compliance/governance)
- Added III Multi-Tenant by Design
- Added IV LiteLLM-Native, No Patching
- Added VI Client Onboarding as Data
- Added VII Tested & Verified
- Removed old V "Explanatory Playground" (demo-specific; observability folded into audit)
- Renamed project: Basa Guardian
Templates requiring review: plan-template.md, spec-template.md, tasks-template.md (inherited from gatelite; re-validate on first spec)
STATUS: DRAFT — pending user review before ratification.
-->

# Basa Guardian

Producto: gateway/firewall de **compliance y gobernanza** para el uso de IA en una organización.
Repo de producto white-label; los despliegues por cliente (Elea, Cámara…) son **configuración + seed**,
nunca forks de código. Base técnica: portada de `gatelite-salud-eu` feature/012 (LiteLLM-first,
compresión, tests). Se construye con SDD.

## Core Principles

### I. Privacy & PII/PHI Masking-First
Todo prompt con PII/PHI DEBE detectarse y poder enmascararse antes de salir de la organización, con
un mapa **reversible** que reconstruye los valores en la respuesta (incl. streaming). El objetivo de
producción es NLP real (Presidio), con regex como fallback — nunca solo regex en prod. El
enmascaramiento vive donde exista el estado reversible (backend / guardrail del motor), nunca se
delega a un tercero que rompa la reversibilidad.

### II. Compliance & Governance FIRST
El producto ES la compliance y la gobernanza. Cada petición se rige por GDPR (base legal, residencia,
minimización) y el EU AI Act (clasificación de riesgo, disclosure, supervisión humana), resueltos de
forma **jerárquica** (tenant → grupo → cliente → conexión) reutilizando el modelo de `ComplianceProject`.
Los niveles de protección se asignan por **grupo** con override por cliente. La auditoría es
**metadata-only**: nunca se persiste texto de prompt ni PII cruda.

### III. Multi-Tenant by Design
Aislamiento de tenant desde el día 1: toda entidad lleva `tenant_id`, toda query se scopea, y el aislamiento
duro se refuerza con Row-Level Security de Postgres. El MISMO código corre **single-tenant on-premise**
(un tenant por instalación, apto para modelos locales) y **multi-tenant cloud** (SaaS). Jerarquía:
**Tenant (empresa) → Group/Team → Client (persona) → Connection (APIKey por herramienta)**. Dos niveles
de admin: super-admin (Basa) y tenant-admin (el cliente, gestiona solo su tenant).

### IV. LiteLLM-Native, No Patching
LiteLLM es el motor. Se reutilizan sus **puntos de extensión documentados** (custom guardrails, custom
auth, custom callbacks/loggers, `/v1/messages` nativo) — NO se parchea ni se reimplementa lo que el motor
ya hace (routing, guardrails, cost, streaming, protocolo). El passthrough de suscripción OAuth (que
LiteLLM no soporta) es la única pieza de proxy propia. Se **fija la versión** de LiteLLM y se cubren las
firmas de los hooks con **tests de contrato**; actualizar el motor = correr tests, no reescribir.

### V. White-Label & Containerized
Ningún nombre de proveedor externo (Anthropic, OpenAI, Azure, Meta, LiteLLM, Presidio…) aparece en la API
pública, mensajes de error ni UI. Backend, motor y frontend corren en containers separados. La marca y los
ejemplos por sector son configuración, no código.

### VI. Client Onboarding as Data
Un "client" (Claude Code, Copilot, Claude Desktop, ChatGPT client, o nuestro chat UI) es un usuario de
primera clase (`role="client"` + `client_type`), onboardeado como **dato**: crear cliente, asignar
grupo/policy/proyecto, emitir virtual key(s) por herramienta. Sumar un cliente o un demo NUNCA requiere
tocar código. Herramientas sin base URL / con red hostil quedan documentadas como no compatibles.

### VII. Tested & Verified
Todo cambio con lógica no trivial DEBE tener tests automatizados (se hereda la suite de feature/012).
Verificación local con Docker Compose antes de mergear. La reversibilidad del enmascaramiento y los hooks
de LiteLLM tienen tests e2e contra la versión fijada.

## Security & Compliance Constraints

1. **No Raw PII/PHI Storage**: ni en DB, ni archivos, ni logging externo. La auditoría guarda solo
   metadatos (tipos de entidad, scores, timing, verdicto), nunca el contenido.
2. **Tenant Isolation**: ninguna query cruza `tenant_id`; RLS activo en cloud.
3. **Encryption**: TLS en tránsito; credenciales fuera de `config.yaml` (env/secretos).

## Development Workflow

1. **Spec-Driven Development**: toda feature se especifica, planea y revisa antes de codear.
2. **Reuse over Reinvent**: primero se busca si LiteLLM (o el core existente) ya lo resuelve.
3. **Local Verification**: Docker Compose + tests verdes antes de mergear.

## Governance

Esta constitución gobierna todas las decisiones de arquitectura. Cambiar un principio core requiere bump
de versión mayor. Los despliegues por cliente son config/seed y no pueden violar estos principios.

**Version**: 2.0.0 (DRAFT) | **Ratified**: pendiente review | **Based on**: gatelite v1.0.0 + feature/012
