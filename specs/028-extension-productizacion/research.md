# Research (Fase 0): Productización de la extensión de navegador (028)

Insumo primario: **issue #46** (brief de handoff). Este documento registra lo **verificado contra el código** de `dev-fran` (2026-07-24), que corrige varios supuestos del brief — sobre todo cuánto del lado servidor ya lo dejó hecho la 027.

## D1 — Modelo de conexión: URL la pone el usuario, sin CORS, con permiso de host en runtime

**Decisión (JF, revierte el brief):** el paquete hornea solo la marca; la URL + key las ingresa el usuario (editable, agnóstica, default opcional); el acceso al host se concede en tiempo de ejecución con `optional_host_permissions`.

**Por qué funciona sí o sí (verificado):** el único componente que hace fetch al gateway es el **service worker** — [`extension/background.js:2`](../../extension/background.js) lo dice explícito: *"Único que habla con el gateway (tiene host_permissions → sin CORS)"*. El content script `guardia-main.js` (MAIN, reescribe el HTML al enmascarar/desenmascarar) **no** hace fetch: manda el texto por `postMessage` → `bridge.js` (ISOLATED) → `chrome.runtime` → SW → `fetch(/inspect|/whoami)`. Un fetch del SW a un host con permiso **no pasa por CORS**. Conclusión: no hay CORS que resolver, no hace falta microservicio/proxy; el único portón es el permiso de host.

**El problema real de hoy:** `manifest.json` clava `host_permissions: ["http://localhost:8091/*"]`. La URL del popup es editable pero es "libertad falsa": el SW no alcanza ningún otro host. `optional_host_permissions` + `chrome.permissions.request({origins})` en el gesto de "Conectar" lo resuelve (prompt nativo, una vez por host). Patrón MV3 estándar y privacy-preserving.

**Alternativas descartadas:** (a) `host_permissions` amplio / `<all_urls>` — mala postura de seguridad, review de la tienda lo marca; (b) hornear la URL por deploy (modelo del brief) — reintroduce dependencia de conocer la URL al empaquetar, que es justo lo que JF quiere evitar; (c) microservicio/proxy server-side — no cambia el modelo de permisos del navegador, no resuelve nada.

## D2 — La 027 ya implementó el lado servidor de los bloqueos (US5)

Verificado en [`backend/src/api/inspect.py`](../../backend/src/api/inspect.py):
- `gw_inspect` (líneas 148+) arma un body sintético y pasa el texto del navegador por la **misma** `evaluate_request_policy` que el passthrough (AI-Act → secretos → detección PII → enmascarado). Fix P4 de la 027.
- Responde `ok:false` + `blocked` + `blocked_by_layer` + `motivo` en un bloqueo (contrato en `specs/027-.../contracts/api-gobernanza.md`, sección "Bloqueo en /gw/inspect").
- El `motivo` sale de un **catálogo cerrado** local (`_MOTIVO_POR_CAPA`, inspect.py:52-74): sin nombres de proveedor, sin el `block_reason` que enumera tipos de secreto, sin el texto inspeccionado (garantía C1).

**Implicación:** US5 **server = HECHO**. Solo falta el lado extensión: parsear `blocked`/`motivo` y mostrar el `motivo` del server (hoy `basa-guard.js:115-118` solo bloquea con `!res.ok` y muestra un texto genérico). Extensiones viejas siguen fail-closed (bloquean con su error genérico); las nuevas distinguen y muestran el motivo. Sin skew fail-open.

## D3 — US4 (chip de honestidad): falta el bloque `proteccion` en `whoami`

Verificado: `gw_whoami` (inspect.py:134-145) devuelve solo `{ok, user, team, key_label}` — **no** trae protección. Hay que agregar un bloque `proteccion` calculado server-side.

- La regla: plano `gateway` + `pii_detection.requires_service is None` ⇒ `deteccion="patrones"`. Verificado que `requires_service` **hoy está vacío** para todo el catálogo ([`governance_status.py:309-311`](../../backend/src/services/governance_status.py)) → en el piloto siempre es "patrones". El día que el sidecar NLP declare `requires_service`, el mismo cálculo da "linguistico" sin tocar la extensión.
- El copy sale de una **fuente única**: `_PISO_SIGUE` de `governance_status.py:87`. La extensión **no** hardcodea el texto (FR-016).
- `capas_delegadas`: en modo suscripción, las capas delegables (moderación, prompt-injection) se reportan `delegated`, no "desprotegido" (ya en la lógica de 027).

**Implicación:** US4 server = pequeño (un bloque nuevo en whoami, reusando `governance_status`). US4 extensión = chip ámbar.

## D4 — Superficie de navegador: no existe en el enum (US9 diferido)

`SURFACES` = `("claude-code","copilot","cursor","claude-desktop","chatgpt","chat-ui")` ([`basa_governance.py:94`](../../litellm/extensions/basa_governance.py)) — **sin valor de navegador**. `_superficie()` (inspect.py:117-131) devuelve `"desconocido"` para el tráfico de la extensión. Agregar `chatgpt-web`/`claude-web` es 2 líneas + migración del `CHECK tool_type` (budget.py:89) + aviso a Cristian **antes del freeze de la 027** (reabre contrato después). **Diferido (US9, fast-follow)** por decisión de alcance del piloto: el tráfico se audita "desconocido", no bloquea nada. Coordinación humana, no código de la 028.

## D5 — US8: expiración sí, filtro por superficie depende de US9

`_resolve_attribution` (gateway.py:356) filtra `key_hash == hash AND is_active` — **ignora `expires_at`** (existe en budget.py:52). Sumar `expires_at IS NULL OR expires_at > now()` es la parte real de US8 y da el offboarding por vencimiento (valor con key-por-usuario). La otra mitad ("rechazar key cuya superficie no sea navegador") **depende de que exista un `tool_type` de navegador** (US9) — sin él no hay cómo distinguir; se difiere junto con US9.

## D6 — Empaquetado por partner: hermano de `render_docs_brand`, solo marca

`deploy/release/render_docs_brand.sh` es el patrón. El nuevo `render_extension_brand.sh` deriva del brand-pack **solo** identidad visible (nombre, descripción, íconos) + genera/embebe el `manifest.key` para **ID estable** (par RSA por partner, pública base64 en `manifest.key`, privada fuera del repo). **No** hornea URL. El zip entra a `bundle.sh` + MANIFEST con sha256. Excepción documentada al "config+seed, nunca fork": la extensión es el único artefacto horneado por partner porque Chrome lee `name/description/icons` del manifest del paquete, no de runtime.

## D7 — Gate de white-label (US7): la lista de prohibidos no tiene "basa"

`deploy/release/checks/prohibited_names.txt` = `litellm/berriai/presidio` — **sin `basa`**. El gate actual escanea `/srv` del frontend y `deploy/branding/`, no la extensión. `test_extension_whitelabel.sh` nuevo: descomprime el zip renderizado y falla ante `prohibited_names.txt` **+** una lista de marca del fabricante (`basa`, `basa guard`, `PoC`, `localhost`). `make check-whitelabel` lo invoca.

## Resumen: dónde está el trabajo real de la 028

| US | Server | Extensión | Estado |
|----|--------|-----------|--------|
| US1 marca+bundle | — | render_extension_brand.sh + manifest.key + bundle | NUEVO |
| US2 conexión | — | optional_host_permissions + request en Conectar + https + default editable | NUEVO |
| US3 white-label | — | (deriva de US1) | NUEVO |
| US4 honestidad | bloque `proteccion` en whoami (chico) | chip ámbar | NUEVO (chico+ext) |
| US5 bloqueos | **HECHO (027)** | parsear `blocked`/`motivo`, mostrar motivo | solo ext |
| US6 sesión | — | 401≠403≠sin-red, chrome.alarms 30min, dueño único SW | NUEVO |
| US7 gate | check nuevo + lista marca fabricante | — | NUEVO (deploy) |
| US8a expiración | filtro `expires_at` en _resolve_attribution | — | NUEVO (chico) |
| US8b/US9 superficie | difer. (enum+migración+Cristian) | — | DIFERIDO |

**Conclusión:** la 028 es **mayormente trabajo de extensión** + dos añadidos server chicos (whoami proteccion, filtro expires_at). El grueso server de bloqueos ya lo trajo la 027. Buen augurio para el martes.
