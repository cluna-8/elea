# Contrato — Flujo SSO del Hub (`client/server.js`)

**Alcance**: rutas nuevas del Hub y lo que consume de la API de Guardian. Específico de esta
línea: en Sentinel se porta el **enfoque** (spec.md §Preparación para Sentinel). Decisiones:
[research.md](../research.md) D1 a D5, D11 y D12, con F2, F4, F5, F6, F10, B3 y B6 de
[qa-plan.md](../qa-plan.md).

**Invariantes**

- **FR-003**: el Hub habla **solo** con la API de Guardian (`ELEA_BACKEND_URL`,
  `client/server.js:19`). No decodifica ni valida tokens de Microsoft ni el JWT de estado.
- **FR-004**: el `access_token` nunca aparece en una URL, en una respuesta al navegador ni en un
  log. Vive solo en `sessions` (`client/server.js:75`).
- **FR-005**: `POST /api/auth/login` (`client/server.js:258-273`) no cambia.
- **FR-006**: cualquier fallo del camino SSO termina en la pantalla de ingreso con un mensaje que
  recuerda que el acceso con contraseña sigue disponible.
- Sin variables de entorno nuevas en el Hub. Sin textos de marca fijos: la marca sale de
  `/api/branding` (`client/server.js:314-316`).

## 1. `GET /api/auth/sso/available` (pre-auth, JSON)

Consume `GET {ELEA_BACKEND_URL}/auth/sso/available` ([guardian-sso-api.md](guardian-sso-api.md) §1).

| Respuesta del backend | Respuesta del Hub (`200`) |
|---|---|
| `200` con `enabled === true` | `{"enabled": true, "return_origin": <string\|null del backend>}` |
| `200` con `enabled !== true` | `{"enabled": false, "return_origin": null}` |
| `403` (licencia sin `sso`), cualquier otro status, cuerpo no JSON, red caída o timeout | `{"enabled": false, "return_origin": null}` |

Nunca responde un status de error: es fail-closed. No expone `provider_type`, `config` ni nada
del directorio. Timeout de 3 s (`AbortSignal.timeout(3000)`) para no demorar la pantalla de ingreso.
Responde con `Cache-Control: no-store` (B6 del QA): apagar el interruptor en el panel tiene que
ocultar el botón en el próximo ingreso, sin depender de cachés ni de ETag (US3 AS2).

El Hub pasa `return_origin` tal cual. La regla del botón (§6) trata `return_origin: null` como
"sin botón" (F4 del QA, spec FR-001 y FR-015).

## 2. `GET /sso/login` (navegación del navegador)

1. **Límite de ritmo** (research D11, F5 del QA): un contador global por proceso, con ventana de
   60 s y tope `SSO_LOGIN_POR_MIN = 120` (constante en `client/sso.js`, reloj inyectable). Pasado
   el tope → `302 Location: /?sso_error=sso_reintentar`, **sin** llamar al backend ni guardar
   pendiente.
2. Llama a `GET {ELEA_BACKEND_URL}/auth/sso/login` con `redirect: 'manual'`.
3. Si responde `302` con `Location` absoluta **y** un `Set-Cookie` `sentinel_sso_state=<valor>`:
   - toma `state` del query de `Location`;
   - si el `redirect_uri` del query de `Location` empieza con `https://`, genera un valor
     aleatorio de 24 bytes (`atadura`) y lo emite como cookie
     `__Host-sso_flow=<atadura>; Secure; HttpOnly; Path=/; SameSite=Lax; Max-Age=600` (research
     D12, F6 del QA). Con un retorno `http://` (desarrollo en `localhost`) no hay cookie de
     atadura y el flujo queda atado solo al `sid`, como en el diseño original;
   - guarda `pendingSso[req.sid] = {stateCookie, state, atadura|null, venceEn: ahora + 10 min}`
     (reemplaza un pendiente previo del mismo `sid`). Si el almacén está **lleno** después de
     barrer los vencidos, **no** expulsa a nadie: responde `302 /?sso_error=sso_reintentar` y no
     guarda (F5 del QA: los ingresos en curso se conservan);
   - responde `302 Location: <Location del backend>` con `Cache-Control: no-store` y
     `Referrer-Policy: no-referrer`.
4. Cualquier otra cosa → `302 Location: /?sso_error=<código>` según §4. No guarda pendiente.

## 3. `GET /sso/callback?code=…&state=…` (retorno del directorio)

La ruta **tiene** que ser exactamente `/sso/callback`: es el path de
`SENTINEL_SSO_REDIRECT_URI` registrado en Entra.

1. Lee y **borra** `pendingSso[req.sid]` (un solo uso, siempre, salga bien o mal). Borra también
   la cookie `__Host-sso_flow` en la respuesta (`Max-Age=0`, mismos atributos).
2. Si **no hay pendiente**, está vencido, el `state` del query no coincide con el guardado, o el
   pendiente tiene `atadura` y la cookie `__Host-sso_flow` del pedido falta o no coincide (las dos
   comparaciones con `crypto.timingSafeEqual` sobre buffers del mismo largo; distinto largo = no
   coincide): llama igual a `GET {ELEA_BACKEND_URL}/auth/sso/callback?…` **sin** cabecera
   `Cookie`, para que el backend registre el rechazo (`auth_sso_denied`, research D6), y responde
   `302 Location: /?sso_error=sso_reintentar`. No canjea con un pendiente ajeno.
3. Si el directorio devolvió `error=…` (p. ej. `access_denied` porque la persona canceló): igual
   que el paso anterior, pero con el pendiente válido reenviado, y `sso_error=sso_cancelado`.
4. Si coincide: `GET {ELEA_BACKEND_URL}/auth/sso/callback?state=…&code=…` con
   `Cookie: sentinel_sso_state=<stateCookie>`.
   - `200` con `access_token` y `user`: **rota el `sid`** (nuevo `sid` aleatorio de 24 bytes,
     `Set-Cookie: elea_rag_sid=<nuevo>; HttpOnly; Path=/; SameSite=Lax`, más `Secure` si el
     pendiente tenía `atadura`, es decir, si el retorno es `https://`, F6 del QA). Guarda
     `sessions[nuevo] = {token, user, auth_method: 'sso'}`, borra `sessions[viejo]` y responde
     `302 Location: /` con `Cache-Control: no-store` y `Referrer-Policy: no-referrer`.
   - Cualquier otro status → `302 Location: /?sso_error=<código>` según §4.
5. El cuerpo de la respuesta del backend (que trae el token) no se loguea nunca.
6. La URL de la llamada al backend se arma con `URLSearchParams` a partir de los valores **ya
   decodificados** del query (`state`, `code`, `error`), nunca por concatenación (B3 del QA): un
   `code` con `&`, `=` o `#` no puede inyectar parámetros en la llamada interna.

## 4. Códigos de error (`sso_error`, lista cerrada)

El Hub elige el código **solo** por status y por el prefijo del `detail` del backend
(`backend/src/sso/api.py`, `jit.py`, `licensing/gate.py`). El `detail` no se copia a la URL.
El texto visible lo arma `index.html` y siempre termina recordando el acceso con contraseña.

| Código | Cuándo | Mensaje (orientativo, sin marca fija) |
|---|---|---|
| `sso_no_disponible` | login o callback: `403` `sso_no_licenciado`, `404` `sso_no_configurado` (p. ej. el admin lo apagó a mitad del ingreso), `500` `sso_redirect_uri_no_configurado`, `400` `sso_proveedor_desconocido` | "El ingreso con Microsoft no está disponible en esta instalación." |
| `sso_proveedor_caido` | login: `502` `sso_idp_inaccesible`; login o callback: backend inaccesible (red) | "No pudimos contactar a Microsoft. Probá de nuevo en unos minutos." |
| `sso_reintentar` | callback sin pendiente, vencido, `state` distinto; backend `400` `sso_state_*` | "El ingreso venció o se interrumpió. Volvé a intentarlo." |
| `sso_cancelado` | callback con `error=` del directorio, o backend `400` `sso_code_ausente` | "Se canceló el ingreso con Microsoft." |
| `sso_identidad_no_verificada` | callback: `401` `sso_identidad_no_verificada`. Cubre el `code` vencido o inventado, el secreto vencido de la aplicación, el directorio caído durante el canje y el tope de canjes fallidos (research D6) | "No se pudo confirmar el ingreso con Microsoft. Si se repite, avisá al administrador." (F10 del QA: el texto no culpa a la identidad, porque la causa puede ser de la instalación; el log del backend distingue la causa, `entra.py:109`) |
| `sso_sin_email` | callback: `401` `sso_identidad_sin_email` | "Tu cuenta corporativa no tiene un email asociado. Pedile a tu área de sistemas que lo complete." |
| `sso_usuario_inactivo` | callback: `403` con `detail` que empieza por `sso_usuario_inactivo` (se distingue del `403` de licencia por el prefijo) | "Tu usuario está dado de baja. Consultá con el administrador." |
| `sso_sin_puestos` | callback: `402` `license_seat_limit_exceeded` o `403` `license_creation_blocked` | "No quedan puestos disponibles para usuarios nuevos. Consultá con el administrador." |
| `sso_error` | cualquier otro caso | "No se pudo completar el ingreso con Microsoft." |

`index.html` borra el parámetro de la barra con `history.replaceState` después de mostrarlo.
Un código desconocido se trata como `sso_error`. La tabla código → texto vive en
`client/public/sso-ui.js` (§6), no en el HTML. El valor de `sso_error` **nunca** se pinta:
solo se usa como clave de la lista cerrada, y el texto se escribe con `textContent`.

## 5. Cambios en rutas existentes

| Ruta | Cambio |
|---|---|
| `GET /api/user/current` (`client/server.js:318`) | `user.auth_method` (`'sso'` o `'password'`). |
| `POST /api/auth/change-password` (`client/server.js:284`) | Sesión con `auth_method === 'sso'` → `409 {"error": "Ingresaste con tu cuenta corporativa: la contraseña se gestiona en Microsoft."}` sin llamar al backend (FR-008). |
| `POST /api/auth/logout` | Sin cambio (borra la sesión del `sid`). |

## 6. Pantalla de ingreso (`client/public/index.html` + `client/public/sso-ui.js`)

La lógica de la pantalla vive en un módulo **puro, sin DOM y sin dependencias**,
`client/public/sso-ui.js` (F2 del QA). Se sirve como estático y se carga con
`<script src="/sso-ui.js">` antes del script inline de `index.html`. Exporta por `module.exports`
cuando existe (tests con `node --test`) y por `window.SsoUi` en el navegador:

| Función | Regla |
|---|---|
| `destinoBoton({enabled, return_origin}, origen)` | `null` (sin botón) si `enabled !== true` o `return_origin` es `null`, vacío o no es un origen `http(s)` (F4, FR-001/FR-015). `'/sso/login'` si `return_origin === origen`. `` `${return_origin}/sso/login` `` si es otro origen. |
| `mensajeError(codigo)` | Texto de la tabla §4 para un código de la lista cerrada. Cualquier otro valor (desconocido, vacío, con HTML) → el texto de `sso_error`. Todo texto termina recordando el acceso con contraseña (FR-006). Sin marca fija (FR-013/FR-014). |
| `ofrecerCambioContrasena(user)` | `false` si `user.auth_method === 'sso'` (FR-008), `true` en otro caso. Gobierna el botón "Contraseña" (`index.html:542`) y la apertura del modal (`:1067`). |

`index.html` solo cablea:

- Al mostrar el overlay de ingreso (`boot`, `index.html:1051-1056`) consulta
  `/api/auth/sso/available` y llama a `destinoBoton(respuesta, window.location.origin)`. Con
  `null` no dibuja nada (US2 AS3): ni botón deshabilitado ni aviso. Con un destino, dibuja
  "Ingresar con Microsoft" bajo el formulario (`:444-455`), que navega ahí.
- Lee `?sso_error=` y escribe `mensajeError(valor)` en `#login-error` con **`textContent`**
  (nunca `innerHTML`). Después limpia la barra con `history.replaceState`. El formulario de
  usuario y contraseña sigue visible y operativo siempre.
- Usa `ofrecerCambioContrasena(currentUser)` para el botón "Contraseña" y el modal.

## 7. Tests de contrato mínimos (TDD)

Servidor, con el doble HTTP de `client/tests/mock-servers.js`:

1. `available` fail-closed: 403, 500, red caída y cuerpo raro → `enabled:false`; `return_origin`
   pasa tal cual (incluido `null`); `Cache-Control: no-store`.
2. `/sso/login` guarda pendiente y redirige a la `Location` del backend; sin `Set-Cookie` →
   `sso_error`.
3. `/sso/login` con retorno `https://` emite `__Host-sso_flow` con `Secure; HttpOnly; Path=/;
   SameSite=Lax`; con retorno `http://localhost` no la emite.
4. `/sso/login` pasado el límite de ritmo → `sso_reintentar` sin llamar al backend.
5. Almacén lleno: un pendiente en curso sigue consumible y el login nuevo recibe `sso_reintentar`.
6. Callback con el mismo `sid`, `state` y atadura correctos → sesión con `auth_method:'sso'`,
   `sid` rotado (con `Secure` si el retorno es `https://`) y `302 /`.
7. Callback desde **otro** `sid` (otro navegador) → `sso_reintentar` y el backend recibe la
   llamada **sin** cookie.
8. Callback con el `sid` correcto pero **sin** la cookie de atadura, o con otra (cookie `sid`
   inyectada, F6) → `sso_reintentar`, sin canje con cookie.
9. Callback con `state` distinto → `sso_reintentar`, sin canje con cookie.
10. Callback repetido (mismo `sid`, mismo `state`) → el segundo da `sso_reintentar`.
11. Pendiente vencido → `sso_reintentar`.
12. `code` y `state` con `&`, `=` y `#` llegan al backend como **un** valor cada uno (B3).
13. Ninguna respuesta del Hub (cabeceras `Location` y cuerpo) contiene el `access_token`.
14. Mapeo de cada status/`detail` del backend al código de §4.
15. `change-password` con sesión SSO → 409; con sesión de contraseña, igual que hoy.
16. `POST /api/auth/login` sigue idéntico (regresión).

Pantalla, con `node --test` sobre `client/public/sso-ui.js` (sin `jsdom`, sin dependencias nuevas):

17. `destinoBoton`: `enabled:false` → `null`; `enabled:true` + `return_origin:null` → `null` (F4);
    mismo origen → `/sso/login`; otro origen → `${return_origin}/sso/login`; `return_origin` que no
    es `http(s)` (p. ej. `javascript:`) → `null`.
18. `mensajeError`: cada código de §4 → su texto; desconocido, vacío y `<img src=x onerror=…>` →
    el texto genérico, que no contiene el valor recibido; todos recuerdan la contraseña.
19. `ofrecerCambioContrasena`: `sso` → `false`; `password` o ausente → `true`.
20. Cableado de `index.html` (lectura estática del archivo): carga `/sso-ui.js`, usa
    `destinoBoton`, `mensajeError` y `ofrecerCambioContrasena`, y el error de `sso_error` no se
    escribe con `innerHTML`.

Marca blanca (FR-013/FR-014), `client/tests/unit/whitelabel-hub-056.test.js`, solo con `node:fs`:

21. Ningún archivo nuevo de la 056 (`client/sso.js`, `client/public/sso-ui.js`) contiene un
    nombre de `deploy/release/checks/prohibited_names.txt`, un nombre de los motores internos de
    documentos o presentaciones (lista local del test, sin tocar la lista compartida), ni
    `Elea`/`Eleia`.
22. `client/public/index.html` y `client/server.js` no contienen ningún nombre de
    `prohibited_names.txt` (la lista compartida; los comentarios ya existentes que nombran un
    motor interno quedan fuera porque esa lista no lo incluye).
