# Research — 057 Porte de la redirección de modelos (Sentinel 068)

**Fecha**: 2026-10-06 · **Fuentes de solo lectura**: Sentinel `origin/main` `6a70855`, HANDOFF
`docs/handoff-068-elea` `8c525db`, spike `specs/ANALISIS-SEPARAR-BASES-MOTOR-2026-10.md` (rama
`cluna-8/spike-separar-bases-motor`). `sentinel:` = archivo de Sentinel en `6a70855`; sin prefijo =
este repo.

Formato: **Decisión** · **Por qué** · **Alternativas**. Las decisiones D1–D4 (R13–R16) tenían opciones
abiertas y se preguntaron al coordinador. **Respuesta del owner (2026-10-06)**: D2 = A, D3 = A, D4 = A;
D1 = mecanismo A (todo por datos); el **valor por defecto** que siembra Eleia quedó pendiente de un
análisis legal, y por la misma razón el default de postura sin postura explícita pasó a ser
**configurable** (R23).

**Decisiones del owner sobre el análisis legal (2026-10-06)** — `specs/ANALISIS-TRANSFERENCIAS-AMERICA-2026-10.md`
§5 (rama `cluna-8/spike-transferencias-america`, `a5a88e2`), volcadas en la spec por `speckit-clarify`
(Clarifications, Session 2026-10-06, decisiones legales):

| Decisión del análisis | Qué decidió el owner | Dónde queda |
|---|---|---|
| D1 | Sin bloqueo de APIs chinas por defecto: el mecanismo por datos queda y las listas de Eleia se siembran **vacías** | spec FR-029; R14; T028 |
| D2 | Todo el tráfico redirigido sale **enmascarado por defecto** (enmascarado forzado con analizador fail-closed, dentro y fuera de `AMERICAS`); cumplimiento lo relaja por destino o por región; se rechaza solo lo que no tiene jurisdicción de inferencia | spec FR-027, FR-031, FR-031a, US3 esc. 5 y 8; R23, R24; T053, T064 |
| D5 | Modelos chinos alojados en América, en alojadores nombrados y con retención cero: configurables **sin** enmascarado forzado por relajación explícita, nunca por defecto | spec FR-031a, US3 esc. 10; R24; T057 |
| D12 | El catálogo registra entidad responsable y jurisdicción de control (≥ 50 % o control), además de la de inferencia; «en región» exige las tres | spec FR-028a, US3 esc. 11; R25; T087, T054, T060 |
| D3, D10 | «Seudonimización reversible», nunca «anonimización» ni «cumple con X»; `AMERICAS` es criterio de riesgo, no de legalidad; leyenda 🟡 hasta la revisión legal | spec FR-030, Assumptions «Base legal»; R26; T079, T080 |

**Convención de nombres**: en este documento, «D1–D4» a secas son las decisiones de diseño del plan
(R13–R16); las del análisis legal se citan «D1 legal», «D2 legal», etc. (en la spec, en la tabla de
arriba y en R23–R26 siempre son las legales). Con esto se cierran los dos valores que el plan dejaba
pendientes (R14 y R23). Las decisiones D1–D4 del
plan (R13–R16) y la enmienda del 403 (R21) no se reabren.

---

## R1. Cómo se traen las costuras: cherry-pick de Sentinel

- **Decisión**: `git cherry-pick -x` de los commits **de Sentinel**, en el orden de HANDOFF §1(a)
  (16 commits) y después `9c17500` y `efb2c94` (Anexo A §A.1); los dos archivos de ADAPT-024 con
  `git checkout 14edbc7 -- backend/src/services/encryption_service.py
  backend/tests/unit/test_encryption_multifernet.py` (nunca el commit entero: trae symlinks por error,
  HANDOFF fila 17). Cada conflicto *modify/delete* sobre `docs/sentinel/04-REGISTRO-DE-CAMBIOS.md`,
  `specs/045-…/tasks.md`, `specs/069-…/tasks.md` y `deploy/clients/nix/config.yaml.tmpl` se resuelve
  con `git rm` (HANDOFF §1(a), §A.1).
- **Por qué**: Eleia ya usa los nombres `sentinel_*` en el motor y la pasarela; desde Sentinel, S2 da
  3 conflictos y desde la base `guardian-secure`, 11 (medido, HANDOFF encabezado). El orden y los hunks
  ya se ensayaron sobre `8999e27` (HANDOFF §A.4): `gateway_openai.py` y su test quedan idénticos a
  `efb2c94`.
- **Alternativas**: reescribir las costuras a mano (pierde trazabilidad `-x` y la paridad); traerlas de
  la base (más conflictos y PRs de la base todavía abiertos).

## R2. Resolución de los hunks

- **Decisión**: la resolución **mínima ensayada** de HANDOFF §1(a) y §A.1: `7a4f65c` conserva el
  `engine_params` de Eleia y el `_visible_entries(...)` de Sentinel en `update_model_credential`;
  `6161bf0` deja solo `mount_plugin_routers(app)` antes de CORS (sin `TrialReadOnlyMiddleware`);
  `e3a5297` suma solo `ctx=None` a `_byok_proxy` y usa `_respuesta_destino(ctx, …)` con el mensaje de
  error de Eleia, sin `require_not_trial_expired`; `9c17500` deja la firma
  `ruta_motor: str = "/v1/messages", error_fn=None, ctx=None`, `(error_fn or _anthropic_error)(…)` con
  `sanitize_engine_error`, y en `main.py` primero `gateway_openai` y después `mount_plugin_routers`,
  ambos antes de CORS (orden de ADAPT-022). El logger `sentinel-secure-gateway.plugins` de `6161bf0` se
  conserva si coincide con el prefijo de loggers de Eleia; si no, se ajusta y se anota.
- **Por qué**: es lo único medido; el «atajo» de tomar la firma completa en `e3a5297` no se ensayó.
- **Alternativas**: el atajo de §A.1 (menos hunks en `9c17500`, sin evidencia).

## R3. Registro de adaptaciones de Eleia (FR-003)

- **Decisión**: cada tramo deja sus entradas `ADAPT-0xx` / desvíos en el mensaje del commit (con
  «plan de salida»), y T-G las consolida en `specs/057-…/CHANGELOG.md` (precedente: `CHANGELOG.md` de las
  specs 050 y 051) y en `HANDOFF-elea-a-sentinel.md`. Se reescriben ahí las entradas de Sentinel que
  aplican: ADAPT-017 (puerta OpenAI), ADAPT-022 (orden de montaje), ADAPT-024, ADAPT-026, y ADAPT-018
  como «no se trae: Eleia tiene `f8118e7`».
- **Por qué**: Eleia no tiene `docs/sentinel/04-REGISTRO-DE-CAMBIOS.md`; un único archivo escrito por
  un solo tramo respeta la propiedad exclusiva de archivos.
- **Alternativas**: crear un registro global nuevo en `docs/` (fuera del sitio, sin precedente en el
  repo); que cada tramo edite el mismo archivo (rompe la exclusividad).

## R4. Paquete de la extensión

- **Decisión**: `git checkout 6a70855 -- sentinel` y quitar `sentinel/onboarding/` y
  `sentinel/migrations/b8c4d7e2a915_wizard_profile.py` (HANDOFF §1(b)). Se conservan nombres de
  paquete, tablas, etiqueta de migraciones y rutas internas (paridad, HANDOFF §4.5). Los cambios que
  Eleia haga dentro de `sentinel/` son genéricos y vuelven por HANDOFF (T-G).
- **Por qué**: es capa 2, la base no la conoce; reproducir ~40 PRs no aporta nada. Desde la E3 de la
  069 los destinos de la redirección son las entradas del catálogo, así que `sentinel/catalog`,
  `sentinel/access` (por import en `sentinel:sentinel/redirect/plugin.py`) y `sentinel/common`
  (versión de instantánea) son necesarios (HANDOFF §1(b)).
- **Alternativas**: copiar solo `redirect/` (no arranca: imports); neutralizar nombres (decisión aparte
  coordinada con Sentinel, spec §Assumptions).

## R5. Migraciones de la extensión y la base compartida con el motor

- **Decisión**:
  1. Rama propia `sentinel_redirect` colgada de `010`, con `upgrade heads` solo si
     `ALEMBIC_EXTRA_VERSION_LOCATIONS` está definida (S4, `1021c8e`). Sin la variable:
     `heads = ['199fe429762a']`; con ella: `['199fe429762a', 'f7a3c1d9e508']` (HANDOFF §1(c)), y la
     migración nueva de Eleia (R13, R14) cuelga de `f7a3c1d9e508`, con id por hash
     (`alembic revision`), así que la cabeza de la extensión pasa a ser ese hash. No se reapunta
     `0615e56e8251` a `199fe429762a` (rompería la paridad). No se porta ninguna migración del backend
     de Sentinel (`019`–`025`: ids que chocan).
  2. **No empeorar el riesgo de la base compartida**. El spike verificó que el migrador del motor
     borra tablas ajenas cuando la base no tiene `_prisma_migrations` o cuando una imagen nueva del
     motor aplica migraciones pendientes (`ANALISIS-SEPARAR-BASES-MOTOR` §1.3). Las tablas de la
     extensión quedan expuestas igual que las del backend, pero **sin agregar disparadores**: (a) solo
     tablas con prefijo `sentinel_redirect_`/`ext_`, nunca `LiteLLM_*` ni `_prisma_migrations`, con FKs
     solo a `tenants`, `groups` y tablas propias; (b) ningún cambio al orden de arranque
     (`depends_on`), ni a la versión ni al digest base del motor (la variante `-ext` de R27 deriva de ese digest y solo
     agrega archivos y `pypdf`; T102 verifica que no cambie `_prisma_migrations`); (c) el plano motor de la extensión no
     lee la base: habla por HTTP interno (`sentinel:sentinel/engine/redirect_catalog.py:71-133`), y la
     ruta directa queda apagada (`CATALOG_DIRECT_ENABLED` vacío); (d) T016 lo verifica con un test
     offline sobre el `ScriptDirectory`; (e) las pruebas en vivo corren sobre la base existente de
     desarrollo (libro del motor presente) o con bases separadas, nunca con una base nueva y el backend
     primero. `DISABLE_SCHEMA_UPDATE=true` en el motor es una **hipótesis sin respaldo experimental**
     (el spike la propone pero no la ensayó: `ANALISIS-SEPARAR-BASES-MOTOR` §7 ítem 8 y §8.10), y con
     ella un motor sobre una base nueva no crea sus tablas: el override de desarrollo **no** la fija por
     defecto; T019 la ensaya (base existente con y sin el flag, sin borrado de tablas ajenas) y solo si
     pasa se agrega al override y al quickstart (QA A5). El instalador comparte base entre backend y
     motor y baja el motor por digest o `:latest` (spike §1.4): las tablas `sentinel_redirect_*`/`ext_*`
     y `alembic_version` quedan expuestas al baseline destructivo igual que las del backend; si el
     baseline borra `alembic_version`, el siguiente arranque con `upgrade heads` reaplica la rama de la
     extensión sobre una base vacía de sus datos (riesgo del plan).
  3. El rollback a una imagen sin la extensión, una vez aplicadas sus migraciones, no está soportado
     (HANDOFF §1(c)): se documenta en operación (T-G, FR-004b).
- **Por qué**: la separación de bases es deuda de las dos líneas con su propio spike; esta feature no
  la resuelve pero tampoco la agrava (spec §Assumptions «Riesgo — base de datos compartida»).
- **Alternativas**: reapuntar la rama a `199fe429762a` (rompe paridad); una base propia para la
  extensión (agrega una tercera conexión y otra superficie de RLS: desproporcionado para el MVP).

## R6. Entrega de la extensión (S9, S11, S12, desarrollo)

- **Decisión**:
  - **S9 [BASE, nueva]**: `deploy/release/populate_volumes.sh` y `bundle.sh` copian, además de
    `litellm/extensions/*.py` (`populate_volumes.sh:45-46`, `bundle.sh:98-99`, `:186-187`), los
    archivos de una variable opcional `EXTRA_ENGINE_EXTENSIONS` (lista de rutas); vacía ⇒ idéntico.
  - **S11 [BASE, nueva]**: `deploy/release/render_profile.sh` (hoy solo templa,
    `render_profile.sh:29`) fusiona los fragmentos de `PROFILE_FRAGMENTS` con un fusionador de base
    nuevo, `deploy/release/fragment_merge.py`, que replica el contrato de
    `sentinel/engine/fragment_merge.py` para que la base no dependa de la ruta de la extensión (contrato
    de la 068: `model_list` y `guardrails` al final; duplicados ⇒ error de render); vacía ⇒ idéntico
    byte a byte.
  - **S12**: `EXTRA_ENV_FILE` (`933c513`) en producción; el archivo de variables de la extensión vive
    fuera del repo (modo 600), como en Sentinel (HANDOFF §2.1).
  - **Desarrollo [nuevo]**: `sentinel/docker/compose.dev.yml` (override opcional que se pasa con
    `-f`): monta `./sentinel` en `/opt/sentinel-ext/sentinel` con `PYTHONPATH`, monta
    `sentinel/engine/redirect_*.py` en las extensiones del motor y el `config.yaml` fusionado, y fija
    las variables de HANDOFF §2.1 desde un `.env` local ignorado. Cubre la T021 de Sentinel, que no hizo.
- **Por qué**: Sentinel reemplazó S9/S11 con su `deploy.sh` de nix (HANDOFF §1(a) «No hacen falta»),
  que Eleia no tiene. **Corrección (QA B1)**: `render_profile.sh`, `populate_volumes.sh` y `bundle.sh`
  son el camino de los **perfiles de cliente** (`deploy/clients/*`, terraform, paquete air-gapped:
  `deploy/clients/itv-examen/README.md:40`, `deploy/terraform/README.md:15`, `bundle.sh:57`); S9/S11
  sirven a ese camino. El instalador de Eleia (`cluna-8/elea-installer`) **no** consume `rendered/`
  ni volúmenes: baja imágenes publicadas por `deploy/release/publish-elea.sh:25` (backend desde
  `backend/Dockerfile.standalone`, que hornea `backend/` y `litellm/extensions/`, `:22-23`; motor desde
  `litellm/Dockerfile:7-8`, que hornea `config.yaml` y `extensions/`). La entrega a ese camino es R27.
- **Alternativas**: editar `docker-compose.yml` de la raíz (cambia la base para todos); un script de
  despliegue propio estilo nix (duplica el camino de release).

## R7. Spike D14 sobre el motor fijado

- **Decisión**: T019 repite el spike D14 de la 068 (familias comodín `rdx-*` sin credencial; el guard
  `pre_call` fija credencial y base por pedido; `rdx-*` sin autorización ⇒ rechazo) contra la imagen de
  `litellm/Dockerfile:6`, con el `spike053/` de Sentinel como guion. Si falla, se para y se re-planea.
- **Por qué**: la spec lo exige (§Assumptions «Versión del motor»). El spike de bases leyó `1.92.0`
  en la imagen fijada (la misma versión del spike de Sentinel), pero la spec 053 cita `1.95.1`
  instalado: hay que confirmar qué corre de verdad.
- **Alternativas**: confiar en la coincidencia de versión (sin evidencia del servidor).

## R8. Panel: pantalla única «Modelos» — ver R15 (D3)

## R9. Catálogo de Azure de la instalación (FR-020)

- **Decisión**:
  - Credencial **adoptada**, sin duplicar el secreto: la entrada referencia `AZURE_API_KEY` con
    `allow_any_env` (`sentinel:sentinel/catalog/credentials.py:56-68`) más `api_version`, forma que
    exige `azure` (`sentinel:sentinel/engine/redirect_credentials.py`, `SHAPES["azure"]`); `api_base`
    = el del recurso.
  - **Verificación del despliegue** (equivalente de la 069 T178, que no está en `6a70855`): al dar de
    alta o editar una entrada `azure`, el catálogo hace una prueba mínima (pedido de 16 tokens por la
    ruta del guard) y traduce el «Resource not found» de Azure a «El despliegue `<x>` no existe en el
    recurso configurado»; la entrada queda `inactive` con aviso hasta que pase. Genérica, vuelve por
    HANDOFF.
  - Datos de ejemplo de la demo en `deploy/redirect-seeds/catalog-seed.azure-demo.yaml` **[ELEIA]**,
    cargados con `python -m sentinel.catalog.seed` (idempotente). Destinos: `gpt-5.1-chat`,
    `gpt-5.4-mini`, `gpt-4o-mini` (tres modelos conversables de `litellm/config.yaml:35-74`; la cuarta
    entrada `azure/*` es `router-embeddings`, no conversable) y `gpt-5.6-luna`, que **no** está en el
    repo ni hay evidencia de su despliegue en el recurso: queda **a confirmar con el owner** antes de
    T045 (si no existe, opus → `gpt-5.1-chat`; QA M2). La jurisdicción de inferencia **no**
    se presume (spec §Assumptions): el seed la deja vacía y el quickstart obliga a cargarla.
- **Por qué**: el síntoma del 6-oct («Resource not found», HANDOFF §2.4) es un `real_model` que no
  coincide con un despliegue (HANDOFF §4.1).
- **Alternativas**: listar despliegues por la API de gestión de Azure (otra credencial y otro permiso);
  no verificar (deja el error opaco que FR-020 prohíbe).

## R10. T139 de Sentinel: campos desconocidos hacia destinos traducidos

- **Decisión**: `normalize_for_translated` (`sentinel:sentinel/redirect/faces/claude.py:255`) pasa a
  trabajar con una **lista permitida** de campos de primer nivel de la Messages API (`model`,
  `messages`, `system`, `max_tokens`, `stop_sequences`, `stream`, `temperature`, `top_p`, `top_k`,
  `tools`, `tool_choice`, `metadata`); todo lo demás (p. ej. `safeguards`, Diagnóstico #20) se quita y
  sus **nombres** (nunca valores) quedan en `extensions.redirect.dropped_fields`. Hacia nativos no se
  filtra.
- **Por qué**: una lista negra (`safeguards`) se rompe con el próximo campo nuevo de Claude Code.
- **Alternativas**: lista negra; parche del cliente `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`
  (HANDOFF §2.4: no reemplaza a T139).

## R11. T094 de Sentinel: cabeceras beta

- **Decisión**: hacia destinos **nativos**, `anthropic-beta` se reenvía filtrado por una lista
  permitida que es dato de la extensión (default acotado y editable por el super-admin); hacia
  traducidos, todas se descartan (`forward_headers_allowlist` de S2). El mismo `pre_request` rechaza
  con 401 una credencial de suscripción personal hacia un destino de otro proveedor con la política
  encendida (FR-042).
- **Por qué**: FR-040; el reenvío ciego de betas es lo que hoy rompe el 404 con `?beta=true`.
- **Alternativas**: reenviar todas a nativos (riesgo de betas que cambian facturación o retención).

## R12. T093 de Sentinel: `count_tokens` hacia traducidos

- **Decisión**: respuesta temprana en `pre_request`: estimación local con `tiktoken` y la misma
  codificación que ya usa la base (`cl100k_base`, `backend/src/services/token_counter.py:17`), cuyo
  vocabulario se hornea en la imagen (`TIKTOKEN_CACHE_DIR`) para no salir a la red en el primer uso; si
  el vocabulario no está, estimación `caracteres/4` (sin red); si nada de eso está disponible, 404
  `not_found_error` para que la herramienta estime sola (contrato 068 §count_tokens). Nativos: reenvío.
  Test offline en T034 (QA M14).
- **Por qué**: Claude Code usa el conteo para decidir la compactación; un 404 funciona, pero una
  estimación da compactación más fiel con ventanas chicas.
- **Alternativas**: siempre 404 (más simple, menos fiel).

## R13. D2 — Región → jurisdicciones como dato del perfil de país (FR-030, FR-031)

Hoy la correspondencia está fija en código: `_ZONES`/`_REGION_PREFIX` y `region_codes`
(`sentinel:sentinel/redirect/residency.py:22-48`: `latam_ar` → `{LATAM, AR}`), y la región del tenant
sale de `resolve_region` (`litellm/extensions/sentinel_guardian_policy.py:510`; default de código
`eu`, `:154`; Eleia fija `SENTINEL_ENTITY_REGION=latam_ar`, `.env.example:194`).

- **Opción A (recomendada)**: tabla de la extensión `sentinel_redirect_region` (nombre, lista de
  jurisdicciones, nivel instalación/empresa) y correspondencia `region_profile` → nombre de región,
  con una migración nueva por hash en la rama `sentinel_redirect` sobre `f7a3c1d9e508`; seed
  `deploy/redirect-seeds/regions.americas.yaml` **[ELEIA]** con `AMERICAS`; editable en el panel
  (pestaña Residencia); `residency.py` resuelve zonas y región desde la instantánea; la tabla fija
  queda como respaldo para regiones sin fila (Sentinel sigue igual hasta adoptar el cambio).
- **Opción B**: solo archivo de datos del perfil (YAML montado y leído al arrancar), editable por el
  operador y no desde el panel; sin migración ni cambio de cabeza.
- **Recomendación**: A — FR-030 pide lista **editable** que el panel usa para pre-completar posturas.
- **Estado**: **decidida A** por el owner (2026-10-06). La misma tabla guarda, por región, el default de
  postura fuera de región (R23).

## R14. D1 — Bloqueo por defecto de la API oficial de proveedores chinos (FR-029)

En `6a70855` solo se bloquea `provider == "deepseek"` (`sentinel:sentinel/catalog/api/admin.py:503`,
`seed.py:86`, `api/legacy.py:157`); Qwen (DashScope), Kimi (Moonshot) y MiniMax entran como
`openai_compatible` y GLM como `zai`, **sin bloqueo**. La habilitación con motivo ya existe
(`blocked_by_default`, `enabled_at`, `enabled_by`, `enable_reason` en
`sentinel:sentinel/catalog/models.py:120-123`; control en `sentinel:sentinel/redirect/resolver.py:156-157`).

- **Opción A (recomendada)**: regla **por datos**: una entrada nace `blocked_by_default` si su
  proveedor está en una lista, o el host de su `api_base` coincide con una lista sembrada y editable,
  o su jurisdicción de entidad o de inferencia está en una lista sembrada. Seed en
  `deploy/redirect-seeds/habilitacion-explicita.yaml`; la regla es genérica y vuelve por HANDOFF.
- **Opción B**: solo por proveedor (`deepseek` + `zai`): no cubre Qwen ni Kimi por `openai_compatible`.
- **Opción C**: solo por jurisdicción `CN` declarada: depende de que el administrador la cargue bien.
- **Recomendación**: A — cubre las tres vías de alta sin depender de un solo dato.
- **Estado**: **mecanismo A decidido** por el owner (2026-10-06): listas editables de proveedores, hosts
  de `api_base` y jurisdicciones, genéricas, con migración en la rama de la extensión (junto con R13).
  La regla `jurisdiction` compara contra las jurisdicciones de inferencia, de entidad y de control de
  la ficha (R25).
  - La regla de Sentinel (`provider == "deepseek"` fijo en `sentinel:sentinel/catalog/api/admin.py:503`,
    `seed.py:86` y `api/legacy.py:157`; `migrate.py:101` copia el valor de origen) se reemplaza por la
    lectura de las listas; para no cambiar el comportamiento de Sentinel, su seed de paridad es
    `providers: [deepseek]`.
  - **Valor de Eleia: decidido (D1 del owner, 2026-10-06) — opción (a), listas vacías**. Eleia siembra
    `deploy/redirect-seeds/habilitacion-explicita.yaml` con las tres listas vacías (T028): ningún destino
    nace bloqueado y todo es configurable desde el panel; con listas vacías todo funciona (test
    obligatorio, T025). Las jurisdicciones de preocupación, si un cliente las quiere, son reglas
    `jurisdiction` cargadas como dato.
  - Opciones que se evaluaron para el seed: (a) listas vacías (**elegida**); (b) solo proveedores
    (`deepseek`, `zai`); (c) proveedores + hosts de APIs oficiales chinas; (d) (c) + jurisdicción `CN`.
    Cualquiera es solo dato: no toca código.

## R15. D3 — Panel: pantalla única «Modelos» (FR-011)

- **Opción A (recomendada)**: `sentinel/frontend/pages/modelos.tsx` con `replaces: "models"` (costura
  ADAPT-026, `1d8a3b7`): reemplaza el ítem «Modelos» del menú base por la pantalla única con
  catálogo, redirección (Política, Publicados, Reglas, Destinos, Residencia, Vista previa) y acceso. Es
  la configuración verificada en nix con Claude Desktop (HANDOFF §2.2).
- **Opción B**: páginas sueltas restauradas de `62edcdc` (`redireccion.tsx`) y `26c62d3`
  (`catalogo.tsx`), sin `replaces`; no probadas en Eleia.
- **Ajustes [MVP]** sobre A: el estado *sombra* no se ofrece (FR-010) y la entrada queda junto a
  Gobernanza (FR-005).
- **Estado**: **decidida A** por el owner (2026-10-06).

## R16. D4 — Semáforo del catálogo por perfil (FR-030a)

`sentinel:sentinel/catalog/semaforo.py:47-118` evalúa contra `{"EU"}` fijo (inferencia, registros, DPA)
y sus estados son `eu_ok | standard | unclassified`.

- **Opción A (recomendada)**: parametrizar la regla con las jurisdicciones de la región del perfil
  (R13) y **conservar el valor interno `eu_ok`** por paridad de API y tests; la etiqueta visible sale
  de la región. Por D3 legal (2026-10-06) la etiqueta dice «Dentro de AMERICAS», nunca «Admisible» ni
  «Cumple»: la región es criterio de riesgo, no de legalidad (R26). La comparación usa la regla «en
  región» de R25 (inferencia, entidad y control).
- **Opción B**: renombrar el estado a `region_ok` en API, panel y tests (rompe la paridad).
- **Estado**: **decidida A** por el owner (2026-10-06).

## R17. Modelos chinos y económicos (requisito del owner al aprobar la spec)

- **Decisión**:
  1. **Carga**: el catálogo ya admite `deepseek`, `zai`, `openrouter` y `openai_compatible` con
     `api_base` (`sentinel:sentinel/catalog/models.py:31-33`), con familias `rdx-deepseek`, `rdx-zai`
     y `rdx-chatcompat` en el motor (`sentinel:sentinel/engine/profile-fragment.yaml`,
     `redirect_credentials.py` `PROVIDER_FAMILY`). T024 lo prueba para DeepSeek, Qwen, GLM y Kimi
     (directos) y para los mismos vía OpenRouter, con la regla `cheapest`
     (`d5b8e3a1c742_redirect_regla_estrategia`) eligiendo el más barato por precio del catálogo.
  2. **Bloqueo por defecto** de la API oficial: mecanismo por datos (R14); en Eleia las listas se
     siembran **vacías** (D1): ningún destino chino nace bloqueado.
  3. **Residencia**: sin postura explícita rige la **postura por defecto** de la región (R23); en Eleia,
     `masked_all` (D2): todo destino redirigido, chino o no, dentro o fuera de `AMERICAS`, sale con
     enmascarado forzado y, con el analizador caído, se bloquea (FR-027, FR-031); un destino sin
     jurisdicción de inferencia se rechaza.
  4. **Alojados en América** (D5): los mismos modelos servidos por alojadores nombrados (Azure AI Foundry
     o AWS en EE. UU./Brasil, o OpenRouter con lista de proveedores de EE. UU.) con jurisdicciones de
     inferencia, entidad y control en `AMERICAS` y retención cero declarada **pueden** usarse sin
     enmascarado forzado, solo con una relajación explícita de cumplimiento (R24); por defecto salen
     enmascarados. Una nube de una entidad controlada desde fuera de `AMERICAS` no cuenta como en región
     (R25).
  5. **OpenRouter**: R19.
  6. **Prueba real**: 🟡 hasta tener credencial; los tests usan un upstream falso
     (`sentinel:specs/068-…/spike053/fake_upstream.py` como base).
- **Por qué**: requisito explícito del owner; todo es dato y mecanismo ya portado, salvo R14 y R19.
- **Alternativas**: ninguna razonable dentro de la spec aprobada.

## R18. S13 — marcadores estables por conversación (FR-045)

Hoy el guardrail crea `policy.PlaceholderMap()` por pedido (`litellm/extensions/sentinel_guardrail.py:626`)
con sufijo aleatorio de 4 hex (`litellm/extensions/sentinel_guardian_policy.py:784`). La variante por
documento de la 043 deriva el sufijo con HMAC **usando el `document_id` como clave**
(`sentinel_guardian_policy.py:776-782`): no sirve para S13 porque es predecible para quien conoce el id.

- **Decisión**: el guardrail acepta un **identificador de conversación** en un campo de metadata
  interna que solo escribe la pasarela (el `pre_engine` de la extensión lo arma desde
  `x-claude-code-session-id` o `metadata.user_id` de la herramienta; el campo que mande el cliente se
  descarta). Con él, `nonce = HMAC(MASKING_NONCE_KEY, "nonce" | tenant | llave | conversación)` truncado con `hexdigest()[:4]`, y el
  índice por valor sigue el esquema determinista de la 043 pero con esa clave del servidor. Sin
  identificador o sin clave, el comportamiento es el de hoy (aleatorio). Genérica para las dos líneas;
  vuelve por HANDOFF (Sentinel T131/T132).
- **Por qué**: la caché del proveedor exige el mismo historial enmascarado byte a byte (FR-045); la
  clave del servidor mantiene el sufijo impredecible y la llave en el HMAC impide compartirlo entre
  personas. Es compatible con la decisión sellada del 08-sep (comentario en
  `litellm/extensions/sentinel_guardian_policy.py:759-773`: un seudónimo estable **entre** documentos
  sería una enmienda constitucional aparte, C1): S13 es estable solo dentro de una conversación; T067
  prueba que no lo es entre conversaciones (QA M3).
- **Clave del servidor** (QA M10): `MASKING_NONCE_KEY` deriva, con separación de dominio, el sufijo
  (`HMAC(k, "nonce" | tenant | llave | conversation_ref)`, truncado a 4 caracteres hex como el sufijo de hoy), `sentinel_conversation_ref`
  (`HMAC(k, "conv" | tenant | id de sesión)`) y el identificador de afinidad
  (`HMAC(k, "affinity" | tenant | id de sesión)`); sin la clave no hay referencia de conversación ni
  afinidad (comportamiento de hoy). La clave entra en `ENV_DENYLIST` de
  `sentinel/engine/redirect_credentials.py` (hoy `:81-84`) para que una credencial `env:` no pueda
  leerla, y el release la genera y la valida (`deploy/release/gen_secrets.sh`,
  `deploy/release/checks/test_no_default_secrets.sh`; en el instalador, T100).
- **Alternativas**: reusar la variante `document_id` (predecible); sufijo fijo por persona (seudónimo
  estable entre conversaciones, prohibido por FR-045).

## R19. OpenRouter con cero retención (FR-032)

- **Decisión**: el guard (`sentinel/engine/redirect_guard.py`) fuerza en todo pedido a un destino
  `openrouter` el objeto de preferencias de proveedor con cero retención, sin recolección de datos y
  la lista de proveedores permitidos del administrador (`provider_options`), sin fallbacks fuera de
  la lista; el campo de preferencias que mande el cliente se ignora (se suma a
  `CLIENT_CREDENTIAL_FIELDS`). Dar de alta un destino OpenRouter sin lista de proveedores falla. Los
  nombres exactos de los parámetros se verifican contra la referencia de la API de OpenRouter antes de
  implementar (como pide Sentinel T077) y la evidencia queda en `routing_decision.extensions.redirect`
  (`openrouter_zdr: true`, sin valores sensibles).
- **Por qué**: en `6a70855` `zero_data_retention` es solo un dato de la ficha
  (`sentinel:sentinel/catalog/models.py:155`); nada lo exige por pedido (T077 abierta en Sentinel).
- **Alternativas**: confiar en la configuración de la cuenta de OpenRouter (no verificable por pedido).

## R20. Caché de respuestas del motor (FR-048)

- **Decisión**: test primero (T071): dos pedidos idénticos a destinos distintos, o con mapas de
  enmascarado distintos, no comparten respuesta de la caché Redis del motor
  (`litellm/config.yaml:19-25`). La clave de caché ya incluye el modelo (`rdx-<familia>/<real>`) y el
  cuerpo enmascarado (sufijo por conversación); si el test muestra un cruce, el guard marca los
  pedidos redirigidos como no cacheables por respuesta (la caché del proveedor no se afecta).
- **Por qué**: FR-048 es una garantía, no una suposición sobre la clave del motor.

## R21. Constitución

- **Decisión (aprobada por el owner el 2026-10-06)**: enmienda MINOR de `.specify/memory/constitution.md`,
  alineada con la 2.4.0 de Sentinel (D19 de la 068): (1) 403 `permission_error` para los rechazos de
  residencia de la política de redirección (no 503, que Claude Code y Desktop reintentan en bucle);
  (2) aclaración de §VII: nombres de proveedor solo como datos cargados por el administrador o donde
  el protocolo de la herramienta los exige; (3) default de residencia por región del perfil de país
  (FR-031). **Estado: enmienda aprobada, pendiente de aplicar**: la aplica T001 con
  `speckit-constitution` como **primera tarea**, antes de que T-B entre a `main`.
- **Alcance**: la enmienda **no** fija los valores de Eleia del análisis legal (bloqueo por defecto de
  APIs chinas, R14; postura por defecto, R23): son datos del seed, decididos por el owner el 2026-10-06
  (D1, D2). El punto (3) de la enmienda se redacta genérico («postura por defecto por región del perfil
  de país, configurable»), sin fijar `reject` ni `masked_all`.
- **Por qué**: spec §Assumptions «Constitución»; el CRITICAL de `speckit-analyze` por el 503 del
  Principio II queda cerrado como «enmienda aprobada, pendiente de aplicar».

## R22. Docker y verificación en vivo

Todo lo que usa Docker se pide antes al owner con `ask` y se espera: suite del backend en contenedor,
`make -C deploy check`, `check-docs`, `docs-refs` (exporta `openapi.json` por contenedor,
`deploy/Makefile:45-49`), el spike D14 y las pruebas en vivo. Los tests de la extensión y del panel
corren sin Docker (venv del backend con `PYTHONPATH` y Vitest). Ids públicos de ejemplo: los que la
versión instalada de Claude Code / Desktop reconoce (Claude Code rechaza en el cliente ids que no
conoce, HANDOFF §2.4), por ejemplo `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-4-5`.

## R23. Postura por defecto del tráfico redirigido sin postura explícita (FR-031; D2 del owner)

Pedido del owner (2026-10-06, al aprobar el plan): la lectura «una API china habilitada sin postura
explícita se rechaza con 403» pasa a ser **comportamiento configurable**. Decisión del owner sobre el
análisis legal (D2, mismo día): en Eleia, **todo el tráfico redirigido sale enmascarado por defecto**.

- **Decisión (mecanismo [BASE])**: cada región del perfil (R13) lleva un dato `default_posture` que
  `effective_posture` (`sentinel:sentinel/redirect/residency.py:90-120`) usa **solo** cuando el pedido
  es redirigido y no hay ninguna fila de postura para el alcance (hoy devuelve `allowlist[región]`,
  `:95-98`):

  | Valor | Destino en región (regla de R25) | Destino fuera de región |
  |---|---|---|
  | `reject_offregion` (**fábrica**, paridad con Sentinel) | sin forzado | rechazo 403 «Modelo no disponible para tu región» |
  | `masked_offregion` | sin forzado | enmascarado forzado, fail-closed |
  | `masked_all` (**valor de Eleia**, D2) | enmascarado forzado, fail-closed | enmascarado forzado, fail-closed |
  | `allow` | sin forzado | sin forzado |

  Con cualquier valor, un destino sin jurisdicción de inferencia se rechaza (FR-028). Con filas de
  postura explícitas, la postura efectiva sale de las filas (068 FR-024), pero el forzado de
  `masked_all`/`masked_offregion` es un **piso** que las filas no quitan (`forced = base OR filas del admin OR piso`, con el forzado de la base calculado antes de combinar las filas del admin, QA re-análisis U5;
  data-model §1): así una `allowlist` restringe el alcance sin quitar el enmascarado y agregar filas
  sigue siendo endurecer (FR-023). El piso solo lo quitan las relajaciones (R24). El tráfico **no**
  redirigido sigue en `off` sin postura (FR-007). Cambiar el dato queda en
  el registro de configuración (FR-008) y solo pueden hacerlo cumplimiento o el super-admin (FR-023).
  `masked_all` se implementa como `offregion_masked` con `home = ∅`: reusa la verificación del
  enmascarado forzado y el fail-closed de la 068 (D16) sin un modo nuevo.
- **Valor para Eleia**: **`masked_all`** (D2). T064 lo siembra en `deploy/redirect-seeds/regions.americas.yaml`.
- **Efecto sobre la spec**: FR-031 y US3 esc. 8 se enmendaron por `speckit-clarify` (Session
  2026-10-06, decisiones legales); la nota de alcance que dejaba esto al coordinador queda cerrada.
- **Por qué**: el análisis (§2.3 y §4.2) muestra que ninguna jurisdicción revisada trata a América
  como zona de libre circulación (EE. UU. no es adecuado para Argentina ni Brasil), así que el owner
  eligió la postura más prudente como default y dejar la relajación en manos de cumplimiento.
- **Alternativas**: el valor `masked_offregion` (recomendación inicial del análisis: forzado solo fuera
  de `AMERICAS`), descartado por el owner; dejar el rechazo fijo (lo que pidió cambiar); default por
  empresa en vez de por región (posible a futuro con la misma columna en el nivel empresa).

## R24. Relajación del enmascarado forzado por cumplimiento (FR-031a; D2, D5 del owner)

- **Decisión [BASE]**: dos vías, ambas explícitas, con motivo, solo cumplimiento o super-admin y
  registradas (FR-008):
  1. **Por región**: cambiar `default_posture` de la región (fila de empresa o de instalación) de
     `masked_all` a `masked_offregion`. Los destinos en región (R25) salen sin forzado; el resto, con
     forzado. No se hace con una fila de postura, porque las filas no quitan el piso (R23).
  2. **Por destino**: una fila en `sentinel_redirect_masking_relaxation` (data-model §3) sobre una entrada
     del catálogo. Precondiciones: ficha con jurisdicciones de inferencia, entidad y control cargadas,
     `zero_data_retention = true` (`sentinel:sentinel/catalog/models.py:155`) y, en `openrouter`, lista
     de proveedores no vacía (D5 legal: «alojadores nombrados y con retención cero»; sin comodines de
     enrutado). Si la ficha deja de cumplir, la relajación deja de tener efecto al resolver (T060) y la
     API del catálogo la revoca al guardar la ficha (T087).
- **Límites** (respuesta del coordinador en el clarify): ninguna relajación habilita un destino sin
  jurisdicción de inferencia, relaja el fail-closed del analizador mientras el forzado rija, ni vuelve
  alcanzable un destino fuera de una postura *solo jurisdicciones permitidas*. Ningún override del
  cliente, la conexión, las cabeceras o la llave relaja el forzado (FR-027).
- **Admin de empresa**: no puede relajar: no escribe regiones ni relajaciones, y las filas de postura
  que sí puede agregar no quitan el piso de enmascarado (R23).
- **Dónde se evalúa**: `evaluate` (`sentinel:sentinel/redirect/residency.py:122-135`) recibe el
  conjunto de relajaciones vigentes de la instantánea (`sentinel/redirect/store.py`); el guard del
  motor (`sentinel/engine/redirect_guard.py`) sigue verificando el `masking_report` (S5b) cuando el
  forzado rige.
- **Por qué**: D5 pide poder usar modelos de pesos abiertos alojados en América sin enmascarado, pero
  como decisión registrada de cumplimiento, no como default.
- **Alternativas**: una bandera booleana en la entrada del catálogo (no distingue empresas en un destino
  de instalación ofrecido a varias, ni guarda autor y motivo de la relajación).

## R25. Entidad responsable y jurisdicción de control en el catálogo (FR-028a; D12 del owner)

- **Hecho**: la ficha `ext_compliance_sheet` (`sentinel:sentinel/catalog/models.py:146-163`) ya tiene
  `provider_legal_entity` (`:151`), `entity_jurisdiction` (`:152`), `inference_jurisdiction` (`:153`) y
  `zero_data_retention` (`:155`); `evaluate` mira solo inferencia y entidad
  (`sentinel:sentinel/redirect/residency.py:122-135`). No hay dato de propiedad o control.
- **Decisión [BASE]**: una columna nueva `control_jurisdiction` (`String(8)`, nullable, como `entity_jurisdiction`; QA B-1) en la ficha,
  en la migración nueva de T026; `provider_legal_entity` pasa a ser la «entidad responsable» de FR-028a
  y el panel la muestra junto a las tres jurisdicciones. Regla «en región»: inferencia **y** entidad
  **y** control satisfacen el conjunto. Control NULL o fuera ⇒ bajo `allowlist`, `foreign_entity`
  (solo con `accept_foreign_entity`); bajo `offregion_masked`, fuera de región (forzado). La misma regla
  la usa el semáforo (R16) y la regla `jurisdiction` de habilitación (R14).
- **Genérico**: ningún código nombra un país de preocupación; las jurisdicciones de preocupación son
  reglas `jurisdiction` (R14), vacías en Eleia (D1).
- **Impacto en Sentinel**: fichas sin `control_jurisdiction` dejan de contar como en región bajo
  `allowlist` y `offregion_masked`. Va en el HANDOFF con la sugerencia de cargar el dato antes de
  adoptar el cambio.
- **Por qué**: el análisis (§3.3 punto 2) muestra que una nube de una entidad de la RPC (o controlada
  ≥ 50 % desde allí) con región en América pasaría hoy como «en región» si solo se mira el país del
  servidor.
- **Alternativas**: un booleano «propiedad ≥ 50 % RPC» (específico de un país, no portable a Sentinel);
  solo nombre y jurisdicción de la entidad (no cubre la entidad local de una nube extranjera).

## R26. Textos de producto sobre enmascarado y región (D3, D10 del owner)

- **Decisión [ELEIA]**: en panel, errores, documentación (`docs/docs/**`) y HANDOFF:
  - el enmascarado se llama «seudonimización reversible de identificadores detectados»; nunca
    «anonimización», «anonimizado» ni «datos anónimos»;
  - nada dice «cumple con X», «conforme a X» ni «transferencia lícita»;
  - `AMERICAS` se presenta como **criterio de riesgo del producto, no de legalidad**: «dentro de la
    región» no significa base legal resuelta (la cubre Elea por fuera del sistema, spec §Assumptions);
  - toda la sección de residencia de la documentación queda **🟡** hasta la revisión legal (D11 del
    análisis, no decidida aquí).
- **Verificación**: T080 lo exige y T082 corre `make -C deploy check-docs`; además, en el gate de T-G
  (T086), un `grep` de `anonimiz|cumple con|conforme a|transferencia lícita` sobre lo nuevo, revisado a mano (una frase como
  «no es anonimización» es válida; una que describa el producto así, no).
- **Por qué**: el análisis §2.3 punto 4: tiene consecuencias legales distintas (solo lo irreversible
  sale del régimen en Chile y Perú) y la documentación se vende por su honestidad (AGENTS.md, DoD).

## R27. Entrega a lo que Eleia publica y al instalador (QA B1; FR-004d)

Decisión del owner por el coordinador (Clarifications, Session 2026-10-06, QA del plan, pregunta 1 = A).

- **Hechos**: `deploy/release/publish-elea.sh:23-27` publica `elea-guardian-{backend,frontend,engine}` desde
  `backend/Dockerfile.standalone`, `frontend/Dockerfile` y `litellm/Dockerfile`; el backend publicado arranca con
  `alembic upgrade head && uvicorn …` fijo (`backend/Dockerfile.standalone:35`) y `backend/src/main.py:40-43`
  registra el fallo de migración sin abortar. El instalador (`cluna-8/elea-installer`, `docker-compose.yml` de
  `main` `:48`, `:88`, `:131`) solo baja imágenes, sin `render_profile.sh` ni volúmenes. Sentinel `6a70855` ya
  trae `sentinel/docker/backend.Dockerfile` y `sentinel/docker/frontend.Dockerfile`, que **derivan** de la
  imagen base (`ARG BASE_IMAGE` / `FROM ${BASE_IMAGE}`) y no activan nada.
- **Decisión**:
  1. **Imágenes base**: no cambian salvo `backend/Dockerfile.standalone`, que delega el arranque en la misma
     lógica condicional de S4 (`upgrade heads` solo con `ALEMBIC_EXTRA_VERSION_LOCATIONS`; sin ella,
     `upgrade head` como hoy), y `backend/src/main.py`, que **aborta** el arranque si la variable está
     definida y la migración falla (sin la variable, el comportamiento de hoy). T088.
  2. **Variantes derivadas `-ext`** (tag propio, p. ej. `<versión>-ext`; nunca mueven `latest`), construidas
     por `deploy/release/publish-elea.sh` después de las base: backend con `sentinel/docker/backend.Dockerfile`
     adaptado a Eleia (usuario de la imagen de Eleia, sin `sentinel/onboarding`, seeds `[ELEIA]` de
     `deploy/redirect-seeds/` horneados en `/opt/sentinel-ext/seeds`); panel con
     `sentinel/docker/frontend.Dockerfile` (S3 en build); motor con `sentinel/docker/engine.Dockerfile`
     **nuevo**, que suma `sentinel/engine/redirect_*.py` a `/app/extensions/`, el `config.yaml` fusionado
     con `deploy/release/fragment_merge.py` (contrato S11) y `pypdf` fijado (R29). T091.
  3. **Instalador** `[repo: elea-installer]`: variable opt-in `ELEA_REDIRECT=1` que elige las `-ext`,
     escribe el entorno de la extensión en un archivo fuera del repo con modo 600 (genera
     `REDIRECT_INTERNAL_KEY` y `MASKING_NONCE_KEY`; fija `SENTINEL_ENTITY_REGION=latam_ar`,
     `REDIRECT_SEED_FILES`; `INTERNAL_ALLOWED_CIDRS` no: la fija el arreglo de bases, R31) y lo pasa por `EXTRA_ENV_FILE` (S12); sin la
     variable, `docker compose config` idéntico. T100.
  4. **Prueba local antes del servidor**: con el mismo instalador y `ELEA_REDIRECT=1` en la PC del owner,
     Claude Desktop y Claude Code contra la pasarela local, destino Azure (T102, 🐳), **antes** del runbook
     del servidor por VPN (T103).
  5. **Vuelta atrás** (runbook, T103): nivel 1, *apagar*: política apagada y sin
     `GATEWAY_PLUGINS`/`PLUGIN_PACKAGES`, conservando la imagen `-ext` del backend y
     `ALEMBIC_EXTRA_VERSION_LOCATIONS` (las migraciones aplicadas siguen visibles: con la imagen base, el
     `upgrade head` fallaría por revisiones desconocidas en `alembic_version`); nivel 2, *volver a las
     imágenes base*: solo restaurando el respaldo de la base tomado antes de activar (`respaldo.sh` del
     instalador), porque el rollback con migraciones aplicadas no está soportado (FR-004b).
- **Por qué**: la base queda intacta para quien no activa (FR-001); la paridad con Sentinel se conserva
  (mismos Dockerfiles derivados); el owner quiere verlo local antes de instalarlo en el servidor de Elea.
- **Alternativas**: una sola imagen por servicio con la extensión inerte (exige elegir la config del motor
  por entorno y un interruptor de runtime en el panel: costuras nuevas en la base); declarar el MVP solo
  desarrollo y perfiles (deja a Elea sin la feature).
- **Relación con S9/S11 (R6)**: siguen sirviendo al camino de perfiles de cliente; `fragment_merge.py` de
  la base lo reusan S11 y el `engine.Dockerfile`.

## R28. Respaldo en código de la postura por defecto (QA B2; FR-031)

Decisión del owner por el coordinador (Clarifications, QA del plan, pregunta 2 = A).

- **Hechos**: sin filas, `sentinel:sentinel/redirect/residency.py:94-98` devuelve `allowlist[home]` sin
  forzado; `tenant_region` (`sentinel:sentinel/redirect/plugin.py:134-137`) cae a `"eu"`; los compose de
  Eleia defaultean `SENTINEL_ENTITY_REGION` a `eu` (`docker-compose.yml:101`, `:217`;
  `deploy/docker/compose.prod.yml:112`, `:201`; el default de código de la base es `eu`,
  `litellm/extensions/sentinel_guardian_policy.py:154`), y solo `.env.example:194` y el instalador
  (`docker-compose.yml` de `main` `:64`, `:112`) usan `latam_ar`. El seed se cargaba a mano (T064).
- **Decisión [BASE]**:
  1. `tenant_region` devuelve «sin resolver» (`None`) si ni la identidad ni la variable traen región; no cae
     a ningún valor de otra línea.
  2. Pedido **redirigido** sin fila de `sentinel_redirect_region` que resuelva la región: postura de
     respaldo en código = `offregion_masked` con `home = ∅` (forzado en todo destino, fail-closed) **más**
     alcance limitado a `region_codes(región)` si la región se conoce (lo más estricto entre
     `reject_offregion` y `masked_all`); `default_posture_applied = "code_fallback"` en la auditoría. Región sin
     resolver ⇒ 403 `region_not_allowed` a todo lo redirigido. Destino sin jurisdicción de inferencia ⇒ 403
     siempre. No redirigido: `off` como hoy (FR-007).
  3. Estado: la extensión publica `GET /api/v1/redirect/health` (por S1, sin tocar el `/health` de la base):
     `503 {"status": "degraded", "reason": "region_unresolved" | "region_row_missing"}` cuando rige el
     respaldo, `200` si no; el instalador y el runbook lo consultan (T100, T103). Se elige la ruta de la
     extensión en vez del `/health` de la base para no agregar una costura nueva.
  4. Seeds al arrancar: con la extensión activa y `REDIRECT_SEED_FILES` (lista de archivos), un enganche
     de arranque del router de la extensión (S1) carga regiones y reglas de habilitación de forma
     idempotente antes de servir; si falla, se registra y rige el respaldo (2).
  5. `[ELEIA]`: el override de desarrollo de la extensión (`sentinel/docker/compose.dev.yml`) fija
     `SENTINEL_ENTITY_REGION=latam_ar` (como `.env.example:194` y el instalador), con check de release; el
     `docker-compose.yml` de la raíz no cambia (es el de la suite de CI y cambiarlo cambia la base para todos,
     R6; QA re-análisis M1). `deploy/docker/compose.prod.yml` **conserva** `eu`: `deploy/release/bundle.sh:58` lo empaqueta para todo
     perfil de cliente, incluidos los europeos, cuyo enmascarado depende de los patrones de `eu`
     (`litellm/extensions/sentinel_guardian_policy.py:131-137`); cambiarlo violaría FR-001/FR-007 para ellos.
     Un perfil de `deploy/clients/*` que active la extensión sin fijar la región cae en el respaldo
     fail-closed de (2) con `/api/v1/redirect/health` en 503 (QA re-análisis F1).
- **Por qué**: D2 queda garantizado aunque falte el dato; con el seed rige `masked_all` sin cambios. Para
  Sentinel es más estricto que hoy sin fila: el HANDOFF le indica sembrar su fila `reject_offregion`.
- **Alternativas**: respaldo = `masked_all` exacto (abre fuera de región sin el dato); no arrancar con la
  política activa sin fila (deja sin servicio por un dato que la extensión puede sembrar sola).

## R29. Alcance completo del enmascarado forzado y bloqueo de lo no analizable — S14 (QA B3; FR-027, SC-006)

Decisión del owner por el coordinador (Clarifications, QA del plan, pregunta 3 = C: A + extracción de PDF).

- **Hechos**: `mask_body` enmascara solo turnos `user` (`litellm/extensions/sentinel_guardian_policy.py:880-892`,
  docstring `:882-883`), `_mask_content` solo bloques `text` y `tool_result` de texto (`:858-878`) y
  `extract_inspect_text` tiene el mismo alcance (`:734-749`); el guard compara solo `detected == masked`
  (`sentinel:sentinel/engine/redirect_guard.py:118-125`); con el forzado en el camino redirigido, el guard
  verifica pero no obliga al guardrail a enmascarar (`redirect_guard.py:328-330`); en el de suscripción la
  extensión fuerza por `governance_overrides` (`sentinel:sentinel/redirect/plugin.py:375-376`). Sentinel T074
  sigue abierta.
- **Decisión [BASE], costura nueva S14** (retrocompatible: sin la señal, todo igual que hoy):
  1. **Señal**: metadata interna `sentinel_forced_masking = {"scope": "full"}` que solo escribe la pasarela
     (`pre_engine` de la extensión cuando la resolución dice forzado; la que mande el cliente se descarta,
     igual que S13) y, en el camino de suscripción, `governance_overrides["masking_scope"] = "full"`.
  2. **Con la señal**, el guardrail enmascara con `pii_masking` encendido y `nlp_fail_mode=block` aunque la
     empresa diga otra cosa, y el alcance es completo: `system` (texto y bloques; en formato OpenAI, turnos
     `system`/`developer`); todos los turnos `user` y `assistant` (bloques `text`, `tool_use.input` en sus
     valores de texto, `tool_result`, `thinking`; en OpenAI, `content` y `tool_calls[].function.arguments`
     parseados); descripciones de herramientas (`tools[].description`, descripciones dentro de
     `input_schema`; en OpenAI, `tools[].function.description`). **Regla general, fail-closed** (QA re-análisis
     U3): bajo la señal se analiza y enmascara **todo valor de texto** del cuerpo, en cualquier campo y a
     cualquier profundidad (incluidos `metadata`, `stop_sequences`, `enum`/`default`/`examples` de
     `input_schema`, `user` y `name` de OpenAI y campos desconocidos), **salvo** una lista cerrada de campos
     estructurales: `model`, `role`, `type`, `id`, `tool_use_id`, `tool_call_id`, el nombre de una herramienta
     (`tools[].name`, `tool_use.name`, `function.name`, `tool_choice.name`), `media_type`, `cache_control`,
     `signature`, `stream`, las claves de objeto y los datos base64 de bloques no textuales (que van por el
     camino de PDF o cuentan como no analizables). Agregar un campo estructural es un cambio de contrato
     con test.
  2b. **`count_tokens` bajo forzado** (QA re-análisis U2; FR-041): no se reenvía a ningún destino ni por el
     camino de suscripción; se estima localmente (R12) o responde 404 `not_found_error`. Lo resuelve la
     extensión antes del motor (T041) y, en suscripción, el `pre_request` del camino de suscripción (T062). Bajo forzado, ningún tipo de entidad del perfil queda exento por la configuración de la
     empresa (QA M4).
  3. **PDF**: un bloque `document` con PDF en base64 (en OpenAI, la parte `file` con PDF) se convierte a
     texto con `pypdf` (la librería que ya usa el repo en `client/extract_text.py:33-37`, instalada en
     `client/Dockerfile:6`), se enmascara y viaja como bloque de texto enmascarado. **No analizable** (⇒
     bloqueo): PDF sin texto extraíble (escaneado), protegido o corrupto; PDF por encima de
     `MASKING_PDF_MAX_PAGES` (por defecto 200) o `MASKING_PDF_MAX_BYTES` (por defecto 20 MB); `document` por
     URL; imágenes; audio; tipos desconocidos; `redacted_thinking`; un `thinking` firmado con detecciones
     hacia un destino nativo (enmascararlo invalida la firma). Sin `pypdf` instalado (imagen base del motor),
     todo PDF es no analizable: falla cerrado.
  4. **Informe S5b ampliado**: `masking_report` suma `scope` (`"user"` hoy, `"full"` con la señal),
     `unanalyzable` (entero) y `unanalyzable_kinds` (solo nombres de tipo, nunca contenido).
     `masking_ok` del guard exige además `unanalyzable == 0` y `scope == "full"` cuando el forzado rige;
     un informe sin esos campos (guardrail viejo) no pasa.
  5. **Restauración**: no cambia (la respuesta vuelve restaurada, también en streaming y en chunks OpenAI,
     `f8118e7`); en el turno siguiente, el texto del asistente que la herramienta reenvía restaurado vuelve
     a enmascararse (con S13, con los mismos marcadores).
- **Costo** (pedido del owner): `pypdf` es Python puro, sin dependencias nativas; se instala solo en la
  variante `-ext` del motor, fijado por versión exacta y hash en `sentinel/docker/engine-requirements.txt`
  (T091). La extracción corre solo bajo forzado y solo con PDF: del orden de milisegundos por página de
  texto (decenas de ms en páginas densas), así que un PDF de decenas de páginas suma de cientos de ms a
  pocos segundos al pedido que lo trae; SC-010 (≤ 50 ms p95) se mide sin adjuntos y T097 agrega una medición
  informativa con PDF y otra de un pedido típico de Claude Code de solo texto con alcance completo. Los topes de páginas y bytes acotan el peor caso (fallan cerrado). Riesgo de
  seguridad del parser: se ejecuta en el motor, sin red, sobre bytes del propio cliente; los errores del
  parser cuentan como no analizable.
- **Fase siguiente**: OCR de imágenes y PDF escaneados (fuera del MVP).
- **Vuelve a Sentinel por HANDOFF** y cierra la T074 de Sentinel.
- **Alternativas**: declarar `system`/tools como límite 🟡 (deja salir en claro lo que más datos de entorno
  lleva en Claude Code); bloquear todo PDF (rompe Cowork con documentos).

## R30. Permisos: filas del admin de empresa, rol real y ficha del destino (QA A6, A7, A8; FR-023, FR-028)

Decisión del owner por el coordinador (Clarifications, QA del plan, pregunta 4 = A).

- **Hechos**: `sentinel:sentinel/redirect/api/admin.py:583-598` deja a `require_role("admin","compliance_officer")`
  crear una fila de cualquier modo (`_check_posture`, `:557-563`, valida solo el nombre); `residency.py:99-119`
  calcula la postura solo entre filas, así que una fila `off` reemplaza el default (`:125-126`); `RedirectPosture`
  ya guarda `created_by_role` (`sentinel:sentinel/redirect/models.py:79`). `REDIRECT_OPERATOR_TENANT`
  (`admin.py:83-100`) da autoridad de instalación al `tenant_admin` del tenant operador. La ficha se escribe con
  `SHEET_WRITERS = ("admin","compliance_officer")` (`sentinel:sentinel/catalog/api/admin.py:41`, `:668-669`).
- **Decisión [BASE]**:
  1. **Filas que solo restringen**: base = la más estricta entre las filas de `compliance_officer`/`super_admin`
     (068 FR-024) o, si no hay, la postura por defecto (o el respaldo de R28); efectiva = la más estricta entre la
     base y las filas de `tenant_admin`, con el piso de enmascarado de `default_posture` encima y el forzado que
     impone la base conservado (una `allowlist` del admin restringe el alcance, nunca quita ese forzado; QA
     re-análisis U5); bajo el respaldo en código de R28, ninguna fila de ningún rol quita el forzado ni amplía
     el alcance (QA re-análisis U1) (data-model §1).
     La API responde 422 `posture_less_strict` a una fila de `tenant_admin` menos estricta que la efectiva del
     alcance.
  2. **Sin jurisdicción de inferencia ⇒ 403** para todo pedido redirigido, con cualquier fila o relajación.
  3. **Rol real**: escribir regiones, `default_posture` y relajaciones exige `compliance_officer` o `super_admin`
     por rol, no `_is_super` por `REDIRECT_OPERATOR_TENANT`. Eleia no define esa variable (tiene `super_admin`,
     `backend/src/models/user.py:9`; no está en `.env.example`, `sentinel/extensions.env.example` ni en el
     instalador); test con la variable definida.
  4. **Ficha**: `provider_legal_entity`, `entity_jurisdiction`, `control_jurisdiction`, `inference_jurisdiction` y
     `zero_data_retention` solo los escriben `compliance_officer` y `super_admin` (403 para el admin de
     empresa en esos campos; el resto de la ficha sigue igual); cada cambio en el registro (FR-008).
- **Por qué**: D2 dice que el enmascarado por defecto lo relaja solo cumplimiento; sin esto, el admin de empresa lo
  relaja por tres vías.
- **Alternativas**: documentar A6/A7 como riesgo (deja la vía abierta); que el admin de empresa no cree filas
  (pierde el «endurecer» de FR-023).

## R31. Canal interno en tres capas — S15 (QA A10; FR-013)

Decisión del owner por el coordinador (Clarifications, QA del plan, pregunta 5 = A).

- **Hechos**: `sentinel:sentinel/catalog/api/internal.py:149-163` devuelve la credencial descifrada con solo
  `_require_internal_secret` (`backend/src/api/internal.py:120-127`); `direct_enabled()` (`internal.py:97-101`) no
  apaga la ruta; el plano motor de la redirección **no** la usa (la credencial viaja en la autorización firmada,
  `sentinel:sentinel/engine/redirect_guard.py:345`), solo la ruta directa del catálogo
  (`sentinel:sentinel/engine/redirect_catalog.py:10`, `:133`); el chat de la consola la llama en proceso
  (`sentinel:sentinel/catalog/chat_route.py:50`). El ingress de Eleia niega `/api/v1/internal/*`
  (`deploy/docker/Caddyfile.ingress:20`), pero el instalador publica el backend en `8091:8000` sin proxy
  (`docker-compose.yml` de `main` `:92`).
- **Decisión** (con la precisión del coordinador en el re-análisis: capas 2 y 3 para **toda**
  instalación, entregadas por el arreglo de separación de bases del instalador, que va antes que la 057 y cuyo
  ensayo, `ENSAYO-SEPARAR-BASES.md` de `cluna-8/fix-separar-bases-motor`, verificó que `/api/v1/internal/*` se
  alcanza por `8091` con la llave maestra; la 057 **no las duplica**: depende de ellas y verifica que la variante
  `-ext` no las salte):
  1. **Extensión [BASE]** (lo único que implementa la 057): la **ruta HTTP** `/api/v1/internal/model-credential`
     lleva una dependencia que responde 404 salvo `direct_enabled()`; la función sigue invocable en proceso por el
     chat. T090.
  2. **Base de Eleia [BASE], S15** (dependencia; T089 verifica que cubre las rutas de la extensión): `_require_internal_secret` exige además que el par de transporte del pedido
     (no `X-Forwarded-For`) esté en `INTERNAL_ALLOWED_CIDRS`: lista de CIDR o `auto` (las subredes de las
     interfaces del contenedor, sin la dirección de su puerta de enlace, por donde entra lo publicado desde el
     host); vacía ⇒ sin chequeo (igual que hoy). El compose de Eleia y el instalador la fijan en `auto`.
  3. **Instalador [repo: elea-installer]** (dependencia; T101 verifica que sigue con `ELEA_REDIRECT=1`): un proxy delante del backend (como `Caddyfile.ingress`) publica el
     puerto de hoy, niega `/api/v1/internal/*` con 404 y deja pasar `/api/v1/gw/*`, el panel y el Hub, que siguen
     alcanzables desde la LAN; el backend deja de publicar puertos.
  4. T081 documenta que `/api/v1/internal/*` no se publica fuera de la red de compose.
- **Efecto sobre FR-004d** (QA re-análisis C1): «sin `ELEA_REDIRECT`, idéntico» se mide contra la instalación
  ya corregida por el arreglo de bases (proxy y chequeo de origen incluidos), no contra la de hoy.

## R32. Otros altos del QA (A2, A3, A4, A9)

- **A2 — FR-016 sin prueba propia**: con auth propia el motor 1.92.0 no aplica `models` de la llave
  (`068/research.md:529`, caso (c)); la única barrera es la de la pasarela
  (`sentinel:sentinel/redirect/plugin.py:354-357`). T035 suma el caso concreto (llave con `allowed_models`: id
  público permitido ⇒ sirve; no permitido ⇒ rechazo; lista vacía ⇒ sirve) y T019 corre **todos** los casos de R13
  de Sentinel (incluidos el (c), el rechazo del cuerpo con `api_base` y la expansión del comodín en `/v1/models`
  del motor, `068/research.md:529-531`).
- **A3 — `rdx-*` y orden de guardrails**: test offline (T092) de «`rdx-*` sin autorización ⇒ 403 también en
  `call_type` no textuales», del **orden efectivo** en el `config.yaml` fusionado (`redirect-guard` después de
  `sentinel-guardian`, `litellm/config.yaml:12`) y de que `metadata.masking_report`, `guardrails` o
  `disable_global_guardrails` mandados por el cliente no relajan el forzado; T020 verifica el orden, no solo «al
  final».
- **A4 — Sobre-enmascarado de Claude Desktop (Sentinel 069 T184, abierta)**: con `masked_all` todo el tráfico
  redirigido pasa por el enmascarado y, con S14, también `system` y herramientas: el riesgo sobre SC-004 y SC-011
  sube. Entra al registro de riesgos del plan; T045 y T083 miden con el forzado encendido y registran los
  falsos positivos por pedido (solo conteos por tipo); T085 lo devuelve en el HANDOFF.
- **A9 — Secuencia**: T047 y T051 exigen la postura por defecto (T060/T061/T064): T-D pasa a depender de T-E
  (orden A → B → C → E → {D ∥ F} → H → G). T045 (T-C) corre con una postura **explícita** de prueba
  cargada por cumplimiento (`offregion_masked` sin jurisdicciones, que fuerza el enmascarado hacia todo destino
  fuera de `LATAM/AR`, equivalente a `masked_all` para Azure en EE. UU.) y T083 repite la medición con el
  default real.

## Resolución del QA

Resolución de `qa-plan.md` (`3537847`, QA crítico del plan, tercera pasada) por `speckit-clarify` (5 preguntas
al coordinador, Session 2026-10-06 «QA del plan», más una precisión en el re-análisis), `speckit-plan` y
`speckit-tasks`, el 2026-10-06. Las referencias `archivo:línea` son de este directorio
(`specs/057-porte-sentinel-068-redireccion-modelos/`) en el commit de esta resolución. Ningún hallazgo reabre
P1–P5, D1–D4, D1/D2/D5/D12 legales ni la enmienda del 403.

| Hallazgo | Severidad | Resolución | Dónde (archivo:línea) |
|---|---|---|---|
| B1 — la extensión no llega a lo publicado ni al instalador; el backend publicado no arranca con la variable | Bloqueante | Variantes `-ext` derivadas, `Dockerfile.standalone` con `upgrade heads` condicional y arranque que aborta, opt-in `ELEA_REDIRECT=1`, prueba local antes del runbook con vuelta atrás; premisa de R6 corregida | spec.md:197 (Clarifications); spec.md:71 (Diagnóstico #5); spec.md:580 (FR-004d); research.md:146 (R6); research.md:512 (R27); plan.md:26 (T-H); plan.md:252 (riesgo); contracts/costuras-base.md:14 (S4); quickstart.md:36 (§1b); tasks.md:81 (T088); tasks.md:116 (T091); tasks.md:265 (T100); tasks.md:267 (T102); tasks.md:268 (T103) |
| B2 — `masked_all` solo como dato sembrado; sin seed o región, sale sin forzado; región cae a `eu` | Bloqueante | Respaldo en código forzado y fail-closed con alcance a `region_codes`, sin región ⇒ 403, ninguna fila lo quita; `tenant_region` sin `eu`; seeds al arrancar; compose con `latam_ar`; `/api/v1/redirect/health` | spec.md:790 (FR-031); research.md:557 (R28); data-model.md:66 (§1); data-model.md:103 (piso); contracts/admin-api.md:30; tasks.md:205 (T094); tasks.md:208 (T060); tasks.md:213 (T095) |
| B3 — el forzado no cubre `system`, turnos del asistente, herramientas ni adjuntos; «no analizable bloquea» sin tarea | Bloqueante | Costura S14: todo valor de texto salvo campos estructurales, PDF a texto con `pypdf`, no analizables ⇒ bloqueo, informe con `scope`/`unanalyzable`, guard que lo exige, `count_tokens` no se reenvía bajo forzado; cierra Sentinel T074 por HANDOFF | spec.md:728 (FR-027); spec.md:858 (FR-041); spec.md:986 (SC-006); research.md:596 (R29); contracts/costuras-base.md:50 (§S14); tasks.md:142 (T034); tasks.md:201 (T056); tasks.md:206 (T096); tasks.md:209 (T061); tasks.md:214 (T097) |
| A2 — FR-016 sin prueba propia; T019 no corre todos los casos de R13 | Alto | Caso de `allowed_models` en T035; T019 corre todos los casos de R13 de Sentinel | research.md:720 (R32); tasks.md:104 (T019); tasks.md:143 (T035) |
| A3 — `rdx-*` y orden de guardrails solo en vivo | Alto | Test offline de `rdx-*` en todos los `call_type`, orden efectivo y metadata del cliente que no relaja; T020 verifica el orden | research.md:720 (R32); tasks.md:105 (T020); tasks.md:117 (T092) |
| A4 — sobre-enmascarado de Claude Desktop (Sentinel 069 T184) ausente | Alto | Registro de riesgos; T045/T083 miden falsos positivos con el forzado encendido; escalamiento si SC-004 no se alcanza; HANDOFF | plan.md:255 (riesgo); research.md:720 (R32); tasks.md:153 (T045); tasks.md:285 (T083); tasks.md:287 (T085) |
| A5 — `DISABLE_SCHEMA_UPDATE=true` presentada como respaldada | Alto | Hipótesis; fuera del override hasta que T019 la ensaye | research.md:111 (R5); plan.md:256 (riesgo); quickstart.md:13 (§0); tasks.md:104 (T019); tasks.md:106 (T021) |
| A6 — `REDIRECT_OPERATOR_TENANT` desarma FR-023 | Alto | Eleia no la define; regiones, `default_posture` y relajaciones por rol real; test con la variable definida | spec.md:701 (FR-023); research.md:657 (R30); data-model.md:127 (§1); contracts/admin-api.md:26; tasks.md:200 (T055); tasks.md:208 (T060) |
| A7 — el admin de empresa puede falsear la ficha de la que depende la relajación | Alto | Campos de residencia y retención de la ficha solo de cumplimiento y super-admin (403) | spec.md:701 (FR-023); research.md:657 (R30); data-model.md:235 (§4); contracts/admin-api.md:76; tasks.md:118 (T099) |
| A8 — una fila `off` del admin de empresa reemplaza el default | Alto | Postura efectiva en dos niveles, 422 `posture_less_strict` con orden total definido (entre modos y por inclusión), destino sin jurisdicción ⇒ 403 con cualquier fila | spec.md:701 (FR-023); spec.md:744 (FR-028); data-model.md:91 (§1); contracts/admin-api.md:21; tasks.md:207 (T098); tasks.md:208 (T060) |
| A9 — T045, T047 y T051 dependen de T-E aunque el plan los ordenaba antes o en paralelo | Alto | Orden A → B → C → E → {D ∥ F} → H → G; T045 con postura explícita de prueba y T083 con el default real | plan.md:226 (orden); quickstart.md:80 (§3); tasks.md:162 (T-D); tasks.md:153 (T045); tasks.md:302 (dependencias) |
| A10 — `/internal/model-credential` entrega credenciales descifradas con solo el secreto; el instalador publica el backend | Alto | Capa 1 en la 057 (404 sin ruta directa). Capas 2 (S15) y 3 (proxy) para **toda** instalación las entrega antes el arreglo de separación de bases (decisión del coordinador en el re-análisis): dependencia que T089 y T101 verifican; T081 lo documenta | spec.md:238 (Clarifications); spec.md:652 (FR-013); research.md:689 (R31); contracts/costuras-base.md:77 (§S15); tasks.md:82 (T089); tasks.md:115 (T090); tasks.md:266 (T101); tasks.md:283 (T081) |
| M1 — gate de T-A con Docker | Medio | Sin cambio: T015 ya 🐳 con aviso al owner | tasks.md:83 (T015) |
| M2 — «cuatro entradas `azure/*`» y `gpt-5.6-luna` sin evidencia | Medio | Tres conversables + embeddings; `gpt-5.6-luna` a confirmar con el owner, con alternativa | research.md:184 (R9); quickstart.md:65 (§2); tasks.md:108 (T023); tasks.md:153 (T045) |
| M3 — S13 y la decisión sellada del 08-sep | Medio | Referencia agregada; T067 prueba que no es estable entre conversaciones | research.md:345 (R18); tasks.md:234 (T067) |
| M4 — `masking_ok` exige `detected == masked` | Medio | Bajo forzado ningún tipo queda exento | research.md:596 (R29); tasks.md:201 (T056); tasks.md:214 (T097) |
| M5 — FR-005/006/012/013/016 con test solo heredado | Medio | T030 lista los heredados (incluidos retiro de oferta y Hub) y exige que no queden saltados | tasks.md:120 (T030) |
| M6 — absorbido por A8 | — | Ver A8 | — |
| M7 — CUIT/CUIL solo con guiones | Medio | Batería con formatos fijados; patrón sin guiones | tasks.md:201 (T056); tasks.md:214 (T097) |
| M8 — texto del bloqueo por enmascarado | Medio | Contratos alineados con las caras copiadas (400 cara Claude, 403 genérica) | contracts/cara-claude.md:72; contracts/cara-generica.md:23; contracts/costuras-base.md:72 |
| M9 — habilitación de entradas bloqueadas por el admin | Medio | Sin cambio (rol de la 068/069; habilitar no relaja la residencia); con A7 el admin no cambia la ficha | data-model.md:179 (§2); tasks.md:118 (T099) |
| M10 — `MASKING_NONCE_KEY` fuera de la lista negra; claves sin definir; release sin generarlas | Medio | Clave con separación de dominio y ancho fijo; `ENV_DENYLIST`, `gen_secrets.sh` y check; el instalador la genera | research.md:349 (R18); data-model.md:280 (§6); tasks.md:240 (T093); tasks.md:265 (T100) |
| M11 — S5b cambia el camino de `redact_enabled=false` | Medio | Test del guardrail en T008 y anotación para el HANDOFF | tasks.md:74 (T008); tasks.md:287 (T085) |
| M12 — gates sin Docker pueden pasar con tests saltados | Medio | `-rs` y 0 saltados entre los críticos | tasks.md:120 (T030); tasks.md:215 (T065); tasks.md:288 (T086) |
| M13 — DoD de docs incompleta | Medio | T079 suma overview, release-notes y compliance (o los declara fuera con motivo) | tasks.md:281 (T079) |
| M14 — estimador de tokens con red | Bajo | `cl100k_base` horneado en la `-ext` y respaldo `caracteres/4`, test offline | research.md:214 (R12); tasks.md:142 (T034); tasks.md:149 (T041); tasks.md:116 (T091) |
| M15 — citas de ids de Sentinel; versión de la enmienda | Bajo | Ids rotulados «de Sentinel» en spec, plan, data-model, contratos y tasks; aviso de divergencia en T001 | spec.md:550; plan.md:22; contracts/cara-claude.md:11; tasks.md:67 (T001); tasks.md:130 (T-C) |
| B-1 — `control_jurisdiction` `String(16)` vs `String(8)` | Bajo | Unificado a `String(8)` | data-model.md:231; research.md:479 (R25) |
| B-2 — cita de `gw_messages` aproximada | Bajo | Sin cambio: sin consecuencia | spec.md:67 |
| §6 — cobertura de escenarios (US3.3, US1.6, US3.7, US3.8, SC-004, SC-006, SC-010) | — | US3.3/SC-006 por B3; US1.6 por A3 y por G1 del re-análisis (política apagada); US3.7 por A6–A8; US3.8 por B2; SC-004 bajo la postura real (A9); SC-010 aclarado | tasks.md:206 (T096); tasks.md:117 (T092); tasks.md:103 (T018); tasks.md:207 (T098); tasks.md:205 (T094); tasks.md:285 (T083); tasks.md:152 (T044) |

### Re-análisis (`speckit-analyze`, solo lectura, 2026-10-06)

Primera corrida sobre esta resolución: 0 CRITICAL, 5 HIGH, 13 MEDIUM, 13 LOW. Se corrigieron así:

| Hallazgo del análisis | Severidad | Resolución | Dónde (archivo:línea) |
|---|---|---|---|
| C1 — FR-004d «idéntico sin la variable» vs. proxy del instalador | HIGH | Pregunta al coordinador: proxy y chequeo de origen para toda instalación, entregados por el arreglo de bases (dependencia); «idéntico» se mide contra la instalación ya corregida | spec.md:238; spec.md:580; research.md:717 (R31); tasks.md:265 (T100); tasks.md:266 (T101) |
| U1 — el respaldo en código no tenía piso frente a filas de cumplimiento | HIGH | Piso de forzado en todo destino bajo el respaldo, sin excepción de rol | data-model.md:103; tasks.md:205 (T094) |
| C2 — T098 rechazaba filas más estrictas; orden dentro del mismo modo indefinido | HIGH | Orden total definido (inclusión de jurisdicciones o de `home`); 422 solo si es menos estricta | data-model.md:109; tasks.md:207 (T098) |
| U2 — `count_tokens` reenviado bajo forzado | HIGH | Bajo forzado nunca se reenvía (estimado local o 404), también en suscripción | spec.md:858 (FR-041); research.md:625 (R29); contracts/cara-claude.md:38; tasks.md:142 (T034); tasks.md:149 (T041); tasks.md:210 (T062) |
| U3 — «todo lo que sale» sin regla para campos fuera de la lista | HIGH | Regla general fail-closed: todo valor de texto salvo una lista cerrada de campos estructurales | spec.md:729 (FR-027); research.md:616 (R29); contracts/costuras-base.md:60; tasks.md:206 (T096) |
| I1–I8, O1–O3, A1, G1 (medios) | MEDIUM | Ids de Sentinel rotulados; 400/403 por cara; alcance del respaldo = `region_codes`; borrado por SQL; quickstart marca qué vale antes de T-E; medición PDF en T097; S14 de docs en T080; imagen del motor «mismo digest base»; T050 escala si sale de `generic.py`; S1–S15; `conversation_ref` alineado; sufijo de 4 hex; FR-014 con política apagada en T018 | quickstart.md:50; tasks.md:41; tasks.md:175 (T050); tasks.md:282 (T080); tasks.md:214 (T097); tasks.md:103 (T018); data-model.md:287 |
| L1–L11 (bajos) | LOW | `masking_relaxation=region` decidible; `unanalyzable_kinds` en S14; 403 en la ficha; `code_fallback`; FR-006/012/030/050 en T030/T079; archivos de test en las filas de tramo; vocabulario horneado; textos de tramos y fases. L12 y D1 (orden de FR/SC y repetición de la regla sin jurisdicción en la spec) se dejan: reordenar la spec cambiaría ids y citas sin efecto en la implementación | data-model.md:273; data-model.md:270; plan.md:238; tasks.md:16 |

### Re-análisis, segunda corrida (`speckit-analyze`, solo lectura)

Sobre las correcciones de la primera corrida: 0 CRITICAL, 1 HIGH, 4 MEDIUM, 10 LOW; los 5 HIGH anteriores, resueltos. Se corrigieron así:

| Hallazgo del análisis | Severidad | Resolución | Dónde (archivo:línea) |
|---|---|---|---|
| U5 — una `allowlist` del admin quitaba el forzado que impone una fila de cumplimiento | HIGH | El forzado de la base se calcula antes de combinar con las filas del admin y se conserva | data-model.md:99; spec.md:706 (FR-023); research.md:671 (R30); tasks.md:207 (T098) |
| U4 — la regla U1 no estaba en FR-031 ni en R30 | MEDIUM | Agregada a FR-031 y R30 | spec.md:796 (FR-031); research.md:672 (R30) |
| I1 — T-H en el resumen del plan seguía diciendo «proxy» | MEDIUM | Reescrito como verificación de la dependencia | plan.md:26 |
| G1 — rutas de la extensión a través del proxy | MEDIUM | T101 exige `/api/v1/redirect/*`, `/api/v1/catalog/*` y la salud por el puerto publicado | tasks.md:266 (T101) |
| G2 — demora del alcance completo sin medir | MEDIUM | Medición informativa de un pedido típico de Claude Code de solo texto en T097, junto a SC-010 | tasks.md:214 (T097); research.md:648 (R29) |
| L1–L10 (bajos) | LOW | T097 en R29; fórmula del sufijo alineada; ids de Sentinel rotulados; `unanalyzable_kinds` en S5b; fila de forzado primero en `count_tokens`; línea suelta del plan; estado de la spec; archivo de perf en T-E; FR-006 → T030; precisión de C1 en el quickstart | research.md:339; contracts/cara-claude.md:39; spec.md:7; tasks.md:377; quickstart.md:25 |

### Re-análisis, tercera corrida (`speckit-analyze`, solo lectura)

Sobre las correcciones de la segunda: 0 CRITICAL, 1 HIGH, 4 MEDIUM, 7 LOW; U5 y los demás, resueltos (≈90 referencias `archivo:línea` de estas tablas verificadas por el análisis). Se corrigieron así:

| Hallazgo del análisis | Severidad | Resolución | Dónde (archivo:línea) |
|---|---|---|---|
| F1 — cambiar el default de región en `compose.prod.yml` afectaba a los perfiles de cliente europeos sin la extensión | HIGH | El default `latam_ar` solo en el compose de desarrollo de Eleia (el instalador ya lo usa); `compose.prod.yml` conserva `eu`; los perfiles que activen la extensión fijan la región | research.md:586 (R28); tasks.md:213 (T095); plan.md:192 |
| C1 — R23 conservaba la fórmula previa a U5 | MEDIUM | Fórmula alineada con data-model §1 | research.md:428 (R23) |
| C2 — T-H del plan aún listaba el proxy | MEDIUM | Quitado | plan.md:212 |
| C3 — T056 bloqueaba con `redact_enabled=false` bajo forzado | MEDIUM | Bajo forzado sale enmascarado; bloquea solo con analizador caído/degradado o no analizable | tasks.md:201 (T056) |
| A1 — `home` vacío en una fila vs. `masked_all` | MEDIUM | Se compara el `home` resuelto; ejemplo de T098 ajustado | data-model.md:114; tasks.md:207 (T098) |
| U1, U2, A2, G1, T1–T3 (bajos) | LOW | Paridad 068 entre filas de cumplimiento declarada; contrato de posturas con la regla U5; SC-010 sin el costo del análisis forzado; test de roles del panel en T063; T139 rotulado; M10 → T093 en el encabezado; comentario del plan | data-model.md:116; contracts/admin-api.md:21; spec.md:997; tasks.md:211 (T063); tasks.md:31 |

### Re-análisis, cuarta corrida (`speckit-analyze`, solo lectura)

Sobre las correcciones de la tercera: **0 CRITICAL, 0 HIGH**, 2 MEDIUM, 5 LOW (F1 y los demás, resueltos; ≈120 referencias `archivo:línea` de estas tablas verificadas). Los siete se corrigieron igual, por ser baratos:

| Hallazgo del análisis | Severidad | Resolución | Dónde (archivo:línea) |
|---|---|---|---|
| M1 — el default `latam_ar` en el `docker-compose.yml` de la raíz cambiaba la región de la suite de CI | MEDIUM | El default va al override de desarrollo de la extensión; la raíz y `compose.prod.yml` no cambian | research.md:583 (R28); tasks.md:213 (T095); plan.md:237 |
| M2 — ¿una relajación quita el forzado del respaldo en código? | MEDIUM | No: bajo el respaldo ninguna relajación tiene efecto | data-model.md:215 (§3); data-model.md:105 (§1); tasks.md:205 (T094) |
| L1–L5 (bajos) | LOW | Riesgo con el origen correcto de «sin `eu`»; `plugin.py` de T-F después de T-E; test de roles del panel en la fila de T-E; contrato de la ficha alineado con FR-028; la cláusula sin marcador de T095 reemplazada por el respaldo fail-closed | plan.md:253; plan.md:238; contracts/admin-api.md:74 |
