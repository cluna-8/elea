# Research T004 (Phase 0) — Open questions de compatibilidad de clientes (019 Integration Surfaces)

**Fecha**: 2026-07-13 · **Método**: revisión de prior-art público (foros de producto, docs de
gateways/DLP, blogs técnicos de browser-DLP) cruzada con la evidencia del demo (`gatelite-salud-eu`
+ `basa-browser-dlp/`). Cinco preguntas abiertas que la spec dejaba pendientes de fundamentar. Cada
hallazgo trae **veredicto** y **fuentes**. Complementa los hechos ya verificados del demo (Ask vs
Agent en Copilot, body no firmado en ChatGPT/Claude, WebSocket vs `fetch`, gaps de iframe).

> ⚠️ Nota de alcance: estas respuestas fijan **estados de la matriz de compatibilidad** (US4) y el
> **posicionamiento** de las superficies roadmap (US5, Claude Desktop MCP). No son claims de código
> entregado en esta feature: lo que aquí se marca "viable/spike" queda como roadmap explícito.

## Resumen

- **Cursor NO es un "NO" — es PARCIAL.** Cursor tiene "Override OpenAI Base URL", pero **sólo** se honra
  en el panel chat/plan (Cmd+L); el agente (Composer), inline edit y autocomplete están clavados al
  backend de Cursor. Cae en la **misma casilla que Copilot**: gobernable sólo en el modo sin-tools.
- **Claude Desktop vía MCP = viable pero alcance TOOL-PLANE.** Un MCP server nunca ve el chat; sólo args
  de tool-calls y results. Da DLP sobre results, audit, elicitation, sampling — **no** masking del prompt
  del usuario ni de las respuestas de Claude (gap conocido).
- **Gemini web = viable, requiere spike.** Endpoint `StreamGenerate` (POST `batchexecute`,
  fetch-interceptable) con el prompt ofuscado en `f.req`; el prior-art hace **DOM-hook** (editor Quill).
- **Strip-tools = mecanismo, no estrategia.** Fuerza texto pero degrada el agente a chat, rompe UI y no
  frena tool-calls por system prompt. Preferible el modo Ask nativo.
- **Prior-art browser-DLP:** no hay un "LiteLLM del browser-DLP" OSS; el approach de Basa (extensión MV3
  + fetch/DOM hook + mask contra gateway + unmask por MutationObserver) es el **patrón dominante**; el
  moat es **des-enmascarar** (mantener UX) frente a los incumbentes que **bloquean** (rompen UX).

---

## (1) Cursor — ¿NO o PARCIAL? → **PARCIAL** (no "NO")

Cursor **sí** expone un "Override OpenAI Base URL" (Settings → Models), pero **sólo se honra en el panel
chat/plan** (Cmd+L). El **agente (Composer)**, el **inline edit** y el **autocomplete** están **clavados
al backend de Cursor** y **NO** rutean por el endpoint custom. El "Override Anthropic Base URL" se
**auto-activa** al fijar el override y **rompe con 422**; no existe un override Anthropic standalone
usable. Conclusión: Cursor cae en la **misma casilla que Copilot** — gobernable **sólo** en el modo
sin-tools (chat/plan), **no** el agente.

**Veredicto**: **PARCIAL** (antes NO). Estado de matriz: `PARCIAL — Override OpenAI Base URL, honrado
sólo en chat/plan (como Copilot Ask); agente/inline/autocomplete no ruteables; Override Anthropic → 422`.

**Fuentes**:
- https://forum.cursor.com/t/147219
- https://docs.llmgateway.io/guides/cursor
- https://forum.cursor.com/t/158805

## (2) Claude Desktop vía MCP — ¿gobernable? → **VIABLE, alcance TOOL-PLANE**

Un **MCP server nunca ve la conversación ni el prompt del usuario**; sólo ve los **args de las tool-calls**
y **devuelve results**. Por tanto ofrece:
- **DLP/redaction sobre los RESULTS de tools** (con Presidio),
- **audit** de las tool calls,
- **elicitation** (confirmaciones interactivas),
- **sampling** (clasificar sin gastar API key propia).

Lo que **NO** puede hacer: enmascarar lo que el usuario **teclea** ni las **respuestas de Claude**. El
masking del prompt del usuario en Claude Desktop es un **gap conocido no cubrible hoy** por esta vía.
Posicionamiento a fijar en la spec: **"MCP = gobernanza del tool-plane, no del chat-plane"**.

**Veredicto**: **MCP-ONLY / VIABLE (tool-plane)**. Prior-art fuerte que valida el patrón: Strac MCP DLP,
MCP Manager (usa Presidio), Nightfall MCP.

**Fuentes** (prior-art): Strac MCP DLP; MCP Manager (Presidio-based); Nightfall MCP.

## (3) Gemini web — ¿viable como adapter de la extensión? → **VIABLE, requiere SPIKE en vivo**

El endpoint es **`StreamGenerate`** (POST a **`batchexecute`**, **no** WebSocket → **fetch-interceptable**).
El prompt del usuario va **enterrado en el parámetro `f.req`** (JSON anidado, ofuscado, **no documentado**).
El prior-art de extensiones DLP intercepta vía **DOM** (editor **Quill**, selector `.ql-editor`), evitando
parsear `batchexecute`. **Recomendación**: prototipar el **DOM-hook primero** (menor riesgo) frente al
**fetch-hook** (más frágil por la ofuscación de `f.req`).

**Veredicto**: **NO hoy / roadmap VIABLE**; requiere un **spike** en vivo para validar el DOM-hook (host
en `manifest.matches` + adapter `{ id:"gemini", match, read, write }` en `guardia-main.js`).

**Fuentes**:
- https://anonym.legal/blog/browser-dlp-chatgpt-claude-gemini-2026

## (4) Strip tools en BYOK — ¿estrategia para gobernar el agente? → **MECANISMO, NO estrategia**

Quitar `tools` (o forzar `tool_choice:none`) **fuerza salida de texto**, pero:
- **degrada el agente a chat** (pierde la razón de ser del modo Agent),
- **puede romper la UI del cliente** (que espera `tool_calls` estructuradas),
- **no evita tool-calls alucinadas** si el cliente mete las tools en el **SYSTEM PROMPT**.

Mejor camino: usar el **modo Ask nativo** (ya resuelto en US2) que el hack de `tool_choice:none`.

**Veredicto**: válido como mecanismo puntual, **no** como estrategia; **strip-tools no habilita gobernar
el agente** no-Claude. Ratifica Copilot/Cursor = PARCIAL (sólo modo sin-tools).

**Fuentes**:
- https://answer.ai/posts/2026-01-20-toolcalling.html
- https://docs.litellm.ai/docs/completion/drop_params

## (5) Prior-art browser-DLP — ¿hay un estándar/OSS que copiar? → **NO hay "LiteLLM del browser-DLP"; el patrón de Basa es el dominante**

No existe un OSS "LiteLLM del browser-DLP". El approach de Basa — **extensión MV3 + fetch/DOM hook + mask
contra el gateway + unmask por MutationObserver** — es el **patrón dominante**. `anonym.legal` replica
casi idéntico: **tokens reversibles + unmask client-side + selectores per-plataforma**. **Moat** frente a
Nightfall / Microsoft Purview / Zscaler: esos productos **BLOQUEAN** (rompen la UX); Basa **DES-ENMASCARA**
(mantiene la UX). Recomendación de diseño: tratar la **lógica per-plataforma como ADAPTERS versionados**
(igual que `chatgpt`/`claude`, con Gemini como el próximo adapter).

**Veredicto**: el patrón de Basa está **validado por prior-art convergente**; el diferencial es
des-enmascarar (no bloquear) y versionar los adapters per-plataforma.

**Fuentes**:
- https://anonym.legal/blog/browser-dlp-chatgpt-claude-gemini-2026

---

## Impacto en spec/plan/tasks

- **Matriz (US4, FR-020/021)**: **Cursor** pasa de **NO** a **PARCIAL** (misma casilla que Copilot Ask);
  **Claude Desktop** = MCP-ONLY con nota de **tool-plane only**; **Gemini** = NO/roadmap **viable** (spike
  DOM-hook).
- **US2 / Edge cases**: se añade la nota de que **strip-tools no habilita gobernar el agente** (se prefiere
  el modo Ask/chat-plan nativo).
- **US5**: Gemini documentado como **viable vía DOM-hook** (Quill `.ql-editor`) con el endpoint
  `StreamGenerate`/`batchexecute` fetch-interceptable pero `f.req` ofuscado — spike requerido.
- **Posicionamiento**: los adapters per-plataforma se tratan como **artefactos versionados**; el moat es
  des-enmascarar (mantener UX) vs bloquear.
