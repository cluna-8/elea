# Diagnóstico técnico (evidencia file:line) — insumo para plan.md de la 043 y la 044

Verificado en código el 2026-09-08 sobre `cluna-8/elea` main (`81aceb9`) y `cluna-8/elea-installer`.
Nada de esto está implementado; es solo diagnóstico.

## 1. Memoria de chats compartida (043 US1 / 044 US1)

- Sesión por cookie con identidad completa (`id, username, role, email`): `client/server.js:47-77`. Se usa SOLO en `/api/models` (:296), `/api/user/current` (:263) y chat directo (:635).
- Única credencial de servicio hacia el motor de documentos: `client/server.js:23` (`ANYTHINGLLM_API_KEY`), inyectada en `anythingllmFetch` (:149-159).
- Endpoints SIN guard de sesión y sin filtro por usuario: `/api/workspaces` (:323), `/api/workspaces/:slug` (:333), `/api/workspaces/:slug/messages` (:347), `/api/workspaces/create|delete|settings|upload` (:388-601), `/api/threads/*` (:471-524). Líneas exactas para el hotfix de guard: 323, 333, 347, 388, 443, 459, 471, 486, 499, 512, 527, 590.
- `/api/chat` con slug (:616-632) exige sesión pero usa el slug del body sin verificar pertenencia.
- Front auto-selecciona `workspaces[0]`: `client/public/index.html:792-799`, carga historial en :825.
- Ninguna asociación workspace↔usuario en backend (`backend/src/models/user.py:74-125` no la tiene; `engine_user_id` :92 apunta al motor de IA, no al de documentos), ni en Redis (el `client` no lo tiene como dependencia: `elea-installer/docker-compose.yml:151-170`), ni en el motor de documentos (single-user; compose :137-149 no activa multiusuario; imagen `latest` sin pin :138).
- `create-tester.sh` (:11-33) crea usuario + presupuesto en Guardian; nada en el motor de documentos.
- Spec 040 decía "Sin sesión no se ve ningún workspace ni historial ajeno" (`specs/040-cliente-rag-elea-completo/spec.md:76`) — incumplido.

## 2. Enmascarado no determinista (043 US3 / 044 US3)

- `PlaceholderMap.__init__`: nonce `uuid4().hex[:4]` por instancia — `litellm/extensions/sentinel_guardian_policy.py:704`; `placeholder_for` memoiza por valor exacto (:710) pero índice por tipo (:712); formato `[TIPO_idx_nonce]` (:714). El parámetro `nonce` existe y ningún call-site lo pasa.
- Un `PlaceholderMap()` nuevo por request: motor `sentinel_guardrail.py:620`; backend `backend/src/api/gateway.py:468` (y :285, :400 para preview).
- Cliente trocea a 4000 chars por líneas (`client/server.js:191, 198-212`), un `POST /gw/inspect` por trozo (:164-182, :221-226) con body `{text, tool}` — sin id de documento ni slug (el slug existe en :527-530 pero no se propaga). Conteos por trozo "desde 0" (:227-229).
- `/gw/inspect`: `backend/src/api/inspect.py:197-270`, llama `gateway.evaluate_request_policy` (:236-239).
- Regexes de placeholder que hay que respetar: `sentinel_guardian_policy.py:59-71` (`PH_TYPE_RE`, `PLACEHOLDER_TOKEN_RE`, `PH_TAIL_RE`, `MAX_CARRY=48`). Consumidor: `gateway.py:527-534` (`_entity_counts`).
- Bóveda 042: flag :779-780, clave `sentinel:pii_vault:<placeholder>` :781/:808, TTL :782, escritura :790-819, lectura :822-855. Scope global (sin tenant/workspace en la clave). Unmask en `sentinel_guardrail.py:637-650`.
- Constitución I / C1: `sentinel_guardian_policy.py:17-37`; precedente de escalado `specs/042-.../CHANGELOG.md:65-75`.
- Detección PERSON: `presidio-analyzer/conf/es.yaml` (`es_core_news_md`, `low_confidence_score_multiplier: 0.4` para PERSON), sin umbral de score (`presidio-analyzer/app.py:105-118`, `presidio_analyze` :593-643). Mitigación existente: `custom_names` deny_list (:550-556).
- Diseño elegido (08-sep): **nonce/derivación por documento** (opción A del informe). No se toca C1.

## 3. `license` y `chat-ui` como modelos (043 US4 / 044 US2)

- `license`: escrito por `backend/src/licensing/audit_events.py:266` (`model="license"`, cost 0). Excluido en compliance (`compliance.py:428,438`), reports (`reports.py:147`), analytics-capas (`analytics.py:94,114`); NO excluido en `analytics.py:219-234` (desglose por modelo) ni `costs.py:135-150` (`top_models`). Render: `DashboardPage.tsx:281`, `CostsPage.tsx:329`.
- `chat-ui`: `/gw/inspect` audita la superficie de la llave como `model` — `inspect.py:216` (`_superficie`, :123-137) → :247 `gateway._audit(ident, superficie, ...)` → `gateway.py:1029,1094` → `AuditService.log_transaction(model=...)`, cost 0.0 (:1096). El instalador crea las llaves de servicio con `tool_type: "chat-ui"` (`elea-installer/install.sh:~146`).
- Otros valores no-modelo en la columna: `"desconocido"` (`litellm/extensions/custom_auth.py:299`).

## 4. Cuentas de servicio como usuarios (043 US4 / 044 US4)

- `elea-installer/install.sh:~130-157`: `create_service_key()` → `svc.anythingllm-provider` / `svc.rag-masking` (users role `client`) + llaves `anythingllm-provider` / `rag-masking`.
- `GET /users` devuelve `db.query(User).all()` — `backend/src/api/users.py:390-392`. Sin flag `is_service` en `backend/src/models/user.py`.
- Consumen asientos (spec 021, `backend/tests/integration/test_seat_gate_users.py`).

## 5. Atribución de gasto (043 US2 / 044 US2)

- Enmascarado: `client/server.js:166-170` con `MASKING_VIRTUAL_KEY` global (:24) → `inspect.py:204` `_resolve_attribution` → identidad = `svc.rag-masking` → `gateway.py:1099-1101`.
- Chat RAG: `client/server.js:616-632` vía motor de documentos con `ANYTHINGLLM_API_KEY`; el motor de documentos llama al motor de IA con `PROVIDER_KEY` (`install.sh:~162-166`, `update-env`) → `custom_auth.py:411-430` identidad = `svc.anythingllm-provider`.
- Chat directo (bien atribuido): `client/server.js:635-638` con JWT.
- Cero soporte de end-user: grep `end_user|end-user|customer` en `backend/src` y `litellm/extensions` = 0. `AuditService.log_transaction` (`audit_service.py:395-513`) solo `user_id`. Presupuesto por `user_id` de la llave: `custom_auth.py:141-143`, gate 402 :365-385.
- El Hub muestra presupuesto con sesión admin (`client/server.js:280-291`, `ELEA_SERVICE_USERNAME=admin`) y NO lo aplica en `POST /api/chat` (:609-653). Deuda ya anotada: `specs/040-.../plan.md:75` (falta `GET /users/me/spend`).
- Vía preferida para el plan: recuperación de contexto en el motor de documentos + generación en el motor de IA con la identidad de la persona (atribución, 402 y desenmascarado en el mismo pedido).

## 6. Usuarios: edición y baja (043 US5 / 044 US4)

- Backend: `PUT /users/{id}` (:403) acepta rol/email/group/is_active pero es reemplazo completo (`schemas/user.py:21-29`, campos obligatorios); auditoría `AUTH_ROLE_CHANGED` :430-433. **No existe `DELETE`** (`_borrar_usuario` :344-354 es compensación interna). Roles válidos: `user.py:9`, CHECK :113-116.
- Frontend: `UsersPage.tsx:791-832` tabla; acciones solo "Asignar equipo" (:816-821) y "Restablecer contraseña" (:822-827). `api.updateUser` (`api.ts:737`) ya tipa `role` sin uso.

## 7. Branding (043 US6 / 044 US5)

- Sanitización solo en chat interno: `backend/src/api/chat.py:1616, 1677`; ausente en `gateway.py`.
- Campo público `litellm_params`: `chat.py:2260, 2277-2279`; `frontend/src/services/api.ts:936-940`; `docs/docs/api-reference/openapi.json:2355, 4580`.
- Guardián sembrado "(Presidio)": `backend/src/services/guardian_service.py:179-180`; `SecurityPage.tsx:10, 55, 371, 375, 678-679`; `guardians.py:85`.
- Título del panel: `frontend/index.html:7` ("Sentinel Secure AI Gateway"); branding existente en `frontend/src/services/branding.ts`, `deploy/branding/brand.*.json` (título no enganchado).
- Hub: 7 errores que nombran el motor de documentos — `client/server.js:326, 329, 396, 439, 567, 570, 624`; comentarios en `client/public/index.html:592-593, 687, 818, 821, 838, 871, 893, 1031` (servido estático, :79).
- Instalador: mensajes `log "Esperando a AnythingLLM..."` (`install.sh:~99-106`); `docker compose logs engine` muestra banner del motor (`LITELLM_LOG=INFO`, compose :59). Nombres de contenedor ya neutros (compose :10-153).
- Gate anti-fuga existente a extender: `docs/COORDINATION-028-extension-productizacion.md:62, 91`; `/gw/whoami` ya usa vocabulario cerrado (`inspect.py:143-163`).
