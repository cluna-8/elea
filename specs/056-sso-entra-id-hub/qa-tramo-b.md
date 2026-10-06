# QA crítico — Tramo B (Hub) de la 056

**Rama**: `cluna-8/056-tramo-b-hub` (HEAD `a26e8d6`) · **Fecha**: 2026-10-06 · **Rol**: qa-critico (solo lectura y
tests de Node; sin Docker, sin tocar código de producto).
**Contra**: [contracts/hub-sso.md](contracts/hub-sso.md), [spec.md](spec.md) (FR-001 a FR-016 que tocan el Hub),
[research.md](research.md) (D1 a D5, D11, D12, D15) y la constitución del repo.
**Diff revisado**: `git diff main...HEAD -- client/` (commits `dba9212`, `18032e1`, `ee6733b`; `c60d55f` solo
toca `.gitignore`).

## Veredicto

**Sin hallazgos de seguridad.** Las defensas que el contrato pide (atadura `sid` + `__Host-sso_flow`, un solo uso,
rotación de `sid`, token fuera de la URL, cookies, límites, lista cerrada, 409, marca blanca) están implementadas
como el contrato las describe y cada una tiene un test que fallaría si se la quitara.
**Ningún escenario de los 25 del contrato §7 queda sin test.**

Quedan **3 observaciones no bloqueantes** (O1 a O3) y **1 estado incorrecto de tarea** (O4: T003), más 2
notas informativas (N1, N2). Ninguna cambia el veredicto de seguridad; O1 y O4 necesitan acción antes del PR.

## Comandos corridos

| Comando | Resultado |
|---|---|
| `cd client && npm test` | `tests 192 · suites 0 · pass 192 · fail 0 · cancelled 0 · skipped 0` (9,9 s). Incluye los 5 archivos nuevos de la 056 y todos los preexistentes del Hub. |
| `git check-ignore -v backend/config/licenses/dev-sso-local.lic docker-compose.sso-local.yml` | Las dos quedan ignoradas (`.gitignore:91` y `:92`). |
| `node <scratchpad>/origen.js` (sonda propia, fuera del repo) | 54 orígenes adversariales contra `destinoBoton`; tabla en O1. |
| `node -e "new URL('https://a\"onmouseover=x').origin === x"` | `true` para `"`, `'`, `;`, `=` en el host: la regla `origin === x` del contrato **no** los descarta (confirma lo que halló el dev). |
| `git diff main...HEAD --name-only` fuera de `specs/` y `client/` | Solo `.gitignore` y `AGENTS.md` (este último no es del Tramo B). |

No se corrieron `frontend` ni `backend` ni nada con Docker: el Tramo B no los toca (`git diff` no tiene archivos
de `frontend/` ni `backend/`) y el brief prohíbe Docker sin aviso del owner.

## 1. Seguridad, punto por punto

| # | Requisito | Dónde se cumple | Test que lo fija | Estado |
|---|---|---|---|---|
| 1 | **Atadura del pendiente** al `sid` y, con retorno `https://`, a `__Host-sso_flow` (FR-016, D1 req. 1-2, D12) | `client/server.js:470` (`tomar(req.sid)`), `:471` (lee la cookie), `:479-481` (`state` **y** atadura, ambos con `iguales`), `:457` (atadura solo si `redirect_uri` empieza con `https://`) | `test_sso_flujo_056.test.js:312` (otro `sid`), `:326` (sin cookie), `:337` (otra cookie, 4 variantes de largo), `:349` (atadura de uno y `sid` de otro), `:369` (`state` distinto) | OK |
| 2 | **Comparación en tiempo constante**, largo distinto = no coincide, sin lanzar | `client/sso.js:72-78` (`Buffer` + `timingSafeEqual` tras comparar el largo en bytes; vacío o no-string → `false`) | `sso-pendientes-056.test.js` (`iguales`, 2 tests) | OK |
| 3 | **Un solo uso**, salga bien o mal | `client/sso.js:39-48` (`tomar` borra antes de mirar el vencimiento); `client/server.js:470` lo llama antes de cualquier `await`, así que dos callbacks simultáneos no pueden consumir el mismo pendiente | `test_sso_flujo_056.test.js:359` (se consume aunque falle la atadura), `:391` (repetido), `:429` (también tras `error=`) | OK |
| 4 | **Rechazo sin canje y sin cookie de estado**, pero igual llega al backend para auditar (D6) | `client/server.js:482-486`: `ssoLlamarCallback(entrada, null)` → sin cabecera `Cookie` (`:396`) | `:312-322`, `:326`, `:337`, `:369`, `:405`, `:417` verifican `llamadas.length === 1` y `sinCookie(...)` | OK |
| 5 | **Rotación de `sid`** al emitir sesión (D1 req. 4) | `client/server.js:141-148` (`sid` nuevo de 24 bytes, borra el viejo, reemplaza solo la entrada `elea_rag_sid`); usada en `:313` (contraseña) y `:501-506` (SSO) | `test_sso_flujo_056.test.js:124` (sesión bajo el nuevo, el viejo sin sesión), `test_login_sid_056.test.js:45`, `:60`, `:86`, `:97`, `:108` | OK |
| 6 | **Token fuera de la URL, de la respuesta y del log** (FR-004) | El `access_token` solo se copia a `sessions` (`client/server.js:501-506`); la respuesta es `302 /` (`:508`); los errores redirigen por código de lista cerrada (`:379-381`); no hay `console.*` en el camino SSO (`grep` de `console.` no da líneas entre `:364` y `:512`) | `test_sso_flujo_056.test.js:206` (ningún header ni cuerpo contiene el token), `:292` (captura `console` y busca token, JWT de estado y `code`), `test_sso_hub_056.test.js:190` (el JWT de estado nunca llega al navegador) | OK |
| 7 | **Cookies** | `__Host-sso_flow`: `Secure; HttpOnly; Path=/; SameSite=Lax; Max-Age=600` (`:462`), sin `Domain` (requisito del prefijo), borrado con los mismos atributos y `Max-Age=0` (`:473`). `sid` rotado: `HttpOnly; Path=/; SameSite=Lax` y `Secure` solo si el pendiente tenía atadura (`:105-107`, `:501-506`). `sid` de contraseña sin `Secure` (FR-005). | `test_sso_hub_056.test.js:199`, `:214`, `:232`; `test_sso_flujo_056.test.js:144`, `:165` (lista exacta: sid rotado + borrado, sin el sid viejo) | OK |
| 8 | **Cookies sin pisarse** (N8) | `listaSetCookie`/`agregarSetCookie` (`:111-117`) y el filtro por prefijo en `:145-146` | `test_sso_flujo_056.test.js:165`, `:183`; `test_sso_hub_056.test.js:232` | OK |
| 9 | **Límite de ritmo** 120/min, global, sin llamar al backend | `client/server.js:425` (antes de cualquier `fetch`); `client/sso.js:10`, `:53-67` (el rechazo no cuenta ni extiende la ventana) | `test_sso_hub_056.test.js:261` (sin llamada al backend ni pendiente), `:279` (ventana siguiente), `:428` (el login con contraseña sigue), `sso-pendientes-056.test.js` (3 tests) | OK |
| 10 | **Tabla llena**: rechaza al que llega, no expulsa a nadie | `client/sso.js:30-37` (barre vencidos y recién ahí rechaza; reemplazar un `sid` ya presente no cuenta como nuevo); `client/server.js:458-460` | `test_sso_hub_056.test.js:292` (llena hasta `MAX_PENDIENTES`, el en curso sigue consumible), `sso-pendientes-056.test.js` (3 tests) | OK |
| 11 | **Errores de lista cerrada**; el `detail` nunca se copia | `client/sso.js:82-124` (`codigoError` solo mira status y prefijo); `client/server.js:379-381`; `sso-ui.js:32-36` (clave desconocida → `sso_error`, el valor no se pinta); `index.html:1083` (`textContent`) | `sso-pendientes-056.test.js` (mapeo completo y «nunca copia el detail»), `sso-ui-056.test.js` («desconocido, vacío o con HTML → genérico»), `test_sso_flujo_056.test.js:269`, `test_sso_hub_056.test.js:342` | OK |
| 12 | **409 en change-password** sin llamar al backend (FR-008) | `client/server.js:333-335` | `test_sso_flujo_056.test.js:230` (409 y backend sin llamadas), `test_sso_hub_056.test.js:387` (sesión de contraseña: sigue proxy) | OK |
| 13 | **`code`/`state` con `&`, `=`, `#`** (B3) | `client/server.js:392-399` (`URLSearchParams`, valores ya decodificados; `texto()` descarta arrays y objetos en `:475`) | `test_sso_flujo_056.test.js:192`, `:380` (ausente, vacío, repetido como array) | OK |
| 14 | **Fail-closed de `available`** | `client/server.js:406-421` (timeout 3 s, `enabled === true` estricto, `no-store` también en el camino de error) | `test_sso_hub_056.test.js:83-165` (11 casos, incluido timeout) | OK |
| 15 | **XSS por `?sso_error=` y por `return_origin`** | `index.html:1070-1076` (`createElement` + `href` + `textContent`), `:1083`; sin `innerHTML` en el bloque `sso-056` | `sso-ui-056.test.js` (4 tests de cableado estático, incluido «sin innerHTML») | OK |
| 16 | **Marca blanca** (FR-013, FR-014) | `sso.js` y `sso-ui.js` sin marca ni motores; `index.html` sin literal del botón ni «microsoft» | `whitelabel-hub-056.test.js` (6 tests) | OK |

Sobre FR-012: los cortes del Hub (límite de ritmo, tabla llena) no llegan al backend (`client/server.js:425`, `:458`), como pide la spec.

## 2. Foco extra del coordinador

### 2.1 Defensa de `return_origin` en `sso-ui.js` (hub-sso.md §6, N5)

**Conclusión: correcta y suficiente contra XSS por atributo y `javascript:`; el contrato necesita corregirse.**

- **El problema es real**: `new URL(x).origin === x` acepta `"`, `'`, `;`, `=` y otros en el host (comprobado arriba), así que
  la regla del contrato §6 sola deja pasar `https://a"onmouseover=x`.
- **La corrección**: `client/public/sso-ui.js:44` — `FORMA_ORIGEN = /^https?:\/\/(\[[0-9a-f:.]+\]|[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::[0-9]{1,5})?$/`,
  más la regla del contrato (`:46-55`). Es una lista blanca anclada, sin bandera `m` (`$` no tolera un `\n` final; comprobado), con
  host `[a-z0-9.-]` o IPv6 entre corchetes `[0-9a-f:.]` y puerto numérico.
- **Defensa en profundidad**: el valor además solo llega a `boton.href` (`index.html:1074`), nunca a HTML parseado.
- **Sonda de 54 casos** (`destinoBoton({enabled:true, return_origin: c}, 'https://otro.local')`):
  - `null` (rechazados): `javascript:`/`JAVASCRIPT:`/`data:`, `//evil.com`, `"`, `'`, `;`, `%22`, `` ` ``, `$`, `,`, `|`, `{`, `*`, espacio, `\n`, `\t`, NUL, `<`, `\`, credenciales, ruta, query, fragmento, barra final, mayúsculas, puerto por omisión (`:443`, `:80`), puerto fuera de rango (`:99999`), ceros (`:080`), host con `_`, host con punto final, IDN sin punycode, `-a.com`, `0x7f.1`, corchetes mal cerrados o con `<script>`, IPv6 con letras no hex.
  - Aceptados (esperados): `https://hub.ejemplo.local`, `…:8443`, `http://localhost:8095`, `http://172.16.0.120:8095`, `https://[::1]:8443`, `https://[2001:db8::1]`, `https://1.2.3.4`, `https://xn--bcher-kva.example`.
  - Aceptados sin ser útiles, **inocuos** (solo caracteres de la lista blanca, van a `href`): `https://hub.ejemplo.local:0`, `https://a..b`.
  - Rechazado aunque podría ser legítimo: `https://[::ffff:1.2.3.4]` (la URL lo normaliza y `origin !== x`; irrelevante en la práctica).
- **Corrección que necesita el contrato** (a aplicar con el skill `speckit-*`, no a mano): en `hub-sso.md` §6, fila
  `destinoBoton`, definir «bien formado» como las dos condiciones **juntas**: (a) la regla actual (`new URL` no lanza, `http:`/`https:`,
  `origin === return_origin`) **y** (b) lista blanca de forma `^https?://(host|[ipv6])(:puerto)?$` con host en minúsculas `[a-z0-9.-]`
  (sin `"`, `'`, `;`, `=`, `` ` `` ni nada fuera de la lista). En el test 17 sumar `'`, `;`, `=` y `%22` a los mal formados y los positivos IPv4/IPv6/puerto (O2).
  El `qa-plan-v2.md` N5 y `research.md` D13 que citen solo `origin === x` quedan con la misma nota.

### 2.2 T049 — rotación de `sid` y `parseCookies` (FR-005)

**No cambia nada visible.** Diff de `POST /api/auth/login` (`client/server.js:313`): una sola línea, `setSession(...)` →
`emitirSesionRotada(...)`; status, cuerpo (`{success, user}`), mensaje de error y `must_change_password` (viaja dentro de `data.user`) quedan intactos.
La cookie sigue `HttpOnly; Path=/; SameSite=Lax` **sin** `Secure` (`:105-107`, `secure=false` por omisión). Con login fallido o backend caído, la rama
`return`/`catch` sale antes de rotar (`:305-318`).
Tests: `test_login_sid_056.test.js:74` (status, cuerpo y sin `Secure`), `:97`, `:108` (sin rotación en fallo), `test_sso_hub_056.test.js:353`, `:371`, `:379` (regresión).
`parseCookies` (`:89-101`): `try/catch` por cookie; una mala se ignora y las demás se leen; probado contra `/api/user/current`, `/api/branding` y `/sso/callback` (`test_login_sid_056.test.js:117-130`) y contra el propio `elea_rag_sid` mal formado (`:132`).
Único efecto observable fuera de la cookie: la sesión vieja del mismo navegador se descarta al volver a ingresar (el `sid` ya no es el mismo). Es el comportamiento buscado y la pantalla lo recarga con `boot()` (`index.html:1154`).

### 2.3 T003 — estado incorrecto (O4)

`tasks.md:74` marca `[x] T003`, pero T003 tiene **tres** cosas y solo una está hecha:
1. directorio Entra de prueba con las 3 URIs Web — **no existe** (lo crea el owner; no hay artefacto ni evidencia en el repo);
2. entradas en `.gitignore` — hecho (`c60d55f`, `.gitignore:91-92`);
3. verificación con `git check-ignore -v` — verificada ahora (arriba).

Hay que reabrir T003 (`[ ]`) o partirla en `T003a` (repo, hecho) y `T003b` (directorio, del owner, pendiente). Mientras tanto
**cualquier tarea que dependa del directorio de prueba** (la prueba local de `GUIA-PRUEBA-LOCAL-SSO.md` §1-§3 y la punta a punta de `quickstart.md` §3b) está bloqueada, y marcarla como hecha oculta ese bloqueo.

## 3. Observaciones

| # | Severidad | Hallazgo | Requisito | Qué hacer |
|---|---|---|---|---|
| **O1** | Media (doc/contrato) | La regla de «origen bien formado» de `hub-sso.md:151` es insuficiente (ver 2.1). El código (`client/public/sso-ui.js:44-55`) ya la supera, así que el contrato quedó **atrás** del código. | Contrato §6, test 17; FR-001, FR-015 | Corregir el contrato por Spec-Kit antes del PR (texto propuesto en 2.1). |
| **O2** | Baja (test) | El código nuevo `FORMA_ORIGEN` no tiene tests del lado **aceptado** para IPv4, IPv6 ni puerto: `sso-ui-056.test.js:44-53` solo prueba `https://hub.ejemplo.local` y `…:8443`, y el caso explícito de D4 (`http://172.16.0.120:8095`) y el de FR-015/N3 (IPv6 con corchetes) quedan sin cobertura. Una regresión que los rechace dejaría al botón sin dibujarse en silencio. Tampoco hay casos negativos para `'`, `;`, `=` en el host. | FR-015, spec N3 | Sumar a `sso-ui-056.test.js`: positivos `http://172.16.0.120:8095`, `https://[::1]:8443`, `https://[2001:db8::1]`; negativos `https://a'b`, `https://a;b`, `https://a=b`. |
| **O3** | Baja (doc) | Las referencias `archivo:línea` del contrato quedaron viejas: `client/server.js:75`, `:78-86`, `:93`, `:258-273`, `:284`, `:314-316`, `:318` (hub-sso.md:12-14, 21, 136-140) apuntaban al código previo al diff; ahora el `parseCookies` está en `:89-101`, el middleware en `:119-128`, el login en `:301-319`, el cambio de contraseña en `:329`. | Trazabilidad del contrato | Actualizarlas junto con O1. |
| **O4** | Media (estado) | T003 marcada `[x]` sin el directorio de prueba (ver 2.3). | `tasks.md:74` | Reabrir o partir la tarea. |

## 4. Notas informativas (no son hallazgos)

- **N1 — Caso unreachable del test 6**: el contrato (§7.6) pide «lo mismo en una primera visita, con el `Set-Cookie` del middleware ya puesto» para el **callback exitoso**.
  No puede darse: sin `elea_rag_sid` el Hub inventa un `sid` sin pendiente y el callback siempre cae al rechazo. El test `test_sso_flujo_056.test.js:183` cubre la variante alcanzable
  (callback fallido en primera visita: una sola `elea_rag_sid`, sin rotación) y `test_login_sid_056.test.js:86` cubre el filtro de `emitirSesionRotada` con el middleware ya puesto. Sin riesgo; conviene aclararlo en la próxima edición del contrato.
- **N2 — Límites ya aceptados (Clarifications N1)**: el callback no tiene tope de ritmo propio en el Hub (`client/server.js:467-487`); cada rechazo hace una llamada al backend de hasta 15 s (`:83`, `:400`) y el tope vive en el backend (D6). El contrato no pide un tope en el Hub; se anota solo para el PR.
- **Fuera del Tramo B** (no se evalúa): `docs/docs/**`, `make -C deploy check-docs` y la guía del owner son de T039-T044 (tramo E). El Tramo B no cambió API ni `.env.example`, así que `docs-refs` no aplica a este tramo.

## 5. Conformidad con las reglas del repo

- **Constitución / auditoría metadata-only**: el Hub no escribe auditoría ni logs de SSO; los rechazos de flujo se delegan al backend sin cookie ni token.
- **Marca blanca**: `npm test` verde en `whitelabel-hub-056.test.js`; límite honesto ya documentado (`server.js` conserva `Elea`/`ELEA_*` preexistentes).
- **Línea**: nada de GDPR ni EU AI Act; el diff no menciona normativa.
- **Sin secretos versionados**: el diff de `client/` no contiene tokens ni secretos (los de los tests son literales falsos: `TOKEN`, `STATE_JWT`, `cod-secreto`).
- **TDD y SDD**: cada comportamiento nuevo tiene su test; los artefactos de spec no se tocaron en esta revisión.
- **Modificado por este QA**: solo este archivo.
