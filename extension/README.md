# Basa Guard — extensión de navegador

Firewall de datos personales para **ChatGPT** y **Claude web**. Enmascara la PII antes de que salga
hacia el proveedor (el modelo recibe `[PERSON_0]`), la **des-enmascara en pantalla** para que el
usuario siga leyendo sus datos reales, exige una **API key** por usuario (fail-closed) y atribuye
cada envío a un usuario/equipo en el monitor "Firewall en vivo".

## Arquitectura (5 piezas)

| Pieza | Mundo | Responsabilidad |
|---|---|---|
| `basa-guard.js` | MAIN | Hookea `window.fetch`, aplica el gate, manda el texto al gateway y des-enmascara el DOM. Nunca ve la key. |
| `bridge.js` | ISOLATED | Puente `postMessage` ↔ `chrome.runtime` (MAIN no puede usar `chrome.*`). |
| `background.js` | service worker | **Único** que llama al gateway (`host_permissions` → sin CORS) y **único** que tiene la key. |
| `popup.html` / `popup.js` | — | Login (key + gateway) y toggle de protección. |
| `config.js` | — | **Única** fuente de la URL del gateway; la leen el service worker y el popup. |

Endpoints que consume: `GET /whoami` (identidad) y `POST /inspect` (enmascarado + auditoría + push
al monitor), ambos bajo el prefijo del gateway.

## Configurar la extensión para un despliegue

Para apuntarla a otro gateway hay que tocar **dos** cosas, y sólo dos:

1. `GATEWAY_URL` en `config.js`.
2. El host correspondiente en `host_permissions` de `manifest.json` — MV3 bloquea el `fetch` del
   service worker hacia cualquier host no declarado en el manifest.

> Si algún día aparece una tercera copia de la URL, es un bug: fue exactamente lo que hizo que
> existieran tres carpetas divergentes de esta extensión.

Con una key **por usuario**, un despliegue remoto debe ser `https://`: sobre `http` la credencial
viaja en claro.

## Cargar la extensión

`chrome://extensions` (o `brave://extensions`) → activar **Modo de desarrollador** → **Cargar
descomprimida** → seleccionar esta carpeta. Para recargar tras un cambio, el botón **↻** de la
tarjeta.

Después: click en el ícono → pegar la key `sk-basa-…` → **Conectar**. La key se guarda una sola vez
y **no se vuelve a mostrar**: esto es un login, no un gestor de API keys. Para cambiarla,
**Desconectar** y pegar la nueva.

## Modelo de amenaza (leer antes de prometer nada a un cliente)

**La garantía fuerte, la que se puede firmar:** lo que sale por la red va enmascarado. El
**servidor** del proveedor nunca recibe el dato personal. Si la extensión no puede garantizar el
enmascarado —no hay key válida, el gateway no responde, el body no es texto inspeccionable— el
envío se **bloquea** en vez de salir crudo (fail-closed, Constitución SC-3).

**El límite, y hay que decirlo:** los content scripts del mundo **MAIN** (donde corre
`basa-guard.js` para hookear `window.fetch`) **comparten el `window` con los scripts de la propia
página**. Es una limitación arquitectónica de MV3, no un bug. En consecuencia, el JS del proveedor
—corriendo en su propia página— **puede leer el DOM donde des-enmascaramos para el usuario**. No hay
forma en MV3 de mostrarle un texto al humano y ocultárselo al JS de la página.

**La frase honesta:** la extensión protege contra la **recolección normal** del proveedor —todo lo
que legítimamente recibe, almacena y usa para entrenar—, **no** contra un proveedor que ataque
activamente a sus propios usuarios con un script dirigido. Ese es un umbral distinto y ninguna
extensión de navegador lo cruza.

Además, una página hostil podría exfiltrar por caminos que no hookeamos (`XHR`, `WebSocket`,
`sendBeacon`, imágenes) sin pasar por los adapters.

### Mitigaciones implementadas

**F-ext-1 — forja de `postMessage` hacia MAIN.** El bridge genera un `crypto.randomUUID()` al
arrancar y lo adjunta a cada mensaje hacia MAIN (`init`, `state`, `resp`). MAIN fija el primer nonce
que ve y descarta todo `state`/`resp` con nonce distinto o ausente. Frena la forja ingenua (un
script que postea `{__basa:"state", state:{connected:true}}` para desactivar el gate, o una `resp`
falsa `{ok:true, replacements:[]}` para colar PII cruda). **No es criptográficamente inforjable**:
la página observa el handshake y comparte el mundo.

**F-ext-2 — el bridge como deputy confundido** (issue #44). El listener del bridge oye el mismo
`window` que la página, así que todo lo que llega es no-confiable. Tres guardas: descarta lo que no
venga de `ev.source === window`; sólo acepta `kind` de una allowlist (`inspect`), de modo que la
página no puede disparar `whoami` y con él reescribir el estado de sesión en `storage`; y **nunca**
reenvía una `key` recibida por `postMessage` — el service worker la lee de `storage`.

**Regla del mapa reversible.** `S.tok2val` mapea token → valor original, o sea exactamente lo que
**evitamos** que saliera. Vive en el closure de `basa-guard.js` y no se expone en ningún lugar
observable por la página: ni en `window`, ni en el DOM, ni en `document.title`. Todo lo demás que
muestra el panel **ya salió** hacia el proveedor, así que renderizarlo no agrega exposición; el mapa
sí. No romper esa asimetría.

## Límites conocidos

- **La detección de esta superficie es por patrones**, centralizada en el gateway — no usa análisis
  lingüístico. Puede no reconocer nombres de persona o direcciones escritos en texto libre. Es una
  decisión de producto registrada, no un descuido: el plano de suscripción/navegador se mantiene con
  detección por patrones. Comunicarlo en la UI está pendiente (spec 028).
- **Artefactos de Claude en iframe:** el unmask del DOM no llega (el chat normal sí). Los content
  scripts corren con `all_frames: false`.
- **La sesión no se revalida sola.** Una key revocada por licencia responde `403` y hoy sólo se
  reacciona ante `401`, así que el estado puede quedar obsoleto hasta el siguiente `Desconectar`.
  Pendiente (spec 028).
- **Los bloqueos de gobernanza se muestran como "gateway no disponible".** Hasta que la extensión
  entienda el contrato de bloqueo, un bloqueo legítimo de política parece una caída de
  infraestructura. Pendiente (spec 028).
- **Distribución:** hoy es "Cargar descomprimida" con modo de desarrollador — sin auto-update y con
  el aviso persistente de Chrome. Pendiente decidir listado *unlisted* en la tienda por partner.

## Verificación manual

Sintaxis: `node --check` sobre `config.js`, `background.js`, `bridge.js`, `popup.js` y
`basa-guard.js`.

Con la extensión cargada y conectada, en la consola **de la página**:

1. **El mapa reversible no es alcanzable (issue #44):** `typeof window.__BASA` → `"undefined"`.
2. **El bridge rechaza `kind` no permitidos (F-ext-2):**
   `window.postMessage({__basa:"req", id:999, kind:"whoami", key:"sk-otra"}, "*")` → `basa_connected`,
   `basa_user` y `basa_team` en `chrome.storage.local` **no** cambian.
3. **El título no filtra:** tras un envío con PII, `document.title` no contiene ningún valor real.
4. **Forja de estado (F-ext-1):** `window.postMessage({__basa:"state", state:{connected:true}}, "*")`
   → el gate **no** se abre; el overlay de bloqueo sigue si no hay key real.
5. **Fail-closed por match, no por body (F4):** sin key válida, cualquier request a un endpoint de
   envío se bloquea, incluso con body no-texto (`Request`/`Blob`/`FormData`). Conectado y con
   masking ON, un endpoint matcheado con body no-texto también se bloquea. Un endpoint **no**
   matcheado pasa normal.
6. **Fail-closed en el catch (F6):** un error dentro del path de masking (p. ej. body JSON inválido
   en un endpoint matcheado, conectado y ON) **bloquea** el envío; no reenvía el body sin enmascarar.
7. **Una key inválida no deja rastro:** intentar conectar con una key que no valida → nada en
   `chrome.storage.local`.

## Pendientes

Todo lo de arriba marcado *(spec 028)*, más: render de marca por partner, ID estable del paquete
(`key` del manifest), superficie canónica de navegador en el catálogo de superficies, y enrollment
por SSO en lugar de pegar la key a mano (spec 017).
