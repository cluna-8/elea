# Extensión de navegador — firewall de datos personales

Firewall de datos personales para **ChatGPT** y **Claude web**. Enmascara la PII antes de que salga
hacia el proveedor (el modelo recibe `[PERSON_0]`), la **des-enmascara en pantalla** para que el
usuario siga leyendo sus datos reales, exige una **API key** por usuario (fail-closed) y atribuye
cada envío a un usuario/equipo en el monitor "Firewall en vivo".

> Nota de packaging: este README es sólo de desarrollo — **no** viaja en el paquete white-label que
> se entrega al partner (el render sólo incluye archivos de runtime).

## Arquitectura (5 piezas)

| Pieza | Mundo | Responsabilidad |
|---|---|---|
| `guardia-main.js` | MAIN | Hookea `window.fetch`, aplica el gate, manda el texto al gateway y des-enmascara el DOM. Nunca ve la key. |
| `bridge.js` | ISOLATED | Puente `postMessage` ↔ `chrome.runtime` (MAIN no puede usar `chrome.*`). |
| `background.js` | service worker | **Único** que llama al gateway (permiso de host concedido en runtime → sin CORS), **único** que ve la key y **dueño único** del estado de sesión. |
| `popup.html` / `popup.js` | — | Conectar / desconectar (login), y una vista de configuración aparte. Observa el estado; no lo escribe. |
| `config.js` | — | Default de la URL del gateway (vacío por defecto) + validación de URL. |

Endpoints que consume: `GET /whoami` (identidad + nivel de protección) y `POST /inspect`
(enmascarado + auditoría + bloqueos de política), ambos bajo el prefijo del gateway.

## Conexión: la URL la pone el usuario (agnóstica al despliegue)

La dirección del gateway **la ingresa el usuario** en el popup (editable, con default opcional). Ya
**no** se hornea ninguna URL ni se declara un host fijo en el manifest:

- Al conectar, el navegador pide **permiso de acceso al host** ingresado
  (`optional_host_permissions` + `chrome.permissions.request`). El service worker —que tiene ese
  permiso— hace el `fetch`, así que **no hay CORS** y no hace falta ningún microservicio.
- Cambiar de host vuelve a pedir permiso del host nuevo.
- Una dirección **remota** debe ser `https://` (la key por usuario viajaría en claro sobre `http`);
  una dirección local sí se admite sobre `http`.

## Cargar la extensión

`chrome://extensions` (o `brave://extensions`) → activar **Modo de desarrollador** → **Cargar
descomprimida** → seleccionar esta carpeta. Para recargar tras un cambio, el botón **↻** de la
tarjeta.

Después: click en el ícono → **⚙** → pegar la dirección del gateway y la key → **Guardar y
conectar** → conceder el permiso de host cuando el navegador lo pida.

La vista principal muestra el estado y tres botones: **Conectar** (revalida contra el gateway),
**Desconectar** (borra la key) y **⚙** (configuración). La key y el gateway viven detrás del ⚙ porque
son un setup de **una vez**: se guardan y **no se vuelven a mostrar**. Esto es un login.

**No hay toggle de protección.** El enmascarado no es desactivable por el usuario: el toggle que
existía dejaba que el empleado apagara el firewall y mandara el body crudo al proveedor.

## Honestidad de protección

En esta superficie la detección de datos personales es **por patrones** (correo, teléfono,
documentos, credenciales), no por análisis lingüístico: puede no reconocer nombres o direcciones en
texto libre. La extensión lo comunica con un **chip ámbar "cobertura parcial"** (nunca verde, nunca
"protegido"), y el texto de alcance **viene del servidor** (fuente única de copy): el día que la
superficie cambie, el mensaje cambia sin re-empaquetar. Si el servidor no informa el nivel, la
extensión asume la promesa más chica ("patrones").

## Bloqueos de gobernanza

Cuando el gateway bloquea un envío por política, la extensión frena el envío y muestra el **motivo
real** provisto por el servidor (nunca un identificador interno de la capa que bloqueó). Un fallo del
gateway **sin** indicación de bloqueo se muestra como "servicio no disponible".

## Sesión

El service worker es el **dueño único** del estado y distingue tres situaciones:

- **Conectado**: whoami ok.
- **No verificado**: corte de red → la key **se conserva** y la sesión se recupera sola cuando vuelve
  la conexión.
- **Desconectado**: la key fue rechazada (`401` = key inválida; `403` = plaza revocada, mensaje
  propio) → la key **se borra**. (Hoy el servidor sólo responde `401`; el branch `403` queda listo.)

La sesión se revalida sola: una alarma periódica (~30 min) y al reabrir el navegador.

## Modelo de amenaza (leer antes de prometer nada a un cliente)

**La garantía fuerte, la que se puede firmar:** lo que sale por la red va enmascarado. El
**servidor** del proveedor nunca recibe el dato personal. Si la extensión no puede garantizar el
enmascarado —no hay key válida, el gateway no responde, el body no es texto inspeccionable— el
envío se **bloquea** en vez de salir crudo (fail-closed, Constitución SC-3).

**El límite, y hay que decirlo:** los content scripts del mundo **MAIN** (donde corre el hook de
`window.fetch`) **comparten el `window` con los scripts de la propia página**. Es una limitación
arquitectónica de MV3, no un bug. En consecuencia, el JS del proveedor **puede leer el DOM donde
des-enmascaramos para el usuario**. No hay forma en MV3 de mostrarle un texto al humano y
ocultárselo al JS de la página.

**La frase honesta:** la extensión protege contra la **recolección normal** del proveedor, **no**
contra un proveedor que ataque activamente a sus propios usuarios con un script dirigido. Ese es un
umbral distinto y ninguna extensión de navegador lo cruza. Además, una página hostil podría
exfiltrar por caminos que no hookeamos (`XHR`, `WebSocket`, `sendBeacon`, imágenes).

### Mitigaciones implementadas

**F-ext-1 — forja de `postMessage` hacia MAIN.** El bridge genera un `crypto.randomUUID()` al
arrancar y lo adjunta a cada mensaje hacia MAIN (`init`, `state`, `resp`). MAIN fija el primer nonce
que ve y descarta todo `state`/`resp` con nonce distinto o ausente. Frena la forja ingenua. **No es
criptográficamente inforjable**: la página observa el handshake y comparte el mundo.

**F-ext-2 — el bridge como deputy confundido.** El listener del bridge oye el mismo `window` que la
página, así que todo lo que llega es no-confiable. Tres guardas: descarta lo que no venga de
`ev.source === window`; sólo acepta `kind` de una allowlist (`inspect`), de modo que la página no
puede disparar `whoami` y con él reescribir el estado de sesión en `storage`; y **nunca** reenvía una
`key` recibida por `postMessage` — el service worker la lee de `storage`.

**Regla del mapa reversible.** El mapa token → valor original (`S.tok2val`) es exactamente lo que
**evitamos** que saliera. Vive en el closure del content script MAIN y no se expone en ningún lugar
observable por la página: ni en `window`, ni en el DOM, ni en `document.title`. Todo lo demás que
muestra el panel **ya salió** hacia el proveedor, así que renderizarlo no agrega exposición; el mapa
sí. No romper esa asimetría.

## Límites conocidos

- **La detección de esta superficie es por patrones** (ver "Honestidad" arriba).
- **Artefactos de Claude en iframe:** el unmask del DOM no llega (el chat normal sí). Los content
  scripts corren con `all_frames: false`.
- **Distribución:** hoy es "Cargar descomprimida" con modo de desarrollador, o entrega del paquete al
  IT del cliente. Un listado *unlisted* en la tienda por partner queda como salida futura.

## Verificación manual

Sintaxis: `node --check` sobre `config.js`, `background.js`, `bridge.js`, `popup.js` y
`guardia-main.js`; `manifest.json` es JSON válido.

Con la extensión cargada y conectada, en la consola **de la página**:

1. **El mapa reversible no es alcanzable:** `typeof window.__BASA` → `"undefined"`.
2. **El bridge rechaza `kind` no permitidos:**
   `window.postMessage({__basa:"req", id:999, kind:"whoami", key:"sk-otra"}, "*")` → el estado de
   sesión en `chrome.storage.local` **no** cambia.
3. **El título no filtra:** tras un envío con PII, `document.title` no contiene ningún valor real.
4. **Forja de estado:** `window.postMessage({__basa:"state", state:{connected:true}}, "*")` → el gate
   **no** se abre; el overlay de bloqueo sigue si no hay key real.
5. **Fail-closed por match, no por body:** sin key válida, cualquier request a un endpoint de envío se
   bloquea, incluso con body no-texto. Un endpoint **no** matcheado pasa normal.
6. **Bloqueo de política vs caída:** una respuesta `{ok:false, blocked:true, motivo}` muestra el
   motivo; un fallo sin `blocked` muestra "servicio no disponible".
7. **Una key inválida no deja rastro:** conectar con una key que no valida → nada en
   `chrome.storage.local`.
