# Matriz de compatibilidad — Basa Guardian (superficies de cliente)

**Spec**: 019 · **Estado**: viva (se actualiza al sumar/validar superficies) · **Última**: 2026-07-14

Contrato de onboarding: para cada herramienta, **qué funciona, cómo se engancha y por qué**
(incluido lo que NO). Los estados FUNCIONA/PARCIAL reflejan comportamiento observable (US1–US3);
NO/MCP-ONLY llevan razón técnica concreta, nunca "pendiente" (SC-006).

## Criterios de estado (T005)

| Estado | Evidencia mínima que exige |
|---|---|
| **FUNCIONA** | Se engancha por un mecanismo estándar y el ciclo completo (incl. masking/unmask) corre sin corromper la herramienta. Para coding tools: aguanta su modo de trabajo real (Agent si aplica). |
| **PARCIAL** | Se engancha pero con una limitación conocida y acotada (p.ej. sólo modo Ask/chat, no Agent). La limitación tiene razón técnica y test/documentación. |
| **NO (roadmap)** | Hoy no se engancha, pero es **viable** por un camino identificado (gaps concretos nombrados). No hay promesa de hecho. |
| **MCP-ONLY** | No expone base_url ni hook interceptable; sólo gobernable vía servidor MCP y sólo en el **tool-plane** (args/results de tools), no el chat. |

## Matriz

| Herramienta | Superficie | Estado | Mecanismo de enganche | Razón / notas |
|---|---|---|---|---|
| **Claude Code** | base_url | **FUNCIONA** | `ANTHROPIC_BASE_URL` → `subscription-passthrough`; OAuth verbatim; identidad por UA + `X-Basa-Key` | Aguanta modo **Agent** (modelos Claude no rompen el tool-calling). Superficie titular. Verificado live: OAuth reenviado a `api.anthropic.com` (401 real con `request_id`). |
| **VS Code / GitHub Copilot** | base_url | **PARCIAL** | byok por **auto-byok** (`sk-basa-…`) + **key-in-URL** (`?k=…`); `x-api-key` vacío | Sólo **modo Ask**. En **Agent** loopea: modelos no-Claude rompen tool-calling y VS Code rechaza input UUID → 400. |
| **ChatGPT (web)** | browser | **FUNCIONA** | Extensión MV3, adapter `chatgpt` (`/backend-api/f/conversation`) | Body no firmado → acepta reescritura enmascarada. |
| **Claude (web)** | browser | **FUNCIONA** | Extensión MV3, adapter `claude` (`/completion` **y** `/title`) | Cubre la **fuga de título** (`unmaskTitle`). Respuesta por WebSocket → unmask en DOM. |
| **Cursor** | base_url | **PARCIAL** | **Override OpenAI Base URL** (Settings→Models) → gateway; sólo panel **chat/plan** (Cmd+L) | Como Copilot Ask: gobernable sólo sin-tools. El agente (Composer), inline y autocomplete están clavados al backend de Cursor; el "Override Anthropic Base URL" se auto-activa y rompe con **422**. |
| **Gemini (web)** | browser | **NO (roadmap, viable)** | — (falta adapter + host) | Ver "Gemini — roadmap" abajo. |
| **Claude Desktop** | desktop | **MCP-ONLY** | Servidor MCP (**tool-plane**) | Sin `ANTHROPIC_BASE_URL` ni hook interceptable. El MCP server sólo ve args/results de tools, nunca el chat: gobierna el tool-plane (DLP sobre results, audit de tool calls), **no** el prompt del usuario. Masking del chat = gap conocido no cubrible por esta vía. |

## Ruteo (puerta única) — cómo el gateway decide

Un solo endpoint `…/api/v1/gw/v1/messages`; el modo se auto-detecta (o se fuerza con `X-Basa-Upstream`):

- **`subscription-passthrough`** (Claude Code): OAuth del cliente verbatim → `api.anthropic.com`. La
  política (AI-Act/secretos/mask/unmask) la aplica **el gateway**.
- **`byok`** (Copilot/Cursor): virtual key `sk-basa-…` detectada en un header de auth (excl. `x-basa-*`)
  o en `?k=…` → **router fino al motor LiteLLM**. La política la aplica **el motor** (custom_auth +
  BasaGuardrail de 014); el gateway NO la duplica.
- **Exclusión `x-basa-*` (load-bearing)**: el `sk-basa` de atribución de Claude Code viaja SOLO en
  `X-Basa-Key` y está excluido del scan de auto-byok → Claude Code no se desvía a byok. Test:
  `tests/integration/test_surface_routing.py::test_xbasa_key_excluded_stays_passthrough`.

## Gemini web — roadmap (US5, NO implementado)

Sumar Gemini es **aditivo** (no un mecanismo nuevo) y **viable**, con dos gaps concretos:

1. **Host match** en `extension/manifest.json` → agregar `https://gemini.google.com/*` a `matches`
   (hoy sólo chatgpt/openai/claude).
2. **Adapter** en `extension/basa-guard.js` → `{ id:"gemini", vendor:"Google", match, read, write }`.

Recomendación (research): el endpoint es `StreamGenerate` (POST `batchexecute`, **no** WebSocket →
fetch-interceptable) pero el prompt va enterrado en `f.req` (JSON anidado ofuscado). Por eso conviene
un **DOM-hook** (editor Quill `.ql-editor`, como las extensiones DLP existentes) antes que el fetch-hook
(más frágil) — requiere un **spike** en vivo. No se entrega en 019.

## Limitaciones conocidas (documentadas, no defectos)

- **`all_frames:false`**: artefactos en iframe no se des-enmascaran (roadmap: `all_frames:true` + control de superficie).
- **Cap de inspección**: toma la cola del último turno; un secreto al inicio de un prompt gigante puede quedar fuera (roadmap: subir cap / inspección por turnos).
- **Key-in-URL**: `?k=sk-basa-…` es **atajo de demo** (logueable); en prod la key entra por input seguro/SSO.
- **Body firmado**: si una web app firmara el body, la reescritura vía `window.fetch` se detectaría (hoy ChatGPT/Claude no firman).
- **`/gw/inspect` enmascara PII (regex)**: Presidio real (PHI español, CIE-10) llega en la **spec 016**; el shape del endpoint no cambia.

## Onboarding as data (Principio IV)

Sumar/quitar una superficie **soportada** es una `Connection`/`APIKey` (013) con su `tool_type` +
`upstream_mode` (config + seed), **0 código**. Las no soportadas se documentan acá.
