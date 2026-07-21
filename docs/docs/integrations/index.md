# Integraciones & matriz de compatibilidad

Guía práctica para el distribuidor y el operador: qué clientes de IA se pueden gobernar con el
firewall del gateway, cómo se configura cada superficie y dónde están los límites verificados de
cada integración. Los gotchas con su causa y su fix viven en [Gotchas verificados](gotchas.md).

**Para quién**: el integrador que conecta herramientas de IA al gateway, y el soporte del
distribuidor / operador que atiende tickets de estas superficies.

!!! note "Base de los ejemplos"
    Los ejemplos usan la base `http://localhost:8091/api/v1/gw` (entorno local de desarrollo); en
    producción es `https://<host>/api/v1/gw` (el host del gateway desplegado por el operador, con
    el **mismo path `/api/v1/gw`**).

---

## 1. Topología de superficies

**Tres superficies, un producto:**

1. **`base_url`** — herramientas de coding que permiten apuntar su endpoint de API al gateway
   (Claude Code — por suscripción o con modelo propio —, Aider, GitHub Copilot, Cursor).
2. **`browser`** — aplicaciones de chat web (ChatGPT, Claude.ai) gobernadas por la extensión de
   navegador del producto.
3. **`mcp`** — plano de tools: la DLP se aplica sobre los resultados de las tools MCP (cobertura
   limitada, ver la fila de Claude Desktop en la matriz).

Las dos superficies principales (`base_url` y `browser`) empujan al **mismo** monitor en vivo
(`GET /api/v1/gw/monitor`) con un tag `surface`. *"Un empleado, N herramientas, un firewall."*

```mermaid
graph LR
    subgraph S1 [Superficie 1 - base_url]
        CC[Claude Code suscripcion]
        CM[Claude Code modelo propio]
        AI[Aider]
        CP[Copilot modo Ask]
        CU[Cursor chat y plan]
    end
    subgraph S2 [Superficie 2 - browser]
        CH[ChatGPT web]
        CL[Claude web]
    end
    EXT[Extension de navegador]
    subgraph GWY [Gateway /api/v1/gw]
        MSG[POST /v1/messages]
        INS[POST /inspect]
        MON[GET /monitor]
    end
    LLM[Proveedor LLM cloud]
    MOT[Motor del gateway]
    OLL[Modelo propio - runtime Ollama]
    VEN[Backend del asistente web]

    CC -->|prompt| MSG
    CM -->|prompt byok| MSG
    AI -->|prompt byok| MSG
    CP -->|prompt con key en la URL| MSG
    CU -->|override de base URL| MSG
    CH -->|hook de fetch| EXT
    CL -->|hook de fetch| EXT
    EXT -->|texto plano| INS
    INS -->|masked y replacements| EXT
    EXT -->|body enmascarado| VEN
    MSG -->|passthrough enmascarado| LLM
    MSG -->|byok enmascarado| MOT
    MOT --> OLL
    LLM -->|respuesta con placeholders| MSG
    MOT -->|respuesta con placeholders| MSG
    MSG -->|unmask sobre la respuesta| S1
    EXT -->|unmask en el DOM| S2
    MSG --> MON
    INS --> MON
```

Los dos caminos de ida — y el camino de vuelta del unmask, que es distinto por superficie:

- **Ida `base_url`**: la herramienta manda el prompt directamente a
  `POST /api/v1/gw/v1/messages`; el gateway enmascara lo detectado y reenvía al proveedor LLM
  (por passthrough de suscripción o `byok` al motor del gateway, según el modo).
- **Ida `browser`**: la extensión intercepta el `fetch` de la página **antes** de que el prompt
  salga, manda el texto plano a `POST /api/v1/gw/inspect`, recibe el texto enmascarado y los
  `replacements` (token → original), y reescribe el body — el backend del asistente web solo
  recibe placeholders.
- **Vuelta (unmask)**: en `base_url` la restauración de los valores reales cubre **ambos
  modos** — passthrough de suscripción (la aplica el gateway) y `byok` con cualquier modelo
  del motor, incluidos los puenteados (la aplica el motor; el histórico [G9](gotchas.md)
  quedó corregido) — en streaming y no-streaming. En `browser` el mapa token → original
  queda **en la extensión** y el unmask se aplica **en el DOM** con un `MutationObserver` —
  porque en ChatGPT la respuesta no llega en el body del POST sino por WebSocket (ver
  [G4](gotchas.md)).

Endpoints auxiliares de la superficie `base_url`: `GET /api/v1/gw` responde el **discovery**
(uso y endpoints disponibles), y `POST /api/v1/gw/v1/messages/count_tokens` +
`GET /api/v1/gw/v1/models` dan **paridad de rutas** con el API nativo mediante reenvío verbatim
(estas dos rutas auxiliares no enmascaran: el conteo de tokens necesita el texto real y el
destino es el propio upstream de la sesión).

---

## 2. Tabla de compatibilidad

Estados (leyenda del sitio): 🟢 funciona hoy, verificado · 🟡 parcial · ⚪ fuera de las dos
superficies principales.

| Cliente | Estado | Superficie | Mecanismo | Gotcha clave |
|---|---|---|---|---|
| **Claude Code** | 🟢 Funciona | `base_url` | `ANTHROPIC_BASE_URL` → `/api/v1/gw/v1/messages`. Passthrough de **suscripción** (OAuth reenviado verbatim por el gateway) **o** `byok` al motor del gateway. | Hay que **reiniciar `claude`** para tomar `ANTHROPIC_CUSTOM_HEADERS`. Para trabajo agéntico: suscripción, o **modelo propio** (§3.5 — el modo Agent está verificado por esa vía; el límite de G1 es del loop agéntico de Copilot). |
| **Claude Code → modelo propio** | 🟢 Funciona | `base_url` | `byok` + el modelo del cliente servido por su runtime local (p. ej. **Ollama**) registrado en el motor del gateway — ver §3.5. | **El modo Agent funciona** (verificado con tools reales) y el ciclo mask→restauración completa ([G9](gotchas.md): corregido). Con el cache del motor activo, repetir un prompt idéntico puede devolver placeholders de una respuesta cacheada (limitación conocida en evaluación). |
| **Aider** | 🟢 Funciona | `base_url` | `ANTHROPIC_API_BASE` → `…/api/v1/gw` + `ANTHROPIC_API_KEY=sk-basa-…` + `--model anthropic/<modelo-del-motor>`. Cero config extra. | El flujo editor completo (diff-apply) funciona, **no** se corrompe con el masking y los archivos quedan con los valores reales ([G9](gotchas.md): corregido). Misma nota de cache del motor que Claude Code → modelo propio. |
| **Codex CLI** | 🔵 Objetivo (roadmap) | — | Codex ≥0.142 solo habla la Responses API (OpenAI) y el gateway **no expone esa superficie hoy** — no hay camino gobernado que ofrecer en una instalación estándar. | **No se ofrece hoy.** El camino identificado (roadmap) es exponer una superficie OpenAI/Responses gobernada en el propio gateway; hasta entonces, no conectar Codex por rutas internas del despliegue: quedan **fuera** de la política y la auditoría del firewall. |
| **VS Code / GitHub Copilot** | 🟡 Parcial — **solo modo Ask** | `base_url` | `chatLanguageModels.json` con `apiType:"messages"` → `byok` al motor del gateway. Auto-byok por virtual key. | En **Agent/Edit** entra en loop (los modelos no-Claude llaman mal las tools). La key va **en la URL** (`?k=…`) porque manda `x-api-key` vacío. |
| **ChatGPT (web)** | 🟢 Funciona | `browser` | Extensión de navegador: hookea `fetch` sobre `POST /backend-api/f/conversation`, enmascara `messages[].content.parts[]` vía `/api/v1/gw/inspect`. | La respuesta **no** viene en el POST: llega por **WebSocket** (`stream_handoff`) → el unmask se hace en el **DOM**, no sobre la respuesta. |
| **Claude (web, claude.ai)** | 🟢 Funciona | `browser` | Extensión de navegador: hookea `fetch` sobre `.../completion` **y** `.../title`, enmascara `body.prompt` / `body.message_content`. | **Fuga de título**: el endpoint `/title` manda el prompt crudo → hay que enmascararlo también. **Artefactos** en `iframe` → el unmask del DOM no llega. |
| **Gemini (web)** | 🔵 Objetivo (roadmap) | `browser` | **DOM-hook** sobre el editor **Quill** (`.ql-editor`) en `gemini.google.com`: enmascarar el texto del prompt en el editor antes del envío (no vía `fetch`). | **Aún sin verificar — no se ofrece todavía.** A diferencia de ChatGPT/Claude no se mapea endpoint/stream: el approach definido es hookear el editor Quill, no interceptar el POST. Los `content_scripts` del manifest deben matchear `gemini.google.com`. |
| **Cursor** | 🟡 Parcial — **solo chat/plan** | `base_url` | **Override OpenAI Base URL** (settings de Cursor) → apunta el endpoint OpenAI-compatible del modelo al gateway. Gobierna el **chat** y el **modo plan**. | El **agente Composer** y el **autocomplete** **no** pasan por el override (enrutan por el backend propio de Cursor) → quedan fuera del firewall. **Misma casilla que Copilot en modo Ask** (ver §3.4 y [G1](gotchas.md)). |
| **Claude Desktop** | ⚪ MCP tool-plane only | `mcp` | No expone override de `base_url`; la gobernanza entra por **MCP**: la DLP se aplica sobre los **results de las tools** MCP, **no** sobre el prompt del chat. | El prompt del usuario al modelo **no** es interceptable (fuera del reverse-proxy); sólo se gobierna el **plano de tools**. Fuera del scope de las dos superficies principales. |

**Cómo se detecta la herramienta.** El gateway mapea el `User-Agent` a un nombre amigable
(`claude` → Claude Code, `copilot` → GitHub Copilot, `vscode` → VS Code, `cursor` → Cursor,
`gemini` → Gemini CLI, `curl`/`httpx`/`python-requests` → API directa…). Un UA no reconocido cae a
**"Desconocido"** y **no** crashea: se audita con esa etiqueta.

---

## 3. Cómo configurar cada superficie

### 3.1 Claude Code (`base_url`, superficie 1)

Modo recomendado: **suscripción** (la calidad de los modelos Claude reales + la gobernanza del
gateway). Aislar el `ANTHROPIC_BASE_URL` **al proyecto** con un `.claude/settings.json` (no toca
el Claude global):

```jsonc
// ~/mi-proyecto/.claude/settings.json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:8091/api/v1/gw",
    "ANTHROPIC_CUSTOM_HEADERS": "X-Basa-Key: sk-basa-<usuario>-<herramienta>-<año>"
  }
}
```

- `ANTHROPIC_BASE_URL` → apunta a `…/api/v1/gw` (Claude Code le agrega `/v1/messages`; las rutas
  auxiliares `…/v1/messages/count_tokens` y `…/v1/models` también existen en el gateway, así que
  la paridad de rutas se mantiene).
- `ANTHROPIC_CUSTOM_HEADERS` → `X-Basa-Key: sk-basa-…` da **atribución de identidad**
  (usuario/equipo). Sin ella, el evento se atribuye al identity por defecto.
- La suscripción OAuth del cliente viaja en `Authorization` y **atraviesa verbatim** — `X-Basa-Key`
  está **excluido** del auto-byok, así que la key de atribución NO desvía a Claude Code al motor
  (el porqué de esa exclusión, en [G8](gotchas.md)).
- **Reiniciá `claude`** después de tocar el archivo (los headers se leen al arrancar).

Forzar modo `byok` (consumir modelos gobernados del motor del gateway) por request:

```bash
# header por request; o BASA_GW_UPSTREAM_DEFAULT=byok en el entorno del gateway
curl -s http://localhost:8091/api/v1/gw/v1/messages \
  -H "content-type: application/json" \
  -H "X-Basa-Key: sk-basa-<usuario>-<herramienta>-<año>" \
  -H "X-Basa-Upstream: byok" \
  -d '{"model":"gpt-4o-mini","max_tokens":256,"messages":[{"role":"user","content":"hola"}]}'
```

Verificar identidad:

```bash
curl -s http://localhost:8091/api/v1/gw/whoami \
  -H "X-Basa-Key: sk-basa-<usuario>-<herramienta>-<año>"
# → {"ok":true,"user":"<usuario>","team":"<equipo>","key_label":"…"}
```

### 3.2 VS Code / GitHub Copilot (`base_url`, **modo Ask**)

`Chat: Manage Language Models` → **Custom** → `apiType` = **`messages`**. Copilot manda `x-api-key`
**vacío** e **ignora** el `apiKey` del config, así que la virtual key se mete **en la URL**
(`?k=…`). El archivo vive en `~/Library/Application Support/Code/User/chatLanguageModels.json`:

```jsonc
// chatLanguageModels.json
[
  {
    "apiType": "messages",
    "url": "http://localhost:8091/api/v1/gw/v1/messages?k=sk-basa-<usuario>-<herramienta>-<año>",
    "id": "gpt-4o-mini"
  }
]
```

- **Usar modo Ask**, no Agent/Edit (ver [G1](gotchas.md)).
- El gateway lee la key de la URL como fallback → auto-byok + atribución. La key en la URL es un
  **atajo para entornos de prueba**; en producción va por input seguro/SSO.
- Los modelos disponibles son los `model_name` que el operador tenga configurados en el
  motor (con sus credenciales BYOK); la lista viva se consulta en
  `GET /api/v1/gw/v1/models` con la virtual key.

### 3.3 Browser — ChatGPT / Claude web (superficie 2, extensión de navegador)

1. **Instalar la extensión (descomprimida):** `brave://extensions` o `chrome://extensions` →
   activar **Modo desarrollador** → **Cargar descomprimida** → la carpeta de la extensión provista
   con el producto. Para actualizar el código, botón **↻** sobre la tarjeta de la extensión.
2. **Conectar (login):** click en el ícono 🛡️ → pegar la key (p. ej.
   `sk-basa-<usuario>-<herramienta>-<año>`) y el gateway (`http://localhost:8091/api/v1/gw`) →
   **Conectar**. El popup valida contra `GET /api/v1/gw/whoami` y muestra
   "🟢 Conectado como `<usuario>` · `<equipo>`".
3. **Toggle** de protección en el popup (por defecto ON).

El ciclo completo de un prompt (mask a la ida, unmask a la vuelta):

```mermaid
sequenceDiagram
    participant P as Pagina del asistente
    participant CS as Content script
    participant SW as Service worker
    participant GW as Gateway
    participant V as Backend del asistente

    P->>CS: fetch interceptado con el prompt crudo
    CS->>SW: texto plano del prompt
    SW->>GW: POST /api/v1/gw/inspect con X-Basa-Key
    GW-->>SW: masked mas replacements token-original
    SW-->>CS: texto enmascarado y mapa local
    CS->>V: body reescrito - solo salen placeholders
    V-->>P: respuesta por stream o WebSocket
    CS->>P: unmask en el DOM via MutationObserver
```

El contrato de `POST /api/v1/gw/inspect` (verificado en el producto):

- Request: `{"text": "<texto plano>", "tool": "<nombre opcional>"}` + header `X-Basa-Key`.
- Respuesta: `masked` (el texto enmascarado **completo** — el enmascaramiento no se trunca; el
  cap corto aplica solo al preview del monitor), `replacements` (pares token → original con los
  que la extensión reescribe el body y des-enmascara el DOM) y `entities` (conteo agregado por
  tipo, sin contenido).
- **Fail-closed**: sin key válida responde **401** — no enmascara ni audita a medias.
- Un `text` no-string (número, lista) se trata como vacío y responde `200` con `replacements`
  vacíos, en vez de un error 500.
- Cada llamada empuja al monitor con `surface="browser"` y audita **metadata-only**; el preview
  del monitor viaja siempre enmascarado y con secretos scrubbeados.

Notas de arquitectura útiles para soporte:

- La key vive en `chrome.storage.local` y **solo el service worker** de la extensión habla con el
  gateway (`host_permissions` → sin CORS); el content script no maneja la key en ningún flujo.
- **Fail-closed:** sin key válida, un overlay **bloquea** la página (no hay key → no se usa la IA).
  Si el gateway se cae estando conectado, también bloquea.
- `host_permissions` del manifest = `http://localhost:8091/*`. **Si cambia el host del gateway hay
  que editar el `manifest.json`** (`host_permissions` y, en producción, `chrome.storage.managed`
  vía MDM).

### 3.4 Cursor (`base_url`, **solo chat/plan**)

Cursor se gobierna **parcialmente** vía **Override OpenAI Base URL** (en los settings de Cursor):
se apunta el endpoint OpenAI-compatible del modelo al gateway y el **chat** y el **modo plan**
pasan por el firewall (masking/bloqueo + monitor). Es la **misma casilla** que Copilot en modo
Ask (§3.2).

!!! warning "Cobertura parcial"
    El **agente Composer** y el **autocomplete** **no** honran el override — enrutan por el
    backend propio de Cursor y quedan **fuera** del firewall (igual que Agent/Edit en Copilot,
    [G1](gotchas.md)). La gobernanza alcanza la ruta de chat/plan, no la agéntica. Presentarlo
    siempre como "Cursor chat/plan gobernado, Composer/autocomplete no", **nunca** como cobertura
    total.

### 3.5 Modelo propio / local — entorno controlado (runtime Ollama)

Para **clientes de infraestructura** (alto riesgo): el tráfico de IA no sale a ningún proveedor
cloud — el cliente aloja su propio modelo (p. ej. con **Ollama**) y el gateway lo gobierna con la
misma política (masking, secretos, AI-Act) que un modelo cloud, con el tráfico **atribuido** en
el monitor (herramienta, cliente y tenant por Connection). Para perfiles de oficina, el camino
recomendado sigue siendo el passthrough de suscripción (§3.1).

```mermaid
graph LR
    CC[Claude Code del cliente] -->|sk-basa auto-byok| GW[Gateway /api/v1/gw]
    GW -->|politica: mask, secretos, AI-Act| MOT[Motor del gateway]
    MOT -->|bridge de tools nativo| OLL[Runtime local Ollama]
    OLL --> MOD[(Modelo propio)]
    MOT --> MON[Monitor y auditoria]
```

**Alta del modelo (operador)** — es **configuración del motor, no código**: se registra el
modelo local con su `api_base` (el runtime del cliente: una dirección **alcanzable desde el
motor** en el despliegue real; en el stack de desarrollo local es el host de la máquina) y un
`model_name` que las herramientas usarán como identificador. Costo por token 0 (el modelo es
del cliente).

**Configuración de la herramienta (ejemplo Claude Code)**:

```bash
export ANTHROPIC_BASE_URL="https://<host>/api/v1/gw"
export ANTHROPIC_AUTH_TOKEN="sk-basa-<usuario>-<herramienta>-<año>"   # auto-byok
export ANTHROPIC_MODEL="<model_name-del-motor>"
```

**Verificado en vivo** (2026-07-20): chat, tool-calling y el **loop agéntico completo**
(leer/escribir archivos y verificar) funcionan con un modelo local — el motor traduce las
llamadas de tools en ambas direcciones, así que el modo Agent de Claude Code **sí** aguanta
modelos no-Claude por esta vía. La calidad del resultado depende del modelo que aloje el
cliente (un modelo chico resuelve tareas simples; la elección es del cliente).

Gotchas de onboarding:

- El runtime necesita **contexto amplio** para los prompts de sistema de las coding tools:
  con Ollama, `OLLAMA_CONTEXT_LENGTH=32768` (el default los truncaría en silencio).
- Si la máquina ya tiene una sesión de `claude` logueada con suscripción, esa sesión **pisa
  las variables de entorno** — ver [G10](gotchas.md).
- Si un modelo cloud del motor se queda sin credenciales, el **fallback** configurado puede
  servir la petición con el modelo local. ⚠ La sustitución es **silenciosa** (el campo
  `model` de la respuesta conserva el nombre pedido): si la instalación exige trazabilidad
  estricta del modelo que respondió, el operador debe deshabilitar ese fallback en el motor.
- La restauración de PII sobre las respuestas está **verificada** en este camino, en
  streaming y no-streaming ([G9](gotchas.md): corregido). Limitación conocida en evaluación:
  con el **cache del motor** activado, repetir un prompt crudo idéntico dentro de la ventana
  de cache puede devolver una respuesta cacheada con placeholders — desactivar el cache del
  motor la elimina.

---

## 4. Límites verificados por superficie

Leyenda del sitio: 🟢 **HOY** (funciona y está verificado) · 🟡 **PARCIAL** (existe con límites
documentados) · 🔵 **OBJETIVO** (roadmap explícito, no implementado).

- 🟢 **Claude Code por passthrough de suscripción** — cubre también el flujo agéntico
  (tool-calling) porque el upstream son los modelos Claude reales.
- 🟢 **Claude Code con modelo propio (byok)** — el modo Agent **funciona** (verificado en
  vivo: el motor traduce las tools en ambas direcciones, §3.5) y la restauración de PII en
  las respuestas está verificada ([G9](gotchas.md): corregido). El "byok rompe el agéntico"
  aplica al loop de **Copilot** ([G1](gotchas.md)), no a Claude Code. La calidad agéntica
  depende del modelo que aloje el cliente.
- 🟢 **Aider** — flujo editor completo gobernado, con los valores reales en los archivos
  (aplica la misma nota del cache del motor que el resto del camino byok).
- 🔵 **Codex CLI** — sin camino gobernado hoy: el gateway no expone la superficie
  OpenAI/Responses que Codex necesita. Roadmap; no conectar por rutas internas del
  despliegue (quedan fuera de la política del firewall).
- 🟡 **Copilot: solo modo Ask** — Agent/Edit loopea con modelos no-Claude
  ([G1](gotchas.md)); la key viaja en la URL como atajo de prueba ([G2](gotchas.md)).
- 🟡 **Cursor: solo chat/plan** — Composer y autocomplete no honran el override y quedan fuera
  del firewall (§3.4).
- 🟢 **ChatGPT / Claude web con la extensión** — mask antes de salir, unmask en el DOM; incluye
  el endpoint de título de Claude.ai ([G3](gotchas.md)). Límite conocido: los artefactos de
  Claude renderizan en un `iframe` y el unmask del DOM no entra ([G5](gotchas.md)); el unmask
  dentro de iframes/artefactos es 🔵 roadmap.
- 🔵 **Gemini web** — roadmap con approach definido (DOM-hook sobre el editor), **aún sin
  verificar** — no se ofrece todavía.
- 🟡 **Plano MCP** — la DLP cubre los resultados de las tools; el prompt de chat de un cliente
  desktop sin override de `base_url` no es interceptable.
- 🟡 **Cobertura de detección** — lo **detectado** se enmascara siempre; la cobertura depende del
  modo: patrones por default (pilotos, entornos sin PHI real) o **motor NLP**, precondición de
  producción con PHI. Ningún detector garantiza un recall del 100 %.
- **Riesgo estructural de la superficie `browser`** — el masking depende de que el vendor no
  firme el body del request ([G6](gotchas.md)); si eso cambia, el adapter de esa superficie debe
  replantearse.

## Relacionado

- [Gotchas verificados](gotchas.md) — los límites G1–G10 de estas superficies con su síntoma,
  causa y fix verificados en vivo.
- [Operaciones & troubleshooting](../operations/index.md) — la tabla exprés síntoma → causa → fix
  para tickets y los endpoints de apoyo del gateway.
- [Administración](../administration/index.md) — cómo se crean las personas, Connections y
  virtual keys que estas superficies consumen.
- [Overview & arquitectura](../overview/index.md) — el pipeline de cinco capas que atraviesa cada
  request, sea cual sea la superficie de entrada.
