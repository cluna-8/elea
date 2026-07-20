# Spikes batch 1 — evidencia (2026-07-20)

**Spec**: 019 · **Issue**: #15 · **Origen**: reunión JF+Cristian 2026-07-20 (Ollama como
entorno controlado para clientes de infraestructura) + candidatos ya registrados.

Protocolo por spike (criterios de `compatibility.md` §T005): mecanismo de enganche →
ciclo completo observable (incl. política del motor) → veredicto FUNCIONA/PARCIAL/NO
con razón técnica → fila en la matriz. Evidencia = comandos y salidas reales, no teoría.

Entorno: stack dev basa-* (backend :8091, motor :4010, db :5433) + Ollama 0.32.1 en el
host (`:11434`), modelo `qwen3:4b` (soporta tool-calling).

---

## Spike 1 — Ollama como upstream del motor (byok → LiteLLM → Ollama)

**Hipótesis**: sumar un modelo propio/local es config, no código (Principio IV).

**Hallazgo previo**: el config del motor traía 2 entradas Ollama MUERTAS
(`ollama/gemma4:31b-cloud`, `ollama/qwen3.5:2b` — nombres inexistentes en la librería,
`api_base` a una IP de bridge que en macOS no llega al host). Estaban como fallback de
TODOS los modelos cloud → un failover habría 404eado. Saneado en este spike.

**Cambios (solo config, `litellm/config.yaml`)**:

- Entradas muertas → una real: `model_name: ollama-qwen3-4b`, `model: ollama_chat/qwen3:4b`
  (`ollama_chat/` usa `/api/chat` de Ollama = tool-calling; `ollama/` usa `/api/generate`),
  `api_base: http://host.docker.internal:11434` (host desde el contenedor en Docker Desktop).
- Fallbacks actualizados al nombre nuevo.

**Identidad**: Connection byok minteada por `seed_client` (013) — user `spike-ollama`,
`client_type: base_url` (CHECK del schema: `base_url|desktop|chat_ui`), tool `claude-code`,
key `sk-…kLBg` (en claro solo en el momento del seed, jamás en el repo).
`custom_auth` del motor valida sha256 contra la MISMA tabla `api_keys` → cero
provisioning extra en el motor.

**Evidencia** (2026-07-20, curl → `:8091/api/v1/gw/v1/messages` con la key del spike):

| # | Prueba | Resultado |
|---|---|---|
| 1 | Cadena completa no-streaming | ✅ HTTP 200 en 4.5s, respuesta formato Anthropic, `model: ollama-qwen3-4b` |
| 2 | Mask PII pre_call | ✅ El thinking del modelo reveló que recibió `[EMAIL_ADDRESS_0_…]` — **el modelo local jamás vio** `laura.perez@hospital.es` |
| 3 | Bloqueo de secretos | ✅ Prompt con `sk-proj…` → HTTP 400 del guardrail («material secreto detectado (OpenAI API Key)») |
| 4 | Fallback cloud→local | ✅ `gemini-2.5-flash-lite` sin key upstream → router sirvió `ollama-qwen3-4b` (resiliencia; ojo: el campo `model` conserva el nombre pedido) |
| 5 | **Unmask de respuesta (no-streaming)** | ❌ El texto final llegó al cliente con el placeholder (`[EMAIL_ADDRESS_0_…]`), no el valor original |
| 6 | **Unmask de respuesta (streaming)** | ❌ Ídem — el placeholder salió en los `text_delta` letra por letra |

**Root cause del unmask (instrumentación temporal del hook, luego revertida)**: en ambos
casos el hook SÍ corre y el mapping `pii_tokens` SÍ está presente — el problema es el *shape*:

- No-streaming: la respuesta de la ruta bridged llega como **`dict` plano**, y
  `_unmask_response_inplace` la lee con `getattr(response, "content")` → `None` → no-op silencioso.
- Streaming: el response es un generator de **objetos parseados** (no bytes SSE crudos como en
  el passthrough Anthropic) → caen en el escape «objeto ya parseado → se entrega tal cual».

Alcance: **toda ruta bridged** de `/v1/messages` (Ollama y presumiblemente gpt-4o/gemini),
no solo Ollama. Nota de honestidad: las keys cloud del stack dev están vacías → la evidencia
byok cloud de la matriz (2026-07-14/15) provino del stack demo; el round-trip unmask por el
motor no tenía assert e2e (el contract test cubre el round-trip DEL GATEWAY, passthrough).

Seguridad: el gap es **fail-safe** — la PII nunca llega al modelo y al cliente nunca vuelve
PII de terceros; el costo es UX (placeholders visibles cuando el modelo repite el dato).

**Veredicto**: **PARCIAL (config-only)** — ruteo, identidad, mask, secretos y fallback
funcionan sumando el modelo como config (Principio IV, 0 código); la limitación conocida es
el unmask de respuesta en rutas bridged. Promoción a FUNCIONA cuando aterrice la spec del
fix (`_unmask_response_inplace` con soporte dict + rewrite de chunks parseados, TDD).

---

## Spike 2 — Claude Code → gateway → modelo propio (¿aguanta Agent?)

**Mecanismo**: `ANTHROPIC_BASE_URL=http://localhost:8091/api/v1/gw` +
`ANTHROPIC_AUTH_TOKEN=sk-basa-…` (auto-byok detecta la virtual key en el header de auth
→ modo byok → `{motor}/v1/messages`, la API Anthropic-compat de LiteLLM) +
`ANTHROPIC_MODEL=ollama-qwen3-4b` (Claude Code manda ese nombre en el body y el motor
rutea por `model_name`).

**Pregunta clave**: tool-calling en modo Agent con modelo no-Claude (el gap que dejó a
Copilot/Cursor en PARCIAL).

**Evidencia** (2026-07-20, `claude` CLI real headless contra el stack dev):

| # | Prueba | Resultado |
|---|---|---|
| 1 | Chat simple (`¿7*6?`) | ✅ «42» — ciclo completo Claude Code → gateway byok → motor → qwen3:4b |
| 2 | **Agent con tool Read** (leer notas.txt y extraer un dato) | ✅ «8091» — el modelo emitió `tool_use`, Claude Code ejecutó Read y el resultado volvió por la cadena |
| 3 | **Loop agéntico multi-tool** (Write → Read → verificar) | ✅ «OK» y el archivo existe en disco con el contenido exacto |
| 4 | Feed de eventos del gateway | ✅ tráfico visible (`model: qwen3:4b`, compliance `passed`) · ❌ atribución `tool/client/tenant: null` en este camino (misma familia del gap de metadata bridged → al fix-spec) |

**RESPUESTA A LA PREGUNTA CLAVE: SÍ aguanta modo Agent.** El bridge Anthropic⇄OpenAI del
motor traduce `tool_use`/`tool_result` en ambas direcciones y qwen3 soporta tools nativas.
El gap que hundió a Copilot-Agent (modelos no-Claude rompen su tool-calling) NO aplica a
Claude Code sobre esta cadena.

**Gotchas de onboarding (documentar en la guía)**:

- Una sesión de `claude` ya logueada con suscripción **pisa el env** y valida el modelo
  contra la lista Anthropic («It may not exist…»). En máquina de cliente no pasa; en setups
  mixtos: `CLAUDE_CONFIG_DIR` aislado (verificado) o logout.
- Ollama necesita contexto amplio para el system prompt de Claude Code:
  `OLLAMA_CONTEXT_LENGTH=32768` (el default truncaría).
- Config del cliente: `ANTHROPIC_BASE_URL=<gateway>/api/v1/gw` +
  `ANTHROPIC_AUTH_TOKEN=sk-basa-…` + `ANTHROPIC_MODEL=<model_name del motor>`.

**Veredicto**: **FUNCIONA (mecanismo)** — con dos notas: la calidad agéntica depende del
modelo que el cliente aloje (un 4b resuelve tareas simples; la elección del modelo es del
cliente, no del mecanismo), y arrastra la limitación de unmask del Spike 1 hasta el fix.

---

## Spike 3 — Aider (byok por la superficie Anthropic del gateway)

**Mecanismo**: aider usa litellm como lib → con `ANTHROPIC_API_BASE=<gateway>/api/v1/gw` +
`ANTHROPIC_API_KEY=sk-basa-…` + `--model anthropic/<model_name>` postea al `/v1/messages`
del gateway. Cero config extra.

**Evidencia** (aider 0.86.2, headless `--message --yes`):

| # | Prueba | Resultado |
|---|---|---|
| 1 | Crear `aider_test.py` con `suma(a,b)` | ✅ archivo creado, «Applied edit», 604 sent/715 received por el gateway |
| 2 | **Diff-apply con PII en el prompt** (criterio de la matriz) | ✅ el diff-apply NO se rompe — pero el archivo hereda el placeholder (`EMAIL = '[EMAIL_ADDRESS_0_…]'`) por el gap de unmask del Spike 1 |

**Veredicto**: **PARCIAL** — se engancha de fábrica y el flujo editor completo funciona;
limitación conocida = unmask (placeholders llegan a archivos si el prompt lleva PII).
Promoción a FUNCIONA con el mismo fix-spec del Spike 1.

## Spike 4 — Codex CLI (protocolo OpenAI → motor directo)

**Hallazgo arquitectónico**: el gateway NO expone superficie OpenAI/Responses (solo
`/v1/messages` Anthropic-shape). Codex ≥0.142 **eliminó** `wire_api=chat` — solo habla
**Responses API**. Camino gobernado hoy: motor directo (`base_url=<motor>/v1`,
`wire_api=responses`, key `sk-basa-…` via `env_key`) — la política (custom_auth +
guardrail) vive en el motor, así que aplica igual; lo que se pierde es la puerta única
del gateway. Exponer superficie OpenAI/Responses en el gateway = gap para el roadmap.

**Evidencia** (codex-cli 0.142.5, `codex exec`):

| # | Prueba | Resultado |
|---|---|---|
| 1 | Chat (`¿7*6?`) via `/v1/responses` del motor | ✅ «42» (warning recuperable `OutputTextDelta without active item` del bridge) |
| 2 | Agéntico (`--full-auto`, crear archivo / usar shell) | ❌ el modelo razona el tool-call pero lo emite como TEXTO («I should output this in the tool_call XML tags») — la llamada nativa nunca se dispara por el bridge Responses→ollama; 2 intentos, 0 archivos |

Contraste clave: con el bridge Anthropic (Spike 2) el MISMO modelo emitió `tool_use`
nativo — el gap es de la ruta Responses del motor (bridge/tool-wiring), no del modelo.

**Veredicto**: **PARCIAL** — chat/Q&A gobernado funciona contra el motor; modo agéntico
NO por la ruta Responses bridged. Razones acotadas: (a) gateway sin superficie OpenAI,
(b) tools no nativas en el bridge Responses→ollama.

## Spike 5 — Cline / Continue (extensiones VS Code)

**PENDIENTE — requiere sesión GUI** (VS Code interactivo; no evidenciable headless con
el protocolo de este batch). Mecanismo identificado: base URL configurable en settings
(camino byok). Queda **EN SPIKE** en el registro para una sesión en vivo con JF.

---

## Síntesis del batch → trabajo derivado

1. **Fix-spec (código, SDD)**: unmask en rutas bridged del motor (dict + chunks parseados)
   + atribución `tool/client/tenant` nula en eventos byok bridged. Chica y bien acotada;
   promueve Ollama/Claude Code-modelo-propio/Aider de PARCIAL a FUNCIONA.
2. **Roadmap**: superficie OpenAI/Responses en el gateway (desbloquea Codex agéntico
   gobernado por la puerta única y a futuro cualquier tool OpenAI-only).
3. **Cobertura de secretos**: `SECRET_PATTERNS` no incluye AWS (`AKIA…`) ni otros formatos
   comunes — territorio Presidio/016 (módulo seguridad), avisar a Cristian.
4. **Docs**: guía de onboarding «modelo propio via Ollama» con los gotchas de contexto
   (`OLLAMA_CONTEXT_LENGTH`), login de suscripción y config por herramienta.
