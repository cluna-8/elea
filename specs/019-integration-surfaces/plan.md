# Implementation Plan: Integration Surfaces & Client Compatibility

**Branch**: `019-integration-surfaces` | **Date**: 2026-07-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/019-integration-surfaces/spec.md`

## Summary

Documentar y **portar el LADO CLIENTE** del firewall de Sentinel: qué herramientas se integran, **cómo** se
enganchan a Sentinel, y la **matriz de compatibilidad** real con su por-qué técnico. Complementa la **014**
(que formalizó el lado gateway) desde el otro extremo de la conexión.

Las superficies existen y se probaron en vivo en el **demo** `gatelite-salud-eu`; esta spec las **porta**
a `sentinel-guardian` y las versiona. Hay dos familias de superficie:

1. **base_url clients** (coding tools que apuntan `ANTHROPIC_BASE_URL` al gateway): Claude Code
   (**passthrough de suscripción**, FUNCIONA con Agent) y VS Code/Copilot (**auto-byok + key-in-URL**,
   PARCIAL, sólo Ask). El enganche reusa mecanismos estándar del cliente + el ruteo del gateway
   (`X-Sentinel-Upstream`, `_SENTINEL_KEY_RE`, exclusión de `x-sentinel-*`, `_resolve_identity`, `_TOOL_UA`).
2. **browser surface** (web apps sin base_url): una **extensión MV3** (`sentinel-browser-dlp/`) que hookea
   `window.fetch` en el mundo MAIN, enmascara vía `POST /gw/inspect`, reescribe el body (el modelo ve
   placeholders) y des-enmascara en el DOM con `MutationObserver`. Adapters para ChatGPT y Claude web (con
   cobertura de la fuga de título).

El artefacto transversal es la **matriz de compatibilidad**: FUNCIONA / PARCIAL / NO / MCP-ONLY con la
razón técnica de cada estado (incluyendo Cursor=**PARCIAL** —Override OpenAI Base URL honrado sólo en
chat/plan, como Copilot Ask— y Claude Desktop=MCP-ONLY de alcance **tool-plane**). El enfoque central: **reuso
de mecanismos estándar** del cliente (Principio VI), **onboarding as data** por `Connection`/`APIKey`
(Principio IV) y **un único pipeline transparente** para todas las superficies (Principio VIII).

## Technical Context

**Language/Version**: Python 3.11 (backend FastAPI: el ruteo de superficies base_url + endpoints de la
extensión); JavaScript (extensión MV3: content scripts, service worker).

**Primary Dependencies**: El **gateway/firewall de la 014** (al que apuntan estos clientes) y el **schema
013** (`Connection`/`APIKey` con `tool_type`/`upstream_mode`). Del lado cliente: `ANTHROPIC_BASE_URL` de
los coding tools; APIs MV3 del navegador (content scripts MAIN/ISOLATED, service worker, `chrome.storage`).
Servicios reusados: `PresidioService` (masking en `/gw/inspect`), `AuditService` (metadata-only),
`_resolve_identity` (identidad).

**Storage**: PostgreSQL (Connection/APIKey/AuditLog de la 013, metadata-only). La extensión guarda la key
en el service worker (`chrome.storage`), NO en el mundo MAIN. Feed del monitor: ring en memoria (compartido
con la 014, `surface="browser"` para la extensión).

**Testing**: pytest — integration tests del ruteo (passthrough vs auto-byok vs key-in-URL, exclusión de
`x-sentinel-*`), del endpoint `/gw/inspect` (mask + fail-closed + surface=browser), y de la detección por UA.
Tests de la extensión (unit/adapters): mask/unmask, `unmaskTitle`, fail-closed sin key. La **matriz** se
valida como documentación (cobertura + razón concreta por entrada).

**Target Platform**: Linux server en containers (backend/gateway, Principio VII) + navegador del usuario
(extensión MV3, Chromium).

**Performance Goals**: no degradar la latencia del proxy actual; el masking corre inline en `/gw/inspect`
y en los hooks del gateway (014). Sin objetivo de throughput nuevo.

**Constraints**: masking ANTES de que el prompt salga (placeholders atómicos, Principio I); la key de la
extensión jamás en el mundo MAIN (fail-closed, service worker only); auditoría metadata-only (Constraint C1);
credenciales fuera de config en claro (Constraint C5); GDPR-routing N/A en base_url/browser (excepción
acotada del Principio II); key-in-URL **sólo** como atajo de demo (prod = input seguro/SSO).

**Scale/Scope**: portar el ruteo de superficies (backend) + la extensión MV3 (4 archivos:
`manifest.json`, `guardia-main.js`, `bridge.js`, `background.js` + `popup.*`) + los endpoints
`/gw/whoami` y `/gw/inspect` + la matriz de compatibilidad. Sin schema nuevo propio (todo viene de 013/014).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio / Constraint | Cómo lo cumple esta feature | Veredicto |
|---|---|---|
| **IV. Client Onboarding as Data** | Cada superficie soportada = una `Connection`/`APIKey` (013) con `tool_type`/`upstream_mode`; onboardear una herramienta soportada es config+seed. Las no soportadas se documentan (matriz). | PASS by-design |
| **VI. LiteLLM-Native, No Patching** | El enganche reusa mecanismos estándar del cliente (`ANTHROPIC_BASE_URL`, `x-api-key`, `window.fetch`); el ruteo (passthrough/byok) es el del gateway 014. La única superficie de proxy propio (passthrough de suscripción) ya está acotada por la 014. | PASS by-design |
| **VIII. Pipeline Transparency** | Todas las superficies (base_url + browser) empujan su before/after al **mismo** monitor; la extensión con `surface="browser"`. Datos reales, animación cosmética. | PASS by-design / a verificar |
| **I. Privacy & Masking-First** | Masking antes de que salga el prompt (gateway hooks y `/gw/inspect`); unmask en DOM; placeholders atómicos; la extensión no expone PII al modelo. | PASS by-design |
| **Constraint C1 No Raw PII/PHI Storage** | `/gw/inspect` audita metadata-only; el monitor no persiste texto de prompt ni PII cruda. | PASS by-design / a verificar |
| **Constraint C3 Fail-closed auth** | La extensión es fail-closed sin key válida (`/gw/whoami`); la identidad base_url reusa `_resolve_identity`. (El fail-closed **duro** de byok lo gobierna la 014; aquí se reusa.) | PASS by-design |
| **Constraint C5 Credenciales fuera de config** | La key de la extensión vive en el service worker (no en el mundo MAIN); key-in-URL marcada como atajo de demo (prod = SSO). | PASS by-design / a verificar |
| **Excepción Principio II (GDPR-routing N/A)** | base_url + browser interceptan sin re-inyectar → GDPR-routing N/A, ya ratificado (constitución + 014). Se reusa, no se re-abre. | PASS (excepción ratificada) |
| **Dev Workflow — Reuse over Reinvent** | Porta mecanismos ya probados en el demo; no inventa superficies nuevas (Gemini es aditivo/roadmap). | PASS by-design |

**Sin violaciones nuevas**: esta spec **no** introduce proxy propio nuevo (la única excepción, el
passthrough de suscripción, ya la autorizó y acotó la 014). Ver Complexity Tracking.

## Mapeo demo → superficies portadas

Traducción fiel de la evidencia del demo (`gatelite-salud-eu/backend/src/api/gateway.py` y
`sentinel-browser-dlp/`) a los requisitos de esta spec. Columna "Dueño" = REUSA-gateway vs PROPIO.

| Demo (evidencia) | Objetivo portado (019) | Dueño |
|---|---|---|
| modo `anthropic` (default) — reverse-proxy verbatim a `api.anthropic.com` | `subscription-passthrough` (US1): OAuth verbatim, suscripción paga | REUSA gateway (014) |
| `X-Sentinel-Upstream` + `SENTINEL_GW_UPSTREAM_DEFAULT` | selección de modo por header/env (FR-002) | REUSA gateway |
| `_passthrough_headers` (anthropic-version/beta, UA, x-app) | reenvío verbatim de headers de Claude Code (FR-003) | REUSA gateway |
| `_SENTINEL_KEY_RE = sk-sentinel-…` + auto-byok (scan de headers de auth) | auto-byok por virtual key (US2, FR-008) | REUSA gateway |
| exclusión `x-sentinel-*` en el scan de auto-byok | exclusión load-bearing (FR-009) | REUSA gateway (protege coexistencia) |
| key-in-URL (`?k=sk-sentinel-…`, `_with_query`/`request.url`) | fallback de Copilot (FR-010) | REUSA gateway (atajo de demo) |
| `_resolve_identity` (X-Sentinel-Key → sha256 → user/group) | identidad/atribución, no credencial (FR-006/FR-007) | REUSA gateway |
| `_TOOL_UA`/`_detect_tool` (UA → tool_type) | detección de herramienta (FR-004) | REUSA gateway |
| `manifest.json` (MAIN + ISOLATED, host_permissions, all_frames:false) | extensión MV3 base (US3) | PROPIO (a portar) |
| `guardia-main.js` (hook `window.fetch`, mask vía `/gw/inspect`, unmask DOM, unmaskTitle) | content script MAIN (FR-013/14/16) | PROPIO |
| adapters `chatgpt` (`/backend-api/f/conversation`, parts[]) y `claude` (`/completion` + `/title`) | adapters por web app (FR-018) | PROPIO |
| `bridge.js` (ISOLATED) + `background.js` (service worker con la key) | aislamiento de la key del mundo MAIN (FR-017) | PROPIO |
| `GET /gw/whoami` (valida key → user/team) | login/fail-closed del popup (FR-015) | REUSA gateway |
| `POST /gw/inspect` (mask + `surface="browser"` + `_log_tx`) | inspección + monitor + audit (FR-014/19) | REUSA gateway |
| — (no existe en el demo) | **matriz de compatibilidad** (US4, FR-020/21) | PROPIO (documentación NUEVA) |
| host_permissions sólo chatgpt/openai/claude | **Gemini** = gap (host + adapter) → roadmap (US5, FR-022) | PROPIO (roadmap) |

## Project Structure

### Documentation (this feature)

```text
specs/019-integration-surfaces/
├── plan.md              # This file
├── spec.md              # Feature spec (user stories, FR, SC, matriz de compatibilidad)
├── tasks.md             # Task list (por user story)
├── research.md          # Phase 0: open questions resueltas — Cursor=PARCIAL (chat/plan), Claude Desktop MCP=tool-plane, Gemini=DOM-hook (spike), strip-tools no gobierna el agente, prior-art browser-DLP; + Ask vs Agent, body no firmado, WebSocket vs fetch
├── compatibility.md     # Phase 1 (a generar): matriz de compatibilidad viva + criterios de estado
└── quickstart.md        # Phase 1 (a generar): apuntar Claude Code / Copilot; instalar la extensión; ver el monitor
```

### Source Code (repository root)

```text
backend/src/
├── api/
│   ├── gateway.py                     # ruteo de superficies base_url: passthrough vs auto-byok vs key-in-URL (reusa 014)
│   └── inspect.py                     # endpoints browser-DLP: GET /gw/whoami, POST /gw/inspect (surface=browser)
├── services/                          # REUSADOS: PresidioService (mask), AuditService (metadata-only), identidad
└── models/                            # REUSADOS de la 013: APIKey (=Connection con tool_type/upstream_mode), AuditLog

extension/                             # extensión MV3 (a portar de sentinel-browser-dlp/)
├── manifest.json                      # content scripts MAIN + ISOLATED; host_permissions; all_frames:false
├── guardia-main.js                      # PROPIO (MAIN): hook window.fetch, mask vía /gw/inspect, unmask DOM + unmaskTitle, adapters
├── bridge.js                          # PROPIO (ISOLATED): puente content-script ↔ service worker
├── background.js                      # PROPIO (service worker): guarda la key; el MAIN nunca la ve
└── popup.html / popup.js              # PROPIO: login del popup (valida contra /gw/whoami)

tests/
├── integration/                       # ruteo de superficies (passthrough/auto-byok/key-in-URL/exclusión x-sentinel-*); /gw/inspect
└── unit/                              # detección por UA; adapters de la extensión (mask/unmask/unmaskTitle/fail-closed)
```

**Structure Decision**: web-service en containers (Principio VII) + extensión de navegador. El código se
divide por **hogar de ejecución**: (a) el **backend** gobierna el ruteo de las superficies base_url y sirve
los endpoints de la extensión (`/gw/whoami`, `/gw/inspect`), reusando el gateway/firewall de la 014;
(b) la **extensión MV3** corre en el navegador del usuario (mundo MAIN para el hook + mundo ISOLATED/service
worker para la key). No se crea schema nuevo: `Connection`/`APIKey`/`AuditLog` vienen de la 013. La matriz
de compatibilidad es un **artefacto de documentación** (spec + `compatibility.md`).

## Orden de implementación

1. **Fundacional — Phase 0 research + matriz.** Confirmar contra el demo (y contra cada cliente real) el
   comportamiento de Ask vs Agent, body no firmado, WebSocket vs fetch, y los gaps de Gemini/iframe.
   Fijar la **matriz de compatibilidad** (criterios de estado). Bloquea las claims de US1/US2/US4.
2. **US1 Claude Code passthrough (P1).** Portar/verificar el ruteo `subscription-passthrough` (OAuth
   verbatim + `_passthrough_headers` + detección por UA + identidad por `X-Sentinel-Key`). Demo titular.
3. **US2 VS Code/Copilot auto-byok (P1).** Portar/verificar auto-byok (`_SENTINEL_KEY_RE`) + la **exclusión de
   `x-sentinel-*`** (load-bearing) + key-in-URL; documentar Ask vs Agent. Va con US1 (coexistencia).
4. **US3 extensión MV3 (P1).** Portar la extensión (`manifest`/`sentinel-guard`/`bridge`/`background`), los
   adapters (chatgpt + claude con `/title`) y los endpoints `/gw/whoami`/`/gw/inspect` (surface=browser).
5. **US4 matriz de compatibilidad (P2).** Consolidar la matriz (FUNCIONA/PARCIAL/NO/MCP-ONLY) con razones
   concretas; documentar Cursor=**PARCIAL** (sólo chat/plan, como Copilot Ask; el agente Composer no rutea
   por el endpoint custom) y Claude Desktop=MCP-ONLY (**tool-plane**).
6. **US5 Gemini roadmap (P3).** Documentar el patrón de adapter + host match como aditivo; NO entregarlo.
7. **Cierre.** Verificación E2E (apuntar Claude Code/Copilot; instalar la extensión; ver el monitor);
   validar `quickstart.md`; confirmar que sumar una superficie soportada es config+seed.

## Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **La exclusión de `x-sentinel-*` en el auto-byok es load-bearing**: si se pierde, Claude Code (que trae `X-Sentinel-Key` con `sk-sentinel-…`) se desvía a byok y deja de usar su suscripción. | Alto — rompe la demo titular y factura mal. | Test explícito de coexistencia (SC-002): passthrough + byok en el mismo gateway; test negativo sin la exclusión. |
| **Tool-calling agéntico no-Claude rompe (`tool_use_failed`)**: Copilot en Agent y Cursor. | Medio — expectativa mal seteada si se promete Agent. | Fijar Ask/chat-plan como modo soportado: Copilot **y Cursor** = **PARCIAL** (sólo el modo sin-tools es gobernable; el agente Composer/Copilot-Agent no rutea por el endpoint custom); documentar el 400 por input UUID como esperado. **Strip-tools NO habilita el agente** (degrada a chat, rompe la UI que espera `tool_calls`, no frena tool-calls por system prompt). |
| **Fuga de título en Claude.ai** (`/title` con prompt crudo): si el adapter sólo cubre `/completion`, el título filtra PII. | Alto — fuga de PII. | El adapter `claude` cubre `/completion` **y** `/title`; `unmaskTitle()` con test. |
| **Respuesta por WebSocket** (no por el `fetch` hookeado): el unmask no puede ir sobre el transporte de respuesta. | Medio — placeholders crudos visibles si se asume fetch. | Unmask **en el DOM** vía `MutationObserver` (no sobre transporte); test sobre DOM. |
| **`all_frames:false`**: artefactos en iframe no se des-enmascaran. | Bajo — gap acotado. | Documentado como limitación conocida; roadmap `all_frames:true` + control de superficie. |
| **Body firmado por la web app**: si ChatGPT/Claude firmaran el body, la reescritura se detectaría. | Medio — la técnica no aplicaría a esa superficie. | Verificado hoy: body no firmado; Phase 0 lo re-confirma; la matriz marca la dependencia. |
| **Cap de inspección muestrea la cola del último turno**: un secreto al inicio de un prompt agéntico gigante puede quedar fuera. | Medio — bypass de detección. | Documentado; mitigación roadmap (subir cap / inspección por turnos completos). |
| **Key-in-URL logueable**: la key en `?k=…` puede terminar en logs. | Medio — fuga de credencial. | Marcada como **atajo de demo**; prod = input seguro/SSO; no se normaliza en la spec. |
| **Key expuesta en el mundo MAIN**: si el content script MAIN tuviera la key, cualquier script de la página la leería. | Alto — robo de credencial. | La key vive **sólo** en el service worker; MAIN habla vía `bridge.js` (ISOLATED); test de aislamiento (SC-005). |

## Complexity Tracking

> Sin violaciones nuevas de principio en esta feature.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| *(ninguna nueva)* | El passthrough de suscripción —la única excepción de proxy propio del Principio VI— ya fue autorizada y acotada por la **014**. Esta spec la **consume** desde el lado cliente sin introducir proxy propio nuevo. | La extensión MV3 y el ruteo base_url reusan mecanismos estándar del cliente/gateway; no reimplementan routing/streaming/cost-ceiling. Gemini y Claude-Desktop-MCP son **roadmap documentado**, no proxy propio. |
