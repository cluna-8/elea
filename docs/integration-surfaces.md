# Superficies de integración — cheat-sheet operativo (training & soporte)

> **Qué es esto.** Guía práctica para el **training** y el **soporte** que Basa le garantiza al
> distribuidor: qué clientes de IA se pueden gobernar con el firewall, cómo se configura cada uno, y los
> gotchas verificados en vivo con su causa y su fix. **No es una spec** (para el diseño formal ver
> `specs/013-*` y `specs/014-litellm-native-firewall/`). Es el papel que uno tiene abierto al lado
> mientras enrola una máquina o atiende un ticket.
>
> **Base de la guía.** Todo lo de acá está anclado en el código real:
> `gatelite-salud-eu/backend/src/api/gateway.py` (el firewall reverse-proxy, superficie `base_url`) y
> `basa-browser-dlp/` (la extensión Basa Guard, superficie `browser`). Los ejemplos usan la base
> **demo/dev** `http://localhost:8081/gw`; en prod es el host del gateway desplegado por el distribuidor
> (mismo path `/gw`).
>
> **Dos superficies, un producto.** (1) **`base_url`** — coding tools que dejan apuntar
> `ANTHROPIC_BASE_URL` al gateway (Claude Code, Copilot). (2) **`browser`** — apps de chat web
> (ChatGPT, Claude.ai) gobernadas por la extensión. Ambas empujan al **mismo** monitor en vivo
> (`GET /gw/monitor`) con un tag `surface`. *"Un empleado, N herramientas, un firewall."*

---

## 1. Tabla de compatibilidad

| Cliente | Estado | Superficie | Mecanismo | Gotcha clave |
|---|---|---|---|---|
| **Claude Code** | ✅ Funciona | `base_url` | `ANTHROPIC_BASE_URL` → `/gw/v1/messages`. Passthrough de **suscripción** (OAuth reenviado verbatim por `_passthrough_headers`) **o** `byok` al motor LiteLLM. | Hay que **reiniciar `claude`** para tomar `ANTHROPIC_CUSTOM_HEADERS`. En `byok` los modelos no-Claude rompen el tool-calling agéntico → usar suscripción. |
| **VS Code / GitHub Copilot** | 🟡 Parcial — **solo modo Ask** | `base_url` | `chatLanguageModels.json` con `apiType:"messages"` → `byok` al motor. Auto-byok por virtual key. | En **Agent/Edit** entra en loop (los modelos no-Claude llaman mal las tools). La key va **en la URL** (`?k=…`) porque manda `x-api-key` vacío. |
| **ChatGPT (web)** | ✅ Funciona | `browser` | Extensión Basa Guard: hookea `fetch` sobre `POST /backend-api/f/conversation`, enmascara `messages[].content.parts[]` vía `/gw/inspect`. | La respuesta **no** viene en el POST: llega por **WebSocket** (`stream_handoff`) → el unmask se hace en el **DOM**, no sobre la respuesta. |
| **Claude (web, claude.ai)** | ✅ Funciona | `browser` | Extensión Basa Guard: hookea `fetch` sobre `.../completion` **y** `.../title`, enmascara `body.prompt` / `body.message_content`. | **Fuga de título**: el endpoint `/title` manda el prompt crudo → hay que enmascararlo también. **Artefactos** en `iframe` → el unmask del DOM no llega. |
| **Gemini (web)** | 🟡 Parcial — **requiere spike** | `browser` | **DOM-hook** sobre el editor **Quill** (`.ql-editor`) en `gemini.google.com`: enmascara el texto del prompt en el editor antes del envío (no vía `fetch`). | Aún **sin verificar** — falta el spike. A diferencia de ChatGPT/Claude no se mapea endpoint/stream: el approach es hookear el editor Quill, no interceptar el POST. Los `content_scripts` del manifest deben matchear `gemini.google.com`. |
| **Cursor** | 🟡 Parcial — **solo chat/plan** | `base_url` | **Override OpenAI Base URL** (settings de Cursor) → apunta el endpoint OpenAI-compatible del modelo al gateway. Gobierna el **chat** y el **modo plan**. | El **agente Composer** y el **autocomplete** **no** pasan por el override (enrutan por el backend propio de Cursor) → quedan fuera del firewall. **Misma casilla que Copilot en modo Ask** (ver §2.4, G1). |
| **Claude Desktop** | ⚪ MCP tool-plane only | `mcp` | No expone override de `base_url`; la gobernanza entra por **MCP**: la DLP se aplica sobre los **results de las tools** MCP, **no** sobre el prompt del chat. | El prompt del usuario al modelo **no** es interceptable (fuera del reverse-proxy); sólo se gobierna el **plano de tools**. Fuera del scope de las dos superficies principales. |

**Cómo se detecta la herramienta.** El gateway mapea el `User-Agent` a un nombre amigable en
`_detect_tool` / `_TOOL_UA` (`claude`→Claude Code, `copilot`→GitHub Copilot, `vscode`→VS Code,
`cursor`→Cursor, `gemini`→Gemini CLI, `curl`/`httpx`/`python-requests`→API directa…). Un UA no
reconocido cae a **"Desconocido"** y **no** crashea: se audita con esa etiqueta.

---

## 2. Cómo configurar cada superficie

### 2.1 Claude Code (`base_url`, superficie 1)

Modo recomendado para demo: **suscripción** (calidad de Claude real + gobernanza Basa). Aislar el
`ANTHROPIC_BASE_URL` **al proyecto** con un `.claude/settings.json` (no toca el Claude global):

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
- `ANTHROPIC_CUSTOM_HEADERS` → `X-Basa-Key: sk-basa-…` da **atribución de identidad** (usuario/equipo).
  Sin ella, el evento se atribuye al identity por defecto.
- La suscripción OAuth del cliente viaja en `Authorization` y **atraviesa verbatim** — `X-Basa-Key`
  está **excluido** del auto-byok, así que la key de atribución NO desvía a Claude Code al motor.
- **Reiniciá `claude`** después de tocar el archivo (los headers se leen al arrancar).

Forzar modo `byok` (consumir modelos gobernados del motor) por request:

```bash
# header por request; o BASA_GW_UPSTREAM_DEFAULT=byok en el entorno del gateway
curl -s http://localhost:8081/gw/v1/messages \
  -H "content-type: application/json" \
  -H "X-Basa-Key: sk-basa-laura-cc-2026" \
  -H "X-Basa-Upstream: byok" \
  -d '{"model":"gpt-4o-mini","max_tokens":256,"messages":[{"role":"user","content":"hola"}]}'
```

Verificar identidad antes de una demo:

```bash
curl -s http://localhost:8081/gw/whoami -H "X-Basa-Key: sk-basa-laura-cc-2026"
# → {"ok":true,"user":"marc.ferrer","team":"Oncología","key_label":"…"}
```

### 2.2 VS Code / GitHub Copilot (`base_url`, **modo Ask**)

`Chat: Manage Language Models` → **Custom** → `apiType` = **`messages`**. Copilot manda `x-api-key`
**vacío** e **ignora** el `apiKey` del config, así que la virtual key se mete **en la URL** (`?k=…`).
El archivo vive en `~/Library/Application Support/Code/User/chatLanguageModels.json`:

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

- **Usar modo Ask**, no Agent/Edit (ver gotcha G1).
- El gateway lee la key de la URL como fallback (`_BASA_KEY_RE.search(str(request.url))`) → auto-byok +
  atribución. La key en la URL es un **atajo de demo**; en prod va por input seguro/SSO.
- Modelos del motor verificados que responden: `gpt-4o-mini`, `gpt-4o`, `groq-llama3-8b`,
  `groq-llama-3.3-70b`, `gemini-2.5-flash(-lite)`, `bedrock-claude-3-5-sonnet` (según credenciales del
  motor).

### 2.3 Browser — ChatGPT / Claude web (superficie 2, extensión Basa Guard)

1. **Instalar la extensión (descomprimida):** `brave://extensions` o `chrome://extensions` → activar
   **Modo desarrollador** → **Cargar descomprimida** → carpeta `basa-browser-dlp/`. Para actualizar el
   código, botón **↻** sobre la tarjeta de la extensión.
2. **Conectar (login):** click en el ícono 🛡️ → pegar la key (p. ej. `sk-basa-<tu-connection>`)
   y el gateway (`http://localhost:8081/gw`) → **Conectar**. El popup valida contra `GET /gw/whoami` y
   muestra "🟢 Conectado como sofia.nunez · Radiología".
3. **Toggle** de protección en el popup (por defecto ON).

Notas de arquitectura útiles para soporte:

- La key vive en `chrome.storage.local`; **solo el service worker** (`background.js`) habla con el
  gateway (`host_permissions` → sin CORS). El content script **nunca** ve la key.
- **Fail-closed:** sin key válida, un overlay **bloquea** la página (no hay key → no se usa la IA). Si el
  gateway se cae estando conectado, también bloquea.
- `host_permissions` del manifest = `http://localhost:8081/*`. **Si cambia el host del gateway hay que
  editar el `manifest.json`** (`host_permissions` y, en prod, `chrome.storage.managed` vía MDM).

### 2.4 Cursor (`base_url`, **solo chat/plan**)

Cursor se gobierna **parcialmente** vía **Override OpenAI Base URL** (en los settings de Cursor): se apunta
el endpoint OpenAI-compatible del modelo al gateway y el **chat** y el **modo plan** pasan por el firewall
(masking/bloqueo + monitor). Es la **misma casilla** que Copilot en modo Ask (§2.2).

- **Cobertura parcial:** el **agente Composer** y el **autocomplete** **no** honran el override — enrutan
  por el backend propio de Cursor y quedan **fuera** del firewall (igual que Agent/Edit en Copilot, G1). La
  gobernanza alcanza la ruta de chat/plan, no la agéntica.
- En training: presentarlo como "Cursor chat/plan gobernado, Composer/autocomplete no", **nunca** como
  cobertura total.

---

## 3. Gotchas verificados (causa → fix)

### G1 · Ask vs Agent en Copilot (loop en Agent)
- **Síntoma:** con `gpt-4o-mini` en `byok`, Copilot en **Agent/Edit** loopea: invoca tools, el modelo
  no-Claude las llama mal, VS Code rechaza el input (`must match pattern ^[0-9a-fA-F]{8}-…`, un UUID),
  reintenta cada ~8 s → termina en 400. En el monitor se ve `mode=byok in=0 out=NN` repetido y la tarjeta
  muestra el **texto del error** en vez del prompt.
- **Causa:** el tool-calling agéntico de Claude Code lo aguantan solo los modelos Claude; los modelos del
  motor (gpt-4o-mini, groq…) no cumplen el contrato de tools.
- **Fix:** **usar modo Ask** (sin tool-calling → el modelo responde texto y el enmascaramiento anda).
  Claude Code sí aguanta Agent porque va por **passthrough de suscripción** a Claude real.

### G2 · Key en la URL porque `x-api-key` llega vacío (Copilot)
- **Síntoma:** Copilot no autentica; el gateway no ve virtual key.
- **Causa:** Copilot manda `x-api-key` **vacío** e **ignora** el `apiKey` del `chatLanguageModels.json`;
  tampoco deja mandar headers custom.
- **Fix:** meter la key **en la URL** (`…/gw/v1/messages?k=sk-basa-…`). El gateway la levanta con el
  fallback `_BASA_KEY_RE.search(str(request.url))`. Atajo de demo; en prod la key va por input seguro/SSO.

### G3 · Fuga de título en Claude.ai
- **Síntoma:** el nombre real del paciente aparece en el **título** de la conversación aunque el chat esté
  enmascarado.
- **Causa:** además de `.../completion`, Claude.ai llama a un endpoint **aparte**
  `POST .../chat_conversations/{id}/title` con `body.message_content` = **prompt crudo** para generar el
  título.
- **Fix:** el adapter `claude` matchea **también** `/title` y enmascara `message_content`; y en el DOM se
  corre `unmaskTitle()` sobre `document.title`. Si reaparece el nombre en el título, revisar que el match
  del adapter incluya `/title`.

### G4 · Unmask en el DOM (no sobre la respuesta) por WebSocket
- **Síntoma:** intentar des-enmascarar leyendo la respuesta del `fetch` no encuentra los placeholders.
- **Causa:** en ChatGPT la respuesta del POST es un `stream_handoff`; los tokens llegan por **WebSocket**,
  no en el body de la respuesta.
- **Fix:** el unmask se hace **en el DOM** con un `MutationObserver` (agnóstico al transporte): el mapa
  reversible es local y se reemplaza sobre los text-nodes a medida que se pintan.

### G5 · Artefactos de Claude en `iframe`
- **Síntoma:** dentro de un **artefacto** de Claude se ven los `[PLACEHOLDER]` crudos (el chat normal sí
  des-enmascara).
- **Causa:** el artefacto renderiza en un **iframe** y el manifest usa `all_frames:false` → el content
  script (y su `MutationObserver`) no entra al iframe.
- **Fix:** limitación conocida del PoC (documentada). Roadmap: unmask dentro de iframes/artefactos. Como
  workaround de demo, mostrar el resultado en el chat, no en el artefacto.

### G6 · Body no firmado (lo que hace viable el masking)
- **Hecho:** ni ChatGPT (`sentinel`/proof-of-work) ni Claude.ai hacen **integrity-check del body** → el
  body modificado se **acepta** (probado: MANGO→PLATANO, el modelo respondió PLATANO).
- **Implicación para soporte:** el masking depende de esto. Si un vendor empieza a **firmar el body**, el
  adapter deja de poder mutar el request y hay que replantear (enterprise-browser). Es el riesgo
  estructural de la superficie `browser`.

### G7 · El cap de inspección toma la **cola**, no la cabeza
- **Síntoma (bug histórico, arreglado):** un **secreto** pasaba **PERMITIDO** en prompts agénticos
  enormes (Copilot ~22k tokens, Claude Code).
- **Causa:** `_extract_inspect_text` tomaba `system + último turno` truncado a `_INSPECT_CAP=16000` chars
  **desde la cabeza**; el `<userRequest>` con el secreto va al **FINAL** → quedaba fuera del cap. (La PII
  sí se enmascaraba porque eso corre sobre el body completo, no sobre la copia de inspección.)
- **Fix:** la inspección toma la **cola** del último turno (`last_user[-_INSPECT_CAP:]`) + cabeza del
  system. Ahora los secretos se bloquean en Copilot y Claude Code.

### G8 · La exclusión `x-basa-*` es load-bearing
- **Hecho:** el auto-byok escanea **todos** los headers buscando una virtual key `sk-basa-…`, **pero
  excluye** los headers `x-basa-*`.
- **Por qué importa:** si no se excluyeran, la `X-Basa-Key` de **atribución** de Claude Code dispararía el
  auto-byok y **desviaría al motor** una sesión que debe ir por **passthrough de suscripción**. La
  exclusión mantiene: `X-Basa-Key` = identidad; cualquier `sk-basa-…` en `x-api-key`/`Authorization` =
  credencial → byok.
- **Regla de soporte:** **no** metas la virtual key en un header `x-basa-*` esperando que enrute a byok;
  para byok va en `x-api-key`/`Authorization`/URL. Para atribución sin desviar, va en `X-Basa-Key`.

---

## 4. Troubleshooting rápido

| Síntoma | Causa probable | Fix |
|---|---|---|
| Claude Code ignora la identidad (aparece admin/default) | No reinició `claude` tras editar `settings.json`; o falta `X-Basa-Key` | Reiniciar `claude`; verificar con `curl …/gw/whoami -H "X-Basa-Key: …"` |
| Copilot 401 / no autentica | `x-api-key` vacío, `apiKey` ignorado (G2) | Poner la key en la URL: `…/v1/messages?k=sk-basa-…` |
| Copilot loopea, tarjetas `in=0 out=NN` repetidas (G1) | Modo Agent/Edit con modelo no-Claude | Cambiar a **modo Ask** |
| El nombre real sale en el título de Claude.ai (G3) | Endpoint `/title` con prompt crudo | Confirmar que el adapter matchea `/title`; recargar la extensión (↻) |
| Placeholders `[PERSON_0]` visibles en un artefacto de Claude (G5) | Artefacto en `iframe`, `all_frames:false` | Limitación conocida; mostrar en el chat |
| La página web queda bloqueada por un overlay 🛡️ | Fail-closed: sin key válida o gateway caído | Conectar con key válida en el popup; verificar que el gateway responde `/gw/whoami` |
| La extensión no llega al gateway (sin CORS pero sin respuesta) | `host_permissions` del manifest no cubre el host | Editar `manifest.json` (`host_permissions`) y recargar |
| Un secreto pasa PERMITIDO en un prompt gigante | Cap de inspección desde la cabeza (G7) | Debe estar el fix de la **cola**; confirmar versión del gateway |
| En `byok` Claude Code falla tool-calling (`tool_use_failed`) | Modelo no-Claude no soporta el tool-calling agéntico | Usar **suscripción** (default `anthropic`), no byok, para Claude Code |
| Nada aparece en el monitor | Superficie no llama al gateway (masking local viejo) o buffer limpio | La extensión debe llamar `/gw/inspect`; ver `GET /gw/events`; `DELETE /gw/events` resetea |

**Endpoints de apoyo (superficie `base_url` + `browser`):**
`POST /gw/v1/messages` (firewall), `POST /gw/v1/messages/count_tokens`, `GET /gw/v1/models`,
`GET /gw/whoami` (valida key → identidad), `POST /gw/inspect` (masking de texto plano, fail-closed),
`GET /gw/monitor` (consola en vivo), `GET/DELETE /gw/events`, `GET/POST /gw/config` (`{redact}`).

**Recordatorio de honestidad (para no sobrevender en la demo):** la detección de PII hoy es regex
in-process (Presidio NLP real = roadmap, spec 016); el monitor es una **vitrina de demo** con feed
efímero en memoria — la auditoría durable (Postgres) sigue siendo **metadata-only** (cero texto de
prompt, cero PII cruda). El masking reversible reenvía el original salvo con redacción activa
(`X-Basa-Redact`), donde el modelo solo ve placeholders y el caller recibe los valores reales.
