# Feature Specification: LiteLLM-Native Firewall (base_url clients)

**Feature Branch**: `014-litellm-native-firewall`

**Created**: 2026-07-10

**Status**: Implementada — estado canónico en [`ROADMAP-guardian.md`](../ROADMAP-guardian.md)

**Input**: User description: "Portar el firewall del demo (hoy hand-rolled en `gatelite backend/src/api/gateway.py`) a extensiones NATIVAS de LiteLLM (CustomGuardrail pre/post/streaming, custom_auth para identidad, CustomLogger para audit, `/v1/messages` nativo), con la excepción propia del passthrough OAuth de suscripción en el backend. Router GDPR = N/A (excepción acotada del Principio II). Incluir el monitor en vivo para demos. Depende de la spec 013."

---

## Contexto y honestidad SDD *(léelo antes que nada)*

Esta feature es un **PORT**, no una feature verde. Hoy existe, y funciona en demo, un firewall
**hand-rolled** en `gatelite-salud-eu/backend/src/api/gateway.py`: un reverse-proxy sobre
`/gw/v1/messages` que habla la Anthropic Messages API, detecta la herramienta por User-Agent
(`_detect_tool`), redacta el cuerpo con placeholders reversibles (`_redact_body`), reescribe eventos
SSE crudos para des-enmascarar (`_rewrite_sse_event`), soporta dos modos (los `upstream_mode` de la 013:
`byok` y `subscription-passthrough` — este último era "anthropic" en el demo) y resuelve
identidad por `X-Basa-Key` (`_resolve_identity`). Ese archivo reimplementa a mano cosas que el motor
LiteLLM **ya hace**: framing SSE, decodificación UTF-8 incremental, parsing de `input_tokens`/
`output_tokens`, reintentos/fallbacks/rpm-tpm/cost-ceiling.

El objetivo de la 014 es mover esa política a los **puntos de extensión documentados de LiteLLM**
(Principio VI, LiteLLM-Native, No Patching) para dejar de mantener motor propio. Esta spec es
**explícita** sobre qué se **REUSA del motor** y qué sigue siendo **código PROPIO de Basa**:

- **REUSA del motor (deja de ser código nuestro):** el endpoint `/v1/messages` nativo con guardrails
  ON; el framing SSE + decodificación UTF-8 incremental + parsing de usage/tokens; reintentos,
  fallbacks, rpm/tpm y cost-ceiling (ya en `router_settings`).
- **SIGUE siendo PROPIO (política Basa):** los cuatro puntos de extensión — `BasaGuardrail`
  (CustomGuardrail), `custom_auth` (identidad), `BasaAuditLogger` (CustomLogger), y una **única**
  excepción de proxy propio: el passthrough OAuth de **suscripción** en el backend. Más una **librería
  pura compartida** (`basa_guardian_policy`) que ambas rutas (motor y passthrough) importan para no
  divergir.

**Alcance honesto:** esta spec cubre el port del firewall y sus contract tests. NO activa Presidio
NLP real (eso es la 016), NO reescribe SecurityPolicy scoped (015), NO cierra el fallback admin de
todo el sistema (017) — aunque SÍ exige fail-closed en la identidad de esta ruta (Constraint C3, ver más abajo).
Depende del **bedrock 013** (Tenant, `role="client"`, `client_type`, y la Connection = APIKey extendida
con `tenant_id`/`tool_type`/`upstream_mode`).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - El firewall corre como guardrail nativo sobre `/v1/messages` (Priority: P1)

Un desarrollador apunta `ANTHROPIC_BASE_URL` de su coding tool (Claude Code, Cursor…) en modo **BYOK**
al motor Basa. El motor recibe la request en su endpoint `/v1/messages` **nativo** (no en un
`/gw/v1/messages` hand-rolled) y ejecuta `BasaGuardrail.async_pre_call_hook`: bloquea prácticas
prohibidas del EU AI Act Art.5 (→ 400), bloquea secretos/keys, y enmascara PII con placeholders
reversibles antes de que el prompt salga al LLM. La respuesta pasa por
`async_post_call_success_hook` (no-streaming) o `async_post_call_streaming_iterator_hook` (streaming)
que des-enmascara, de modo que el LLM sólo vio placeholders pero el usuario recibe los valores reales.

**Why this priority**: Es el titular de la spec y de las demos (ROADMAP: "el firewall que da las
demos"). Sin esto no hay port: es la prueba de que la política Basa corre como extensión del motor y no
como proxy paralelo. Materializa el Principio VI (reuso del motor) y el Principio I (masking-first
reversible).

**⚠️ Premisa condicionada (correr T005 ANTES de codear)**: Este story asume que LiteLLM ejecuta los tres
hooks del guardrail y **normaliza el stream** (`ModelResponseStream` parseado) sobre el endpoint
`/v1/messages` **nativo**. Esa premisa NO está verificada: el Phase-0 research (T005, inspección del
**código** de la imagen pinneada) DEBE correr antes de implementar cualquier tarea de US1. Si el research
invalida la premisa, la **Estrategia A** (unmask sobre objetos parseados) queda descartada y se activa la
**Estrategia B** (rewrite de bytes SSE) como excepción acotada documentada (ver plan.md y FR-007). No se
escribe código de US1 hasta cerrar T005.

**Independent Test**: **Precondición: T005 (Phase-0 research) cerrado y confirmando la Estrategia
aplicable.** Levantar el contenedor LiteLLM con `guardrails:` configurado, enviar a
`/v1/messages` un prompt BYOK con PII y una práctica prohibida por separado, y verificar: (a) el prompt
con práctica prohibida devuelve 400 sin llegar al LLM; (b) el prompt con PII sale enmascarado al
upstream (placeholders) y vuelve des-enmascarado al caller. Todo sin tocar `/chat/completions`.

**Acceptance Scenarios**:

1. **Given** el contenedor LiteLLM con `BasaGuardrail` registrado en `guardrails:` (modes
   `pre_call`, `post_call`, `post_call_streaming`), **When** llega a `/v1/messages` una request BYOK
   cuyo texto describe una práctica del EU AI Act Art.5, **Then** `async_pre_call_hook` la bloquea con
   HTTP 400 y el LLM nunca recibe el prompt.
2. **Given** la misma configuración, **When** llega una request BYOK con un email y un nombre en el
   turno de usuario, **Then** el prompt que sale al LLM contiene sólo placeholders atómicos
   (`[EMAIL_ADDRESS_0_ab12]`, `[PERSON_1_ab12]`), el mapa reversible vive en
   `data["metadata"]["pii_tokens"]`, y la respuesta no-streaming devuelta al caller tiene los valores
   reales restaurados por `async_post_call_success_hook`.
3. **Given** una request BYOK con `stream: true` y PII, **When** el LLM responde en SSE,
   **Then** `async_post_call_streaming_iterator_hook` des-enmascara sobre los objetos
   `ModelResponseStream` ya parseados (no bytes SSE crudos) y el caller nunca ve un placeholder crudo.
4. **Given** un prompt que contiene una API key / secreto, **When** entra por `pre_call`, **Then** se
   bloquea (delegando en `GuardianService`) antes de salir al LLM.

---

### User Story 2 - Identidad por User-Agent + virtual key (custom_auth, fail-closed) (Priority: P1)

Cada request al motor se autentica con `custom_auth.user_api_key_auth(request, api_key)`: se detecta el
`tool_type` desde el User-Agent (porta `_detect_tool`/`_TOOL_UA`), la virtual key se resuelve contra la
tabla `APIKey` de Basa (porta `_resolve_identity`) para atribuir tenant/client/team, y esa metadata se
inyecta para que los hooks y el logger la usen. Si no hay virtual key válida, la request se **rechaza**
(fail-closed): NO cae al usuario admin por defecto.

**Why this priority**: Sin identidad no hay atribución de auditoría ni gobernanza por tenant, y el
agujero heredado (caer a `get_or_create_default_user`) viola Constraint C3. Es P1 porque los hooks de US1
necesitan la metadata de identidad que este story produce, y porque el fail-closed es una constraint de
seguridad dura del proyecto.

**Independent Test**: Registrar `custom_auth` en `general_settings.custom_auth`, enviar una request con
User-Agent de Claude Code y una virtual key válida → verificar que `tool_type="claude-code"` y el
tenant/client/team correctos aparecen en la metadata; enviar una request sin key válida → verificar
rechazo (401/403), NO admin por defecto.

**Acceptance Scenarios**:

1. **Given** `custom_auth` registrado, **When** llega una request con User-Agent que contiene "claude",
   **Then** la identidad resuelta tiene `tool_type="claude-code"`.
2. **Given** una virtual key que mapea a un `APIKey` activo con `role="client"`, **When** entra la
   request, **Then** `user_api_key_auth` devuelve un `UserAPIKeyAuth` con la metadata
   `{tenant_id, client_id, tool_type}` correcta resuelta contra la tabla `APIKey` de Basa (013).
3. **Given** una request sin virtual key válida en `upstream_mode` = `byok` (013), **When** entra al
   motor, **Then** se rechaza (fail-closed), y NO se cae a `get_or_create_default_user` ni a admin. (El
   ramaje de `custom_auth` sobre `upstream_mode`: `byok` → fail-closed duro; `subscription-passthrough` →
   ruta OAuth del backend, ver US4 y [D-014].)
4. **Given** un User-Agent no reconocido, **When** entra la request, **Then** el `tool_type` es
   `unknown`/desconocido pero la request no crashea (degradación honesta; ver Edge Cases).

---

### User Story 3 - Auditoría metadata-only vía CustomLogger + monitor en vivo (Priority: P2)

Cada transacción exitosa dispara `BasaAuditLogger.async_log_success_event`, que persiste **sólo
metadata** (modelo, tokens, verdicto de compliance, tipos de entidad, timing, propósito) reusando
`AuditService.log_transaction`, y que **hace scrub de `metadata.pii_tokens`** antes de persistir para
no filtrar el mapa reversible. El mismo logger alimenta un **feed en memoria** que el monitor en vivo
(`/monitor`, la vitrina para demos) consume para mostrar el before/after real por capa.

**Why this priority**: La auditoría metadata-only es un compromiso de compliance (Constraint C1) y el monitor es
la vitrina que vende las demos (Principio VIII, Pipeline Transparency). Es P2 porque el firewall (US1) +
identidad (US2) ya entregan valor sin él, pero sin auditoría no hay accountability GDPR y sin monitor no
hay demo vendible.

**Independent Test**: Registrar `BasaAuditLogger` en `litellm_settings.callbacks`, correr una request
con PII, y verificar en la DB que el `AuditLog` guarda verdicto/tipos/timing pero **cero** texto de
prompt y **cero** `pii_tokens`; abrir `/monitor` y verificar que el feed muestra el before/after real.

**Acceptance Scenarios**:

1. **Given** `BasaAuditLogger` en `litellm_settings.callbacks`, **When** una request con PII se completa,
   **Then** el `AuditLog` persistido contiene `pii_detected=true`, tipos de entidad, tokens, latencia y
   verdicto, pero **no** el texto del prompt ni el mapa `pii_tokens`.
2. **Given** el logger corriendo, **When** `metadata.pii_tokens` está poblado, **Then** el logger lo
   **scrubbea** antes de llamar a `AuditService.log_transaction` (verificable: ningún placeholder ni
   valor original llega a la fila de auditoría).
3. **Given** el monitor abierto en `/monitor`, **When** llegan requests, **Then** el feed en vivo
   muestra el original → enviado-al-modelo (before/after) con los pares de entidades, alimentado por el
   ring en memoria del logger, y la animación es cosmética sobre datos reales.

---

### User Story 4 - Excepción: passthrough OAuth de suscripción en el backend (Priority: P2)

Un desarrollador con **suscripción** Claude Pro/Max (OAuth, sin API key) apunta su coding tool a Basa en
modo `subscription-passthrough` (`upstream_mode` de la 013; era "anthropic" en el demo). Como LiteLLM
**reclama el header `Authorization` como su propia virtual
key**, el token OAuth del cliente **no puede atravesar el motor**. Para esta ruta —y sólo esta— el
backend mantiene un **thin reverse-proxy** a `api.anthropic.com` que reenvía el OAuth **verbatim**, pero
invoca la **misma** librería pura `basa_guardian_policy` (bloqueo + masking/unmask) para no reimplementar
la política ni violar el Principio VI. En esta ruta el **GDPR-routing es N/A** (excepción acotada del
Principio II — base_url clients).

**Why this priority**: Es la "firewall on top of your subscription story" que hace las demos memorables,
pero técnicamente es la **única excepción de proxy propio** permitida por la constitución (Principio VI),
así que debe existir con disciplina: importar la política compartida, no duplicarla. P2 porque el modo
BYOK (US1) ya demuestra el port nativo; la suscripción es el caso que el motor no soporta.

**Independent Test**: Enviar al passthrough del backend una request con OAuth (header `Authorization`
verbatim) + PII + una práctica prohibida: verificar que el OAuth llega intacto a `api.anthropic.com`
(la suscripción paga), que la práctica prohibida se bloquea con el **mismo** resultado que la ruta motor,
y que el masking/unmask produce **idéntico** output que `BasaGuardrail` (misma `basa_guardian_policy`).

**Acceptance Scenarios**:

1. **Given** el passthrough OAuth del backend, **When** llega una request `upstream_mode` =
   `subscription-passthrough` con `Authorization` OAuth y sin API key, **Then** el backend reenvía el header verbatim a
   `api.anthropic.com` (la suscripción del cliente paga) y NO usa la auth del motor.
2. **Given** un prompt con práctica prohibida por esa ruta, **When** entra al passthrough, **Then** se
   bloquea invocando `basa_guardian_policy` con el **mismo** verdicto que produciría `BasaGuardrail` en
   la ruta motor.
3. **Given** un prompt con PII en modo suscripción con redacción activa, **When** se procesa, **Then**
   el masking/unmask (incluido streaming con placeholder partido) usa la **misma** librería
   `basa_guardian_policy` y round-trippea igual que la ruta BYOK.
4. **Given** esta ruta base_url, **When** se resuelve compliance, **Then** el GDPR-routing es N/A (no se
   fuerza endpoint EU) y la garantía se traslada a masking/audit/allowlist (excepción documentada del
   Principio II).

---

### User Story 5 - Pin de versión del motor + contract tests de firmas (Priority: P3)

El equipo fija (pin) la imagen del contenedor LiteLLM a una versión/digest concreto y cubre con **tests
de contrato** las firmas de los tres hooks del guardrail y de `user_api_key_auth`. Actualizar el motor
implica bumpear el pin y correr los contract tests: si el motor cambió una firma o dejó de ejecutar un
hook sobre `/v1/messages`, el build **falla** en vez de degradar en silencio.

**Why this priority**: Es la disciplina que hace sostenible el Principio VI (No Patching). P3 porque el
firewall funciona antes de pinnear, pero sin pin+contract-tests el port es frágil ante upgrades del
motor (la doc de LiteLLM va por detrás del código).

**Independent Test**: Con la imagen pinneada, correr los contract tests: (a) verifican que las firmas de
`async_pre_call_hook`/`async_post_call_success_hook`/`async_post_call_streaming_iterator_hook`/
`user_api_key_auth` coinciden con las de la versión pinneada; (b) verifican que los hooks realmente
corren sobre `/v1/messages` (no sólo `/chat/completions`). Cambiar el pin a una versión incompatible
hace fallar la suite.

**Acceptance Scenarios**:

1. **Given** la imagen LiteLLM pinneada por tag+digest en docker-compose, **When** corren los contract
   tests, **Then** verifican las firmas de los tres hooks y de `user_api_key_auth` contra esa versión.
2. **Given** los contract tests, **When** el motor no ejecuta `async_pre_call_hook` sobre la ruta
   `/v1/messages` (sólo sobre `/chat/completions`), **Then** el test **falla** (protege el riesgo de que
   el masking no corra en la ruta titular).
3. **Given** un bump de versión del motor que rompe una firma, **When** corre la suite, **Then** el build
   falla antes de desplegar.

---

### Edge Cases

- **Placeholder partido entre dos chunks de streaming (carry-split)**: un placeholder atómico
  (`[PERSON_0_ab12]`) puede quedar dividido entre dos `ModelResponseStream`. El guardrail debe retener
  el fragmento final sólo si aún podría crecer hasta un placeholder (porta la lógica de `_safe_split`/
  `_PH_TAIL_RE`), y nunca entregar un placeholder crudo ni perder texto. Un `[` suelto de código/prosa
  (`arr[i`, `nums[0`, markdown) NO se retiene (no bloquea el stream).
- **Colisión de placeholder con literal del usuario**: el usuario podría escribir literalmente
  `[PERSON_0]`. El nonce por request (`uuid4().hex[:4]`, porta el nonce de `_redact_body`) evita que un
  placeholder generado colisione con un literal tipeado o que el modelo lo reproduzca por azar.
- **Herramienta no detectada (User-Agent desconocido)**: `tool_type` cae a `unknown`/desconocido, la
  request NO crashea y se audita con esa etiqueta. Herramientas con red hostil / cert-pinning (que no
  aceptan base_url) se documentan como **no compatibles** (Principio IV), fuera de scope.
- **Round-trip de deltas Anthropic (text/thinking/tool_use input_json)**: tras la normalización del
  motor, el unmask debe funcionar sobre text, thinking y los args JSON de tool_use sin dejar
  placeholders crudos ni corromper tool-calls. (Los 12 bugs del demo se portan como contract tests en la
  016; aquí se cubre el happy-path del round-trip.)
- **`pii_tokens` filtrado**: si cualquier callback (incluido el propio logger) persiste o loguea
  `metadata.pii_tokens`, se viola Constraint C1. El logger DEBE scrubbearlo explícitamente; hay un test negativo.
- **Deriva entre los dos call-sites (motor BYOK vs backend suscripción)**: si el passthrough reimplementa
  la política en vez de importar `basa_guardian_policy`, los verdictos/masking pueden divergir. Un
  contract test ejerce ambas rutas con el mismo input y exige el mismo resultado.
- **Guardrails no corren sobre `/v1/messages` nativo**: riesgo de madurez del motor; si el hook sólo se
  ejecuta en `/chat/completions`, el masking no correría en la ruta titular. Contract test de US5 lo
  detecta.
- **Stream truncado a mitad**: si el upstream corta el stream con un `carry` retenido, el guardrail debe
  flushear ese carry des-enmascarado al final (porta el flush de `gen_redacted`), sin perder texto.
- **Modo suscripción sin `X-Basa-Key`**: en la ruta OAuth (`subscription-passthrough`), la credencial es
  el OAuth; `X-Basa-Key` es atribución **opcional**. La resolución de identidad
  (tenant-anónimo-pero-autenticado-por-suscripción, auditado como `tenant-default`) se fija en el default
  documentado **[D-014]** (Assumptions), revisable.

## Requirements *(mandatory)*

### Functional Requirements

**Firewall nativo (US1)**
- **FR-001**: El sistema MUST exponer la política Basa como un `CustomGuardrail` (`BasaGuardrail`)
  registrado en el bloque `guardrails:` de `config.yaml` con modes `pre_call`, `post_call` y
  `post_call_streaming`, sin parchear el motor (Principio VI).
- **FR-002**: `BasaGuardrail.async_pre_call_hook` MUST bloquear con HTTP 400 los prompts que describen
  prácticas prohibidas del EU AI Act Art.5, delegando en `ComplianceService.evaluate_prompt`
  (enforcement duro, Principio II).
- **FR-003**: `async_pre_call_hook` MUST bloquear prompts con secretos/API keys detectados, delegando en
  `GuardianService.process_prompt`.
- **FR-004**: `async_pre_call_hook` MUST enmascarar PII con placeholders atómicos reversibles antes de
  que el prompt salga al LLM, delegando la detección/masking en `PresidioService`, de modo que el motor
  y el LLM sólo vean placeholders (Principio I).
- **FR-005**: El sistema MUST almacenar el mapa reversible placeholder→original en
  `data["metadata"]["pii_tokens"]`, leído por `async_post_call_success_hook` y
  `async_post_call_streaming_iterator_hook`.
- **FR-006**: `async_post_call_success_hook` MUST des-enmascarar la respuesta no-streaming, restaurando
  los valores reales para el caller.
- **FR-007**: `async_post_call_streaming_iterator_hook` MUST des-enmascarar sobre objetos
  `ModelResponseStream` ya parseados (**Estrategia A, preferida**; NO bytes SSE crudos), portando
  únicamente la lógica de carry de placeholders partidos entre chunks; por defecto el sistema MUST NOT
  reimplementar framing SSE, decodificación UTF-8 incremental ni parsing de usage (los cubre el motor).
  **Excepción acotada**: si el Phase-0 research (T005) demuestra que el motor NO ejecuta el hook parseado
  sobre `/v1/messages` nativo (o normaliza los deltas de forma que rompe el round-trip de tool_use),
  entonces la **Estrategia B** (rewrite de bytes SSE, portando `_rewrite_sse_event` + decoder UTF-8)
  queda **habilitada como excepción acotada y documentada** en el research; en ese caso FR-007 se lee
  como "des-enmascarar en streaming reusando el máximo del motor que la ruta `/v1/messages` permita". La
  Estrategia B nunca se activa sin evidencia de T005 (ver plan.md → "Dos estrategias para el unmask").
- **FR-008**: El sistema MUST NOT entregar nunca un placeholder crudo al caller ni perder texto, incluso
  con placeholder partido entre chunks o stream truncado.

**Identidad (US2)**
- **FR-009**: El sistema MUST registrar `custom_auth.user_api_key_auth` en
  `general_settings.custom_auth` para resolver identidad por request.
- **FR-010**: `user_api_key_auth` MUST derivar el `tool_type` desde el User-Agent (portando el mapeo de
  `_detect_tool`/`_TOOL_UA`).
- **FR-011**: `user_api_key_auth` MUST resolver la virtual key contra la tabla `APIKey` de Basa
  (portando `_resolve_identity`) para atribuir `tenant_id`/`client_id`/`team`, e inyectar esa metadata
  para hooks y logger.
- **FR-012**: `user_api_key_auth` MUST ser **fail-closed** en la ruta BYOK: sin virtual key válida, la
  request se rechaza y NO cae a `get_or_create_default_user` ni a un usuario admin por defecto (Constraint C3).
- **FR-013**: El sistema MUST degradar sin crashear cuando el User-Agent no coincide con ninguna
  herramienta conocida (`tool_type` = desconocido).

**Auditoría + monitor (US3)**
- **FR-014**: El sistema MUST registrar `BasaAuditLogger` (`CustomLogger`) en
  `litellm_settings.callbacks`, cuyo `async_log_success_event` persiste auditoría **metadata-only**
  reusando `AuditService.log_transaction`.
- **FR-015**: `BasaAuditLogger` MUST hacer **scrub** de `metadata.pii_tokens` (y de cualquier texto de
  prompt/PII cruda) antes de persistir; MUST NOT escribir texto de prompt ni el mapa reversible
  (Constraint C1).
- **FR-016**: El sistema MUST alimentar un feed en memoria (ring acotado) desde el logger para el
  monitor en vivo, mostrando el before/after real por capa; la animación MUST ser cosmética y los datos
  reales (Principio VIII).
- **FR-017**: El monitor MUST exponerse como una vista autocontenida para demos (equivalente a
  `/monitor` del demo) sin persistir texto de prompt ni PII cruda.

**Excepción suscripción (US4)**
- **FR-018**: El sistema MUST mantener en el backend un thin reverse-proxy que, en `upstream_mode` =
  `subscription-passthrough` (013; era "anthropic" en el demo), reenvía el header `Authorization`/OAuth
  **verbatim** a `api.anthropic.com` sin usar la auth del motor (única excepción del Principio VI).
- **FR-019**: El passthrough OAuth MUST invocar la librería pura compartida `basa_guardian_policy` para
  bloqueo y masking/unmask, produciendo el **mismo** resultado que `BasaGuardrail`; MUST NOT
  reimplementar la política.
- **FR-020**: En la ruta base_url, el sistema MUST tratar el GDPR-routing como **N/A** (no forzar
  endpoint EU), trasladando la garantía a masking/audit/allowlist (excepción acotada del Principio II).
- **FR-021**: El modo BYOK MUST migrar a LiteLLM nativo (auth+cost+guardrails del motor); sólo la ruta
  suscripción sobrevive como proxy propio en el backend.

**Librería compartida + config (transversal)**
- **FR-022**: El sistema MUST proveer una librería pura `basa_guardian_policy` (mask_reversible / unmask
  / detect_ai_act / detect_secrets / carry-split de placeholders) importada tanto por `BasaGuardrail`
  como por el passthrough OAuth, para no divergir (DRY, Principio VI).
- **FR-023**: `config.yaml` MUST conservar `model_list` y `router_settings.fallbacks` existentes y
  añadir los bloques `guardrails:`, `litellm_settings.callbacks:` y `general_settings.custom_auth:`.
- **FR-024**: El paquete de extensiones (guardrail, custom_auth, logger, librería pura) MUST montarse en
  la imagen/volumen del contenedor LiteLLM (mismo patrón que `./litellm/config.yaml:/app/config.yaml`).
- **FR-025**: Las credenciales MUST vivir fuera de `config.yaml` en claro (env vars / gestor de
  secretos), incluida la referencia al secreto OAuth de suscripción (Constraint C5).

**Pin + contract tests (US5)**
- **FR-026**: La imagen del contenedor LiteLLM MUST estar pinneada por tag+digest en docker-compose (no
  `main-latest`).
- **FR-027**: El sistema MUST cubrir con contract tests las firmas de `async_pre_call_hook`,
  `async_post_call_success_hook`, `async_post_call_streaming_iterator_hook` y `user_api_key_auth` contra
  la versión pinneada; el build MUST fallar si una firma cambia.
- **FR-028**: Un contract test MUST verificar que los guardrails se ejecutan sobre `/v1/messages`
  nativo (no sólo `/chat/completions`).
- **FR-029**: Un contract test MUST ejercer ambas rutas (motor BYOK y passthrough suscripción) con el
  mismo input y exigir el mismo verdicto/masking (protege contra deriva).

**Retiro del código propio (migración)**
- **FR-030**: El sistema MUST retirar de `gatelite gateway.py` el endpoint `/gw/v1/messages`, los
  passthrough `count_tokens`/`models`, `_rewrite_sse_event`, `_redact_body`, `_detect_tool`,
  `_resolve_identity`, `_passthrough_headers` y el parsing `_IN_RE`/`_OUT_RE`, conservando **sólo** el
  passthrough OAuth de suscripción reescrito sobre `basa_guardian_policy`.

### Key Entities *(include if feature involves data)*

- **BasaGuardrail (CustomGuardrail)** — *código PROPIO*. Wrapper de los tres hooks nativos
  (`async_pre_call_hook`, `async_post_call_success_hook`,
  `async_post_call_streaming_iterator_hook`) + estado reversible en `data["metadata"]["pii_tokens"]`.
  REUSA `ComplianceService`/`GuardianService`/`PresidioService`. Reemplaza `_redact_body` y
  `_rewrite_sse_event`.
- **basa_guardian_policy (librería pura compartida)** — *código PROPIO*. Funciones puras: mask
  reversible, unmask (texto y objetos), detect AI-Act, detect secrets, carry-split de placeholders
  (porta `_safe_split`/`_PH_TYPE_RE`/`_PH_TAIL_RE`). Importada por `BasaGuardrail` (ruta motor) y por el
  passthrough OAuth (ruta suscripción) para honrar VI.
- **custom_auth.user_api_key_auth** — *código PROPIO (resolución Basa) sobre pipeline del motor*.
  Identidad: User-Agent→`tool_type`, virtual key→tenant/client/team vía tabla `APIKey`. Fail-closed.
  Devuelve `UserAPIKeyAuth` del motor.
- **BasaAuditLogger (CustomLogger)** — *código PROPIO (wrapper)*. `async_log_success_event`
  metadata-only, con scrub de `pii_tokens`. REUSA `AuditService.log_transaction`. Alimenta el monitor.
- **/v1/messages (endpoint nativo)** — *REUSA motor 100%*. Anthropic Messages API nativo con guardrails
  ON. Reemplaza `/gw/v1/messages` + `count_tokens` + `models`.
- **Backend subscription OAuth passthrough** — *código PROPIO, única excepción VI*. Thin reverse-proxy
  a `api.anthropic.com` que reenvía OAuth verbatim e invoca `basa_guardian_policy`. GDPR-routing N/A.
- **APIKey (= Connection, modelo DB de la 013)** — *REUSA*. Usa `tenant_id`/`client_id`/`tool_type`/
  `upstream_mode` para el mapeo de identidad en `custom_auth`. `key_hash` sin cambios. Depende del
  bedrock 013.
- **AuditLog (modelo DB)** — *REUSA sin cambios*. Metadata-only (tipos, scores, timing, verdicto,
  propósito). Nunca texto ni `pii_tokens`.
- **config.yaml** — *modificado*. + `guardrails:`, + `litellm_settings.callbacks:`,
  + `general_settings.custom_auth:`. Conserva `model_list`/`router_settings.fallbacks`.
- **docker-compose litellm image** — *modificado*. Tag+digest pinneado en vez de `main-latest`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001 (No Raw PII/PHI Storage)**: En 100% de las requests auditadas, el `AuditLog` persiste sólo
  metadata (tipos, scores, timing, verdicto, propósito) y **cero** texto de prompt y **cero** entradas
  de `pii_tokens`. Test negativo verifica el scrub.
- **SC-002 (masking en la ruta titular)**: El masking/unmask corre sobre `/v1/messages` nativo (no sólo
  `/chat/completions`), verificado enviando un prompt con PII y comprobando que el upstream sólo recibe
  placeholders y el caller recibe los valores reales.
- **SC-003 (fail-closed)**: 100% de las requests BYOK sin virtual key válida se rechazan; 0% cae a un
  usuario admin por defecto.
- **SC-004 (reversibilidad en streaming)**: 0 placeholders crudos entregados al caller y 0 texto perdido
  en escenarios de placeholder partido entre chunks y de stream truncado (round-trip de
  text/thinking/tool_use).
- **SC-005 (paridad de rutas)**: Para un mismo input, la ruta motor BYOK y el passthrough OAuth de
  suscripción producen **idéntico** verdicto de bloqueo y **idéntico** masking/unmask (misma
  `basa_guardian_policy`).
- **SC-006 (pin + contract tests como puerta)**: La imagen LiteLLM está pinneada por tag+digest y los
  contract tests de las 4 firmas + la ejecución sobre `/v1/messages` corren en el build; un bump
  incompatible del motor hace fallar el build.
- **SC-007 (credenciales fuera de config)**: 0 credenciales (incluida la referencia OAuth de
  suscripción) aparecen en `config.yaml` en claro; viven en env vars / gestor de secretos.
- **SC-008 (código propio retirado)**: El `gatelite gateway.py` post-migración conserva **sólo** el
  passthrough OAuth de suscripción. Criterio verificable por la lista concreta de símbolos de FR-030 (no
  por conteo de líneas): un `grep` sobre `gateway.py` de `_rewrite_sse_event`, `_redact_body`,
  `_detect_tool`, `_resolve_identity`, `_passthrough_headers`, `_IN_RE`, `_OUT_RE`, el endpoint
  `/gw/v1/messages` y los passthrough `count_tokens`/`models` devuelve **0 coincidencias**; el archivo
  retiene únicamente el passthrough OAuth reescrito sobre `basa_guardian_policy`.

## Assumptions

- **Depende del bedrock 013**: `Tenant`, `role="client"`, `client_type`, y la Connection = APIKey
  extendida con `tenant_id`/`tool_type`/`upstream_mode` ya existen. Esta spec NO los diseña; los consume.
- **Reconciliación de vocabulario con 013 (`upstream_mode`)**: la 013 define el enum
  `upstream_mode = {'byok', 'subscription-passthrough'}`. Esta spec (y el demo hand-rolled) hablaban de
  "modo anthropic"; queda **reconciliado** así: "anthropic" (demo) → `subscription-passthrough` (013);
  "byok" se mantiene igual. En toda la 014 se usan los valores del enum de 013 como fuente de verdad; las
  menciones a "anthropic" se conservan sólo como glosa histórica del demo.
- **Reuso de servicios existentes**: `ComplianceService`, `GuardianService`, `PresidioService` y
  `AuditService` se reutilizan sin modificarlos. La activación de Presidio NLP real es la spec 016
  (hoy sigue el default regex, aceptable para demo/dev; prod exige 016 — Constraint C2 constitucional).
- **Madurez del motor a verificar**: se asume que LiteLLM ejecuta los tres hooks del guardrail y
  `custom_auth` sobre la ruta `/v1/messages` nativa; esto se **verifica** con contract tests (US5) y es
  un riesgo explícito (la doc del motor va por detrás del código).
- **[D-014] (decisión por defecto, revisable)**: en `upstream_mode` = `subscription-passthrough` sin
  `X-Basa-Key`, la identidad se atribuye así: **tenant/cliente atribuido por `X-Basa-Key` si está
  presente; si no, la request se considera autenticada por la suscripción (el OAuth es la credencial)
  pero con atribución anónima a nivel `tenant-default`, auditada explícitamente como tal**. Esto
  desbloquea US4: el fail-closed duro aplica a `byok` (Constraint C3), no a esta ruta OAuth, donde
  la credencial es la suscripción y `X-Basa-Key` es atribución opcional. Marcado `[D-014]` como decisión
  revisable (los defaults son revisables).
- **Provisioning de virtual keys**: se asume resolución **directa** por `key_hash` contra la tabla
  `APIKey` de Basa dentro de `custom_auth` (mantiene el modelo de identidad en Basa/013), evitando doble
  fuente de verdad con el store interno de virtual keys de LiteLLM. Si se prefiere delegar al store del
  motor, es un seed que sincroniza `APIKey`↔virtual key.
- **Router GDPR-routing = N/A** en toda esta ruta base_url es una decisión constitucional ya ratificada
  (excepción acotada del Principio II), no una omisión.
- **El monitor es vitrina de demo**: su feed es efímero (in-memory); la auditoría durable (Postgres)
  sigue siendo metadata-only. La animación es cosmética sobre datos reales (Principio VIII).
