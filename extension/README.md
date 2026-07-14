# Basa Guard — browser-DLP (PoC, v0.2 · conectado al gateway)

Firewall de PII para **ChatGPT** y **Claude web**, **conectado al gateway de Basa**. Enmascara PII
antes de que salga al vendor (el modelo ve `[PERSON_0]`), des-enmascara en pantalla, y — la novedad de
la v0.2 — **requiere una API key** (fail-closed) y **atribuye el uso a un usuario/equipo en el "Firewall
en vivo"**, igual que Claude Code pero `surface="browser"`.

> Validado en vivo el 2026-07-10 sobre ChatGPT (`gpt-5-6-thinking`) y Claude.ai (`fable-5`).

## Qué cambió vs v0.1
- **Masking vía gateway** (`POST /gw/inspect`), no regex local → misma detección que el resto del
  producto (Presidio/regex central) + audit + monitor.
- **Fail-closed (SC-3):** sin API key válida (validada con `GET /gw/whoami`), un **overlay bloquea** la
  página. No hay key → no se usa la IA.
- **Identidad:** la key ES el `Client` (Constitución IV). El popup te loguea → "sofia.nunez · Radiología".
- **Popup** con login (key + gateway) y **toggle** de protección.

## Arquitectura (5 piezas)
- `basa-guard.js` (MAIN): hookea `fetch`, gating, manda el texto al gateway, des-enmascara en el DOM.
- `bridge.js` (ISOLATED): puente `postMessage` ↔ `chrome.runtime` (MAIN no puede usar `chrome.*`).
- `background.js` (service worker): único que llama al gateway (host_permissions → sin CORS); guarda la key.
- `popup.html`/`popup.js`: login + toggle.
- Gateway: `/gw/whoami` (identidad) y `/gw/inspect` (mask + audit + push al monitor con `surface:"browser"`).

## Puesta en marcha

**1. Backend (una vez):** gateway arriba + seed del usuario de Radiología:
```bash
docker exec eu-backend python -m scripts.seed_browser_demo
# crea: sofia.nunez / Radiología · key: sk-basa-radiologia-browser-2026
```

**2. Cargar/recargar la extensión:** `brave://extensions` (o `chrome://`) → **↻** en Basa Guard
(o "Cargar descomprimida" → carpeta `basa-browser-dlp/` si es la primera vez).

**3. Conectar:** click en el ícono 🛡️ → pegá la key `sk-basa-radiologia-browser-2026`, gateway
`http://localhost:8081/gw` → **Conectar** → "🟢 Conectado como sofia.nunez · Radiología".

## Guion de demo (el contraste es la gracia)
1. **Sin conectar:** abrí ChatGPT → **overlay de bloqueo** ("necesitás tu API key"). *No se puede usar.*
2. **Conectá** con la key de Radiología → el overlay desaparece.
3. Prompt: *"email para el paciente Juan Perez (juan.perez@clinica.es)…"* → el panel muestra
   **team/user + entidades + lo que salió enmascarado**; el modelo ve `[PERSON_0]`, vos ves el nombre real.
4. Abrí el **monitor** `http://localhost:8081/gw/monitor` → aparece la tarjeta **`browser · sofia.nunez ·
   Radiología`**, junto a Claude Code. *"Un empleado, N herramientas, un firewall."*

## Modelo de amenaza (leer antes de confiar en el fail-closed)

**Qué protege Basa Guard:** la **fuga accidental de PII del propio usuario** cuando usa sitios de IA
de **confianza** (ChatGPT, Claude.ai). El usuario pega datos sensibles sin querer; la extensión los
enmascara antes de que salgan al vendor, o **bloquea el envío** (fail-closed) si no puede garantizar el
masking o no hay key válida. Ese es el caso de uso real y la garantía es fuerte para él.

**Qué NO protege: una página hostil.** Los content scripts del mundo **MAIN** (donde corre
`basa-guard.js` para hookear `window.fetch`) **comparten el `window` con los scripts de la propia
página** — es una limitación arquitectónica de los hooks MAIN-world en MV3, no un bug. Una página
hostil controla ese contexto JS y podría, entre otras cosas:
- exfiltrar los datos por otros medios (su propio `fetch`/`XHR`/`WebSocket`, `sendBeacon`, imágenes, …)
  sin pasar por los adapters que hookeamos;
- **observar el handshake** del nonce (los `postMessage` viajan por el mismo `window`) y, con esfuerzo,
  reproducirlo.

**Mitigación de forja de `postMessage` (F-ext-1):** el bridge (mundo ISOLATED) genera un
`crypto.randomUUID()` al arrancar y lo adjunta a **cada** mensaje hacia MAIN (`init`, `state`, `resp`).
MAIN **fija el primer nonce** que ve de un mensaje del bridge y **descarta** cualquier `state`/`resp`
con nonce distinto o ausente. Esto **frena la forja ingenua** (un script de la página que simplemente
postea `{__basa:"state", state:{connected:true}}` para desactivar el fail-closed, o una `resp` falsa
`{ok:true, replacements:[]}` para colar PII cruda). **No es criptográficamente inforjable** —la página
observa el handshake y comparte el mundo—, pero **eleva el costo** y cubre el caso realista (script de
terceros/anuncio ingenuo, no un atacante que instrumenta activamente el mundo MAIN).

**Conclusión honesta:** la garantía fuerte de fail-closed + masking aplica a **páginas no-hostiles de
confianza**. Contra una **página activamente hostil** el nonce es defense-in-depth, no una barrera
infranqueable. Es una **limitación conocida y documentada**, no un descuido.

## Verificación (hardening 019 — fail-closed)

`node --check extension/basa-guard.js` y `node --check extension/bridge.js` deben pasar (sintaxis).
Verificación manual (cargar la extensión descomprimida y observar):

1. **Fail-closed por match, no por body (F4):** desconectá la extensión (sin key válida) y abrí
   ChatGPT/Claude. Cualquier request a un endpoint de envío se **bloquea** (throw `[Basa Guard] …`),
   incluso si el body no es un string JSON (Request/Blob/FormData). Conectado + masking ON, un request
   a un endpoint matcheado con **body no-texto** también se **bloquea** (mensaje "body no-texto") en vez
   de mandarse crudo. Un request a un endpoint **no** matcheado pasa normal.
2. **Fail-closed en el catch (F6):** forzá un error dentro del path de masking (p.ej. un body JSON
   inválido en un endpoint matcheado, estando conectado + ON): el envío se **bloquea** (throw), no se
   reenvía el body original sin enmascarar. Un error en un request no-matcheado **no** interfiere.
3. **Forja de estado (F-ext-1):** en la consola de la página (mundo de la página), ejecutá
   `window.postMessage({__basa:"state", state:{enabled:true, connected:true}}, "*")`. El gate **no**
   cambia a "conectado" (el mensaje se descarta por nonce faltante/incorrecto); el overlay de bloqueo
   sigue si no hay key real. Lo mismo con una `resp` forjada para un id pendiente: se descarta.

## Honesto / límites
- Detección de nombres = la del gateway (mejor que el regex v0.1, pero prod = Presidio NLP real, SC-2).
- Artefactos de Claude en iframe: el unmask del DOM no llega (chat normal sí).
- PoC: gateway local (`localhost:8081`). Prod: enrollment por SSO (spec 017) + deploy por MDM.
- **Superficie de ataque (MAIN-world):** ver "Modelo de amenaza" arriba — el nonce mitiga forja ingenua
  de `postMessage`, no una página activamente hostil (comparte el contexto JS del mundo MAIN).

## Próximos pasos
- [ ] Tag de `surface` visible en el HTML del monitor (browser vs base_url).
- [ ] Enrollment por SSO en vez de pegar la key a mano (spec 017).
- [ ] Unmask en iframes (artefactos de Claude).
- [ ] Formalizar como spec del módulo browser-DLP en `basa-guardian/specs/`.
