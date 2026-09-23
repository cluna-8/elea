# Guía — Prueba local del SSO con Microsoft Entra (línea Eleia)

**Para**: Cristian y la sesión de Claude que lo acompaña en `cluna-8/elea`. **Fecha**: 23-sep-2026.
**Directorio Entra**: el **personal** de Cristian, nunca uno de Elea.
**Gemela**: `specs/067-porte-elea-sso-entra-hub/GUIA-PRUEBA-LOCAL-SSO.md` en `cluna-8/sentinel`
(misma prueba contra el directorio de Evidenze).

Esta guía reutiliza el runbook de la spec 017,
[`specs/017-auth-rbac-sso/RUNBOOK-e2e-sso.md`](../017-auth-rbac-sso/RUNBOOK-e2e-sso.md), y su
script `frontend/e2e/017-sso-e2e.mjs`. Las fases 1 a 4 de ese runbook ya pasaron el 24-ago. **La
5 (`login-real`, una persona entrando de verdad) nunca se corrió.** Esa es la que cierra esta
prueba.

---

## 0. Qué vamos a probar, y la idea en un minuto

**Objetivo**: comprobar que el SSO que **ya existe** en Guardian funciona contra Microsoft real
entrando por el **panel** (`localhost:8090`), sin escribir código nuevo. Después se construye el
Hub (spec 056) con la confianza de que la base anda.

Actores:

- el **usuario**: la persona en el navegador;
- **Guardian**: el panel en `:8090` y la API en `:8091`;
- **Microsoft Entra**: el directorio donde viven las cuentas.

El recorrido:

1. El usuario pulsa **"Entrar con Microsoft"**. Guardian lo manda a Microsoft con cuatro datos:
   - **quién pide** el ingreso (el *Client ID* de la aplicación registrada);
   - **adónde volver** (la *URI de retorno*);
   - un `state`, que protege contra que alguien inyecte un ingreso ajeno;
   - un `nonce`, que evita que se reutilice una respuesta vieja.
2. Microsoft le pide su cuenta, su contraseña y, si corresponde, el MFA. **Guardian nunca ve esa
   contraseña.**
3. Microsoft devuelve el navegador a la URI de retorno con un **código de un solo uso**.
4. El servidor de Guardian canjea ese código directamente con Microsoft, probando que es la
   aplicación registrada con el **secreto**. Recibe un `id_token`: un documento **firmado por
   Microsoft** que dice "esta persona es fulano@dominio". Guardian verifica cuatro cosas:
   - la firma, con las claves públicas del directorio;
   - el emisor (el tenant correcto);
   - la audiencia (que el token sea para esta aplicación);
   - que no esté vencido.
5. Guardian busca a esa persona **por email** y emite **la misma sesión** que un login con
   contraseña: mismo rol, grupo y presupuesto.

Por eso en Entra se crean tres cosas: **usuarios de prueba**, una **aplicación registrada**
(que es Guardian vista desde Microsoft) y un **secreto** (la "contraseña" de la aplicación).

---

## 1. Microsoft Entra (lo hace Cristian en el portal; Claude guía y explica cada pantalla)

> Regla: Claude **no** inicia sesión, no tipea contraseñas ni secretos y no crea cuentas.
> Cristian hace los clics de creación. Claude mira la pantalla (Claude in Chrome) y explica.

### 1.1 Entrar al directorio

1. https://portal.azure.com, con la **cuenta personal**.
2. Buscar **Microsoft Entra ID**. En **Información general** anotar:
   - **Id. de inquilino** (*Tenant ID*): identifica el directorio. En producción es el de Elea.
   - **Dominio principal**: `algo.onmicrosoft.com`. Es el dominio de los usuarios de prueba.

### 1.2 Usuarios de prueba (**Usuarios → Nuevo usuario → Crear usuario**)

| Usuario | Para qué |
|---|---|
| `prueba.existente@<dominio>` | Se da de alta **antes** en Guardian con el mismo email. Prueba que el SSO reconoce a un usuario existente con su rol y su grupo |
| `prueba.nuevo@<dominio>` | **No** existe en Guardian. Prueba el alta automática como `client` |

**Por qué no la cuenta personal de Gmail/Outlook**: las cuentas personales de Microsoft entran
como invitadas y el email llega en otro campo. Los usuarios `onmicrosoft.com` se comportan igual
que los de Elea sincronizados desde su AD.

### 1.3 Registrar la aplicación (**App registrations → New registration**)

| Campo | Valor | Por qué |
|---|---|---|
| Nombre | `Eleia (prueba local)` | Es lo que ve el usuario en la pantalla de Microsoft |
| Tipos de cuenta | **Solo cuentas de este directorio** | Un solo tenant, como en Elea. Ninguna cuenta ajena puede entrar |
| URI de redirección | Plataforma **Web**: `http://localhost:8090/sso/callback` | **Web, no SPA**: el canje lo hace el servidor. Una URI SPA falla en el canje. `http` se acepta solo para `localhost` |

Después, en **Authentication**, agregar otra URI Web: `http://localhost:8095/sso/callback`. Es la
del Hub, para cuando esté construido.

Anotar el **Application (client) ID** de la página de la aplicación.

### 1.4 Secreto (**Certificates & secrets → New client secret**)

- Vencimiento: 6 meses. En producción se anota y se agenda su renovación.
- Copiar el **Value**, no el "Secret ID". **Se muestra una sola vez.**

### 1.5 Permisos (**API permissions**)

Dejar `User.Read`, que viene por defecto. Los alcances `openid profile email` los pide el propio
ingreso. En un directorio propio no hace falta consentimiento de administrador.

### 1.6 Guardar los datos fuera del repo

```bash
nano ~/.eleia-sso-prueba.env
chmod 600 ~/.eleia-sso-prueba.env
```

```
SSO_TENANT_ID=<Directory (tenant) ID>
SSO_CLIENT_ID=<Application (client) ID>
SSO_CLIENT_SECRET=<Value del secreto>
```

**El secreto no se pega en el chat.** El paso 4 lo lee de este archivo.

---

## 2. Licencia de desarrollo con `sso`

La función está detrás del permiso `sso` de la licencia. Sin él, todo responde 403 y el botón no
aparece: es lo que pasa hoy en Elea.

Se firma con la clave **de desarrollo** (`kid sentinel-dev-2026`). Es la misma en los dos repos y
se verificó el 23-sep contra los dos keysets. **No es una clave de producción.**

```bash
cd ~/Documents/ELEA/LLMADMIN-Elea/elea/backend
.venv/bin/python scripts/issue_license.py \
  --key ~/Documents/EVIDENZE/SENTINEL/backend/scripts/license_out/dev_signing_key.pem \
  --kid sentinel-dev-2026 --lic-id lic_dev_sso_local \
  --tenant-id 00000000-0000-0000-0000-000000000001 \
  --distributor-id d_sentinel --pool-id pool_sentinel_dev \
  --max-seats 50 --expiry 2099-01-01T00:00:00Z \
  --feature-flags monitor,sso \
  --out config/licenses/dev-sso-local.lic
```

**No commitear `dev-sso-local.lic`.** Es solo para la prueba local.

---

## 3. Levantar el stack con SSO (archivo local, no se commitea)

`~/Documents/ELEA/LLMADMIN-Elea/elea/docker-compose.sso-local.yml`:

```yaml
services:
  backend:
    environment:
      - SENTINEL_LICENSE_TOKEN_FILE=/app/config/licenses/dev-sso-local.lic
      - SENTINEL_SSO_REDIRECT_URI=http://localhost:8090/sso/callback   # byte a byte la registrada
      - SENTINEL_SSO_COOKIE_INSECURE=true                             # SOLO dev sobre http
```

```bash
cd ~/Documents/ELEA/LLMADMIN-Elea/elea
docker stop $(docker ps -q -f name=sentinel-) 2>/dev/null   # si el stack de Sentinel está arriba: mismos puertos
STACK_PREFIX=eleae2e docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose.sso-local.yml up -d
```

Comprobar que la licencia se tomó (tiene que responder `{"enabled": false, ...}`, **no** 403):

```bash
curl -s http://localhost:8091/api/v1/auth/sso/available
```

---

## 4. Cargar la configuración de Entra en Guardian

Hoy no hay formulario en el panel (lo agrega la 056, US3). Se carga por la API, como en
producción hasta que exista el formulario. **Cristian tipea la contraseña del admin**; el
secreto sale del archivo del paso 1.6.

```bash
source ~/.eleia-sso-prueba.env
read -rs -p 'Contraseña del admin local: ' CLAVE; echo
TOKEN=$(curl -s http://localhost:8091/api/v1/users/login -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"$CLAVE\"}" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p'); unset CLAVE
python3 - "$TOKEN" <<'PY'
import json, os, sys, urllib.request
body = {"provider_type": "entra",
        "config": {"tenant_id": os.environ["SSO_TENANT_ID"], "client_id": os.environ["SSO_CLIENT_ID"]},
        "client_secret": os.environ["SSO_CLIENT_SECRET"], "enabled": True}
req = urllib.request.Request("http://localhost:8091/api/v1/auth/sso/config", method="PUT",
      data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {sys.argv[1]}",
      "Content-Type": "application/json"})
print(urllib.request.urlopen(req).read().decode())   # nunca incluye el secreto
PY
unset SSO_CLIENT_SECRET
```

La respuesta tiene que traer `"enabled": true` y `"client_secret_configurado": true`. El secreto
queda **cifrado** en la base y ninguna respuesta lo devuelve.

---

## 5. La prueba

Primero, en el panel (`localhost:8090`, entrando como admin con contraseña), **dar de alta un
usuario** con email `prueba.existente@<dominio>`. Ponerle un grupo con presupuesto, para ver
después que lo conserva.

| # | Qué hacer | Qué tiene que pasar |
|---|---|---|
| 1 | Cerrar sesión. En el login aparece **"Entrar con Microsoft"** | El botón se dibuja porque la licencia **y** la configuración están activas |
| 2 | Entrar con `prueba.existente@…` en una ventana de incógnito | Pantalla de Microsoft → vuelve a Guardian con sesión abierta, **mismo rol y grupo** que el alta del paso previo |
| 3 | Entrar con `prueba.nuevo@…` | Se crea como `client`, sin grupo, y ocupa un puesto |
| 4 | En el panel, dar de baja a `prueba.existente` y reintentar el ingreso | Rechazado. La baja **no** se revierte |
| 5 | Entrar con `admin` y contraseña | Igual que siempre: **el login local no se tocó** |
| 6 | Desactivar el SSO (`PUT` con `enabled: false`) | Desaparece el botón; el login con contraseña sigue |

Para dejar evidencia automatizada, la fase 5 del runbook de la 017:

```bash
cd frontend && node e2e/017-sso-e2e.mjs http://localhost:8090 ./shots-056-sso --fase=login-real \
  --usuario=admin --clave=<clave> --tenant-id=$SSO_TENANT_ID --client-id=$SSO_CLIENT_ID --espera-humana=300
```

Abre un navegador y espera a que una persona complete el ingreso en Microsoft (el MFA no se
automatiza a propósito). Después compara la sesión del SSO con la del login local.

### Si algo falla

Ver la tabla **"Qué hacer con un rojo"** del runbook de la 017. Las más probables:

| Síntoma | Causa |
|---|---|
| `403 sso_no_licenciado` | El backend no tomó `dev-sso-local.lic` (revisar el paso 3) |
| `AADSTS50011` después de la contraseña | La URI registrada en Entra no es **idéntica** a `SENTINEL_SSO_REDIRECT_URI` |
| "no hay flujo SSO en curso en este navegador" | Falta `SENTINEL_SSO_COOKIE_INSECURE=true`, o se cambió de navegador o de perfil a mitad del ingreso |
| `401 sso_identidad_sin_email` | El usuario de Entra no trae email: usar usuarios `onmicrosoft.com`, no cuentas personales |

---

## 6. Al terminar

1. Anotar el resultado en `RESULTADOS-PRUEBA-LOCAL.md` en esta carpeta: fecha, qué pasó en cada
   uno de los 6 puntos, y las capturas de `shots-056-sso`.
2. Actualizar la tabla **"Estado de esta verificación"** del runbook de la 017: la fila
   `login-real` deja de estar bloqueada.
3. Dejar el stack como estaba:
   - borrar `docker-compose.sso-local.yml` y `config/licenses/dev-sso-local.lic`, o dejarlos
     fuera de git;
   - bajar el stack.
4. En Entra (cuenta personal), la aplicación y los usuarios de prueba pueden quedar para cuando
   se pruebe el Hub. Eso sí, el secreto vence a los 6 meses.
