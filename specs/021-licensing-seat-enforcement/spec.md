# Feature Specification: Licensing & Seat Enforcement (offline, distributor model)

**Feature Branch**: `021-licensing-seat-enforcement`

**Created**: 2026-07-13

**Status**: Draft

**Input**: User description: "Modelo comercial 'install + X licencias' vendido a un distribuidor marca-blanca. El cliente CORRE el software (Basa no controla la caja) → el enforcement de licencias debe ser OFFLINE y anti-tamper, sin phone-home (on-prem/VPN puede no tener egress). Falta hoy TODO el enforcement (cero max_seats/license_key/entitlement); es greenfield sobre plomería sólida (Connection=APIKey, custom_auth fail-closed, audit inmutable). Complementa la 020 (deploy)."

---

## Contexto y honestidad SDD *(léelo antes que nada)*

Esta feature es **VERDE (greenfield)** en su corazón: **hoy no existe NINGÚN enforcement de licencias**.
No hay `max_seats`, ni `license_key`, ni `entitlement`, ni artefacto de licencia firmado, ni contador de
seats, ni expiry/grace, ni modo degradado por vencimiento. El sistema hoy crea Connections y Clients sin
tope. Decirlo con todas las letras: **el gate comercial de "X licencias" NO está implementado**.

Lo que **SÍ es sólido** es la **PLOMERÍA sobre la que esta spec engancha** — y por eso es viable sin
refactor grande:

- **La UNIDAD DE SEAT ya existe y es limpia.** La **Connection** (modelo `APIKey`) es "un asiento": hay
  **≤1 Connection activa por herramienta por cliente**, garantizado por el índice parcial
  `uq_api_keys_tenant_user_tool` **más** un pre-check que devuelve **409** antes de crear una duplicada.
  Es decir, "X licencias" mapea **limpio** a "**X Connections activas**" (o "**X Clients con
  `role=client`**") bajo un **Tenant**. La licencia se **escopea por Tenant** (el comprador = el cliente
  final del distribuidor); el `slug`/`deployment_mode` empaquetan por cliente (013/020).
- **El punto de enganche del gate ya está identificado y es fail-closed.** `custom_auth.py` resuelve
  virtual key → tenant/client/tool **FAIL-CLOSED** por `key_hash=sha256`, y el provisioning al motor va
  vía `ai_engine_client` (`generate_key`/`create_user`/`create_team`). El gate de licencia vive en la
  **CREACIÓN**: rechazar crear una Connection/Client **más allá del máximo licenciado** en los `POST` del
  backend (`keys.py`/`users.py`), **más** una **reconciliación** periódica que detecta drift.

**OJO — trampa a evitar:** `rpm_limit`/`tpm_limit`/`max_budget` (spec 007) son **gobernanza de USO por
seat** (cuánto consume un asiento), **NO conteo de seats**. **No sirven como licencia**: un tenant puede
tener presupuesto infinito y aun así estar limitado a 5 asientos, o presupuesto cero y 50 asientos. Son
ejes ortogonales; esta spec cuenta **asientos**, no tokens ni dólares.

**Alcance honesto — lo que ESTA spec construye (el corazón que falta):**
1. Un **artefacto de LICENCIA FIRMADO** verificable **OFFLINE** (token **Ed25519** con `tenant_id`,
   `distributor_id`/`pool_id`, `max_seats`, `expiry`, `feature_flags`, `license_id` — lista completa en
   FR-001), chequeado al **arranque** y en la **creación** de Connection/Client — **NADA de
   license-server / phone-home** (on-prem/VPN puede no tener egress).
2. Un **contador de seats** = `COUNT(APIKey activas)` (o `COUNT(User role=client)`) por tenant, contra el
   `max_seats` del artefacto.
3. Manejo de **expiry + grace period**.
4. **Evidencia de tamper** vía el **audit log inmutable YA existente** (no se inventa un canal nuevo).
5. **Modo degradado** al vencer/exceder (read-only vs bloqueo de creación).

**Esta spec NO hace**: no diseña el schema base (Tenant/APIKey/User vienen de 013); no toca el deploy /
packaging del contenedor (eso es la **020**, que esta spec **complementa**: la licencia se **inyecta**
en el artefacto de deploy de la 020); no implementa un portal de emisión/venta de licencias del lado del
distribuidor (fuera de scope — sólo se define el **formato** del token y la **clave pública** que el
producto embebe). El **firmante** (clave privada) vive del lado de **Basa** (central, KMS/HSM); el
distribuidor NUNCA posee clave de firma — mintea vía el portal de emisión de Basa dentro de su cupo
(FR-030, research addendum).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Artefacto de licencia firmado Ed25519 + verificación offline al arranque (Priority: P1)

Basa emite (firma **central**; el distribuidor la solicita vía el portal de emisión dentro de su cupo,
FR-030) un **token de licencia firmado con Ed25519** que contiene `license_id`, `tenant_id`,
`distributor_id`, `pool_id`, `max_seats`, `expiry`, `feature_flags` y `grace_days` (lista completa en
FR-001).
El producto (contenedor) embebe **sólo la clave PÚBLICA** de Basa. Al **arranque**, el backend lee el
token (de un env var / secret / fichero montado por la 020), **verifica la firma Ed25519 contra la clave
pública embebida**, valida que no esté expirado más allá del grace, y **carga el entitlement en memoria**.
Si la firma es inválida, el `tenant_id` no coincide con el deployment, o el token está ausente/corrupto,
el sistema **arranca en modo degradado fail-closed** (no crea seats nuevos) y **emite un evento de audit**.
Todo **sin ninguna llamada de red** — funciona en una caja on-prem sin egress.

**Why this priority**: Es el cimiento de toda la spec. Sin un artefacto verificable **offline** no hay
enforcement posible en el modelo distribuidor (Basa no controla la caja, y on-prem/VPN puede no tener
egress → **phone-home no es una opción**). Materializa el Principio VII (White-Label: la licencia es
**config firmada**, no un fork ni un binario custom por cliente) y habilita el gate de US2/US3.

**Independent Test**: Arrancar el contenedor con (a) un token válido firmado → el entitlement
(`tenant_id`, `max_seats`, `expiry`) queda cargado y consultable; (b) un token con **firma alterada** (un
byte cambiado) → arranque en modo degradado fail-closed + evento de audit; (c) **sin** token → ídem;
(d) un token de **otro `tenant_id`** → rechazo. Todo **sin acceso a red** (correr con egress bloqueado
para probar que es offline).

**Acceptance Scenarios**:

1. **Given** un token de licencia firmado Ed25519 válido para el `tenant_id` del deployment, **When** el
   backend arranca, **Then** verifica la firma contra la **clave pública embebida** (sin red), carga
   `{license_id, tenant_id, distributor_id, pool_id, max_seats, expiry, feature_flags, grace_days}` en
   memoria y queda operativo.
2. **Given** un token cuya firma no valida contra la clave pública (alterado/corrupto), **When** el
   backend arranca, **Then** entra en **modo degradado fail-closed** (no permite crear seats), lo
   registra en el audit inmutable y expone el estado de licencia como `invalid`.
3. **Given** un token cuyo `tenant_id` no coincide con el del deployment (013/020), **When** arranca,
   **Then** lo rechaza como `mismatch` y no carga el entitlement.
4. **Given** un entorno **sin egress de red**, **When** el backend arranca con token válido, **Then** la
   verificación se completa **localmente** (0 llamadas salientes) y el sistema opera normal.
5. **Given** un token con **firma VÁLIDA pero `expiry` pasado** (dentro de `grace_days`), **When** el
   backend arranca, **Then** el entitlement SE CARGA con estado `grace` (NO `invalid`): el tráfico
   existente sigue y sólo se bloquea la creación de seats — **una licencia vencida jamás mata el
   proceso**, y bajo la **política default** (read-only-para-creación) tampoco corta el tráfico en vuelo
   (el bloqueo total post-grace es un opt-in contractual de US4, no el default; distinto de firma
   inválida/tamper, que es fail-closed duro de creación; ver research addendum: HashiCorp/Elastic/GitLab
   degradan, ninguno crashea prod por expiración).

---

### User Story 2 - Gate de seats en la creación de Connection/Client (Priority: P1)

Cuando un operador del cliente crea una **Connection** nueva (`POST` en `keys.py`) o un **Client**
(`role=client`, `POST` en `users.py`), el backend consulta el entitlement cargado (US1) y **cuenta los
seats activos** del tenant. Si crear el nuevo seat **excedería `max_seats`**, el `POST` se **rechaza con
HTTP 402/403** (`license_seat_limit_exceeded`) **antes** de provisionar nada en el motor
(`ai_engine_client.generate_key`), y se emite un evento de audit. El gate es **fail-closed**: si el
entitlement no está cargado o es inválido, la creación se **bloquea** (no se asume "ilimitado").

**Why this priority**: Es el punto donde "X licencias" se **hace cumplir**. El pre-check ya existe para el
409 de duplicados; este story añade una **segunda guarda** —el conteo contra `max_seats`— en el **mismo
call-site** de creación. Es P1 porque sin este gate el artefacto de US1 es decorativo. Materializa el
Principio III (Multi-Tenant: el tope se aplica **por tenant**, aislado) y refuerza el fail-closed
existente de `custom_auth`.

**Independent Test**: Con un entitlement de `max_seats=3` y 3 Connections activas, hacer `POST` de una 4ª
Connection → **rechazo 402/403** `license_seat_limit_exceeded`, **sin** provisioning en el motor, con
evento de audit; borrar/revocar una Connection (baja a 2) y reintentar → **éxito**. Repetir para
`POST` de Client con `role=client`.

**Acceptance Scenarios**:

1. **Given** un tenant con `max_seats=N` y **N Connections activas**, **When** llega un `POST` que crearía
   la Connection N+1, **Then** el backend responde **402/403** `license_seat_limit_exceeded`, **no** llama
   a `ai_engine_client.generate_key`, y registra el intento en el audit.
2. **Given** el mismo tenant tras revocar una Connection (activas = N−1), **When** llega el `POST`,
   **Then** la Connection se crea normalmente y el conteo vuelve a N.
3. **Given** el entitlement **no cargado** o inválido (US1 en degradado), **When** llega un `POST` de
   creación, **Then** se **bloquea fail-closed** (no se asume ilimitado).
4. **Given** el gate de licencia, **When** convive con el pre-check de duplicados (409
   `uq_api_keys_tenant_user_tool`), **Then** ambos aplican: el 409 protege contra el duplicado por
   herramienta y el 402/403 protege contra exceder `max_seats` (guardas independientes).
5. **Given** que `max_seats` cuenta **asientos**, **When** un tenant tiene `rpm_limit`/`max_budget` (007)
   configurados, **Then** esos límites de **uso** NO afectan el conteo de seats (ejes ortogonales).

---

### User Story 3 - Contador / reconciliación de seats por tenant (Priority: P2)

El sistema define **una fuente de verdad** del conteo de seats por tenant — `COUNT(APIKey activas)` (o,
según la política elegida, `COUNT(User role=client)`) — y corre una **reconciliación periódica** que
compara ese conteo real contra `max_seats`. La reconciliación detecta **drift** (p.ej. seats creados por
una ruta que evadió el gate, restauración de backup, edición directa en DB) y, si el conteo **supera** el
tope, marca el tenant como **over-seat** y dispara el modo degradado (US4) + evento de audit. La
reconciliación es **local** (query a la DB propia), sin phone-home.

**Why this priority**: El gate de creación (US2) protege la **puerta de entrada**, pero un modelo offline
anti-tamper necesita **detección continua** de estados inconsistentes que la puerta no vio (backups,
manipulación directa de la DB, bugs). Es P2 porque US1+US2 ya entregan el enforcement en el happy-path;
la reconciliación es la **red de seguridad** que cierra los caminos laterales. Refuerza el Principio III
(aislamiento por tenant) y alimenta la evidencia de tamper (US5).

**Independent Test**: Insertar directamente en DB Connections activas hasta superar `max_seats` (simulando
drift), correr la reconciliación → el tenant queda marcado `over_seat`, se dispara el modo degradado y
hay un evento de audit con el conteo real vs el tope. Bajar el conteo y reconciliar → estado vuelve a
`ok`.

**Acceptance Scenarios**:

1. **Given** la definición de seat = `COUNT(APIKey activas)` por tenant, **When** corre la reconciliación,
   **Then** compara ese conteo contra `max_seats` del entitlement y publica un estado
   `{ok|over_seat|expired}` por tenant.
2. **Given** un conteo real que **supera** `max_seats` (drift por DB directa o restauración de backup),
   **When** reconcilia, **Then** marca `over_seat`, activa el modo degradado (US4) y emite audit con
   `seats_used` vs `max_seats`.
3. **Given** que el drift se corrige (conteo ≤ `max_seats`), **When** reconcilia de nuevo, **Then** el
   estado vuelve a `ok` y el modo degradado se levanta (según política de US4).
4. **Given** múltiples tenants, **When** reconcilia, **Then** cada tenant se evalúa **aislado** (el
   over-seat de uno no afecta a otro) — Principio III.

---

### User Story 4 - Expiry + grace period + modo degradado (Priority: P2)

El entitlement tiene `expiry` y `grace_days`. Antes del `expiry`, todo normal. Entre `expiry` y
`expiry + grace_days`, el sistema entra en **grace**: sigue operando pero **advierte** (estado
`grace`, evento de audit, banner/health) y **bloquea la creación de seats nuevos**. Pasado el grace (o si
el estado es `over_seat` por US3), entra en **modo degradado**: por defecto **read-only para creación**
(las Connections/Clients existentes siguen sirviendo tráfico, pero **no se crean nuevos** ni se re-emiten
keys), configurable a un modo de **bloqueo total** más duro según la política del contrato. El reloj es
**local** (no depende de un time-server externo); se documenta la mitigación anti-rollback (US5).

**Why this priority**: Una licencia sin expiry no es una licencia; sin grace, un reloj desfasado o una
renovación en trámite tumba producción del cliente. El modo degradado **read-only-para-creación** es el
default humano (no rompe el tráfico en vuelo, sólo cierra el crecimiento). Es P2 porque el enforcement
"duro" (US1+US2) ya existe sin expiry; esto le da **ciclo de vida** y un **aterrizaje suave**. Sirve al
Principio II (el estado de licencia y sus transiciones quedan como evidencia auditable).

**Independent Test**: Con un token cuyo `expiry` es pasado pero dentro de `grace_days` → estado `grace`,
creación bloqueada, tráfico existente OK, audit emitido. Avanzar el reloj más allá del grace → `expired`,
modo degradado (read-only-para-creación por default). Verificar el toggle a bloqueo total.

**Acceptance Scenarios**:

1. **Given** un entitlement con `expiry` futuro, **When** opera, **Then** el estado es `active` y la
   creación de seats está permitida (hasta `max_seats`).
2. **Given** un `expiry` ya pasado pero dentro de `expiry + grace_days`, **When** opera, **Then** el
   estado es `grace`: el tráfico existente sigue, la **creación de seats se bloquea**, y se emite audit +
   señal de health.
3. **Given** un `expiry + grace_days` ya superado, **When** opera, **Then** el estado es `expired` y entra
   en **modo degradado** (default: **read-only para creación**; toggle a bloqueo total configurable).
4. **Given** el reloj **local** de la caja, **When** se evalúa el expiry, **Then** la decisión NO depende
   de un time-server externo (offline), y el rollback de reloj se mitiga con la marca monotónica de US5.

---

### User Story 5 - Evidencia de tamper: audit hash-chained + export de true-up firmado (Priority: P3)

Cada transición relevante de licencia — carga OK, firma inválida, `tenant_id` mismatch, token ausente,
seat-limit-exceeded (US2), over-seat detectado (US3), grace, expired, y **sospecha de rollback de reloj**
(un `now` observado **anterior** al último timestamp de licencia visto) — se registra como un evento en el
**audit log inmutable YA existente** (metadata-only), con un endurecimiento clave: los eventos de licencia
van **encadenados por hash** (cada evento incluye el hash del anterior), de modo que borrar o editar
cualquier eslabón **rompe la cadena de forma detectable**. Además, el operador puede generar un **export
de true-up** (resumen de seats usados + historial de estados de licencia) que el sistema **firma**, para
entregarlo al distribuidor/Basa en la **renovación** (modelo de reconciliación de GitLab). Un auditor
puede así reconstruir si el cliente corrió over-seat, expirado, o con un token inválido — y detectar si el
historial fue manipulado. NO se inventa un canal nuevo: se **reusa** la infraestructura de audit
inmutable, endurecida con la cadena de hashes.

> **Honestidad (research addendum)**: una tabla "inmutable" que vive en el Postgres del cliente es
> borrable por quien controla el runtime — y la **deployment key también vive en la caja** (quien
> controla el box puede leerla y firmar un export forjado sobre una cadena regenerada). La cadena de
> hashes hace el tamper **intermedio** detectable localmente; el truncado (de cola o total) se detecta
> recién **en la renovación** por la continuidad head/contador entre exports; y el export firmado aporta
> **atribución al deployment + integridad del artefacto** — es tan confiable como el operador de la
> caja. El **ancla de innegabilidad es el contrato** (true-up + audit-rights del EULA), no la
> criptografía. La spec promete detectabilidad y fricción, no un log indestructible.

**Why this priority**: En un modelo donde el cliente **corre el software**, el enforcement no puede ser
inviolable — pero **sí puede ser detectable y oponible por contrato** (true-up + audit-rights). El audit
hash-chained convierte el tamper intermedio en un rastro verificable y el true-up hace el resto exigible
comercialmente (evidencia para el contrato / disputa). Es P3 porque el enforcement funciona sin
esta capa de evidencia formalizada, pero sin ella se pierde el valor **anti-tamper** del modelo
distribuidor. Materializa el Principio II (el audit inmutable como evidencia de compliance/tamper).

**Independent Test**: Provocar cada transición (token inválido, exceder seats, over-seat por DB directa,
grace, expired, retroceder el reloj del sistema) y verificar que **cada una** deja un `AuditLog`
append-only con el tipo de evento, `license_id`, `tenant_id`, `seats_used`/`max_seats` y timestamp, y que
**ninguno** puede borrarse/editarse por la ruta normal (inmutabilidad). Además: (a) borrar/editar un
evento **intermedio** por DB directa → la **verificación de la cadena de hashes** lo detecta y lo
reporta (el truncado de cola/total NO es detectable localmente — se cubre por continuidad head/contador
entre exports en la renovación, FR-028); (b) generar el **export de true-up** → su firma valida contra
la **clave pública del deployment** (registrada en el onboarding) y su contenido refleja lo que la caja
registró (incl. hash-head + contador); alterar un byte del export → la firma NO valida.

**Acceptance Scenarios**:

1. **Given** el audit inmutable existente, **When** ocurre cualquier transición de licencia (carga,
   inválido, mismatch, seat-limit, over-seat, grace, expired), **Then** se persiste un evento
   metadata-only con `{event_type, license_id, tenant_id, seats_used, max_seats, ts, prev_hash}`
   (FR-028) y **cero** secretos (ni la clave, ni el token crudo).
2. **Given** un `now` del sistema **anterior** al último timestamp de licencia registrado (posible
   rollback de reloj), **When** se evalúa la licencia, **Then** se emite un evento
   `license_clock_rollback_suspected` y (según política) se trata como degradado.
3. **Given** los eventos de licencia en el audit append-only, **When** un auditor los revisa, **Then**
   puede reconstruir el historial de estados (over-seat/expired/tamper) **sin** poder alterarlos
   (inmutabilidad garantizada por la infraestructura existente).
4. **Given** la evidencia de tamper, **When** se persiste, **Then** es **metadata-only** (no incluye el
   token de licencia crudo ni la clave pública/privada), consistente con la política de audit del sistema.
5. **Given** los eventos de licencia **encadenados por hash**, **When** alguien borra o edita un evento
   **intermedio** por DB directa, **Then** la verificación de la cadena detecta el eslabón roto y lo
   reporta como evidencia de tamper (detectable, no prevenible; el truncado de cola/total escapa a la
   verificación local y se detecta en la renovación — ver honestidad arriba y FR-028).
6. **Given** una renovación de licencia en curso, **When** el operador genera el **export de true-up**,
   **Then** el sistema produce un artefacto **firmado con la clave de deployment** (par Ed25519 generado
   en el install; la pública se registra del lado Basa/distribuidor en el onboarding — la caja NO puede
   firmar con la clave de Basa, solo tiene su pública) que contiene `{tenant_id, distributor_id, pool_id,
   seats_used, max_seats, historial de estados, hash-head + contador de eventos, rango de fechas}` —
   metadata-only, sin PII ni el token crudo. Basa verifica: firma vs la deployment key registrada +
   consistencia interna de la cadena + **continuidad con el export anterior** (head-ancestro, contador
   no-decreciente) + anclaje al `license_id`.

---

### Edge Cases

- **Caja sin egress de red (on-prem/VPN)**: la verificación de licencia y la reconciliación deben ser
  **100% locales**. Cualquier intento de phone-home rompe el modelo. Test explícito con egress bloqueado.
- **Reloj retrocedido (anti-rollback)**: un cliente podría atrasar el reloj para evadir el `expiry`. Se
  guarda una **marca monotónica** (último timestamp de licencia/audit visto); si `now` < esa marca, se
  sospecha rollback (US5) y se degrada. No es inviolable, pero es **detectable y auditable**.
- **Token ausente o corrupto al arranque**: fail-closed (no "sin token = ilimitado"). Arranca en degradado
  y audita. El default seguro es **negar creación**, no permitirla.
- **Firma válida pero `tenant_id` cruzado**: un token legítimo de otro tenant no debe habilitar este
  deployment. El `tenant_id` del token debe coincidir con el del deployment (013/020) → si no, `mismatch`.
- **Drift por restauración de backup / edición directa en DB**: un backup viejo o un `INSERT` manual puede
  crear más seats de los licenciados sin pasar por el gate (US2). La reconciliación (US3) lo detecta como
  `over_seat`.
- **Seats "activos" vs revocados/soft-deleted**: el conteo debe contar **sólo activos** (misma definición
  que el índice parcial `uq_api_keys_tenant_user_tool`), no las Connections revocadas/expiradas, para no
  inflar el conteo y bloquear injustamente.
- **`max_seats` reducido en una renovación (downgrade)**: si un nuevo token baja `max_seats` por debajo del
  conteo actual, el tenant queda `over_seat` legítimamente; la política (US4) decide si es grace o bloqueo
  de creación hasta que el cliente reduzca seats. No se borran seats automáticamente.
- **`feature_flags` del token**: habilitan/deshabilitan módulos white-label (p.ej. monitor, ciertos
  tools). Un flag ausente = feature **off** (fail-closed), no on por defecto.
- **Colisión con `rpm_limit`/`max_budget` (007)**: NO confundir gobernanza de uso con conteo de seats. Un
  seat puede existir (cuenta para la licencia) aunque esté rate-limited a 0 rpm por gobernanza. Ejes
  ortogonales; un test lo fija.
- **Rotación de la clave pública embebida**: si Basa rota su par de claves, los deployments viejos con la
  clave pública anterior deben seguir validando tokens firmados con la privada anterior hasta migrar. Se
  soporta un **conjunto** de claves públicas embebidas (key-id en el token) para rotación sin romper cajas
  desplegadas.

## Requirements *(mandatory)*

### Functional Requirements

**Artefacto de licencia + verificación offline (US1)**
- **FR-001**: El sistema MUST definir un **artefacto de licencia** firmado con **Ed25519** que contenga al
  menos `{schema, license_id, tenant_id, distributor_id, pool_id, max_seats, not_before, expiry,
  grace_days, feature_flags, key_id}` (con `issued_at` **opcional** ≈ `not_before` si se omite, como en
  el esbozo `.lic` del research). `distributor_id`/`pool_id` identifican el **canal** que
  giró la licencia (atribución para audit/true-up; la validación del cupo del pool vive en el portal de
  emisión de Basa, fuera del scope de la caja — ver addendum). Para **emisión directa de Basa sin canal**
  (demos, pilotos, cajas propias): sentinel `distributor_id: "d_basa"` + pool interno — semántica "canal
  directo" fijada desde el día 1 para no cambiar el formato wire después. El formato wire `.lic` (JSON canónico +
  firma detached; nombres compactos `lic_id`/`kid`) y el veredicto build-vs-buy (DIY Ed25519, emisión
  CENTRAL de Basa por cupo — nunca clave de firma delegada al distribuidor) están fijados en
  [`research.md`](./research.md).
- **FR-002**: El producto MUST embeber **sólo la(s) clave(s) PÚBLICA(s)** de Basa; la clave privada de
  firma de licencias NUNCA vive en el contenedor ni en la caja del cliente (vive del lado de **Basa**, en
  KMS/HSM — el distribuidor no firma, addendum). Nota: la **deployment key** (FR-029) es un par DISTINTO
  que sí vive en la caja — firma **evidencia**, no licencias, y no tiene poder de emisión.
- **FR-003**: Al **arranque**, el sistema MUST verificar la firma Ed25519 del token contra la clave
  pública embebida (seleccionada por `key_id`) y cargar el entitlement en memoria si es válido.
- **FR-004**: La verificación MUST ser **100% offline**: 0 llamadas de red (no license-server, no
  phone-home), para operar en cajas on-prem/VPN sin egress (Constraint: distributor/offline).
- **FR-005**: El sistema MUST validar que `token.tenant_id` coincide con el `tenant_id` del deployment
  (013/020); si no, MUST rechazar el token como `mismatch` y NO cargar el entitlement.
- **FR-006**: Si el token está **ausente, corrupto, con firma inválida o mismatch**, el sistema MUST
  arrancar en **modo degradado fail-closed** (no crea seats nuevos) y MUST emitir un evento de audit
  (US5). MUST NOT interpretar "sin token" como "seats ilimitados".
- **FR-007**: El sistema MUST soportar un **conjunto** de claves públicas embebidas indexadas por `key_id`
  para permitir **rotación de claves** sin romper deployments ya desplegados.

**Gate de seats en creación (US2)**
- **FR-008**: En el `POST` de creación de **Connection** (`keys.py`) el sistema MUST contar los seats
  activos del tenant y **rechazar** con **HTTP 402/403** `license_seat_limit_exceeded` si la creación
  excedería `max_seats`, **antes** de provisionar en el motor (`ai_engine_client.generate_key`).
- **FR-009**: En el `POST` de creación de **Client** (`role=client`, `users.py`) el sistema MUST aplicar
  el mismo gate contra `max_seats` (según la política de unidad de seat elegida — ver FR-013).
- **FR-010**: El gate de seats MUST ser **fail-closed**: si el entitlement no está cargado o es inválido
  (US1 degradado), la creación MUST bloquearse (no asumir ilimitado).
- **FR-011**: El gate de licencia MUST **coexistir** con el pre-check de duplicados existente (409 sobre
  `uq_api_keys_tenant_user_tool`): son **guardas independientes** (409 = duplicado por herramienta;
  402/403 = exceder `max_seats`).
- **FR-012**: El sistema MUST NOT usar `rpm_limit`/`tpm_limit`/`max_budget` (007) como conteo de seats:
  esos son gobernanza de **uso**, ortogonales al conteo de **asientos**.

**Contador / reconciliación (US3)**
- **FR-013**: El sistema MUST definir **una** fuente de verdad para el conteo de seats por tenant —
  `COUNT(APIKey activas)` como default, o `COUNT(User role=client)` según la política documentada— y usar
  la **misma** definición en el gate (US2) y en la reconciliación (US3).
- **FR-014**: El sistema MUST contar **sólo seats activos** (consistente con el índice parcial
  `uq_api_keys_tenant_user_tool`), excluyendo revocados/soft-deleted/expirados.
- **FR-015**: El sistema MUST correr una **reconciliación periódica local** que compare el conteo real
  contra `max_seats` por tenant y publique un estado `{ok|over_seat|expired}` por tenant.
- **FR-016**: Si la reconciliación detecta `seats_used > max_seats` (drift por DB directa, backup, bug),
  MUST marcar el tenant `over_seat`, activar el modo degradado (US4) y emitir audit (US5).
- **FR-017**: La reconciliación MUST evaluar cada tenant **aislado** (Principio III): el over-seat de un
  tenant no afecta a otro.

**Expiry + grace + modo degradado (US4)**
- **FR-018**: El sistema MUST evaluar `expiry` y `grace_days` del entitlement y computar un estado de
  licencia `{active|grace|expired|invalid|over_seat}`.
- **FR-019**: En estado `grace` (entre `expiry` y `expiry + grace_days`) el sistema MUST permitir el
  tráfico existente pero **bloquear la creación de seats nuevos**, emitiendo audit + señal de health.
- **FR-020**: En estado `expired` (o `over_seat`) el sistema MUST entrar en **modo degradado**, con default
  **read-only para creación** (Connections/Clients existentes siguen sirviendo, no se crean nuevos ni se
  re-emiten keys) y un **toggle configurable** a bloqueo total más duro.
- **FR-021**: La evaluación de expiry MUST usar el reloj **local** (offline), sin depender de un
  time-server externo.

**Evidencia de tamper (US5)**
- **FR-022**: El sistema MUST registrar **cada transición de licencia** (carga OK, inválido, mismatch,
  ausente, seat-limit-exceeded, over-seat, grace, expired, clock-rollback) como evento en el **audit log
  inmutable existente**, metadata-only.
- **FR-023**: El sistema MUST guardar una **marca monotónica** (último timestamp de licencia/audit visto)
  y, si `now` < esa marca, MUST emitir `license_clock_rollback_suspected` y tratar el estado como degradado
  según política (anti-rollback).
- **FR-024**: Los eventos de licencia MUST ser **metadata-only**: MUST NOT persistir el token de licencia
  crudo, ni la clave privada, ni ningún secreto (consistente con la política de audit del sistema).
- **FR-025**: El sistema MUST reusar la **infraestructura de audit inmutable existente** (append-only); NO
  MUST inventar un canal de evidencia separado.
- **FR-028**: Los eventos de licencia MUST ir **encadenados por hash** (cada evento incluye el hash del
  anterior, con génesis anclada al `license_id`), y el sistema MUST persistir junto a la marca monotónica
  (FR-023) el **hash-head vigente** y un **contador monotónico de eventos**. Alcance honesto: la cadena
  local detecta **edición/borrado intermedio**; NO detecta por sí sola el **truncado de cola** ni el
  **truncado total + re-génesis** (el cliente controla el Postgres y conoce su `license_id`). Esos dos
  ataques se detectan **en la renovación** vía FR-029: Basa verifica **continuidad entre exports
  sucesivos** (el head del export N debe ser ancestro del head del export N+1; el contador nunca
  decrece). En una renovación (nuevo `license_id`), la nueva génesis MUST encadenarse al head de la
  cadena anterior (continuidad entre licencias). **Primer export (sin export anterior)**: el hash-head de
  la génesis MUST registrarse en el **onboarding** (mismo canal que la pública del deployment, FR-029) y
  servir de baseline — sin ese registro, un truncado total + re-génesis ANTES de la primera renovación
  sería indetectable incluso para Basa.
- **FR-029**: El sistema MUST poder generar un **export de true-up** firmado con la **clave de
  deployment** (par Ed25519 generado en el install; la privada nunca sale de la caja, la pública se
  registra del lado Basa/distribuidor en el onboarding) con `{tenant_id, distributor_id, pool_id,
  seats_used, max_seats, historial de estados, hash-head + contador de eventos de la cadena, rango de
  fechas}`, metadata-only. Es el artefacto de **reconciliación en la renovación** (modelo GitLab true-up);
  su generación es local y offline (el operador lo entrega por el canal que sea — email/USB). Honestidad:
  el export aporta **atribución al deployment + integridad del artefacto** — quien controla la caja puede
  leer la deployment key y firmar un export forjado sobre una cadena regenerada; la evidencia es tan
  confiable como el operador (ver Assumptions).

*(Numeración: FR-028/FR-029 se añadieron con el addendum 2026-07-14 — por eso siguen a FR-027; FR-030
vive en la sección transversal de abajo.)*

**Integración con deploy (020) y config (transversal)**
- **FR-026**: El token de licencia MUST inyectarse como **config** del artefacto de deploy de la 020
  (env var / secret / fichero montado), NUNCA hardcodeado ni forkeado por cliente (Principio VII: la
  licencia es config firmada, no un binario custom). Segundo punto de contacto con la 020: el artefacto
  de deploy MUST provisionar además el **volumen/secret persistente** para la clave privada del
  deployment (FR-029), generada en el **install** (encaja con "secretos por instalación" D5 de la 020);
  el registro de la pública ocurre en el onboarding, fuera de la caja.
- **FR-027**: El estado de licencia (`{status, seats_used, max_seats, expiry}`) MUST exponerse en un
  endpoint de **health/status** (metadata-only) para operación y soporte, sin filtrar el token ni claves.
- **FR-030**: El enforcement del **cupo del distribuidor** (`sum(max_seats de las hojas VIGENTES) ≤
  max_total_seats` del pool — una **re-emisión para el mismo `tenant_id` SUPERSEDE a la anterior**, de
  modo que expansiones y renovaciones NO consumen cupo doble) vive en el **portal/API de emisión de
  Basa** (lado firmante, online), NO en la caja: la caja sólo valida su propia hoja `.lic`. La spec del
  portal queda fuera de scope; este FR fija el contrato (la caja nunca asume responsabilidad por el techo
  global del pool).

### Key Entities *(include if feature involves data)*

- **LicenseToken (artefacto firmado)** — *NUEVO, código PROPIO*. Payload firmado Ed25519 con
  `{schema, license_id, tenant_id, distributor_id, pool_id, max_seats, not_before, expiry, grace_days,
  feature_flags, key_id}` (+ `issued_at` opcional) + firma (esbozo `.lic` completo en
  [`research.md`](./research.md); wire `lic_id`/`kid`). Emitido SIEMPRE por Basa (firma central; el distribuidor mintea vía portal dentro
  de su cupo — addendum). Se **inyecta como config** (020), se verifica offline al arranque. NO se
  persiste crudo en audit.
- **DeploymentKey (par de claves del deployment)** — *NUEVO, código PROPIO*. Par Ed25519 generado en el
  **install** de la caja; la privada nunca sale de la caja, la pública se registra del lado
  Basa/distribuidor en el onboarding. Firma el TrueUpExport (FR-029). Distinta de las claves de Basa
  (BasaPublicKeySet): Basa firma licencias, el deployment firma evidencia.
- **TrueUpExport (artefacto de reconciliación)** — *NUEVO, código PROPIO*. Export metadata-only firmado
  con la DeploymentKey: `{tenant_id, distributor_id, pool_id, seats_used, max_seats, historial de
  estados, hash-head de la cadena, rango de fechas}`. Generado local/offline por el operador; entregado
  en la renovación (modelo GitLab true-up). Basa lo verifica contra la deployment key registrada + la
  consistencia de la cadena (FR-028).
- **Entitlement (estado en memoria)** — *NUEVO, código PROPIO*. Resultado de verificar el token: el
  entitlement cargado + el estado computado `{active|grace|expired|invalid|over_seat}` + `seats_used`.
  Consultado por el gate (US2), la reconciliación (US3) y el health (FR-027).
- **BasaPublicKeySet (claves embebidas)** — *NUEVO, config del producto*. Conjunto de claves públicas
  Ed25519 indexadas por `key_id` para verificar firmas y soportar rotación (FR-007). Sólo públicas.
- **APIKey (= Connection, modelo DB de la 013)** — *REUSA sin cambios de schema*. Es la **unidad de seat**.
  El conteo = `COUNT(APIKey activas)` por tenant, con la misma definición de "activa" que el índice
  parcial `uq_api_keys_tenant_user_tool`. Depende del bedrock 013.
- **User (role=client, modelo DB de la 013)** — *REUSA*. Unidad de seat alternativa
  (`COUNT(User role=client)`) según la política documentada (FR-013). Se elige **una** definición, usada
  consistentemente en gate y reconciliación.
- **Tenant (modelo DB de la 013)** — *REUSA*. Ámbito del entitlement: la licencia se escopea **por
  tenant** (el comprador = cliente final del distribuidor). Aislamiento por tenant (Principio III).
- **AuditLog (modelo DB inmutable)** — *REUSA sin cambios*. Canal de evidencia de tamper (US5),
  append-only, metadata-only. Nunca el token crudo ni claves.
- **SeatReconciliation (job periódico)** — *NUEVO, código PROPIO*. Query local que compara
  `COUNT(activas)` vs `max_seats` por tenant y publica el estado; dispara degradado + audit ante drift.
- **License status endpoint (health)** — *NUEVO, código PROPIO*. Expone `{status, seats_used, max_seats,
  expiry}` metadata-only para operación/soporte.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001 (verificación offline)**: 100% de los arranques con token válido completan la verificación
  **sin ninguna llamada de red** (verificado con egress bloqueado); 0 dependencias de un license-server.
- **SC-002 (fail-closed sin token/inválido)**: 100% de los arranques con token ausente/corrupto/firma
  inválida/`tenant_id` mismatch entran en modo degradado fail-closed (0% interpreta "sin token" como
  ilimitado) y dejan evento de audit.
- **SC-003 (gate de seats)**: Con `max_seats=N` y N seats activos, el 100% de los `POST` de creación
  (Connection y Client) que excederían el tope se rechazan con 402/403 `license_seat_limit_exceeded`
  **antes** de provisionar en el motor; 0 provisioning en el motor para requests rechazadas.
- **SC-004 (coexistencia de guardas)**: El gate de licencia (402/403) y el pre-check de duplicados (409
  `uq_api_keys_tenant_user_tool`) aplican independientemente; verificado con un caso que dispara sólo el
  409, otro sólo el 402/403, y un tercero que podría disparar ambos.
- **SC-005 (reconciliación detecta drift)**: Un drift inyectado por DB directa que lleva el conteo por
  encima de `max_seats` es detectado por la reconciliación en su siguiente corrida al 100%, marcando
  `over_seat` con `seats_used` vs `max_seats` en el audit.
- **SC-006 (ciclo de vida expiry/grace)**: Las tres transiciones `active→grace→expired` se computan con el
  reloj local (offline); en `grace` y `expired` la creación de seats está bloqueada al 100% y el tráfico
  existente sigue (default read-only-para-creación), con evento de audit por transición.
- **SC-007 (evidencia de tamper inmutable)**: 100% de las transiciones de licencia (incl. rollback de
  reloj sospechado) dejan un `AuditLog` append-only metadata-only; 0% de esos eventos contiene el token
  crudo o una clave; 0% puede borrarse/editarse por la ruta normal (inmutabilidad).
- **SC-008 (seats = asientos, no uso)**: El conteo de seats es **independiente** de `rpm_limit`/
  `tpm_limit`/`max_budget` (007); verificado con un tenant que tiene un seat rate-limited a 0 rpm que
  **igual** cuenta para `max_seats`.
- **SC-009 (aislamiento por tenant)**: El estado de licencia (over-seat/expired) de un tenant no altera el
  de ningún otro tenant en el mismo deployment (Principio III).
- **SC-010 (licencia como config, no fork)**: El mismo binario/imagen del producto opera para cualquier
  cliente cambiando **sólo** el token inyectado (020) y (si aplica) el `key_id`; 0 forks ni builds custom
  por cliente (Principio VII).
- **SC-011 (cadena de hashes detecta tamper intermedio)**: Editar o borrar cualquier evento de licencia
  **intermedio** por DB directa es detectado al 100% por la verificación de la cadena (eslabón roto
  reportado como evidencia). El **truncado de cola** y el **truncado total + re-génesis** quedan
  explícitamente FUERA del alcance de la verificación local (limitación estructural de una cadena que
  vive en la DB del cliente): se detectan en la **renovación**, por la continuidad head/contador entre
  TrueUpExports sucesivos (FR-028/FR-029, verificada del lado Basa; baseline del PRIMER export = la
  génesis registrada en el onboarding).
- **SC-012 (true-up verificable)**: El export de true-up generado offline valida al 100% contra la
  deployment key registrada y refleja **lo que la caja registró** (no puede probar más que eso — la
  deployment key es legible por quien controla la caja, ver Assumptions); cualquier alteración de un byte
  invalida la firma; incluye hash-head + contador para la verificación de continuidad del lado Basa. La
  generación no requiere egress.
- **SC-013 (expiry degrada, nunca mata)**: Con licencia válida-pero-vencida (dentro y fuera de grace) y
  **la política default** (read-only-para-creación), el proceso arranca y el tráfico de las Connections
  existentes fluye al 100%; sólo la creación de seats se bloquea. 0 crashes/exits por expiración en
  cualquier política (distinto de firma inválida = fail-closed duro de creación). El **bloqueo total**
  post-grace existe sólo como **opt-in contractual explícito** (toggle de US4), nunca como default.

## Assumptions

- **Depende del bedrock 013**: `Tenant`, `User role=client`, y la Connection = `APIKey` con
  `tenant_id`/`tool_type`/`upstream_mode` y el índice parcial `uq_api_keys_tenant_user_tool` ya existen.
  Esta spec NO los diseña; los **consume** como unidad de seat y ámbito de licencia.
- **Complementa la 020 (deploy)**: la 020 empaqueta/despliega el contenedor; esta spec define **qué config
  firmada** (el token) se inyecta en ese artefacto y **cómo** el producto la verifica offline. La emisión
  de tokens del lado del distribuidor (portal de venta) queda **fuera de scope**: aquí sólo se define el
  **formato** del token y la **clave pública** embebida.
- **Veredicto build-vs-buy (Phase 0, [`research.md`](./research.md))**: no existe un SaaS/servidor de
  licencias reusable que respete a la vez el **air-gap** y el "**cliente corre la caja**"; el enforcement
  es **DIY Ed25519** (verificación offline con clave pública embebida). Billing (Stripe/Paddle/
  LemonSqueezy) ≠ enforcement (validan por HTTP → mueren sin egress); Keygen respeta el air-gap pero su
  parte útil = firmar/verificar un blob (~40 LOC con PyNaCl), el resto asume una topología que no usamos
  porque el conteo de seats vive en NUESTRO Postgres (013).
- **El firmante de licencias es Basa, central**: la clave privada Ed25519 de firma de licencias NUNCA se
  despliega en la caja del cliente ni se entrega al distribuidor (custodia en KMS/HSM del lado Basa;
  el distribuidor mintea vía portal dentro de su cupo — addendum). El producto sólo **verifica**
  licencias; no las firma (sí firma **evidencia** con su deployment key FR-029 — un par distinto, sin
  poder de emisión, legible por quien controla la caja → evidencia best-effort).
- **Definición de "seat" (decisión por defecto, revisable [D-021])**: la unidad de seat por defecto es
  `COUNT(APIKey activas)` por tenant (la Connection = asiento, con el 409/índice parcial ya existente como
  garantía de unicidad por herramienta). Alternativa documentada: `COUNT(User role=client)`. Se elige
  **una** y se usa consistentemente en gate y reconciliación (FR-013). Marcado `[D-021]` como revisable.
- **Enforcement offline = detectable, no inviolable**: como el cliente **corre la caja**, el enforcement
  no puede ser criptográficamente inviolable end-to-end (podrían parchear el binario, y el seat-count vive
  en un Postgres que el cliente controla → el gate de creación es **fricción best-effort, honor-system**,
  idéntico al de GitLab self-managed). El objetivo realista es **fail-closed + anti-tamper detectable**:
  dificultar la evasión y dejar evidencia (cadena de hashes FR-028 + export de true-up firmado FR-029)
  cuya manipulación se detecta. El **ancla de enforcement real es contractual**: el true-up en la
  renovación + la cláusula de audit-rights del EULA (precondición comercial — verificar que exista).
  Esto es explícito, no una carencia oculta (validado contra el mercado en el research addendum).
- **Modelo de 3 partes / emisión central por cupo (addendum)**: Basa (autoridad de firma, privada en KMS)
  → distribuidor/hyperscaler (mintea `.lic` vía portal de Basa dentro de su cupo; único cliente comercial
  de Basa) → cliente final (corre la caja air-gapped). El per-seat se captura **en la emisión** + true-up
  en renovación — nunca metering vivo (imposible sin egress; el metering de marketplace sólo aplica al
  draw-down del cupo del distribuidor en el portal). La **firma delegada al distribuidor NO se construye**;
  trigger documentado: contrato que exija emisión con cero egress a Basa.
- **Anti-rollback de reloj es best-effort**: la marca monotónica (FR-023) detecta retrocesos de reloj pero
  no los previene por completo (sin time-server externo, por diseño offline). Se documenta como mitigación
  detectable-y-auditable, no como garantía dura.
- **Modo degradado por defecto = read-only para creación**: el default es no romper el tráfico en vuelo
  (las Connections existentes siguen sirviendo) y sólo cerrar el crecimiento; el bloqueo total es un toggle
  del contrato. Revisable por cliente/contrato.
- **`feature_flags` fail-closed**: un flag ausente del token = feature **off** (no on por defecto),
  consistente con la postura fail-closed del resto de la spec.
- **Reuso de la infraestructura de audit inmutable**: se asume que el `AuditLog` existente es append-only
  y metadata-only, y sirve como canal de evidencia sin cambios de schema. Si no lo fuera, endurecerlo es
  precondición (pero se asume que sí, por la plomería existente).
- **Rotación de claves por `key_id`**: se asume que el token incluye un `key_id` y que el producto puede
  embeber más de una clave pública para migrar sin romper cajas ya desplegadas (FR-007).
