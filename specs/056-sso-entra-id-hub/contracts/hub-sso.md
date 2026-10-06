# Contrato — Flujo SSO del Hub (`client/server.js`)

**Alcance**: rutas nuevas del Hub y lo que consume de la API de Guardian. Específico de esta
línea: en Sentinel se porta el **enfoque** (spec.md §Preparación para Sentinel). Decisiones:
[research.md](../research.md) D1 a D5, D11 y D12, con F2, F4, F5, F6, F10, B3 y B6 de
[qa-plan.md](../qa-plan.md).

**Referencias de línea** (O3 del QA del Tramo B, [qa-tramo-b.md](../qa-tramo-b.md)): los
`archivo:línea` de `client/` corresponden al código del Tramo B (commits `dba9212`, `18032e1` y
`ee6733b`), no al Hub previo a la 056. Rutas: `GET /api/auth/sso/available` en
`client/server.js:406-421`, `GET /sso/login` en `:423-465`, `GET /sso/callback` en `:467-508`
y la llamada interna al callback del backend en `:392-402`. Almacén de pendientes, límite de
ritmo, comparación y mapeo de errores en `client/sso.js` (`:10-13`, `:18-49`, `:53-68`, `:72-79`,
`:94-124`); pantalla en `client/public/sso-ui.js:12-70`.

**Invariantes**

- **FR-003**: el Hub habla **solo** con la API de Guardian (`ELEA_BACKEND_URL`,
  `client/server.js:20`). No decodifica ni valida tokens de Microsoft ni el JWT de estado.
- **FR-004**: el `access_token` nunca aparece en una URL, en una respuesta al navegador ni en un
  log. Vive solo en `sessions` (`client/server.js:76`).
- **FR-005**: `POST /api/auth/login` (`client/server.js:301-319`) no cambia lo visible (status,
  cuerpo, `must_change_password`). Única excepción, interna (N7 del QA v2, decisión del owner del
  2026-10-06): renueva el `sid` al emitir la sesión y `parseCookies` ignora una cookie mal formada
  (§5).
- **FR-006**: cualquier fallo del camino SSO termina en la pantalla de ingreso con un mensaje que
  recuerda que el acceso con contraseña sigue disponible.
- Sin variables de entorno nuevas en el Hub. Sin textos de marca fijos: la marca sale de
  `/api/branding` (`client/server.js:363-365`, marca de `HUB_BRAND`, `:47-53`).

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
   pendiente. **Efecto aceptado, límite conocido** (spec, Clarifications N1; research D11): 2
   pedidos/s **sostenidos** sin autenticarse dejan el botón en `sso_reintentar` para todos
   mientras dure. El login con contraseña no se afecta. El valor no sale de un dato medido:
   tras un reinicio del Hub (sesiones en memoria), el reingreso masivo legítimo también lo puede
   alcanzar.
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
   - **Cookies sin pisarse**: en una primera visita sin `elea_rag_sid`, el middleware ya dejó un
     `Set-Cookie` con el `sid` nuevo (middleware de `client/server.js:119-128`, que lo agrega con
     `agregarSetCookie` en `:123`). La cookie
     `__Host-sso_flow` se **agrega** a ese encabezado (lista de `Set-Cookie`, `:111-117` y `:462`), nunca lo reemplaza:
     si se pisara, el pendiente quedaría atado a un `sid` que el navegador nunca recibe y todo
     ingreso desde una primera visita fallaría (el caso de quien llega por `http://IP:8095` y el
     botón lo lleva al nombre HTTPS, D4).
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
   - **Cookies sin pisarse en el callback** (N8 del QA v2): la respuesta lleva una **lista** de
     `Set-Cookie` con exactamente una `elea_rag_sid` (la rotada) y, si el pendiente tenía
     `atadura`, el borrado de `__Host-sso_flow` del paso 1. Si el middleware ya había puesto un
     `elea_rag_sid` en esta respuesta, se reemplaza **solo esa entrada** de la lista; el borrado de
     la atadura se conserva. El `sid` viejo no aparece en ningún `Set-Cookie`.
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

Los textos de la tabla son la **base** de cada mensaje. `mensajeError` les agrega siempre el
mismo sufijo, que recuerda que el acceso con usuario y contraseña sigue disponible (FR-006).

`index.html` borra el parámetro de la barra con `history.replaceState` después de mostrarlo.
Un código desconocido se trata como `sso_error`. La tabla código → texto vive en
`client/public/sso-ui.js` (§6), no en el HTML. El valor de `sso_error` **nunca** se pinta:
solo se usa como clave de la lista cerrada, y el texto se escribe con `textContent`.

## 5. Cambios en rutas existentes

| Ruta | Cambio |
|---|---|
| `GET /api/user/current` (`client/server.js:510-525`; el campo, en `:521`) | `user.auth_method` (`'sso'` o `'password'`). |
| `POST /api/auth/change-password` (`client/server.js:329`; el 409, en `:333-335`) | Sesión con `auth_method === 'sso'` → `409 {"error": "Ingresaste con tu cuenta corporativa: la contraseña se gestiona en Microsoft."}` sin llamar al backend (FR-008). |
| `POST /api/auth/logout` | Sin cambio (borra la sesión del `sid`). |
| `POST /api/auth/login` (`client/server.js:301-319`; la rotación, `emitirSesionRotada` en `:141-148`, llamada en `:313`) | **Rotación de `sid`** (N7 del QA v2): con login exitoso, `sid` nuevo de 24 bytes, `sessions[nuevo] = …`, `sessions[viejo]` borrada y `Set-Cookie: elea_rag_sid=<nuevo>; HttpOnly; Path=/; SameSite=Lax` (los atributos de `sidCookie`, `:104-107`, **sin** `Secure`, como hoy). Si el middleware ya puso un `elea_rag_sid` en la respuesta, se reemplaza solo esa entrada. Status y cuerpo idénticos a hoy. Con login fallido, nada cambia. |
| `parseCookies` (`client/server.js:89-101`) | `decodeURIComponent` dentro de `try`: una cookie con `%` mal formado se **ignora** (como si no estuviera) y las demás se leen; nunca un 500 (N7 del QA v2). |

## 6. Pantalla de ingreso (`client/public/index.html` + `client/public/sso-ui.js`)

La lógica de la pantalla vive en un módulo **puro, sin DOM y sin dependencias**,
`client/public/sso-ui.js` (F2 del QA). Se sirve como estático y se carga con
`<script src="/sso-ui.js">` antes del script inline de `index.html`. Exporta por `module.exports`
cuando existe (tests con `node --test`) y por `window.SsoUi` en el navegador:

| Función | Regla |
|---|---|
| `destinoBoton({enabled, return_origin}, origen)` | `null` (sin botón) si `enabled !== true` o `return_origin` es `null`, vacío o no es un origen `http(s)` **bien formado** (F4, FR-001/FR-015). Bien formado = las **dos** condiciones juntas (`client/public/sso-ui.js:44-54`): **(a) lista blanca estricta de forma** (O1 del QA del Tramo B), `^https?://(host\|[ipv6])(:puerto)?$` anclada y sin bandera `m`: host en minúsculas con solo `[a-z0-9.-]` (empieza y termina en letra o dígito) o IPv6 entre corchetes con solo `[0-9a-f:.]`, y puerto opcional de 1 a 5 dígitos (`FORMA_ORIGEN`, `sso-ui.js:44`); **y (b)** (N5 del QA v2) `new URL(return_origin)` no lanza, su `protocol` es `http:` o `https:` y `new URL(return_origin).origin === return_origin` (`sso-ui.js:46-54`). (b) sola **no alcanza**: el parser de URL acepta en el host `"`, `'`, `;`, `=` y otros, así que `https://a"onmouseover=x` pasaría; (a) los descarta. Entre las dos descartan comillas, apóstrofos, `;`, `=`, `%`, `` ` ``, espacios, `<`, `\\`, credenciales `usuario@`, ruta, query, fragmento, barra final, mayúsculas, puerto vacío o no numérico y el puerto por defecto escrito (`:443`, `:80`, porque `origin` lo normaliza). `'/sso/login'` si `return_origin === origen`. `` `${return_origin}/sso/login` `` si es otro origen (`sso-ui.js:57-63`). |
| `TEXTO_BOTON` | Constante con la etiqueta "Ingresar con Microsoft". **Todo** texto nuevo visible de la 056 vive en este módulo, incluida la etiqueta del botón, y no en `index.html` (N6 del QA v2: así lo cubre entero el test de marca blanca 21). |
| `mensajeError(codigo)` | Texto de la tabla §4 para un código de la lista cerrada. Cualquier otro valor (desconocido, vacío, con HTML) → el texto de `sso_error`. Todo texto termina recordando el acceso con contraseña (FR-006). Sin marca fija (FR-013/FR-014). |
| `ofrecerCambioContrasena(user)` | `false` si `user.auth_method === 'sso'` (FR-008), `true` en otro caso. Gobierna el botón "Contraseña" (`index.html:550`, vía `aplicarCambioContrasena` en `:1089-1092`) y la apertura del modal (`:1164-1165`). |

`index.html` solo cablea:

- Al mostrar el overlay de ingreso (`boot`, `index.html:1096-1105`, que llama a
  `mostrarIngresoCorporativo` en `:1064-1078`) consulta
  `/api/auth/sso/available` y llama a `destinoBoton(respuesta, window.location.origin)`. Con
  `null` no dibuja nada (US2 AS3): ni botón deshabilitado ni aviso. Con un destino, dibuja el
  botón bajo el formulario (`:450-461`), en `#sso-login-slot` (`:462-463`), que navega ahí. El botón se arma con
  `document.createElement`, la etiqueta con `textContent = SsoUi.TEXTO_BOTON` y el destino con una
  propiedad (`href` o `location.assign`), **nunca** con `innerHTML` ni plantillas de texto con el
  origen adentro (N5 del QA v2).
- Lee `?sso_error=` (`mostrarErrorCorporativo`, `index.html:1079-1088`) y escribe
  `mensajeError(valor)` en `#login-error` (`:459`) con **`textContent`**
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
   SameSite=Lax`; con retorno `http://localhost` no la emite. Un pedido **sin** `elea_rag_sid`
   y con retorno `https://` recibe **los dos** `Set-Cookie` (`sid` nuevo y atadura), y el
   pendiente queda bajo ese `sid`.
4. `/sso/login` pasado el límite de ritmo → `sso_reintentar` sin llamar al backend.
5. Almacén lleno: un pendiente en curso sigue consumible y el login nuevo recibe `sso_reintentar`.
6. Callback con el mismo `sid`, `state` y atadura correctos → sesión con `auth_method:'sso'`,
   `sid` rotado (con `Secure` si el retorno es `https://`) y `302 /`. Con `getSetCookie()`, la
   respuesta trae **exactamente** el `sid` rotado y el borrado de `__Host-sso_flow`, los dos, y
   el `sid` viejo no aparece (N8 del QA v2). La variante «primera visita» **no** se da con un
   callback exitoso: sin `elea_rag_sid`, el middleware inventa un `sid` sin pendiente y el
   callback cae siempre al rechazo (N1 del QA del Tramo B). Se cubre con lo alcanzable: un
   callback fallido en primera visita deja una sola `elea_rag_sid` y no rota
   (`client/tests/integration/test_sso_flujo_056.test.js:183`), y el filtro de
   `emitirSesionRotada` con el `Set-Cookie` del middleware ya puesto lo prueba el test 24
   (`client/tests/contract/test_login_sid_056.test.js:86`).
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
16. `POST /api/auth/login` sigue idéntico en lo visible (regresión): status, cuerpo y
    `must_change_password`; la cookie `elea_rag_sid` sin `Secure`.
24. `POST /api/auth/login` exitoso con un `elea_rag_sid` plantado → la respuesta trae un
    `elea_rag_sid` **distinto**, la sesión vive bajo el nuevo y el plantado no tiene sesión; en una
    primera visita, un solo `elea_rag_sid` en la lista de `Set-Cookie`; login fallido → sin
    rotación (N7 del QA v2).
25. Pedido con `Cookie: x=%E0%A4%A; elea_rag_sid=<válido>` a cualquier ruta (incluidas
    `/api/user/current` y `/sso/callback`) → no responde 500; la cookie mala se ignora y el `sid`
    válido se respeta (N7 del QA v2).

Pantalla, con `node --test` sobre `client/public/sso-ui.js` (sin `jsdom`, sin dependencias nuevas):

17. `destinoBoton`: `enabled:false` → `null`; `enabled:true` + `return_origin:null` → `null` (F4);
    mismo origen → `/sso/login`; otro origen → `${return_origin}/sso/login`; `return_origin` que no
    es `http(s)` (p. ej. `javascript:`) → `null`; `return_origin` mal formado → `null`: con comilla
    (`https://a"onmouseover=x`), con espacio (`https://a b`), con `<`, con `\\`, con credenciales
    (`https://u@hub.ejemplo.local`), con ruta o con barra final (N5 del QA v2); con `'`, `;`,
    `=`, `%22` o `` ` `` en el host (`https://a'b`, `https://a;b`, `https://a=b`, `https://a%22b`),
    con puerto vacío, no numérico o de más de 5 dígitos, con corchetes mal cerrados y con el
    puerto por defecto escrito (`https://hub.ejemplo.local:443`, `http://hub.ejemplo.local:80`)
    (O1 y O2 del QA del Tramo B). Lado **aceptado** (O2): IPv4 con y sin puerto
    (`http://172.16.0.120:8095`, el caso de D4, y `http://192.168.1.10`), IPv6 entre corchetes
    con y sin puerto (`https://[::1]:8443`, `https://[2001:db8::1]`, el caso de FR-015) y nombre
    con puerto explícito o por defecto → botón hacia ese origen, o `/sso/login` si es el mismo
    (`client/tests/unit/sso-ui-056.test.js:62-123`; los casos de O2, commit `f1c5403`, T051).
18. `mensajeError`: cada código de §4 → su texto; desconocido, vacío y `<img src=x onerror=…>` →
    el texto genérico, que no contiene el valor recibido; todos recuerdan la contraseña.
19. `ofrecerCambioContrasena`: `sso` → `false`; `password` o ausente → `true`.
20. Cableado de `index.html` (lectura estática del archivo): carga `/sso-ui.js`, usa
    `destinoBoton`, `mensajeError`, `ofrecerCambioContrasena` y `TEXTO_BOTON`; ni el error de
    `sso_error` ni el botón se escriben con `innerHTML` (N5 del QA v2).

Marca blanca (FR-013/FR-014), `client/tests/unit/whitelabel-hub-056.test.js`, solo con `node:fs`:

21. Ningún archivo nuevo de la 056 (`client/sso.js`, `client/public/sso-ui.js`) contiene un
    nombre de `deploy/release/checks/prohibited_names.txt`, un nombre de los motores internos de
    documentos o presentaciones (lista local del test, sin tocar la lista compartida), ni
    `Elea`/`Eleia`.
22. `client/public/index.html` y `client/server.js` no contienen ningún nombre de
    `prohibited_names.txt` (la lista compartida; los comentarios ya existentes que nombran un
    motor interno quedan fuera porque esa lista no lo incluye).
23. `client/public/index.html` no contiene el literal "Ingresar con Microsoft" ni otro texto
    visible nuevo de la 056: la etiqueta sale de `SsoUi.TEXTO_BOTON` (N6 del QA v2). Así FR-013
    queda cubierto sin tocar la lista compartida. Límite honesto: `client/server.js` ya contiene
    `Elea`/`ELEA_*` (`client/server.js:20`), así que sus rutas nuevas no se verifican contra
    FR-014 por lectura de marca; las cubre la revisión del PR.
