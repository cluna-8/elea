# Matriz de compatibilidad — Basa Guardian (superficies de cliente)

**Spec**: 019 · **Estado**: viva (se actualiza al sumar/validar superficies) · **Última**: 2026-07-20

Este documento es **el registro oficial de superficies cliente** (decisión JF 2026-07-20): toda
herramienta candidata a hablar con el gateway vive acá con su estado de ciclo de vida — se añade,
se pospone o se cancela ACÁ, nunca en un canal lateral. La matriz de abajo guarda la evidencia
técnica de las evaluadas; el sitio de docs (`docs/docs/integrations/`) publica el subconjunto
soportado (DoD de AGENTS.md).

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
| **Ollama (upstream de modelos propios)** | upstream | **FUNCIONA** | Config del motor: `ollama_chat/<modelo>` + `api_base` → 0 código (Principio IV) | Ruteo, identidad, mask pre_call, secretos, fallback y **round-trip unmask completo** verificados en vivo (spec 024, e2e `test_engine_roundtrip_e2e.py`). Nota acotada: cache del motor + prompts crudos idénticos puede servir placeholders ajenos (issue #30, decisión pendiente). |
| **Claude Code → modelo propio** | base_url (byok) | **FUNCIONA** | `ANTHROPIC_BASE_URL` → gateway + `ANTHROPIC_AUTH_TOKEN=sk-basa-…` (auto-byok) + `ANTHROPIC_MODEL=<model_name>` | **Aguanta modo Agent con modelo no-Claude** (Read/Write/loop verificados vivo — el bridge traduce `tool_use` nativo) y el round-trip mask→unmask cierra (024). Gotchas: `OLLAMA_CONTEXT_LENGTH=32768`, login suscripción pisa env, cache #30. |
| **Aider** | base_url (byok) | **FUNCIONA** | `ANTHROPIC_API_BASE` → gateway + `--model anthropic/<model_name>` (usa litellm como lib) | Flujo editor completo OK; diff-apply intacto con mask y archivos con los **valores reales** tras la 024 (antes heredaban placeholders). |
| **Codex CLI** | — (sin superficie hoy) | **NO (roadmap, viable)** | Único endpoint que le responde: motor directo `/v1/responses` (codex ≥0.142 solo habla Responses) — y esa ruta corre **SIN política** (verificado: PII en claro, secretos sin bloquear; el call_type no está en `_TEXT_CALL_TYPES`), sin puerto en prod, y evadiría licencias 021 + atribución | NO ofrecer. Camino identificado: **issue #28** — superficie OpenAI/Responses EN el gateway (licencias+política+atribución) + cobertura del call_type en el guardrail. Agéntico además no dispara tools nativas por ese bridge. Evidencia: [spikes-batch1.md](spikes-batch1.md) Spike 4. |

## Registro de superficies — ciclo de vida (fuente oficial)

Estados del registro (ortogonales al veredicto técnico de la matriz):

- **EN MATRIZ** — evaluada con evidencia; el veredicto (FUNCIONA/PARCIAL/NO/MCP-ONLY) vive arriba.
- **EN SPIKE** — research en curso (issue #15); sin promesa de compatibilidad hasta tener evidencia.
- **PLANIFICADA** — aprobada para un batch futuro; aún sin trabajo activo.
- **POSPUESTA** — decisión consciente de NO evaluarla ahora; lleva razón y condición de reapertura.
- **CANCELADA** — descartada; lleva razón técnica o de producto.

| Herramienta | Estado | Desde | Decisión / razón |
|---|---|---|---|
| Claude Code (suscripción) | EN MATRIZ | 2026-07-14 | FUNCIONA — superficie titular (passthrough) |
| ChatGPT web / Claude web | EN MATRIZ | 2026-07-14 | FUNCIONA — extensión MV3 |
| VS Code / GitHub Copilot | EN MATRIZ | 2026-07-14 | PARCIAL — solo Ask |
| Cursor | EN MATRIZ | 2026-07-15 | PARCIAL — solo chat/plan |
| Claude Desktop | EN MATRIZ | 2026-07-14 | MCP-ONLY — tool-plane |
| **Ollama como upstream** (modelos propios/locales) | EN MATRIZ | 2026-07-20 | FUNCIONA — spike batch 1 + spec 024 (#27 cierra con su PR); origen: reunión JF+Cristian 2026-07-20 (clientes infra = modelos propios en entorno controlado); nota cache #30 |
| **Claude Code → modelo propio** (byok→motor→Ollama) | EN MATRIZ | 2026-07-20 | FUNCIONA — **aguanta Agent** + round-trip completo (spec 024) |
| Aider | EN MATRIZ | 2026-07-20 | FUNCIONA — diff-apply con valores reales (spec 024) |
| Codex CLI | EN MATRIZ | 2026-07-20 | NO (roadmap, viable — issue #28): ruta Responses del motor sin política (verificado) + sin superficie en gateway ni endpoint en prod |
| Cline / Continue | EN SPIKE · batch 1 | 2026-07-20 | Pendiente sesión GUI con JF (extensiones VS Code, no evidenciable headless) |
| Zed | PLANIFICADA · batch 2 | 2026-07-20 | Anuncia base URL OpenAI-compat; barato de probar tras batch 1 |
| Gemini CLI | PLANIFICADA · batch 2 | 2026-07-20 | Confirmar si siquiera expone base URL |
| OpenCode | PLANIFICADA · batch 2 | 2026-07-20 | Integración oficial de Ollama (descubierta en research 2026-07-20) → candidata natural al mismo camino byok |
| Gemini web | EN MATRIZ | 2026-07-14 | NO (roadmap, viable) — con veredicto en la matriz; 2 gaps identificados (ver "Gemini — roadmap" abajo) |
| Windsurf / JetBrains AI | POSPUESTA | 2026-07-20 | Decisión JF: fortalecer la base y testear la v1 con clientes reales antes de ampliar; además requieren cuenta/licencia. **Reapertura**: tras feedback de clientes de la v1 |
| ChatGPT Desktop (app nativa) | POSPUESTA | 2026-07-14 | Sin camino técnico hoy: app nativa sin base_url ni hook interceptable (cert-pinning, mismo gap que el chat-plane de Claude Desktop). **Reapertura**: si aparece mecanismo de override |

> Promover una superficie = correr su spike y moverla a **EN MATRIZ** con evidencia (FUNCIONA /
> PARCIAL / NO con razón técnica). Mientras tanto NO se promete compatibilidad.

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
