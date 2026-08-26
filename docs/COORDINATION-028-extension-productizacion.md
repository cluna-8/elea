# COORDINATION 028 — Productización de la extensión de navegador

**Orquestador**: Claude (srdev-claude). **Rama feature**: `028-extension-productizacion` (worktree base desde `dev-fran` @ ca3725b + specs).
**Deadline**: install del piloto Cámara **martes 28-jul**. **Regla dura**: NUNCA commit directo a `dev-fran`/`main`. Cada minion trabaja en su worktree y su rama; el orquestador integra a la rama feature y verifica antes de PR.

Artefactos SDD (fuente de verdad, ya escritos y commiteados): [spec.md](../specs/028-extension-productizacion/spec.md) · [plan.md](../specs/028-extension-productizacion/plan.md) · [tasks.md](../specs/028-extension-productizacion/tasks.md) · [research.md](../specs/028-extension-productizacion/research.md) · [contracts/whoami-proteccion.md](../specs/028-extension-productizacion/contracts/whoami-proteccion.md).

`speckit-analyze` corrió limpio: 27/28 FR cubiertos (FR-028 diferido a fast-follow, documentado), 0 CRITICAL/HIGH, constitución OK.

---

## Context

La extensión MV3 (superficie navegador: **Claude + ChatGPT**; Gemini fuera de alcance) ya intercepta `window.fetch`, enmascara PII vía `/gw/inspect` y hace fail-closed. Lo nuevo de la 028:

1. **Entregable white-label** (US1/US3/US7): un comando produce `extension-<slug>.zip` con la marca del partner (sin URL horneada), viaja en el bundle, y un gate impide que se re-filtre la marca del fabricante.
2. **Conexión agnóstica** (US2): la URL la ingresa el usuario y **funciona de verdad** vía `optional_host_permissions` (hoy el host está clavado en `localhost:8091` → "libertad falsa").
3. **Honestidad** (US4): chip ámbar "Detección por patrones · cobertura parcial", texto del server.
4. **Bloqueos** (US5): mostrar el `motivo` real del server (027 ya lo devuelve), no "servicio no disponible".
5. **Sesión** (US6): distinguir sin-red de sin-permiso, revalidar sola, un único dueño del estado.
6. **Backend chico** (US4 server + US8a): `proteccion` en `whoami` + filtro `expires_at`.

El grueso del lado servidor de bloqueos (US5) **ya lo trajo la 027** (`gw_inspect` devuelve `{ok:false, blocked:true, blocked_by_layer, motivo}` con catálogo cerrado). Ver `backend/src/api/inspect.py:197-208`.

## Locked design decisions (confirmadas por JF — no re-litigar)

- **URL la pone el usuario** (editable, agnóstica, default opcional pre-cargable), NO horneada. Revierte el brief #46.
- **`optional_host_permissions` + `chrome.permissions.request({origins})`** en el gesto Conectar → el host se concede en runtime. El SW (que tiene el permiso) hace el fetch → **sin CORS, sin microservicio**. Revierte el brief #46.
- **HTTPS obligatorio** para URL remota; `http` solo local.
- **White-label**: cero marca del fabricante en el zip del partner. Nombre publicado de la extensión de Cámara = **`cc-guardian`** (aprobado por JF).
- **Gemini**: fuera (fast-follow). **FR-028** (rechazo por superficie navegador): diferido (falta enum de navegador, coord con Cristian).
- **Hardening #45 NO se regresa**: el mapa token→PII vive en el closure (nunca `window`/DOM/`document.title`); handshake de nonce bridge↔MAIN; enmascarado no desactivable; la key no se persiste ni re-inyecta antes de validar.

## Architecture summary

`guardia-main.js` (MAIN, hookea fetch, enmascara/desenmascara el DOM) → `postMessage` → `bridge.js` (ISOLATED, relay con nonce) → `chrome.runtime` → `background.js` (service worker, **único que fetchea el gateway** → host_permissions → sin CORS). `config.js` tiene el default de URL. `popup.html/js` = login (URL + key). Backend: `/gw/whoami` (login) y `/gw/inspect` (masking + bloqueo), ambos con `_resolve_attribution` (fail-closed).

---

## Minion roster (Wave 1 — paralelo, CERO solape de archivos)

| Minion | Track | Archivos que POSEE | Rama |
|--------|-------|--------------------|------|
| **A — Backend** | US4 server + US8a | `backend/src/api/inspect.py`, `backend/src/api/gateway.py`, `backend/tests/contract/test_whoami_proteccion.py` (NUEVO), `backend/tests/unit/test_api_key_expiry.py` (NUEVO) | `028-backend` |
| **B — Extensión** | US2+US3(fuente)+US4(chip)+US5+US6 | **todo `extension/`**: `manifest.json`, `background.js`, `guardia-main.js`, `popup.js`, `popup.html`, `config.js`, `README.md` (NO `bridge.js` salvo lo indicado) | `028-extension` |
| **C — Deploy** | US1+US3(render)+US7 | `deploy/release/render_extension_brand.sh` (NUEVO), `deploy/release/bundle.sh`, `deploy/release/checks/test_extension_whitelabel.sh` (NUEVO), `deploy/release/checks/test_airgapped_bundle.sh`, `deploy/release/checks/prohibited_brand.txt` (NUEVO), `deploy/Makefile`, `deploy/clients/camara-comercio/brand.extension.json` (NUEVO) | `028-deploy` |

**Verificación de cero solape**: A=solo `backend/`, B=solo `extension/`, C=solo `deploy/`. Ningún archivo compartido. ✅

---

## Cross-minion contract (CRÍTICO — leer aunque no sea tu sección)

El zip del partner lo **arma Minion C** sustituyendo marca en una COPIA de `extension/`. Para que el gate white-label (US7) pase sobre esa copia, B y C acuerdan:

### Qué campos de `manifest.json` son "marca" (los sustituye el render de C)
- `name`, `description`, `action.default_title`, `icons`, `action.default_icon`.
- C los toma de `brand.extension.json` (`name`, `description`, íconos). **El source de B puede seguir diciendo "Basa Guard" en esos campos** — el render los pisa.

### Qué debe neutralizar B en el SOURCE (porque el render NO los toca y viajan en el zip)
1. **`config.js`**: el default de URL **NO puede ser `http://localhost:8091/...`** (el gate prohíbe `localhost`). Dejar `GATEWAY_URL: ""` (vacío, editable) o un placeholder `https://` neutro. Pre-cargable con la URL de Cámara vía brand, pero por defecto vacío.
2. **`*.js` (guardia-main.js, background.js, popup.js)**: quitar el literal **"Basa Guard"** de `console.log`/comentarios visibles → usar un string neutro (p.ej. `"[guardia]"`) o leerlo de `chrome.runtime.getManifest().name`. Los **identificadores internos** (`__BASA_GUARD__`, `BASA_CONFIG`, `basa_key`, `basa_gateway`, `basa_connected`, `X-Basa-Key`, prefijos `__basa_*`) **se conservan** — no son texto visible; van en la allowlist del gate (como `litellm_params`/`presidio` en el gate de la UI).
3. **`README.md`**: **NO viaja en el zip** (C lo excluye). B lo neutraliza igual por higiene de repo, pero no es un bloqueante del gate.

### Qué NO ship-ea el render de C en el zip
Solo runtime: `manifest.json`, `background.js`, `bridge.js`, `guardia-main.js`, `popup.html`, `popup.js`, `config.js`, `icons/`. **NO** `README.md` ni nada de dev.

### Allowlist del gate (C la implementa siguiendo el patrón de `test_no_engine_name.sh`)
Denylist fabricante: `basa`, `basa guard`, `poc`, `localhost`, + `prohibited_names.txt` (motor). Allowlist de identificadores internos (word-exact): `__BASA_GUARD__`, `BASA_CONFIG`, `basa_key`, `basa_gateway`, `basa_connected`, `basa_user`, `basa_team`, `X-Basa-Key`, `__basa`, `__basa_nonce`.

---

## Minion A — Backend (US4 server + US8a)

**Rama base**: `028-extension-productizacion`. **Tu rama**: `028-backend`. Worktree: te lo asigna el orquestador (cd ahí).

### Tareas
1. **US4 server (T016)** — `backend/src/api/inspect.py`, función `gw_whoami` (líneas 134-145): agregar un bloque `proteccion` a la respuesta. Contrato exacto: [contracts/whoami-proteccion.md](../specs/028-extension-productizacion/contracts/whoami-proteccion.md).
   - `proteccion.deteccion` = `"patrones"` (regla: plano gateway + `pii_detection.requires_service is None`; hoy `requires_service` está vacío → siempre `"patrones"`. Ver `backend/src/services/governance_status.py:309-311`).
   - `proteccion.titulo` = `"Detección por patrones"`.
   - `proteccion.detalle` = texto en lenguaje llano que **termina con el literal `_PISO_SIGUE`** (`governance_status.py:87`) — importalo, no lo copies a mano (fuente única de copy).
   - `proteccion.capas_delegadas` = las capas delegables en suscripción (moderación, prompt-injection). Si hay un helper en `governance_status`, reusalo; si no, lista mínima explícita `["content_moderation", "prompt_injection"]` con un comentario de por qué.
   - **NUNCA** nombres de motor/tecnología en ningún campo (C1 / Constitución VII). Vocabulario cerrado.
2. **US8a (T024)** — `backend/src/api/gateway.py`, `_resolve_attribution` (línea 355-357): sumar al filtro `expires_at IS NULL OR expires_at > now()`. Usá `datetime.now(timezone.utc)` (ya importados en `gateway.py:65`) o `func.now()` — lo que sea consistente con el estilo del archivo. Efecto: una key vencida cae al fallback anónimo (`api_key_id = None`), y `gw_whoami`/`gw_inspect` responden el **mismo 401 indistinguible** que una key inexistente (sin oráculo).

### Tests (required)
- **`backend/tests/contract/test_whoami_proteccion.py`** (NUEVO — escribir primero, debe fallar contra el código actual):
  - Setup: cliente FastAPI con una key válida (mirá `test_governance_status_contract.py` / `conftest.py` para el harness de key/tenant).
  - Assert `resp.json()["proteccion"]["deteccion"] == "patrones"`.
  - Assert `resp.json()["proteccion"]["detalle"].endswith(_PISO_SIGUE)` (importá `_PISO_SIGUE` de `governance_status`).
  - Assert que NINGÚN campo de `proteccion` contiene los substrings `"presidio"`, `"regex"`, `"litellm"` (case-insensitive) — regresión anti-fuga de motor.
  - Assert `proteccion.titulo == "Detección por patrones"`.
- **`backend/tests/unit/test_api_key_expiry.py`** (NUEVO):
  - **Repro (falla antes del fix)**: insertá una `APIKey` con `is_active=True` y `expires_at` en el pasado → `_resolve_attribution(key)` devuelve `api_key_id is None` (rechazada). Antes del fix devolvía el id (aceptada) → este test lo prueba.
  - Regresión: una key con `expires_at=None` sigue resolviendo (aceptada). Una key con `expires_at` futuro sigue resolviendo.
  - Indistinguibilidad: `gw_whoami` con key vencida devuelve status 401 y el MISMO cuerpo `{"ok": False, "error": ...}` que con una key inexistente (sin campo que revele "vencida").

### Reglas duras
- No `any`-equivalente (no `dict` sin forma donde se pueda tipar), no `except: pass`, no texto de motor en respuestas de cliente.
- No tocar la lógica de `gw_inspect` (el bloqueo ya está hecho por 027) salvo que un test lo exija.

### Verificación local (correr ANTES de reportar done)
```bash
# desde tu worktree, backend corriendo en el compose de dev o vía el runner del repo:
cd backend && python -m pytest tests/contract/test_whoami_proteccion.py tests/unit/test_api_key_expiry.py -q
# y no romper lo existente en esos módulos:
python -m pytest tests/contract/test_governance_status_contract.py tests/unit -q
```
Si el backend necesita Postgres, usá el patrón del repo (docker compose del stack basa; ver `conftest.py`). Reportá el output real.

### Reportá: rama, archivos cambiados, output de pytest (conteo pass/fail), blockers.

---

## Minion B — Extensión (US2 + US3 fuente + US4 chip + US5 + US6)

**Rama base**: `028-extension-productizacion`. **Tu rama**: `028-extension`. Worktree asignado por el orquestador.

Leé **Cross-minion contract** arriba: sos responsable de neutralizar `config.js` (sin `localhost`), los `console.log`/comentarios "Basa Guard" de los `.js`, y `README.md`.

### US2 — Conexión agnóstica que funciona (FR-008..FR-012)
- **`manifest.json`**: reemplazar `"host_permissions": ["http://localhost:8091/*"]` por **`optional_host_permissions`** con un patrón que cubra hosts https/http (p.ej. `["https://*/*", "http://*/*"]` — el permiso real se concede por host en runtime, esto solo declara que PODEMOS pedirlo). Mantener `"permissions": ["storage"]` y agregar lo que haga falta (`"alarms"` para US6). content_scripts SIN cambios (chatgpt/claude; Gemini fuera).
- **`background.js`** (SW, único dueño): en el mensaje de conectar (whoami con key nueva), antes de fetchear, pedir permiso del host ingresado: `chrome.permissions.request({ origins: [origin + "/*"] })`. Si el usuario deniega → responder un error claro tipo `{ ok:false, error:"permiso_denegado" }` (no fallo silencioso). El SW lee el host de `storage` para el fetch. Cambiar de host → volver a pedir permiso (comparar contra `chrome.permissions.contains`).
- **`config.js`**: `GATEWAY_URL` default **vacío** (o placeholder https neutro), editable. Reescribir el comentario "tocar DOS cosas" — ya no aplica (el host se concede por permiso en runtime, no por editar `host_permissions`).
- **Validación (FR-010)**: rechazar URL remota que no sea `https`; permitir `http` solo si el host es local (`localhost`/`127.0.0.1`). Mensaje claro. Esto va en `popup.js` (al guardar) y/o `background.js`.
- **`popup.js`/`popup.html`**: el input de URL ya existe; asegurar que el flujo Conectar dispare el request de permiso y muestre el mensaje si se deniega.

### US4 — Chip de honestidad (FR-013..FR-017)
- El SW ya recibe `whoami`; pasar el bloque `proteccion` de la respuesta al popup y al panel.
- **`popup.js`/`popup.html`**: mostrar un chip **ámbar** (no verde) con `proteccion.titulo` + " · cobertura parcial" y `proteccion.detalle` (texto del server). **Nunca** la palabra "protegido" en verde.
- **`guardia-main.js`**: el panel flotante debe reflejar el mismo chip ámbar desde `proteccion` (viaja en el `state` por el bridge, o pedirlo). **Fallback**: si `proteccion` falta (backend viejo) → asumir `"patrones"` con un `detalle` mínimo genérico, **nunca** "linguistico"/verde. **No hardcodear** el `detalle` (debe venir del server cuando está).
- Coordinación con Minion A: el shape lo define [contracts/whoami-proteccion.md](../specs/028-extension-productizacion/contracts/whoami-proteccion.md). Programá contra ese contrato + fallback.

### US5 — Motivo real de bloqueo (FR-018..FR-020)
- **`guardia-main.js`**, en el hook de fetch tras `callBridge("inspect", …)`: hoy trata cualquier `!res.ok` como "gateway no disponible" (línea 125-128). Distinguir:
  - `res.blocked === true` (con `res.motivo`) → frenar el envío y mostrar **`res.motivo`** (texto del server) en el overlay/mensaje de bloqueo.
  - `res.ok === false` **sin** `blocked` → mostrar "servicio no disponible" (comportamiento actual).
  - **Nunca** renderizar `res.blocked_by_layer` crudo.
  - Conservar el fail-closed actual para respuestas viejas (un `ok:false` sin `blocked` sigue bloqueando).
- El SW (`background.js`) hoy en `inspect` solo devuelve `{ok, masked, replacements, entities, user, team}` (línea 42-46): **propagá también `blocked`, `blocked_by_layer`, `motivo`** de la respuesta del gateway hacia el content script, para que `guardia-main.js` pueda distinguir. (Sin esto, el MAIN nunca ve el motivo.)

### US6 — Sesión (FR-021..FR-025)
- **`background.js`** dueño único del estado. Tres estados:
  - `conectado` (whoami ok).
  - `no_verificado` (fallo de RED — `fetch` throw / sin respuesta): **conservar la key**, marcar el estado, reintentar solo cuando vuelva la red.
  - `desconectado` (401 **o** 403): **borrar la key**. 403 = "tu plaza ya no está activa" (mensaje distinto); 401 = "key inválida". (El backend hoy devuelve 401 para vencida/inválida; si 403 no aplica aún, dejá el branch listo y usá el 401 para key inválida — no inventes un 403 que el server no manda. Documentá el mapeo.)
  - Un corte de red **NO** borra la key (FR-023).
- **Revalidación (FR-024)**: `chrome.alarms` cada ~30 min + `chrome.runtime.onStartup` → re-whoami. **No** keepalive artificial (el SW MV3 ya es correcto).
- **Dueño único (FR-025)**: el SW escribe `basa_connected`/estado; **`popup.js` deja de escribir `basa_connected`** (solo lee/observa vía `chrome.storage.onChanged`). Hoy `popup.js` no escribe `basa_connected` directamente (lo hace el SW) — verificá y, si el disconnect del popup escribe estado, muévelo al SW o a un mensaje al SW.

### Reglas duras (hardening #45 — NO regresar)
- El mapa `S.tok2val` (token→PII) sigue SOLO en el closure. No exponerlo en `window`, DOM ni `document.title`.
- No re-inyectar la key en el input; no persistirla antes de validar.
- Mantener el handshake de nonce bridge↔MAIN.
- El enmascarado NO es desactivable (sin toggle de usuario).
- No romper los adapters de ChatGPT/Claude ni el fail-closed por body no-inspeccionable (F4).

### Tests / verificación
La extensión MV3 **se verifica viva en Chrome** (la corre el orquestador con Playwright/carga manual contra un gateway real). Vos garantizá:
- `node --check` sobre cada `.js` (sintaxis).
- `python3 -c "import json,sys; json.load(open('extension/manifest.json'))"` (manifest válido).
- Un checklist en tu reporte: por cada US, qué archivo/línea la implementa y cómo se prueba viva.
- **No** inventes unit tests de DOM que no corren; si querés, un smoke de las funciones puras (validación de URL https) en un `.mjs` con `node --test` es bienvenido pero opcional.

### Reportá: rama, archivos cambiados, salida de `node --check` + validación de manifest, checklist US→archivo, blockers.

---

## Minion C — Deploy / packaging (US1 + US3 render + US7 gate)

**Rama base**: `028-extension-productizacion`. **Tu rama**: `028-deploy`. Worktree asignado por el orquestador.

Leé **Cross-minion contract** arriba. Patrón de referencia: `deploy/release/render_docs_brand.sh` (mismo estilo python-in-bash) y el gate `deploy/release/checks/test_no_engine_name.sh` (allowlist con `grep -viE`).

### T001 — `deploy/clients/camara-comercio/brand.extension.json` (NUEVO)
Fuente de la identidad de la extensión de Cámara. Mínimo:
```json
{
  "name": "cc-guardian",
  "description": "Protege los datos personales antes de enviarlos a asistentes de IA. Tu organización define qué se enmascara y registra el uso.",
  "icons": { "16": "icons/icon-16.png", "48": "icons/icon-48.png", "128": "icons/icon-128.png" }
}
```
(`description` ≤132 chars, sin "PoC"/motor/localhost/fabricante. Íconos: por ahora reusá los de `extension/icons/` como placeholder del partner — son escudos genéricos sin marca; documentá que el partner puede reemplazarlos.)

### T004/T005 — `deploy/release/render_extension_brand.sh` (NUEVO)
`render_extension_brand.sh <slug> <brand.extension.json>`:
- Copia `extension/` a `deploy/clients/<slug>/rendered/extension/` **incluyendo SOLO runtime** (`manifest.json`, `*.js`, `config.js`, `icons/`) — **excluí `README.md`** y cualquier dev-only.
- Sustituye en el `manifest.json` de la copia: `name`, `description`, `action.default_title` (= `name`), `icons`, `action.default_icon` desde el brand-pack. **NO** hornea ninguna URL de gateway.
- **`manifest.key`** (T005): embebe una clave pública base64 para un **ID de extensión estable** entre carpetas. Generá el par RSA por partner (T002): pública→manifest, privada→**fuera del repo** (misma custodia que las claves de licencia; documentá dónde). Para no bloquear, si no hay par provisto, generalo determinísticamente-por-slug NO (debe ser estable y secreta la privada) — mejor: generá el par, guardá la pública en el render y escribí la privada a un path fuera del repo (`deploy/clients/<slug>/secrets/extension_key.pem`) con aviso de que va a la custodia. Documentá en el output.
- Emite `extension-<slug>.zip` (zip de la carpeta `rendered/extension/`).
- Versión (T008): fuente única = `manifest.version`. No dupliques versión en ningún otro lado del render.

### T006 — `deploy/Makefile`
Target `build-extension-brand` que invoca el render: `make -C deploy build-extension-brand BRAND=camara-comercio`. Enganchá el gate white-label de la extensión en `check-whitelabel` (o un `check-extension-whitelabel` nuevo sumado a `check`).

### T007 — `deploy/release/bundle.sh` + `test_airgapped_bundle.sh`
- `bundle.sh`: incluir `extension-<slug>.zip` en el bundle y listarlo en el `MANIFEST` con su **sha256**. (Ver cómo arma el MANIFEST hoy, líneas ~40-46: agregá una línea para el zip con `sha256sum`.)
- `checks/test_airgapped_bundle.sh`: verificar que el zip de la extensión está presente en el bundle y su sha256 coincide con el MANIFEST.

### T009/T010 — Gate white-label de la extensión (US7)
- `deploy/release/checks/prohibited_brand.txt` (NUEVO): lista de marca del fabricante — `basa`, `basa guard`, `poc`, `localhost`. (Separada de `prohibited_names.txt`, que es motor y la comparten UI/docs — NO metas "basa" ahí, rompe esos gates.)
- `deploy/release/checks/test_extension_whitelabel.sh` (NUEVO): descomprime `extension-<slug>.zip` y falla si aparece cualquier término de `prohibited_brand.txt` **o** de `prohibited_names.txt` (motor), **con la allowlist de identificadores internos** del cross-contract (grep word-exact, patrón de `test_no_engine_name.sh`). Debe además verificar que `manifest.name`/`description` NO son "Basa Guard" (o sea, que el render sustituyó). Test both ways: un zip con "Basa Guard" reintroducido → rojo; el zip limpio → verde.

### Verificación local (correr ANTES de reportar done)
```bash
# 1. Render produce un zip:
deploy/release/render_extension_brand.sh camara-comercio deploy/clients/camara-comercio/brand.extension.json
ls -la deploy/clients/camara-comercio/rendered/extension/ && test -f extension-camara-comercio.zip || echo "FALTA ZIP"
# 2. Gate pasa sobre el zip limpio:
bash deploy/release/checks/test_extension_whitelabel.sh camara-comercio   # ✅ verde
# 3. Gate falla si se reintroduce la marca (prueba negativa):
#    (inyectá "Basa Guard" en una copia del manifest y confirmá que el gate da rojo)
# 4. shellcheck de los scripts nuevos:
command -v shellcheck >/dev/null && shellcheck deploy/release/render_extension_brand.sh deploy/release/checks/test_extension_whitelabel.sh || echo "shellcheck no instalado (ok)"
```
> Nota: al correr en tu worktree, `extension/` es el de la rama base (sin los cambios de Minion B todavía). El zip puede contener el `localhost` de `config.js` o "[Basa Guard]" en los `.js` → tu gate detectará esas fugas. **Eso es correcto**: documentá qué fugas detecta; el orquestador re-corre el gate DESPUÉS de integrar a Minion B (que neutraliza el source) y ahí debe quedar verde. Diseñá el gate para que sea la verdad, no para pasar artificialmente.

### Reglas duras
- No hornear URL de gateway en el zip. Íconos y nombre desde el brand-pack. Versión fuente única.
- La privada del par RSA NUNCA en el repo.

### Reportá: rama, archivos cambiados, output del render + gate (verde sobre limpio, rojo sobre sucio), qué fugas detecta sobre el `extension/` base, blockers.

---

## Integration plan (orquestador)

1. Reviso cada minion al reportar (calidad, tests corridos de verdad, cero tech-debt).
2. Merge a `028-extension-productizacion` en orden: **A (backend, define contrato whoami)** → **B (extensión, consume contrato)** → **C (deploy, empaqueta B)**.
3. Limpio los worktrees de minions ANTES de correr tests (evitar inflado de conteo).
4. Verificación integrada:
   - Backend: `pytest` de los módulos tocados (conteo esperado, sin inflar).
   - Deploy: re-corro `render_extension_brand.sh` + `test_extension_whitelabel.sh` sobre el `extension/` YA integrado de B → **debe quedar verde** (si no, hotfix a B).
   - Extensión: cargo el zip en Chrome vía Playwright contra un gateway real (compose con 027) → conectar con permiso, ver chip ámbar, disparar un bloqueo y ver el motivo, revocar y ver desconexión.
5. Codex review (`codex review --base 028-extension-productizacion` o vs dev-fran) → hotfix minions por hallazgo (§11.5), budget 5 pases.
6. Docs DoD (T025): actualizar `docs/docs/integrations/index.md` §3.3 + `docs/docs/operations/index.md`, `make -C deploy check-docs` 9/9.
7. **NO merge a dev-fran** — 028 queda en su rama, verificada y PR-ready. La integración a dev-fran + bundle + ensayo es el paso 3, JOINT con JF.

## Verificación de integración (orquestador, 2026-07-24)

- **Merge**: A→B→C limpio en la rama feature; + fix de integración `460ac91` (renombre `guardia-main.js`→`guardia-main.js`, última fuga white-label del zip).
- **Gate white-label**: VERDE sobre el zip integrado (`name='cc-guardian'`, `manifest.key` presente, sin fuga fabricante/motor, allowlist interna respetada).
- **Backend pytest (integrado, contenedor one-off)**: 17 passed, 2 skipped (skips = sondas de motor vivo). Cubre whoami `proteccion`, `expires_at` indistinguible, `gw_inspect` (shape de bloqueo 027), contrato governance_status.
- **Playwright vivo en Chrome (headed, extensión renderizada)** — `extension/e2e/`:
  - `load-smoke` **7/7**: carga + SW registra + `ext_id` = el declarado por el render (ID estable ✓) + header `cc-guardian` + FR-010 (http remoto rechazado) + chip oculto desconectado + 0 errores de consola.
  - `connected` **7/7**: US2 conecta contra el contrato whoami + US4 chip ámbar "▲ Detección por patrones · cobertura parcial" con copy del server (termina en el piso) + nunca "protegido" + US6 desconectar limpia.
  - `block` **5/5**: US5 fetch shape-ChatGPT con credencial → guard → SW → gateway bloquea → modal con el `motivo` REAL del server, nunca `blocked_by_layer` crudo, fail-closed.

### Codex — trayectoria de convergencia (§11.9)

| Pase | P1 | P2 | P3 | Notas |
|------|----|----|----|-------|
| 1 | 1→0 | 0 | 0 | Único hallazgo: "[P1] Declare the permissions API permission" (manifest.json). **FALSO POSITIVO**, refutado empíricamente. |

**Dismissal del P1 (evidencia, no opinión)**: Codex afirma que `chrome.permissions.request/contains` no funciona sin declarar la API en `permissions`. `extension/e2e/perm-probe.mjs` cargó el manifest de **producción** (`optional_host_permissions`, `permissions:["storage","alarms"]`) y en el SW real dio: `typeof chrome.permissions === "object"`, `request`/`contains` = `function`, y `chrome.permissions.contains({origins:["http://localhost:8787/*"]})` devolvió `false` **sin lanzar**. La API `chrome.permissions` está disponible para toda extensión por defecto; `optional_host_permissions` es lo que habilita pedir esos orígenes. No se corrige (§11 → documentar dismissal). **Convergido: 0 P1/P2/P3 reales → SHIP.**

## Definition of Done (028)

- [ ] US1: `make -C deploy build-extension-brand BRAND=camara-comercio` produce `extension-camara-comercio.zip` con identidad cc-guardian + `manifest.key` (ID estable), sin URL horneada.
- [ ] US1: el zip aparece en el bundle con su sha256 en el MANIFEST; `test_airgapped_bundle.sh` lo verifica.
- [ ] US2: instalado en Chrome, ingresar URL+key → pide permiso de host → conecta y enmascara; cambiar de host re-pide permiso; URL remota no-https rechazada; permiso denegado → mensaje claro.
- [ ] US3/US7: gate white-label verde sobre el zip limpio, rojo si se reintroduce "Basa Guard".
- [ ] US4: chip ámbar "Detección por patrones · cobertura parcial" desde el server; fallback conservador; contract test verde.
- [ ] US5: un bloqueo (AI-Act/secreto) muestra el `motivo` del server; un servicio caído muestra "servicio no disponible"; nunca `blocked_by_layer` crudo.
- [ ] US6: sin-red conserva key (no_verificado), 401/403 borra key (mensajes distintos), revalida por alarm + onStartup, dueño único = SW.
- [ ] US8a: key vencida → 401 indistinguible; test de regresión verde.
- [ ] Hardening #45 preservado; fail-closed intacto.
- [ ] Codex sin P1; docs DoD 9/9.
- [ ] Rama `028-extension-productizacion` PR-ready contra `dev-fran` (NO mergeada).
