# Contrato — Panel: formulario de configuración SSO y botón de ingreso

**Base Guardian** (`frontend/` es el mismo en las dos líneas): portable a Sentinel por
cherry-pick, confirmando antes el diff de `UsersPage.tsx` (mismo caveat que la 054 y la 055).
Cubre US3 (FR-009) y la parte de D4 que toca al panel. Usa **solo** la API existente:
`GET`/`PUT /api/v1/auth/sso/config` (`backend/src/sso/admin_api.py:104-195`) y
`GET /api/v1/auth/sso/available` ([guardian-sso-api.md](guardian-sso-api.md) §1).

## 1. Pestaña "Autenticación & SSO" (`frontend/src/pages/UsersPage.tsx:1271-1376`)

La tarjeta de Entra y la grilla de "Próximamente" se quedan como están. El párrafo "contacte a su
equipo de soporte" (`:1372-1375`) se reemplaza, **solo para la tarjeta de Microsoft Entra ID**,
por un formulario.

### Visibilidad

| Quién | Ve |
|---|---|
| `super_admin`, `tenant_admin` (rol `admin` efectivo del backend, `admin_api.py:69`) | Formulario editable. |
| `compliance_officer` | **Sin formulario ni datos de config** (spec US3 AS5: quien no es `super_admin` ni `tenant_admin` no puede verla ni cambiarla): solo la tarjeta de estado de hoy. La UI no llama al `GET` de config para este rol. Residual conocido: la API de la 017 le permite el `GET` (`admin_api.py:66-68`, matriz de roles 017); no expone el secreto y cambiar la matriz está fuera de alcance. |
| Otros roles | Sin formulario ni datos de config: solo la tarjeta de estado de hoy. El acceso a la página no cambia. El backend responde 403 a cualquier `GET`/`PUT` de config (`admin_api.py:68-69`). |

### Carga inicial

`GET /auth/sso/config`:

- `200` → precarga `config.tenant_id`, `config.client_id`, `enabled` y `client_secret_configurado`.
- `404` `sso_sin_configurar` → formulario vacío, estado "No configurado".
- `403` (licencia sin `sso`, porque el router de config está detrás del mismo gate,
  `backend/tests/integration/test_sso_config_api.py:119-122`, o rol sin permiso) → aviso "El ingreso con Microsoft no está habilitado en esta licencia" y el
  formulario no se dibuja.
- Error de red u otro status → aviso de error. La pestaña no se rompe.

### Campos

| Campo | Envío en `PUT` | Regla |
|---|---|---|
| Directorio (tenant) ID | `config.tenant_id` | Obligatorio. Formato GUID validado en el cliente, solo como ayuda. El backend es la autoridad. |
| Identificador de la aplicación (client ID) | `config.client_id` | Obligatorio, mismo criterio. |
| Secreto | `client_secret` | `type="password"`, `autocomplete="off"`, **siempre vacío al cargar**. Si queda vacío se **omite** del `PUT` (conserva el guardado, `admin_api.py:170-173`). Nunca se manda `""`, porque el backend lo rechaza con `sso_secreto_vacio`. Indicador "Secreto cargado" / "Sin secreto" desde `client_secret_configurado`. |
| Interruptor "Ingreso con Microsoft activo" | `enabled` | Se guarda con el mismo `PUT`. |
| — | `provider_type: "entra"` | Fijo: es el único proveedor del build. |

`config` **no** lleva otras claves: el formulario no ofrece campos libres, para que nadie tipee
un secreto dentro de `config`, que se guarda en claro (límite conocido, `admin_api.py:34-40`).

### Guardado y errores

- `200` → toast "Configuración guardada", el secreto se vacía y se refresca el estado.
- `400` `sso_habilitado_sin_secreto`, `400` `sso_secreto_vacio`, `503` `sso_cifrado_no_disponible`,
  `400` `sso_proveedor_desconocido` → se muestra el `detail` traducido a un texto claro. Nada se
  da por guardado.
- El secreto no se loguea en consola ni queda en el estado de React después del `PUT`.

**Vuelta atrás de nivel 0** (DESPLIEGUE-Y-REVERSION.md): apagar el interruptor y guardar. El
`PUT` con `enabled:false` no exige el secreto.

## 2. Botón "Entrar con Microsoft" del panel (`frontend/src/pages/LoginPage.tsx:155-162`)

`api.getSsoAvailable()` (`frontend/src/services/api.ts:687-699`) pasa a devolver también
`return_origin` (string o `null`, mismo criterio fail-closed). El botón se dibuja solo si
`enabled === true` **y** (`return_origin` es `null` **o** igual a `window.location.origin`).

Con la URI de retorno apuntando al Hub (fase 1 de Elea), el panel no muestra el botón y los
admins siguen con contraseña, como dice la spec. Una instalación cuya URI apunta al panel (por
ejemplo la prueba local de GUIA-PRUEBA-LOCAL-SSO.md) lo sigue viendo como hoy.

La tarjeta de estado de la pestaña sigue usando solo `enabled` ("Activo" o "Próximamente"): el
SSO está activo aunque su botón viva en el Hub.

## 3. Tests (vitest, `frontend/tests/contract/`)

1. `UsersPage.sso-config.test.tsx`:
   - admin con `404` → formulario vacío;
   - `200` precarga sin secreto;
   - guardar con secreto vacío **no** manda `client_secret`;
   - guardar con secreto lo manda una vez y después el campo queda vacío;
   - errores del backend visibles;
   - `compliance_officer` sin formulario y sin llamada al `GET` de config;
   - `403` sin formulario.
2. `LoginPage.sso-origin.test.tsx`: botón visible con `return_origin` `null` o igual al origen,
   oculto con otro origen y oculto con `enabled:false` (regresión del fail-closed).
