# QA crítico del tramo T-B — 057 porte de la redirección de modelos (Sentinel 068)

**Rol**: qa-critico (segundo nivel: seguridad, datos sensibles, permisos, dominio crítico). **Fecha**: 2026-10-06.
**Rama**: `cluna-8/057-tramo-b` (`efc6089`, 62 commits sobre `8999e27`; `main` avanzó 23 commits, no afecta al tramo).
**Alcance**: T016–T030 y T087–T092, T099 de `tasks.md` (T019, el spike D14, sigue abierta) contra `spec.md` (FR-004a–FR-004d, FR-011–FR-014, FR-020, FR-023, FR-028a,
FR-029, FR-031, FR-031a, FR-032; Clarifications de las decisiones legales del owner y del QA del plan), `plan.md`, `research.md` (R4–R9, R14, R17, R23–R25, R27, R30, R31),
`data-model.md` §1–§4, `contracts/`, `qa-tramo-a.md`, la constitución 2.3.0 y `AGENTS.md`.
**Método**: lectura del código de `sentinel/`, de `deploy/release/**` y de `backend/` tocado por el tramo, con archivo:línea; tests locales con el venv del checkout
principal (`/home/drexgen/Documents/ELEA/LLMADMIN-Elea/elea/backend/.venv`, `PYTHONPATH=.:backend`, `LITELLM_MODE=PRODUCTION`); **11 mutaciones y 3 pruebas descartables**
sobre una copia de `sentinel/` en el scratchpad (el repo no se tocó salvo este reporte).
**Límite**: nada que use Docker se corrió (`make -C deploy check`, `check-docs`, `docs-refs`, la suite del backend en contenedor, T019, la construcción de las imágenes `-ext`);
la RLS real y el motor real quedan sin verificar por mí (ver §9).

## Veredicto

**Sin bloqueantes para integrar T-B.** Lo que T-B declara cumplido está respaldado por tests que detectan la regresión (§1–§4: de 11 mutaciones propias, 10 ponen un test en rojo; la que
no, es una cota de TTL, H6) y el requisito de modelos chinos y económicos tiene su test (§4). La extensión apagada no cambia nada (§2) y la migración queda como segunda cabeza con
el motor intacto (§3).

Hay **3 hallazgos altos que no bloquean T-B pero sí condicionan lo que viene**, porque T-B deja el mecanismo sin cerrar la regla (los tres se verificaron con una prueba, no solo
leyendo):

- **H1**: el admin de empresa puede dar de alta destinos con cualquier `api_base` (169.254.169.254, `engine:4000`, `db:5432`, `file://`): el motor llama a esa dirección.
- **H2**: una relajación del enmascarado forzado por destino sobrevive a que el admin de empresa cambie el `api_base` o el proveedor de la entrada.
- **H3**: el interino de T-B no es el default de D2: sin postura rige `allowlist` sin enmascarado forzado y la región cae a `eu`. Hasta T-E, **la extensión no puede activarse en
  ninguna instalación**.

**worker_done: succeeded** (no hay bloqueantes). Condiciones para el PR del tramo, que **no** son defectos de código de T-B sino trabajo abierto del plan: T019 (spike D14) y el
gate 🐳 de T030 (suite del backend, `make -C deploy check`, construcción real de las `-ext`); H2 y H3 se cierran en T-E (T053, T060–T064) y H1 se decide antes de activar (T-H).

## Resumen de hallazgos

| Id | Sev. | Qué | Dónde | Requisito |
|---|---|---|---|---|
| H1 | Alta (activación; decisión del owner) | `api_base` de las entradas de empresa sin validar: el motor (y la sonda de despliegue) llama a cualquier dirección | `sentinel/catalog/api/admin.py:396,423,291-304,568,328-352` | Constitución III y Seguridad 4 (aislamiento de tenant); espíritu de FR-014; Seguridad 5 |
| H2 | Alta (T-E; no explotable hoy) | La relajación por destino no se revoca cuando cambia el destino (`api_base`, proveedor, modelo, `is_aggregator`) | `sentinel/catalog/api/admin.py:624-694` (sin `revoke_unmet`; solo `:923`), `sentinel/catalog/relaxation.py:35-48` | FR-031a, FR-023, data-model §3 |
| H3 | Alta (T-E; condición de activación) | Interino de T-B sin el default de D2; región de respaldo `eu`; `default_posture` sin lector | `sentinel/redirect/residency.py:95-98,122-135`, `sentinel/redirect/plugin.py:134-137`, `sentinel/redirect/api/admin.py:571`, `sentinel/redirect/api/us5.py:197`, `docker-compose.yml:101,217`, `deploy/docker/compose.prod.yml:122,215`, `sentinel/redirect/models.py:189` | D2, FR-027, FR-031, QA B2, constitución I [D15] |
| H4 | Media | Las costuras de la consola (`access_hook`, `model_route_hook`, `residency_heuristic`) no existen en Eleia y la extensión se degrada en silencio: los perfiles de acceso no rigen en el chat de la consola | `sentinel/catalog/api/__init__.py:4-31`, `sentinel/access/bridge.py:113-118`, `sentinel/catalog/chat_route.py:113-117` | FR-003 (registro de adaptaciones), FR-016, FR-052; spec/plan no lo mencionan |
| H5 | Media | OpenRouter sin cero retención ni lista de proveedores hasta T058, y el test de T024 ya lo ejercita | `sentinel/engine/redirect_guard.py:344-346`, `sentinel/tests/integration/test_catalogo_modelos_chinos_economicos.py:49-52` | FR-032, R19 (T058, T061) |
| H6 | Baja | Cota `MAX_TTL` de la autorización sin test (la mutación pasa); el guard solo tiene 1 test que detecta que no se limpie el campo del cliente | `sentinel/engine/redirect_authz.py:31,114`; `sentinel/engine/redirect_guard.py:332-333` | FR-014, QA A3 |
| H7 | Baja | Texto visible en el panel nombra «Sentinel»; comentarios de código [BASE] nombran a Eleia | `sentinel/frontend/catalog/EntryForm.tsx:126`; `catalog/habilitacion.py:18`, `catalog/api/internal.py:161`, `migrations/89a92524eef6…py:5,9`, `frontend/catalog/EnablementTab.tsx:3` | White-label (FR-004; no está en `prohibited_names.txt`) |
| H8 | Baja | Campos de la ficha que alimentan el semáforo y que el admin de empresa sí puede editar | `sentinel/catalog/store.py:22-24`, `sentinel/catalog/api/admin.py:44-50` | FR-023 (lista de 5), FR-030a (a vigilar en T-E) |
| H9 | Info | Las tres tablas nuevas heredan la política RLS permisiva `tenant_isolation_bootstrap` de la base | `sentinel/migrations/89a92524eef6_redirect_region_y_habilitacion.py:57-65` | FR-051 (🟡 hasta la suite 🐳) |
| H10 | Info | `make -C deploy check` no queda verde en esta rama: `test_redis_wiring.sh` y `check-extension-whitelabel` fallan por motivos ajenos al tramo | `deploy/release/checks/test_redis_wiring.sh:53-56`, `deploy/Makefile:93-96` | AGENTS.md «el gate del release es la verdad» |
| H11 | Info | Canal interno: las capas 2 y 3 son dependencia ausente de esta rama; `/model-catalog` y `/model-access` siguen con el secreto como única barrera (y el secreto de ejemplo es público) | `backend/src/api/internal.py:120-127`, `.env.example:61`, `docker-compose.yml:85` | FR-013, R31 (gate en T-H) |
| H12 | Info | La denylist de variables de entorno no cubre `MASKING_NONCE_KEY` (T093 abierta); la capa de atribución `model_redirect` no se escribe en Eleia | `sentinel/engine/redirect_credentials.py:81-84`, `sentinel/engine/redirect_guard.py:217` | T093; FR-047 |

---

## 1. Seguridad

### 1.1 Credenciales por destino (FR-013, FR-014, FR-020)

- **Almacén cifrado, solo escritura**: `sentinel/catalog/credentials.py:1-9,71-89` (Fernet por `encryption_service`, MultiFernet de T-A; `fingerprint` = últimos 4 del hash,
  `:39-42`); `replace` y `revoke` devuelven huellas (`:105-140`); revocar una credencial en uso exige reemplazo o desactivar (`:126-139`).
  `sentinel/tests/integration/test_catalogo_modelos_chinos_economicos.py:134-136` verifica que el secreto no vuelve en la API de alta.
- **La credencial de un destino solo sale en la autorización firmada**: `sentinel/engine/redirect_authz.py:108-130` (HMAC-SHA256 con llave HKDF de
  `REDIRECT_INTERNAL_KEY`; la credencial viaja con Fernet de una segunda derivación; `ttl` 30 s por defecto, máx. 120 s; liga pedido, alcance, destino, modelo del motor, proveedor,
  base y enmascarado forzado). `verify` (`:133-165`) rechaza forma, firma, expiración y modelo distinto. Una llave corta (como el marcador `<generar>` de
  `sentinel/extensions.env.example`) ⇒ `AuthzKeyMissing` ⇒ 503 fail-closed (`:84-88`, `redirect_guard.py:320-321`).
- **Referencias `env:`** (credencial adoptada, FR-020): solo de instalación y solo `super_admin` (`catalog/api/admin.py:257-258`, `catalog/credentials.py:74-77`); el nombre pasa por
  la denylist común (`redirect_credentials.py:81-90`: `LITELLM_MASTER_KEY`, `FERNET_*`, `JWT_*`, `DATABASE_URL`, `POSTGRES_PASSWORD`, `REDIRECT_INTERNAL_KEY` y los fragmentos
  `MASTER_KEY`, `PASSWORD`, `DATABASE`, `FERNET`, `JWT`, `POSTGRES`, `INTERNAL_KEY`); solo el motor las resuelve (`:233-245`). Contra el `environment:` real del motor
  (`docker-compose.yml:78-102`), lo que queda adoptable son las llaves de proveedor (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_API_KEY`, `GEMINI_API_KEY`), que es lo previsto.
  Mutación M15 (denylist vacía) ⇒ 8 tests en rojo.
- **Una empresa no usa credenciales de otra ni de instalación**: `catalog/api/admin.py:240-246`.
- **Anti-desvío del cliente**: el plugin quita los campos de credencial/destino antes de reescribir el modelo (`sentinel/redirect/plugin.py:434`) y el guard los vuelve a
  quitar y fija los del destino (`redirect_guard.py:332-346`); las cabeceras que no son `anthropic-beta`/`anthropic-version` se descartan (`redirect_credentials.py:143-151`).
  El test de T024 manda `api_base` y `api_key` del cliente a los 8 destinos y exige que ni la salida ni el motor los vean
  (`test_catalogo_modelos_chinos_economicos.py:143-165`).
- **Ver H1** (la dirección del destino que carga el admin de empresa) **y H5** (OpenRouter).

### 1.2 `/internal/model-credential` (FR-013, T090, QA A10)

- La ruta HTTP lleva `Depends(_require_internal_secret)` y `Depends(_require_direct_enabled)` (`sentinel/catalog/api/internal.py:158`): sin `CATALOG_DIRECT_ENABLED` responde 404, el
  mismo cuerpo que sin secreto, **aunque el secreto sea correcto** (`:104-110`). La función sigue invocable en proceso para el chat (`chat_route.py:44-50`).
  **Mutación M1** (quitar la dependencia) ⇒ 8 de 19 tests en rojo.
- `/model-catalog` y `/model-access` no devuelven credenciales (`internal.py:71-94,138-155`): `entry_view(..., owner=False)` y solo huella de precio; el catálogo sí lleva `api_base`,
  `real_model` y `provider`. `model-access` falla cerrado: 503 si el resolutor falla (`:149-152`).
- `CATALOG_DIRECT_ENABLED` no está en `sentinel/extensions.env.example` ni en el fragmento (verificado leyendo ambos), así que la ruta directa del motor queda apagada
  (`sentinel/engine/redirect_catalog.py:10`).
- El plano motor de la extensión no lee la base: no hay `psycopg`, `sqlalchemy` ni `DATABASE_URL` en `sentinel/engine/*.py` (el único `DATABASE_URL` es la denylist,
  `redirect_credentials.py:82`) (R5 c).
- **Capas 2 y 3 de R31 (chequeo de origen, proxy del instalador)**: son dependencia y **no están en esta rama** (H11).

### 1.3 Permisos de la ficha y de las reglas (FR-023, T099, T087; QA A7)

- `RESIDENCY_FIELDS` = `provider_legal_entity`, `entity_jurisdiction`, `control_jurisdiction`, `inference_jurisdiction`, `zero_data_retention` (`catalog/api/admin.py:48-49`); solo
  `compliance_officer` y `super_admin` **por rol real** (`:50`, `:899`: `getattr(user, "role", None) in RESIDENCY_WRITERS`, no `_is_super`): el `tenant_admin` del tenant operador con
  `REDIRECT_OPERATOR_TENANT` definida tampoco (test en `test_ficha_roles_residencia.py`). Comparar con el cuerpo vigente (`_residency_changes`, `:949-953`) evita el falso 403 por
  repetir el valor.
  **Verificado con una prueba descartable**: `PUT /entries/{id}/sheet` como `tenant_admin` ⇒ `inference_jurisdiction` 403, `zero_data_retention` 403, `control_jurisdiction` 403;
  `notes`, `trains_on_data`, `logs_jurisdiction`, `transfer_mechanism` 200 (H8). **Mutación M2** (sumar `tenant_admin` y `admin` a `RESIDENCY_WRITERS`) ⇒ 8 de 29 en rojo.
- `in_region` exige inferencia, entidad **y control** cargadas y dentro del conjunto; `NULL`, vacío o `unknown` no cuentan (`sentinel/catalog/region.py:48-57`, D12). **Mutación M4**
  (quitar el control) ⇒ 2 tests en rojo. Ningún código nombra un país (`habilitacion.py:1-6`; `grep` de nombres de país en `sentinel/catalog` y `sentinel/redirect` sin tests: solo
  los códigos de zona heredados de `residency.py:22-26`).
- Cambiar la ficha re-evalúa las reglas de habilitación y revoca la relajación cuya ficha deja de cumplir (`admin.py:918-923`; `relaxation.py:35-48`): **solo desde la ficha, ver H2**.
- Habilitar una entrada bloqueada exige `admin` o `compliance_officer`, motivo y deja registro (`admin.py:731-740`), y **no** relaja la residencia (`habilitacion.py:14-16`).
- La tabla de relajaciones lleva el rol en el esquema: `CHECK created_by_role IN ('compliance_officer','super_admin')`
  (`migrations/89a92524eef6…py`, `ck_masking_relaxation_role`), de modo que ni un bug de API deja a un admin de empresa crear una fila.
- **Límite conocido y declarado, fuera de la 057** (research R30 N3): el `tenant_admin` puede dar de alta un usuario `compliance_officer`/`super_admin`
  (`backend/src/api/users.py:413-414`); toda la separación de §1.3 es **por rol** y la documentación (T080) no debe decir «el administrador no puede relajar» sin ese arreglo.

### 1.4 Guard del motor (D14, D15, A3)

- `rdx-*` sin autorización ⇒ 403 (`redirect_guard.py:316-317`), aun con la política apagada; `should_run_guardrail` devuelve siempre `True` en `pre_call`
  (`:397-403`), así que ni `disable_global_guardrails` ni `opted_out_global_guardrails` lo apagan. **Mutación M5** (quitar el `True` incondicional) ⇒ 1 test en rojo.
- `family_mismatch` (`:324-326`): la familia del modelo debe ser la del proveedor firmado; una autorización de un destino con el modelo de otro ⇒ 403
  (test `test_el_guard_rechaza_la_autorizacion_de_un_destino_usada_con_el_modelo_de_otro`). **Mutación M18** (quitar la comparación del modelo) ⇒ 3 en rojo.
- Enmascarado forzado: bloquea si el informe del guardrail de la base no es completo, no degradado y con `detectadas == enmascaradas` (`:118-125,328-330`); el informe solo se lee del
  `home` que escribe el guardrail (`:167-171`), un `masking_report` sembrado por el cliente no cuenta (T092, 85 tests).
- La decisión de ruteo se escribe como `EngineRoutingDecision` confiable bajo `extensions.redirect`, con claves y valores escalares acotados (`:174-221`): **metadata-only**
  (constitución, Seguridad 1 y 6); lo que el cliente siembre en `_internal_routing_decision` se descarta (`:368-375`).
- Orden de guardrails: T020 y T092 comprueban `sentinel-guardian` antes que `redirect-guard` en el config fusionado (`litellm/config.yaml:9-16` + `sentinel/engine/profile-fragment.yaml:50-56`).
  Si el motor ejecutara el orden inverso, el guard no vería el informe y **bloquearía** (`masking_required`): falla cerrado. **El orden real en el motor lo fija T019 (🐳)**.
- Los comodines `rdx-<familia>/*` no llevan credencial (`profile-fragment.yaml:9-48`), con `plugin_owner: redirect` (S6, ocultos de listados). La expansión del comodín en
  `/v1/models` del motor y que `models` de la llave no se aplique con auth propia (R13 (c)) **no se pueden verificar sin el motor real**: T019.

## 2. La extensión apagada no cambia nada (FR-001, FR-007, SC-001)

- **El backend no importa `sentinel`**: `grep -rE "^\s*(from|import) sentinel" backend/src backend/alembic litellm` ⇒ 0. Sin `GATEWAY_PLUGINS` ni `PLUGIN_PACKAGES` no se importa nada
  (`backend/src/plugins.py:1-20`) y sin `ALEMBIC_EXTRA_VERSION_LOCATIONS` la cadena sigue con una sola cabeza (§3).
- **Los archivos de la base que toca T-B** (`git diff 67714f7..HEAD` fuera de `sentinel/` y `specs/`): `backend/Dockerfile.standalone`, `backend/src/main.py`, `frontend/src/plugins/registry.ts`,
  `deploy/**` y `.gitignore`. `docker-compose.yml`, `.env.example`, `litellm/**` y `deploy/docker/**` **no** se tocaron.
  - `backend/src/main.py` relanza la falla de migración solo con ramas de extensión declaradas (`main.py:48-53`).
  - `Dockerfile.standalone:35` migra a `heads` solo con la variable (T088).
  - `registry.ts` (`mergeNav`): con `replaces` **y** una `section` distinta existente, el ítem base se quita y la entrada va tras esa sección; en cualquier otro caso, igual que antes
    (3 tests nuevos en `registry.test.ts`).
  - `publish-elea.sh` suma las `-ext` **después** de las base, con tag propio y **sin mover `latest`**.
  - `deploy/release/{populate_volumes,bundle,render_profile}.sh` y `fragment_merge.py` (S9/S11): sin las variables (sin definir, vacías o solo espacios) los hashes de `config.yaml`, volumen
    y paquete son idénticos.
- **T018 con la extensión montada y la política apagada** (`sentinel/tests/integration/test_no_regresion_con_extension.py`, 38 passed): reusa la batería de T003 y el JSON grabado sin tocarlo.
  **Mutación M6** (el plugin deja de ocultar `rdx-*` en `models_filter`) ⇒ en rojo. Verifiqué además que `models_filter` corre siempre y que `pre_request` sale temprano con política `off`
  y sin posturas (`plugin.py:264-265,284-285`).
- **Atención al leer «apagada»**: en las imágenes `-ext` del motor el `config.yaml` fusionado y `redirect_*.py` van **horneados**: el fragmento (comodines `rdx-*` y `redirect-guard`)
  está presente siempre; lo que decide la activación es **elegir la variante** (opt-in del instalador, T-H). Con la variante del motor y sin `REDIRECT_INTERNAL_KEY` todo `rdx-*`
  da 403/503 (no hay forma de usarlo), pero «idéntico a hoy» solo vale con las imágenes base.
- **Cuando el plugin está montado y la política `off`** el puente de acceso consulta la base en cada pedido de pasarela y de `/v1/models` (`plugin.py:248-256`, `access/bridge.py:100-110`)
  y, si no resuelve, responde 503 (`policy_unavailable`): una instalación con el plugin montado y **sin las tablas migradas** deja sin servicio la pasarela. Es el motivo por el que
  `main.py:48-53` aborta el arranque si falla la migración con ramas de extensión.
- **H4**: con la extensión montada, tres costuras de la base de Sentinel que Eleia no tiene se degradan en silencio.

## 3. Migraciones: segunda cabeza y base compartida con el motor (FR-004b, R5)

Calculado por mí con `ScriptDirectory` + `extend_script_directory` (no con los tests de T016):

| Variable | Cabezas |
|---|---|
| sin `ALEMBIC_EXTRA_VERSION_LOCATIONS` | `['199fe429762a']` |
| con `../sentinel/migrations` | `['199fe429762a', '89a92524eef6']` |

- La rama `sentinel_redirect` es lineal de 8 revisiones; la primera (`0615e56e8251`) tiene `down_revision = None` y `depends_on = '010'`; la última (`89a92524eef6`) cuelga de `f7a3c1d9e508` y
  se generó con `alembic revision` (id por hash) (`migrations/89a92524eef6…py:1-30`). No se portó ninguna migración del backend de Sentinel ni la del asistente de alta (`ls sentinel/migrations`).
- **No empeora la base compartida con el motor** (R5.2): la migración nueva crea solo `sentinel_redirect_region`, `ext_catalog_enablement_rule`, `sentinel_redirect_masking_relaxation` y una
  columna en `ext_compliance_sheet`; las FKs apuntan a `tenants` y `ext_catalog_entry` (`:67-135`). **Mutación M19** (agregar un `ALTER TABLE "LiteLLM_VerificationToken"`) ⇒ 3 de 6 en rojo (T016).
  El orden de arranque (`depends_on`) y el digest del motor no se tocaron (`docker-compose.yml:66-70` intacto). T091 deriva el motor `-ext` del digest base y solo agrega archivos y `pypdf`.
- Riesgo residual **documentado y no resuelto por esta feature**: el migrador del motor puede borrar tablas ajenas sobre una base sin `_prisma_migrations` (R5.2); las tablas `ext_*` y
  `sentinel_redirect_*` quedan expuestas igual que las del backend. `DISABLE_SCHEMA_UPDATE=true` no se fija (`compose.dev.yml` la omite, T021) hasta que T019 la ensaye.
- RLS: `ENABLE` + `FORCE`, `tenant_isolation` estricta y filas de instalación (`tenant_id` NULL) legibles por toda empresa y escribibles solo con bypass (`:57-65,138-141`).
  **Mutación M20** (quitar `FORCE ROW LEVEL SECURITY`) ⇒ 3 de 10 en rojo. **H9**: la política `tenant_isolation_bootstrap` (`:62-64`) deja leer y escribir **todas** las filas a una
  sesión sin `app.current_tenant`; es el mismo patrón de la base (`backend/alembic/versions/010_multitenant_foundation.py:283-288` y `018_workspaces_service_accounts_audit_surface.py:78-86`),
  pero aplica a tablas que guardan posturas, reglas y relajaciones de residencia. La RLS real solo la prueba Postgres (🐳).
- `downgrade` (`:143-147`) borra las tablas y la columna; volver a una imagen sin la extensión después de aplicarla **no está soportado** (FR-004b) y es una advertencia de operación de T-G.
- Entrega: `Dockerfile.standalone` y `deploy/docker/entrypoint/backend.sh` migran a `heads` solo con la variable; el único `alembic upgrade head` que queda es el de
  `.github/workflows/ci.yml:50` y el de `deploy/release/checks/test_profile_renders.sh:26`, ambos **sin** extensión.

## 4. El requisito de modelos chinos y económicos tiene su test (T024, R17)

`sentinel/tests/integration/test_catalogo_modelos_chinos_economicos.py` (33 passed, upstream falso): lee el requisito del owner tal como está escrito en R17 y cubre cada punto aplicable a T-B:

| Requisito | Dónde se prueba |
|---|---|
| Alta de DeepSeek (`deepseek`), Qwen y Kimi (`openai_compatible` + `api_base`), GLM (`zai`) y los mismos por OpenRouter | `:44-53` (8 destinos), `:131-136` (alta por la API real, `blocked_by_default is False`, el secreto no vuelve) |
| El guard los manda a `rdx-deepseek` / `rdx-chatcompat` / `rdx-zai` con la credencial y la base **del destino** | `:143-165` (parametrizado en los 8; el cliente manda `api_base` y `api_key` y no pasan) |
| `cheapest` elige el de menor precio y el costo registrado es el del destino real | `:168-209` (el barato es DeepSeek V3 entre los 8; salta al siguiente si se apaga; sin precio queda al final; cambiar el precio cambia la elección sin reiniciar; el costo viene del precio del destino, no del mapa del motor) |
| Ninguno nace bloqueado con las listas vacías (D1) | `:131-136`; `test_catalog_habilitacion_explicita.py` (71) y `deploy/redirect-seeds/habilitacion-explicita.yaml:13-15` |
| No se sale por un destino ajeno | `:253-260` (autorización de un destino con el modelo de otro ⇒ 403) |

- **Mutación del orden de `cheapest`** (los autores la corrieron; no la repetí) ⇒ 3 en rojo. Mi **M3** (el guard no limpia los campos del cliente) ⇒ 1 test en rojo en el conjunto
  `test_redirect_guard.py` + este módulo (los otros 78 pasan porque `to_litellm_params` vuelve a escribir `api_key` y `api_base`): ver H6.
- **Lo que este test no cubre y está bien que no lo cubra en T-B** (la postura explícita de prueba es `off`, `:109-111`; el default de Eleia es de T-E): que esos destinos salgan
  **enmascarados y bloqueados con el analizador caído** (D2). Eso lo prueba **T057** (`tasks.md:211`, abierta). **H5**: el test ya manda los 4 destinos «por OpenRouter» sin cero retención
  ni lista de proveedores, que FR-032 exige y T058 todavía no implementó.
- Sin prueba real contra ningún proveedor (sin credencial): 🟡 en la documentación (spec FR-011, SC-004).

## 5. Las decisiones del owner contra el estado de T-B

| Decisión | Qué debe haber en T-B | Estado | Evidencia |
|---|---|---|---|
| **Listas vacías (D1, FR-029)** | Mecanismo por datos; seed de Eleia vacío; nada hardcodeado; ninguna entrada nace bloqueada | ✅ | `catalog/habilitacion.py:1-19` (sin proveedor ni país en código; `grep "deepseek"` en `sentinel/` sin tests: solo `redirect_credentials.py` como nombre de familia); `deploy/redirect-seeds/habilitacion-explicita.yaml:13-15` (`providers: []`, `api_hosts: []`, `jurisdictions: []`); T025 71 + 13; las reglas de otra empresa no se aplican (T025) |
| **D12 entidad responsable y jurisdicción de control (FR-028a)** | Campo en ficha y migración; `in_region` exige las tres; control vacío ⇒ no en región; cambia ⇒ re-evalúa y revoca relajación; solo cumplimiento escribe | ✅ en T-B (con **H2**) | `catalog/models.py` + migración `:138-141`; `catalog/region.py:48-57`; `admin.py:48-50,899,918-923`; T087 29 + 5, T099 29 + 4; M2 y M4 en rojo |
| **Roles (FR-023, A6-A8)** | Ficha: solo cumplimiento y super-admin; rol real, no por variable; regiones, `default_posture` y relajaciones por rol real | ✅ la ficha; ⏳ T-E regiones/postura/relajaciones (la tabla ya fuerza el rol, `ck_masking_relaxation_role`) | `admin.py:44-50,899`; ver §1.3 y H8 |
| **Enmascarado por defecto (D2, FR-027, FR-031)** | **T-E** (T053, T060–T064); T-B solo debe no empeorarlo | ⏳ **No cumplido en T-B** (H3) | `residency.py:95-98` (sin filas ⇒ `allowlist`), `:122-132` (`allowlist` nunca fuerza enmascarado), `models.py:189` (columna sin lector), migración `:81` (de fábrica `reject_offregion`) |
| **Región `AMERICAS` editable (FR-030)** | T-E (T064, `regions.americas.yaml`): no existe todavía | ⏳ | `ls deploy/redirect-seeds` = solo 2 seeds |
| **Textos «seudonimización reversible» y 🟡 (D3/D10)** | T-G | ⏳ | n/a (no se tocó `docs/`) |

## 6. White-label, secretos y Definition of Done

- **Secretos**: `sentinel/extensions.env.example` solo trae el marcador `<generar>` (menos de `MIN_KEY_LEN` ⇒ fail-closed) y sin `CATALOG_DIRECT_ENABLED`, `REDIRECT_OPERATOR_TENANT` ni
  `INTERNAL_ALLOWED_CIDRS` (R28, R30, R31); los seeds no llevan valores (`credential_ref` guarda solo nombres de variable, `catalog-seed.azure-demo.yaml:15-27`); `grep` de patrones de
  secreto en `sentinel/` y `deploy/redirect-seeds/` sin tests ⇒ solo la regex que **detecta** secretos (`catalog/validation.py:16`). `test_no_default_secrets.sh` y `test_secrets_not_in_state.sh`
  ya corrieron en T030.
- **White-label**: ningún nombre de `prohibited_names.txt` (`litellm`, `berriai`, `presidio`) en un texto visible (`grep` en `sentinel/frontend` sin tests ⇒ solo `helpers.ts:391`, una lista
  de parámetros protegidos que no se muestra; mensajes de API sin esos nombres). **H7**: `EntryForm.tsx:126` dice «Sentinel los quita antes de llegar al proveedor».
- **Documentación de producto (AGENTS.md DoD)**: T-B **no toca `docs/`**; la doc de la feature es T-G (T079–T086). No hay cambio de API pública de la base (los routers de la extensión
  no se montan sin variable) ni de `.env.example` ⇒ `docs-refs` no aplica a T-B. `make -C deploy check-docs` **no se corrió** (Docker). Mientras T-G no cierre, ninguna página puede decir 🟢.
- **Constitución**: auditoría metadata-only ✔ (§1.4); multi-tenant ✔ salvo H1/H9; onboarding como datos ✔ (los destinos de Azure son seed editable, no código: `catalog-seed.azure-demo.yaml`);
  config + seed, no fork ✔ (paquete copiado tal cual; nombres internos conservados, FR-004a); migración con id por hash ✔; base genérica sin strings de Elea ◐: ninguna cadena ejecutable ni texto de API nombra a Eleia (`grep -niE "\belea\b|\beleia\b"` en `sentinel/` sin tests ⇒ 4 coincidencias, todas
  comentarios o docstrings nuevos de Eleia dentro de código [BASE]: `catalog/habilitacion.py:18`, `catalog/api/internal.py:161`, `migrations/89a92524eef6…py:5,9` y `frontend/catalog/EnablementTab.tsx:3`).
  La regla de la línea («lo que es base se escribe genérico y sin strings de Elea/Eleia para portarlo a Sentinel») pide limpiarlos al armar el HANDOFF (H7).
- **Seed de Azure** (T023): las cuatro entradas llevan jurisdicciones de inferencia, entidad y control **vacías y obligatorias** y sin `api_base`: sin jurisdicción de inferencia se rechaza (FR-028,
  FR-028a); `gpt-5.6-luna` sin precio ni ventana («PENDIENTE», no se inventó); la credencial es la adoptada del motor (`AZURE_API_KEY`, `AZURE_API_VERSION`, ambas en `docker-compose.yml:88,90`).

## 7. Tests corridos (venv local, sin Docker)

| Qué | Resultado |
|---|---|
| `PYTHONPATH=.:backend LITELLM_MODE=PRODUCTION pytest sentinel/tests -q -rs` | **1505 passed, 13 skipped** en 163 s (idéntico a T030; los 13 saltos son los listados en §8 H4, H10 y T017) |
| `cd sentinel/frontend && npx vitest run` | **226 passed** (21 archivos) |
| `bash deploy/release/checks/test_extension_delivery.sh` | ✅ (rc 0) |
| `bash deploy/release/checks/test_ext_images.sh` | ✅ (rc 0) |
| `bash deploy/release/checks/test_standalone_heads.sh` | ✅ (rc 0) |
| `bash deploy/release/checks/test_redis_wiring.sh` | ❌ «no se pudo aislar el servicio 'litellm'» en `compose.prod.yml` y `docker-compose.yml`: **preexistente**, el script y los compose no cambian entre T-A y T-B (H10) |
| Cabezas de alembic, calculadas | `['199fe429762a']` / `['199fe429762a', '89a92524eef6']` (§3) |
| 11 mutaciones sobre la copia de `sentinel/` (scratchpad) | 10 en rojo, 1 en verde (M17, H6): M1 8 de 19 tests, M2 8/29, M3 1, M4 2/29, M5 1, M6 1, M15 8, M18 3, M19 3/6, M20 3/10. Las mutaciones que citan los autores de T016–T024 (p. ej. la del orden de `cheapest`) no las repetí |
| Pruebas descartables (scratchpad, no versionadas) | `api_base` interna aceptada (H1); relajación sobrevive al PATCH (H2); ficha por `tenant_admin` (§1.3, H8) |

**No se corrió** (Docker o red): `make -C deploy check`, `check-docs`, `docs-refs`, `docker compose run --rm --no-deps backend pytest tests/ -q`, `test_backend_image.sh`,
`test_frontend_image.sh`, `test_no_engine_name.sh`, T019 y la construcción real de las tres `-ext`. El backend `tests/unit` + `tests/contract` y `cd client && npm test` no los corrí:
T030 declara 1346 passed / 6 failed (los 6 que piden el host `db`, idénticos en la base) y 43 passed; el cambio de T-B en `backend/` es de 6 líneas (`main.py:48-53`) con su test.

---

## 8. Hallazgos en detalle

### H1 — `api_base` sin validar en las entradas de empresa (alta; decisión del owner antes de activar)
- **Evidencia**: `EntryIn.api_base`/`EntryPatch.api_base` solo limitan la longitud (`catalog/api/admin.py:396,423`); `_check_binding` solo exige que **exista** para los proveedores que lo
  requieren (`:291-304`); no hay validación de esquema, host ni rango en `catalog/validation.py` ni en el alta (`:568-574`). **Prueba descartable**: `POST /api/v1/catalog/entries` como
  `tenant_admin` con `provider=openai_compatible` y `api_base` = `http://169.254.169.254/latest`, `http://engine:4000/v1`, `http://db:5432`, `http://127.0.0.1:8000/api/v1/gw/v1`,
  `file:///etc/passwd` y `ftp://x` ⇒ **201** en los seis. El guard fija esa `api_base` en el pedido (`redirect_guard.py:346`, `redirect_credentials.py:275-276`) y el motor la llama con la
  credencial de la entrada. Para las entradas `azure` (que exigen `api_base`) la sonda de despliegue lo hace además **sola en el alta** (`:591-592`) y en `POST /entries/{id}/check`
  (`:697-706`, `default_deployment_probe` `:328-352`): un «ping» fijo por la ruta del guard, del que solo vuelve un estado. Por la ruta normal de las caras, lo que el destino responda con
  forma de respuesta de modelo se devuelve al cliente (`plugin.py:map_response` solo reescribe el campo `model`); lo que no tenga esa forma falla en el motor. Es una **lectura ciega** en
  la sonda y de alcance limitado en la ruta normal (el motor agrega `/chat/completions` o `/v1/messages` a la base): no probé el alcance real, que requiere el motor (🐳).
- **Qué rompe**: Constitución III y Seguridad 4 (aislamiento de tenant): un admin de una empresa hace que el motor compartido alcance la red interna de la instalación o la de otra empresa
  (un SSRF desde el motor). El spec cubre el desvío **por el cliente** (FR-014) y por la **credencial** (FR-013), pero **ni la spec, ni el plan ni R5/R31 hablan de la dirección que carga el
  admin** (`grep -i "ssrf\|loopback\|private"` en `spec.md`/`research.md`/`qa-plan*.md` ⇒ 0 sobre esto). Es la paridad con Sentinel, no una regresión de T-B.
- **Matiz**: la constitución III también pide servir modelos locales (Ollama/vLLM) en instalaciones on-prem de un solo tenant, donde `api_base` privada es legítima.
- **Corrección propuesta** (por `speckit-clarify`/`speckit-tasks`, no a mano; es del owner): para entradas de **empresa**, exigir `https` y rechazar hosts de loopback, link-local,
  rangos privados y nombres de servicio de la red de compose, salvo un interruptor de **instalación** (`CATALOG_ALLOW_PRIVATE_API_BASE`, apagado por defecto; encendido por el operador en
  on-prem de un solo tenant); las de instalación (solo `super_admin`) no cambian. Test en `sentinel/tests/contract/test_catalog_api.py`. Vuelve a Sentinel por HANDOFF.

### H2 — La relajación por destino sobrevive al cambio del destino (alta para T-E; hoy no explotable)
- **Evidencia**: `revoke_unmet` se llama solo desde `put_sheet` (`catalog/api/admin.py:923`); `update_entry` (`:624-694`) re-evalúa las reglas de habilitación con `identity_changed`
  (`:682-684`) pero **no** revoca relajaciones, y `unmet_preconditions` (`relaxation.py:35-45`) no ve cambios de `provider`, `api_base` ni `real_model`. **Prueba descartable**: con una fila
  vigente en `sentinel_redirect_masking_relaxation` para una entrada con ficha completa, `PATCH /entries/{id}` como `tenant_admin` con `{"api_base": "https://otro-host.example.com/v1"}`,
  `{"provider": "openrouter", ...}`, `{"real_model": "otro-modelo"}` o `{"is_aggregator": false}` ⇒ **200** y la relajación sigue **vigente** en los cuatro casos.
- **Qué rompe**: FR-031a («relajación por destino sobre una entrada del catálogo … nunca es un default … el administrador de la empresa no puede relajar», D5 «alojadores nombrados») y
  FR-023: cumplimiento relaja el enmascarado forzado hacia *ese alojador*; el admin de empresa, que sí edita `api_base` y `provider`, lo apunta a otro host sin perder la relajación.
  data-model §3 (`:217-219`) solo define re-evaluación al **resolver el pedido** (T060, ficha) y al **guardar la ficha** (T087); no dice qué pasa al cambiar la identidad del destino.
  Hoy no hay API que cree relajaciones (T060) ni nada que las lea.
- **Corrección propuesta** (T060/T087 por `speckit-tasks`): `update_entry` llama `revoke_unmet` y revoca con `revoke_reason = destino_modificado` cuando cambian `provider`, `api_base`,
  `real_model`, `is_aggregator` o `provider_options.providers_allowlist` de una entrada con relajación vigente; y T060 evalúa la identidad firmada del destino al resolver. Test
  nuevo por cada campo, con la prueba de §7 como esqueleto.

### H3 — Interino de T-B: sin el default de D2 (alta; condición de activación)
- **Evidencia**: sin filas de postura y con un pedido redirigido, `effective_posture` devuelve `allowlist` con las jurisdicciones de la región (`residency.py:95-98`) y `evaluate` en
  `allowlist` nunca marca `forced_masking` (`:127-132`): un destino **en región** sale sin el enmascarado forzado que D2 manda para todo destino. La columna `default_posture` existe
  (`models.py:189-190`, migración `:81-87`, de fábrica `reject_offregion`) pero **ningún código la lee** (`grep default_posture` sin tests: solo esas dos definiciones). La región del
  pedido cae a `eu` si falta la variable: `plugin.py:134-137`, `redirect/api/admin.py:571`, `redirect/api/us5.py:197`, y los compose la fijan con default `eu`
  (`docker-compose.yml:101,217`, `deploy/docker/compose.prod.yml:122,215`), mientras que el catálogo resuelve «sin variable ⇒ ninguna región» (`catalog/region.py:21-23`): dos resoluciones
  distintas de lo mismo. `regions.americas.yaml` no existe.
- **Qué rompe**: D2 (decisión del owner: enmascarado forzado con analizador fail-closed para todo destino), FR-027, FR-031 y QA B2 («la región de la instalación no cae a un valor de otra
  línea»; respaldo en código `masked_all`). Son tareas **de T-E** (T053, T060–T064; `compose.dev.yml` default de `SENTINEL_ENTITY_REGION`), así que no es un defecto de T-B: **es el
  estado intermedio.** Falla cerrado hacia afuera (una región `eu` no admite destinos de América) pero **abierto hacia adentro** (un destino en región sale sin forzado y, si la empresa tiene
  `redact_enabled=false`, sale sin enmascarar).
- **Condición**: ninguna instalación activa la extensión (variante `-ext` + variables) antes de T-E cerrada. La activación es opt-in (T-H) y `sentinel/extensions.env.example` no se usa solo, pero
  conviene que T-H lo verifique con un test («`ELEA_REDIRECT=1` exige el seed de región cargado»).

### H4 — Costuras de la consola ausentes: degradación silenciosa (media)
- **Evidencia**: `sentinel/catalog/api/__init__.py:4-31` registra tres enganches y cada uno se traga el `ImportError`: `src.services.residency_heuristic` (`:4-12`),
  `src.services.access_hook` (`access/bridge.py:113-118`, que **deja `_registered = True` antes** de importar, así que la pasarela sí aplica perfiles pero la consola no) y
  `src.services.model_route_hook` (`catalog/chat_route.py:113-117`). `ls backend/src/services | grep hook` ⇒ ninguno existe. Se ven en los saltos: `test_chat_route.py:15`,
  `test_unsupported_params.py:223`, `test_semaforo_parity.py:239` (todos «requiere el venv/`src.services.*`»).
- **Qué significa**: (a) el chat de la consola **no** aplica los perfiles de acceso del catálogo, así que un usuario al que un perfil le quita un modelo gobernado lo sigue pudiendo usar
  desde la consola (la pasarela sí lo corta, `plugin.py:302-312`); (b) la consola no sirve las entradas del catálogo (FR-006 «la consola queda fuera» se cumple por **ausencia**, no por diseño);
  (c) la residencia de proyectos de la base no consulta el semáforo del catálogo. `AccessTab.tsx` no promete lo contrario.
- **Qué rompe**: FR-003 (toda adaptación debe estar en el registro de cambios con plan de salida): `access_hook`, `model_route_hook` y `residency_heuristic` **no figuran** en
  `spec.md`, `plan.md`, `research.md`, `data-model.md` ni `tasks.md` (salvo como motivo de saltos en T017/T030). FR-052 (documentación honesta): T-G debe decirlo.
- **Corrección propuesta**: registrarlo como adaptación (R3), con un test que fije el comportamiento «sin costura ⇒ sin error ni efecto» (hoy lo cubren por casualidad los saltos) y una
  frase en la documentación de T-G: «los perfiles de acceso rigen en la pasarela, no en el chat de la consola». Va por HANDOFF a Sentinel como las demás.

### H5 — OpenRouter sin cero retención (media; abierta en T058)
- **Evidencia**: el guard fija `api_key` y `api_base` desde la autorización (`redirect_guard.py:344-346`) y **no** agrega `provider`/`zdr`/`data_collection`/`only` para OpenRouter
  (`grep` de `data_collection|zdr|allowed_providers` en `sentinel/` sin tests ⇒ solo `catalog/relaxation.py:28`, que lee `providers_allowlist`). T024 da de alta cuatro destinos
  `openrouter` y los pide por la pasarela real (`test_catalogo_modelos_chinos_economicos.py:49-52`). T058/T061 (FR-032) están abiertas.
- **Qué rompe**: FR-032 («para destinos vía OpenRouter, cero retención y la lista de proveedores del admin en cada pedido»), D5 («OpenRouter con lista de proveedores de EE. UU.») y R17.5.
  No es explotable sin la extensión; sí aplica a quien la active y cargue un destino OpenRouter antes de T-E.
- **Corrección**: T058/T061 como están; mientras tanto, **no** documentar OpenRouter como destino utilizable (🔵) y que T-H no ofrezca seeds con destinos `openrouter`.

### H6 — Cotas sin test (baja)
- `MAX_TTL = 120` (`engine/redirect_authz.py:31`, comprobada en `:114`): **mutación M17** (`MAX_TTL = 100000`) ⇒ `test_redirect_authz.py` pasa (25 passed): un `ttl` enorme en
  `issue` no lo detecta ningún test. No es explotable (solo emite la pasarela con `DEFAULT_TTL`), pero el contrato «la autorización vive ≤ 120 s» no está fijado.
- **M3** (el guard no limpia los campos del cliente, `redirect_guard.py:332-333`) ⇒ **1** test en rojo entre 82: `to_litellm_params` reescribe `api_key` y `api_base`, y los demás campos de
  `CLIENT_CREDENTIAL_FIELDS` (`aws_*`, `vertex_*`, `organization`, `extra_headers`, …) solo los cubre ese test. Hoy está bien; un test por familia de campos baja el riesgo si alguien reordena el guard.
- **Corrección**: dos tests chicos en `test_redirect_authz.py` y `test_redirect_guard.py`.

### H7 — «Sentinel» en un texto visible (baja)
- `sentinel/frontend/catalog/EntryForm.tsx:126`: «…este modelo rechaza: Sentinel los quita antes de llegar al proveedor…». No viola `prohibited_names.txt` (`litellm`, `berriai`,
  `presidio`) pero es el nombre de otro producto en el panel de Eleia. FR-004a conserva **nombres internos** (tablas, ids, rutas), no textos de cliente. Corrección genérica y que vuelve por
  HANDOFF: «la pasarela los quita…» (como `PolicyTab`).
- Mismo problema en código [BASE] (comentarios y docstrings, no se ven al cliente) con el nombre de Eleia: `catalog/habilitacion.py:18`, `catalog/api/internal.py:161`,
  `migrations/89a92524eef6_redirect_region_y_habilitacion.py:5,9`, `frontend/catalog/EnablementTab.tsx:3`. Los marcadores `[ELEIA]` de los seeds de `deploy/redirect-seeds/` son de la capa
  de Eleia y están bien. Se limpian al preparar el HANDOFF (T-G) para que el porte a Sentinel no arrastre el nombre.

### H8 — Campos de la ficha que el admin de empresa edita y alimentan el semáforo (baja)
- `SHEET_FIELDS` (`catalog/store.py:22-24`) incluye `logs_jurisdiction`, `trains_on_data`, `transfer_mechanism`, `dpa_registry_id` y `eu_region_contracted` además de los cinco de
  FR-023; `put_sheet` solo gatea los cinco (`admin.py:48-50,899`) y la prueba de §1.3 confirma que `tenant_admin` los cambia (200). Esos campos entran en `semaforo_of`
  (`store.py:50`) que decide admisibilidad y perfiles de acceso. No afectan al enmascarado ni a las precondiciones de la relajación (`relaxation.py:35-45` solo usa los cinco).
- **Qué vigilar**: FR-030a (T063) evalúa el semáforo contra la región: si el semáforo pasa a gobernar algo de residencia, hay que decidir si esos campos pasan a `RESIDENCY_FIELDS`.

### H9 — RLS permisiva `tenant_isolation_bootstrap` en las tablas nuevas (info)
- `migrations/89a92524eef6…py:57-65` crea `tenant_isolation` estricta **y** `tenant_isolation_bootstrap` (`NULLIF(current_setting('app.current_tenant', true), '') IS NULL`): una sesión
  sin tenant ve y escribe todas las filas. Es lo que hace la base (`010:283-288`, `018:78-86`) y `database.py:38-42` lo describe como ventana de deploy; `FORCE` evita el atajo del dueño de la
  tabla. No es un defecto de T-B; sí significa que el aislamiento por empresa de `sentinel_redirect_region`, las reglas y las relajaciones depende de que **toda** sesión fije el tenant.
  Los canales internos lo hacen (`internal.py:49-60`); la comprobación real es la suite 🐳 (FR-051 queda 🟡, como dice T030).

### H10 — El gate `make -C deploy check` no queda verde por dos checks ajenos (info)
- `check-redis-wiring` busca un servicio `litellm` que ya se llama `engine` (`deploy/release/checks/test_redis_wiring.sh:53-56`; el script y los compose no cambian entre T-A y T-B) y
  `check-extension-whitelabel` pide `extension/` y `deploy/clients/camara-comercio/brand.extension.json` (`deploy/Makefile:93-96`). T030 los declara y los atribuye a la base; **lo verifiqué
  para el primero**. AGENTS.md: «el gate del release es la verdad … verdes antes de pedir merge»: ambos tienen que repararse (fuera de la 057) o el owner debe aceptar la excepción
  escrita.
- Evidencia de T030: «los 13 son `test_chat_route` y 1 de `test_unsupported_params`, 6 módulos…» mezcla conteos (cada módulo saltado entero cuenta 1 en `-rs`); mi corrida lista 13 saltos
  exactos: `test_chat_route:15`, `test_unsupported_params:223`, `test_conservar_modelos_consola:19`, `test_delivery_wiring:17`, `test_servicios_toman_catalogo:16`, `test_catalog_seed:110`,
  `test_console_pages:63`, `test_fragment_merge_parity:59`, `test_semaforo_parity:239`, `test_redirect_gateway_e2e:245` y 3 en `test_redirect_guard:347,355,366`. Ninguno es de
  migraciones, RLS, resolución ni credenciales, salvo el **bloque de H4** (`test_chat_route`), que sí es de credenciales del chat.

### H11 — Canal interno: dependencias ausentes en esta rama (info)
- `_require_internal_secret` sigue con **solo el secreto** (`backend/src/api/internal.py:120-127`); `INTERNAL_ALLOWED_CIDRS` no existe en el backend (`grep` ⇒ 0; solo un comentario de
  `compose.dev.yml:22`). El secreto de ejemplo es público: `.env.example:61` y `docker-compose.yml:85` (`sentinel_master_key_9999`).
- Con la extensión, `/api/v1/internal/model-catalog` (catálogo con `api_base`, proveedor, precio) y `/model-access` (permitidos por identidad) pasan a existir; sin credenciales y detrás del
  secreto. R31 acepta este corte: la credencial de proveedor queda cerrada por T090 y las capas 2 y 3 (S15 y proxy del instalador) las trae el arreglo de bases; el gate pasa a T-H
  (T089, T100, T101, T102). **Confirmo que la rama no resuelve ni empeora** las capas 2 y 3; la verificación («`/api/v1/internal/*` ⇒ 404 desde la LAN con la variante `-ext`») es de T102.

### H12 — Denylist de entorno y atribución del guard (info)
- La denylist (`redirect_credentials.py:81-84`) no incluye `MASKING_NONCE_KEY` (variable de T-F, T093 abierta): cuando exista en el entorno del motor, una referencia `env:MASKING_NONCE_KEY`
  de un `super_admin` la pasaría. Es de T093; queda el recordatorio.
- `redirect_guard.py:217` condiciona `mark_attribution` con `hasattr`: Eleia no trae el canal confiable de atribución de la 069, así que la capa `model_redirect` **no** aparece en
  `applied_layers` de la auditoría (tres tests saltados, `test_redirect_guard.py:347,355,366`). La decisión sí queda en `routing_decision.extensions.redirect` (FR-047). Anotar en el registro
  de adaptaciones.

## 9. Lo que queda para el gate 🐳 y para otros tramos (con aviso al owner)

1. **T019** (spike D14): orden real de guardrails, comodines `rdx-*` sin credencial, `models` de la llave con auth propia, rechazo del cuerpo con `api_base`, expansión del comodín en
   `/v1/models`; `DISABLE_SCHEMA_UPDATE=true` sobre una base existente. **Si falla: parar y re-planear.** Hasta entonces los puntos de §1.4 son «correctos según el código y los dobles».
2. **Suite del backend en contenedor**, `make -C deploy check` (con H10 resuelto o aceptado), `check-docs`/`docs-refs` si T-G ya cambió docs.
3. **RLS real** de las tres tablas nuevas y de las siete heredadas (FR-051 🟡), con Postgres.
4. **Construir las tres `-ext`** y confirmar usuario y `pip` del motor, el `vite build` de verificación del panel y `import sentinel.redirect.api` en el backend (T091, T030).
5. **Antes de activar** (T-H): H1 decidido, H2 y H3 cerrados en T-E, H5 con T058, H11 con T102.
6. **HANDOFF a Sentinel** (T-G): H1, H2, H4, H7, el cambio de `mergeNav` (T029) y el de `fragment_merge`.
