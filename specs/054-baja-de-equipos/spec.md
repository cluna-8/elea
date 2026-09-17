# Feature Specification: Baja de equipos (grupos)

**Feature Branch**: `054-baja-de-equipos`

**Created**: 2026-09-17

**Status**: 🟢 Implementada y verificada — ver sección de implementación.

**Repos que toca**: `cluna-8/elea` (`backend/src/models/user.py`, `backend/src/api/users.py`,
`backend/src/schemas/user.py`, `backend/alembic/versions/`, `frontend/src/pages/UsersPage.tsx`,
`frontend/src/services/api.ts`).

**Input**: hallazgo del dueño del producto (17-sep-2026), probando en vivo la atribución de
costos de la spec 053: necesitaba un equipo descartable para la prueba y no había forma de
sacarlo de encima después. Textual: *"es un error grave el no poder desactivar un grupo"*.

## Diagnóstico verificado en código (17-sep)

| # | Qué se esperaba | Qué había en realidad |
|---|---|---|
| 1 | Un equipo se puede dar de baja igual que un usuario | `Group` (`backend/src/models/user.py:37-66`) no tenía **ningún** campo de ciclo de vida — ni `is_active` ni `deactivated_at` — a diferencia de `User`, que sí los tiene. |
| 2 | El panel tiene un botón para eso | `groups.py` solo expone `PUT`/`DELETE .../compliance` (el *perfil* de cumplimiento del equipo, no el equipo en sí). `users.py` solo tenía `POST /groups` (alta) y `GET /groups` (listado) — ningún `DELETE`. El frontend (`UsersPage.tsx`) solo tenía el botón "Editar perfil" en la fila de cada equipo. |
| 3 | Es coherente con cómo se maneja la baja de un usuario | `DELETE /users/{id}` (`deactivate_user`, `users.py:616-651`) ya existe hace tiempo (spec 043 US5) y resuelve exactamente este problema para personas: no borra físicamente, revoca llaves, libera lo que el usuario tenía asignado, y la auditoría histórica queda intacta. El mismo patrón nunca se replicó para equipos. |

**Es código de la base (Guardian), no de la localización argentina** — mismo criterio que otros
hallazgos de esta línea: se implementa acá porque acá se encontró, y se documenta para portar a
Sentinel por handoff, no por gemelo reescrito (ver `HANDOFF-elea-a-sentinel.md` de esta carpeta).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dar de baja un equipo sin perder su historial (Priority: P1)

Un administrador creó un equipo (por ejemplo para probar algo, o porque un equipo real de la
empresa dejó de existir) y necesita sacarlo de la lista activa sin que eso borre el gasto,
la auditoría o cualquier otro registro histórico que quedó asociado a ese equipo mientras
estuvo activo.

**Por qué esta prioridad**: sin esto, cada equipo creado por error o para una prueba queda para
siempre en el panel, ensuciando la lista y confundiendo a cualquiera que la mire — exactamente lo
que le pasó al dueño del producto probando la spec 053.

**Independent Test**: crear un equipo, asignarle un miembro y una Connection propia, darlo de
baja, y confirmar que (a) desaparece de la lista por defecto, (b) el miembro queda "sin equipo"
en vez de borrado, (c) la Connection del equipo queda revocada, y (d) cualquier fila de auditoría
o presupuesto que ya existía con el `group_id` de ese equipo sigue intacta y visible bajo su
nombre.

**Acceptance Scenarios**:

1. **Given** un equipo activo con al menos un miembro, **When** un administrador lo da de baja,
   **Then** el equipo deja de aparecer en el listado por defecto, pero sigue existiendo (no se
   borra la fila).
2. **Given** el mismo equipo, **When** se completa la baja, **Then** el miembro que tenía asignado
   queda sin equipo (no se borra el usuario, no se toca su cuenta).
3. **Given** un equipo con una Connection (llave virtual) propia y activa, **When** se da de baja
   el equipo, **Then** esa Connection queda revocada.
4. **Given** un equipo que ya generó gasto y quedó auditado mientras estaba activo, **When** se da
   de baja, **Then** ese gasto histórico sigue apareciendo en el panel de Costos bajo el nombre
   del equipo, sin cambios.
5. **Given** un equipo ya dado de baja, **When** se intenta dar de baja de nuevo, **Then** el
   sistema responde con un error claro, no lo vuelve a procesar en silencio.

### Edge Cases

- ¿Qué pasa si se intenta asignar un usuario nuevo a un equipo ya dado de baja? No cubierto en
  esta ronda — el equipo desaparece de los listados que alimentan los selectores de alta (mismo
  filtro que el listado general), así que hoy no debería ser seleccionable; no se agregó un
  chequeo explícito del lado del servidor para ese caso puntual.
- No hay reactivación implementada en esta ronda (mismo alcance que la baja de usuario, que
  tampoco tiene un botón de "reactivar" dedicado hoy).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema DEBE permitir dar de baja un equipo sin borrarlo físicamente.
- **FR-002**: Al dar de baja un equipo, el sistema DEBE liberar a sus miembros actuales a "sin
  equipo", sin tocar sus cuentas.
- **FR-003**: Al dar de baja un equipo, el sistema DEBE revocar cualquier Connection (llave
  virtual) que dependa directamente de ese equipo.
- **FR-004**: El listado de equipos DEBE excluir por defecto a los dados de baja, con una forma
  explícita de pedir también los inactivos.
- **FR-005**: El historial de auditoría y de gasto de un equipo dado de baja NO DEBE modificarse
  ni ocultarse.
- **FR-006**: Dar de baja un equipo ya dado de baja DEBE responder con un error claro (409), no
  reprocesar en silencio.

### Key Entities

- **Group**: gana `is_active` (bool, default `true`) y `deactivated_at` (fecha, nulo si sigue
  activo) — mismo par de campos que ya tiene `User`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un equipo dado de baja deja de aparecer en el selector de "Asociar a Equipo" al
  registrar un nuevo miembro (consecuencia de FR-004, mismo endpoint que alimenta ese selector).
- **SC-002**: El gasto histórico de un equipo dado de baja sigue siendo idéntico antes y después
  de la baja, verificado comparando el panel de Costos.
- **SC-003**: Ningún usuario que era miembro de un equipo dado de baja pierde su cuenta ni su
  historial propio.

## Assumptions

- Se sigue el mismo criterio ya sellado para la baja de usuarios (spec 043 US5): baja lógica, no
  física; revocación de credenciales propias; lo que el ente tenía asignado queda "sin asignar"
  en vez de borrado.
- No se agrega reactivación en esta ronda, por paridad con el estado actual de la baja de
  usuarios (tampoco la tiene).
- La migración usa un id de revisión generado por hash (`alembic revision`, no un número
  secuencial), siguiendo la advertencia ya documentada en `specs/README.md` sobre el choque de
  numeración de migraciones entre las tres líneas (Base/Sentinel/Eleia).

## Implementación (17-sep)

- **FR-001/FR-004/FR-006**: migración `7a6fee614cfd_groups_deactivation.py` (agrega
  `is_active`/`deactivated_at` a `groups`, id por hash, no secuencial); `Group` en
  `backend/src/models/user.py` gana los mismos dos campos; `GroupResponse`
  (`backend/src/schemas/user.py`) los expone; `GET /users/groups` filtra por `is_active=true`
  salvo `?include_inactive=true`; `DELETE /users/groups/{id}` (`deactivate_group`,
  `backend/src/api/users.py`) hace la baja, con 404 si no existe y 409 si ya estaba de baja.
- **FR-002/FR-003**: `deactivate_group` libera `user.group_id = None` para todos los miembros
  actuales y revoca (`is_active=false`) las `APIKey` con `group_id` igual al del equipo —
  simétrico a lo que `deactivate_user` ya hace para las llaves propias de una persona.
- **FR-005**: nada de esto toca `audit_logs` ni `budgets` — ambos solo referencian `group_id`,
  nunca se filtran ni se escriben en esta operación.
- **Frontend**: botón "Dar de baja" en la fila de cada equipo (`UsersPage.tsx`), mismo patrón de
  confirmación fuerte que ya usa la baja de usuario (escribir el nombre exacto para confirmar).
- **Verificación**: `backend/tests/integration/test_group_deactivation_054.py` (2 tests: baja
  completa con miembro + Connection + reintento en 409; filtro del listado por defecto vs.
  `include_inactive`). Migración corrida y confirmada contra Postgres real (se detectó y corrigió
  de paso un problema de caché de bytecode de Alembic al generar la revisión — documentado en el
  historial de commits para quien lo repita). Suite completa: 1234 tests unitarios + toda la
  integración, sin regresiones. TypeScript del frontend compila sin errores
  (`npx tsc --noEmit`).
