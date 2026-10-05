# Contrato — Cambios de base en la API SSO de Guardian (`backend/src/sso/api.py`)

**Base Guardian**: genérico, sin strings de Elea ni Eleia, portable a Sentinel por cherry-pick
(la 067 confirma que `sso/` es idéntico en las dos líneas). Retrocompatible con el panel actual y
con cualquier cliente que ignore el campo nuevo. Extiende
[specs/017-auth-rbac-sso/contracts/proveedor-sso.md](../../017-auth-rbac-sso/contracts/proveedor-sso.md).
Decisiones: [research.md](../research.md) D4 y D6.

`backend/src/sso/jit.py`, `entra.py`, `registry.py` y `admin_api.py` **no cambian** (FR-007).

## 1. `GET /api/v1/auth/sso/available` — campo nuevo `return_origin`

Respuesta (sin cambios de status: 403 sin flag `sso`, 200 en los demás casos, `api.py:179-200`):

```json
{ "enabled": true, "provider_type": "entra", "return_origin": "https://hub.ejemplo.local" }
```

| Campo | Regla |
|---|---|
| `enabled`, `provider_type` | Sin cambio. |
| `return_origin` | **Nuevo.** Origen (`esquema://host[:puerto]`) de `SENTINEL_SSO_REDIRECT_URI`, calculado con `urllib.parse.urlsplit`. El puerto se incluye solo si la URI lo trae. `null` si la variable falta, está vacía o no es absoluta (`http`/`https` con host). Nunca incluye ruta, query ni fragmento. Se devuelve también con `enabled:false`. |

**Por qué es seguro pre-auth**: el mismo valor viaja en el `redirect_uri` de la URL de
Microsoft que ve cualquiera que pulse el botón. No expone `config`, `client_id`, tenant del
directorio ni el secreto (la regla de `api.py:189-192` se mantiene).

**Uso**: el cliente muestra el botón solo si `return_origin` es `null` (instalación vieja o sin
variable: comportamiento de hoy) o coincide con su propio origen. El Hub puede además mandar el
botón a `${return_origin}/sso/login`.

Tests nuevos (junto a `backend/tests/integration/test_sso_api.py:196-228`):

1. Con `SENTINEL_SSO_REDIRECT_URI=https://hub.ejemplo.local/sso/callback` →
   `return_origin == "https://hub.ejemplo.local"`.
2. Con puerto explícito (`http://localhost:8095/sso/callback`) → `"http://localhost:8095"`.
3. Sin variable, vacía o relativa → `null`, y `enabled` sigue su regla de siempre.
4. Con flag apagado → sigue siendo 403 (el gate preempta, `test_el_gate_preempta_al_handler`).
5. La respuesta sigue sin `config` ni secreto (`test_available_no_filtra_la_config_del_tenant`).

## 2. `GET /api/v1/auth/sso/callback` — auditoría de los rechazos de flujo

Hoy `_leer_estado` (`api.py:102-124`), la comparación de `state` (`:264-268`), el `code`
ausente (`:269-273`) y el cambio de proveedor (`:276-282`) responden 400 **sin** auditar. Pasan
a emitir `auth_sso_denied` (con `_auditar_denegado(db, tenant_id)`, `api.py:339-347`) **antes**
de levantar el 400.

| Caso | Status y `detail` | Auditoría |
|---|---|---|
| Sin cookie de estado | 400 `sso_state_ausente` (sin cambio) | **nueva** `auth_sso_denied` |
| Cookie inválida, vencida o de otro propósito | 400 `sso_state_invalido` (sin cambio) | **nueva** |
| `state` del query ausente o distinto | 400 `sso_state_invalido` (sin cambio) | **nueva** |
| `code` ausente (incluye la cancelación en el directorio) | 400 `sso_code_ausente` (sin cambio) | **nueva** |
| Proveedor cambiado entre login y callback | 400 `sso_state_invalido` (sin cambio) | **nueva** |

Metadata-only: el evento lleva solo tipo y `tenant_id`. **Nunca** `state`, `code`, email,
cookie ni token. Auditar no puede cambiar el veredicto: si la escritura falla, el 400 sale igual
(mismo `try/except` de `_auditar_denegado`).

**Tope contra la inundación** (research D6, decisión del owner): los `auth_sso_denied` de esta
tabla (rechazos de **flujo**) se emiten como máximo `_TOPE_DENEGADOS_FLUJO_POR_MIN` veces
(constante, 30) por ventana de 60 s y por proceso. Los que exceden el tope:

- no escriben filas;
- se cuentan, y al cerrar la ventana se emite un solo `logger.warning` con el conteo omitido
  (sin `state`, `code`, IP ni token);
- no cambian el status ni el `detail`.

Los rechazos de **identidad** (`api.py:302`, `:313`, `:379`) no pasan por el tope.

Tests nuevos (junto a `test_callback_sin_cookie_400`, `test_callback_con_state_ajeno_400`,
`test_callback_con_cookie_falsificada_400`, `test_callback_sin_code_400`, `test_sso_api.py:322-430`):
cada caso de la tabla deja **exactamente un** evento `auth_sso_denied` y ninguna columna del
evento contiene el `state` ni el `code` usados. Además:

- con el reloj de la ventana inyectado, `tope + 5` rechazos de flujo dejan exactamente `tope`
  eventos, todos con status 400 intacto, y un warning con el conteo omitido;
- al abrirse la ventana siguiente se vuelve a auditar;
- los rechazos de identidad siguen auditándose aunque el tope de flujo esté agotado.

## 3. Lo que el Hub consume (sin cambios de contrato)

| Endpoint | Cómo lo usa el Hub |
|---|---|
| `GET /auth/sso/available` | Proxy fail-closed ([hub-sso.md](hub-sso.md) §1). |
| `GET /auth/sso/login` | Llamada de servidor con `redirect: 'manual'`: lee `Location` (302) y el `Set-Cookie` `sentinel_sso_state` (`api.py:237-247`). |
| `GET /auth/sso/callback` | Llamada de servidor con `Cookie: sentinel_sso_state=…`; recibe `{access_token, token_type, user}` (`api.py:321-336`). |

La cookie de estado del backend tiene `Secure` salvo `SENTINEL_SSO_COOKIE_INSECURE` (`api.py:82-85`),
pero en el tramo Hub → backend no la gestiona un navegador: el Hub la lee de la cabecera y la
reenvía. **El Hub no necesita `SENTINEL_SSO_COOKIE_INSECURE`**, ni siquiera en desarrollo sobre
HTTP. Esa variable sigue siendo solo para el panel en dev.

**Un solo uso**: el backend lo garantiza borrando la cookie del navegador
(`api.py:335`, `test_el_state_no_se_puede_reusar`), lo que no alcanza cuando el cliente es un
servidor. En el camino del Hub, el un-solo-uso lo garantiza el consumo del pendiente
([hub-sso.md](hub-sso.md) §3, paso 1).

## 4. Configuración (`SENTINEL_SSO_REDIRECT_URI`)

Sin cambios de semántica: una sola URI, obligatoria para iniciar el flujo (`api.py:127-154`). En
la fase 1 de Elea apunta al **Hub**: `https://<nombre-del-hub>/sso/callback`. El panel deja de
mostrar su botón por `return_origin` (§1). SSO en el panel con dos URIs sigue fuera de alcance.
