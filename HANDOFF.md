# HANDOFF — Basa Guardian

> Documento de arranque en frío para una **instancia nueva de Claude** (o cualquier dev) que va a
> **codear** Basa Guardian desde cero. Todo lo necesario para empezar sin el contexto de la sesión
> que preparó esto. Última actualización: **2026-07-10**.

---

## 0. TL;DR — dónde empezar

1. Leé, en orden: [`.specify/memory/constitution.md`](.specify/memory/constitution.md) (v2.0.0, gobierna todo) →
   [`specs/ROADMAP-guardian.md`](specs/ROADMAP-guardian.md) → esta guía.
2. La primera feature a codear es **spec 013** ([`specs/013-multi-tenant-foundation/`](specs/013-multi-tenant-foundation/)):
   el *bedrock* multi-tenant. Ya tiene `spec.md` + `plan.md` + `tasks.md`. Empezá por `tasks.md` (T001…).
3. Después va **spec 014** ([`specs/014-litellm-native-firewall/`](specs/014-litellm-native-firewall/)): el firewall
   LiteLLM-native. **Depende de 013.** Antes de codear su US1, corré la research **T005** (ver §10).
4. **Antes de tocar código**, leé §7 (hechos no-obvios del heredado) — te ahorra trampas reales.
5. Hay **defaults `[D#]` y `[D-014]`** documentados y **revisables** (§10): confirmá con el usuario si alguno no cierra.

---

## 1. Qué es Basa Guardian

Gateway/firewall de **compliance y gobernanza multi-tenant** para el uso de IA en una organización.
**El producto ES la compliance/gobernanza**, no un proxy LLM con features de compliance encima.
Stack: **FastAPI** (backend, única puerta de entrada) + **motor LiteLLM** (white-label, nunca nombrado) +
**PostgreSQL** + **Redis** + **React/Vite/Tailwind** (frontend), todo en **Docker Compose**.

Dos modos de despliegue desde el **mismo código**: **on-premise** (single-tenant, permite modelos locales
Ollama/vLLM) y **cloud SaaS** (multi-tenant). Cada cliente/demo = **configuración + seed**, nunca un fork.

## 2. De dónde viene (fork + mapa honesto del heredado)

Basa Guardian se **forkeó de `gatelite-salud-eu` feature/012** (de Cristian, `github.com/cluna-8/gatelite-salud-eu`).
Ese producto heredado ("Basa Secure AI Gateway") trae 12 specs (001-012), 13 entidades ORM, suite Pytest 20/20,
y una constitución v1.0.0. **NO es greenfield**: hay mucho código real y sólido que se reutiliza (compliance,
budget, audit, white-label, compresión). Pero el pivote a producto exige construir lo que **no existe** (§5).

## 3. La constitución v2.0.0 (gobierna todo)

[`.specify/memory/constitution.md`](.specify/memory/constitution.md). Es una **reconciliación honesta** de la
v1.0.0 heredada + los añadidos del pivote demo→prod (no un reemplazo — un intento previo que borró principios
reales fue revertido). 8 principios:

| # | Principio | Origen |
|---|-----------|--------|
| I | Privacy & PII/PHI Masking-First (scopeable, reversible, "nunca solo regex en prod") | heredado (evolve) |
| II | Compliance & Governance FIRST (GDPR+AI Act; **2 niveles**: gate duro vs evidencia auditada) | fusión |
| III | Multi-Tenant by Design (`tenant_id` día 1 + RLS; **forward-looking, a construir**) | nuevo |
| IV | Client Onboarding as Data (`role=client` + `client_type` + APIKey por tool) | nuevo |
| V | Cost Governance & Optimization (budget **post-hoc honesto** + compresión) | fusión |
| VI | LiteLLM-Native, No Patching (reusar extension points; excepción: passthrough OAuth) | nuevo |
| VII | Containerized & White-Label (config+seed, never fork) | heredado (keep) |
| VIII | Pipeline Transparency & Explainability (Playground = vitrina) | heredado (evolve) |

Más: **Security & Compliance Constraints** (C1-C6), **Development Workflow** (SDD, tests, Docker), **Governance**
(reglas de enmienda), y **9 defaults `[D1]…[D9]`** revisables. Cada principio marca **qué es real hoy vs qué es meta**.

## 4. Roadmap del core (013-018)

Ver [`specs/ROADMAP-guardian.md`](specs/ROADMAP-guardian.md). Secuencia: **013 bedrock → 014 titular →** 015-018
endurecimientos. La deuda del producto heredado (A-F) está en [`specs/ROADMAP.md`](specs/ROADMAP.md) y se absorbe
donde corresponde (C2 Presidio→016, C3-C5 SSO→017, D5 env vars→017).

## 5. Estado actual: qué existe y qué no

- ✅ **Specced y listo para codear**: 013 (multi-tenant + client model), 014 (firewall LiteLLM-native). Cada una
  con `spec.md`/`plan.md`/`tasks.md`, revisadas por un crítico de honestidad-SDD (fixes aplicados).
- ✅ **Código heredado real** (reutilizable): compliance (`ComplianceProject`, DPA, DSR, consent, retention, DPO),
  budget/rate-limit, audit metadata-only, guardrails regex + masking reversible, compresión (`optimization_service`),
  RBAC JWT, white-label, migraciones Alembic 001-009, Playground.
- ❌ **NO existe todavía** (es lo que 013/014 construyen): `tenant_id` en cualquier tabla, RLS, entidad `Tenant`,
  `role="client"`, `client_type`, `Connection`/toggles por-tool, el firewall como extensión LiteLLM (hoy solo vive
  hand-rolled en el **repo demo**, ver §9), SecurityPolicy scopeada (hoy singleton global).

## 6. Cómo empezar a codear (SDD)

El repo usa **Spec-Kit** (`.specify/`). El flujo por feature es `spec.md → plan.md → tasks.md → implementar`.
013 y 014 ya tienen los 3. Entonces:

1. **Spec 013 primero** (bedrock — sin esto nada encaja). Abrí `specs/013-multi-tenant-foundation/tasks.md` y
   ejecutá T001… en orden. Orden crítico de la migración Alembic 010: **backfill del default-tenant ANTES** del
   `CHECK` de roles y del `ENABLE+FORCE RLS`. El on-prem single-tenant debe seguir andando (default tenant
   UUID `00000000-0000-0000-0000-000000000001`).
2. **Spec 014 después** (depende de 013). **Antes de US1**, corré la research **T005** (Phase-0): verificar que la
   imagen pinneada de LiteLLM ejecuta los 3 hooks del guardrail y normaliza el stream sobre `/v1/messages` nativo.
   Ese research decide Estrategia A (hook sobre `ModelResponseStream`) vs B (rewrite SSE, excepción acotada).
3. Cada cambio con lógica no trivial lleva **tests** (heredás Pytest); verificá con **Docker Compose** antes de mergear.
4. **No parchees LiteLLM** (Principio VI): reusá sus extension points. Única excepción autorizada: el passthrough
   OAuth de suscripción en el backend.

## 7. Hechos NO-obvios del código heredado (LEER antes de codear)

Mapeados el 2026-07-10 contra el código real. Ignorarlos = trampas garantizadas:

- **Es single-tenant de facto**: cero `tenant_id`, sin RLS. Todo lo multi-tenant es a construir (013).
- **Presidio es código muerto**: el scaffolding HTTP existe pero **nunca se invoca**, no hay servicio en
  `docker-compose.yml`, no está en `requirements.txt`. El masking real es **regex** (EMAIL, PHONE +54, DNI, CUIL,
  PERSON-por-prefijo). "Nunca solo regex en prod" es la Constraint **C2**; activarlo es la spec **016**.
- **Budget es real pero POST-HOC**: gate 402 pre-request + accounting post-request. **NO es "tiempo real"** y
  **el gateway no hace streaming** (`stream=False` hardcodeado). El texto heredado "incluso durante streaming"
  era declarativo — corregido en la constitución.
- **Compliance = fail-open / "evidencia auditada"**: consent/DPA/retention **NO bloquean en runtime**; la retención
  **nunca purga**; el alto-riesgo Anexo III solo se flaggea. Bloquean de verdad: AI-Act Art.5, PII marcada `BLOCK`,
  secretos, y residencia EU (503). Esto está ratificado como stance honesto de 2 niveles (`[D3]`), no es un bug.
- **Agujero de auth (a cerrar, Constraint C3 / spec 017)**: una request sin key válida **cae a un usuario admin por
  defecto** (`get_or_create_default_user` en el gateway del demo). Fail-closed pendiente.
- **RBAC heredado**: `users.role` es **String libre sin CHECK** (`admin`/`compliance_officer`/`clinician`/`developer`).
  013 lo reconcilia a enum (`super_admin`/`tenant_admin`/`compliance_officer`/`client`), degradando `clinician`/`developer`
  a labels de display.
- **`APIKey` vive en `backend/src/models/budget.py`** (tabla `api_keys`), **NO** en `user.py`. (Es la futura `Connection`.)
- La creación real de keys/clients está en `backend/src/api/keys.py`. **`seed_gateway_demo` NO está en este repo** —
  es del fork externo (gatelite); 013 lo porta/productiviza.

## 8. Cómo levantar el proyecto

```bash
cd basa-guardian
docker compose up -d           # backend + frontend + postgres + redis + motor
# migraciones Alembic se aplican al arranque (backend/alembic/)
```
Ver [`README.md`](README.md) y [`USE.md`](USE.md) para detalle de `.env` (claves de proveedores, `LITELLM_MASTER_KEY`,
JWT, Fernet) y flujos. `AGENTS.md` tiene convenciones para agentes en este repo.

## 9. Relación con el repo demo (gatelite) y el firewall a portar

- **`gatelite-salud-eu`** (repo hermano en `../gatelite-salud-eu`) = **repo DEMO**, tailor-made, se sigue usando para
  demos en vivo (incl. la demo del lunes: interceptar Claude Code / VS Code / Claude Desktop). **No es el producto.**
- El **firewall que la spec 014 porta** vive hand-rolled ahí: **`../gatelite-salud-eu/backend/src/api/gateway.py`**
  (~1015 líneas: `/gw/v1/messages`, `_detect_tool`, `_redact_body` con placeholders reversibles, `_rewrite_sse_event`
  para unmask sobre streaming, modos anthropic/byok, identidad por `X-Basa-Key`, monitor en vivo). 014 lo lleva a
  `CustomGuardrail` + `custom_auth` + `CustomLogger` nativos. Leelo como referencia de comportamiento.

## 10. Decisiones abiertas / defaults a confirmar con el usuario

Todo tomado como **default sensato y documentado** (el usuario pidió "no bloquear, defaults revisables"). Confirmá
antes de codear la parte que los materializa:

- **Constitución `[D1]…[D9]`** (ver su sección "Decisiones"): versionado 2.0.0, Playground→observabilidad,
  compliance fail-open de 2 niveles, Presidio-en-prod, RBAC reconciliado, etc.
- **013**: (a) frontera cascade 013↔015 (013 = defaults de contexto legal_basis/risk/project; 015 = SecurityPolicy);
  (b) incluir `tenant_id`+RLS en las 5 tablas de compliance no listadas (recomendado, evita fugas cross-tenant);
  (c) ventana de deploy de la migración FORCE-RLS ↔ cableado del GUC en runtime (llega con la identidad de 017).
- **014**: (a) **`[D-014]`** identidad en modo suscripción sin `X-Basa-Key` = atribución por `X-Basa-Key` si está,
  si no tenant-default anónimo auditado (revisable); (b) Estrategia A vs B de unmask streaming = la decide la research
  **T005**; (c) provisioning de virtual keys directo por `key_hash` contra la `APIKey` de Basa (preferido).

## 11. Coordinación con Cristian

Basa Guardian arrancó **sobre `feature/012` de Cris** (branch renombrada a `main`, **sin remote** — repo de producto
independiente). Antes de un push/colaboración, coordiná con él si hay updates nuevos en su repo. La deuda heredada
que sigue vigente está en `specs/ROADMAP.md` (A-F).

---

*Generado por la sesión de preparación del 2026-07-10. El demo del lunes (gatelite) queda intacto y funcionando;
este repo (basa-guardian) es el producto a codear.*
