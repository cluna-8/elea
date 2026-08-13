# Feature Specification: Identidad con dientes — matriz RBAC definitiva, SSO Entra y RLS despierta

**Feature Branch**: `017-auth-rbac-sso`

**Created**: 2026-08-13

**Status**: Draft — pendiente gate de producto (JF): 3 confirmaciones, ver Checklist

**Input**: Roadmap piso 0 (promesa API/BYOK, «SSO escalonado MS+Google, rol Lectura nuevo») + recorte de alcance sellado por JF el 13-ago-2026 + mapa as-is verificado en fuente (workflow de 6 agentes, 13-ago).

---

## Contexto y honestidad — el as-is verificado

Todo lo de abajo está leído en el código de `main` (HEAD 81ea8ce), no en docs ni en memoria. Los `path:line` son evidencia del estado actual, no diseño.

**Identidad y sesión.** Hay un solo login (`POST /api/v1/users/login`, users.py:54-98) que además hace el bootstrap del primer admin mientras la instalación no tenga dueño — ventana «el primero que llega gana» documentada en el propio código (users.py:47-49). El login no tiene rate-limit, no tiene lockout y no emite **ni un** evento de auditoría (grep `audit` en users.py = 0). El JWT es HS256 a 24 h con payload `{sub, role, username, exp}` — **sin tenant, sin jti**, sin refresh ni revocación server-side (session.py:30-37). Logout no existe en el backend (grep = 0); la revocación efectiva es `is_active`, releído de DB en cada request (session.py:76) — desactivar al usuario SÍ corta.

**RBAC.** Un solo mecanismo fail-closed (`require_role`, rbac.py:58-103), pero los gates de **15 routers** están escritos con vocabulario legacy (`admin`/`compliance_officer`/`clinician`/`developer`); el puente es el shim `effective_roles` (rbac.py:36-55), marcado literalmente *«transicional hasta el refactor RBAC de 017»*. `PERMISSIONS` y `ROLE_HIERARCHY` (rbac.py:9-34) son código muerto con cero consumidores: documentación que miente. `compliance_officer` («Auditor» en la UI) **no es read-only**: escribe en 8 superficies, incluida `PUT /compliance/retention` (compliance.py:319, 133-271; consent.py:91,125; policy.py:76-138; costs.py:299,338) — y su existencia **prueba dueño** en el bootstrap (users.py:32). El rol Lectura no existe en ningún plano (grep = 0). `require_role` valida y **descarta** al usuario: ningún endpoint de config sabe quién hizo el cambio (rbac.py:71-84, issue #72). `POST /chat/completions` no gatea rol: dual-auth propia (chat.py:744-782).

**Multi-tenant / RLS (fundación 013, dormida).** RLS `ENABLE`+`FORCE` con policy `tenant_isolation` sobre 13 tablas + governance_profiles + tenants — pero (a) la policy permisiva `tenant_isolation_bootstrap` deja pasar todo sin GUC, con mandato escrito *«la spec 017 DEBE eliminarla al cablear el GUC por request»* (010_multitenant_foundation.py:33-38,82-84); (b) `basa_admin` es SUPERUSER y bypasea RLS **siempre**, incluso FORCE (010:27-31; database.py:11). El runtime está listo (`tenant_context`, GUC por transacción — database.py:40-76) pero el único caller de producción es el escritor de auditoría del gateway (gateway.py:901). El JWT no lleva tenant; `get_db` no setea nada; toda la API de gestión corre bajo la policy bootstrap.

**Credenciales sk-basa: 3 planos, 3 criterios.** `expires_at` se setea al crear (keys.py:202) y se enforcea en **1 de 3** planos: el motor byok lo SELECTea y jamás lo evalúa (custom_auth.py:73 vs :266-299 — una key vencida y activa sigue autenticando), el Playground valida `key_hash`+`is_active` sin expiry (chat.py:750-751), solo la atribución de `/gw` filtra vencidas (gateway.py:560-570). Y `engine_key_token` persiste **la sk-basa entera en claro, indexada** (keys.py:192-206; models/budget.py:51) — el docstring dice «first 10 chars» y miente (ai_engine_client.py:131-132 vs :161-164). Un dump de `api_keys` regala todas las Connections.

**OIDC/SSO.** Cero: sin rutas, sin dependencia elegida (grep `oidc|authlib|msal` = 0). La única pieza es la vitrina «Próximamente» del frontend. Los usuarios sembrados usan el centinela `!seeded-client-no-login` con promesa escrita *«un login real llega con SSO/auth hardening (spec 017)»* (onboarding.py:30, passwords.py:62). El punto de enchufe natural: un callback que termine emitiendo **el mismo JWT** de `create_session_token` (session.py:30-37) — todo lo aguas abajo queda intacto.

**Licencias.** `feature_flags` existe dentro de la licencia firmada Ed25519, con `feature_enabled` fail-closed («ausente = OFF») y **cero consumidores** (token.py:111-113). Las licencias emitidas hoy van con `flags=[]`. El seat es la Connection activa, no el User (seat_counter.py:20-32).

### El recorte sellado (JF, 13-ago-2026)

La 017 enunciada entera (matriz + auditor + Lectura + SSO MS **y** Google + cierre RLS completo + hardening) **no cabe en C2**. El recorte acordado:

1. **Matriz entera, operando SOBRE el shim**: se recablea `effective_roles`, NO se renombran los literales legacy de los 15 routers. El shim es el seguro de migración gate-por-gate.
2. **SSO solo Entra en C2**; Google fast-follow C3; **password login = fallback permanente** (el posicionamiento air-gap lo exige: en sede sin salida, Entra/Google no existen).
3. **RLS partido**: C2 entrega tenant claim + GUC cableado por request + tests con rol NOSUPERUSER. El DROP de `tenant_isolation_bootstrap` y el flip NOSUPERUSER van como **migración gateada por env para el release siguiente**, coordinada con Factory (tocan compose/perfiles y la sede Cámara no tiene acceso remoto).
4. **Hardening = lista CERRADA de 4**: rate-limit+lockout del login, auditoría de auth events, `expires_at` unificado, cifrar `engine_key_token`. Todo lo demás, diferido con nombre (ver Out of scope).

### Deslindes y costuras

- **Con la 018 (PR #192)**: los auth events de esta spec caen en la clase `security_events` (365 d) del clasificador único de la 018 (su FR-002) — esta spec **emite**, la 018 **clasifica y purga**. El contrato de identidad de jobs batch (018 FR-006, `tenant_context`) es el mismo que esta spec exige a seeds y jobs. Y la decisión conjunta ya sellada en 018 FR-009: post-017, retención la escribe **solo tenant_admin**.
- **Con Cristian**: el #137 toca `custom_auth._IDENTITY_SQL` — el corazón fail-closed del plano motor que esta spec también toca (FR-017); el #147 crea un router que nace con `require_role` legacy. **Precondición de tasks: orden de merge acordado con Cristian antes del 24-ago** (esta spec se rebasa sobre ellos, o ellos sobre esta — pero decidido, no descubierto en semana 1). Con la 036: nada de esta spec toca políticas de contenido.
- **Con la 037 (wizard, Cristian) y el perfil de cliente (Falime)**: pedido ya cursado en Slack (13-ago) — el schema del perfil v1 reserva un bloque opcional `sso`. El wizard **escribe la config**; la licencia **autoriza el uso** (FR-010). El perfil configura, la licencia autoriza.
- **Con la 021**: esta spec es el **primer consumidor** de `feature_enabled` — estrena el mecanismo que la 021 dejó listo.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - La matriz definitiva: el auditor deja de poder editar lo que audita (Priority: P1)

Como responsable de compliance del cliente, quiero que el rol Auditor sea de solo-lectura real (con la única excepción de resolver revisiones humanas), que exista un rol Lectura para dar acceso a dashboards sin regalar escritura ni gasto, y que cada cambio de configuración registre **quién** lo hizo — porque hoy el mismo rol que audita la retención puede editarla, y ningún cambio de config tiene autor.

**Why this priority**: es la deuda RBAC nombrada por el propio código («transicional hasta el refactor RBAC de 017») y la promesa del roadmap piso 0 (rol Lectura). Sin matriz sellada, la 018 no sabe quién escribe retención y el rol Auditor es una mentira vendible.

**Independent Test**: harness de matriz rol×endpoint (Foundational, semana 1) que recorre TODA la matriz declarada en esta spec y falla ante cualquier gate desalineado. Se puede entregar y demostrar sin SSO ni RLS.

**Acceptance Scenarios**:

1. **Given** un usuario `compliance_officer`, **When** intenta `PUT /compliance/retention` (o cualquiera de sus 8 escrituras actuales salvo resolver human reviews), **Then** recibe 403 y el intento queda auditado con actor.
2. **Given** un usuario `compliance_officer`, **When** resuelve una human review (aprobar/rechazar), **Then** la operación procede — es su única escritura, deliberada y nombrada.
3. **Given** un usuario con el rol nuevo `lectura`, **When** consulta dashboards/monitor/reports/health, **Then** ve datos; **When** intenta cualquier mutación o `POST /chat/completions` con su JWT, **Then** 403.
4. **Given** cualquier mutación admin (alta de key, cambio de guardián, edición de policy), **When** se ejecuta, **Then** el evento durable registra el actor (user id + rol), no solo el hecho.
5. **Given** una instalación existente (Cámara) con usuarios `compliance_officer`, **When** se actualiza a esta versión, **Then** nadie pierde acceso de lectura y el cambio de matriz queda descrito en la nota de release — sin migración de datos de usuarios.

---

### User Story 2 - SSO Entra: el cliente entra con su identidad corporativa, y la licencia lo autoriza (Priority: P1)

Como IT del cliente instalado, quiero que mis usuarios entren con su cuenta de Microsoft Entra (la misma del resto de sus herramientas) sin que Basa guarde sus contraseñas, entregando solo 3 datos en la instalación (directory/tenant ID, client ID, client secret) y registrando la redirect URI en MI IdP. Y como negocio, quiero que SSO sea una capacidad **vendible**: activa solo si la licencia firmada la incluye.

**Why this priority**: promesa del roadmap piso 0 («SSO escalonado MS+Google») y requisito típico de compra enterprise. Además estrena el contrato de proveedor: Google en C3 debe ser «un módulo más», no otro refactor.

**Independent Test**: login E2E contra el tenant Entra de prueba (encargo a DevOps, 13-ago) que termina en el mismo JWT de sesión que el login local; con el flag de licencia apagado, la superficie SSO desaparece y el login local sigue intacto.

**Acceptance Scenarios**:

1. **Given** un tenant con SSO Entra configurado y licencia con flag `sso`, **When** un usuario existente entra por Entra, **Then** termina con la misma sesión (mismo formato de JWT, con tenant claim) que si hubiera entrado por password.
2. **Given** un usuario sembrado con centinela `!seeded-client-no-login` cuyo email coincide con la identidad de Entra, **When** entra por SSO, **Then** se activa ese mismo User (sin duplicar) y no consume seat por existir.
3. **Given** una identidad de Entra sin User previo, **When** entra por SSO, **Then** se aprovisiona JIT con rol `client` pasando por el mismo camino de alta (seat gate incluido).
4. **Given** el IdP caído o una sede sin salida a internet, **When** un usuario intenta entrar, **Then** el login local por password funciona igual que hoy — SSO nunca es el único camino.
5. **Given** una licencia sin el flag `sso` (p. ej. la de la Cámara, `flags=[]`), **When** alguien consulta o intenta iniciar el flujo SSO, **Then** la capacidad está apagada fail-closed (la config del tenant puede existir; no se usa), sin re-emisión de licencia requerida para seguir operando.

---

### User Story 3 - El aislamiento deja de ser decorativo: tenant en la sesión, GUC por request (Priority: P2)

Como operador del producto, quiero que cada request de la API de gestión corra con su tenant inyectado en la base (el GUC que la fundación 013 dejó listo), y que la suite pruebe el aislamiento **como va a ser** (sin policy bootstrap, sin superuser) — para que el drop de la policy en el release siguiente sea un flip verificado y no un salto de fe.

**Why this priority**: P2 porque no cambia comportamiento visible en single-tenant, pero es la mitad C2 del mandato escrito de la migración 010, y sin tenant claim el resto de la spec (SSO, auditoría con actor) nacería emitiendo sesiones incompletas otra vez.

**Independent Test**: harness de CI que corre la suite de aislamiento contra una base con `tenant_isolation_bootstrap` dropeada y un rol NOSUPERUSER — verde = el mundo post-flip funciona; se entrega sin activar nada en producción.

**Acceptance Scenarios**:

1. **Given** un login exitoso (local o SSO), **When** se emite la sesión, **Then** el JWT lleva el tenant del usuario.
2. **Given** cualquier request autenticada de la API de gestión, **When** toca la base, **Then** la transacción corre con `app.current_tenant` seteado desde la identidad — cero endpoints exentos salvo los pre-auth (login, health).
3. **Given** el harness post-flip (sin bootstrap, NOSUPERUSER), **When** un usuario del tenant A consulta recursos, **Then** las filas del tenant B no aparecen (0 filas, no error).
4. **Given** un token emitido antes de esta versión (sin tenant claim), **When** llega durante su ventana de vida (≤24 h), **Then** se acepta con el tenant por defecto de la instalación y la sesión siguiente ya nace completa — rotación natural, sin corte de servicio.
5. **Given** los escritores batch (seeds, jobs), **When** corren en el mundo post-flip del harness, **Then** escriben vía el contrato de identidad batch (el mismo del 018 FR-006) y no dependen de la policy bootstrap.

---

### User Story 4 - Hardening de identidad: la lista cerrada de 4 (Priority: P2)

Como responsable de seguridad del cliente, quiero que el login resista fuerza bruta y deje rastro, que una credencial vencida no autentique en **ningún** plano, y que un dump de la base no regale las Connections — los cuatro agujeros con evidencia localizada, y solo esos.

**Why this priority**: P2 porque cada ítem es un quick-win con evidencia `path:line` ya localizada; el riesgo del capítulo es el scope creep, y por eso la lista es CERRADA.

**Acceptance Scenarios**:

1. **Given** N intentos fallidos consecutivos contra una cuenta (umbral definido en tasks), **When** llega el intento N+1, **Then** lockout temporal con respuesta uniforme (sin oráculo de existencia de usuario) y evento auditado.
2. **Given** cualquier evento de auth (login ok/fail, lockout, bootstrap del primer admin, cambio de password), **When** ocurre, **Then** queda en la auditoría durable como clase `security_events`, con actor donde exista.
3. **Given** una sk-basa con `expires_at` vencido y `is_active=true`, **When** se usa contra byok del motor, el Playground o `/gw`, **Then** los TRES planos la rechazan con el mismo criterio.
4. **Given** un dump de la tabla de keys, **When** se inspecciona, **Then** no contiene ninguna sk-basa en claro (el token del motor está cifrado; el flujo que consulta gasto lo descifra en el camino).

---

### Edge Cases

- **Instalación cuyo único no-client es un Auditor**: con `compliance_officer` read-only, si siguiera probando «dueño» en el bootstrap, la instalación quedaría con dueño probado pero sin nadie capaz de crear un admin. Por eso deja de probar dueño (FR-002) — y la ventana de bootstrap se re-verifica con la matriz nueva.
- **SSO con email que colisiona con un User activo de otro camino**: matching por email SOLO activa centinelas o enlaza al User exacto; jamás re-asigna rol ni tenant por venir de Entra.
- **Lockout y SSO**: el lockout aplica al camino password; un usuario lockeado localmente puede seguir entrando por SSO (identidad delegada al IdP) — y ambos eventos quedan auditados.
- **Licencia con flag `sso` que expira o se degrada**: la capacidad se apaga fail-closed en caliente (mismo comportamiento que el resto del gate 021); las sesiones ya emitidas viven su exp natural.
- **Token viejo sin tenant claim** el día del release: ventana ≤24 h con tenant por defecto (single-tenant hoy); documentado en release notes. En el mundo post-flip esa tolerancia desaparece (el harness lo prueba).
- **`config` SSO escrita pero rota** (secret inválido, IdP mal apuntado): el flujo SSO falla con error claro y auditado; el login local no se ve afectado — fail-closed del módulo, no del login.
- **Purga 018 vs auth events**: los eventos de auth son `security_events` (365 d) — la 018 los purga por edad como a cualquier clase; nada de esta spec crea filas inmortales nuevas (la única cadena inmortal sigue siendo `model='license'`).

## Requirements *(mandatory)*

### Functional Requirements

**Capítulo A — Matriz RBAC definitiva (sobre el shim)**

- **FR-001**: La matriz canónica rol×superficie queda definida EN esta spec (tabla en `plan.md`/`tasks.md` derivada de este contrato): roles canónicos `super_admin`, `tenant_admin`, `compliance_officer`, `client`, `lectura` (nuevo). Todos los cambios de autorización se implementan recableando `effective_roles` (rbac.py:36-55); los literales legacy de los 15 routers NO se renombran en este ciclo. `PERMISSIONS` y `ROLE_HIERARCHY` (rbac.py:9-34, código muerto) se eliminan.
- **FR-002**: `compliance_officer` pasa a solo-lectura con UNA excepción nombrada: resolver human reviews (aprobar/rechazar). Sus escrituras actuales (retención, DPAs, DSRs, consent, security policies, costs) pasan a `tenant_admin` — coherente con 018 FR-009. Deja de probar «dueño» en el bootstrap: `ROLES_QUE_PRUEBAN_DUENO` queda en `tenant_admin|super_admin` (users.py:32). Sin migración de datos: cambia la matriz, no las filas.
- **FR-003**: Rol `lectura`: acceso de consulta a dashboards, monitor, reports y health; CERO mutaciones; NO puede usar `POST /chat/completions` (el camino JWT del dual-auth gatea rol — hoy no lo hace, chat.py:744-782); NO prueba dueño; NO consume seat (el seat sigue siendo la Connection). Requiere migración del CHECK `ck_users_role` + `normalize_legacy_role` + shim + espejo frontend — las ~5 ediciones acopladas se listan en tasks como UN paquete.
- **FR-004**: Las mutaciones admin propagan el ACTOR: la dependencia de autorización inyecta el usuario al endpoint y los eventos durables de config registran quién (id + rol) además de qué (cierra issue #72). Prerequisito de credibilidad del rol Auditor.
- **FR-005**: Harness de matriz rol×endpoint como tarea Foundational (semana 1): test parametrizado que recorre la matriz completa declarada y falla ante cualquier gate que difiera — incluye los 15 routers y el camino JWT de chat.

**Capítulo B — SSO como contrato de proveedor; Entra primer módulo**

- **FR-006**: Se define un contrato de proveedor SSO extensible (tipo + config por tenant), registry-style como las capas 027: agregar un proveedor nuevo = implementar el contrato + alta en el registro, sin tocar el flujo común. Proveedor v1: Microsoft Entra (OIDC authorization code). La config vive EN el tenant (los 3 datos del cliente: directory/tenant ID, client ID, client secret cifrado con el precedente Fernet de la instalación) — el wizard 037 la escribe en el perfil; el schema del perfil reserva el bloque `sso` (pedido en Slack 13-ago).
- **FR-007**: El callback SSO termina emitiendo EL MISMO token de sesión que el login local (`create_session_token`, session.py:30-37), con el tenant claim de FR-011 — cero bifurcación de sesión aguas abajo.
- **FR-008**: Aprovisionamiento JIT mínimo: (a) matching por email a User existente — si es un sembrado con centinela `!seeded-client-no-login`, se activa ese mismo User sin duplicar y sin consumir seat por existir; (b) identidad nueva → alta con rol `client` por el MISMO camino de alta actual, seat gate incluido. Jamás re-asigna rol/tenant de un User existente.
- **FR-009**: El login local por password es fallback PERMANENTE, declarado en las docs vendibles: SSO nunca es el único camino (posicionamiento air-gap: en sede sin salida el IdP no existe). La caída del IdP o una config rota degradan SOLO el camino SSO, con error claro y auditado.
- **FR-010**: SSO se gatea por `feature_flags` DENTRO de la licencia firmada (flag `sso`), consumiendo `feature_enabled` (021, token.py:111-113) — primer consumidor del mecanismo, fail-closed «ausente = OFF». Flag apagado: superficie SSO oculta/inactiva, config del tenant puede persistir, login local intacto. Las licencias emitidas (Cámara: `flags=[]`) siguen operando sin re-emisión. *El perfil configura, la licencia autoriza.*

**Capítulo C — RLS partida: lo que entra en C2**

- **FR-011**: La sesión lleva tenant: el token incluye el tenant del usuario. Tokens previos sin claim se aceptan durante su vida restante (≤24 h) con el tenant por defecto de la instalación; después, claim obligatorio.
- **FR-012**: El GUC de tenant (`app.current_tenant`) se setea por request en TODA la API de gestión desde la identidad autenticada — generalizando el patrón hoy único del gateway (gateway.py:901) vía la infraestructura existente (database.py:40-76). Endpoints pre-auth (login, health) documentados como exentos.
- **FR-013**: La suite prueba el mundo post-flip ANTES del flip: harness de CI con `tenant_isolation_bootstrap` dropeada y rol de conexión NOSUPERUSER que corre los tests de aislamiento (cross-tenant = 0 filas) y los escritores batch (seeds y jobs vía contrato de identidad batch, el mismo de 018 FR-006). Verde obligatorio para cerrar la spec.
- **FR-014**: El DROP definitivo de la policy bootstrap + flip NOSUPERUSER del rol de conexión se entregan como migración gateada por env, apagada por defecto, para el release siguiente — coordinación Factory explícita en tasks (toca compose/perfiles; la sede no tiene acceso remoto). Esta spec la DEJA LISTA y probada (FR-013); no la activa.

**Capítulo D — Hardening: la lista cerrada de 4**

- **FR-015**: Rate-limit + lockout en `/users/login`: umbral e intervalo definidos en tasks, respuesta uniforme sin oráculo de existencia, contadores en la infraestructura de rate-limit existente. Aplica al camino password; no bloquea SSO.
- **FR-016**: Auditoría de eventos de auth: login ok/fail, lockout, bootstrap del primer admin, cambio de password, login SSO y fallo SSO — como clase `security_events` del clasificador 018 (FR-002 de aquella), con actor donde exista. Hoy: cero rastro (grep audit en users.py = 0).
- **FR-017**: `expires_at` unificado en los 3 planos: byok del motor (custom_auth.py:266-299 — hoy lo ignora), Playground (chat.py:750-751 — hoy lo ignora) y `/gw` (ya lo evalúa) rechazan credencial vencida con el mismo criterio. ⚠️ toca `custom_auth.py` = coordinar merge-order con #137 ANTES (precondición de tasks).
- **FR-018**: `engine_key_token` deja de estar en claro: cifrado con el servicio de cifrado existente, descifrado solo en el camino que consulta gasto al motor (ai_engine_client.py:168-171); migración re-cifra las filas existentes; el docstring mentiroso (ai_engine_client.py:131-132) se corrige. Un dump de `api_keys` no contiene material de credencial utilizable.

### Key Entities

- **Rol canónico**: `super_admin | tenant_admin | compliance_officer | client | lectura` — la matriz de esta spec es la fuente única; el shim traduce hacia los literales legacy de los routers.
- **Config de proveedor SSO**: por tenant; tipo de proveedor + los 3 datos del cliente (directory/tenant ID, client ID, secret cifrado); escrita por el wizard/instalación, usable solo con licencia que lo autorice.
- **Sesión**: mismo token para login local y SSO; claims `{sub, role, username, tenant, exp}`; revocación efectiva sigue siendo `is_active` releído por request (documentado, no cambia).
- **Evento de auth**: clase `security_events` del clasificador 018; con actor.
- **Estado de lockout**: contador por cuenta con ventana; efímero (infra de rate-limit), no durable — lo durable es el evento.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El harness de matriz recorre el 100 % de los endpoints gateados (15 routers + chat JWT) y pasa; `PERMISSIONS`/`ROLE_HIERARCHY` tienen 0 referencias en el repo.
- **SC-002**: `compliance_officer` recibe 403 en sus 8 superficies de escritura actuales (salvo resolver reviews) y el test ancla del rol auditor queda actualizado y verde; `lectura` no puede ejecutar ninguna mutación ni chatear.
- **SC-003**: Login E2E contra el tenant Entra de prueba termina en sesión funcional idéntica a la local (mismo formato de token, tenant claim presente); con flag de licencia apagado, el flujo SSO no es alcanzable y el login local pasa la misma suite que hoy.
- **SC-004**: El harness post-flip (bootstrap dropeada + NOSUPERUSER) corre la suite de aislamiento en verde: cross-tenant = 0 filas, seeds y jobs escriben vía contrato batch.
- **SC-005**: N+1 intentos fallidos producen lockout con evento auditado; una key con `expires_at` vencido es rechazada en los 3 planos (test por plano); un dump de la tabla de keys no contiene ninguna sk-basa en claro.
- **SC-006**: Todos los eventos de auth enumerados en FR-016 aparecen en la auditoría durable con actor, y caen en la clase `security_events` del clasificador 018.
- **SC-007**: Cero regresión funcional para la instalación viva: la suite completa actual pasa sin cambios de datos; el cambio de matriz queda descrito en release notes.

## Out of scope (diferido con nombre)

- **Google SSO** → C3, como segundo módulo del contrato FR-006 (el contrato se diseña para eso; no se implementa ahora).
- **Revocación server-side, refresh tokens, jti, token fuera de localStorage** → diferidos; la revocación efectiva documentada es `is_active` por request.
- **Rename del vocabulario legacy en los 15 routers** → el shim queda como capa de traducción consagrada; el rename cosmético no compra nada en C2.
- **DROP de la bootstrap + flip NOSUPERUSER activados por defecto** → release siguiente, migración env-gated (FR-014 la deja lista y FR-013 la deja probada).
- **Multi-tenant «real»** (activar el aislamiento del seat gate pasando tenant real, scoping de listados más allá de RLS, semántica propia de super_admin) → despierta cuando haya segundo tenant; hoy contradiría la asunción sellada de la 036 («una instalación = un cliente fijo»).
- **DSAR (#62) y todo lo de retención** → 018 (PR #192) y Parte 5 del BRIEF de Cristian.
- **MFA, SCIM/provisioning masivo, mapeo de grupos del IdP a roles** → ni C2 ni C3 comprometidos; se anotan como futuros consumidores del contrato FR-006.

## Assumptions

- Instalaciones vivas son single-tenant (Cámara); la ventana de rotación de tokens de 24 h con tenant por defecto no rompe a nadie.
- El tenant Entra de prueba llega de DevOps antes del 24-ago (encargo cursado 13-ago); sus credenciales van a custodia estándar de DevOps — jamás por chat; a la spec solo llegan dominio/directory ID/emails de test.
- La infraestructura de rate-limit existente (Redis) está disponible en todos los perfiles de deploy donde hay login.
- El equipo de Jeff implementa (regla JF 13-ago); Cristian hace gate de review de seguridad; el manager gatea y mergea.

## Dependencies

- **018 (PR #192)**: clasificador de clases de fila (FR-002 de aquella) para los auth events; contrato de identidad batch (su FR-006); decisión conjunta FR-009 (retención = tenant_admin) ya reflejada aquí en FR-002.
- **Cristian #137/#147**: orden de merge sellado antes del 24-ago — precondición de tasks (FR-017 toca `custom_auth.py`; #147 nace con matriz vieja).
- **037/perfil (Cristian/Falime)**: bloque `sso` opcional reservado en el schema del perfil v1 (pedido en Slack 13-ago; confirmar al abrir el PR de la 037).
- **DevOps**: tenant Entra de prueba (24-ago).
- **Gate de producto (JF), 3 confirmaciones antes del 24-ago**: (1) Auditor read-only con única excepción reviews y sin probar dueño; (2) rol `lectura` con la superficie propuesta (no chatea, no seat, no dueño); (3) SSO gateado por flag de licencia firmada — primer consumidor de feature_flags; la Cámara queda con SSO apagado sin re-emisión.
