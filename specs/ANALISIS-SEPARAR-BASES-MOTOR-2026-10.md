# Análisis (spike): separar la base del motor de la base del Guardian

**Fecha**: 2026-10-06 · **Rama**: `cluna-8/spike-separar-bases-motor` · **Tipo**: spike — conclusiones, no código.
**No abre spec ni numeración** (AGENTS.md: «Exploración ≠ spec»). Sus conclusiones alimentan, si el owner lo decide, una enmienda o una tarea de ensayo.

**Convención**: cada afirmación lleva `[verificado]` (leí el código/artefacto citado, o lo medí) o `[no verificado]` (inferencia, estimación o algo que solo se confirma ejecutando). `archivo:línea` sin prefijo = este repo. `instalador:` = `elea-installer` (solo lectura). `sentinel:` = `cluna-8/sentinel`, rama `origin/main` (solo lectura). `imagen:` = archivo leído dentro de las capas publicadas en el registro, sin Docker.

**Cómo se obtuvo la evidencia de la imagen** (sin Docker, sin tocar producción): manifiestos y capas por `curl` anónimo a `ghcr.io`, extrayendo un puñado de archivos de la capa `sha256:a73796f6…` (la del `.venv`: `litellm_proxy_extras/*.py`, `proxy_cli.py`, `utils.py`, `schema.prisma`, `check_migration.py`, `prisma_client.py`) hacia el directorio temporal de la sesión, que se borró al terminar. Las ruedas de `litellm-proxy-extras` se leyeron en memoria desde PyPI. En el repo de Sentinel solo corrí `git fetch origin` (actualiza refs remotas, no toca el árbol) y `git show`/`git grep` contra `origin/main`.

---

## Resumen ejecutivo

1. **El borrado es real y está en el código de la imagen de producción.** El arranque del motor ejecuta `prisma migrate deploy`; si la base no tiene su libro de migraciones (`_prisma_migrations`) pero sí tablas, crea un «baseline», calcula el diff *base viva → schema del motor* y **lo ejecuta**; ese diff contiene `DROP` de toda tabla que el motor no conoce (en la base compartida: `users`, `alembic_version`, `audit_logs`…). Además, **aunque el libro exista**, el mismo diff se ejecuta tras cualquier `migrate deploy` que haya aplicado migraciones pendientes — o sea, tras **subir la versión del motor**. [verificado, §1]
2. **La imagen de producción tiene ese código**: `ghcr.io/cluna-8/elea-guardian-engine` (las tres tags) = litellm 1.92.0 + `litellm-proxy-extras` 0.4.74. Pero **el instalador la consume por `:latest`, no por digest** (`instalador:docker-compose.yml:48`); lo que está fijado por digest es la imagen *base* dentro del Dockerfile (`litellm/Dockerfile:6`). [verificado]
3. **El backend NO lee ni escribe tablas `LiteLLM_*` por SQL.** Habla con el motor solo por su API HTTP. El acoplamiento por SQL es el **inverso y por defecto**: el motor lee tablas del backend (`api_keys`, `users`, `budgets`…) y escribe `audit_logs` con el cliente Prisma cuando comparten base. Ese camino ya tiene su reemplazo HTTP implementado (`SENTINEL_IDENTITY_URL`, `SENTINEL_AUDIT_URL`), usado por `deploy/docker/compose.prod.yml` pero **no por el docker-compose de desarrollo ni por el instalador**. [verificado, §2]
4. **Sentinel lo resolvió en su compose de producción** (base `sentinel_engine`, `ENGINE_DB`, `initdb`, las dos URL internas). Este repo ya hereda *exactamente* eso en `deploy/docker/` (idéntico, verificado por `diff`), pero el camino que **realmente instala Elea** (el instalador) y el de desarrollo siguen compartiendo base. [verificado, §3]
5. **Riesgo vivo hoy**: el servidor de Elea (instalado con el instalador) comparte base. Se dispara con la primera imagen publicada sobre un litellm más nuevo (el instalador la baja sola por `:latest`) o con cualquier restauración que pierda `_prisma_migrations`. Mitigación inmediata sin cambiar imagen: **copia completa antes de cada `./install.sh` y `DISABLE_SCHEMA_UPDATE=true` vía un `docker-compose.override.yml` en el servidor** (§5). [verificado por lectura de código; no ensayado]
6. **Recomendación**: separar en los tres frentes, con la producción **después** de un ensayo con Docker que pruebe la vuelta atrás (§4, §6). Nada de esto se ensayó aquí (sin Docker, por consigna).

---

## §1. Mecanismo del borrado

### 1.1 Qué hace `litellm_proxy_extras` al arrancar

El proceso `litellm --config …` (`docker-compose.yml:117`, `litellm/Dockerfile:9`) entra en `run_server` y, si hay `DATABASE_URL`, hace esto `[verificado: imagen:litellm/proxy/proxy_cli.py:1112-1181]`:

1. Si `DISABLE_SCHEMA_UPDATE` (env) o `general_settings.disable_prisma_schema_update` es verdadero → **no migra**: solo `check_prisma_schema_diff`, que corre `prisma migrate diff` y **loguea** el resultado, sin ejecutarlo (`imagen:litellm/proxy/db/prisma_client.py:686-710`, `imagen:litellm/proxy/db/check_migration.py:57-103`, `proxy_cli.py:1168-1169`).
2. Si no → `PrismaManager.setup_database(use_migrate = not use_prisma_db_push, use_v2_resolver = use_v2_migration_resolver)` (`proxy_cli.py:1179-1181`). El entrypoint de Elea no pasa ninguna de las dos banderas (`docker-compose.yml:117`; `litellm/Dockerfile:9`; `instalador:docker-compose.yml:47-51` ni siquiera define entrypoint, hereda el de la imagen) ⇒ **camino v1 con `migrate`**. [verificado]

El camino v1 (`imagen:litellm_proxy_extras/utils.py:680-927`):

| Paso | Qué hace | Línea |
|---|---|---|
| a | `prisma migrate deploy` contra `DATABASE_URL` | `utils.py:709-714` |
| b | Si la salida contiene `No pending migrations to apply` → **termina sin más** | `utils.py:726-730` |
| c | Si no (hubo migraciones aplicadas) → **«sanity check»**: `_resolve_all_migrations(…, mark_all_applied=False)` | `utils.py:733-736` |
| d | Si `migrate deploy` falla con `P3005` + «database schema is not empty» → loguea **«Database schema is not empty, creating baseline migration…»**, `_create_baseline_migration` (`migrate diff --from-empty --to-url` → `migrations/0_init/migration.sql`; `migrate resolve --applied 0_init`) y luego `_resolve_all_migrations(…)` (con `mark_all_applied=True`) | `utils.py:807-819`, `109-170` |
| e | `_resolve_all_migrations`: **`prisma migrate diff --from-url <DB viva> --to-schema-datamodel schema.prisma --script`** → archivo; **`prisma db execute --file <ese diff>`**; log **«✅ Migration diff applied successfully»**; luego marca todas las migraciones como aplicadas | `utils.py:267-390` (diff `:295-297`, execute `:357`, log `:370`) |

Esto es **exactamente la secuencia del incidente**: «Database schema is not empty, creating baseline migration» → «Migration diff applied successfully». [verificado: los dos textos están literales en `utils.py:811` y `:370`]

**Por qué borra**: `schema.prisma` de la imagen define 65 modelos, **todos `LiteLLM_*`** (`imagen:litellm/proxy/schema.prisma`; `grep '^model '` → 65, ninguno sin ese prefijo). El diff «DB viva → schema» trata cualquier tabla ajena (`users`, `alembic_version`, `audit_logs`, `api_keys`…) como sobrante y emite su `DROP TABLE`; `db execute` lo ejecuta. [verificado el mecanismo y el schema; que Prisma emite `DROP` para tablas fuera del datamodel **no lo ejecuté** — se deduce del incidente aportado (faltaban `users` y `alembic_version`) y de la reproducción de 2026-07-22 documentada en `git show f83a0e6` («reproducido 2 veces, determinístico») → `[verificado como evidencia documental; no re-ejecutado]`]

Otros dos caminos destructivos, **no usados por Elea** pero presentes: `--use_prisma_db_push` ⇒ `prisma db push --accept-data-loss` (`utils.py:924`, `:528`).

### 1.2 En qué versiones

`litellm-proxy-extras` es el paquete que trae `utils.py`. Barrido de ruedas de PyPI (leídas en memoria; `[verificado]` por presencia de cadenas en cada versión):

| extras | fecha | mensaje de baseline + `_resolve_all_migrations` | diff `--from-url` + «diff applied» | sanity check post-`deploy` | resolver v2 |
|---|---|---|---|---|---|
| 0.1.3 | 2025-04-05 | no | no | no | no |
| 0.1.7 | 2025-04-12 | **sí** | no | no | no |
| 0.2.0 → 0.2.19 | 2025-05-24 → 2025-09-20 | sí | **sí** | no | no |
| 0.3.0, 0.4.0 → 0.4.50 | 2025-11-01 → 2026-02-28 | sí | sí | **sí** | no |
| **0.4.74 (la de la imagen)** | 2026-06-06 | sí | sí | sí | **sí (opt-in)** |
| 0.4.90, **0.4.105 (última)** | 2026-08-28, 2026-10-04 | sí | sí | sí | sí (opt-in) |

Lectura: el baseline destructivo existe desde ~abril de 2025; el sanity check que lo extiende a las **actualizaciones** desde ≤ nov-2025; **sigue presente en la última publicada**, así que «actualizar el motor» no lo arregla. El resolver v2 (`--use_v2_migration_resolver`, solo bandera de CLI, sin variable de entorno: `proxy_cli.py:811-818`) **no llama a `_resolve_all_migrations`** (docstring `utils.py:505-516`) y es la defensa opt-in de upstream. Los bordes exactos de introducción (entre 0.1.3–0.1.7, 0.1.7–0.2.0, 0.2.19–0.3.0, 0.4.50–0.4.74) no se acotaron versión a versión `[no verificado]`. Si la última versión cambió el *default* a v2, tampoco `[no verificado]`.

### 1.3 Condiciones exactas (en la base compartida actual)

Sea **L** = existe `_prisma_migrations` con las migraciones del paquete aplicadas; **T** = hay tablas ajenas al schema del motor (las del backend).

| Caso | Condición | Qué pasa | Dispara el borrado |
|---|---|---|---|
| **Base nueva, motor primero** | base vacía → motor migra todo, crea L → después corre `alembic` | `migrate deploy` aplica; sanity check corre sobre una base solo con `LiteLLM_*` ⇒ diff vacío | **No**. Es el orden histórico de dev y el del instalador: `install.sh:67-75` espera al motor *healthy* antes de levantar el backend; `docker-compose.yml:119-120` (instalador) y `:226-228` (dev) lo exigen con `condition: service_healthy`. [verificado] |
| **Base nueva, `alembic` primero** | `alembic upgrade head` crea T antes de que el motor haya creado L → `migrate deploy` da `P3005` | baseline + diff ejecutado | **Sí** (la reproducción del 22-jul: «en una instalación fresca el backend gana la carrera»). En `deploy/docker/compose.prod.yml:131-132` el backend espera al motor solo en `service_started`, no `healthy` ⇒ la carrera existiría si compartieran base `[verificado el compose; la carrera no la ensayé]`. El backend corre `alembic upgrade head` en cada arranque (`backend/Dockerfile:19`, `instalador:docker-compose.yml:90`, `backend/src/main.py:21-39,64`). |
| **Actualización de la imagen del motor** | L existe, pero el nuevo litellm trae migraciones pendientes (trae más de las que la base tiene) | `migrate deploy` las aplica (no dice «No pending») → **sanity check ejecuta el diff** ⇒ `DROP` de T | **Sí, aun con L intacto** (`utils.py:726-736`). Solo se evita si **no** hay migraciones pendientes (mismas capas de litellm). [verificado por código; que Prisma imprima exactamente «No pending migrations to apply» cuando no hay pendientes lo asumo `[no verificado]`] |
| **Base restaurada** | la restauración deja T sin L (p. ej. restaurar solo tablas del backend, o un dump de otra base) | `P3005` ⇒ baseline + diff | **Sí**. Si el restore trae L completo y sin pendientes: no. |
| **Reinicio normal** | L completo, misma imagen | «No pending» ⇒ sale en `:726-730` | No |

Esto significa que **hoy el servidor de Elea no se está destruyendo en cada reinicio**: se destruye en el *próximo evento* de la tabla (imagen con migraciones nuevas o L perdido).

### 1.4 ¿La imagen de producción tiene ese código?

Sí. `[verificado]`:

- `ghcr.io/cluna-8/elea-guardian-engine` publica tres tags: `latest`, `2026-09-14`, `2026-09-17`. `latest` = `sha256:1928af9d1ef6…6189dafe` (abreviado; el completo sale de un `HEAD` al manifiesto de la tag) (= `2026-09-17`); `2026-09-14` = `sha256:ea73bd808368…126b915aa9` (abreviado).
- Las **21 primeras capas** (por `diff_id`) de las dos tags son idénticas a las de `ghcr.io/berriai/litellm@sha256:80ea654c…` (la base fijada en `litellm/Dockerfile:6` y `docker-compose.yml:70`); las dos capas finales son `COPY config.yaml` y `COPY extensions/` (historia de la imagen). Entonces el código del migrador es el de la base.
- Esa base contiene `litellm-1.92.0.dist-info` y `litellm_proxy_extras-0.4.74.dist-info`; creada 2026-06-30; entrypoint heredado `docker/prod_entrypoint.sh`, **sobrescrito** por `ENTRYPOINT ["litellm","--config","/app/config.yaml"]` (`litellm/Dockerfile:9`).
- La base fijada está en el repo desde 2026-07-10 (`git log -S"80ea654c506da9"` → `199bb23`), así que **las dos tags comparten el mismo litellm**: pasar de `2026-09-14` a `2026-09-17` no trae migraciones ⇒ no dispara el caso «actualización» `[inferido de que las capas de litellm son idénticas]`.

**Dos matices a verificar antes de nada**: (1) `specs/053-integridad-costos-restriccion-tabular/spec.md:148-149` cita «código instalado (**1.95.1**)» — distinto del 1.92.0 de la imagen publicada. Puede ser una imagen de desarrollo con `main-latest` sin fijar; si el servidor de Elea corriera otra versión que la publicada, todo lo de esta sección habría que re-leerlo contra *esa* imagen `[no verificado: no accedí al servidor]`. (2) El instalador usa `:latest` (`instalador:docker-compose.yml:48`), no el digest.

---

## §2. Acoplamiento: ¿el backend toca tablas del motor?

### 2.1 Backend → motor: solo por API HTTP

`[verificado]` — el backend **no contiene ninguna referencia a una tabla `LiteLLM_*`** (`grep -rn "LiteLLM_" backend/ cli/ scripts/ tools/ deploy/ harness/` → solo comentarios de specs; la única mención en código es el `litellm_params` del contrato). Todo su SQL crudo va contra tablas propias:

- `backend/src/api/costs.py:113,135,170,197,224` → `audit_logs`, `users`, `groups`
- `backend/src/api/analytics.py:73-142,202-240` → `audit_logs`
- `backend/src/api/internal.py:48-139` (`_IDENTITY_SQL`: `api_keys`, `users`, `groups`, `tenants`, `security_policies`, `guardians`, `budgets`), `:201-220` (`INSERT INTO audit_logs`), `:382-383` (`SELECT 1`)
- `backend/src/services/audit_service.py:367-368`, `backend/src/api/gateway.py`, `retention/purger.py` → tablas propias

La conexión del backend es una sola, `postgresql://…/${POSTGRES_DB}` (`backend/src/database.py:11-28`); `alembic/env.py:38-44` usa la misma; `alembic/env.py:30-35` (`include_object`) ya asume que **el motor comparte la base** y le impide a *autogenerate* tocar tablas ajenas.

Lo que el backend sí hace es llamar a la API del motor con la master key (`backend/src/services/ai_engine_client.py:12-18`, URL `SENTINEL_ENGINE_API_BASE`). El gasto, las llaves y los presupuestos del motor se tocan **solo así**:

| Dato del motor (tabla en la base del motor) | Acceso del backend | Archivo:línea |
|---|---|---|
| Equipos (`LiteLLM_TeamTable`) | `POST /team/new`, `GET /team/info` | `ai_engine_client.py:93,99`; alta desde `api/users.py:233`; gasto `users.py:777` |
| Usuarios (`LiteLLM_UserTable`) | `POST /user/new`, `GET /user/info` | `ai_engine_client.py:116,122`; `users.py:435,764`; `sso/api.py:389` |
| **Llaves virtuales** (`LiteLLM_VerificationToken`), incluidas las de las cuentas `svc.*` | `POST /key/generate` (la llave se fuerza `sk-sentinel-…`), `GET /key/info`, `POST /key/delete` | `ai_engine_client.py:175,185,198`; `api/keys.py:184,225,250,291` |
| **Gasto** | `spend` que devuelven `/key/info`, `/user/info`, `/team/info`; el gasto «real» de la consola sale de `audit_logs`, no del motor | `ai_engine_client.py:99-105,122-128,185-195`; `costs.py` (solo `audit_logs`) |
| **Presupuestos** | los del producto viven en `budgets` (backend); al motor solo se le reenvía `max_budget/budget_duration` en `/key/generate`, `/user/new`, `/team/new` | `ai_engine_client.py:90-92,114-115,155-160`; `custom_auth.py:140-146` lee `budgets` (backend) |
| Guardrails / políticas de contenido | `POST /guardrails`, `DELETE /guardrails/{id}`, `GET /v2/guardrails/list` | `ai_engine_client.py:307,337,342,366,391` |
| Sondas, embeddings, chat | `/v1/embeddings`, `/v1/chat/completions` | `ai_engine_client.py:551,573`; `router_config.py:420`; `entity_catalog_service.py:370` |

Los **identificadores del motor** quedan guardados en tablas del backend: `groups.engine_team_id` (`models/user.py:47`), `users.engine_user_id` (`models/user.py:99`), `api_keys.engine_key_token` (`models/budget.py:51`). Consecuencia para el traslado: **las filas `LiteLLM_*` tienen que viajar con sus ids intactos**; si se recrean, esas columnas apuntan a nada. `GET /keys/{id}/spend` **traga** el fallo del motor y devuelve el consumo propio (`api/keys.py:292-293`), así que **no sirve como prueba** de que el motor responde.

**Respuesta a «si existe, qué haría falta (segunda conexión o API)»**: no existe acoplamiento backend→motor por SQL; no hace falta segunda conexión del backend. Separar las bases no obliga a tocar el código del backend para *sus* accesos.

### 2.2 Motor → backend: el acoplamiento por SQL que sí existe

`[verificado]` — es el que hace falta desacoplar:

| Qué lee/escribe el motor | Dónde | Camino de producción (HTTP) | Camino por defecto (SQL compartido) |
|---|---|---|---|
| **Identidad** de cada pedido: `api_keys` ⋈ `users`, `groups`, `tenants`, `security_policies`, `guardians`, `budgets` | SQL en `litellm/extensions/custom_auth.py:77-147` (espejo de `backend/src/api/internal.py:48-139`) | `GET {SENTINEL_IDENTITY_URL}?key_hash=…` (`custom_auth.py:218,240-266`) → `internal.py:161` | `prisma_client.db.query_raw(_IDENTITY_SQL, …)` (`custom_auth.py:268-272`) |
| Verificar «actúa en nombre de»: `users` | `custom_auth.py:296-313` | `GET …/verify-user` → `internal.py:142` | `query_raw('SELECT id FROM users …')` (`custom_auth.py:311-313`) |
| **Auditoría durable**: `INSERT INTO audit_logs` | `litellm/extensions/sentinel_audit_logger.py:49` (SQL), `:236-241` (selección de camino) | `POST {SENTINEL_AUDIT_URL}` → `internal.py:298` | `_insertar_por_prisma` → `query_raw` (`sentinel_audit_logger.py:415-422`) |
| Sonda de auditoría (`closed`) | `sentinel_guardrail.py` (`/internal/audit/probe`) | `internal.py:368` | — |

Qué pasa si se separan las bases **sin** cablear las dos URL: el motor consulta `api_keys` en su base nueva ⇒ `relation "api_keys" does not exist` ⇒ **todo byok/svc devuelve 401** y el tráfico deja de auditarse en silencio (`custom_auth.py:19-26`, `internal.py:1-14`, `sentinel_audit_logger.py:357-363`). Está documentado como cicatriz del 2026-07-27.

**Dónde hoy se usa el camino por defecto (SQL compartido)**:
- docker-compose de desarrollo: el motor no define ninguna de las dos URL (`docker-compose.yml:75-112`) y comparte `DATABASE_URL` con el backend (`:76` vs `:149-152`). `[verificado]`
- **Instalador (= producción de Elea)**: ídem — `instalador:docker-compose.yml:50-72` no define `SENTINEL_IDENTITY_URL` ni `SENTINEL_AUDIT_URL`, y `DATABASE_URL` apunta a `elea_gateway` (`:51`), la misma base del backend (`:94`). `[verificado]`

**Qué haría falta** (sin cambiar código de extensiones ni del backend): dos variables más en el servicio `engine` (las URL internas) y la `DATABASE_URL` nueva. Cuidados: (a) el backend pasa a ser **dependencia de tiempo de ejecución del motor** (si el backend está caído, la identidad falla cerrada: `custom_auth.py:240-250`); (b) el endpoint interno se protege con el secreto compartido `SENTINEL_ENGINE_MASTER_KEY` (`internal.py:120-127`); en Sentinel además el ingress devuelve 404 a `/api/v1/internal/*` (`sentinel: deploy/docker/Caddyfile.ingress`, según el docstring de `internal.py`), pero el **instalador no tiene ingress** y publica `8091:8000` (`instalador:docker-compose.yml:91-92`) ⇒ la protección es solo el secreto [verificado: el compose y `internal.py:120-127`]; (c) la reentrada backend→motor→backend bajo carga no se ensayó `[no verificado]`.

---

## §3. Cómo lo resolvió Sentinel y qué se puede portar

`[verificado]` contra `origin/main` de Sentinel (HEAD `6a70855`):

| Pieza | Sentinel | Este repo hoy |
|---|---|---|
| Base propia del motor | `DATABASE_URL` armada con las mismas variables `POSTGRES_*` del backend, pero apuntando a la base `${ENGINE_DB:-sentinel_engine}` (`sentinel:deploy/docker/compose.prod.yml:238`) | **igual** (`deploy/docker/compose.prod.yml:207`) |
| Creación de la base | `deploy/docker/initdb/01-engine-db.sql` → `CREATE DATABASE sentinel_engine;`, montado en `db` (`compose.prod.yml:340`) | **idéntico** byte a byte (`diff` vacío; `deploy/docker/initdb/01-engine-db.sql:15`; mount `:297`) |
| Identidad y auditoría por HTTP | `SENTINEL_IDENTITY_URL` (`:245`), `SENTINEL_AUDIT_URL` (`:250`) | **igual** (`:214`, `:219`) |
| Orden de arranque | `backend` espera `engine` con `service_started` (`:155-157`) | igual (`:131-132`) |
| Motivo documentado | «su migrador Prisma aplica un diff DB↔schema… DROPea tablas ajenas… (ensayo 2026-07-22)» (`:232-237`) | igual (`:202-206`) |
| Dev (`docker-compose.yml:77`) | **sigue compartiendo** `POSTGRES_DB` | igual: comparte (`docker-compose.yml:76`) |
| Backup/restore | `deploy/release/backup.sh:72` hace `pg_dump -d "$PGD"` solo de `POSTGRES_DB`; `restore.sh:69,82` ídem | **no existen** en este repo (`deploy/release/` sin `backup.sh`/`restore.sh`) |
| Documentación | «el motor usa base propia `sentinel_engine`» (`sentinel:docs/sentinel/01-COMO-FUNCIONA-SENTINEL.md:47,165`) | no la menciona |

Sentinel no tiene (en `origin/main`) ningún uso de `DISABLE_SCHEMA_UPDATE`, `--use_v2_migration_resolver` ni `elea_engine`; tampoco documenta el caso «actualización de imagen con L presente» [verificado por git grep; ausencia ≠ imposibilidad].

**Qué se puede portar tal cual** (al instalador y al compose de desarrollo de Elea):
1. **Las dos variables** `SENTINEL_IDENTITY_URL` / `SENTINEL_AUDIT_URL` y la `DATABASE_URL` con `ENGINE_DB` — copiar el bloque de `compose.prod.yml:202-219`, con el nombre de la base como variable.
2. **El orden** «motor primero» (ya está en dev e instalador).
3. **El motivo y el aviso** en comentarios (genérico, sin strings de Elea ⇒ portable a la base Guardian).

**Qué NO se porta tal cual**:
- **`initdb/01-engine-db.sql` solo corre al inicializar un volumen vacío** (comentario `01-engine-db.sql:6`; Postgres `docker-entrypoint-initdb.d`). La instalación de Elea **ya tiene volumen** ⇒ no se crearía la base. Y el script tiene el nombre **fijo** (`:15`) aunque el compose lo parametriza con `ENGINE_DB` (`:207`): si alguien cambia `ENGINE_DB`, la base no se crea y el motor no arranca. Además el servicio `db` no recibe `ENGINE_DB` en su entorno (`compose.prod.yml:291-294`). Un script genérico necesitaría `.sh` + `ENGINE_DB` en el `environment` de `db`.
- **El backup**: Sentinel solo respalda `POSTGRES_DB`; tras separar, las llaves virtuales y el gasto del motor quedan **fuera de la copia** (impacto de perderlos: ver §7).
- **El instalador no tiene ni `initdb/` ni `Caddyfile.ingress`**; un bind-mount a una carpeta inexistente hace que Docker cree una carpeta vacía y la base no se cree *en silencio* (lo describe `sentinel:deploy/release/bundle.sh:65-75`) — por eso en §4.2 se propone un servicio de un solo disparo en lugar de `initdb`.

---

## §4. Procedimiento propuesto (tres casos)

**Nombres**: base nueva `elea_engine` (variable `ENGINE_DB`). Usuario/base actuales de la instalación de Elea: valores por defecto del instalador `elea_admin` / `elea_gateway` (`instalador:.env.example:5-6`); los reales del servidor **no los vi** `[no verificado]`. Contenedor `elea-db` (`instalador:docker-compose.yml:8`).

**Tiempos**: ninguno está medido; son estimaciones `[no verificado]` que el ensayo debe sustituir por mediciones. **El tamaño de las tablas del motor del servidor es la variable que falta** (sobre todo `LiteLLM_SpendLogs`).

**Vuelta atrás probada**: *ninguna* lo está todavía — no hay Docker en este spike. Cada caso dice qué debe probarse y cómo; el ensayo (tarea siguiente, con la compuerta del owner) es el que convierte «propuesta» en «probada».

### 4.1 Desarrollo (`docker-compose.yml` de este repo)

Cambios (los hace una tarea posterior, no este spike):
1. Servicio `engine` (`docker-compose.yml:75-112`): `DATABASE_URL` → `…/${ENGINE_DB:-sentinel_engine}` (el default queda como el de Sentinel por ser base Guardian; en Elea se fija `ENGINE_DB=elea_engine` en `.env`), más `SENTINEL_IDENTITY_URL=http://backend:8000/api/v1/internal/identity` y `SENTINEL_AUDIT_URL=http://backend:8000/api/v1/internal/audit`.
2. Creación de la base: montar `./deploy/docker/initdb:/docker-entrypoint-initdb.d:ro` en `db` (sirve en volúmenes nuevos) **y** documentar el comando manual para volúmenes existentes: `docker exec <prefijo>-db psql -U $POSTGRES_USER -d postgres -c "CREATE DATABASE <ENGINE_DB>"`.
3. Dependencia: el motor ya no necesita esperar a una base compartida, pero **conviene que el backend siga esperando al motor sano** (`docker-compose.yml:226-228`) porque las llaves se crean por API.

Procedimiento para un dev con volumen existente: `docker compose down engine` → crear la base → `up -d engine` (migra una base vacía, caso sin riesgo) → recrear llaves de prueba (se pierden las del motor viejo; en dev no hay nada que preservar) o aplicar el traslado de §4.3 si se quiere conservar.

- **Corte**: ~2–5 min por dev `[no verificado]`. Solo se reinicia el motor.
- **Vuelta atrás**: quitar las 3 variables y `up -d engine`: las tablas viejas `LiteLLM_*` siguen en la base compartida (no se borran en este caso). Probar: que el motor viejo vuelva a arrancar sobre esa base sin entrar en el caso «actualización» (misma imagen ⇒ «No pending»).
- **Verificar**: (i) log del motor **sin** «baseline» ni «diff applied»; (ii) `psql -d <ENGINE_DB> -c '\dt'` muestra solo `LiteLLM_*` y `_prisma_migrations`; (iii) `psql -d <POSTGRES_DB> -c '\dt'` muestra las tablas del backend intactas; (iv) una llamada con una llave de `/gw` responde 200 (identidad por HTTP) y deja fila en `audit_logs` (auditoría por HTTP); (v) `docker compose up` desde cero con la base nueva **y** con alembic corrido primero no dispara nada (porque ya no comparten).

### 4.2 Instalación nueva (instalador)

Cambios en `elea-installer` (otro repo; se coordina desde el plan de Atlas, no se toca acá):
1. `docker-compose.yml`, servicio `engine`: `DATABASE_URL` → `…/${ENGINE_DB:-elea_engine}`; agregar `SENTINEL_IDENTITY_URL` y `SENTINEL_AUDIT_URL` (valores de §4.1). `.env.example`: `ENGINE_DB=elea_engine`.
2. **Crear la base con un servicio de un solo disparo, no con `initdb`**: p. ej. un servicio `db-engine-init` (`postgres:16-alpine`, `restart: "no"`, `depends_on: db: service_healthy`) que ejecute `SELECT 'CREATE DATABASE elea_engine' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='elea_engine')\gexec`, y `engine` con `depends_on: db-engine-init: condition: service_completed_successfully`. Razón: **idempotente**, sirve para instalación nueva *y* para actualizar una instalación con volumen (donde `initdb` no corre), y no depende de un bind-mount que el instalador no tiene. `[propuesta; no ensayada]`
3. `install.sh:67`: ya levanta `db redis nlp-analyzer engine anythingllm` y espera al motor sano antes del backend (`:69-75`); habría que sumar el servicio de init o dejar que `depends_on` lo arrastre.
4. Fijar la imagen del motor por digest (ver §5/§6).

- **Corte**: ninguno (instalación nueva); costo: una base más y ~10 s de arranque `[no verificado]`.
- **Vuelta atrás**: `docker compose down -v` (en una instalación nueva el volumen es descartable); para volver al layout compartido bastaría revertir el compose del instalador a su commit anterior. Probar: instalar desde cero con el compose nuevo, y desde cero con el viejo, y comparar.
- **Verificar**: lo de §4.1 más lo específico del instalador: `./install.sh` completo hasta «Listo. Todo corriendo»; las 3 cuentas `svc.*` quedan con llave y el Hub chatea; el motor `healthy` antes del backend; **sin** el orden alembic→motor en ningún camino (el servicio de init no depende del backend).

### 4.3 PRODUCCIÓN en marcha (instalación de Elea con el instalador, base compartida)

**Premisa**: producción es el layout del instalador (`elea-db`, base `elea_gateway`, motor por `:latest`). No se accede al servidor desde este spike; todo lo siguiente es el **procedimiento a ensayar**, no ejecutado.

**Antes de la ventana (sin corte)**
1. Anotar qué corre: `docker inspect elea-engine --format '{{.Image}} {{.Config.Image}}'` y `docker exec elea-engine python3 -c "import importlib.metadata as m; print(m.version('litellm'), m.version('litellm-proxy-extras'))"` (resuelve la duda 1.92.0 vs 1.95.1 de §1.4; la imagen no trae `pip`, sí `python3`: el propio healthcheck lo usa, `instalador:docker-compose.yml:81`).
2. **Copia completa verificada**: `docker exec elea-db pg_dump -U $POSTGRES_USER -Fc $POSTGRES_DB > pre-split-$(date +%F-%H%M).dump`; comprobar con `docker exec -i elea-db pg_restore -l < …dump | head`; guardarla **fuera del servidor de la base** (si no, no es respaldo).
3. Inventario y fotografía previa (SQL de solo lectura contra `elea_gateway`):
   - tablas del motor: `SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'LiteLLM\_%' OR tablename='_prisma_migrations') ORDER BY 1;`
   - libro completo: `SELECT count(*) FROM _prisma_migrations WHERE finished_at IS NULL OR rolled_back_at IS NOT NULL;` → debe ser 0
   - llaves y gasto: `SELECT user_id, key_alias, spend FROM "LiteLLM_VerificationToken" ORDER BY key_alias;`. **Ojo con el alias**: las cuentas `svc.*` son *usuarios* (`user_id` = `svc.<nombre>@elea-internal.com`, `users.py:435` + `install.sh:167-180`); el `key_alias` de su llave es el nombre corto (`tabular`, `presenton`, `anythingllm-provider[-aaaammddhhmm]`, `install.sh:143`, `ai_engine_client.py:154`), no «svc.*».
   - tamaños: `SELECT relname, pg_size_pretty(pg_total_relation_size(oid)) FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace AND (relname LIKE 'LiteLLM\_%' OR relname='_prisma_migrations') ORDER BY pg_total_relation_size(oid) DESC;` — **define el tiempo de corte real**.
   - vistas del motor (`pg_views`): el motor las recrea sola si faltan (`imagen:litellm/proxy/utils.py:2978-3028`, `check_view_exists`); por eso no se trasladan `[verificado que existe el método; que se invoque en el arranque, no]`.
4. Aplicar la mitigación de §5 (M1–M3) **antes** de tocar nada: reduce el riesgo durante el propio procedimiento.

**Ventana de corte** (estimación de indisponibilidad del motor y, por tanto, del Hub/planillas/presentaciones: **5–10 min** con tablas chicas; el motor tarda en estar `healthy` — `install.sh:69` avisa «varios minutos» en base nueva; reservar **30 min** con margen `[no verificado]`):

| # | Acción | Nota |
|---|---|---|
| 1 | `docker compose stop client tabular presenton anythingllm engine` | Congela el gasto. `db` y `backend` siguen arriba. |
| 2 | `docker exec elea-db psql -U $U -d postgres -c "CREATE DATABASE elea_engine OWNER $U"` | `$U` es superusuario de la imagen `postgres` (`POSTGRES_USER`) ⇒ puede crear bases `[verificado el patrón del compose; no el servidor]`. |
| 3 | `pg_dump -Fc` **solo** de las tablas del motor: lista armada **desde el catálogo** (paso 3 de arriba) y pasada como `-t public."<tabla>"` por cada una, más `_prisma_migrations` → `engine.dump`; restaurar con `pg_restore -d elea_engine --no-owner --exit-on-error` | **No usar** `-t 'LiteLLM_*'`: los patrones de `pg_dump` pasan a minúsculas salvo que vayan entre comillas dobles y el comportamiento del `*` dentro de comillas no lo comprobé `[no verificado]`. Tampoco comprobé si `-t` arrastra las secuencias propias de cada tabla: verificar con `\ds` en ambas bases. Alternativa si las secuencias molestan: `CREATE DATABASE elea_engine TEMPLATE elea_gateway` (exige **parar también el backend** para liberar conexiones) y luego `DROP` de las tablas ajenas *en la copia*. |
| 4 | **Compuerta de integridad** (no seguir si falla): `count(*)` por tabla igual en ambas bases; `_prisma_migrations` sin filas pendientes/fallidas en la nueva; `LiteLLM_VerificationToken` idéntica a la fotografía previa (mismas llaves, mismo `spend`). | |
| 5 | Cambiar el servicio `engine`: `DATABASE_URL` → `elea_engine` **y a la vez** `SENTINEL_IDENTITY_URL` + `SENTINEL_AUDIT_URL` (si va solo lo primero, byok/svc da 401: §2.2). Se hace con el compose del instalador ya modificado (§4.2) o, para el primer ensayo, con un `docker-compose.override.yml`. | Cambio atómico: las tres variables o ninguna. |
| 6 | `docker compose up -d engine`; esperar `healthy`; **leer el log**: debe decir «No pending migrations» (o aplicar migraciones *solo sobre la base nueva*, donde el diff es inocuo porque solo hay tablas del motor) y **no** «baseline» ni «diff applied». | Si el libro trasladado estuviera incompleto, el sanity check se ejecuta **sobre `elea_engine`**: no puede borrar nada del backend. Esa es la gracia de separar. |
| 7 | Verificación funcional (abajo). | |
| 8 | `docker compose up -d client tabular presenton anythingllm` | Las llaves `svc.*` **no cambian** (se trasladaron con su hash): el `.env` sigue valiendo; **no** correr `./install.sh` en este paso (reemitiría llaves si faltara alguna). |

**Qué verificar tras el corte** (todo debe cumplirse; si no, vuelta atrás):
- Motor `healthy`; log sin «baseline»/«diff applied»; `\dt` de `elea_engine` = solo `LiteLLM_*` + `_prisma_migrations`; `\dt` de `elea_gateway` = tablas del backend intactas y `alembic_version` con su id.
- **Llaves `svc.*`**: cada una responde 200 contra el motor. Disparar una pregunta real: planillas (usa `svc.tabular`), presentación (`svc.presenton`), chat con documentos (`svc.anythingllm-provider`). Para cada una: sube `LiteLLM_VerificationToken.spend` en `elea_engine` **y** aparece una fila nueva en `audit_logs` (llegó por `/internal/audit`).
- **Gasto**: el panel de costos (lee `audit_logs`, `costs.py`) no cambia respecto de la fotografía previa; el `spend` de cada llave en `elea_engine` = fotografía previa + lo consumido en las pruebas. **No** usar `GET /keys/{id}/spend` como prueba (`keys.py:292-293` oculta el fallo).
- Identidad por HTTP bajo carga ligera (reentrada backend→motor→backend, §2.2c).
- Que el backend arranque y migre sin tocar nada del motor: `docker compose restart backend` ⇒ `alembic upgrade head` sin efecto sobre `elea_engine`.

**Vuelta atrás** (probar *cada* escalón en el ensayo):
- **A — antes del paso 5**: nada cambió. `docker compose up -d engine client tabular presenton anythingllm`; `DROP DATABASE elea_engine`.
- **B — después del paso 6 y mientras no se borren las copias viejas (paso 9)**: restaurar el compose/`.env` anterior (revertir las 3 variables) y `docker compose up -d engine`. El motor vuelve a leer las `LiteLLM_*` de `elea_gateway`, que **siguen intactas** (este procedimiento solo *copia*). Pérdida acotada: lo que el motor contó en `elea_engine` desde el corte (contadores de gasto del motor; `audit_logs` no se afecta porque vive en el backend). Con la imagen vieja y su libro intacto no hay migraciones pendientes ⇒ no se dispara §1.
- **C — `elea_gateway` dañada**: `pg_restore` de `pre-split-….dump` (paso 2 previo) en una base nueva. Sirve además para ensayar el caso «base restaurada»: **restaurar el dump completo trae `_prisma_migrations` y no dispara nada; restaurar solo tablas del backend sí**.

**Paso 9 — borrar las copias viejas (solo después)**: pasada una ventana de observación (propuesta: **≥ 7 días** con el motor ya sobre `elea_engine`, y una copia completa nueva): `DROP TABLE` de las `"LiteLLM_*"` y de `_prisma_migrations` **en `elea_gateway`**. Por qué esperar: (i) es la vuelta atrás B; (ii) hasta entonces, `elea_gateway` conserva un libro `_prisma_migrations` — inofensivo mientras ningún motor se conecte a ella, pero deja un cebo si alguien arranca un motor con la `DATABASE_URL` vieja. **Borrar `_prisma_migrations` de `elea_gateway` sin haber separado sería exactamente el caso que dispara el borrado (§1.3, «base restaurada»)**: el orden importa.

**Documentación a actualizar en la tarea siguiente** (Definition of Done de AGENTS.md): `docs/docs/operations/index.md:586-596` documenta el respaldo con un solo `pg_dump -d <db>` ⇒ tras separar hay **dos** bases que respaldar; y las páginas de despliegue (`docs/docs/install-deploy/index.md`, `docs/docs/api-reference/configuration.md`) deben reflejar `ENGINE_DB` y las dos URL internas, con la leyenda 🟢/🟡/🔵 según lo que el código respalde `[no revisado a fondo]`.

---

## §5. Riesgo mientras no se haga

**Cuándo puede dispararse en producción de Elea** (instalador, base compartida) — de más a menos probable:

1. **`./install.sh` con una imagen del motor sobre un litellm más nuevo** (caso «actualización», §1.3). `install.sh:56,66-67` baja `elea-guardian-engine:latest` y recrea el contenedor si cambió; `litellm/Dockerfile:6` hoy fija 1.92.0, pero **la próxima vez que alguien haga `publish-elea.sh` tras subir el digest** (`deploy/release/publish-elea.sh:23-34`), el siguiente `./install.sh` en el servidor lo toma solo, sin que nadie lo decida y sin aviso. Las dos tags publicadas (09-14 y 09-17) **no** traen migraciones nuevas entre sí ⇒ hasta hoy no mordió. `[verificado por código y por las capas; el disparo exacto no se ensayó]`
2. **Restauración del servidor desde una copia** que pierda `_prisma_migrations` o que sea parcial (restaurar solo tablas del backend, o un dump de otra base) + arrancar el motor ⇒ `P3005` ⇒ baseline + diff.
3. **Cualquier orden alembic→motor sobre una base nueva o recién restaurada** (instalación de otro cliente copiando el procedimiento a mano, un `docker compose up backend` sobre una base vacía fuera de `install.sh`, un CI).
4. **Desarrollo**: el dev que baje el digest o restaure su base. Mismo mecanismo; menor impacto.

El impacto: pérdida de `users`, `api_keys`, `audit_logs`, `alembic_version`…, **incluida la auditoría durable** (producto de compliance). Sin copia previa, irrecuperable salvo restauración física.

**Mitigación inmediata** (no requiere imagen nueva ni código; **no ensayada**):

- **M1 — congelar el motor**: no correr `./install.sh` ni `docker compose pull engine` hasta fijar la imagen por digest (`ghcr.io/cluna-8/elea-guardian-engine@sha256:1928af9d…`, la `latest` de hoy; verificar primero la versión real del servidor, §4.3 paso 1). No publicar una imagen del motor sobre otro litellm sin pasar por M2/M3.
- **M2 — copia completa antes de cualquier actualización** (`pg_dump -Fc`, §4.3 paso 2), guardada fuera del servidor.
- **M3 — apagar el migrador del motor** en el servidor con un archivo **`docker-compose.override.yml`** junto al `docker-compose.yml` del instalador (compose lo toma solo; no se versiona ni cambia el repo): 
  ```yaml
  services:
    engine:
      environment:
        - DISABLE_SCHEMA_UPDATE=true
  ```
  Efecto leído en el código: `should_update_prisma_schema` devuelve `False` ⇒ el arranque corre solo `check_prisma_schema_diff`, que **no ejecuta** el diff (`imagen:…/prisma_client.py:704-710`, `proxy_cli.py:1168-1169`, `check_migration.py:92-103`). Costo: el motor **no aplicará** migraciones de un litellm nuevo, así que M3 solo es válido junto con M1 (imagen fija). Hay que ensayar que, con la base actual y esta variable, el motor arranca normal `[no verificado]`.
- **M4 (opcional, defensa en profundidad)**: la bandera `--use_v2_migration_resolver` evita `_resolve_all_migrations` (`utils.py:505-516`), pero es solo de CLI: exige cambiar el `ENTRYPOINT` de `litellm/Dockerfile:9` y reconstruir la imagen; y su camino `P3005` sigue creando un baseline `0_init` (sin `DROP`, por lectura de `utils.py:573-580`). Evaluar en el ensayo `[no verificado]`.

**Decisión de fondo**: M1–M3 reducen el riesgo, **no lo eliminan** (siguen compartiendo base). Lo elimina §4.3.

---

## §6. Decisiones para el owner (con recomendación)

| # | Decisión | Recomendación |
|---|---|---|
| D1 | ¿Se separa la base del motor en los tres frentes? | **Sí.** Es la única forma de que el diff del migrador sea inocuo; Sentinel ya lo hace en producción. |
| D2 | ¿Aplicar M1–M3 **ya** en el servidor de Elea, antes de cualquier ensayo? | **Sí, esta semana**: son baratas y quitan el disparo «silencioso» por `:latest`. M3 requiere confirmar la versión real del servidor primero. |
| D3 | Imagen del motor en el instalador: ¿`:latest` o digest? | **Digest**, siempre (`publish-elea.sh` ya imprime `PINNED …=<digest>`, `:43`; falta que el instalador lo consuma). El `README` del instalador ya dice «imágenes fijadas por digest/versión» para Presenton/AnythingLLM (`instalador:README.md:44`); el motor es el que falta. |
| D4 | Creación de la base en el instalador: ¿`initdb` (como Sentinel) o servicio de un solo disparo? | **Servicio de un solo disparo** (idempotente; sirve para actualizar una instalación con volumen). Mantener `initdb` en `compose.prod.yml`, pero generalizado a `.sh` con `ENGINE_DB` (hoy el nombre es fijo). |
| D5 | Identidad/auditoría del motor: ¿HTTP interno (Sentinel) o segunda conexión SQL? | **HTTP interno.** Ya está implementado y probado en producción de Sentinel; la imagen del motor no trae driver de Postgres ni `pip` (`internal.py:10-14`). |
| D6 | ¿Cuándo se hace el traslado de producción? | **Después** del ensayo con Docker que pruebe las tres vueltas atrás (A/B/C) y mida el tamaño real; en una ventana de ~30 min acordada con el cliente. Esto requiere **tu compuerta** (Docker). |
| D7 | Backup: ¿incluir la base del motor? | **Sí**, ambas bases en una sola copia consistente; hoy ni Sentinel lo hace (`backup.sh:72`) ⇒ es un hallazgo para el HANDOFF a Sentinel. Falta decidir si perder `elea_engine` es tolerable (ver §7: depende de si el motor sirve algo sin sus llaves virtuales). |
| D8 | ¿Cuánto esperar antes de borrar las copias viejas? | **≥ 7 días** y con copia completa nueva. |
| D9 | ¿Qué sube a la base Guardian (→ Sentinel) y qué es de Elea? | Base Guardian: variables/comentarios genéricos del compose de dev y `initdb` genérico, `backup.sh` con dos bases → **HANDOFF a Sentinel**. Elea: el instalador, el servicio de init, la fijación por digest y el runbook de producción. |
| D10 | ¿Habilitar `--use_v2_migration_resolver` además? | **Después del ensayo**, como defensa adicional; no sustituye la separación. |

---

## §7. No verificado

Todo lo siguiente es `[no verificado]`:

1. **Que Prisma emita `DROP TABLE` para tablas ajenas al datamodel** — no lo ejecuté (sin Docker/Postgres/Prisma local). Lo sustentan: el código que ejecuta el diff (§1.1), el incidente aportado, y la reproducción del 2026-07-22 en `git show f83a0e6`. El ensayo debe reproducirlo en una base descartable.
2. **Qué versión corre realmente el servidor de Elea** y qué digest. Lo publicado es 1.92.0 (verificado); `specs/053…/spec.md:148` menciona 1.95.1. No accedí al servidor.
3. **Los nombres reales** de base/usuario/proyecto compose del servidor (asumí los del instalador) y **si hay `docker-compose.override.yml` o variables extra** ya presentes.
4. **Tamaño de las tablas del motor** en producción ⇒ los tiempos de corte de §4 son estimaciones, no mediciones.
5. **Comportamiento de `pg_dump -t` con identificadores en mayúsculas y comodines, y con secuencias propias** (§4.3 paso 3). Por eso se propone armar la lista desde el catálogo y verificar con `\ds`.
6. **Que el motor recree las vistas** (`LiteLLM_VerificationTokenView`, etc.) en cada arranque: solo vi que el método existe (`utils.py:2978`), no su invocación.
7. **Que Prisma imprima «No pending migrations to apply»** exactamente cuando no hay pendientes (el código lo compara por cadena, `utils.py:726`).
8. **Que `DISABLE_SCHEMA_UPDATE=true` deje al motor arrancando normal** sobre la base actual con libro completo (M3), y que `check_prisma_schema_diff` no tenga efectos laterales: lo leí como solo lectura (`check_migration.py:57-103`) pero no lo corrí.
9. **Las tres vueltas atrás (A/B/C)**: propuestas, no probadas. Tampoco el servicio de un solo disparo de §4.2 ni su `depends_on`.
10. **Qué sirve el motor sin sus `LiteLLM_*`** (si perder `elea_engine` deja a las llaves `svc.*` operativas): la identidad sale del backend (`custom_auth.py`), así que probablemente sí, pero faltarían los contadores de gasto del motor y `engine_key_token` apuntaría a una llave inexistente en `/key/info` (`keys.py:292-293` lo oculta). Se debe probar.
11. **La reentrada backend→motor→backend bajo carga** con identidad por HTTP en el instalador (hilos del backend; el instalador arranca uvicorn sin workers: `instalador:docker-compose.yml:90`).
12. **La carrera alembic/motor con `service_started`** (`compose.prod.yml:131-132`): inferida de la lectura, no reproducida.
13. **Los bordes exactos de versión** de cada comportamiento del migrador (§1.2) y si el *default* de la última `litellm-proxy-extras` (0.4.105) sigue siendo v1.
14. **Dónde y cuándo ocurrió el incidente** que dio origen a este spike (el log del brief): no lo vi; se asume el mecanismo de §1.
15. **Cobertura de la documentación de producto** (`docs/docs/**`) y de los checks `make -C deploy check*`: **no se corrieron** (usan Docker y este spike solo agrega un archivo en `specs/`, fuera del sitio publicado y de cualquier scan de los checks revisados).
