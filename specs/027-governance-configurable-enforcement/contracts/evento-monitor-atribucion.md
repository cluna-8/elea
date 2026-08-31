# Contrato — Atribución por pedido: `applied_layers` + evento de monitor extendido

Contrato del esquema de atribución compartido entre la columna durable
(`audit_logs.applied_layers` / `blocked_by_layer`) y el feed efímero del monitor, para
**ambos productores a la vez**: el logger del motor
(`litellm/extensions/sentinel_audit_logger.py:143-152`) y el passthrough del gateway
(`backend/src/api/gateway.py:304-315`). `guardian_events` queda **congelado como legado,
sin migración** (D6).

## El elemento de atribución (shape único)

1. **Un solo shape, definido una vez**: la lista `applied_layers` es una lista de

   ```json
   { "layer_code": "<layer_key del registry>",
     "status":  "applied | skipped | not_configured | requires_credential | delegated | degraded",
     "decision": "allow | mask | flag | block | null",
     "count": 3 }
   ```

   `decision` es `null` cuando `status != applied` (la capa no corrió: no decidió nada) —
   idéntico a la tabla canónica de data-model §3.1.

   `count` es **opcional**: entero, presente solo con `status=applied` — nº de ocurrencias
   (entidades detectadas/enmascaradas, secretos). Es el único contador permitido y lo que hace
   contable el registro D8 ("PII detectada [count], no enmascarada por configuración").

   La definición canónica de la columna vive en [data-model.md](../data-model.md) — este
   contrato la **referencia, no la duplica**: columna, evento del motor y evento del
   gateway llevan **exactamente el mismo elemento**, serializado desde el
   `PolicyResult.applied_layers` del resolutor
   ([resolutor-perfil.md](./resolutor-perfil.md)) **sin transformar**. Prohibido que un
   productor "resuma distinto".
2. **Solo códigos y contadores (C1)**: las **cuatro** claves de arriba y nada más — sin campo
   `detail`, sin texto libre, sin valores detectados. El patrón vigente de los triggers
   (`f'Nombre personalizado bloqueado: {name}'`, `guardian_service.py:268`) es una fuga y
   queda explícitamente **prohibido** en este esquema. Test negativo: ningún elemento tiene
   claves fuera de las 4, ningún valor es string salvo `layer_code`/`status`/`decision` (de
   sus enums), ningún valor contiene texto del prompt.
3. **Identidad estable**: `layer_code` es el `layer_key` del registry `GOVERNANCE_LAYERS`
   (D1) — jamás `guardian.name` (editable/white-label; un rename del cliente rompería la
   atribución histórica, D6) ni `engine_guardrail_name` (Principio VII).
4. **Tres ejes separados, nunca reconflados**: identidad (`layer_code`) + estado de la
   capa (`status`) + decisión sobre el pedido (`decision`). El eje único `action` del
   legado (donde `DELEGATED` convivía con `MASK`/`BLOCK`) no se replica.

## Columnas durables (`audit_logs`)

5. `applied_layers` JSONB (lista del elemento §1) + `blocked_by_layer` VARCHAR indexable
   (`layer_code` o `NULL`) — hermanas de `masked_entities`/`guardian_events`
   (`audit.py:26,32`). El escalar hace la atribución consultable con una query trivial,
   sin LATERAL joins (SC-005).
6. **Coherencia interna**: `blocked_by_layer != NULL` ⇔ existe un elemento con
   `decision=block` (y su `layer_code` coincide) ⇔ el status del pedido refleja bloqueo.
   Los tres productores durables escriben las columnas nuevas: `AuditService` (gateway y
   chat) y el `_INSERT_AUDIT_SQL` del motor (`sentinel_audit_logger.py:25-34`, extendido).
7. **Exhaustividad** (SC-005): todo pedido gobernado persiste `applied_layers` con TODAS
   las capas de su perfil (también las `skipped`/`not_configured`/…) — es la
   materialización durable del Principio VIII; `pipeline_metadata` del chat pasa a
   **derivarse** de esta lista, no a armarse a mano.

## Evento de monitor extendido

8. **Mismo esquema en todos los emisores**: los campos existentes del evento (`ts`,
   `tool`, `client`, `tenant`, `model`, `compliance_status`, `masked_entities`,
   `masked_preview` [, `surface`]) quedan intactos; se agregan `applied_layers` (lista del
   elemento §1) y `blocked_by_layer`. Emisores: los **2 productores de tráfico normal**
   existentes (logger del motor + passthrough del gateway) extendidos, más los emisores en
   **punto de bloqueo** de los tres planos (§11-§13 — el del chat es nuevo). El comentario
   de `gateway.py:297-299` ("MISMO esquema que sentinel_audit_logger") pasa de convención a
   contrato: extender uno sin los demás rompe el render uniforme de la vitrina y **falla
   el gate**.
9. **Best-effort, jamás en el camino del cliente**: el publish a Redis nunca afecta la
   request ni la respuesta (patrón existente, `sentinel_audit_logger.py:159-160` /
   `gateway.py:321-322`). Sigue siendo efímero (TTL 300 s, cap 100) y metadata-only.
10. **`masked_preview` SIEMPRE display-masked (C1, cierre de fuga D8)**: el preview de **todo**
    evento — incluidos los de punto de bloqueo (§12/§13), donde el bloqueo puede ocurrir ANTES
    de que `pii_detection` corra — se construye con un pase propio de display-masking sobre
    mapa desechable **más** scrub de secretos (el patrón `_safe_preview`,
    `gateway.py:135-146`), independientemente de qué capas alcanzaron a correr y de si el
    texto saliente fue enmascarado. Test negativo: ningún evento, de ningún emisor, lleva en
    `masked_preview` una entidad detectable ni un secreto en claro — tampoco los eventos con
    `pii_masking` ≠ `applied` (D8) ni los emitidos al bloquear por secreto. Sin esta regla, la
    postura legítima de D8 o un bloqueo temprano convertirían la vitrina en canal de fuga al
    feed Redis.

## Atribución en el punto de bloqueo — y el corte con la 018

11. **Plano gateway**: el camino de bloqueo ya emite `_audit` + `_publish_monitor`
    (`gateway.py:485-490`); con 027 esos dos llevan los campos nuevos con
    `blocked_by_layer` poblado.
12. **Plano motor**: hoy un bloqueo hace `return reason` (`sentinel_guardrail.py:86, :91-92`)
    → LiteLLM levanta 400 → `async_log_success_event` **nunca dispara** → ni fila ni
    evento (research D6). 027 obliga al guardrail a **publicar el evento de monitor en el
    punto de bloqueo** (best-effort, §9), con `applied_layers` + `blocked_by_layer` — el
    bloqueo deja de ser invisible en la vitrina.
13. **Plano chat (backend), mismo requisito**: los `raise` de bloqueo del pipeline del chat
    preceden hoy a todo registro (`chat.py:187/:207/:306`, research D6). 027 obliga a
    publicar el evento de monitor **en el punto de bloqueo, antes del raise** (best-effort,
    §9), con el mismo shape. Los **tres** planos emiten al bloquear; la fila durable sigue
    el corte del §14.
14. **Corte explícito (D6)**: la **fila durable** de un bloqueo en los planos donde el
    bloqueo precede al registro (**motor y chat backend**) NO es de esta spec — depende de
    la completitud/confiabilidad de auditoría de la **018** (owner: Cristian). 027 define
    los campos, emite la atribución en el punto de bloqueo y la publica al monitor en los
    tres planos; declarar SC-005 "cumplido" en esos caminos sin la 018 sería marcar verde
    una promesa que el sistema no sostiene.
