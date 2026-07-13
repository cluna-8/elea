# Feature Specification: Integration Surfaces & Client Compatibility

**Feature Branch**: `019-integration-surfaces`

**Created**: 2026-07-13

**Status**: Draft

**Input**: User description: "Documentar y portar el LADO CLIENTE del firewall: qué herramientas se
integran a Basa, cómo se enganchan (passthrough de suscripción, auto-byok, key-in-URL, extensión de
navegador MV3) y la matriz de compatibilidad real (qué FUNCIONA, qué es PARCIAL, qué NO y por qué).
Complementa la 014 (lado gateway). Depende del bedrock 013 y del port de la 014."

---

## Contexto y honestidad SDD *(léelo antes que nada)*

Esta feature es un **PORT + FORMALIZACIÓN**, no una feature verde. Las superficies de integración que
esta spec describe **ya existen y se probaron en vivo** en el repo **DEMO** `gatelite-salud-eu`, no en
`basa-guardian`. Dos piezas de evidencia son la fuente de verdad:

- **`gatelite-salud-eu/backend/src/api/gateway.py`** — el reverse-proxy hand-rolled que hoy da las
  demos. De ahí salen literalmente: los dos modos de upstream (`X-Basa-Upstream`, default
  `BASA_GW_UPSTREAM_DEFAULT`), el **auto-byok** por virtual key (`_BASA_KEY_RE = sk-basa-…`, con el
  scan que **excluye** los headers `x-basa-*`), el **key-in-URL** (`?k=sk-basa-…`) como fallback de
  Copilot, la **identidad por `X-Basa-Key`** (`_resolve_identity`, sha256→user/group, fail-closed a
  default), la **detección de herramienta por User-Agent** (`_TOOL_UA`/`_detect_tool`), y los endpoints
  de la extensión (`GET /gw/whoami`, `POST /gw/inspect`, monitor `surface="browser"`).
- **`basa-browser-dlp/`** — la extensión MV3 (superficie 2) validada en vivo sobre ChatGPT y Claude.ai:
  `manifest.json` (content scripts MAIN + ISOLATED, `all_frames:false`), `basa-guard.js` (hook de
  `window.fetch`, mask vía `/gw/inspect`, unmask en DOM con `MutationObserver`, `unmask` + `unmaskTitle`),
  `bridge.js` (mundo ISOLATED) y `background.js` (service worker que guarda la key; el MAIN nunca la ve).

**Qué es esta spec, honestamente:** la **014** formalizó el LADO GATEWAY (el firewall como guardrail
nativo de LiteLLM + la excepción del passthrough OAuth). Esta **019** formaliza el **LADO CLIENTE**: qué
herramientas se conectan, **cómo** se enganchan a Basa, y la **matriz de compatibilidad real** con su
por-qué técnico (incluyendo lo que NO funciona y por qué). No inventa mecanismos nuevos: **porta a
`basa-guardian` los mecanismos ya probados en el demo** y los eleva a requisitos versionados.

**Alcance honesto:**
- **Lo que está IMPLEMENTADO y probado (en el demo, a portar):** passthrough de suscripción de Claude
  Code; auto-byok + key-in-URL para VS Code/Copilot; extensión MV3 para ChatGPT web y Claude web
  (incluida la cobertura de la fuga de título de Claude.ai).
- **Lo que es ROADMAP (esta spec lo documenta, NO lo entrega):** el adapter de **Gemini web** (US5, P3;
  **viable** vía DOM-hook — requiere spike en vivo); la gobernanza de **Claude Desktop vía MCP** (se
  documenta como superficie MCP-only de alcance **tool-plane** —gobierna args/results de tools, no el
  chat—, su implementación es otra spec); el des-enmascarado dentro de **iframes** de artefactos
  (`all_frames:false` hoy).
- **Excepción constitucional heredada:** el `base_url` firewall es la **excepción documentada del
  Principio II** (GDPR-routing N/A), ya ratificada en la constitución y en la 014. Esta spec la **reusa**,
  no la re-abre.

Depende del **bedrock 013** (Tenant, `role="client"`, `client_type`, la Connection = APIKey con
`tenant_id`/`tool_type`/`upstream_mode`) y del port de la **014** (el gateway al que apuntan estos
clientes). Esta spec **no** re-diseña el gateway ni el schema: los **consume** desde el lado cliente.

**Mapeo a principios de la constitución (v2.0.0):**
- **VI. LiteLLM-Native, No Patching** — el enganche de cada cliente reusa mecanismos estándar
  (`ANTHROPIC_BASE_URL`, `x-api-key`, `window.fetch` del navegador). La única superficie que exige proxy
  propio (passthrough de suscripción) ya está acotada por la 014.
- **VIII. Pipeline Transparency** — toda superficie (base_url y browser) empuja su before/after real al
  **mismo** monitor en vivo (`surface="browser"` para la extensión); la observabilidad es común a todos
  los clientes.
- **IV. Client Onboarding as Data** — cada herramienta es una `Connection`/`APIKey` con su `tool_type` y
  `upstream_mode`; sumar o quitar una superficie soportada es **config + seed**, no código.
- **Excepción del II** — el `base_url` firewall (Claude Code/Copilot) y la extensión operan *dentro* del
  cliente sin re-inyectar, por lo que el GDPR-routing es N/A (garantía trasladada a masking/audit/allowlist).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Claude Code: passthrough de suscripción + identidad (Priority: P1)

Un desarrollador con **suscripción** Claude Pro/Max apunta `ANTHROPIC_BASE_URL` de Claude Code al gateway
de Basa. El gateway corre en modo **`anthropic`** (default; reconciliado como `subscription-passthrough`
en el vocabulario de la 013) y actúa como **reverse-proxy fiel** a `api.anthropic.com`: reenvía la
credencial del cliente (el token OAuth de la suscripción) **verbatim**, junto con `anthropic-version`,
`anthropic-beta`, User-Agent y los `x-app` que Claude Code necesita. Resultado: **la suscripción del
cliente paga** (Basa no gasta tokens) y Basa **sólo firewallea** (bloqueo + masking/unmask). En paralelo,
Basa **atribuye identidad**: la herramienta se detecta por User-Agent (`claude` → Claude Code) y el
`X-Basa-Key` (opcional) resuelve tenant/cliente/equipo para la auditoría, **sin** consumirse como
credencial de upstream.

**Why this priority**: Es la superficie titular de las demos ("firewall on top of your subscription") y
la que **funciona de punta a punta hoy**, incluso en modo Agent, porque Claude Code habla con modelos
Claude que **no rompen** el tool-calling al pasar por el proxy. Sin ella no hay demo vendible del firewall
sobre coding tools. Materializa la excepción acotada del Principio II y el reuso de `ANTHROPIC_BASE_URL`
(Principio VI).

**Independent Test**: Apuntar `ANTHROPIC_BASE_URL` de Claude Code al gateway en modo `anthropic`, mandar
un prompt con PII y un turno agéntico (tool_use). Verificar: (a) el token OAuth llega **verbatim** a
`api.anthropic.com` y la suscripción responde; (b) el User-Agent resuelve `tool_type` = "Claude Code";
(c) la PII sale enmascarada al upstream y vuelve des-enmascarada al caller; (d) el ciclo agéntico
(tool_use/tool_result) completa sin corromperse.

**Acceptance Scenarios**:

1. **Given** Claude Code con `ANTHROPIC_BASE_URL` = gateway y `upstream_mode` = `subscription-passthrough`
   (013; "anthropic" en el demo), **When** llega una request con el OAuth de la suscripción, **Then** el
   gateway reenvía el `Authorization`/OAuth **verbatim** a `api.anthropic.com` y NO lo consume como su
   propia credencial.
2. **Given** una request con User-Agent que contiene "claude", **When** el gateway detecta la herramienta,
   **Then** `tool_type` resuelve a "Claude Code" (porta `_TOOL_UA`/`_detect_tool`).
3. **Given** un `X-Basa-Key` presente, **When** se resuelve identidad, **Then** atribuye tenant/cliente/
   equipo por `key_hash` (sha256) para la auditoría, pero **no** viaja al upstream ni se usa como
   credencial (porta `_resolve_identity`; ver US2 para el scan que lo excluye del auto-byok).
4. **Given** un turno agéntico (tool_use) con PII, **When** Claude Code opera en modo Agent, **Then** el
   round-trip completa sin corromper el tool-calling (los modelos Claude mantienen el protocolo) y sin
   dejar placeholders crudos en la respuesta.

---

### User Story 2 - VS Code / GitHub Copilot: auto-byok + key-in-URL + modo Ask (Priority: P1)

Un desarrollador usa **VS Code / GitHub Copilot** apuntado a Basa en modo **BYOK** (la key de Basa
gobierna el motor: cost tracking + budgets). Como Copilot **no manda header de control** `X-Basa-Upstream`,
el gateway usa **auto-byok**: si detecta una virtual key `sk-basa-…` (`_BASA_KEY_RE`) en **cualquier**
header de auth, enruta a byok **y** atribuye identidad — **sin** header de control. El scan **excluye**
los headers `x-basa-*` (load-bearing: si no los excluyera, la `X-Basa-Key` de Claude Code lo sacaría del
passthrough de suscripción). Para Copilot, que manda `x-api-key` **vacío**, ignora el `apiKey` del config
y **no** deja mandar headers custom, existe el fallback **key-in-URL** (`?k=sk-basa-…`): la key viaja en
la URL (atajo de demo; en prod va por input seguro/SSO). Esta superficie es **PARCIAL**: exige **modo
Ask** obligatorio, porque en modo **Agent** loopea (los modelos no-Claude rompen el tool-calling y VS Code
rechaza el input UUID → 400).

**Why this priority**: Es la segunda superficie base_url y prueba que Basa gobierna herramientas que **no
cooperan** con headers de control (auto-byok + key-in-URL). Es P1 porque el mecanismo (detección de virtual
key + exclusión de `x-basa-*`) es load-bearing para que **coexistan** Claude Code (passthrough) y Copilot
(byok) sobre el mismo gateway. La limitación a modo Ask es una **verdad de compatibilidad** que la spec
debe fijar, no esconder.

**Independent Test**: Apuntar Copilot a Basa **sin** header de control, con la key `sk-basa-…` en la URL
(`?k=…`). Verificar: (a) el gateway enruta a byok por detección de virtual key; (b) la identidad se
atribuye (tenant/cliente); (c) en **modo Ask** el masking/unmask completa; (d) documentar que en **modo
Agent** con modelo no-Claude el ciclo falla (tool_use_failed / 400 por input UUID) — comportamiento
esperado, no bug.

**Acceptance Scenarios**:

1. **Given** una request **sin** `X-Basa-Upstream` que trae una virtual key `sk-basa-…` en un header de
   auth (p.ej. `x-api-key` o `authorization`), **When** el gateway la inspecciona, **Then** enruta a
   **byok** por auto-detección (porta `_BASA_KEY_RE`) y atribuye identidad, sin necesidad de header de
   control.
2. **Given** la misma inspección, **When** la virtual key aparece en un header `x-basa-*` (p.ej.
   `X-Basa-Key`), **Then** el scan de auto-byok la **ignora** (exclusión load-bearing) para no sacar a
   Claude Code del passthrough de suscripción.
3. **Given** Copilot que manda `x-api-key` vacío e ignora el `apiKey` del config, **When** la key viaja
   en la URL (`?k=sk-basa-…`), **Then** el gateway la acepta como fallback y enruta a byok (atajo de demo;
   en prod la key entra por input seguro/SSO).
4. **Given** VS Code/Copilot en **modo Ask** con byok, **When** se procesa un prompt con PII, **Then** el
   masking/unmask completa correctamente.
5. **Given** VS Code/Copilot en **modo Agent** con un modelo **no-Claude**, **When** arranca el ciclo
   agéntico, **Then** el tool-calling se rompe (tool_use_failed) y VS Code rechaza el input UUID (→ 400):
   documentado como **limitación conocida** (superficie PARCIAL, sólo Ask), no como defecto a arreglar aquí.

---

### User Story 3 - Extensión de navegador MV3: mask/unmask sobre ChatGPT y Claude web (Priority: P1)

Un usuario instala la extensión **Basa Guard** (MV3) en su navegador y la conecta al gateway con una
virtual key. La extensión es la **superficie 2** (web apps sin base_url): un content script en el mundo
**MAIN** hookea `window.fetch`, y cuando el usuario envía un prompt a ChatGPT o Claude web, **intercepta el
body del request**, lo manda a `POST /gw/inspect` (fail-closed: sin key válida no deja pasar), reescribe el
body con los `replacements` que devuelve el gateway (de modo que **el modelo ve `[PERSON_0]`**, no la PII),
y **des-enmascara en el DOM** con un `MutationObserver` (`unmask` + `unmaskTitle`). La key la guarda el
**service worker**; el mundo MAIN **nunca la ve** (se comunica vía `bridge.js` en el mundo ISOLATED).
Adapters: **chatgpt** (`/backend-api/f/conversation`, `messages[].content.parts[]`) y **claude**
(`/chat_conversations/…` en `/completion` **y** `/title`). Cada inspección empuja su before/after al
**mismo monitor en vivo** con `surface="browser"` y deja auditoría metadata-only.

**Why this priority**: Es la superficie que cubre **web apps** (ChatGPT, Claude.ai) donde no hay
`ANTHROPIC_BASE_URL` que apuntar. Está **implementada y validada en vivo** (`basa-browser-dlp/`). Es P1
porque extiende el firewall a las superficies de chat que los usuarios usan a diario, con el **mismo**
monitor y la **misma** auditoría que las base_url. Materializa el Principio VIII (mismo pipeline
transparente) y la excepción del II (intercepta sin re-inyectar).

**Independent Test**: Instalar la extensión, conectar la key (validada contra `GET /gw/whoami`), abrir
ChatGPT web y mandar un prompt con un email y un nombre. Verificar: (a) el request que sale al backend de
ChatGPT lleva placeholders (`[EMAIL_ADDRESS_0]`, `[PERSON_0]`), no la PII; (b) la respuesta se muestra
des-enmascarada en el DOM; (c) sin key válida, la extensión es **fail-closed** (no deja enviar); (d) el
monitor muestra el evento con `surface="browser"`. Repetir en Claude.ai verificando que el **título** de
la conversación (endpoint `/title`) también se des-enmascara (`unmaskTitle`).

**Acceptance Scenarios**:

1. **Given** la extensión MV3 con la key conectada, **When** el usuario envía un prompt con PII en ChatGPT,
   **Then** el content script MAIN hookea `window.fetch`, manda el texto a `POST /gw/inspect` y reescribe
   el body con los `replacements`, de modo que el backend de ChatGPT recibe **placeholders**, no la PII.
2. **Given** la respuesta del modelo llegando al DOM, **When** el `MutationObserver` detecta cambios,
   **Then** `unmask(document.body)` restaura los valores reales usando los tokens exactos que devolvió el
   gateway; ningún placeholder crudo queda visible.
3. **Given** que la key vive en el service worker, **When** el content script MAIN opera, **Then** el mundo
   MAIN **nunca** ve la key (se habla con el service worker vía `bridge.js` en el mundo ISOLATED); sin key
   válida (validada contra `/gw/whoami`), la extensión es **fail-closed** y no deja enviar el prompt.
4. **Given** Claude.ai, **When** el cliente pide el **título** de la conversación (endpoint `/title` con el
   prompt crudo), **Then** el adapter `claude` cubre `/completion` **y** `/title`, y `unmaskTitle()`
   des-enmascara el `document.title` (cierra la fuga de título específica de Claude.ai).
5. **Given** cualquier inspección exitosa, **When** el gateway responde, **Then** empuja el before/after al
   monitor en vivo con `surface="browser"` y registra auditoría **metadata-only** (sin persistir el texto
   del prompt ni la PII cruda).

---

### User Story 4 - Matriz de compatibilidad + superficies no soportadas (Priority: P2)

El equipo (y cada cliente) necesita una **matriz de compatibilidad** honesta y versionada: para cada
herramienta, **qué funciona, cómo se engancha, y por qué** — incluyendo lo que **NO** funciona y su razón
técnica. La matriz distingue cuatro estados: **FUNCIONA** (Claude Code, ChatGPT web, Claude web),
**PARCIAL** (VS Code/Copilot: byok + key-in-URL, sólo modo Ask; **Cursor**: Override OpenAI Base URL
honrado sólo en el panel chat/plan, como Copilot Ask — el agente Composer no rutea por el endpoint
custom), **NO** (Gemini web: falta adapter — **viable** vía DOM-hook, roadmap), y **MCP-ONLY**
(Claude Desktop: sin `ANTHROPIC_BASE_URL` ni hook interceptable, sólo gobernable vía servidor MCP y
sólo en el **tool-plane**).

**Why this priority**: La constitución (Principio IV) manda documentar las herramientas **no compatibles**
(sin base URL o con red hostil). La matriz es el artefacto que le dice a cada cliente qué esperar antes de
onboardear, y evita prometer lo que no existe. Es P2 porque las superficies que FUNCIONAN (US1–US3) ya
entregan valor; la matriz es la **documentación de contrato** que las rodea.

**Independent Test**: Verificar que la matriz existe como tabla en la spec, cubre las 7+ herramientas con
su estado + mecanismo + razón, y que cada entrada "NO"/"MCP-ONLY" tiene una razón técnica concreta (no
"pendiente"). Confirmar que las entradas FUNCIONA/PARCIAL coinciden con el comportamiento observable de
US1–US3.

**Acceptance Scenarios**:

1. **Given** la matriz de compatibilidad, **When** se consulta Claude Code, **Then** figura como
   **FUNCIONA** (passthrough de suscripción, aguanta modo Agent) con el mecanismo `ANTHROPIC_BASE_URL` +
   `subscription-passthrough`.
2. **Given** VS Code/Copilot, **When** se consulta, **Then** figura como **PARCIAL** con la razón: byok +
   key-in-URL, **modo Ask obligatorio** (en Agent loopea porque los modelos no-Claude rompen el
   tool-calling y VS Code rechaza el input UUID → 400).
3. **Given** Cursor, **When** se consulta, **Then** figura como **PARCIAL** con la razón: honra el
   **Override OpenAI Base URL** (Settings→Models) sólo en el panel **chat/plan** (Cmd+L), como Copilot Ask;
   el **agente** (Composer), inline edit y autocomplete están clavados al backend de Cursor y NO rutean por
   el endpoint custom (y el "Override Anthropic Base URL" se auto-activa y rompe con **422**).
4. **Given** Claude Desktop, **When** se consulta, **Then** figura como **MCP-ONLY** con la razón: no expone
   `ANTHROPIC_BASE_URL` ni un hook interceptable; sólo gobernable vía un servidor MCP y sólo en el
   **tool-plane** (args/results de tools), no el chat.
5. **Given** ChatGPT web y Claude web, **When** se consultan, **Then** figuran como **FUNCIONA** vía la
   extensión MV3 (Claude web con la cobertura de la fuga de título).

---

### User Story 5 - Gemini web como extensión futura (adapter roadmap) (Priority: P3)

El equipo quiere extender la extensión MV3 a **Gemini web**. Hoy **NO** funciona, pero es **viable**:
faltan dos cosas concretas — el **host match** en el `manifest.json` (los content scripts sólo matchean
`chatgpt.com`, `chat.openai.com` y `claude.ai`) y el **adapter** en `basa-guard.js` (dónde vive el texto
del usuario en el request de Gemini y cómo leerlo/escribirlo). El endpoint de Gemini es `StreamGenerate`
(POST `batchexecute`, **no** WebSocket → fetch-interceptable) con el prompt enterrado en el parámetro
`f.req` (JSON anidado ofuscado, no documentado); por eso la recomendación es prototipar un **DOM-hook**
(editor Quill `.ql-editor`, como hacen las extensiones DLP existentes) antes que el fetch-hook (más
frágil) — requiere un **spike** en vivo. Esta story **documenta** el patrón para sumarlo — un nuevo
adapter `{ id, vendor, match, read, write }` + el host en `manifest.matches` — como **roadmap explícito**,
sin entregarlo.

**Why this priority**: Es la extensión natural de la superficie 2, pero es P3 porque las superficies
actuales ya cubren las web apps más usadas y sumar Gemini es **aditivo** (nuevo adapter + host, no un
mecanismo nuevo). La spec lo fija como roadmap para no venderlo como hecho (honestidad SDD).

**Independent Test**: Verificar que la spec documenta el patrón de extensión (nuevo adapter + host match)
y lo marca explícitamente como **NO implementado / roadmap**, con los dos gaps concretos nombrados (host
en `manifest.matches`, adapter en `basa-guard.js`). NO se exige código de Gemini en esta feature.

**Acceptance Scenarios**:

1. **Given** la spec, **When** se busca Gemini web, **Then** figura como **NO (roadmap)** con los dos gaps
   concretos: falta el host en `manifest.matches` y falta el adapter en `basa-guard.js`.
2. **Given** el patrón de adapters existente (`chatgpt`, `claude`), **When** se documenta sumar Gemini,
   **Then** se describe como aditivo: un nuevo adapter `{ id:"gemini", match, read, write }` + el host
   añadido a `manifest.matches`, sin tocar el mecanismo de mask/unmask.

---

### Edge Cases

- **Ask vs Agent en Copilot**: el masking/unmask completa en **modo Ask**; en **modo Agent** con modelo
  no-Claude el ciclo loopea/falla (`tool_use_failed`) y VS Code rechaza el input UUID (→ 400). La spec fija
  Ask como **modo soportado** para byok no-Claude; Agent queda documentado como no soportado en esa ruta.
- **Tool-calling agéntico no-Claude (`tool_use_failed`)**: los modelos que no son Claude rompen el
  protocolo de tool_use al pasar por el proxy con masking. Por eso **Copilot** queda **PARCIAL** (sólo Ask).
  **Cursor** también es **PARCIAL** por una razón afín pero más dura: su agente (Composer), inline edit y
  autocomplete ni siquiera rutean por el endpoint custom (clavados al backend de Cursor); sólo el panel
  **chat/plan** honra el Override OpenAI Base URL y es gobernable (como Copilot Ask).
- **Strip-tools NO habilita gobernar el agente**: quitar `tools` (o forzar `tool_choice:none`) en byok
  fuerza salida de texto, pero es un **mecanismo, no una estrategia**: degrada el agente a chat, puede
  romper la UI del cliente (que espera `tool_calls` estructuradas) y **no** evita tool-calls alucinadas si
  el cliente inyecta las tools en el **system prompt**. Preferible el modo **Ask/chat-plan nativo** al hack
  de `tool_choice`. Conclusión: strip-tools no convierte al agente no-Claude en superficie gobernable.
- **Fuga de título en Claude.ai**: Claude.ai llama un endpoint `/title` separado con
  `message_content` = el prompt **crudo**; si el adapter sólo cubriera `/completion`, el título filtraría
  PII. El adapter `claude` cubre **ambos** (`/completion` y `/title`) y `unmaskTitle()` des-enmascara el
  `document.title`.
- **Respuesta por WebSocket → unmask en DOM, no sobre transporte**: algunas web apps entregan la respuesta
  por WebSocket (no por el `fetch` hookeado), así que el des-enmascarado se hace **en el DOM** (vía
  `MutationObserver`), no interceptando el transporte de respuesta.
- **Artefactos en iframe no se des-enmascaran**: `all_frames:false` en el manifest → el content script no
  corre en iframes anidados, por lo que artefactos renderizados en un iframe **no** se des-enmascaran hoy
  (gap documentado; roadmap sería `all_frames:true` + control de superficie).
- **Body no firmado (ChatGPT/Claude)**: ChatGPT y Claude web **no** hacen integrity-check del body del
  request, así que aceptan el body **reescrito** (enmascarado) sin rechazarlo. Si una web app **firmara**
  el body, la reescritura vía `window.fetch` se detectaría y esta técnica no aplicaría a esa superficie.
- **Cap de inspección toma la COLA del último turno**: la inspección tiene un cap de longitud y toma el
  **final** del último turno del usuario; en un prompt agéntico gigante, un secreto al **inicio** podría
  quedar fuera del cap. Es una limitación conocida del muestreo (mitigable subiendo el cap o inspeccionando
  por turnos completos — roadmap).
- **Coexistencia passthrough vs byok en el mismo gateway**: si el scan de auto-byok **no** excluyera los
  `x-basa-*`, la `X-Basa-Key` de Claude Code (que trae `sk-basa-…` como atribución) lo sacaría del
  passthrough de suscripción y lo enrutaría a byok por error. La exclusión es **load-bearing** y tiene un
  test que la protege.
- **Key-in-URL es atajo de demo**: la key en `?k=sk-basa-…` viaja en la URL (potencialmente logueable);
  es un **fallback de demo** para Copilot. En prod la credencial entra por input seguro/SSO — la spec lo
  marca como tal para no normalizar la key en la URL.
- **User-Agent desconocido**: si el UA no matchea ninguna herramienta de `_TOOL_UA`, `tool_type` cae a
  "Desconocido"; la request **no** crashea y se audita con esa etiqueta (degradación honesta).

## Requirements *(mandatory)*

### Functional Requirements

**Claude Code — passthrough de suscripción (US1)**
- **FR-001**: El sistema MUST soportar el modo **`subscription-passthrough`** (013; "anthropic" en el demo)
  como reverse-proxy fiel a `api.anthropic.com` que reenvía la credencial del cliente (OAuth de suscripción)
  **verbatim**, de modo que la suscripción del cliente pague y Basa sólo firewallee.
- **FR-002**: El sistema MUST seleccionar el modo de upstream por el header `X-Basa-Upstream` (por
  request) y, en su ausencia, por el default de entorno `BASA_GW_UPSTREAM_DEFAULT` (porta la semántica del
  demo).
- **FR-003**: El sistema MUST reenviar **verbatim** los headers que Claude Code necesita para
  `api.anthropic.com` (`anthropic-version`, `anthropic-beta`, User-Agent, `x-app`) sin alterarlos (porta
  `_passthrough_headers`).
- **FR-004**: El sistema MUST detectar el `tool_type` desde el User-Agent (porta `_TOOL_UA`/`_detect_tool`;
  `claude` → "Claude Code") y degradar a "Desconocido" sin crashear cuando el UA no matchea.
- **FR-005**: Claude Code MUST figurar como superficie **FUNCIONA** que aguanta modo **Agent** (los modelos
  Claude mantienen el tool-calling a través del proxy con masking).

**Identidad por X-Basa-Key (transversal, US1/US2)**
- **FR-006**: El sistema MUST tratar `X-Basa-Key` como **identidad/atribución**, NO como credencial de
  upstream: resolver `key_hash` (sha256) → tenant/cliente/equipo (porta `_resolve_identity`) sin reenviar
  la key al upstream.
- **FR-007**: `X-Basa-Key` MUST estar **excluida** del scan de auto-byok y de los headers hop-by-hop (no
  viaja al upstream).

**VS Code / Copilot — auto-byok + key-in-URL (US2)**
- **FR-008**: El sistema MUST enrutar a **byok** por **auto-detección** cuando aparece una virtual key
  `sk-basa-…` (`_BASA_KEY_RE`) en **cualquier** header de auth, **sin** requerir el header de control
  `X-Basa-Upstream` (porta el auto-byok del demo).
- **FR-009**: El scan de auto-byok MUST **excluir** los headers `x-basa-*` (load-bearing: evita que la
  `X-Basa-Key` de Claude Code lo saque del passthrough de suscripción).
- **FR-010**: El sistema MUST aceptar la virtual key en la **URL** (`?k=sk-basa-…`) como fallback para
  Copilot (que manda `x-api-key` vacío, ignora el `apiKey` del config y no deja headers custom); MUST
  documentar que es un **atajo de demo** y que en prod la key entra por input seguro/SSO.
- **FR-011**: En modo **byok** el sistema MUST enrutar al motor LiteLLM con la key de Basa (cost tracking
  + budgets), a diferencia del passthrough de suscripción.
- **FR-012**: El sistema MUST documentar que VS Code/Copilot es superficie **PARCIAL**: masking/unmask
  soportado en **modo Ask**; en modo **Agent** con modelo no-Claude el ciclo falla (tool_use_failed / 400
  por input UUID). El **modo Ask** es el modo soportado para byok no-Claude.

**Extensión de navegador MV3 (US3)**
- **FR-013**: El sistema MUST proveer una extensión MV3 cuyo content script en el mundo **MAIN** hookea
  `window.fetch` para interceptar el body del request de las web apps soportadas (porta `basa-guard.js`).
- **FR-014**: La extensión MUST enmascarar el texto del usuario vía `POST /gw/inspect` y **reescribir** el
  body del request con los `replacements` devueltos, de modo que el modelo reciba **placeholders**
  (`[PERSON_0]`), no la PII.
- **FR-015**: La extensión MUST ser **fail-closed**: sin virtual key válida (validada contra
  `GET /gw/whoami`) NO deja enviar el prompt.
- **FR-016**: La extensión MUST des-enmascarar en el **DOM** con un `MutationObserver` (`unmask` +
  `unmaskTitle`), usando los tokens exactos devueltos por el gateway; MUST NOT depender de interceptar el
  transporte de respuesta (que puede ser WebSocket).
- **FR-017**: La key MUST vivir en el **service worker**; el content script del mundo MAIN MUST NOT verla
  nunca (comunicación vía `bridge.js` en el mundo **ISOLATED**).
- **FR-018**: La extensión MUST proveer adapters por web app: **chatgpt**
  (`/backend-api/f/conversation`, `messages[].content.parts[]`) y **claude** (`/chat_conversations/…`
  cubriendo `/completion` **y** `/title` para cerrar la fuga de título de Claude.ai).
- **FR-019**: `POST /gw/inspect` MUST empujar el evento al **mismo** monitor en vivo con `surface="browser"`
  y registrar auditoría **metadata-only** (sin persistir el texto del prompt ni la PII cruda).

**Matriz de compatibilidad + no soportados (US4)**
- **FR-020**: El sistema MUST publicar una **matriz de compatibilidad** (tabla en esta spec) con, por
  herramienta: estado (FUNCIONA / PARCIAL / NO / MCP-ONLY), mecanismo de enganche y razón técnica.
- **FR-021**: La matriz MUST documentar las superficies **parciales/no soportadas** con su razón concreta:
  **Cursor** = PARCIAL (honra el **Override OpenAI Base URL** sólo en el panel chat/plan, como Copilot Ask;
  el agente Composer/inline/autocomplete queda clavado al backend de Cursor y el "Override Anthropic Base
  URL" se auto-activa y rompe con 422); **Claude Desktop** = MCP-ONLY (sin `ANTHROPIC_BASE_URL` ni hook
  interceptable; sólo gobernable vía servidor MCP y sólo en el **tool-plane**); **Gemini web** = NO/roadmap
  (falta host match + adapter; **viable** vía DOM-hook, requiere spike).

**Gemini web futuro (US5)**
- **FR-022**: El sistema MUST documentar el patrón para sumar **Gemini web** como aditivo — un nuevo
  adapter `{ id:"gemini", match, read, write }` en `basa-guard.js` + el host en `manifest.matches` — y
  marcarlo explícitamente como **roadmap / NO implementado**.

**Transversal (onboarding + transparencia)**
- **FR-023**: Cada superficie soportada MUST modelarse como una `Connection`/`APIKey` (013) con su
  `tool_type` y `upstream_mode`; sumar o quitar una superficie soportada MUST ser **config + seed**, no
  código (Principio IV).
- **FR-024**: Todas las superficies (base_url y browser) MUST alimentar el **mismo** monitor/pipeline
  transparente (Principio VIII); la extensión con `surface="browser"`, las base_url con su surface propia.

### Key Entities *(include if feature involves data)*

- **Upstream mode (`upstream_mode`)** — *REUSA 013 / consumido desde el cliente*. `subscription-passthrough`
  (OAuth verbatim → suscripción paga, Basa firewallea) vs `byok` (motor LiteLLM con key de Basa → cost
  tracking/budgets). Seleccionado por `X-Basa-Upstream` o `BASA_GW_UPSTREAM_DEFAULT`.
- **Virtual key `sk-basa-…` (auto-byok)** — *REUSA gateway*. Detectada por `_BASA_KEY_RE` en cualquier
  header de auth (excepto `x-basa-*`) → enruta a byok + atribuye identidad. Fallback: key-in-URL
  (`?k=sk-basa-…`).
- **X-Basa-Key (identidad)** — *REUSA gateway*. Atribución (sha256 → tenant/cliente/equipo vía
  `_resolve_identity`), NO credencial de upstream; excluida del auto-byok y de hop-by-hop.
- **Tool detection (`_TOOL_UA`/`_detect_tool`)** — *REUSA gateway*. Mapea User-Agent → `tool_type`
  (claude→Claude Code, copilot→GitHub Copilot, vscode→VS Code, cursor→Cursor, …); default "Desconocido".
- **Basa Guard extension (MV3)** — *código PROPIO (a portar de `basa-browser-dlp/`)*. `manifest.json`
  (content scripts MAIN + ISOLATED, host_permissions, `all_frames:false`), `basa-guard.js` (hook
  `window.fetch` + mask vía `/gw/inspect` + unmask DOM), `bridge.js` (ISOLATED), `background.js` (service
  worker con la key).
- **Adapter (por web app)** — *código PROPIO*. `{ id, vendor, match(url), read, write }`: `chatgpt`
  (`/backend-api/f/conversation`, `parts[]`) y `claude` (`/completion` + `/title`). Gemini = roadmap.
- **`GET /gw/whoami`** — *REUSA gateway*. Valida la key → user/team (login del popup, fail-closed).
- **`POST /gw/inspect`** — *REUSA gateway*. Enmascara texto plano, devuelve `replacements`, empuja al
  monitor (`surface="browser"`) y audita metadata-only. Fail-closed sin key.
- **Matriz de compatibilidad** — *artefacto NUEVO (documentación)*. Tabla por herramienta:
  estado + mecanismo + razón. Consumida por onboarding (Principio IV).
- **Connection = APIKey (013)** — *REUSA*. `tool_type` + `upstream_mode` por herramienta; base del
  onboarding as data.

### Matriz de compatibilidad *(artefacto central de US4 — FR-020)*

| Herramienta | Superficie | Estado | Mecanismo de enganche | Razón / notas |
|---|---|---|---|---|
| **Claude Code** | base_url | **FUNCIONA** | `ANTHROPIC_BASE_URL` → `subscription-passthrough`; OAuth verbatim; identidad por UA + `X-Basa-Key` | Aguanta modo **Agent** (modelos Claude no rompen el tool-calling). Superficie titular. |
| **VS Code / GitHub Copilot** | base_url | **PARCIAL** | byok por **auto-byok** (`sk-basa-…`) + **key-in-URL** (`?k=…`); `x-api-key` vacío | Sólo **modo Ask**. En **Agent** loopea: modelos no-Claude rompen tool-calling y VS Code rechaza input UUID → 400. |
| **ChatGPT (web)** | browser | **FUNCIONA** | Extensión MV3, adapter `chatgpt` (`/backend-api/f/conversation`) | Body no firmado → acepta reescritura enmascarada. |
| **Claude (web)** | browser | **FUNCIONA** | Extensión MV3, adapter `claude` (`/completion` **y** `/title`) | Cubre la **fuga de título** (`unmaskTitle`). Respuesta por WebSocket → unmask en DOM. |
| **Gemini (web)** | browser | **NO (roadmap, viable)** | — | **Viable** vía **DOM-hook** (editor Quill `.ql-editor`); requiere **spike** en vivo. Endpoint `StreamGenerate` (POST `batchexecute`, **no** WebSocket → fetch-interceptable) con el prompt enterrado en `f.req` (JSON anidado ofuscado). Faltan **host match** (`manifest.matches`) + **adapter** en `basa-guard.js`; DOM-hook antes que fetch-hook (menor riesgo). Aditivo (US5). |
| **Cursor** | base_url | **PARCIAL** | **Override OpenAI Base URL** (Settings→Models) → gateway; honrado **sólo** en el panel **chat/plan** (Cmd+L) | Misma casilla que Copilot Ask: gobernable **sólo** en el modo sin-tools. El **agente** (Composer), inline edit y autocomplete están **clavados al backend de Cursor** y NO rutean por el endpoint custom; el "Override Anthropic Base URL" se auto-activa y rompe con **422** (no hay override Anthropic standalone usable). |
| **Claude Desktop** | desktop | **MCP-ONLY** | Servidor MCP (**tool-plane**) | Sin `ANTHROPIC_BASE_URL` ni hook interceptable. El MCP server sólo ve **args de tool-calls y results**, nunca el chat: gobierna el **tool-plane** (DLP/redaction sobre results con Presidio, audit de tool calls, elicitation, sampling), **no** el prompt del usuario ni las respuestas de Claude. Masking del chat = **gap conocido no cubrible hoy**. |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001 (passthrough de suscripción)**: En 100% de las requests en modo `subscription-passthrough`, el
  OAuth del cliente llega **verbatim** a `api.anthropic.com` (la suscripción paga) y Basa NO consume la
  credencial como propia; verificable inspeccionando el header reenviado.
- **SC-002 (coexistencia passthrough/byok)**: Con Claude Code (passthrough, trae `X-Basa-Key` con
  `sk-basa-…` de atribución) y Copilot (byok, trae `sk-basa-…` en `x-api-key`) sobre el **mismo** gateway,
  el 100% enruta correctamente: Claude Code queda en passthrough (la exclusión de `x-basa-*` lo protege) y
  Copilot va a byok. Test negativo: sin la exclusión, Claude Code se desviaría a byok.
- **SC-003 (auto-byok + key-in-URL)**: Copilot **sin** header de control y con `x-api-key` vacío enruta a
  byok por virtual key en la URL (`?k=…`) en el 100% de los casos; la identidad se atribuye
  (tenant/cliente), verificable en la auditoría.
- **SC-004 (masking en la extensión)**: En 100% de los prompts con PII enviados por la extensión, el body
  que sale al backend de la web app contiene **sólo placeholders** (0 PII cruda) y la respuesta se muestra
  des-enmascarada en el DOM (0 placeholders crudos visibles), incluido el **título** en Claude.ai.
- **SC-005 (fail-closed browser)**: 100% de los envíos desde la extensión **sin** virtual key válida se
  **bloquean** (no sale el prompt); la key nunca es accesible desde el mundo MAIN (verificable: el MAIN
  no tiene la key en su scope).
- **SC-006 (matriz honesta)**: La matriz de compatibilidad cubre ≥7 herramientas con estado + mecanismo +
  razón; el 100% de las entradas "NO"/"MCP-ONLY" tiene una **razón técnica concreta** (no "pendiente"), y
  las entradas FUNCIONA/PARCIAL coinciden con el comportamiento observable de US1–US3.
- **SC-007 (transparencia común)**: El 100% de las superficies soportadas (base_url y browser) alimenta el
  **mismo** monitor/pipeline; la extensión con `surface="browser"`; la auditoría es metadata-only en todas
  (0 texto de prompt / 0 PII cruda persistidos).
- **SC-008 (onboarding as data)**: Sumar o quitar una superficie **soportada** (una `Connection`/`APIKey`
  con su `tool_type`/`upstream_mode`) es **config + seed**; 0 cambios de código requeridos para onboardear
  una herramienta ya soportada (Principio IV).

## Assumptions

- **Depende del bedrock 013 y del port 014**: `Tenant`, `role="client"`, `client_type`, la Connection =
  APIKey con `tenant_id`/`tool_type`/`upstream_mode` (013), y el gateway/firewall al que apuntan estos
  clientes (014) ya existen. Esta spec los **consume** desde el lado cliente; no los re-diseña.
- **La evidencia viene del demo `gatelite-salud-eu`, no de `basa-guardian`**: los mecanismos
  (passthrough, auto-byok, key-in-URL, identidad, detección por UA, endpoints `/gw/whoami` y `/gw/inspect`)
  están **implementados y probados** en `gatelite-salud-eu/backend/src/api/gateway.py`; la extensión MV3
  en `basa-browser-dlp/`. Esta spec **porta** ese comportamiento a `basa-guardian` y lo versiona.
- **Reconciliación de vocabulario con 013 (`upstream_mode`)**: "anthropic" (demo) → `subscription-passthrough`
  (013); "byok" se mantiene. Se usan los valores del enum de 013 como fuente de verdad; "anthropic" queda
  como glosa histórica del demo (misma reconciliación que la 014).
- **Excepción del Principio II (GDPR-routing N/A)**: ya ratificada en la constitución y la 014 para la ruta
  `base_url` (y aplicable a la extensión, que intercepta sin re-inyectar). Esta spec la **reusa**, no la
  re-abre.
- **Key-in-URL es atajo de demo, no postura de prod**: se documenta como fallback para Copilot; en prod la
  credencial entra por input seguro/SSO. La spec no normaliza la key en la URL como práctica productiva.
- **Ask como modo soportado para byok no-Claude**: se asume que el modo Ask (Copilot) / chat-plan (Cursor)
  es el modo de trabajo soportado para clientes no-Claude en byok; el modo Agent con modelos no-Claude
  queda fuera de soporte por la ruptura del tool-calling (limitación del modelo/cliente, no del gateway).
  **Strip-tools no es la vía**: quitar `tools`/`tool_choice:none` es un mecanismo que fuerza texto pero
  degrada el agente a chat, rompe la UI que espera `tool_calls` y no frena tool-calls inyectadas por
  system prompt; se prefiere el modo Ask/chat-plan nativo (ya resuelto) — strip-tools **no** habilita
  gobernar el agente.
- **`all_frames:false` y cap de inspección son limitaciones conocidas**: artefactos en iframe no se
  des-enmascaran hoy, y el cap de inspección muestrea la cola del último turno; ambos son gaps documentados,
  mitigables en roadmap (no son defectos a corregir en esta feature).
- **Claude Desktop = MCP-only (alcance tool-plane)**: se asume que Claude Desktop no expone
  `ANTHROPIC_BASE_URL` ni un hook interceptable; su gobernanza vía servidor MCP es otra spec (aquí sólo se
  documenta el estado en la matriz). El alcance de MCP es el **tool-plane**: DLP/redaction sobre **results**
  de tools (Presidio), audit de tool calls, elicitation (confirmaciones) y sampling (clasificar sin API
  key); un MCP server **nunca** ve la conversación ni el prompt del usuario, así que enmascarar lo que el
  usuario teclea o las respuestas de Claude es un **gap conocido no cubrible** por esta vía.
- **Gemini web = roadmap (viable, requiere spike)**: sumar Gemini es aditivo (adapter + host match) y
  **viable** vía DOM-hook (editor Quill `.ql-editor`); el endpoint `StreamGenerate`/`batchexecute` es
  fetch-interceptable pero el prompt va ofuscado en `f.req`, por lo que el DOM-hook es la ruta de menor
  riesgo — requiere un spike en vivo. Esta spec lo documenta como no implementado para no venderlo como
  hecho (honestidad SDD).
