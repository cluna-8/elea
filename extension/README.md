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

## Honesto / límites
- Detección de nombres = la del gateway (mejor que el regex v0.1, pero prod = Presidio NLP real, SC-2).
- Artefactos de Claude en iframe: el unmask del DOM no llega (chat normal sí).
- PoC: gateway local (`localhost:8081`). Prod: enrollment por SSO (spec 017) + deploy por MDM.

## Próximos pasos
- [ ] Tag de `surface` visible en el HTML del monitor (browser vs base_url).
- [ ] Enrollment por SSO en vez de pegar la key a mano (spec 017).
- [ ] Unmask en iframes (artefactos de Claude).
- [ ] Formalizar como spec del módulo browser-DLP en `basa-guardian/specs/`.
