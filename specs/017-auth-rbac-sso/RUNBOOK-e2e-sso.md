# Runbook — E2E de SSO contra el tenant Entra real (T018 · SC-003)

Cómo se corre, de punta a punta, el acceso por directorio corporativo contra un **Entra de
verdad**, y qué se captura en cada paso. Cierra **SC-003** de la [spec 017](spec.md) y es la
verificación que antecede a la primera instalación con SSO en la sede de un cliente.

La guía **vendible** —la que se le pasa al cliente y a preventa— es
[`docs/docs/install-deploy/sso.md`](../../docs/docs/install-deploy/sso.md). Este archivo es
lo otro: el procedimiento interno para **medirlo**, con los identificadores del tenant de
prueba y las trampas que ya nos costaron tiempo.

## Qué prueba SC-003, en dos brazos

> *Login E2E contra el tenant Entra de prueba termina en sesión funcional idéntica a la
> local (mismo formato de token, tenant claim presente); con flag de licencia apagado, el
> flujo SSO no es alcanzable y el login local pasa la misma suite que hoy.*

| Brazo | Qué se afirma | ¿Necesita Azure? |
|---|---|---|
| **Apagado** | Sin el flag `sso`, la superficie no es alcanzable y el login local sigue entero | No |
| **Encendido** | El login por Entra emite **la misma sesión** que el login local | Sí |

Los dos se miden con el mismo instrumento: `frontend/e2e/017-sso-e2e.mjs`, una fase por
estado del backend. El script **no reinicia nada** — el estado lo pone este runbook, y el
script mide lo que tiene que valer en ese estado y deja la captura.

## Prerrequisitos, y de quién es cada uno

| # | Qué | Quién | Estado |
|---|---|---|---|
| 1 | Tenant Entra de prueba, con la app registrada | DevOps (Fran) | ✅ existe desde el 18-ago |
| 2 | **URI de retorno registrada en el portal = `http://localhost:8090/sso/callback`** | Fran | ⚠️ **verificar** — ver más abajo |
| 3 | Client secret vigente de esa app | Fran, por vía segura | ⏳ pendiente |
| 4 | Usuario piloto del directorio, con su segundo factor | Fran | ⏳ pendiente |
| 5 | Licencia con el flag `sso` | Emisión del fabricante | ✅ desbloqueado (`issue_license.py --feature-flags sso`, #281) |
| 6 | Stack local en los puertos estándar | Quien corre el E2E | — |

### Identificadores del tenant de prueba

No son secretos —son identificadores de creación, estables— pero **son de nuestro tenant de
prueba**: en una instalación real los da el cliente y son otros.

```
Directory (tenant) ID   d37d0dde-f421-4983-91c0-f76a9c551484
Application (client) ID 33d1b3d4-6ce3-4888-a3ba-078b98ae164b
URI de retorno (dev)    http://localhost:8090/sso/callback
```

> Verificado contra el propio directorio: el documento de discovery de ese `tenant_id`
> responde 200, declara `RS256` como único algoritmo de firma de `id_token` —que es
> exactamente la allowlist que el producto fija— y su región es `EU`.

### ⚠️ La URI de retorno del brief estaba mal, y el atajo para verificarla NO funciona

El brief original decía `localhost:8091/api/v1/auth/sso/callback`. Está mal dos veces:
**8091 es el backend** (el frontend es 8090) y **la ruta es de la consola, no de la API**.
Registrar esa URI da `AADSTS50011`, o un flujo que pasa los tests y aterriza al usuario
mirando un JSON. La correcta es `http://localhost:8090/sso/callback`.

El atajo obvio para verificar cuál quedó registrada —abrir la URL de `authorize` a mano y
ver si el directorio protesta— **no sirve, y hay que decirlo porque invita a un falso
verde**. Medido contra este tenant, con dos brazos de control:

| URI mandada en el `authorize` | Respuesta del directorio |
|---|---|
| `http://localhost:8090/sso/callback` (la correcta) | 200, pantalla de acceso, `AADSTS50058` |
| `http://localhost:8091/api/v1/auth/sso/callback` (la del brief) | 200, pantalla de acceso, `AADSTS50058` |
| `http://localhost:9999/no-registrada` (basura pura) | 200, pantalla de acceso, `AADSTS50058` |

Las tres idénticas. `AADSTS50058` es «no hay sesión silenciosa» —el estado normal de un
acceso limpio— y aparece igual con una URI inventada. **La sonda no discrimina**: sin
autenticar, este tenant no valida la URI de retorno, así que un «no dio error, está bien»
es exactamente el falso verde que la sonda parece descartar.

Quedan dos formas honestas de verificarla, y ninguna es un `curl`:

1. **Mirarla en el portal** (Fran, *App registrations → Authentication → Redirect URIs*).
   Es la única que no necesita credenciales del piloto.
2. **Completar la fase `login-real`** de abajo. Si la URI no coincide, el `AADSTS50011`
   aparece **después** de tipear las credenciales, y la captura del paso lo deja probado.

## Levantar el stack

Los puertos **no son negociables**: la URI registrada en el directorio nombra el `8090`, y
el protocolo exige que la del canje sea idéntica a la del inicio. El compose estándar ya
publica la consola en 8090 y la API en 8091.

```bash
docker compose up -d --build
```

Variables que el camino SSO necesita en el backend (además de las del despliegue):

```yaml
BASA_SSO_REDIRECT_URI: "http://localhost:8090/sso/callback"   # byte a byte la registrada
BASA_SSO_COOKIE_INSECURE: "true"    # SOLO acá: dev sobre HTTP plano. En producción se OMITE.
FERNET_SECRET_KEY: "<clave-del-despliegue>"                   # sin ella el PUT corta con 503
```

`BASA_SSO_COOKIE_INSECURE` existe para esto y **sólo** para esto: la cookie del flujo se
emite con `Secure` por default, y sobre `http://` plano el navegador puede no devolverla —
lo que se ve como «no hay flujo SSO en curso en este navegador», un mensaje que manda a
buscar el problema al lado equivocado.

## Preparar el harness

```bash
cd frontend/e2e && npm install && cd ..
```

`playwright` está declarado en `frontend/e2e/package.json`, aparte del `package.json` del
app para no engordar su instalación — mismo arreglo que el harness visual 029.

## Las fases

Cada fase es un estado del backend + una corrida del script. **Correrlas en orden**: cada
una deja el sistema listo para la siguiente, y un rojo temprano explica los rojos de abajo.

Las capturas salen numeradas y prefijadas por fase
(`<fase>-<NN>-<qué-muestra>.png`) junto a un `reporte-<fase>.json` con el veredicto de cada
paso, para que una captura suelta se ubique sola en el informe.

### Fase 1 · `sin-licencia` — el brazo apagado de SC-003

**Estado**: instalación con una licencia **sin** el flag `sso` (una licencia `monitor`
común sirve).

```bash
PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright" \
  node e2e/017-sso-e2e.mjs http://localhost:8090 ./shots-017-sso \
  --fase=sin-licencia --usuario=<admin> --clave=<clave>
```

Mide que **las tres rutas** responden `403 sso_no_licenciado` —el flujo, el discovery que
dibuja el botón, y la superficie de administración que carga la config—, que el botón
**no existe en el DOM** (no está escondido: no se dibuja), y que el **login local entra
igual** y emite una sesión con `tenant` claim.

> Las tres rutas y no una: «no alcanzable» se prueba en las rutas. Que el botón falte es lo
> que ve el usuario, no lo que lo detiene.

### Fase 2 · `licenciado-sin-config` — la capa de licencia separada de la de tenant

**Estado**: misma instalación, ahora con la licencia **con** `sso`. Todavía sin configurar
el proveedor.

```bash
node e2e/017-sso-e2e.mjs http://localhost:8090 ./shots-017-sso --fase=licenciado-sin-config
```

Mide que `available` responde `200 {"enabled": false, "provider_type": null}` y que el flujo
corta con `404 sso_no_configurado` — **no** con el 403 de licencia. Son dos capas y se
arreglan en lugares distintos: una es del fabricante, la otra del operador.

### Fase 3 · `sembrado` — la configuración cargada, sin tocar todavía el secreto real

**Estado**: licencia con `sso` + configuración del tenant cargada por la API.

La carga es el `PUT /api/v1/auth/sso/config` documentado en el
[paso 3 de la guía de instalación](../../docs/docs/install-deploy/sso.md). Recordar que esa
superficie está detrás del **mismo** flag de licencia: intentarlo antes de la fase 2
devuelve `403` y se lee como un problema de permisos que no es.

> **El secreto real hace falta más tarde de lo que parece.** El alta **no** valida el
> secreto contra el directorio: lo cifra y lo guarda. Con un secreto de relleno esta fase
> pasa entera y el navegador llega hasta la **pantalla de acceso real del directorio** —
> porque el `discovery` y el `authorize` son públicos. El secreto de Fran recién es
> imprescindible en la fase 5, en el canje del código.

```bash
node e2e/017-sso-e2e.mjs http://localhost:8090 ./shots-017-sso --fase=sembrado \
  --tenant-id=d37d0dde-f421-4983-91c0-f76a9c551484 \
  --client-id=33d1b3d4-6ce3-4888-a3ba-078b98ae164b \
  --redirect-uri=http://localhost:8090/sso/callback
```

Mide el `302` del inicio del flujo **contra lo que la instalación manda de verdad**, no
contra lo que dice la configuración: host del directorio, Directory ID en la authority,
`client_id`, `redirect_uri` byte a byte, `state` y `nonce` presentes, y la cookie de flujo
`HttpOnly`. Después hace el clic real y captura la pantalla del directorio.

### Fase 4 · `degradacion` — el fallback permanente, medido contra el directorio real

**Estado**: el mismo de la fase 3. **No hace falta el secreto real.**

```bash
node e2e/017-sso-e2e.mjs http://localhost:8090 ./shots-017-sso --fase=degradacion \
  --usuario=<admin> --clave=<clave>
```

Abre un flujo de verdad —con su cookie de estado— y vuelve al canje con un código que el
directorio va a rechazar. Es el único pedazo del brazo encendido que se puede medir sin las
credenciales del cliente, y **mide lo que ningún doble puede**: que la llamada real a
Microsoft falla y el producto degrada bien. El camino de error es exactamente el mismo que
el de un secreto vencido en la sede.

Exige `401 sso_identidad_no_verificada`, que el mensaje **ofrezca el fallback**, que **no**
filtre el motivo técnico al navegador (`client_secret`, `invalid_client`, `AADSTS`,
`token_endpoint` — eso vive en los logs del backend), y que el **login local siga entero**
después.

> Verificar en el log del backend que la línea
> `sso callback: intercambio rechazado (…): intercambio code→token falló con el IdP` está
> presente. Sin ella, el `401` podría venir de un corte **anterior** a la llamada de red y
> la fase estaría midiendo otra cosa.

### Fase 5 · `login-real` — el brazo encendido, con una persona adentro

**Estado**: el de la fase 3, pero con el **client secret real** cargado.

```bash
node e2e/017-sso-e2e.mjs http://localhost:8090 ./shots-017-sso --fase=login-real \
  --usuario=<admin> --clave=<clave> \
  --tenant-id=d37d0dde-f421-4983-91c0-f76a9c551484 \
  --client-id=33d1b3d4-6ce3-4888-a3ba-078b98ae164b \
  --espera-humana=300
```

Abre el navegador **con cabeza** y espera. El segundo factor lo resuelve una persona: no se
automatiza a propósito — falsificar un MFA sería falsificar justo lo que este E2E existe
para probar.

Cuando el directorio devuelve el navegador, mide el cierre del flujo y **el corazón de
SC-003**: decodifica la sesión que emitió el SSO, la compara con la que emite un login local
en la misma corrida, y exige **el mismo juego de claims**, `tenant` presente, y que el
tenant sea el del despliegue. El brazo de control es el login local: sin él, «el token tiene
buena pinta» no es una medición.

## Qué hacer con un rojo

| Lo que falla | Qué mirar primero |
|---|---|
| `403 sso_no_licenciado` donde se esperaba otra cosa | La licencia instalada no trae el flag. No es la contraseña del admin. |
| `redirect_uri` enviada ≠ esperada | `BASA_SSO_REDIRECT_URI` del backend. Es el valor que viaja, no el del portal. |
| `AADSTS50011` tras las credenciales | El portal del cliente. **Es el único momento en que este error puede aparecer** — ver la sonda que no discrimina, arriba. |
| «no hay flujo SSO en curso en este navegador» | La cookie de flujo no volvió: `BASA_SSO_COOKIE_INSECURE` sobre HTTP plano, u otro navegador/perfil. |
| `503 sso_cifrado_no_disponible` en la carga | `FERNET_SECRET_KEY` del backend. **No se guardó nada**: arreglar y repetir el `PUT`. |
| Identidad no verificada tras un login exitoso en el portal | Secreto vencido/mal cargado, o el directorio no emitió correo. Los detalles están en los **logs del backend**, nunca en el navegador. |

## Estado de esta verificación

| Fase | Corrida | Resultado |
|---|---|---|
| `sin-licencia` | 2026-08-24 | ✅ **7/7** |
| `licenciado-sin-config` | 2026-08-24 | ✅ **5/5** |
| `sembrado` | 2026-08-24 | ✅ **13/13** — el navegador llegó a la pantalla de acceso real de Microsoft |
| `degradacion` | 2026-08-24 | ✅ **5/5** — canje rechazado por Microsoft, degradó a 401 y el login local siguió |
| `login-real` | — | ⛔ **bloqueada**: falta el client secret y el usuario piloto (Fran) |

Se actualiza esta tabla con la fecha y el veredicto de cada corrida. Una fase sin fila
llena es una fase **no corrida** — no una fase que pasó.

Las cuatro primeras se corrieron sobre `main` (`02b1181`) con la consola en `8090` y la API
nativa detrás del proxy de Vite; la licencia de las fases 2-4 se emitió efímera para la
corrida (par Ed25519 generado al vuelo, con `feature_flags: ["monitor","sso"]`), así que
**no hizo falta ninguna clave de firma de producción**. La configuración se sembró con la
receta `curl` del paso 3 de la guía de instalación, tal cual está publicada — que de paso la
verifica contra una instalación viva y no sólo contra el código.

> **Lo que estas cuatro fases NO prueban.** Que un login humano completo cierre. El canje
> exitoso —el `code` bueno, el `id_token` firmado, la verificación de `iss`/`aud`/`nonce`,
> el JIT y la sesión que sale— está cubierto por la suite contra un doble del proveedor,
> pero contra el directorio real sólo lo prueba la fase 5. Hasta que esa fila tenga fecha,
> **SC-003 está medido a medias** y así hay que decirlo.
