# Contrato — Flujo SSO del Hub (`client/server.js`)

**Alcance**: rutas nuevas del Hub y lo que consume de la API de Guardian. Específico de esta
línea: en Sentinel se porta el **enfoque** (spec.md §Preparación para Sentinel). Decisiones:
[research.md](../research.md) D1 a D5.

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

## 2. `GET /sso/login` (navegación del navegador)

1. Llama a `GET {ELEA_BACKEND_URL}/auth/sso/login` con `redirect: 'manual'`.
2. Si responde `302` con `Location` absoluta **y** un `Set-Cookie` `sentinel_sso_state=<valor>`:
   - toma `state` del query de `Location`;
   - guarda `pendingSso[req.sid] = {stateCookie, state, venceEn: ahora + 10 min}` (reemplaza un
     pendiente previo del mismo `sid`);
   - responde `302 Location: <Location del backend>` con `Cache-Control: no-store` y
     `Referrer-Policy: no-referrer`.
3. Cualquier otra cosa → `302 Location: /?sso_error=<código>` según §4. No guarda pendiente.

## 3. `GET /sso/callback?code=…&state=…` (retorno del directorio)

La ruta **tiene** que ser exactamente `/sso/callback`: es el path de
`SENTINEL_SSO_REDIRECT_URI` registrado en Entra.

1. Lee y **borra** `pendingSso[req.sid]` (un solo uso, siempre, salga bien o mal).
2. Si **no hay pendiente**, está vencido, o `state` del query no coincide con el guardado
   (`crypto.timingSafeEqual` sobre buffers del mismo largo; distinto largo = no coincide): llama
   igual a `GET {ELEA_BACKEND_URL}/auth/sso/callback?state=…&code=…` **sin** cabecera `Cookie`,
   para que el backend registre el rechazo (`auth_sso_denied`, research D6), y responde
   `302 Location: /?sso_error=sso_reintentar`. No canjea con un pendiente ajeno.
3. Si el directorio devolvió `error=…` (p. ej. `access_denied` porque la persona canceló): igual
   que el paso anterior, pero con el pendiente válido reenviado, y `sso_error=sso_cancelado`.
4. Si coincide: `GET {ELEA_BACKEND_URL}/auth/sso/callback?state=…&code=…` con
   `Cookie: sentinel_sso_state=<stateCookie>`.
   - `200` con `access_token` y `user`: **rota el `sid`** (nuevo `sid` aleatorio de 24 bytes,
     `Set-Cookie: elea_rag_sid=<nuevo>; HttpOnly; Path=/; SameSite=Lax`), guarda
     `sessions[nuevo] = {token, user, auth_method: 'sso'}`, borra `sessions[viejo]` y responde
     `302 Location: /` con `Cache-Control: no-store` y `Referrer-Policy: no-referrer`.
   - Cualquier otro status → `302 Location: /?sso_error=<código>` según §4.
5. El cuerpo de la respuesta del backend (que trae el token) no se loguea nunca.

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
| `sso_identidad_no_verificada` | callback: `401` `sso_identidad_no_verificada` | "Microsoft no confirmó tu identidad." |
| `sso_sin_email` | callback: `401` `sso_identidad_sin_email` | "Tu cuenta corporativa no tiene un email asociado. Pedile a tu área de sistemas que lo complete." |
| `sso_usuario_inactivo` | callback: `403` con `detail` que empieza por `sso_usuario_inactivo` (se distingue del `403` de licencia por el prefijo) | "Tu usuario está dado de baja. Consultá con el administrador." |
| `sso_sin_puestos` | callback: `402` `license_seat_limit_exceeded` o `403` `license_creation_blocked` | "No quedan puestos disponibles para usuarios nuevos. Consultá con el administrador." |
| `sso_error` | cualquier otro caso | "No se pudo completar el ingreso con Microsoft." |

`index.html` borra el parámetro de la barra con `history.replaceState` después de mostrarlo.
Un código desconocido se trata como `sso_error`.

## 5. Cambios en rutas existentes

| Ruta | Cambio |
|---|---|
| `GET /api/user/current` (`client/server.js:318`) | `user.auth_method` (`'sso'` o `'password'`). |
| `POST /api/auth/change-password` (`client/server.js:284`) | Sesión con `auth_method === 'sso'` → `409 {"error": "Ingresaste con tu cuenta corporativa: la contraseña se gestiona en Microsoft."}` sin llamar al backend (FR-008). |
| `POST /api/auth/logout` | Sin cambio (borra la sesión del `sid`). |

## 6. Pantalla de ingreso (`client/public/index.html`)

- Al mostrar el overlay de ingreso (`boot`, `index.html:1051-1056`) consulta
  `/api/auth/sso/available`. Si `enabled`:
  - si `return_origin` es `null` o igual a `window.location.origin` → botón
    "Ingresar con Microsoft" que navega a `/sso/login`;
  - si es otro origen → el mismo botón navega a `${return_origin}/sso/login`.
- Si no está habilitado, no dibuja nada (US2 AS3): ni botón deshabilitado ni aviso.
- Muestra el error de `?sso_error=` en el mismo lugar que el error del login local
  (`#login-error`). El formulario de usuario y contraseña sigue visible y operativo siempre.
- Con `currentUser.auth_method === 'sso'`: no muestra el botón "Contraseña" (`index.html:542`) y
  nunca abre el modal de cambio (FR-008).

## 7. Tests de contrato mínimos (TDD, con el doble HTTP de `client/tests/mock-servers.js`)

1. `available` fail-closed: 403, 500, red caída y cuerpo raro → `enabled:false`.
2. `/sso/login` guarda pendiente y redirige a la `Location` del backend; sin `Set-Cookie` → `sso_error`.
3. Callback con el mismo `sid` y `state` correcto → sesión con `auth_method:'sso'`, `sid` rotado y `302 /`.
4. Callback desde **otro** `sid` (otro navegador) → `sso_reintentar` y el backend recibe la llamada **sin** cookie.
5. Callback con `state` distinto → `sso_reintentar`, sin canje con cookie.
6. Callback repetido (mismo `sid`, mismo `state`) → el segundo da `sso_reintentar`.
7. Pendiente vencido → `sso_reintentar`.
8. Ninguna respuesta del Hub (cabeceras `Location` y cuerpo) contiene el `access_token`.
9. Mapeo de cada status/`detail` del backend al código de §4.
10. `change-password` con sesión SSO → 409; con sesión de contraseña, igual que hoy.
11. `POST /api/auth/login` sigue idéntico (regresión).
