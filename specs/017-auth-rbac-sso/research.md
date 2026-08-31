# Research — 017 Identidad con dientes

Fuente: mapa as-is verificado en fuente (workflow 6 agentes, 13-ago, ~876k tokens; `path:line` leídos en main @ 81ea8ce) + decisiones de producto selladas por JF el mismo día. Cero NEEDS CLARIFICATION.

## D1 — Matriz sobre el shim; PERMISSIONS muere

- **Decision**: toda la autorización se recablea en `effective_roles` (rbac.py:36-55) contra una fuente única nueva (`auth/matrix.py`, espejo del contrato `contracts/matriz-roles.md`); los literales legacy de los 15 routers NO se tocan en C2. `PERMISSIONS`/`ROLE_HIERARCHY` (rbac.py:9-34, cero consumidores) se eliminan.
- **Rationale**: el shim está marcado «transicional hasta el refactor RBAC de 017» y es el seguro de migración gate-por-gate; renombrar los 15 routers + frontend + 3 suites ancla de una vez no cabe junto a SSO (riesgo top del veredicto de tamaño). Código muerto que documenta en falso es peor que no tener nada.
- **Alternatives**: rename completo del vocabulario (blast radius inasumible en C2 — diferido con nombre); consagrar PERMISSIONS como fuente (estaba muerto Y desalineado — rehacerlo es más caro que la matriz nueva).

## D2 — OIDC: authlib, no msal

- **Decision**: **authlib** como única dependencia nueva — cliente OIDC genérico (authorization code + discovery `.well-known`) sobre el que se implementa el contrato de proveedor; Entra es config, no código especial.
- **Rationale**: FR-006 exige que Google (C3) sea «alta en el registro», no otra librería; msal es Microsoft-only y ataría el contrato al primer proveedor. authlib es framework-agnóstica, mantenida, y cubre auth code + validación de tokens sin traer medio SDK. Air-gap: viaja en la imagen, cero egress en reposo.
- **Alternatives**: msal (solo Entra — rompe el contrato); oauthlib pelada (bajo nivel, más código propio que auditar); implementación manual (jamás para crypto/OIDC).

## D3 — Config SSO: tabla por tenant, secret Fernet

- **Decision**: tabla `sso_providers` (tenant_id, provider_type, config JSONB, client_secret cifrado Fernet, enabled) bajo RLS — patrón GovernanceProfile (migración 012); en on-prem single-tenant colapsa a una fila.
- **Rationale**: la config es DEL cliente (sus 3 datos + su redirect URI) y el wizard 037 la escribe vía el bloque `sso` del perfil (sellado con Cristian/Falime 13-ago) — una tabla por tenant es lo que el perfil siembra. Precedente Fernet ya existe (`oauth_credential_ref`, 010:216-222).
- **Alternatives**: env por instalación (no gobernable por UI ni sembrable por perfil versionado; muere en multi-tenant cloud).

## D4 — JIT y el centinela

- **Decision**: matching por email: (a) User existente con centinela `!seeded-client-no-login` → se activa ESE User (sin duplicar, sin seat nuevo — el seat es la Connection); (b) email nuevo → alta `role=client` por el MISMO camino actual (seat gate incluido); (c) User activo existente → solo login, jamás re-asignar rol/tenant.
- **Rationale**: el centinela ya promete por escrito «un login real llega con la 017» (onboarding.py:30, passwords.py:62); duplicar Users rompería atribución y regalaría seats.

## D5 — Flag de licencia `sso` (primer consumidor de la 021)

- **Decision**: superficie SSO entera detrás de `feature_enabled('sso')` (token.py:111-113, fail-closed) — gate en el router de `sso/api.py` + botón del frontend condicionado. Config del tenant puede persistir con flag apagado.
- **Rationale**: decisión de JF (13-ago) + principio sellado públicamente con Cristian: «el perfil configura, la licencia autoriza». Cámara (`flags=[]`) sigue igual sin re-emisión.
- **Alternatives**: sin gate (contradice el principio recién sellado; quitar después algo ya usado es peor); re-emitir a Cámara ya (no lo pidió; el backup de la privada #65 sigue pendiente).

## D6 — Tenant claim y rotación

- **Decision**: `create_session_token` agrega `tenant`; `get_current_user` acepta tokens sin claim durante su vida restante (≤24 h) resolviendo al tenant default de la instalación, y lo registra. Sin jti/refresh (diferidos con nombre); la revocación efectiva sigue siendo `is_active` releído por request (documentado).
- **Rationale**: sin tenant en la sesión no hay GUC por request (FR-012) ni callback SSO completo (FR-007); la tolerancia de 24 h evita corte de servicio en el release (SC-007).

## D7 — GUC por request

- **Decision**: la dependencia de identidad setea `current_tenant_id` (ContextVar existente) y `get_db` inyecta el GUC por transacción — generalización del único caller vigente (gateway.py:901) con la infra ya lista (database.py:40-76). Endpoints pre-auth (login, health) exentos y documentados.
- **Rationale**: es el mandato escrito de la migración 010 (:33-38, «la 017 DEBE…»); hoy 0 endpoints de gestión lo setean.

## D8 — El flip queda listo, no activo

- **Decision**: migración `016_rls_strict` env-gated (`SENTINEL_RLS_STRICT=true`): DROP `tenant_isolation_bootstrap` + rol de conexión NOSUPERUSER. Apagada por default; se activa el release siguiente coordinado con Factory (toca compose/perfiles; la sede no tiene acceso remoto). El harness post-flip (fixture compartida con la 018) prueba ese mundo YA.
- **Rationale**: recorte sellado #3; activar sin ventana de coordinación rompería la instalación viva.

## D9 — Lockout y auth events

- **Decision**: contadores en Redis (infra de rate-limit existente), umbral 5 / 900 s por env, respuesta uniforme sin oráculo de existencia; lockout solo camino password (SSO delega en el IdP). Auth events (login ok/fail, lockout, bootstrap, password change, SSO ok/fail) emitidos como clase `security_events` vía el emisor durable — clasificador de la 018 los gobierna (365 d).
- **Rationale**: hoy CERO rastro de auth (grep audit en users.py = 0) y la ventana de bootstrap «el primero que llega gana» está documentada en el propio código (users.py:47-49).

## D10 — expires_at unificado y el token en claro

- **Decision**: (a) los 3 planos evalúan `expires_at` con el mismo criterio — motor byok (custom_auth.py:266-299, hoy lo ignora — ⚠️ tras merge-order #137), Playground (chat.py:750-751), /gw (ya lo hace); test por plano. (b) `engine_key_token` → Fernet con el servicio existente; descifrado solo en `get_key_spend` (ai_engine_client.py:168-171); data-migration re-cifra filas existentes y DROPea el índice (inútil sobre cifrado); docstring mentiroso (:131-132) corregido.
- **Rationale**: una key vencida y activa hoy autentica en 2 de 3 planos; un dump de `api_keys` regala todas las Connections — violación vigente de la Constraint 5.

## D11 — Fronteras y precondiciones

- **#137 (Cristian, región por tenant)**: toca `custom_auth._IDENTITY_SQL`. Precondición de la tarea de expires_at-motor: orden de merge sellado ANTES del 24-ago (esta rama se resentinel sobre él, o él sobre esta — decidido, no descubierto).
- **#147 (Cristian, router content_policies)**: nace con `require_role` legacy — al recablear la matriz, su router entra al harness como uno más (el shim lo traduce; cero cambios en su código).
- **018**: fixture post-flip compartida; auth events consumen su clasificador; FR-009 de la 018 (retención escribe tenant_admin) lo ejecuta esta matriz.
- **DevOps**: tenant Entra de prueba antes del 24-ago; credenciales a custodia estándar (jamás por chat); a la spec solo llegan dominio/directory-ID/emails de test. Hasta que llegue: IdP falso local (respuestas OIDC simuladas) — la construcción no se bloquea.
