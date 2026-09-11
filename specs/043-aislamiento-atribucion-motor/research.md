# Phase 0 Research — 043-aislamiento-atribucion-motor

Cinco decisiones de diseño, cada una con la pregunta que resuelve, la decisión, el razonamiento y
las alternativas descartadas. Todas parten del diagnóstico verificado en [diagnostico.md](./diagnostico.md).

## R1 — Dónde vive la autoridad de aislamiento (motor de documentos vs. backend Guardian)

**Pregunta**: Workspace/hilo↔usuario, ¿se modela en AnythingLLM (activando su multi-user mode) o
en el backend Guardian, propio?

**Decisión**: Backend Guardian. Nuevo par de tablas `workspaces` / `workspace_memberships` con
`tenant_id`, siguiendo el patrón ya usado por `budget.py`/`guardian.py`. El Hub Chat (spec 044)
consulta esta autoridad antes de cualquier operación contra AnythingLLM; AnythingLLM sigue en
single-user, hablado solo por la credencial de servicio existente.

**Rationale**:
- El objetivo Multi-Tenant by Design (Principio III) ya asume que toda entidad lleva `tenant_id`
  y se resuelve en el backend — Workspace/Membership encajan en ese patrón sin inventar uno nuevo.
- AnythingLLM corre `latest` sin pin (`elea-installer/docker-compose.yml:138`); su API admin de
  multiusuario varía entre versiones — construir la autoridad de aislamiento sobre una superficie
  no versionada es un riesgo operativo alto para un producto que se instala on-premise en varios
  clientes.
- El backend ya es la fuente de verdad de usuarios y tenants; duplicarla en un segundo sistema de
  identidad (usuarios de AnythingLLM) multiplica el trabajo de sincronización en cada alta/baja
  (US5 de esta spec) sin necesidad.
- Mantiene la credencial hacia AnythingLLM como un detalle de implementación interno del backend,
  nunca expuesto al cliente — reduce superficie de ataque frente a la Opción B evaluada en el
  diagnóstico original.

**Alternatives considered**:
- *Multi-user mode nativo de AnythingLLM* (Opción B del diagnóstico de aislamiento): descartada
  por el riesgo de versión y porque no elimina la necesidad de que el backend conozca la
  pertenencia (el 402 y la auditoría igual necesitan saberlo). Queda documentada como opción para
  otro cliente que ya use AnythingLLM multiusuario de forma nativa, no para este alcance.
- *Filtro por convención de nombres en el cliente* (Opción C): descartada explícitamente en el
  diagnóstico — no es un control real, la credencial global sigue permitiendo acceder a cualquier
  slug. No cumple FR-004 (verificación en el sistema, no solo en el cliente).

## R2 — Cómo un pedido de una llave de servicio afirma "en nombre de" un usuario

**Pregunta**: FR-010 exige que el sistema valide la identidad de usuario final en pedidos hechos
por llaves de servicio (`svc.rag-masking`, `svc.anythingllm-provider` o su reemplazo). ¿Cómo se
transporta y valida esa identidad sin aceptarla a ciegas del cuerpo del pedido?

**Decisión**: Cabecera dedicada (`X-Guardian-Acting-User`) que solo el backend Guardian añade
después de resolver la sesión real del usuario — nunca la construye el cliente Node directamente
desde datos de usuario sin verificar. Concretamente: el Hub Chat (spec 044) sigue autenticando a la
persona con su JWT contra el backend; cuando el backend delega a una llave de servicio (enmascarado,
o el nuevo camino RAG de R3), es el propio backend quien agrega la cabecera con el `user_id` ya
autenticado. `custom_auth.py` y `inspect.py` la aceptan **solo** si la llave que autentica tiene
`tool_type` marcado como capaz de actuar "en nombre de" (allowlist explícita, FR-014), y validan que
el `user_id` pertenezca al mismo `tenant_id` de la llave.

**Rationale**:
- Sigue el precedente ya sentado en `inspect.py:88-112` y `216-218`: nunca confiar en el `tool` (o
  cualquier campo) crudo del body del cliente para decisiones de identidad o auditoría.
- No requiere una llave por usuario (que multiplicaría asientos de licencia y gestión de llaves) ni
  cambia el modelo de Connection/APIKey del Principio IV — la llave de servicio sigue siendo una
  Connection con `tool_type` propio, solo gana el privilegio explícito de portar identidad ajena.
- Compatible con LiteLLM-Native (Principio VI): la cabecera se lee en el hook de auth existente
  (`custom_auth.py`), no se parchea el router.

**Alternatives considered**:
- *Confiar en un `user_id` en el body*: descartado — exactamente el patrón que `inspect.py` ya
  evita para `tool`; sería trivial de falsificar.
- *Virtual key por usuario final* (Opción B del diagnóstico de atribución): más "pura" pero
  multiplica llaves/asientos; queda como alternativa a reconsiderar si el cliente crece mucho más
  allá del piloto — no se descarta para siempre, se pospone.

## R3 — Cómo se atribuye el camino RAG (chat dentro de un espacio) al usuario final

**Pregunta**: hoy AnythingLLM llama al motor de IA con su propia provider key (`svc.anythingllm-
provider`), así que el gasto real del RAG nunca ve al usuario. ¿Cómo se resuelve sin tocar
AnythingLLM (fuera del alcance de este repo) ni acoplarse a su API admin (descartada en R1)?

**Decisión**: el backend Guardian expone un endpoint de "responder con contexto" que el Hub Chat
llama en vez de dejar que AnythingLLM hable directo con el motor de IA para la generación. El flujo
queda: Hub Chat → backend (identidad real del usuario, vía JWT) → backend pide a AnythingLLM
*solo la recuperación* (`/v1/workspace/{slug}/chat` en modo "query"/embeddings, sin generación) →
backend arma el prompt con el contexto recuperado y llama al motor de IA con la llave/identidad del
usuario. La atribución, el 402 y el desenmascarado ocurren en el mismo pedido, en el backend, donde
ya existen los tres mecanismos para el chat directo.

**Rationale**:
- Es la vía marcada como preferida en ambas specs (043 Assumptions, 044 Assumptions) porque no
  depende de la API admin de AnythingLLM (R1) y reutiliza el enforcement 402 y el desenmascarado
  que el chat directo ya tiene correctos (`client/server.js:635-638`, contraste con el camino RAG
  roto en `:616-632`).
- AnythingLLM sigue haciendo lo que hace bien (retrieval semántico, vector store) sin que el
  backend reimplemente esa pieza — no viola Principio VI en su equivalente para AnythingLLM (reuse
  over reinvent, Development Workflow #2).
- El impacto en `client/server.js` (dejar de llamar directo a AnythingLLM para el turno de chat) es
  real pero queda documentado como *contrato* hacia la spec 044, no como cambio de esta spec.

**Alternatives considered**:
- *Multi-user mode de AnythingLLM con su provider key por usuario*: descartada en R1 por el riesgo
  de versión sin pin.
- *Reconciliación de gasto agregado* (Opción C del diagnóstico de atribución, "aceptar el gasto
  agregado y reconciliarlo"): descartada como solución principal — no da 402 real (sigue siendo
  post-hoc sobre un agregado, no por usuario) y no resuelve el desenmascarado. Puede servir como
  mitigación temporal si R3 no llega a tiempo para el piloto, documentado como riesgo en
  Complexity Tracking si el plan de tareas lo necesita.

## R4 — Cómo se logra el determinismo del placeholder por documento sin romper la pureza del módulo

**Pregunta**: `PlaceholderMap` ya acepta un `nonce` opcional que nadie pasa. FR-020/021/022/023
piden que el mismo valor tenga el mismo placeholder dentro de un documento, sin I/O nuevo en el
camino caliente y sin cambiar la gramática `[TIPO_n_hex]`.

**Decisión**: el cliente que enmascara (Hub Chat, vía contrato 3) genera un `document_id` aleatorio
por subida (UUID, efímero, no derivado del contenido) y lo manda en cada llamada de chunk a
`/gw/inspect`. `inspect.py` lo recibe como campo opcional del body, lo pasa a
`gateway.evaluate_request_policy`, que construye `PlaceholderMap(nonce=document_id[:4])` — el mismo
nonce para todos los chunks del mismo documento. La memoización de `orig_to_ph` ya es por request
(por `PlaceholderMap`), así que el reset **no** es necesario entre chunks: cada chunk sigue creando
su propia instancia (no hay estado compartido en memoria del proceso, que sería frágil bajo
concurrencia — ver Edge Case de subidas concurrentes), pero todas las instancias del mismo documento
comparten nonce, con lo cual dos apariciones del mismo valor en chunks distintos producen el mismo
token **si además el índice por tipo coincide**. Como el índice sí puede diferir entre chunks (cada
`PlaceholderMap` reinicia sus contadores), la implementación real deriva el índice también del
nonce+valor mediante un HMAC corto **acotado al documento** (no al valor solo): `idx = int(hmac(
document_id, tipo + valor_normalizado), 16) % 10_000`, evitando así I/O y garantizando el mismo
placeholder para el mismo valor en cualquier chunk del mismo documento, sin memoria compartida entre
requests. Sin `document_id`, el comportamiento es exactamente el actual (nonce aleatorio, sin
regresión — FR-021).

**Rationale**:
- No agrega I/O: el HMAC es cómputo puro, cumple la restricción declarada en
  `sentinel_guardian_policy.py` ("PURA = sin DB, sin servicios, sin I/O").
- No cambia la gramática del placeholder (`_type_hex` en base al `document_id`, no al índice de
  aparición) — la Opción A del diagnóstico de enmascarado, adoptada tal cual salvo el detalle de
  que el índice también deriva del documento en vez de ser un contador secuencial (necesario porque
  distintos chunks no comparten contador en memoria).
- El scope es exactamente "por documento" (decisión sellada 08-sep): dos documentos con el mismo
  valor obtienen HMACs distintos porque `document_id` es distinto y aleatorio por subida — no se
  crea un seudónimo estable entre documentos, no toca Constitución I.
- Compatible con la bóveda de la spec 042 sin cambios: la clave sigue siendo el placeholder
  completo; con determinismo, una subida con reintento reusa el mismo `document_id` → mismos
  placeholders → mismas claves de bóveda (idempotente, refuerza el TTL en vez de crear basura).

**Alternatives considered**:
- *Contador compartido en Redis por documento* (parte de la Opción C del informe de enmascarado):
  descartada — introduce I/O en el camino caliente, contradice la pureza declarada del módulo, y
  agrega latencia a un proceso que ya tarda ~12s en documentos grandes.
- *Determinismo por workspace o tenant*: descartado por decisión explícita del dueño del producto
  (08-sep) — es un cambio constitucional de facto (crea un seudónimo estable, habilita
  correlación entre documentos) y debe escalarse aparte, como se hizo con la bóveda en la 042, no
  incluirse como continuación técnica de este bug.

## R5 — Cómo se separa `model` de `surface` en auditoría sin romper lecturas existentes

**Pregunta**: `audit_logs.model` mezcla modelos reales, superficies (`chat-ui`) y evidencia
(`license`). FR-032 pide separarlas; ¿migración destructiva o aditiva?

**Decisión**: migración aditiva. Se agregan dos columnas nuevas a `audit_logs`: `surface`
(nullable, valores del enum ya existente `SURFACES` de `sentinel_governance.py`) y `event_type`
(nullable, `traffic` | `license_evidence` | default `traffic`). Backfill de una sola pasada:
filas con `model IN ('license',)` → `event_type='license_evidence'`; filas con `model IN (valores
de SURFACES)` → `surface=model` y `model=NULL`. `gateway._audit()` deja de recibir la superficie en
el parámetro `model`; a partir de ahora recibe `model` (real o `NULL` para eventos que no son de
IA) y `surface` por separado. Las vistas de costos (`costs.py`, `analytics.py`) filtran por
`event_type='traffic' AND model IS NOT NULL` para "modelos"; `AuditLog.model` sigue siendo
`nullable=False` hoy (`audit.py:20`) — el plan de tareas debe decidir si se relaja a `nullable=True`
o si las filas de superficie siguen llevando un valor sentinel explícito (`model='__surface__'`)
para no romper el `NOT NULL` sin una migración de esquema mayor. Se deja como decisión de
`tasks.md`, con ambas vías compatibles con este research.

**Rationale**:
- Aditiva y con backfill preserva el histórico (no se pierde ninguna fila, cumple SC de continuidad
  usada en la 042) y no rompe queries existentes que ya filtran por `model != 'license'`
  (compliance.py, reports.py) — esas siguen funcionando idénticas, solo dejan de ser necesarias.
- Separar `event_type` da un lugar limpio para "license_evidence" sin necesitar tocar
  `licensing/audit_events.py` más que en la relectura (sigue escribiendo `model='license'` por
  compatibilidad hacia atrás durante la migración, o se actualiza junto con el backfill — decisión
  de tasks.md).

**Alternatives considered**:
- *Filtrar en las dos queries de costos sin migración* (Opción 1 del informe de cuentas de
  servicio): más rápido pero dijo el propio informe que es frágil (lista a mantener); no resuelve
  FR-013 (auditar el enmascarado como una operación por documento, que si sigue en `model` no
  tiene dónde vivir limpiamente). Se descarta como solución final, válida solo como hotfix si el
  plan de tareas necesita algo desplegable en el día 1 mientras la migración se prueba.
