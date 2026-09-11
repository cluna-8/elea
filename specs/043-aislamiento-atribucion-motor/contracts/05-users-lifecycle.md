# Contrato 5 — Actualización parcial y baja de usuarios

**Consumido por**: spec 044, US4 (P2).

## `PATCH /users/{id}` (nuevo, junto al `PUT` existente que se mantiene por compatibilidad)

Todos los campos opcionales — solo se cambia lo enviado:
```json
{"role": "compliance_officer"}
```
o
```json
{"email": "nuevo@elea.com"}
```
Valida unicidad de `username`/`email` por `tenant_id` (mismo criterio que el `PUT` actual);
cambio de `role` MUST auditarse igual que hoy (`AUTH_ROLE_CHANGED`).

## `DELETE /users/{id}` (nuevo)

Baja definitiva, no física: setea `deactivated_at`, revoca todas sus llaves y sesiones activas,
libera su asiento de licencia. Reglas:
- 409 si es el propio usuario autenticado (no auto-baja).
- 409 si es el último `account_type='person'` con rol admin activo.
- Efecto en cascada: cualquier `Workspace` donde era `owner` pasa a `status='unassigned',
  owner_user_id=NULL` (contrato 1); sus `WorkspaceMembership` se cierran (no se borran, quedan
  como histórico si se necesita auditoría de quién tuvo acceso).
- La auditoría histórica (`AuditLog`) conserva su `user_id`/`acted_for_user_id` sin cambios —
  nunca se reasigna ni se anonimiza acá.

Respuesta (200): `{"status": "deactivated", "id": "uuid"}`. Un usuario dado de baja que intenta
autenticar (login o llave) recibe 401 uniforme (mismo mensaje que credenciales inválidas — no
revela que la cuenta existe pero está dada de baja).

## Reactivación

`PATCH /users/{id}` con `{"is_active": true}` sobre un usuario **suspendido** (`is_active=false`,
mecanismo ya existente) lo reactiva. Un usuario **dado de baja** (`deactivated_at` seteado)
requiere un endpoint explícito de reactivación si el negocio lo permite — fuera de alcance de esta
spec salvo que `tasks.md` lo agregue como variante de `PATCH`.
