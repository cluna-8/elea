# Contrato 2 — Identidad "en nombre de" y autoservicio de presupuesto/consumo

**Consumido por**: spec 044, US2 (P1), US6.

## Cabecera `X-Guardian-Acting-User`

Cualquier pedido que el Hub Chat haga con una llave de servicio (`can_act_on_behalf=true`, ver
`data-model.md`) hacia `/gw/inspect` o hacia el nuevo endpoint de chat con contexto (contrato
implícito de R3, ver `03-masking-document-id.md` y el plan de tareas para su endpoint exacto) MUST
incluir esta cabecera con el `user_id` de la persona autenticada por sesión en el backend — nunca
construida por el cliente Node a partir de datos no verificados.

Validación del lado del backend/motor:
- La llave que autentica MUST tener `can_act_on_behalf=true`; si no, la cabecera se ignora y se
  audita el intento (FR-010).
- El `user_id` de la cabecera MUST pertenecer al mismo `tenant_id` de la llave; si no, 403.
- Si falta la cabecera en una llave con `can_act_on_behalf=true`, el pedido se atribuye a la propia
  cuenta de servicio (comportamiento actual, sin romper otros usos de la llave).

## Endpoint de autoservicio: `GET /users/me/budget`

Reemplaza la necesidad de que el Hub Chat use una sesión de admin para leer presupuesto
(`client/server.js:280-291` actual). Auth: JWT de sesión del propio usuario.

Respuesta (200):
```json
{"used_usd": 0.42, "max_usd": 1.00, "status": "ok"}
```
`status` es `"ok"` o `"exceeded"`. Se recalcula en cada llamada (no cacheado del lado del backend
más allá de lo que ya haga el modelo de `Budget`).

## Enforcement 402 (FR-012)

Todo endpoint de consumo (enmascarado, chat con o sin espacio) MUST evaluar el presupuesto del
`acted_for_user_id` (o `user_id` si no hay "en nombre de") **antes** de llamar al proveedor, y
responder 402 con copy neutro si está agotado:
```json
{"detail": "Alcanzaste tu presupuesto asignado.", "code": "budget_exceeded"}
```
Esto cierra el "fallback a admin por defecto" que la Constitución (Security & Compliance
Constraints #3) marca como agujero a cerrar.

## Auditoría de enmascarado por documento (FR-013)

`/gw/inspect` MUST aceptar un `document_group_id` (ver contrato 3) y agregar los N chunks de un
mismo documento en **una** fila de auditoría (o N filas con el mismo `document_group_id` que las
vistas de consumo agregan por ese campo — decisión de implementación libre en tasks.md), sin costo
de proveedor, y con `surface` propio (no `model='chat-ui'`).
