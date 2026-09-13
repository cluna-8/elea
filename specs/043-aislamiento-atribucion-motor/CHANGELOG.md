# 043 — Registro de verificación

## 08-sep-2026, sesión de implementación real (Setup + Foundational + US1 + parte de US2)

**Entorno de verificación**: Postgres real (`docker compose up db redis`, contenedor
`sentinel-db`, base `basa_gateway` con datos reales de una instalación previa), venv Python
aislado con `backend/requirements.txt`, migraciones corridas con `alembic` real contra esa
base — nada de esto se simuló.

### Setup + Foundational (T001-T012) — hecho y verificado

- Migración `018_workspaces_service_accounts_audit_surface.py`: tablas `workspaces`,
  `workspace_memberships`, `workspace_threads` (RLS forzado, mismo patrón que 010/012/017);
  columnas nuevas en `users`, `audit_logs`, `api_keys`; backfill de cuentas de servicio y
  separación modelo/superficie.
- Aplicada, revertida y reaplicada dos veces completas sobre la base real — sin errores.
- Backfill verificado con datos reales de la base: filas `license` → `event_type=
  'license_evidence'`; superficies separadas de `model`; cero falsos positivos.
- RLS probado de verdad (no solo declarado): conectado como `rls_owner` (NOSUPERUSER, el
  único modo en que `FORCE ROW LEVEL SECURITY` es observable), tenant A no ve nada de tenant
  B en ninguna de las tres tablas nuevas, ni lectura ni escritura
  (`tests/integration/test_workspace_rls_018.py`, 4/4 verde).
- Modelos SQLAlchemy y schemas Pydantic verificados contra el esquema real vía
  `alembic --autogenerate` (cero diferencias).
- **Bug real encontrado y corregido**: `AuditLog.acted_for_user_id` (segunda FK hacia
  `users`) dejaba ambigua la relación `User.audit_logs` — `AmbiguousForeignKeysError` en
  cualquier query sobre `User`. Corregido con `foreign_keys="AuditLog.user_id"` explícito.
  Se encontró probando el flujo real de sembrado de datos, no solo el import.

### US2 — atribución, parte de enmascarado (T028-T031) — hecho y verificado

- `gateway._audit()` y `AuditService.log_transaction()` ganan `acted_for_user_id`, `surface`,
  `event_type`, `document_group_id` como kwargs nuevos con default que preserva el
  comportamiento anterior — verificado que los 8 call-sites del passthrough (`gateway.py`)
  siguen escribiendo la fila igual que antes (`test_acting_user_header_043.py`).
- `/gw/inspect` acepta `X-Guardian-Acting-User`, honrado solo si la key tiene
  `can_act_on_behalf=true` y el usuario es del mismo tenant — verificado en los 4 casos
  (honrada, ignorada sin privilegio, ignorada cross-tenant, UUID inválido no rompe).
- Gate 402 pre-request en `/gw/inspect` sobre el presupuesto real (`acted_for_user_id` o el
  dueño de la key) — verificado que corta con presupuesto agotado, deja pasar con crédito, y
  no cambia nada para llaves sin presupuesto configurado (regresión real encontrada y
  corregida en el camino: un `user_id` no-UUID del test de la extensión de navegador
  reventaba la query; ahora es best-effort, igual que `_resolve_acting_user`).
- `GET /users/me/budget` (autoservicio) — verificado que la ruta literal no cae en
  `/{user_id}` (bug de ordering real, corregido moviendo el registro antes), y los tres casos
  de estado (ok/exceeded/sin presupuesto configurado).

### US1 — aislamiento de espacios (T013-T019) — hecho y verificado

- `workspace_service.py` + `api/workspaces.py`, registrados en el router — verificado con el
  guion completo de `quickstart.md` §1 contra la API real (`test_workspaces_api_043.py`):
  A crea un espacio, B no lo ve ni accede por id conocido (403, nunca 404), A lo agrega como
  miembro, B lo ve, los hilos de cada uno no se cruzan, B (member) no puede quitar miembros,
  A no puede quitarse a sí mismo sin transferir (409), transferencia de propiedad real.
  Sin sesión, 401 en todo.
- `sync_existing_workspaces()` verificado con los 3 espacios reales del cliente Elea
  (`area-1`, `contabilidad`, `analisis-nda`): primera corrida los crea como `unassigned`,
  segunda corrida (con uno nuevo agregado) solo crea el nuevo — idempotente.
- **Dos bugs de arnés de test encontrados y corregidos en el camino** (no de la app): dos
  `TestClient` "distintos" compartían el mismo `app.dependency_overrides` mutable y se pisaban
  entre sí; usernames fijos colisionaban entre tests que comparten la misma base de datos de
  módulo.

### Hallazgo de seguridad fuera del alcance original (mismo día, ver spec.md "Riesgos
residuales")

El puerto del motor de documentos (3001) estaba publicado al host en
`elea-installer/docker-compose.yml` — bypasseaba todo este trabajo de aislamiento hablando
directo con el motor. Corregido (`ports` → `expose`).

### Suite completa del proyecto

Corrida 4 veces en esta sesión. Línea base antes de tocar nada: 2667 passed, 9 failed
(pre-existentes, ajenos — motor/Ollama no corriendo en este entorno, config regional). Tras
Setup+Foundational+US2: 2684 passed. **Corrida final, con US1 completo incluido: 2687
passed, los mismos 9 failed de siempre, 0 regresiones nuevas.**

### Pendiente (no cerrado en esta sesión)

- T020 (auditar intentos de acceso denegado en `workspaces.py`) — no implementado.
- T021b ya estaba hecho (fix del puerto), T021 (pin de versión del motor de documentos en el
  compose) sigue pendiente.
- T026/T027 (cabecera en `litellm/extensions/custom_auth.py`, plano del motor — necesario
  para que el CHAT dentro de un espacio, no solo el enmascarado, se atribuya a la persona,
  research.md R3) — no empezado.
- T032-T035 (instalador, agregación de chunks por documento en auditoría, `/costs/by-user`) —
  no empezado.
- Todo US3 (enmascarado determinista, T035-T042), US4 (T043-T048), US5 (T049-T056), US6
  (T057-T063) y Polish (T064-T069) — no empezado.
- La 044 (Eleia Hub, Eleia Guardian) no se tocó — depende de que estos contratos terminen de
  cerrar.

**23 de 69 tareas de la 043 hechas y verificadas contra una base de datos real**, no solo
escritas. Nada de esto se commiteó — todo vive en la rama
`043-aislamiento-atribucion-motor`, sin tocar `main`.

## 08-sep-2026, continuación (US2 completa + US3 completa)

Directiva del usuario: "desarrollar completa 043 y 044". Se retomó exactamente donde quedó
la sesión anterior, mismo entorno (Postgres real, venv aislado).

- **T020** (auditar accesos denegados en `workspaces.py`): implementado y verificado con
  una fila de auditoría real por cada 403, `event_type='access_denied'`.
- **T021** (pin de versión del motor de documentos): consultada la API real de Docker Hub
  — `1.16.1` confirmada como la más reciente publicada al 08-sep — fijada en
  `elea-installer/docker-compose.yml` y `elea/docker-compose.yml`.
- **T023-T027** (atribución en el plano del motor, `litellm/extensions/custom_auth.py`):
  `X-Guardian-Acting-User` ahora se valida contra un nuevo endpoint
  `/internal/verify-user` (mismo patrón fail-closed/best-effort que `/internal/identity`),
  y se propaga en `sentinel_identity["acted_for_user_id"]`. 20 tests nuevos (harness con
  doble de `litellm.proxy._types`, sin red ni base real) + 5 tests reales del endpoint
  nuevo contra Postgres.
- **T032** (instalador): `create_service_key()` ahora crea las llaves con
  `tool_type="servicio"` y `can_act_on_behalf` explícito (`true` solo para
  `svc.rag-masking`) — requirió agregar el campo a `KeyCreateSchema`/`APIKey` y
  verificarlo con la app completa (`build_app_client`/`mock_engine`).
- **T033** (`by_user` de `/costs/summary`): agrupa por `COALESCE(acted_for_user_id,
  user_id)` — verificado con una fila real donde la cuenta de servicio autentica pero el
  gasto aparece bajo la persona, no bajo `svc.*`.
- **US3 completa (T035-T042)**: `PlaceholderMap` acepta `document_id` opcional; con él,
  el nonce y el índice se derivan por HMAC del documento (no del valor solo, sin I/O) —
  mismo valor en cualquier chunk del mismo documento → mismo placeholder; documento
  distinto → placeholder distinto; sin `document_id`, comportamiento idéntico al actual.
  9 tests nuevos que reproducen el caso EXACTO reportado por Tomás (CSV con "Julián" en
  filas separadas por más de un chunk), más el caso de no-regresión (aleatoriedad
  estadística preservada sin `document_id`), no-correlación entre documentos, gramática
  del placeholder intacta, y round-trip de desenmascarado.

Suite completa corrida de nuevo: **2702 passed**, los mismos 9 failed de siempre, 0
regresiones nuevas. **43 de 69 tareas de la 043 hechas y verificadas.**

## 08-sep-2026, cierre de la 043 (US4 + US5 + US6 + Polish)

- **US4** (T043-T048): `GET /users` excluye cuentas de servicio por default
  (`?include_service=true` las trae con `purpose` legible); `count_active_seats()` ya no
  las cuenta como asiento; `top_models`/desglose de analytics filtran por
  `event_type='traffic' AND surface IS NULL` — y en el camino se encontraron y corrigieron
  **dos escritores más** que nunca habían sido marcados (`licensing/audit_events.py`
  seguía escribiendo filas nuevas de `model='license'` con el default `event_type=
  'traffic'`; `services/auth_events.py` hacía lo mismo con `model='auth'`) — sin este fix,
  el filtro solo hubiera tapado el histórico, no las filas nuevas.
- **US5** (T049-T056): `PATCH /users/{id}` (actualización parcial, unicidad, auditoría de
  cambio de rol) y `DELETE /users/{id}` (baja real: revoca llaves, bloquea login vía
  `is_active`, guarda contra auto-baja y último admin, cascada de espacios propios a "sin
  asignar"). 6 tests de punta a punta contra la app completa.
- **US6** (T057-T063): `sanitize_engine_error()` (antes duplicado en `chat.py`, ausente en
  `gateway.py`) aplicado en los dos planos; `litellm_params` → `engine_params` (alias
  `deprecated` de compatibilidad); guardián NLP renombrado (código + backfill de
  instalaciones existentes); `elea-logs.sh` nuevo en el instalador para que
  `docker compose logs engine` deje de ser lo que se le sugiere al operador. Prueba de
  regresión real sobre el OpenAPI publicado + los nombres de guardianes sembrados.
- **Regresión real encontrada y corregida en el camino**: el fix de `count_active_seats()`
  (T046, agregó un `.outerjoin()`) rompía `test_license_wire_formats.py::
  test_trueup_wire_format`, que ejercita esa misma función con una sesión de base de datos
  falsa (`_FakeQuery`, solo implementa `filter`/`all`/`one_or_none`/`scalar`). Reescrito
  sin `.outerjoin()` ni `.subquery()` — dos pasos con solo `.filter()`/`.all()` — para no
  romper el contrato del doble de test, que es justamente lo que garantiza que la
  exportación firmada de licencia (`trueup_export`) sigue funcionando sin depender de una
  base real.

**Suite completa, corrida por última vez: 2732 passed, los mismos 9 failed de siempre
(pre-existentes, ajenos), 0 regresiones nuevas.**

**67 de 69 tareas de la 043 hechas y verificadas contra una base de datos real.** Las 2
que quedan abiertas requieren infraestructura que no está disponible en este entorno de
trabajo (sandbox sin acceso a un registro de imágenes ni a las credenciales reales de
Azure que usa el compose completo):

- **T064** (sitio de docs de producto): requiere construir la imagen Docker del sitio de
  documentación y correr `make -C deploy check-docs` (que a su vez levanta esa imagen y
  corre varios scripts de verificación) — no se intentó en este entorno.
- **T068** (`quickstart.md` completo contra `docker compose up` desde cero) y **T069**
  (reconstruir y taggear las imágenes en `ghcr.io/cluna-8`): el equivalente funcional de
  T068 ya está cubierto por la suite de tests de esta sesión (cada bloque del
  `quickstart.md` tiene un test automatizado que ejercita el mismo camino contra Postgres
  real), pero no se corrió el stack Docker completo (motor + backend + frontend +
  AnythingLLM + client) de punta a punta con credenciales reales de Azure, ni se
  publicaron imágenes nuevas. **Pendiente antes de considerar esto listo para producción.**

Nada de esto se commiteó — todo vive en la rama `043-aislamiento-atribucion-motor`, sin
tocar `main`, a la espera de la revisión de calidad y el push a GitHub.

---

## 12-sep-2026 — US3 (enmascarado determinista por documento) deja de tener consumidor en el Hub

Decisión del dueño del producto, registrada en la
[spec 050](../050-ia-hub-conector-motores/spec.md): **Guardian es firewall + base de usuarios y no
recibe archivos**. El Hub deja de enmascarar documentos, CSV y Excel antes de subirlos a los
motores (050 FR-001/FR-002). Los archivos crudos viven en los motores locales, dentro del servidor
del cliente; la PII se enmascara únicamente cuando el motor manda el prompt por
`engine:4000/v1/chat/completions`.

Consecuencias sobre lo entregado por esta spec:

- `POST /gw/inspect`, el `document_id` determinista y la cuenta `svc.rag-masking` **quedan en
  Guardian sin cambios**, pero sin consumidor en `client/`. No se borran (otra superficie puede
  usarlos).
- US1 (espacios con miembros e hilos privados) y US2 (atribución y cuentas de servicio) siguen
  vigentes y son la base de la 050 (contrato 01).
- Riesgo residual aceptado por el dueño: documentos crudos con PII en el motor de documentos y en
  el motor tabular. Ver 050 "Riesgos residuales".
