# Research — Spec 056: Ingreso con Microsoft Entra ID (SSO) en el Hub

**Fase 0 de `/speckit-plan`** · Fecha: 2026-10-05 · Spec: [spec.md](spec.md)

Cada decisión abierta del plan se resuelve acá con **opciones, recomendación y la elección
final**. Las elecciones marcadas *"confirmada por el coordinador"* se preguntaron por `ask`
(regla del brief: las decisiones de diseño no se cierran en silencio). Toda afirmación sobre el
código lleva `archivo:línea` de la rama `cluna-8/056-sso-entra-id-hub-plan` (base `767ffa7`).

## Hechos del código que condicionan el diseño

| # | Hecho | Dónde |
|---|---|---|
| H1 | El inicio del flujo responde **302 al IdP** y deja el `state`+`nonce` en una cookie **firmada** (`sentinel_sso_state`, JWT de 10 min, `path=/api/v1/auth/sso`). | `backend/src/sso/api.py:58-63`, `:88-99`, `:237-247` |
| H2 | El callback lee **esa cookie** y compara el `state` del query con `compare_digest`. Sin cookie → 400 `sso_state_ausente`. | `backend/src/sso/api.py:102-124`, `:260-268` |
| H3 | El callback devuelve **JSON** `{access_token, token_type, user}` con la misma forma que `POST /users/login`. No redirige. | `backend/src/sso/api.py:321-336` |
| H4 | Hay **una sola** URI de retorno, `SENTINEL_SSO_REDIRECT_URI`, obligatoria y sin default; se usa idéntica en authorize y en el canje. | `backend/src/sso/api.py:127-154`, `:222`, `:293` |
| H5 | `GET /auth/sso/available` es pre-auth, está detrás del gate de licencia (403 sin `sso`) y devuelve solo `{enabled, provider_type}`. | `backend/src/sso/api.py:179-200`, `:66-79` |
| H6 | Los rechazos de **identidad** se auditan (`auth_sso_denied`), pero los 400 de `state` ausente/ inválido y de `code` ausente **no**. | `backend/src/sso/api.py:260-273` (sin `_auditar_denegado`), comparar con `:302`, `:313`, `:379` |
| H7 | El Hub guarda el JWT de Guardian **del lado del servidor** en un `Map` en memoria indexado por la cookie `elea_rag_sid` (HttpOnly, `SameSite=Lax`). | `client/server.js:75-105` |
| H8 | El login del Hub es `POST /api/auth/login` → `POST {ELEA_BACKEND_URL}/users/login` → `setSession`. | `client/server.js:119-127`, `:258-273` |
| H9 | El navegador **nunca** habla con la API de Guardian desde el Hub: el Hub llama a `ELEA_BACKEND_URL` (`http://backend:8000/api/v1`, red interna). | `client/server.js:19`, `elea-installer/docker-compose.yml:184` |
| H10 | El Hub abre el modal de cambio obligatorio si `currentUser.must_change_password`, y ofrece siempre el botón "Contraseña". | `client/public/index.html:1067`, `:542` |
| H11 | El callback SSO **no** incluye `must_change_password` en `user` (el login local sí). | `backend/src/sso/api.py:327-333` vs `backend/src/api/users.py:214` |
| H12 | Los usuarios nacidos por SSO tienen `password_hash = "!sso-no-password"`: ninguna contraseña local los autentica. | `backend/src/sso/jit.py:48`, `:151` |
| H13 | El panel dibuja "Entrar con Microsoft" con **solo** `enabled === true` de `/available`. | `frontend/src/pages/LoginPage.tsx:43`, `:155-162`; `frontend/src/services/api.ts:687-699` |
| H14 | La pestaña "Autenticación & SSO" solo muestra estado y "contacte a soporte"; la API de config (`GET`/`PUT /auth/sso/config`) ya existe, nunca devuelve el secreto y exige rol admin para escribir. | `frontend/src/pages/UsersPage.tsx:1271-1376`; `backend/src/sso/admin_api.py:68-69`, `:87-101`, `:118-195` |
| H15 | Instalador: imágenes con `:latest` fijo, licencia `dev-demo.lic` **horneada** (`SENTINEL_LICENSE_TOKEN_FILE` fijo) y sin `SENTINEL_SSO_REDIRECT_URI`. `install.sh` hace `docker pull …engine:latest` explícito. | `elea-installer/docker-compose.yml:88`, `:109-110`, `:174`; `elea-installer/install.sh:56` |
| H16 | `publish-elea.sh` etiqueta y empuja **siempre** `:latest` además de la fecha. | `deploy/release/publish-elea.sh:34`, `:42` |
| H17 | El Hub corre en `node:20-alpine`: `fetch` nativo (undici) con `redirect: 'manual'` devuelve el 302 real con sus cabeceras, y `Headers.getSetCookie()` está disponible. | `client/Dockerfile:1` |

---

## D1 — Cómo el Hub intermedia el login y el callback con la cookie de estado firmada

**Problema**: la defensa CSRF del backend vive en una cookie que el backend emite para **su**
origen (H1, H2). El navegador del Hub nunca llega al backend (H9), así que esa cookie no puede
quedar en el navegador por sí sola.

| Opción | Cómo funciona | A favor | En contra |
|---|---|---|---|
| **A. Flujo pendiente en el servidor del Hub** | `GET /sso/login` (Hub) llama a `GET {backend}/auth/sso/login` con `redirect:'manual'`, toma `Location` y el valor de `sentinel_sso_state` del `Set-Cookie` (H17), lo guarda en un `Map` `sid → {cookie, vence}` (TTL 10 min, tope de entradas) y responde 302 al IdP. `GET /sso/callback` busca el pendiente del `sid`, lo **consume** (borra) y llama a `GET {backend}/auth/sso/callback?code&state` con `Cookie: sentinel_sso_state=…`. | Nada nuevo viaja al navegador; mismo patrón que las sesiones (H7); la cookie del backend nunca cambia de dueño; un solo uso por flujo. | Un reinicio del Hub a mitad del ingreso lo invalida → "volvé a intentar" (es exactamente el caso borde de la spec). |
| B. Re-emitir la cookie al navegador | El Hub copia el JWT de estado a una cookie propia (`path=/sso`, HttpOnly, `SameSite=Lax`) y en el callback la reenvía al backend. | Sobrevive a un reinicio del Hub. | El atributo `Secure` depende de si la petición llegó por HTTPS detrás del proxy (`X-Forwarded-Proto`): más superficie y un modo de fallo silencioso en `http://IP:8095`; no hay consumo de un solo uso del lado del Hub. |
| C. El navegador habla directo con el backend | Exponer `/api/v1/auth/sso/*` en el origen del Hub (proxy de ruta). | Reusa el flujo del panel tal cual. | Rompe FR-003/H9 (el Hub dejaría de ser el único cliente de la API); el callback devuelve JSON al navegador (H3) y haría falta JS que lo pase al Hub: el token pasaría por el navegador (FR-004). |

**Recomendación**: **A**. Además, cuando no hay pendiente (reinicio, otra pestaña, respuesta
repetida), el Hub **igual** llama al callback del backend sin cookie, para que el rechazo quede
auditado en un solo lugar (ver D6).

**Elección final: A**, confirmada por el coordinador (2026-10-05), con un requisito explícito
sobre la **atadura al navegador** (protección contra CSRF de login):

1. El pendiente se indexa por la cookie propia del Hub `elea_rag_sid` (HttpOnly, `SameSite=Lax`,
   `client/server.js:88-97`). Un callback que llega con otro `sid`, o sin él, **no encuentra
   pendiente** y se rechaza.
2. El pendiente guarda también el `state` que el Hub leyó del `Location` del backend. En el
   callback el Hub compara el `state` del query con el guardado (`crypto.timingSafeEqual`) **antes**
   de reenviar el canje; si no coincide, rechaza sin canjear (y deriva el rechazo al backend para
   la auditoría, D6). El backend vuelve a validar con su cookie firmada (H2): son dos controles
   independientes.
3. El pendiente se **consume una sola vez**: se borra al entrar al callback, salga bien o mal.
   Una respuesta repetida no encuentra pendiente.
4. Al emitir la sesión, el Hub **rota el `sid`** (nueva cookie, la sesión pasa al `sid` nuevo y el
   viejo queda sin sesión), para que un `sid` fijado de antemano no herede una sesión SSO. Solo en
   el camino SSO: el login con contraseña queda idéntico (FR-005).

Tiene tarea y test propios en tasks.md.

## D2 — Cómo sabe el Hub si mostrar el botón

| Opción | Cómo | Evaluación |
|---|---|---|
| **A. Proxy fail-closed** `GET /api/auth/sso/available` en el Hub | Llama a `GET {backend}/auth/sso/available` (H5). Solo `200` + `enabled === true` muestra el botón; 403, 5xx, red caída o cuerpo raro → `{enabled:false}`. Mismo criterio que el panel (`frontend/src/services/api.ts:687-699`). | Refleja en vivo el interruptor del panel (US3 AS2: desaparece en el próximo ingreso sin reiniciar). Pre-auth y sin sesión, igual que `/api/branding` (`client/server.js:314-316`). |
| B. Sumar `sso` a `/api/features` | `/api/features` es síncrono y leído de env (`client/server.js:1019-1027`). | Mezcla "motores configurados" con estado vivo de otro sistema; obligaría a volverlo async. |
| C. Variable de entorno del Hub | `HUB_SSO_ENABLED=true` | Rompe US3 (el admin apaga desde el panel, no desde el `.env`). |

**Recomendación**: **A**.

**Elección final: A**, confirmada por el coordinador (2026-10-05).

## D3 — Cómo se evita que el token viaje en la URL (FR-004)

Con D1-A el `access_token` va **solo** en el cuerpo de la respuesta del backend al servidor del
Hub (H3) y queda en el `Map` de sesiones (H7). El navegador recibe un `302 Location: /` y la
cookie `elea_rag_sid` que ya tenía. Lo único que aparece en una URL es lo que OIDC pone ahí por
definición: `code` y `state` en `/sso/callback?…`, de un solo uso e inútiles sin el secreto. El
302 inmediato a `/` hace que esa URL no quede como entrada del historial, y la respuesta lleva
`Referrer-Policy: no-referrer` y `Cache-Control: no-store`.

**Errores**: el Hub redirige a `/?sso_error=<código>` con un código de una **lista cerrada**
(contrato [hub-sso.md](contracts/hub-sso.md) §4); el texto lo arma la página. Nunca se copia el
`detail` del backend a la URL. Alternativa evaluada: guardar el error como "flash" en el `Map`
del `sid`; descartada porque se pierde con el mismo reinicio que quiere explicar.

**Elección final**: confirmada por el coordinador (2026-10-05) junto con D1: el token no sale
del servidor del Hub, y el error viaja como código de lista cerrada.

## D4 — La URI de retorno única (`_redirect_uri`) y el botón del panel

**Problema**: en la fase 1 `SENTINEL_SSO_REDIRECT_URI` apunta al **Hub**
(`https://<nombre>/sso/callback`). Pero el panel dibuja su botón con solo `enabled:true` (H13):
un admin que lo pulse arranca un flujo cuyo retorno cae en el Hub, sin pendiente ni cookie →
error. El panel tendría un botón roto (la spec dice que el panel sigue con contraseña).

| Opción | Cómo | Evaluación |
|---|---|---|
| **A. `/available` informa el origen de retorno** | `GET /auth/sso/available` suma `return_origin` = esquema+host+puerto de `SENTINEL_SSO_REDIRECT_URI` (o `null` si no está). El panel muestra el botón solo si `return_origin` es `null`/ausente (retrocompatible) o igual a `window.location.origin`. El Hub hace lo mismo y, si está en otro origen (p. ej. `http://172.16.0.120:8095`), el botón lleva a `${return_origin}/sso/login`. | Cero configuración nueva, automático en las dos líneas (en Sentinel la URI puede seguir apuntando al panel). Además resuelve el caso "el usuario entró por la IP y el retorno vuelve al nombre DNS" (cookies distintas por origen). Lo que expone pre-auth (el nombre público del Hub) ya lo ve cualquiera que pulse el botón: va en el `redirect_uri` de la URL de Microsoft. Por eso se informa **solo con `enabled:true`**; con `enabled:false` es `null`, y una variable mal formada también da `null`, nunca un 500 (N3 del QA v2, respuesta 3 de clarify). Cambio de base chico, con test. |
| B. Variable `SENTINEL_SSO_PANEL_LOGIN=false` | `/available` suma `panel_login`; el instalador de Elea la pone en `false`. | Una variable más que mantener coherente a mano con la URI; no ayuda al caso IP vs nombre. |
| C. Lista de URIs permitidas en el backend | `SENTINEL_SSO_REDIRECT_URIS` y elegir según origen. | Es "SSO también en el panel" (fuera de alcance, +0,5 a 1 día). |
| D. No hacer nada y documentarlo | El botón del panel falla con "volvé a intentar". | Botón roto visible para admins; contradice FR-006 en el espíritu. |

**Recomendación**: **A**.

**Elección final: A**, confirmada por el coordinador (2026-10-05).

## D5 — FR-008: no ofrecer "cambiar contraseña" a quien entró por SSO

Lo del cambio **obligatorio** ya se cumple: el callback no trae `must_change_password` (H11), así
que el modal forzado no se abre (H10). Falta ocultar el cambio **voluntario**.

| Opción | Cómo | Evaluación |
|---|---|---|
| **A. Marca de sesión en el Hub** | `setSession(req, {token, user, auth_method:'sso'})`; `/api/user/current` la expone; `index.html` oculta el botón "Contraseña" y nunca abre el modal si `auth_method === 'sso'`; `POST /api/auth/change-password` responde 409 para esas sesiones. | Solo Hub, sin tocar el backend. Oculta el botón también a un usuario existente que sí tiene contraseña pero entró por Microsoft: aceptable (puede entrar con contraseña y cambiarla ahí). |
| B. El backend informa `has_local_password` | Sumar el dato a la respuesta del callback y de `/users/me`. | Más preciso, pero toca contrato de base y la respuesta de login; no aporta a FR-008 más que A. |

**Recomendación**: **A**.

**Elección final: A**, confirmada por el coordinador (2026-10-05).

## D6 — Auditoría de los rechazos de flujo (FR-012 y caso borde "estado inválido o respuesta repetida")

H6 muestra que hoy los 400 de `state`/`code` no dejan rastro. La spec exige que **todo** ingreso
rechazado quede en la auditoría. **Decisión** (se deriva de la spec, no es opcional): en
`sso_callback` se emite `auth_sso_denied` (metadata-only: tipo y tenant, sin `state`, `code`,
email ni token) antes de cada 400. Es base genérica y viaja a Sentinel con `sso/`. El Hub no
audita por su cuenta: siempre deriva el rechazo al backend (D1). Confirmada por el coordinador
(2026-10-05).

**Tope contra la inundación de la auditoría** (riesgo detectado por el analyze; **elección final:
A**, decidida por el owner vía coordinador el 2026-10-05):

- **Problema**: la auditoría de los rechazos de flujo la puede disparar cualquiera sin autenticarse.
  El backend publica `:8091` en la LAN (`elea-installer/docker-compose.yml:91-92`) y el callback es
  público cuando la licencia trae `sso`, así que cada petición basura escribiría una fila.
- **Decisión**: en `backend/src/sso/api.py`, un tope fijo por minuto y **por proceso**
  (constante `~30/min`, ventana de 60 s) para los `auth_sso_denied` de rechazo de flujo
  (`state`, `code`, proveedor cambiado o sin configurar, URI de retorno faltante).
- **Extensión al canje fallido** (F1 del QA, [qa-plan.md](qa-plan.md); decisión del owner vía
  coordinador, 2026-10-05). La versión anterior de este punto afirmaba que los rechazos de
  identidad *"exigen un canje real con el IdP y no se pueden fabricar en masa"*. **Era falso
  para `api.py:302`**:
  - `GET /auth/sso/login` es público y le entrega a cualquiera una cookie de estado válida
    (`api.py:203-247`);
  - con esa cookie y su `state`, un `code` inventado pasa las validaciones (`api.py:260-273`)
    y dispara un `POST` real al `token_endpoint` del directorio (`entra.py:280`);
  - el rechazo cae en `except Exception` (`api.py:297-302`): una fila y una llamada saliente por
    intento.

  Por eso el canje fallido entra al tope, con **el mismo valor y la misma ventana, pero contador
  propio**. Así, una ráfaga de 400 sin cookie (la más barata) no consume el cupo de los canjes.
  Pasado el tope de canjes fallidos de la ventana, el callback **no llama al `token_endpoint`**
  (el chequeo va antes de `provider.exchange_code`, en `api.py`; `entra.py` no cambia), no
  escribe fila y responde el mismo `401 sso_identidad_no_verificada`. Los rechazos que exigen
  una identidad real del directorio (`api.py:313` sin email y `:379` JIT: baja o sin puestos)
  **no** tienen tope.
- **Excedente**: no escribe filas. Se resume en un `logger.warning` por ventana y por
  categoría (flujo, canje), con el conteo omitido. Es metadata-only, sin `state`, `code`, IP ni
  token.
- **Respuesta HTTP**: no cambia (mismo status y mismo `detail`). El tope limita la auditoría y
  las llamadas salientes, nunca el veredicto. **Efecto aceptado (límite conocido, N1 del QA
  v2)**: no es una ráfaga pasajera. La cookie de estado vale 10 minutos (`api.py:59`, `:95`), así
  que con **una** cookie alcanza mandar 30 canjes con `code` basura al inicio de cada ventana de
  60 s (0,5 pedidos/s sostenidos) para que **todo** canje legítimo de esa ventana reciba el 401
  sin llegar al directorio. Un tercero con acceso de red al backend puede mantener fuera de
  servicio el ingreso con Microsoft mientras sostenga ese ritmo. Solo se degrada el camino SSO:
  el login con contraseña no se afecta (FR-006). El owner acepta el trueque, que es el lado
  fail-closed (constitución, Security 3), y el diseño no cambia. Cómo se distingue del directorio
  caído: filas `auth_sso_denied` hasta el tope y después un `logger.warning` con el conteo omitido
  por ventana (guía de T039, caso de diagnóstico de T046).
- **Alcance**: cambio de base mínimo y genérico, con test. Viaja a Sentinel con `sso/`. La
  imagen del backend de Elea corre **un** proceso `uvicorn` (`backend/Dockerfile.standalone:35`),
  así que ahí "por proceso" equivale a "por instalación". La imagen prod de la base arranca
  `--workers ${WEB_CONCURRENCY:-2}` (`deploy/docker/entrypoint/backend.sh:38-41`): allí el tope
  efectivo es `tope × workers`. Sigue acotado y se anota en el HANDOFF.

Alternativas descartadas:

- **B** (sin tope, documentarlo): deja abierta la inundación.
- **C** (tope solo en el Hub): no cubre las llamadas directas a `:8091`.

## D7 — HTTPS delante del Hub (FR-010)

| Opción | Cómo | Evaluación |
|---|---|---|
| **A. Servicio TLS opcional en el instalador** | Servicio `hub-tls` (`nginx:<versión fijada>-alpine`) bajo un `profile` de compose, activado por `.env` (`HUB_TLS_HOSTNAME`, certificado y clave montados desde el host, `:ro`), que termina TLS en `:443` y pasa a `client:8095` con `X-Forwarded-Proto`. Sin certificado → el perfil no se activa y todo sigue por `:8095`. | Repetible y versionado; la vuelta atrás es apagar el perfil. Portable al wizard de Sentinel como enfoque. |
| B. Proxy del lado de Elea o configurado a mano en el host | Se documenta el requisito y Elea lo resuelve con su infraestructura. | Cero código, pero depende de la red de Elea y no queda versionado ni ensayado en la Etapa 1. |

**Recomendación original**: A.

**Elección final: B**, decidida por el owner vía coordinador (2026-10-05). El instalador **no**
suma un servicio TLS ni nginx al compose. El HTTPS lo pone el proxy de Elea, o se configura a
mano en el host, y se **documenta**:

- guía en `docs/docs/install-deploy/sso.md` (sección "Detrás de un proxy TLS": qué publica, a
  qué puerto reenvía, qué cabeceras pasa);
- paso explícito en SOLICITUD-A-ELEA.md (punto 3) y en DESPLIEGUE-Y-REVERSION.md (Etapa 3);
- lo que el stack necesita para funcionar detrás de un proxy TLS, y nada más:
  - `SENTINEL_SSO_REDIRECT_URI` con `https://<nombre>/sso/callback` (byte a byte la registrada);
  - el Hub **no depende** de `X-Forwarded-*`: todas sus redirecciones del flujo SSO son relativas
    (`Location: /…`) o van a la URL que devuelve el backend, y la comparación de origen de D4 la
    hace el **navegador** (`window.location.origin`), así que no hace falta `trust proxy` ni una
    variable nueva. El proxy puede mandar esas cabeceras (es lo estándar) sin efecto en el Hub;
  - la cookie `elea_rag_sid` conserva sus atributos actuales en el login con contraseña (sin
    `Secure`, porque la misma instalación sigue sirviendo `http://…:8095`). En el camino SSO con
    retorno `https://`, la cookie rotada lleva `Secure` y el flujo se ata además a una cookie
    `__Host-` (D12, por F6 del QA). Las dos cosas se deciden por el esquema del `redirect_uri`,
    sin `trust proxy`;
  - el proxy de Elea reenvía **todas** las rutas (incluidas `/sso/login` y `/sso/callback`, con
    su query intacto) al puerto `8095` del Hub; no hace falta publicar el backend (H9).

## D8 — Licencia de Elea con `sso`, montada desde el host

**Decisión técnica** (sale de DESPLIEGUE-Y-REVERSION.md): el instalador monta
`./license/` del host en `/app/config/licenses/host/` (`:ro`) y `SENTINEL_LICENSE_TOKEN_FILE`
pasa a ser `${SENTINEL_LICENSE_TOKEN_FILE:-/app/config/licenses/dev-demo.lic}`, así una
instalación sin licencia propia arranca igual que hoy (H15). La licencia nueva la emite el dueño
con `backend/scripts/issue_license.py --feature-flags monitor,sso`, con los mismos asientos y
vencimiento que la vigente.

**Firma**: con qué clave se firma. Hoy Elea corre con la licencia de desarrollo y
`SENTINEL_ALLOW_DEV_LICENSE=true` (`elea-installer/docker-compose.yml:109-110`).
Recomendación: **no cambiar la postura de firma en esta spec** (misma clave/`kid` que la
licencia vigente) y dejar el pase a clave de producción como decisión aparte.

**Elección final**: confirmada por el coordinador (2026-10-05): misma clave/`kid` que la
licencia vigente.

**Deuda conocida (se anota también en `HANDOFF-elea-a-sentinel.md`)**: la licencia de Elea sigue
firmada con la clave de **desarrollo** y la instalación corre con
`SENTINEL_ALLOW_DEV_LICENSE=true`. Esta spec **no** lo cambia. Pasar a una clave de producción
es una decisión aparte del dueño.

## D9 — Vuelta atrás real (`ELEA_TAG`, candidatas sin `latest`)

**Decisión técnica** (sin alternativas en disputa, la pide DESPLIEGUE-Y-REVERSION.md):

- `publish-elea.sh`: `LATEST=0` publica solo `:${VERSION}` (H16). Default `LATEST=1`: el uso de
  hoy no cambia.
- `elea-installer/docker-compose.yml`: las seis imágenes propias pasan a
  `ghcr.io/cluna-8/<imagen>:${ELEA_TAG:-latest}`; `install.sh` usa el mismo tag en su `docker pull`
  explícito (H15) y lo anota en el resumen final.
- `.env.example` del instalador documenta `ELEA_TAG` y `SENTINEL_SSO_REDIRECT_URI` (vacía = sin
  SSO, FR-009b).
- **Promover a `latest` = re-etiquetar, no reconstruir** (N2 del QA v2, fijado por el owner en
  el brief del 2026-10-05). `publish-elea.sh` hace `docker build` cada vez (`:34`) y empuja lo
  recién construido (`:41-42`). Si la Etapa 5 republicara con `LATEST=1`, el cliente recibiría
  bits distintos de los que se probaron en la Etapa 1 y ya corren en el server de producción de
  Elea, donde los usó el grupo piloto de 2 o 3 usuarios en la Etapa 4. Por eso el
  script suma el modo `PROMOTE_FROM=<tag>`: `pull` de la candidata, `tag` a `:${VERSION}` y
  `:latest`, y `push`, **sin** `build`. Los digests publicados son los de la candidata y se
  comparan con las líneas `PINNED …` (`:43`) anotadas al publicarla
  ([instalador-y-release.md](contracts/instalador-y-release.md) §5).
- **Residual, provisorio** (respuesta del coordinador a la pregunta 2 de clarify, 2026-10-06;
  **sujeto a la política de dependencias e imágenes reproducibles que va a definir el owner**, a
  partir de un análisis aparte con medición de la imagen en producción): `client/Dockerfile:10-11`
  copia solo `package.json` y corre `npm install --production`, aunque `client/package-lock.json`
  existe, y las capas `apk`/`pip` de `:4-6` no están fijadas. Con el re-etiquetado eso **no**
  afecta lo que se entrega en la Etapa 5 (mismos digests), pero una reconstrucción posterior (por
  ejemplo un hotfix) puede traer otras versiones. Esta spec no suma tarea en el tramo B; se anota
  también en el HANDOFF (T047).

## D10 — Formulario de configuración en el panel (US3)

**Decisión técnica**: el formulario vive en la pestaña existente (`UsersPage.tsx:1271`) y usa
solo `GET`/`PUT /auth/sso/config` (H14). Reglas: el campo secreto siempre vacío; vacío al
guardar = **omitirlo** (conserva el guardado, `admin_api.py:170-173`); el interruptor envía
`enabled`; se muestra `client_secret_configurado` como "cargado / no cargado"; los errores del
backend (`sso_habilitado_sin_secreto`, `sso_cifrado_no_disponible`) se muestran tal cual. Solo
`super_admin`/`tenant_admin` ven el formulario (mismo criterio de la pestaña). Es base: viaja a
Sentinel por cherry-pick.

## Ajustes del QA crítico del plan (D11 a D15)

Salen de [qa-plan.md](qa-plan.md) (2026-10-05). D11, D12 y D15 se consultaron al coordinador por
`ask` porque eran decisiones de diseño nuevas. D13 y D14 son ajustes que no abren decisiones.
Ninguno reabre D1 a D10.

### D11 — Pendientes del Hub: almacén lleno y límite de ritmo (F5)

**Problema**: con "expulsar el más viejo", quien pide `/sso/login` sin cookie unas 8 veces por
segundo expulsa a todos los ingresos en curso. Cada `GET /sso/login` sin cookie crea un `sid` y
un pendiente nuevos (`client/server.js:88-97`). Además, cada pedido cuesta en el backend una
consulta a la base y un descifrado del secreto (`api.py:207`, `:176`). Un límite por IP no sirve:
detrás del proxy del cliente todos los pedidos llegan desde la misma IP (D7).

| Opción | Cómo | Evaluación |
|---|---|---|
| A. Rechazar al que llega | Lleno después de barrer vencidos → `sso_reintentar` y no guarda. | Protege a los que están a mitad de ingreso. No acota la carga en el backend. |
| **B. A + límite de ritmo global** | Además, un contador global por proceso en `/sso/login` del Hub (`120/min`, ventana de 60 s, reloj inyectable). Pasado el límite → `sso_reintentar` sin llamar al backend. | Acota también la carga en el backend. Solo Hub. Efecto aceptado (N1 del QA v2): 2 pedidos/s **sostenidos** sin autenticarse dejan el botón en `sso_reintentar` para todos mientras dure; la contraseña sigue (FR-006). El valor `120/min` no sale de un dato medido: tras un reinicio del Hub (sesiones en memoria) el reingreso masivo legítimo también lo puede alcanzar. |

**Recomendación**: B. **Elección final**: ver la nota de cierre de esta sección.

### D12 — Login CSRF por cookie `sid` inyectada (F6)

**Problema**: la atadura al `sid` (D1) solo vale si el atacante no puede escribir `elea_rag_sid`
en el navegador de la víctima. La cookie no lleva `Secure` ni prefijo. Quien tenga posición de
red (un `http://<nombre>` antes del HTTPS) o un subdominio hermano puede fijar
`elea_rag_sid=A`, donde `A` es el `sid` de un flujo que el atacante inició con su identidad. Así
el callback de la víctima encuentra el pendiente del atacante y le abre una sesión con la
identidad del atacante. La rotación ocurre después y no lo impide.

| Opción | Cómo | Evaluación |
|---|---|---|
| A. Límite documentado | Como estaba. | No cierra nada. |
| B. `Secure` en el `sid` rotado | Si el `redirect_uri` que devuelve el backend empieza con `https://`, la cookie rotada lleva `Secure`. | Evita que la sesión viaje en claro. No impide inyectar el `sid` **antes** del ingreso. |
| **C. B + cookie de atadura `__Host-`** | En `/sso/login`, con retorno `https://`, el Hub emite `__Host-sso_flow` (aleatoria, `Secure; HttpOnly; Path=/; SameSite=Lax`, 10 min) y guarda su valor en el pendiente. El callback exige `sid` **y** atadura. Con retorno `http://` (desarrollo en `localhost`), solo `sid`, como en D1. | El prefijo `__Host-` impide que esa cookie se escriba desde `http://` o desde un subdominio, así que el atacante no puede plantar su atadura en la víctima. Solo Hub y sin `trust proxy`: el esquema sale del `redirect_uri`, que Entra respeta byte a byte. |

**Recomendación**: C. **Elección final**: ver la nota de cierre de esta sección.

### D13 — Pantalla del Hub testeable sin dependencias nuevas (F2)

**Problema**: T018 del plan anterior cambiaba `client/public/index.html` sin ningún test. El Hub
no tiene `jsdom` (`client/package.json:7-15`) y ningún test carga `index.html`.

| Opción | Evaluación |
|---|---|
| **A. Módulo puro `client/public/sso-ui.js`** | Las tres decisiones de la pantalla (destino del botón, texto del error, ofrecer "Contraseña") van en funciones puras, testeadas con `node --test`. `index.html` solo las cablea, y un test estático verifica el cableado y que el error no se pinte con `innerHTML` (XSS reflejado por `?sso_error=`). Respeta "ninguna dependencia nueva" (plan, Technical Context). |
| B. `jsdom` como devDependency | Cubre el DOM real, pero suma una dependencia y contradice el plan. |

**Elección**: A (ajuste: no cambia la arquitectura y respeta una restricción ya escrita).

### D14 — Gates automáticos: marca blanca del Hub y `LATEST` (F3, F9)

- **Marca blanca del Hub (FR-013, FR-014)**: los gates de hoy no miran `client/`.
  `test_no_engine_name.sh:19-31` revisa el bundle del panel y `deploy/branding`;
  `test_docs_*` revisan el sitio. Se suma un test `client/tests/unit/whitelabel-hub-056.test.js`
  (solo `node:fs`, corre en `npm test` del Hub) con dos alcances:
  - archivos **nuevos** de la 056 (`client/sso.js`, `client/public/sso-ui.js`): ni la lista
    compartida `deploy/release/checks/prohibited_names.txt`, ni los motores internos de
    documentos y presentaciones (lista local del test), ni `Elea`/`Eleia`;
  - `client/public/index.html` y `client/server.js` completos: solo la lista compartida.
    `index.html:2258` ya nombra un motor interno en un comentario; sumarlo a la lista compartida
    afectaría otros gates y es decisión del owner, así que queda fuera.

  Se cablea a `make -C deploy check` con un target `check-hub-whitelabel` que corre ese archivo
  con `node --test` (sin Docker ni `npm ci`).
- **`LATEST` del script de publicación**: `make -C deploy check` corre una lista explícita
  (`deploy/Makefile:42`); un script nuevo en `checks/` no entra solo. El tramo D suma el target
  `check-release-publish` (con el `docker` de prueba, sin Docker real) y es dueño de
  `deploy/Makefile`. El tramo E, que corre después y no en paralelo, suma
  `check-hub-whitelabel`.
- **Panel**: el bundle ya lo cubre `test_no_engine_name.sh`. Los textos nuevos del formulario se
  verifican además en el test de vitest del tramo C.

### D15 — Mensaje del canje fallido en el callback (F10)

**Problema**: cualquier excepción del canje (directorio caído, `invalid_client` por secreto
vencido, `code` vencido) sale como `401 sso_identidad_no_verificada` (`api.py:297-307`). El texto
del Hub decía "Microsoft no confirmó tu identidad", que culpa a la persona cuando falló la
instalación.

| Opción | Evaluación |
|---|---|
| **A. Solo Hub** | Texto neutro: "No se pudo confirmar el ingreso con Microsoft. Si se repite, avisá al administrador." La guía dice qué mensaje esperar cuando vence el secreto y dónde ver la causa (log del backend, `entra.py:109`, `_causa`). La base no cambia. |
| B. Cambio de base | El backend separa la falla de la instalación con un `detail` nuevo, y el Hub suma un código. Toca el contrato de la 017 y el comportamiento del panel. |

**Recomendación**: A, por la regla de base mínima. **Elección final**: ver la nota de cierre de
esta sección.

**Nota de cierre (D11, D12, D15 y alcance de F8)**: aprobadas por el owner vía coordinador el
2026-10-05 (`ask` del redactor, respuesta *"Sí, aprobadas por el owner"*). Quedan registradas
como Clarifications de spec.md (Session 2026-10-05) y se traducen en FR-016:

- **D11: elección final B** (almacén lleno → rechaza al que llega; límite de ritmo global de
  `120/min` en `/sso/login`).
- **D12: elección final C** (cookie de atadura `__Host-sso_flow` y `Secure` en el `sid` rotado,
  solo con retorno `https://`; solo Hub, sin `trust proxy`).
- **D15: elección final A** (texto neutro en el Hub y guía; la base no cambia).
- **F8**: los `404 sso_no_configurado` y `500 sso_redirect_uri_no_configurado` del callback se
  auditan como rechazos de flujo, dentro del tope de flujo (D6; contrato
  [guardian-sso-api.md](contracts/guardian-sso-api.md) §2).
- **F1**: el canje fallido usa un contador propio, con el mismo valor (`30/min`) y la misma
  ventana que el de flujo (D6).

## Mejores prácticas consideradas

- **OIDC authorization code con cliente confidencial**: el canje lo hace un servidor (el
  backend), la URI se registra como plataforma **Web** (ya documentado en
  `docs/docs/install-deploy/sso.md`).
- **Cookies**: la del Hub sigue `SameSite=Lax`, que viaja en el 302 de vuelta del IdP
  (navegación de nivel superior por GET). `elea_rag_sid` no cambia en el login con contraseña;
  en el camino SSO con retorno `https://` la cookie rotada suma `Secure` (D12).
- **Memoria del Hub**: el `Map` de pendientes tiene TTL de 10 min (el mismo del JWT de estado,
  `api.py:59`) y un tope de entradas, para que un cliente que pide `/sso/login` en bucle sin
  cookie no haga crecer la memoria sin límite. Lleno, rechaza al que llega y no expulsa a nadie
  (D11).
- **White-label**: los textos del Hub dicen "Ingresar con Microsoft" (nombre del proveedor de
  identidad, no un componente interno) y toman la marca de `/api/branding`
  (`client/server.js:46-52`). `Microsoft` no está en
  `deploy/release/checks/prohibited_names.txt`.

## Trazabilidad del QA

Resolución de cada hallazgo de [qa-plan.md](qa-plan.md) (2026-10-05), con el `archivo:línea` del
artefacto que lo resuelve. Rutas relativas a `specs/056-sso-entra-id-hub/`. Los IDs de tarea son
los de tasks.md regenerado; los que cita qa-plan.md son los de la versión anterior.

| # | Sev. | Resolución | Dónde queda resuelto |
|---|---|---|---|
| F1 | Alta | El tope de D6 se extiende al canje fallido (`api.py:297-302`), con contador propio y el mismo valor y ventana (30/min, 60 s). Pasado el tope no escribe fila ni llama al `token_endpoint`; el 401 no cambia. Los rechazos de identidad (`api.py:313`, `:379`) siguen sin tope. Se corrige la frase falsa de la versión anterior (research.md:149-151). Test pedido: cookie válida + `code` basura, `tope + 5` veces → `tope` eventos y `tope` llamadas al proveedor, 401 intacto | research.md:148-172 (corrección y decisión); spec.md:66-71 (Clarification) y spec.md:298-309 (FR-012); contracts/guardian-sso-api.md:75 y :83-99 (tabla y tope); data-model.md:82; tasks.md:95 (T005, el test) y tasks.md:111-115 (T008) |
| F2 | Alta | La lógica de la pantalla va a un módulo puro, `client/public/sso-ui.js`, testeado con `node --test` y sin `jsdom` (D13). Cubre FR-001, FR-006, FR-008, US1 AS5 y US2 AS2/AS3, el `sso_error` con HTML y el cableado de `index.html` sin `innerHTML` | research.md:296-306 (D13); contracts/hub-sso.md:128-150 (§6) y :181-191 (tests 17 a 20); tasks.md:163-167 (T014) y tasks.md:204-210 (T021) |
| F3 | Alta | Gate automático de marca blanca del Hub: `client/tests/unit/whitelabel-hub-056.test.js` (lista compartida, motores internos con lista local, `Elea`/`Eleia` en lo nuevo), en `npm test` y en `make -C deploy check` con el target `check-hub-whitelabel`. El panel lo cubre el test de vitest de T024 | research.md:308-329 (D14); contracts/hub-sso.md:193-201 (tests 21 y 22); contracts/instalador-y-release.md:87-98 (§6); tasks.md:168-172 (T015), tasks.md:258 (T024, panel) y tasks.md:368 (T042) |
| F4 | Media | En el Hub, `return_origin: null` ⇒ sin botón. El panel conserva la regla retrocompatible | spec.md:258-262 (FR-001) y spec.md:317-326 (FR-015); contracts/guardian-sso-api.md:32-35; contracts/hub-sso.md:137; contracts/instalador-y-release.md:17; tasks.md:142 (T011) y tasks.md:164 (T014) |
| F5 | Media | Almacén lleno → se rechaza al que llega, sin expulsar; límite de ritmo global de 120/min en `/sso/login`, sin llamar al backend (D11 = B, aprobada por el owner) | research.md:264-277 (D11) y research.md:346-359 (cierre); spec.md:81-85 (Clarification), spec.md:225-228 (Edge Case) y spec.md:327-333 (FR-016); contracts/hub-sso.md:40-55; data-model.md:37-53; tasks.md:135-138 (T010) y tasks.md:146 (T011) |
| F6 | Media | Con retorno `https://`: cookie de atadura `__Host-sso_flow` exigida en el callback, agregada sin pisar el `Set-Cookie` del `sid`, y `Secure` en el `sid` rotado; con `http://localhost`, solo el `sid` (D12 = C, aprobada por el owner). Solo Hub, sin `trust proxy` | research.md:279-294 (D12) y research.md:346-359 (cierre); spec.md:86-91 (Clarification), spec.md:229-231 (Edge Case) y spec.md:327-333 (FR-016); contracts/hub-sso.md:47-51, :58-63, :71-78 y :83-87; data-model.md:25 y :63-67; tasks.md:144-145 (T011), tasks.md:155-162 (T013), tasks.md:183 (T018), tasks.md:189-195 (T019) y quickstart.md:90-106 (prueba en navegador) |
| F7 | Media | spec.md enmendada con `speckit-clarify`: Clarifications de la sesión 2026-10-05 (D1 a D8, F1, F5, F6, F8, F10), FR-010 reformulado (documentar y verificar el HTTPS del proxy del cliente), FR-012 con la excepción del tope, FR-015 (`return_origin`) y FR-016 nuevos, cabecera y estimación actualizadas | spec.md:7-8 (Status), spec.md:38-96 (Clarifications), spec.md:291-295 (FR-010), spec.md:298-309 (FR-012), spec.md:317-326 (FR-015), spec.md:327-333 (FR-016), spec.md:401-404 (estimación); plan.md:6-15 |
| F8 | Media | Los `404 sso_no_configurado` y `500 sso_redirect_uri_no_configurado` del callback se auditan como rechazos de flujo, dentro del tope de flujo. `_redirect_uri` se resuelve antes del `try` del canje | spec.md:77-80 (Clarification) y spec.md:298-309 (FR-012); contracts/guardian-sso-api.md:72 y :74; tasks.md:93 (T005) y tasks.md:106-108 (T007) |
| F9 | Media | El tramo D es dueño de `deploy/Makefile` y suma el target `check-release-publish` a la lista de `check`; el tramo E suma `check-hub-whitelabel` después, nunca en paralelo | research.md:323-327 (D14); contracts/instalador-y-release.md:94; tasks.md:48 (propiedad del tramo D), tasks.md:298 (T031) y tasks.md:408-410 (orden D → E) |
| F10 | Media | Texto neutro para `sso_identidad_no_verificada` en el Hub (más el sufijo común que recuerda la contraseña), que no culpa a la identidad; la guía dice qué esperar cuando vence el secreto y dónde ver la causa. Sin código nuevo ni cambio de base (D15 = A, aprobada por el owner) | research.md:331-344 (D15) y research.md:346-359 (cierre); spec.md:92-96 (Clarification) y spec.md:248-252 (Edge Case); contracts/hub-sso.md:106 y :112-113; quickstart.md:117-121; tasks.md:204 (T021) y tasks.md:345 (T039) |
| B1 | Baja | Límite conocido documentado (guía, HANDOFF, quickstart). `prompt=select_account` queda fuera: es un cambio de base en `entra.py` | spec.md:235-238 (Edge Case); quickstart.md:82; tasks.md:346 (T039), tasks.md:387 (T047) y tasks.md:465-466 (riesgo aceptado) |
| B2 | Baja | Checklist de activación: resetear o forzar el cambio de los usuarios con cambio obligatorio pendiente antes de activar | spec.md:239-241 (Edge Case); tasks.md:351 (T040) y tasks.md:359 (T041) |
| B3 | Baja | La URL al backend se arma con `URLSearchParams`; test con `&`, `=` y `#` | contracts/hub-sso.md:90-92 y :175 (test 12); tasks.md:151 (T012) y tasks.md:193 (T019) |
| B4 | Baja | Riesgo aceptado: solo corta un ingreso en curso, no da acceso | tasks.md:462-464 (Riesgos aceptados) |
| B5 | Baja | `return_origin` con `scheme`, `hostname` y `port` (nunca `netloc`), sin el puerto por defecto y en minúsculas; casos en T004 | contracts/guardian-sso-api.md:22 y :45-48 (tests 3 y 4); tasks.md:85-87 (T004) y tasks.md:101 (T006) |
| B6 | Baja | `Cache-Control: no-store` en `/api/auth/sso/available` del Hub, con test | contracts/hub-sso.md:32-33; data-model.md:74; tasks.md:142 (T011) y tasks.md:177 (T017) |
| B7 | Baja | SC-002 con datos reales se cierra en el server de producción de Elea (Etapa 4: grupo piloto de 2 o 3 usuarios y después el resto), anotado en DESPLIEGUE y en el HANDOFF | tasks.md:358 (T041) y tasks.md:390 (T048) |
| B8 | Baja | (a) la sección del Hub en `sso.md` se marca "solo si hay Hub"; (b) `ELEA_TAG` se porta como enfoque (FR-014 lo exceptúa como nombre propio del instalador); (c) el tope por proceso se anota en el HANDOFF como `tope × workers` | research.md:173-177 (D6, alcance); spec.md:313-316 (FR-014); tasks.md:341 (T039), tasks.md:381-383 y tasks.md:386 (T047) |
| B9 | Baja | El tramo 0 ignora en `.gitignore` la licencia y el compose de prueba local, y lo verifica con `git check-ignore`. La firma dev sigue como deuda declarada | tasks.md:44 (propiedad del tramo 0), tasks.md:64-67 (T003) y tasks.md:467-468 (riesgo aceptado) |

**Nota sobre las citas de la tabla anterior**: sus `archivo:línea` corresponden a los artefactos
del commit `5d689b5`. La enmienda del QA v2 insertó líneas en spec.md, tasks.md y los contratos;
las citas vigentes de esa enmienda están en la tabla siguiente.

## Trazabilidad del QA v2

Resolución de cada hallazgo nuevo de [qa-plan-v2.md](qa-plan-v2.md) §Hallazgos nuevos, con
`archivo:línea` de la enmienda (2026-10-05 y 2026-10-06; preguntas de `speckit-clarify`
contestadas por el coordinador). Rutas relativas a `specs/056-sso-entra-id-hub/`. tasks.md **no se
renumeró**: N7 suma la tarea T049 al tramo B.

| # | Sev. | Resolución | Dónde queda resuelto |
|---|---|---|---|
| N1 | Media | Clarify 1 = A (owner): límite conocido aceptado, sin cambio de diseño (D6 y D11 siguen). Ya no se dice "ráfaga": un ritmo **sostenido** de 0,5 pedidos/s (callback del backend, una sola cookie de estado) a 2 pedidos/s (`/sso/login` del Hub), sin autenticarse, deja sin SSO a todos mientras dure; la contraseña sigue. `120/min` no sale de un dato medido. Guía, HANDOFF y un caso de diagnóstico en la prueba | spec.md:98-107 (Clarification), spec.md:255-262 y :263-270 (Edge Cases); research.md:169-178 (D6) y research.md:299 (D11); contracts/guardian-sso-api.md:109-115; contracts/hub-sso.md:46-50; quickstart.md:131-137 (§4 caso 8); tasks.md:378 (T039), tasks.md:410 (T046), tasks.md:421 (T047) y tasks.md:505-509 (Riesgos aceptados) |
| N2 | Media | Promover a `latest` = re-etiquetar y empujar **los mismos digests** de la candidata, sin `build` (modo `PROMOTE_FROM`), con comparación de las líneas `PINNED`. Clarify 2 = A **provisorio**: el lockfile de `client/Dockerfile:10-11` queda como residual, sujeto a la política de imágenes reproducibles del owner, sin tarea nueva. Vocabulario del owner: el server de Elea es producción; "piloto" es el grupo de 2 o 3 usuarios | spec.md:114-119 (Clarification); research.md:254-261 (D9) y research.md:263-270 (residual); contracts/instalador-y-release.md:74-107 (§5) y :116 (gate); quickstart.md:141-145 (§5 paso 1) y :163-165; tasks.md:324-329 (T030), tasks.md:330 (T031), tasks.md:390-391 (T041), tasks.md:409 (T045), tasks.md:423 (T047, residual) y tasks.md:426 (T048) |
| N3 | Baja | Clarify 3 = A: `return_origin` es `null` con `enabled:false`; `try/except ValueError` → `null` (puerto inválido o fuera de rango, IPv6 mal cerrado), nunca 500; corchetes para IPv6 | spec.md:120-124 (Clarification) y spec.md:364-367 (FR-015); research.md:107 (D4); contracts/guardian-sso-api.md:22, :24-25 y :50-57 (tests 5b, 7 y 8); tasks.md:97-101 (T004) y tasks.md:115 (T006) |
| N4 | Baja | El tope de canje **reserva** el lugar antes de llamar (incrementa y compara atómico), lo devuelve si el canje sale bien, y el contador se toca desde el event loop o con `threading.Lock`; test concurrente con un doble lento | contracts/guardian-sso-api.md:98-104; tasks.md:109 (T005) y tasks.md:126-128 (T008) |
| N5 | Baja | `destinoBoton` exige un origen bien formado (`new URL(x).origin === x`, `http:`/`https:`); casos con comilla, espacio, `<`, `\\`, credenciales, ruta y barra; botón con `createElement` + `textContent`, nunca `innerHTML` | contracts/hub-sso.md:151, :158-164 (§6, cableado), :212-217 (test 17) y :220-222 (test 20); tasks.md:181 y :185 (T014), tasks.md:223 y :225 (T021) |
| N6 | Baja | Todo texto nuevo visible, incluida la etiqueta del botón (`TEXTO_BOTON`), vive en `sso-ui.js`; test 23 de lectura estática de `index.html`. Límite honesto: `client/server.js:19` ya contiene `ELEA_*`, así que sus rutas nuevas no se verifican contra FR-014 por lectura | contracts/hub-sso.md:152 y :233-238 (test 23); tasks.md:184 (T014), tasks.md:189-191 (T015) y tasks.md:223 (T021) |
| N7 | Baja (preexistente) | Clarify 4 = B (owner, 2026-10-06): se arregla en la 056. Tarea **nueva T049** del tramo B, commit aparte `fix(hub)`: rotar el `sid` en `POST /api/auth/login` (`client/server.js:258-273`) y `parseCookies` (`:78-86`) con `try` (cookie mala ignorada, nunca 500). FR-005 se mantiene: lo visible no cambia | spec.md:125-130 (Clarification), spec.md:273-275 (Edge Case) y spec.md:315-319 (FR-005); contracts/hub-sso.md:14-17, :139-140 (§5) y :200-208 (tests 16, 24 y 25); data-model.md:61; tasks.md:54 (propiedad), tasks.md:222 (T020), tasks.md:243 (T022), tasks.md:253 (T023), tasks.md:255-261 (T049), tasks.md:416 (T047) y tasks.md:451, :459 (orden) |
| N8 | Baja | La respuesta del callback lleva **exactamente** el `sid` rotado y el borrado de `__Host-sso_flow`, los dos (lista de `Set-Cookie`, se reemplaza solo la entrada `elea_rag_sid`); test con `getSetCookie()` | contracts/hub-sso.md:95-99 (§3) y :184-189 (test 6); tasks.md:166 (T012), tasks.md:209 (T019) y tasks.md:217 (T020) |
| T002 | — | La línea base de las partes con Docker sale del último run del CI de `main` (run `35871397897`: 18 fallas conocidas + `check-docs`, que se arregla aparte) y no se corre en local | tasks.md:71-73 (T002) |
