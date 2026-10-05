# Contrato — Cambios de base en la API SSO de Guardian (`backend/src/sso/api.py`)

**Base Guardian**: genérico, sin strings de Elea ni Eleia, portable a Sentinel por cherry-pick
(la 067 confirma que `sso/` es idéntico en las dos líneas). Retrocompatible con el panel actual y
con cualquier cliente que ignore el campo nuevo. Extiende
[specs/017-auth-rbac-sso/contracts/proveedor-sso.md](../../017-auth-rbac-sso/contracts/proveedor-sso.md).
Decisiones: [research.md](../research.md) D4 y D6 (con F1, F4, F8 y B5 de [qa-plan.md](../qa-plan.md)).

`backend/src/sso/jit.py`, `entra.py`, `registry.py` y `admin_api.py` **no cambian** (FR-007).

## 1. `GET /api/v1/auth/sso/available` — campo nuevo `return_origin`

Respuesta (sin cambios de status: 403 sin flag `sso`, 200 en los demás casos, `api.py:179-200`):

```json
{ "enabled": true, "provider_type": "entra", "return_origin": "https://hub.ejemplo.local" }
```

| Campo | Regla |
|---|---|
| `enabled`, `provider_type` | Sin cambio. |
| `return_origin` | **Nuevo.** Origen (`esquema://host[:puerto]`) de `SENTINEL_SSO_REDIRECT_URI`, calculado con `urllib.parse.urlsplit` a partir de `scheme`, `hostname` y `port` (**nunca** `netloc`, que arrastraría credenciales `usuario:clave@`). Normalización igual a la de `window.location.origin`: esquema y host en minúsculas; el puerto se incluye solo si la URI lo trae **y** no es el por defecto del esquema (`https://host:443/…` → `https://host`; `http://host:80/…` → `http://host`). `null` si la variable falta, está vacía o no es absoluta (`http`/`https` con host). Nunca incluye ruta, query, fragmento ni credenciales. Se devuelve también con `enabled:false`. |

**Por qué es seguro pre-auth**: el mismo valor viaja en el `redirect_uri` de la URL de
Microsoft que ve cualquiera que pulse el botón. No expone `config`, `client_id`, tenant del
directorio ni el secreto (la regla de `api.py:189-192` se mantiene).

**Uso** (spec FR-015):

- **Panel**: muestra el botón solo si `return_origin` es `null` (instalación vieja o sin variable:
  comportamiento de hoy) o coincide con su propio origen.
- **Hub**: muestra el botón solo si `return_origin` **no** es `null` (F4 del QA). Con `null`, el
  flujo no puede arrancar (`/auth/sso/login` corta con `500 sso_redirect_uri_no_configurado`,
  `api.py:143-154`) y el Hub no tiene instalaciones viejas que preservar. Si el origen es otro, el
  botón navega a `${return_origin}/sso/login`.

`enabled` **no** cambia de regla: sigue mirando solo el proveedor (`api.py:193-200`), para no
alterar el comportamiento del panel ni de Sentinel.

Tests nuevos (junto a `backend/tests/integration/test_sso_api.py:196-228`):

1. Con `SENTINEL_SSO_REDIRECT_URI=https://hub.ejemplo.local/sso/callback` →
   `return_origin == "https://hub.ejemplo.local"`.
2. Con puerto explícito (`http://localhost:8095/sso/callback`) → `"http://localhost:8095"`.
3. Con el puerto por defecto explícito (`https://hub.ejemplo.local:443/sso/callback`) →
   `"https://hub.ejemplo.local"`; con mayúsculas en esquema o host → en minúsculas.
4. Con credenciales en la URI (`https://u:p@hub.ejemplo.local/sso/callback`) →
   `"https://hub.ejemplo.local"`: nunca aparecen `u` ni `p`.
5. Sin variable, vacía o relativa → `null`, y `enabled` sigue su regla de siempre.
6. Con flag apagado → sigue siendo 403 (el gate preempta, `test_el_gate_preempta_al_handler`).
7. La respuesta sigue sin `config` ni secreto (`test_available_no_filtra_la_config_del_tenant`).

## 2. `GET /api/v1/auth/sso/callback` — auditoría de los rechazos de flujo y tope

Hoy no auditan los siguientes rechazos, que pasan a emitir `auth_sso_denied` (con
`_auditar_denegado(db, tenant_id)`, `api.py:339-347`) **antes** de levantar el error:

- `_leer_estado` (`api.py:102-124`);
- la comparación de `state` (`:264-268`);
- el `code` ausente (`:269-273`);
- `_cargar_config` sin proveedor habilitado (`:171-175`, invocado en `:275` fuera de todo `try`);
- el cambio de proveedor (`:276-282`);
- la URI de retorno faltante (`_redirect_uri`, `:143-154`). Se invoca en `:293` dentro del
  `try` del canje y hoy pasa sin auditar por `except HTTPException: raise` (`:295-296`).

| Caso | Status y `detail` | Auditoría | Categoría del tope |
|---|---|---|---|
| Sin cookie de estado | 400 `sso_state_ausente` (sin cambio) | **nueva** `auth_sso_denied` | flujo |
| Cookie inválida, vencida o de otro propósito | 400 `sso_state_invalido` (sin cambio) | **nueva** | flujo |
| `state` del query ausente o distinto | 400 `sso_state_invalido` (sin cambio) | **nueva** | flujo |
| `code` ausente (incluye la cancelación en el directorio) | 400 `sso_code_ausente` (sin cambio) | **nueva** | flujo |
| Proveedor apagado o borrado entre login y callback (F8 del QA) | 404 `sso_no_configurado` (sin cambio) | **nueva** | flujo |
| Proveedor cambiado entre login y callback | 400 `sso_state_invalido` (sin cambio) | **nueva** | flujo |
| URI de retorno faltante al canjear (F8 del QA) | 500 `sso_redirect_uri_no_configurado` (sin cambio) | **nueva** | flujo |
| Canje fallido con el directorio (`code` inventado o vencido, secreto vencido, directorio caído; `api.py:297-307`) | 401 `sso_identidad_no_verificada` (sin cambio) | ya existía (`:302`) | **canje** (F1 del QA) |
| Identidad sin email (`:309-317`) | 401 `sso_identidad_sin_email` (sin cambio) | ya existía (`:313`) | sin tope |
| JIT: usuario dado de baja o sin puestos (`:374-380`) | 403 / 402 (sin cambio) | ya existía (`:379`) | sin tope |

Metadata-only: el evento lleva solo tipo y `tenant_id`. **Nunca** `state`, `code`, email,
cookie ni token. Auditar no puede cambiar el veredicto: si la escritura falla, el error sale
igual (mismo `try/except` de `_auditar_denegado`).

**Tope contra la inundación** (research D6, decisión del owner; extendido al canje fallido por
F1 del QA). Una constante `_TOPE_DENEGADOS_POR_MIN = 30`, ventana de 60 s, por proceso, con **dos
contadores independientes**, uno por categoría (`flujo` y `canje`), y reloj inyectable para los
tests.

- **Flujo**: pasado el tope, el rechazo no escribe fila.
- **Canje**: el contador suma cada canje fallido. Antes de llamar a `provider.exchange_code`, el
  callback mira el contador: si ya llegó al tope en la ventana, **no llama** al `token_endpoint`,
  no escribe fila y responde `401 sso_identidad_no_verificada` con el mismo `detail`. `entra.py`
  no cambia.
- En las dos categorías el excedente se cuenta, y al cerrar la ventana se emite un solo
  `logger.warning` por categoría con el conteo omitido (sin `state`, `code`, IP ni token). El
  status y el `detail` no cambian.

Los rechazos que exigen una identidad real del directorio (`api.py:313`, `:379`) no pasan por el
tope. Efecto aceptado: durante una ráfaga, un canje legítimo de la misma ventana también recibe el
401. Solo se degrada el camino SSO (FR-006).

Tests nuevos (junto a `test_callback_sin_cookie_400`, `test_callback_con_state_ajeno_400`,
`test_callback_con_cookie_falsificada_400` y `test_callback_sin_code_400`,
`test_sso_api.py:322-430`): cada caso de la tabla deja **exactamente un** evento
`auth_sso_denied`, y ninguna columna del evento contiene el `state` ni el `code` usados. Además:

- **flujo**: con el reloj de la ventana inyectado, `tope + 5` rechazos de flujo dejan exactamente
  `tope` eventos, todos con su status intacto, y un warning con el conteo omitido;
- **canje** (F1): cookie válida + `code` basura, `tope + 5` veces → exactamente `tope` eventos y
  `tope` llamadas al proveedor (el doble del proveedor cuenta las llamadas), los `tope + 5` con
  `401 sso_identidad_no_verificada` intacto, y un warning con el conteo omitido;
- **contadores independientes**: agotar el tope de flujo no impide un canje (el doble del
  proveedor recibe la llamada), y agotar el de canje no impide auditar un rechazo de flujo;
- al abrirse la ventana siguiente se vuelve a auditar y a llamar al proveedor;
- los rechazos de identidad (`:313`, `:379`) siguen auditándose con los dos topes agotados.

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
