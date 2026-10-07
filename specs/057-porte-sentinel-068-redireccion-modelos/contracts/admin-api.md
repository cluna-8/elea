# Contrato — API de administración (delta de Eleia)

**Base**: rigen tal cual `contracts/admin-api.md` de la 068 (`/api/v1/redirect/*`: política, posturas,
publicados, reglas, destinos, vista previa, registro de cambios) y la API del catálogo de la 069 que
trae la copia de `sentinel/` (`sentinel/catalog/api/admin.py`). Credenciales write-only; todo cambio con
`reason` y registro en el registro de cambios (FR-008). Errores con el formato de la API de
administración de la base; textos neutros.

## Regiones del perfil [BASE] (FR-030, FR-031, R13, R23)

| Método y ruta | Rol | Cuerpo / respuesta |
|---|---|---|
| `GET /api/v1/redirect/regions` | admin de empresa, cumplimiento, super-admin (lectura) | lista de regiones visibles: instalación + las de la empresa; incluye `name`, `jurisdictions`, `region_profiles`, `default_posture`, `is_zone`, `level` |
| `POST /api/v1/redirect/regions` | super-admin (instalación); cumplimiento (empresa) | `{name, level, jurisdictions[], region_profiles[], default_posture: reject_offregion\|masked_offregion\|masked_all\|allow, is_zone, reason}`; 409 si `name` o un `region_profile` ya está tomado en el nivel |
| `PATCH /api/v1/redirect/regions/{id}` | mismos roles | cualquier campo salvo `level`; `reason` obligatorio; el antes/después va al registro |
| `DELETE /api/v1/redirect/regions/{id}` | mismos roles | 409 si es la región que resuelve el perfil de la instalación |
| `GET /api/v1/redirect/regions/effective` | cualquier rol de administración | región efectiva del que pide (empresa > instalación > respaldo fijo) y su `default_posture` |

La escritura de posturas (`/api/v1/redirect/postures`) sigue el contrato de la 068 con un cambio
(FR-023; data-model §1; QA A8): una fila del **admin de empresa** menos estricta que la postura efectiva
de su alcance ⇒ `422 {"code": "posture_less_strict"}`; sus filas solo restringen al resolver y nunca quitan el forzado que impone la postura de cumplimiento o
super-admin (data-model §1). Las filas
explícitas no quitan el piso de enmascarado de `default_posture` (FR-031), así que agregar filas nunca
relaja. Un destino sin jurisdicción de inferencia se rechaza con cualquier fila.

**Rol real** (QA A6; R30): las escrituras de regiones, `default_posture` y relajaciones exigen el rol
`compliance_officer` o `super_admin`; el `tenant_admin` del tenant declarado en `REDIRECT_OPERATOR_TENANT`
recibe `403` en ellas (esa variable no se define en Eleia).

**Estado** (R28): `GET /api/v1/redirect/health` (sin sesión; solo estado, sin datos de empresas) ⇒ `200
{"status": "ok"}` o `503 {"status": "degraded", "reason": "region_unresolved" | "region_row_missing"}`
cuando rige el respaldo en código. La **relajación por región** cambia `default_posture` (de `masked_all` a
`masked_offregion`) con `reason`: el super-admin hace `PATCH` de la fila de instalación (afecta a todas
las empresas); el cumplimiento de una empresa hace `POST` de una fila de nivel empresa con los mismos
`region_profiles` (gana sobre la de instalación solo para su empresa). El admin de empresa recibe `403`.

## Relajaciones del enmascarado forzado por destino [BASE] (FR-031a, R24)

| Método y ruta | Rol | Cuerpo / respuesta |
|---|---|---|
| `GET /api/v1/redirect/masking-relaxations` | admin de empresa, cumplimiento, super-admin (lectura) | relajaciones vigentes y revocadas visibles para la empresa (instalación + empresa), con `entry_id`, `level`, `reason`, autor, rol y fechas |
| `POST /api/v1/redirect/masking-relaxations` | cumplimiento (empresa); super-admin (instalación) | `{entry_id, level, reason}`; `422` con `motivo` si la ficha no tiene jurisdicciones de inferencia, entidad y control cargadas, si `zero_data_retention` no es `true` o si un agregador no tiene lista de proveedores; `403` para cualquier otro rol |
| `DELETE /api/v1/redirect/masking-relaxations/{id}` | mismos roles | `{reason}`; revoca (no borra la fila) |

Ninguna relajación se acepta sobre un destino sin jurisdicción de inferencia; no cambia una postura
*solo jurisdicciones permitidas*.

## Reglas de habilitación explícita [BASE] (FR-029, R14)

| Método y ruta | Rol | Cuerpo / respuesta |
|---|---|---|
| `GET /api/v1/catalog/enablement-rules` | admin de empresa, cumplimiento, super-admin | reglas de instalación + empresa |
| `POST /api/v1/catalog/enablement-rules` | super-admin (instalación); cumplimiento o admin de empresa (empresa, solo **agrega**) | `{kind: provider\|api_host\|jurisdiction, value, level, reason}`; `jurisdiction` compara contra inferencia, entidad y control de la ficha; re-evalúa `blocked_by_default` de las entradas afectadas y devuelve cuántas cambiaron |
| `DELETE /api/v1/catalog/enablement-rules/{id}` | super-admin (instalación); cumplimiento (empresa) | el admin de empresa no puede borrar |

En Eleia no se siembra ninguna regla (D1): la lista arranca vacía.

## Habilitación de una entrada bloqueada (sin cambios de forma; precisión)

`POST /api/v1/catalog/entries/{id}/enable` con `{reason}` obligatorio
(`sentinel:sentinel/catalog/api/admin.py:608-609`, `require_role("admin", "compliance_officer")`).
Registra `enabled_at`, `enabled_by`, `enable_reason`. 409 si la entrada no está bloqueada. La residencia
se sigue evaluando.

## Ficha del destino: entidad responsable y jurisdicción de control [BASE] (FR-028a, R25)

La ficha (`ext_compliance_sheet`) que la API del catálogo ya expone suma un campo:

| Campo | Lectura/escritura | Reglas |
|---|---|---|
| `provider_legal_entity` | ya existe | se muestra como «Entidad responsable» |
| `entity_jurisdiction` | ya existe | código ISO o zona |
| `control_jurisdiction` | **nuevo**, opcional | código ISO o zona; vacío = sin cargar (no cuenta como en región) |
| `inference_jurisdiction` | ya existe | vacío/`unknown` ⇒ un pedido redirigido a ese destino se rechaza con cualquier postura, fila o relajación (FR-028) |

**Rol de escritura** (QA A7; R30): `provider_legal_entity`, `entity_jurisdiction`, `control_jurisdiction`,
`inference_jurisdiction` y `zero_data_retention` solo `compliance_officer` y `super_admin`; un
`PUT …/entries/{id}/sheet` del admin de empresa que cambie alguno ⇒ `403`, el resto de la ficha sigue
editable por él.

La respuesta de la entrada incluye `in_region: bool` (regla de FR-028a contra la región efectiva) para
el panel. Cambiar cualquiera de estos campos queda en el registro de cambios y re-evalúa reglas de
habilitación y, si la ficha deja de cumplir las precondiciones de una relajación por destino, la
revoca (`revoke_reason = precondicion_incumplida`) en el mismo cambio.

## Entrada `azure`: verificación del despliegue (R9)

`POST /api/v1/catalog/entries` y `PATCH …/{id}` con `provider = azure`: la respuesta incluye
`deployment_check: {status: ok|not_found|error, checked_at}`; con `not_found` la entrada queda
`inactive` con el motivo y el texto «El despliegue `<real_model>` no existe en el recurso configurado».
`POST /api/v1/catalog/entries/{id}/check` re-ejecuta la verificación.

## OpenRouter (R19)

Alta o edición de una entrada `openrouter` sin `provider_options.providers_allowlist` no vacía ⇒ 422.
`zdr` y `data_collection` no se aceptan en `false`.

## Canal interno (QA A10; R31)

`GET /api/v1/internal/model-credential` (extensión) ⇒ `404` salvo `CATALOG_DIRECT_ENABLED` encendida (vacía
en Eleia); la función sigue disponible en proceso para el chat de la consola. Todo `/api/v1/internal/*`
exige secreto y origen de red interna (S15).
