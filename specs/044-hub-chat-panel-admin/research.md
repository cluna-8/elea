# Phase 0 Research — 044-hub-chat-panel-admin

## R1 — Cómo el Hub deja de usar la sesión de admin para leer presupuesto

**Pregunta**: `client/server.js:280-291` lee presupuesto con `ELEA_SERVICE_USERNAME=admin`. El
contrato 2 de la 043 expone `GET /users/me/budget` con JWT propio. ¿Cómo se conecta?

**Decisión**: `fetchUserBudget(session.token)` deja de resolver `user_id` en memoria y pasa a
llamar `GET /users/me/budget` con el JWT de la sesión real del usuario (`session.token`, que ya
existe en el `Map` de sesiones — `client/server.js:47`). Se elimina el uso de
`ELEA_SERVICE_USERNAME`/`ELEA_SERVICE_PASSWORD` para este camino específico (queda solo donde de
verdad haga falta una sesión de servicio, si algo más lo necesita — a revisar en `tasks.md`).

**Rationale**: es exactamente el propósito del contrato 2; elimina una credencial de admin
innecesaria del camino caliente del badge de presupuesto, reduciendo superficie de fallo (si la
cuenta admin cambia de password, hoy rompe el badge de todo el mundo).

**Alternatives considered**: mantener la sesión de admin y solo agregar el filtro por
`acted_for_user_id` — descartado, sigue siendo una dependencia innecesaria de una cuenta
privilegiada para una operación que cada persona puede hacer sobre sí misma.

## R2 — Cómo el Hub genera y propaga `document_id`

**Pregunta**: contrato 3 pide que el cliente genere un id por subida y lo mande en todos los
chunks, con reuso en reintentos.

**Decisión**: en el handler de subida (`client/server.js`, cerca de `:527-566`), generar
`const documentId = crypto.randomUUID()` **antes** de trocear (`splitIntoChunks`), guardarlo en el
estado local de esa subida (variable de función, no persistido), y pasarlo en cada llamada de
`maskChunk(text, documentId)` → agregado al body de `/gw/inspect`. En un reintento disparado por el
propio cliente (mismo botón "reintentar" tras un fallo de red), reusar el mismo `documentId` si la
subida no llegó a completarse; generar uno nuevo si el usuario sube el archivo de cero otra vez.

**Rationale**: cumple FR-007 sin estado nuevo del lado del servidor — vive en el cierre de la
función que ya orquesta la subida completa.

**Alternatives considered**: derivar `document_id` de un hash del contenido — descartado, el
contrato 3 pide explícitamente que sea efímero y no derivado del contenido (evita que dos subidas
distintas del mismo archivo por error se traten como "el mismo documento" de forma sorpresiva para
el usuario, que sí puede querer eso o no según el caso — mejor que sea explícito por acción, no
implícito por contenido).

## R3 — Cómo el Hub verifica pertenencia sin duplicar lógica de autorización

**Pregunta**: el Hub debe dejar de auto-seleccionar `workspaces[0]` y de proxyar sin verificar. El
plan de la 043 dice que la autoridad vive en el backend (contrato 1). ¿Qué le queda al Hub?

**Decisión**: el Hub llama `GET /workspaces` (backend, contrato 1) en vez de `GET /api/v1/
workspaces` (AnythingLLM directo) para listar; el resultado ya viene filtrado por pertenencia. Para
cualquier operación sobre un `workspace_id` conocido (historial, hilos, subida, ajustes), el Hub
sigue llamando primero a `GET /workspaces/{id}` del backend (que devuelve 403 si no hay membresía)
**antes** de proxyar a AnythingLLM — un guard fino, no una reimplementación de la lógica de acceso.
Si el backend dice 403, el Hub nunca llega a tocar AnythingLLM.

**Rationale**: mantiene al Hub como "proxy fino" (Principio de diseño ya vigente en el código:
"cada endpoint hace una llamada HTTP real", comentario en `client/server.js:1-5`) — la
verificación es una llamada más, no una reimplementación del modelo de permisos.

**Alternatives considered**: cachear la pertenencia en la sesión del Hub tras el login y no
reconsultar en cada operación — descartado, abre una ventana donde una membresía revocada seguiría
permitiendo acceso hasta el próximo login (contradice FR-004 de la 043: verificación en el sistema
en cada operación, no una vez).

## R4 — Tooling de test a introducir (ninguno existe hoy)

**Pregunta**: `client/` y `frontend/` no tienen ningún test hoy. FR-030/031 de esta spec exigen
pruebas automáticas de contrato y de branding.

**Decisión**: `client/` → `node:test` (nativo desde Node 18, cero dependencia nueva) + `supertest`
(única dependencia de test agregada) para golpear los endpoints Express directamente. `frontend/`
→ Vitest + `@testing-library/react` (integra nativo con la config de Vite ya presente,
`devDependencies` ya tiene `@vitejs/plugin-react`).

**Rationale**: ambas elecciones son las de menor fricción para el stack ya elegido en cada
proyecto — no se introduce un framework de test ajeno al ecosistema de cada uno.

**Alternatives considered**: Playwright end-to-end para ambas UIs — más representativo del guion
de integración real (US6), pero más pesado como base de la suite de contrato; se deja como
candidato para el guion de integración de `quickstart.md` (que sí puede correr contra un stack
real), no para las pruebas de contrato unitarias que corren en CI en cada cambio.

## R5 — Cómo se marcan los documentos subidos antes de esta feature

**Pregunta**: FR-008 pide que el Hub indique "esquema anterior" sin fallar, sin que el motor
exponga esa información (el `document_id` es efímero, no se guarda metadata de "versión de
esquema" en el backend).

**Decisión**: el Hub compara la fecha de subida del documento (si AnythingLLM la expone en los
metadatos del documento, a confirmar en `tasks.md`) contra una fecha de corte configurable
(`MASKING_DETERMINISM_SINCE`, variable de entorno del propio Hub, seteada al desplegar esta
feature). Documentos con fecha anterior muestran el aviso; posteriores no.

**Rationale**: no requiere ningún cambio en el backend/motor (que no tiene ni debe tener el
concepto de "versión de esquema de placeholder" — sería un acoplamiento nuevo innecesario); es
enteramente resoluble con un dato que AnythingLLM ya guarda (fecha) y una constante de despliegue.

**Alternatives considered**: pedirle al backend un flag por documento — descartado, agrega estado
nuevo a la 043 para resolver un problema puramente de UX de aviso, evitable con la fecha de corte.
