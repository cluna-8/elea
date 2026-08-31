# Sentinel Guardian — Secure AI Gateway (white-label)

Firewall de IA **white-label** para entornos regulados (salud/EU): una **puerta única** por la que pasan
todos los prompts de una organización hacia los LLMs, aplicando **enmascaramiento reversible de PII/PHI**,
bloqueo por **AI Act**, detección de **secretos**, **presupuestos** y **auditoría inmutable metadata-only**
— multi-tenant, empaquetado para venderse vía distribuidor (deploy air-gapped + licencias offline).

**El moat**: des-enmascarar en vez de bloquear. El modelo recibe placeholders (`[PERSON_0]`, `[DNI_0]`);
el usuario ve los valores reales restaurados. La UX no se rompe; el dato nunca sale.

---

## Cómo funciona — la puerta única

Un solo endpoint (`/api/v1/gw`) auto-detecta el modo de cada cliente y rutea:

```text
                             ┌──────────────────────────────────────────────┐
  Claude Code (OAuth) ─────► │            GATEWAY  /api/v1/gw               │
  Copilot/Cursor (sk-sentinel-…) │                                              │
  Extensión browser ───────► │  passthrough ──► política AQUÍ ─► api.anthropic.com
                             │  byok ─────────► router fino ──► MOTOR LiteLLM
                             │  /gw/inspect ──► mask para la extensión MV3  │
                             └──────────────────────────────────────────────┘
                                                        MOTOR = custom_auth (fail-closed)
                                                        + SentinelGuardrail + audit + budgets
```

- **`subscription-passthrough`** (Claude Code): el OAuth de suscripción del cliente viaja **verbatim** a
  `api.anthropic.com`; la política (AI-Act/secretos/mask-unmask sobre SSE) la aplica **el gateway**.
- **`byok`** (Copilot, Cursor, cualquier tool con base URL): se detecta una virtual key `sk-sentinel-…` en un
  header de auth (o `?k=…`) → router fino al **motor LiteLLM**, que aplica la política (custom_auth +
  SentinelGuardrail). El gateway **no** la duplica (evita doble-masking).
- **Browser** (ChatGPT/Claude web): la extensión MV3 (`extension/`) intercepta `window.fetch`, enmascara
  vía `POST /api/v1/gw/inspect` y des-enmascara el DOM. Fail-closed sin key válida (`/api/v1/gw/whoami`).

Detalle completo del ruteo y la exclusión `x-sentinel-*`: [specs/019 — compatibility.md](specs/019-integration-surfaces/compatibility.md).

---

## Quickstart (dev local)

```bash
cp .env.example .env      # completar JWT/Fernet y las API keys de los providers que uses
docker compose up -d --build
```

> **Puertos** (desplazados para coexistir con el repo demo `gatelite`, que ocupa 5432/4000/8080/8081):

| Servicio | URL / puerto |
|---|---|
| Frontend (panel + playground) | http://localhost:8090 |
| Backend API (Swagger) | http://localhost:8091/docs |
| **Gateway (puerta única)** | `http://localhost:8091/api/v1/gw` |
| Monitor en vivo (todas las superficies) | http://localhost:8091/api/v1/gw/monitor |
| Motor LiteLLM (interno) | http://localhost:4010/health/readiness |
| Motor de detección NLP (interno, sin puerto al host) | `NLP_ANALYZER_URL` (default `http://nlp-analyzer:3000`) |
| PostgreSQL (host) | `localhost:5433` |

**Primer login**: entrar al frontend como `admin` con la contraseña que elijas — el primer login
la fija (bootstrap; queda como `tenant_admin`, email `admin@sentinel.com.ar`).

**Sin API keys reales no hay respuesta de LLM**: el sistema es **fail-closed** (no existe modo
simulado). El panel, las políticas, el seed y la suite de tests funcionan igual sin keys.

**Probar el firewall en 60 segundos** (Claude Code contra tu gateway local):

```bash
export ANTHROPIC_BASE_URL="http://localhost:8091/api/v1/gw"
claude   # tu OAuth viaja verbatim; el gateway aplica la política y empuja al monitor
```

Más recetas por cliente (Copilot, extensión browser, coexistencia): [specs/019 — quickstart.md](specs/019-integration-surfaces/quickstart.md).

---

## Compatibilidad de clientes

Resumen de la **matriz viva** ([specs/019 — compatibility.md](specs/019-integration-surfaces/compatibility.md) —
esa es la fuente de verdad; los estados exigen evidencia, nunca "pendiente". Las filas ⚪ vienen de su
sección *Candidatos*: sin estado hasta que un spike las promueva):

| Cliente | Superficie | Estado | Notas |
|---|---|---|---|
| **Claude Code** (CLI) | base_url | ✅ **Funciona** | Passthrough OAuth verbatim; aguanta modo **Agent**. Identidad por UA + `X-Sentinel-Key`. Verificado en vivo. |
| **ChatGPT** (web) | extensión | ✅ **Funciona** | Adapter `chatgpt`; body no firmado → acepta reescritura enmascarada. Verificado en vivo. |
| **Claude** (web) | extensión | ✅ **Funciona** | Adapters `/completion` + `/title` (cubre la fuga del título). Verificado en vivo. |
| **VS Code / GitHub Copilot** | base_url | 🟡 **Parcial** | byok (auto-detección `sk-sentinel-…` + key-in-URL). Sólo modo **Ask** — en Agent, los modelos no-Claude rompen el tool-calling. |
| **Cursor** | base_url | 🟡 **Parcial** | Override OpenAI Base URL → sólo panel chat/plan (Cmd+L). Composer/inline/autocomplete van clavados al backend de Cursor. |
| **Gemini** (web) | extensión | 🔜 **Not yet** (viable) | Falta adapter + host match; camino identificado: DOM-hook sobre el editor Quill (requiere spike). |
| **Claude Desktop** | MCP | 🔒 **MCP-only** | Sin base_url ni hook interceptable. Sólo gobernable en el tool-plane (args/results de tools), no el chat. |
| **ChatGPT Desktop** (app nativa) | — | ❌ **Not yet** | Mismo gap desktop: sin base_url, cert-pinning. Sin camino identificado hoy. |
| Windsurf / JetBrains AI / Zed | base_url | ⚪ **Por validar** | Candidatos byok donde expongan base URL OpenAI/Anthropic-compatible. Sin evidencia aún. |
| Aider / Cline / Continue | base_url | ⚪ **Por validar** | Base URL configurable de fábrica → candidatos byok directos. Sin evidencia aún. |
| Codex CLI / Gemini CLI | base_url | ⚪ **Por validar** | Codex expone `OPENAI_BASE_URL` (candidato byok); Gemini CLI habla con endpoint Google (requiere spike). |

> Sumar una superficie **soportada** = crear una `Connection` (config + seed, 0 código). Las no
> soportadas se documentan con su razón técnica en la matriz.

## Compatibilidad de proveedores LLM

Dos planos, con reglas distintas:

**1. Plano passthrough (suscripción)** — **Anthropic únicamente, por diseño**: reenvía el OAuth de
suscripción de Claude Code verbatim a `api.anthropic.com`. No hay equivalente para otros providers
(ninguno expone ese modelo de suscripción-con-base_url hoy).

**2. Plano byok (motor LiteLLM)** — el motor rutea a **100+ providers**; agregar uno = un bloque en
[`litellm/config.yaml`](litellm/config.yaml) + su API key en `.env` (0 código):

| Provider | Estado | Env var |
|---|---|---|
| **OpenAI** (gpt-4o, gpt-4o-mini) | ✅ Configurado | `OPENAI_API_KEY` |
| **Anthropic** (claude-3-5-sonnet) | ✅ Configurado | `ANTHROPIC_API_KEY` |
| **Azure OpenAI** (gpt-4o-mini) | ✅ Configurado | `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_ENDPOINT` / `AZURE_API_VERSION` (el compose las mapea al motor) |
| **Google Gemini** (2.5 flash / flash-lite) | ✅ Configurado | `GEMINI_API_KEY` |
| **Ollama** (local / cloud) | ✅ Configurado | — (api_base al host) |
| AWS Bedrock · GCP Vertex AI | ⚪ Soportado por el motor | credenciales cloud |
| OpenRouter · Groq · Mistral · Cohere | ⚪ Soportado por el motor | key del provider |
| Together · Fireworks · DeepSeek · xAI (Grok) | ⚪ Soportado por el motor | key del provider |
| Perplexity · Hugging Face · Replicate · Databricks | ⚪ Soportado por el motor | key del provider |
| Cloudflare Workers AI · IBM watsonx · NVIDIA NIM · SageMaker | ⚪ Soportado por el motor | key del provider |

> **Configurado** = ya cableado en `config.yaml` (falta sólo la key). **Soportado** = el motor
> (LiteLLM, pinneado por digest) lo rutea; se agrega editando config, sin tocar código. La política de
> firewall (guardrail/auth/audit) es **provider-agnóstica**: aplica igual a cualquiera.

---

## Arquitectura del repo

```text
backend/           FastAPI — API, gateway puerta-única (src/api/gateway.py), /gw/inspect (browser),
                   multi-tenant (013: RLS + tenants), presupuestos, compliance, audit
litellm/           Motor LiteLLM + extensiones nativas (014):
  extensions/        sentinel_guardian_policy.py  ← política PURA compartida (mask/unmask, AI-Act, secretos)
                     custom_auth.py           ← identidad fail-closed (virtual key → tenant/client/tool)
                     sentinel_guardrail.py        ← 3 hooks (pre/post/streaming)
                     sentinel_audit_logger.py     ← audit metadata-only + feed del monitor
frontend/          React + Vite + Tailwind (panel, playground, monitor)
extension/         Extensión MV3 Sentinel Guard (browser-DLP: ChatGPT/Claude web)
specs/             SDD — una spec por feature (spec/plan/tasks/research); ver ROADMAP-guardian.md
deploy/            Install & Factory (depto Falime): bundles white-label, perfiles de clientes,
                   imágenes prod, checks de release — en mudanza a repo propio guardian-factory
docs/              Docs de operación: integration-surfaces, whitelabel-deployment, compliance-policies
docs-cliente/      Sitio de docs para el cliente final (viaja en el kit de sede)
tech-team/         Mapas del equipo: EcosystemOverview, TechTree, Licencias, RunbookCamara, DevFlow
.specify/          Spec-Kit (constitución + templates + scripts del flujo SDD)
```

**Stack**: Python 3.12 / FastAPI · LiteLLM (pinneado por digest) · PostgreSQL 16 (RLS multi-tenant) ·
Redis · React/Vite · Docker Compose.

## Tests

```bash
# Suite completa del backend (unit + integration + contract), contra Postgres real:
docker compose run --rm --no-deps backend pytest tests/ -q          # 979 tests
# Contract checks del motor (DENTRO de la imagen pinneada):
docker compose exec -T litellm python /app/extensions/contract_checks.py
docker compose exec -T litellm python /app/extensions/integration_checks.py
# E2E reales (cruzan gateway→motor→Postgres; requieren el stack arriba, si no se saltan):
docker compose -p sentinel-guardian run --rm --no-deps backend pytest tests/e2e -q
```

## Flujo de desarrollo (SDD)

El repo se desarrolla **spec-driven** con [Spec-Kit](.specify/): cada feature vive en `specs/NNN-*/`
(`spec.md` → `plan.md` con research Phase 0 → `tasks.md` → implementación → `implementation-notes.md`).
Usar el **tooling de Spec-Kit** (skills `speckit-*` y `.specify/scripts/`) para los pasos SDD — no
ediciones manuales; `speckit-analyze` valida consistencia spec↔plan↔tasks.

- **Estado y secuencia**: [`specs/ROADMAP-guardian.md`](specs/ROADMAP-guardian.md) — 013–014, 016,
  019–022, 024 y 027–031 implementadas en `main`; 017/018, 023 y 033/034 en roadmap. El tech tree con
  fases y gates 125/250/500: [`specs/ROADMAP-pisos.md`](specs/ROADMAP-pisos.md).
- **Departamentos** (decisión 2026-08-03, supera la división por módulos del 15-jul): Guardian App
  Ecosystem (JF, el producto) e Install & Factory (Falime, `deploy/`); Cristian = gate de seguridad, no
  departamento. Convención de trabajo: [CONTRIBUTING.md](CONTRIBUTING.md) + [CODEOWNERS](.github/CODEOWNERS);
  operativa del depto Guardian: [tech-team/DevFlow-SentinelGuardian.md](tech-team/DevFlow-SentinelGuardian.md).
- **Gobernanza**: [`.specify/memory/constitution.md`](.specify/memory/constitution.md) (principios I–VIII;
  fail-closed, audit metadata-only, white-label config-as-data, never fork).
- **Flujo de PRs**: cada spec/fase → branch → PR (merge humano). Hardening con review multi-agente +
  gate independiente de Codex CLI (`codex review --base main`).

## Docs

- [Superficies de integración](docs/integration-surfaces.md) — training/soporte por cliente
- [Deploy white-label](docs/whitelabel-deployment.md) — runbook distribuidor (spec 020)
- [Políticas de compliance](docs/compliance-policies.md) — GDPR / AI Act
- [Matriz de compatibilidad](specs/019-integration-surfaces/compatibility.md) — la fuente de verdad viva
