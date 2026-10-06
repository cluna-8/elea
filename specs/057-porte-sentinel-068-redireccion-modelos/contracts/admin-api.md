# Contrato — API de administración (delta de Eleia)

**Base**: rigen tal cual `contracts/admin-api.md` de la 068 (`/api/v1/redirect/*`: política, posturas,
publicados, reglas, destinos, vista previa, registro de cambios) y la API del catálogo de la 069 que
trae la copia de `sentinel/` (`sentinel/catalog/api/admin.py`). Credenciales write-only; todo cambio con
`reason` y registro en el registro de cambios (FR-008). Errores con el formato de la API de
administración de la base; textos neutros.

## Regiones del perfil [BASE] (FR-030, FR-031, R13, R23)

| Método y ruta | Rol | Cuerpo / respuesta |
|---|---|---|
| `GET /api/v1/redirect/regions` | admin de empresa, cumplimiento, super-admin (lectura) | lista de regiones visibles: instalación + las de la empresa; incluye `name`, `jurisdictions`, `region_profiles`, `offregion_default`, `is_zone`, `level` |
| `POST /api/v1/redirect/regions` | super-admin (instalación); cumplimiento (empresa) | `{name, level, jurisdictions[], region_profiles[], offregion_default, is_zone, reason}`; 409 si `name` o un `region_profile` ya está tomado en el nivel |
| `PATCH /api/v1/redirect/regions/{id}` | mismos roles | cualquier campo salvo `level`; `reason` obligatorio; el antes/después va al registro |
| `DELETE /api/v1/redirect/regions/{id}` | mismos roles | 409 si es la región que resuelve el perfil de la instalación |
| `GET /api/v1/redirect/regions/effective` | cualquier rol de administración | región efectiva del que pide (empresa > instalación > respaldo fijo) y su `offregion_default` |

## Reglas de habilitación explícita [BASE] (FR-029, R14)

| Método y ruta | Rol | Cuerpo / respuesta |
|---|---|---|
| `GET /api/v1/catalog/enablement-rules` | admin de empresa, cumplimiento, super-admin | reglas de instalación + empresa |
| `POST /api/v1/catalog/enablement-rules` | super-admin (instalación); cumplimiento o admin de empresa (empresa, solo **agrega**) | `{kind: provider\|api_host\|jurisdiction, value, level, reason}`; re-evalúa `blocked_by_default` de las entradas afectadas y devuelve cuántas cambiaron |
| `DELETE /api/v1/catalog/enablement-rules/{id}` | super-admin (instalación); cumplimiento (empresa) | el admin de empresa no puede borrar |

## Habilitación de una entrada bloqueada (sin cambios de forma; precisión)

`POST /api/v1/catalog/entries/{id}/enable` con `{reason}` obligatorio (`sentinel:sentinel/catalog/api/admin.py:608`):
roles cumplimiento o super-admin (nivel instalación: super-admin). Registra `enabled_at`,
`enabled_by`, `enable_reason`. 409 si la entrada no está bloqueada. La residencia se sigue evaluando.

## Entrada `azure`: verificación del despliegue (R9)

`POST /api/v1/catalog/entries` y `PATCH …/{id}` con `provider = azure`: la respuesta incluye
`deployment_check: {status: ok|not_found|error, checked_at}`; con `not_found` la entrada queda
`inactive` con el motivo y el texto «El despliegue `<real_model>` no existe en el recurso configurado».
`POST /api/v1/catalog/entries/{id}/check` re-ejecuta la verificación.

## OpenRouter (R19)

Alta o edición de una entrada `openrouter` sin `provider_options.providers_allowlist` no vacía ⇒ 422.
`zdr` y `data_collection` no se aceptan en `false`.
