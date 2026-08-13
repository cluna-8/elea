# Tasks: Identidad con dientes — matriz RBAC, SSO Entra, RLS partida, hardening de 4

**Input**: Design documents de `/specs/017-auth-rbac-sso/` (plan, research, data-model, contracts/matriz-roles + proveedor-sso, quickstart — sellados 13-ago; gate de producto JF sellado 13-ago: auditor read-only + reviews, `lectura` sin chat/seat/dueño, SSO por flag de licencia).

**Tests**: OBLIGATORIOS (DevFlow: código nuevo = tests nuevos en el mismo PR; codex-gate en cada PR con código — esta spec es TODA superficie de seguridad).

**Quién**: implementa el equipo de **Jeff 2** (coders Opus 5) DESPUÉS de cerrar el MVP de la 018 (US1); Cristian = gate de review de seguridad; el manager gatea y mergea.

**⚠️ Precondiciones externas (no arrancar la tarea marcada sin esto):**
- **[BLOQ-CRIS]** T024: orden de merge con #137 sellado (toca `custom_auth.py`) — el manager lo negocia antes del 24-ago.
- **[BLOQ-DEVOPS]** T018: tenant Entra de prueba (encargado 13-ago, deadline 24-ago). El resto de US2 se construye contra el IdP falso local — NO bloquea.

**Ramas/PRs**: ramas cortas desde main, PR < 400 líneas, un PR por fase/módulo. `Closes #NNN` en inglés donde aplique.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [ ] T001 Paquetes `backend/src/sso/` y módulos `auth/matrix.py`, `auth/lockout.py`, `services/auth_events.py` (esqueletos con docstrings de contrato) + alta de `authlib` pineada en requirements (única dependencia nueva — research D2).
- [ ] T002 [P] Envs nuevos (`BASA_LOGIN_MAX_ATTEMPTS`, `BASA_LOGIN_LOCKOUT_SECONDS`, `BASA_RLS_STRICT`) en `.env.example` + `make -C deploy docs-refs` en el mismo PR (el drift gate vigila).

## Phase 2: Foundational (bloquea todo)

- [ ] T003 `auth/matrix.py`: la matriz de `contracts/matriz-roles.md` como fuente única en código.
- [ ] T004 Harness FR-005: `tests/integration/test_role_matrix.py` — parametrizado sobre los 15 routers + chat-JWT contra la matriz; endpoint sin fila = rojo. PRIMERO en rojo contra el estado actual (documenta el diff), después verde con T006.
- [ ] T005 [P] Tenant claim (FR-011): `session.py` agrega `tenant`; `get_current_user` tolera tokens viejos ≤24 h con tenant default + registro. Test de rotación.
- [ ] T006 Recableado `effective_roles` sobre la matriz + borrar `PERMISSIONS`/`ROLE_HIERARCHY` + actor inyectado al endpoint (FR-004, cierra #72) — `require_role` devuelve el User; mutaciones admin auditan actor.
- [ ] T007 GUC por request (FR-012): dependencia de identidad setea `current_tenant_id`; `get_db` inyecta por transacción; pre-auth exentos documentados. Test: toda request de gestión corre con GUC seteado.

**Checkpoint**: PR Foundational. El harness en verde ES el criterio. Codex-gate. Merge del manager.

## Phase 3: US1 — La matriz definitiva (P1) 🎯

- [ ] T008 [US1] FR-002: recorte del auditor — 8 superficies a solo-lectura (excepción: resolver reviews), herencias a tenant_admin; `ROLES_QUE_PRUEBAN_DUENO` = {tenant_admin, super_admin} (users.py:32); actualizar `test_rol_auditor.py` en el MISMO PR.
- [ ] T009 [US1] FR-003: rol `lectura` — el paquete de ~5 ediciones acopladas como UNA tarea con checklist: migración `014_role_lectura` (CHECK) + `normalize_legacy_role` + shim + frontend (toLegacyRole/nav/labels) + `u.role` del SQL espejo (⚠️ NO editar custom_auth.py si T024 sigue bloqueada — el espejo interno `internal.py` va; el del motor espera).
- [ ] T010 [US1] Gate de rol en el camino JWT de chat (chat.py:744-782): `lectura` → 403; resto sin cambios. Test.
- [ ] T011 [US1] Auth events v1 (FR-016 parcial): bootstrap del primer admin + cambios de matriz auditados con actor.
- [ ] T012 [US1] UI: UsersPage refleja la matriz nueva (labels, rol lectura en el alta, copy del auditor que HOY admite «todavía no es read-only» se actualiza — por fin es verdad).

**Checkpoint**: PR US1 + quickstart §1-§2 en vivo. STOP & VALIDATE con el manager.

## Phase 4: US2 — SSO Entra tras el flag (P1)

- [ ] T013 [US2] Migración `013_sso_providers` + modelo (contrato proveedor-sso; secret Fernet, RLS).
- [ ] T014 [US2] `sso/registry.py` (contrato de proveedor) + `sso/entra.py` (authlib: authorize_url, exchange_code, discovery). Tests unitarios con respuestas OIDC simuladas.
- [ ] T015 [US2] `sso/api.py`: `/auth/sso/login` + `/auth/sso/callback` → `create_session_token` con tenant claim; **gate `feature_enabled('sso')`** en el router (primer consumidor 021); errores del IdP → auth event + camino local intacto (FR-009).
- [ ] T016 [US2] JIT (FR-008): matching por email (centinela→activar; nuevo→alta client por camino actual con seat gate; activo→solo login; jamás re-asignar). Tests de los 3 caminos + colisión.
- [ ] T017 [US2] Frontend: botón «Entrar con Microsoft» condicionado al flag (la vitrina 'Próximamente' de UsersPage.tsx:1003-1060 se vuelve real); config SSO del tenant en UI admin.
- [ ] T018 [US2] **[BLOQ-DEVOPS]** E2E contra el tenant Entra real (SC-003) + doc vendible de instalación SSO (los 3 datos + redirect URI en el IdP del cliente + fallback permanente declarado).

**Checkpoint**: PR(s) US2. Codex-gate obligatorio (superficie de auth nueva).

## Phase 5: US3 — RLS partida (P2)

- [ ] T019 [US3] Fixture post-flip: reusar/extender la de la 018 (`test_purge_post017.py`) como fixture común; suite de aislamiento `test_rls_post_flip.py` (cross-tenant = 0 filas, seeds/jobs por contrato batch) — FR-013/SC-004.
- [ ] T020 [US3] Migración `016_rls_strict` env-gated APAGADA (DROP bootstrap + NOSUPERUSER) + nota de coordinación Factory en `deploy/` (FR-014). Test: sin la env, el arranque es idéntico.
- [ ] T021 [US3] Seeds peligrosos bajo contrato batch: `guardian_service.py` (borra tabla sin filtro) y `policy.py` get_or_create — auditoría de que corren con `tenant_context` (costura con el hallazgo del research; NO cambiar su lógica, solo su identidad).

## Phase 6: US4 — Hardening, lista cerrada de 4 (P2)

- [ ] T022 [US4] FR-015: `auth/lockout.py` (Redis, umbral/env, respuesta uniforme sin oráculo) cableado a `/users/login`; solo camino password. Tests: N+1, expiración, uniformidad.
- [ ] T023 [US4] FR-016 completo: login ok/fail, lockout, password change, SSO ok/fail → clase `security_events`; verificación con el clasificador de la 018 mergeado.
- [ ] T024 [US4] **[BLOQ-CRIS]** FR-017: `expires_at` en el motor byok (custom_auth.py:266-299) + Playground (chat.py:750-751); /gw ya. Test por plano + test de contrato del espejo `_IDENTITY_SQL`.
- [ ] T025 [US4] FR-018: `engine_key_token` Fernet (migración `015_encrypt_engine_key`: re-cifrado + DROP índice), descifrado solo en `get_key_spend`, docstring corregido (ai_engine_client.py:131-132). Test: dump sin material en claro; `get_key_spend` sigue funcionando.

## Phase 7: Polish

- [ ] T026 [P] Docs vendibles: matriz de roles publicada + página SSO + release notes del cambio de matriz (SC-007) — el CHANGELOG canónico de la raíz es la fuente (regla del manager).
- [ ] T027 [P] ROADMAP-guardian: 017 en implementación; diferidos con nombre registrados (Google C3, revocación server-side, drop activo, multi-tenant real).

**Dependencias**: Setup → Foundational → US1 → US2 (necesita tenant claim T005 + matriz T006); US3 en paralelo con US2 tras Foundational; US4 al final (T024 además espera merge-order). La 018-US1 (purga MVP) va ANTES que todo esto en la cola de Jeff 2 — el clasificador de la 018 es dependencia de T023.
