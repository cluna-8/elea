# Quickstart — Validación de 044 (Eleia Hub + Eleia Guardian)

Guía manual/scriptable para validar la 044 sobre una 043 real desplegada (no dobles de prueba —
esto es el guion de integración de la US6, obligatorio antes de cerrar cualquier P1).

## Prerrequisitos

- Backend + motor de la spec 043 desplegados y con su propio `quickstart.md` en verde.
- `client/` y `frontend/` corriendo con los cambios de esta spec (`docker compose up` local, o
  contra `eleavdmia` en un espacio de prueba, como se hizo en la 042).
- Dos usuarios de prueba (`ana`, `luis`) con navegadores/sesiones separadas.
- El CSV real del cliente con un nombre repetido en varias filas.

## 1 — Aislamiento visible en el Hub (US1)

1. Login como `ana` en el Hub → crear espacio "Contabilidad" → subir el CSV.
2. Login como `luis` en otro navegador → la lista de espacios NO muestra "Contabilidad".
3. `luis` abre la URL directa del espacio (id copiado a mano) → ve "No tenés acceso a este
   espacio", sin datos.
4. `ana` agrega a `luis` como miembro (panel de miembros del espacio) → `luis` recarga → ahora lo
   ve, pregunta sobre el CSV, y los hilos de cada uno no se cruzan.
5. Sin cookie de sesión (ventana privada, sin login) → cualquier URL del Hub pide iniciar sesión,
   sin mostrar datos.

**Esperado**: los 5 pasos pasan sin intervención manual en el backend.

6. Desde una máquina fuera del compose (o `curl` al puerto 3001 del host), intentar hablar directo con el motor de documentos → debe fallar por conexión rechazada, no responder ningún dato (fix del 08-sep, verificar que sigue aplicado).

## 2 — Presupuesto visible y aplicado (US2)

1. `ana` (con presupuesto bajo, p. ej. $1 configurado por el admin) hace 2-3 preguntas en el
   espacio → el badge de presupuesto sube tras cada respuesta (< 5s).
2. Al agotarlo, `ana` intenta preguntar de nuevo → ve el aviso "Alcanzaste tu presupuesto..." antes
   de que se envíe el pedido (o inmediatamente después si el bloqueo es del backend).
3. El admin, en Eleia Guardian → Costos, filtra por `ana` → ve las preguntas con costo real y
   modelo real, y la subida del CSV como una operación de enmascarado sin costo.
4. El admin verifica que nada quedó bajo `svc.anythingllm-provider` ni `svc.rag-masking`.

## 3 — Enmascarado coherente (US3)

1. `ana` sube el CSV real del cliente (con "Julián" repetido en filas separadas por más de un
   trozo de 4000 caracteres).
2. El resumen de protección que muestra el Hub tras la subida cuenta "Julián" una sola vez.
3. `ana` pregunta "¿qué registros tiene Julián?" → la respuesta lista todas sus filas y muestra el
   nombre real (no un placeholder).
4. `ana` sube el mismo CSV de nuevo (documento distinto) → el resumen es coherente, y el
   placeholder interno (verificable solo por quien tenga acceso a logs/backend, no por la UI) es
   distinto del de la primera subida.

## 4 — Panel de usuarios completo (US4)

1. El admin edita solo el rol de un usuario → el resto de sus datos no cambia.
2. El admin edita solo el email del mismo usuario.
3. El admin desactiva al usuario → no puede loguear; lo reactiva → puede loguear de nuevo.
4. El admin da de baja a otro usuario (confirmando con su nombre de usuario) → no puede loguear;
   su consumo histórico sigue visible en Costos bajo su nombre.
5. El admin intenta darse de baja a sí mismo → la UI lo impide con una explicación.
6. La sección "Cuentas de servicio (2)" aparece plegada, solo lectura, con el propósito de cada
   una — ninguna de las dos aparece en la tabla principal de personas.

## 5 — Sin nombres de motor/proveedor (US5)

1. Se detiene el contenedor del motor de documentos a propósito → `ana` pregunta en un espacio →
   ve "El servicio de documentos no está disponible..." sin nombres técnicos.
2. Se inspecciona el código fuente servido del Hub (`Ver código fuente` del navegador) → sin
   "AnythingLLM"/"LiteLLM"/"Presidio" en ningún lado, ni en comentarios.
3. En Eleia Guardian → Seguridad, la tarjeta de detección NLP muestra un nombre neutro.
4. El título de la pestaña del panel es el de la marca configurada de Eleia, no "Sentinel Secure AI
   Gateway".

## 6 — Migración de la instalación existente (US1, escenario de continuidad)

1. Sobre una copia (o la instalación real del cliente, en un espacio de prueba creado y borrado —
   mismo criterio que la 042) con los 3 espacios reales (`Area 1`, `Contabilidad`, `Análisis NDA`):
   tras desplegar 043+044, el admin ve los 3 en "Sin asignar" (panel o Hub).
2. El admin les asigna miembros → los usuarios correspondientes empiezan a verlos.
3. Los documentos e hilos previos siguen consultables; los documentos subidos antes de esta feature
   muestran el aviso de "esquema anterior" al preguntar por un dato protegido.

## Registro del resultado

Cada corrida de este guion (local desde cero, y sobre una copia/la instalación real) se documenta
en `specs/044-hub-chat-panel-admin/CHANGELOG.md` (crear si no existe), con el mismo nivel de
detalle que `specs/042-rediseno-ui-boveda-pii-hilos/CHANGELOG.md` — qué se probó, con qué usuarios,
con qué archivos, y el resultado exacto de cada paso. Sin este registro, ninguna historia P1 de
esta spec se considera cerrada (US6 de `spec.md`).
