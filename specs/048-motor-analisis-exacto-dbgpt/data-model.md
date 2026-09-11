# Data Model: Motor de análisis exacto de datos (DB-GPT)

## Entidades

### `Workspace.kind` (extiende la tabla existente, spec 043)

No se crea una tabla nueva — se agrega una columna `kind` (`"rag" | "exact_analysis"`, default
`"rag"` para no romper filas existentes) a `workspaces`. Un espacio de análisis exacto es un
`Workspace` con `kind="exact_analysis"`: reusa `WorkspaceMembership` (pertenencia/dueño/miembro),
RLS, y el patrón "sin asignar" de la 043 sin duplicar ninguno de los tres.

| Columna | Tipo | Notas |
|---|---|---|
| `kind` | `VARCHAR`, `CHECK (kind IN ('rag','exact_analysis'))` | Nueva. Default `'rag'`. |

Migración: `ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS kind VARCHAR NOT NULL DEFAULT 'rag'`
+ el `CHECK` — mismo criterio de idempotencia de las migraciones 018/019.

### `svc.dbgpt-excel` (nueva llave de servicio)

Análoga a `svc.anythingllm-provider`/`svc.rag-masking` (spec 043) — un `User` con
`account_type='service'`, y su `APIKey` asociada:

| Campo | Valor |
|---|---|
| `username` | `svc.dbgpt-excel` |
| `account_type` | `service` |
| `tool_type` (de la `APIKey`) | `servicio` |
| `can_act_on_behalf` | `true` — a diferencia de `svc.anythingllm-provider` (deliberadamente
`false`, "habla con el motor por su cuenta"), esta llave SÍ necesita llevar "en nombre de quién"
en cada llamada, porque acá el pedido explícito es que el costo se atribuya a la persona real
(FR-005) — mismo criterio ya usado por `svc.rag-masking`. |

### `AuditLog` (reusa el esquema existente, sin columnas nuevas)

Cada llamada de modelo que DB-GPT dispara vía `svc.dbgpt-excel` queda auditada con
`acted_for_user_id` apuntando a la persona real (mismo mecanismo que ya usa el chat directo y el
enmascarado, contrato 2 de la 043) y `surface` distinguiéndola como tráfico de análisis exacto
(mismo criterio que `surface='servicio'` ya usa para el enmascarado) — el valor exacto de
`surface` para este caso es decisión de implementación (p. ej. `'exact_analysis'`), a agregar al
vocabulario `_SURFACES_BACKFILL`/`SURFACES` ya existente si aplica.

### `Consulta SQL generada` (no persistida como entidad propia — vive en `AuditLog`)

El SQL efectivo que DB-GPT ejecutó para responder una pregunta, si DB-GPT lo expone en su
respuesta (a confirmar en implementación, ver `research.md` R2/R3), se guarda como parte de la
evidencia auditable de la request — mismo criterio metadata-only de `AuditLog` (Principio II):
el SQL en sí no es contenido de PII, es la evidencia de "qué se ejecutó", análogo a
`guardian_events`.

## Relaciones

```
Workspace (kind='exact_analysis')
  ├── WorkspaceMembership (owner/member) — igual que un Workspace RAG
  └── (sin WorkspaceThread — el análisis exacto no tiene "hilos", cada pregunta es un request)

User (svc.dbgpt-excel, account_type='service')
  └── APIKey (tool_type='servicio', can_act_on_behalf=true)
        └── AuditLog[] (acted_for_user_id = persona real, surface='exact_analysis')
```

## Validaciones

- `Workspace.kind='exact_analysis'` solo acepta archivos con extensión tabular (`.csv`, `.xlsx`,
  `.xls`) en la subida — rechazo explícito de otros formatos (FR de la spec 046 US2, ya
  especificado ahí; este backend solo lo hace cumplir del lado del motor si DB-GPT no lo rechaza
  por su cuenta).
- El SQL auditado, si está disponible, se valida con `sqlglot` como solo-`SELECT`/`WITH` — ver
  `research.md` R3 para el alcance real de esta validación (evidencia/alarma, no bloqueo garantizado
  a nivel de aplicación, dado que DB-GPT ejecuta puertas adentro).
