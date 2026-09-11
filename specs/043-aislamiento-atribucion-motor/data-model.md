# Phase 1 Data Model — 043-aislamiento-atribucion-motor

Entidades nuevas y campos agregados a entidades existentes. No incluye DDL — el detalle de columnas
SQL/tipos exactos y la migración Alembic se resuelven en `tasks.md`.

## Entidades nuevas

### Workspace

Espacio de trabajo del Hub Chat, reflejo del `slug` de AnythingLLM con pertenencia propia.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID → `tenants.id` | Consistente con el resto del esquema (R1) |
| `engine_slug` | string | El `slug` real en AnythingLLM — único por tenant |
| `display_name` | string | Nombre visible ("Contabilidad") |
| `owner_user_id` | UUID → `users.id`, nullable | Nullable = "sin asignar" (backfill de instalaciones existentes, FR-006) |
| `status` | enum | `active` \| `unassigned` |
| `created_at`, `updated_at` | timestamp | |

Reglas: `(tenant_id, engine_slug)` único. Al dar de baja al dueño (US5), `owner_user_id` pasa a
`NULL` y `status` a `unassigned` (FR-042), nunca se borra el workspace ni sus documentos.

### WorkspaceMembership

| Campo | Tipo | Notas |
|---|---|---|
| `id` | UUID | PK |
| `workspace_id` | UUID → `workspaces.id` | |
| `user_id` | UUID → `users.id` | |
| `role` | enum | `owner` \| `member` |
| `created_at` | timestamp | |

Reglas: `(workspace_id, user_id)` único. Exactamente un `owner` activo por workspace (o ninguno si
`status='unassigned'`). Borrar una fila de membresía = quitar acceso (no borra hilos, FR-042).

### WorkspaceThread

Refleja el `threadSlug` de AnythingLLM con dueño explícito.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | UUID | PK |
| `workspace_id` | UUID → `workspaces.id` | |
| `owner_user_id` | UUID → `users.id` | Quien lo creó |
| `engine_thread_slug` | string, nullable | `NULL` = hilo principal del workspace para ese usuario |
| `created_at` | timestamp | |

Reglas: `(workspace_id, owner_user_id, engine_thread_slug)` único. El "hilo principal" es un caso
con `engine_thread_slug = NULL` (uno por usuario por workspace).

## Cambios a entidades existentes

### User (`backend/src/models/user.py`)

| Campo nuevo | Tipo | Notas |
|---|---|---|
| `account_type` | enum | `person` \| `service`, default `person` (FR-030) |
| `deactivated_at` | timestamp, nullable | Baja definitiva (FR-041); distinto de `is_active` (suspensión reversible) |
| `deactivated_reason` | string, nullable | Opcional, para auditoría admin |

Reglas: un usuario con `deactivated_at IS NOT NULL` no autentica (login ni llaves), no cuenta en
asientos de licencia (junto con `account_type='service'`), y no puede ser el `owner` de un
`Workspace` (dispara FR-042 al darlo de baja).

### AuditLog (`backend/src/models/audit.py`)

| Campo nuevo | Tipo | Notas |
|---|---|---|
| `acted_for_user_id` | UUID → `users.id`, nullable | "En nombre de" (R2); `NULL` cuando el que autentica y el usuario final coinciden o no aplica |
| `surface` | string, nullable | Superficie de la Connection (`chat-ui`, `servicio`, etc. — enum `SURFACES` existente), separada de `model` (R5) |
| `event_type` | string, default `traffic` | `traffic` \| `license_evidence` (R5) |
| `document_group_id` | UUID, nullable | Agrupa los N chunks de un mismo documento enmascarado como una operación (FR-013) |

Reglas de lectura: las vistas de "modelos"/"costos por usuario" filtran
`event_type='traffic' AND model IS NOT NULL`, y agrupan gasto por
`COALESCE(acted_for_user_id, user_id)`.

### Connection / APIKey (`backend/src/models/budget.py`)

| Campo nuevo | Tipo | Notas |
|---|---|---|
| `can_act_on_behalf` | boolean, default `false` | Allowlist explícita para aceptar `X-Guardian-Acting-User` (R2, FR-014) |
| `tool_type` | *(ya existe)* | El instalador deja de usar `chat-ui` para llaves de servicio; nuevo valor `servicio` (FR-014) |

## Contratos hacia PlaceholderMap (sin persistencia nueva)

`document_id` viaja en el body de `/gw/inspect` (campo opcional, string, efímero) — **no es una
entidad persistida**, es un parámetro de request que el motor consume en memoria (R4). No se
agrega ninguna tabla ni clave Redis nueva para esto; reutiliza la bóveda de la 042 tal cual.

## Diagrama de relaciones (alto nivel)

```
tenants ──< workspaces ──< workspace_memberships >── users
             │                                          │
             └──< workspace_threads >───────────────────┘
                                                          │
users ──< audit_logs (user_id = quien autenticó) ────────┤
                     (acted_for_user_id = en nombre de) ──┘
```

## Migraciones

Una migración Alembic nueva (`018_workspaces_service_accounts_audit_surface.py` o el próximo
número libre en `backend/alembic/versions/`) que: crea `workspaces`, `workspace_memberships`,
`workspace_threads`; agrega columnas a `users`, `audit_logs`, `api_keys`; backfilla
`account_type='service'` para las filas ya creadas por `install.sh` (identificables por
`username LIKE 'svc.%'`, criterio a confirmar en tasks.md); backfilla `event_type`/`surface` según
R5. Sin downtime esperado (todas las columnas nuevas son nullable o con default) — mismo patrón
usado en la 042 para actualizar `eleavdmia` en caliente.
