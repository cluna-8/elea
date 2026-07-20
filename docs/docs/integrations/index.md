# Integraciones & matriz de compatibilidad

Guía práctica para el distribuidor y el operador: qué clientes de IA se pueden gobernar con el
firewall del gateway, cómo se configura cada superficie y dónde están los límites verificados de
cada integración. Los gotchas con su causa y su fix viven en [Gotchas verificados](gotchas.md).

**Tres superficies, un producto:**

1. **`base_url`** — herramientas de coding que permiten apuntar su endpoint de API al gateway
   (Claude Code, GitHub Copilot, Cursor).
2. **`browser`** — aplicaciones de chat web (ChatGPT, Claude.ai) gobernadas por la extensión de
   navegador del producto.
3. **`mcp`** — plano de tools: la DLP se aplica sobre los resultados de las tools MCP (cobertura
   limitada, ver la fila de Claude Desktop en la matriz).

Las dos superficies principales (`base_url` y `browser`) empujan al **mismo** monitor en vivo
(`GET /gw/monitor`) con un tag `surface`. *"Un empleado, N herramientas, un firewall."*

!!! note "Base de los ejemplos"
    Los ejemplos usan la base `http://localhost:8081/gw` (entorno local de prueba); en producción
    es el host del gateway desplegado por el operador, con el **mismo path `/gw`**.

---

## 1. Tabla de compatibilidad

Estados: ✅ funciona hoy · 🟡 parcial · ⚪ fuera de las dos superficies principales.

| Cliente | Estado | Superficie | Mecanismo | Gotcha clave |
|---|---|---|---|---|
| **Claude Code** | ✅ Funciona | `base_url` | `ANTHROPIC_BASE_URL` → `/gw/v1/messages`. Passthrough de **suscripción** (OAuth reenviado verbatim por el gateway) **o** `byok` al motor del gateway. | Hay que **reiniciar `claude`** para tomar `ANTHROPIC_CUSTOM_HEADERS`. En `byok` los modelos no-Claude rompen el tool-calling agéntico → usar suscripción. |
| **VS Code / GitHub Copilot** | 🟡 Parcial — **solo modo Ask** | `base_url` | `chatLanguageModels.json` con `apiType:"messages"` → `byok` al motor del gateway. Auto-byok por virtual key. | En **Agent/Edit** entra en loop (los modelos no-Claude llaman mal las tools). La key va **en la URL** (`?k=…`) porque manda `x-api-key` vacío. |
| **ChatGPT (web)** | ✅ Funciona | `browser` | Extensión de navegador: hookea `fetch` sobre `POST /backend-api/f/conversation`, enmascara `messages[].content.parts[]` vía `/gw/inspect`. | La respuesta **no** viene en el POST: llega por **WebSocket** (`stream_handoff`) → el unmask se hace en el **DOM**, no sobre la respuesta. |
| **Claude (web, claude.ai)** | ✅ Funciona | `browser` | Extensión de navegador: hookea `fetch` sobre `.../completion` **y** `.../title`, enmascara `body.prompt` / `body.message_content`. | **Fuga de título**: el endpoint `/title` manda el prompt crudo → hay que enmascararlo también. **Artefactos** en `iframe` → el unmask del DOM no llega. |
| **Gemini (web)** | 🟡 Parcial — **pendiente de validación** | `browser` | **DOM-hook** sobre el editor **Quill** (`.ql-editor`) en `gemini.google.com`: enmascara el texto del prompt en el editor antes del envío (no vía `fetch`). | Aún **sin verificar**. A diferencia de ChatGPT/Claude no se mapea endpoint/stream: el approach es hookear el editor Quill, no interceptar el POST. Los `content_scripts` del manifest deben matchear `gemini.google.com`. |
| **Cursor** | 🟡 Parcial — **solo chat/plan** | `base_url` | **Override OpenAI Base URL** (settings de Cursor) → apunta el endpoint OpenAI-compatible del modelo al gateway. Gobierna el **chat** y el **modo plan**. | El **agente Composer** y el **autocomplete** **no** pasan por el override (enrutan por el backend propio de Cursor) → quedan fuera del firewall. **Misma casilla que Copilot en modo Ask** (ver §2.4 y [G1](gotchas.md)). |
| **Claude Desktop** | ⚪ MCP tool-plane only | `mcp` | No expone override de `base_url`; la gobernanza entra por **MCP**: la DLP se aplica sobre los **results de las tools** MCP, **no** sobre el prompt del chat. | El prompt del usuario al modelo **no** es interceptable (fuera del reverse-proxy); sólo se gobierna el **plano de tools**. Fuera del scope de las dos superficies principales. |

**Cómo se detecta la herramienta.** El gateway mapea el `User-Agent` a un nombre amigable
(`claude` → Claude Code, `copilot` → GitHub Copilot, `vscode` → VS Code, `cursor` → Cursor,
`gemini` → Gemini CLI, `curl`/`httpx`/`python-requests` → API directa…). Un UA no reconocido cae a
**"Desconocido"** y **no** crashea: se audita con esa etiqueta.

---

## 2. Cómo configurar cada superficie

### 2.1 Claude Code (`base_url`, superficie 1)

Modo recomendado: **suscripción** (la calidad de los modelos Claude reales + la gobernanza del
gateway). Aislar el `ANTHROPIC_BASE_URL` **al proyecto** con un `.claude/settings.json` (no toca
el Claude global):

```jsonc
// ~/mi-proyecto/.claude/settings.json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:8081/gw",
    "ANTHROPIC_CUSTOM_HEADERS": "X-Basa-Key: sk-basa-laura-cc-2026"
  }
}
```

- `ANTHROPIC_BASE_URL` → apunta a `…/gw` (Claude Code le agrega `/v1/messages`).
- `ANTHROPIC_CUSTOM_HEADERS` → `X-Basa-Key: sk-basa-…` da **atribución de identidad**
  (usuario/equipo). Sin ella, el evento se atribuye al identity por defecto.
- La suscripción OAuth del cliente viaja en `Authorization` y **atraviesa verbatim** — `X-Basa-Key`
  está **excluido** del auto-byok, así que la key de atribución NO desvía a Claude Code al motor.
- **Reiniciá `claude`** después de tocar el archivo (los headers se leen al arrancar).

Forzar modo `byok` (consumir modelos gobernados del motor del gateway) por request:

```bash
# header por request; o BASA_GW_UPSTREAM_DEFAULT=byok en el entorno del gateway
curl -s http://localhost:8081/gw/v1/messages \
  -H "content-type: application/json" \
  -H "X-Basa-Key: sk-basa-laura-cc-2026" \
  -H "X-Basa-Upstream: byok" \
  -d '{"model":"gpt-4o-mini","max_tokens":256,"messages":[{"role":"user","content":"hola"}]}'
```

Verificar identidad:

```bash
curl -s http://localhost:8081/gw/whoami -H "X-Basa-Key: sk-basa-laura-cc-2026"
# → {"ok":true,"user":"marc.ferrer","team":"Oncología","key_label":"…"}
```

### 2.2 VS Code / GitHub Copilot (`base_url`, **modo Ask**)

`Chat: Manage Language Models` → **Custom** → `apiType` = **`messages`**. Copilot manda `x-api-key`
**vacío** e **ignora** el `apiKey` del config, así que la virtual key se mete **en la URL**
(`?k=…`). El archivo vive en `~/Library/Application Support/Code/User/chatLanguageModels.json`:

```jsonc
// chatLanguageModels.json
[
  {
    "apiType": "messages",
    "url": "http://localhost:8081/gw/v1/messages?k=sk-basa-<tu-connection>",
    "id": "gpt-4o-mini"
  }
]
```

- **Usar modo Ask**, no Agent/Edit (ver [G1](gotchas.md)).
- El gateway lee la key de la URL como fallback → auto-byok + atribución. La key en la URL es un
  **atajo para entornos de prueba**; en producción va por input seguro/SSO.
- Modelos del motor verificados que responden: `gpt-4o-mini`, `gpt-4o`, `groq-llama3-8b`,
  `groq-llama-3.3-70b`, `gemini-2.5-flash(-lite)`, `bedrock-claude-3-5-sonnet` (según las
  credenciales BYOK configuradas por el operador en el motor).

### 2.3 Browser — ChatGPT / Claude web (superficie 2, extensión de navegador)

1. **Instalar la extensión (descomprimida):** `brave://extensions` o `chrome://extensions` →
   activar **Modo desarrollador** → **Cargar descomprimida** → la carpeta de la extensión provista
   con el producto. Para actualizar el código, botón **↻** sobre la tarjeta de la extensión.
2. **Conectar (login):** click en el ícono 🛡️ → pegar la key (p. ej. `sk-basa-<tu-connection>`)
   y el gateway (`http://localhost:8081/gw`) → **Conectar**. El popup valida contra
   `GET /gw/whoami` y muestra "🟢 Conectado como sofia.nunez · Radiología".
3. **Toggle** de protección en el popup (por defecto ON).

Notas de arquitectura útiles para soporte:

- La key vive en `chrome.storage.local`; **solo el service worker** de la extensión habla con el
  gateway (`host_permissions` → sin CORS). El content script **nunca** ve la key.
- **Fail-closed:** sin key válida, un overlay **bloquea** la página (no hay key → no se usa la IA).
  Si el gateway se cae estando conectado, también bloquea.
- `host_permissions` del manifest = `http://localhost:8081/*`. **Si cambia el host del gateway hay
  que editar el `manifest.json`** (`host_permissions` y, en producción, `chrome.storage.managed`
  vía MDM).

### 2.4 Cursor (`base_url`, **solo chat/plan**)

Cursor se gobierna **parcialmente** vía **Override OpenAI Base URL** (en los settings de Cursor):
se apunta el endpoint OpenAI-compatible del modelo al gateway y el **chat** y el **modo plan**
pasan por el firewall (masking/bloqueo + monitor). Es la **misma casilla** que Copilot en modo
Ask (§2.2).

!!! warning "Cobertura parcial"
    El **agente Composer** y el **autocomplete** **no** honran el override — enrutan por el
    backend propio de Cursor y quedan **fuera** del firewall (igual que Agent/Edit en Copilot,
    [G1](gotchas.md)). La gobernanza alcanza la ruta de chat/plan, no la agéntica. Presentarlo
    siempre como "Cursor chat/plan gobernado, Composer/autocomplete no", **nunca** como cobertura
    total.

---

**Siguiente:** [Gotchas verificados](gotchas.md) — los límites conocidos de cada superficie con
su causa y su fix.
