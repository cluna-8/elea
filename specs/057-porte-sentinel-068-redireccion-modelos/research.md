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
    repo; el coordinador informó el 2026-10-06 que existe en Azure (dato no verificado por el QA v2, sin red
    a Azure): se siembra y se usa solo si la verificación de despliegue de T022 lo confirma (si no, opus →
    `gpt-5.1-chat`; QA M2). La verificación de T022 no filtra: siembra la entrada y la deja `inactive` si no existe. La jurisdicción de inferencia **no**
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
  - **Alcance de una regla de empresa (decidido por el coordinador, opción A, durante T025/T027):** una regla de
    habilitación de nivel empresa bloquea solo las entradas **de esa empresa**; las entradas de instalación las
    bloquean únicamente las reglas de instalación (la empresa limita lo que ve con ofertas y perfiles de acceso).
    **Mejora posible (opción B, sin tarea en el MVP):** que la regla de empresa bloquee también, solo para esa
    empresa, las entradas de instalación que se le ofrecen; exigiría calcular `blocked_by_default` por empresa en la
    instantánea del plano de datos y que `/enable` opere sobre la oferta (toca resolver e instantánea).
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
  4. Seeds al arrancar: con la extensión activa y `REDIRECT_SEED_FILES` (lista de archivos), el enganche de
     arranque de la extensión carga regiones y reglas de habilitación de forma idempotente antes de servir;
     si falla, se registra y rige el respaldo (2). **Mecanismo** (QA v2 N1; research R33): S1 solo valida y
     monta `(APIRouter, prefix)` (`sentinel:backend/src/plugins.py:9`, `:81-88`) y la app se crea con
     `lifespan=_lifespan` (`backend/src/main.py:80-101`); con FastAPI 0.111.0 (`backend/requirements.txt:1`)
     el `on_startup` de un router incluido **no corre** bajo `lifespan` (ensayado el 2026-10-06 con
     `fastapi==0.111.0`/`starlette==0.37.2`; con FastAPI 0.135 sí corre, así que depender de él cambiaría con
     una actualización). Por eso el enganche va por una costura nueva de base, **S16**, llamada desde el
     `_lifespan` antes del `yield`; la extensión expone `on_startup()` en `sentinel.redirect.api` (el paquete
     de `PLUGIN_PACKAGES`, `sentinel:sentinel/redirect/api/__init__.py:8`) y desde ahí corre
     `sentinel/redirect/seed_on_startup.py`. Las migraciones de la extensión ya corrieron al importar
     `main.py` (`backend/src/main.py:60-64`), así que las tablas existen cuando corre el enganche.
  5. `[ELEIA]`: el override de desarrollo de la extensión (`sentinel/docker/compose.dev.yml`) fija
     `SENTINEL_ENTITY_REGION=latam_ar` (como `.env.example:194` y el instalador), con check de release; el
     `docker-compose.yml` de la raíz no cambia (es el de la suite de CI y cambiarlo cambia la base para todos,
     R6; QA re-análisis M1). `deploy/docker/compose.prod.yml` **conserva** `eu`: `deploy/release/bundle.sh:58` lo empaqueta para todo
     perfil de cliente, incluidos los europeos, cuyo enmascarado depende de los patrones de `eu`
     (`litellm/extensions/sentinel_guardian_policy.py:131-137`); cambiarlo violaría FR-001/FR-007 para ellos.
     Un perfil de `deploy/clients/*` que active la extensión sin fijar la región cae en el respaldo
     fail-closed de (2) con `/api/v1/redirect/health` en 503 (QA re-análisis F1). Precisión (QA v2 N9):
     `compose.prod.yml` **inyecta** `SENTINEL_ENTITY_REGION: "${SENTINEL_ENTITY_REGION:-eu}"` (`:112`, `:201`),
     así que ahí la región nunca queda sin resolver: resuelve a `eu`, no hay fila de región para `eu` (el seed
     de Eleia es `AMERICAS`) y el estado es `region_row_missing` con alcance `region_codes(eu)`, no
     `region_unresolved`. Igual de fail-closed; cambian el diagnóstico y el texto (T094, T080, T081).
  6. **Un único `tenant_region()`** (QA v2 N5): el default `eu` se repite en tres sitios de Sentinel
     (`sentinel:sentinel/redirect/plugin.py:134-137`, `sentinel:sentinel/redirect/api/admin.py:571` en
     `list_postures`, lo que muestra el panel, y `sentinel:sentinel/redirect/api/us5.py:197` en `run_fidelity`);
     los tres pasan a usar la misma función sin caída a `eu`, para que el panel y la prueba de fidelidad digan
     lo mismo que el tráfico (T060, T094).
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
     `input_schema`, `user` y `name` de OpenAI y campos desconocidos), **salvo** una lista cerrada de
     posiciones estructurales. **Exenciones por posición del protocolo, nunca por nombre de clave** (QA v2 N8):
     la lista es una tabla de rutas (`contracts/costuras-base.md` §S14, «Posiciones exentas»), por formato
     (Anthropic Messages y OpenAI chat), p. ej. `messages[*].role`, `messages[*].content[*].id` de un bloque
     `tool_use`, `tools[*].name`, `messages[*].tool_calls[*].function.name`, `max_tokens`; un campo llamado
     `id`, `name`, `type` o `role` en cualquier otra ruta no está exento. Dos clases:
     - **Opacas** (no se analizan ni se reescriben, porque el valor no viaja como lo mandó el cliente o no es
       texto): `model` (en el camino redirigido tiene que ser un id publicado y la extensión lo reemplaza por el del
       destino; analizarlo daría falsos positivos con los ids fechados, `-20250929` cumple el patrón de DNI de
       `latam_ar`, `litellm/extensions/sentinel_guardian_policy.py:142`), `signature`
       de `thinking` (solo hacia nativos; hacia traducidos la extensión la reconstruye, R10), los datos base64
       de `source.data`/`file_data` (van por el camino de PDF o son no analizables) y `cache_control` con forma
       validada (solo `type`/`ttl` con valores del protocolo; otra forma ⇒ no analizable).
     - **Estructurales** (se analizan pero **no se reescriben**, porque reescribirlas rompe el pedido): roles,
       tipos de bloque, ids de bloques y llamadas, nombres de herramienta, `media_type`, los parámetros
       numéricos del protocolo en su ruta (`max_tokens`, `temperature`, `top_p`, `top_k`,
       `thinking.budget_tokens`, `seed`, …) y, dentro de `input_schema`/`parameters` (JSON Schema), las palabras
       clave del esquema, los nombres de propiedad (claves de `properties`) y `required[*]`. Una detección en
       una posición estructural **no** se enmascara: cuenta como no analizable (`structural_entity`) y el
       pedido se bloquea (fail-closed; un id o un nombre de herramienta no pueden contrabandear un dato).
     - **Subárboles libres** (todo lo demás, en particular `tool_use.input`, `tool_calls[].function.arguments`
       parseados, `metadata`, los valores `description`/`title`/`enum`/`const`/`default`/`examples`/`pattern`
       del esquema y los campos desconocidos): no se exime nada; **las claves de objeto se analizan y se
       enmascaran** como cualquier valor; los **escalares numéricos** se analizan como su texto decimal (un
       entero detectado se reemplaza por el marcador como cadena; la respuesta lo restaura como cadena); booleanos
       y `null` no llevan datos y no se analizan.
     La tabla de posiciones vive en el guardrail como dato con un test que la compara con el contrato: agregar
     una posición es un cambio de contrato con test.
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
  3b. **Aislamiento de la extracción** (QA v2 N4; la entrada es del cliente y `pypdf` es síncrono, mientras el
     guardrail corre en el bucle asíncrono del motor): la extracción **nunca** corre en el bucle de eventos ni
     en un hilo del motor (un hilo no se puede matar al vencer el plazo ni acotar en memoria). Corre en un
     **proceso hijo** por PDF (`python -I -m` del módulo de base `litellm/extensions/sentinel_pdf_extract.py`, con el PDF por la entrada estándar y el texto por la
     salida), con límites del sistema operativo fijados antes de importar `pypdf`: memoria `RLIMIT_AS` =
     `MASKING_PDF_MAX_MEMORY_MB` (512) y CPU `RLIMIT_CPU` = plazo + 5 s; plazo de reloj `MASKING_PDF_TIMEOUT_S` (20 s), al
     vencer el hijo se mata; concurrencia acotada por un semáforo `MASKING_PDF_MAX_CONCURRENCY` (2) por proceso
     del motor; el bucle solo espera al hijo. **Por pedido** (análisis de la QA v2, M5): a lo sumo `MASKING_PDF_MAX_PER_REQUEST` (5) PDF y un plazo total `MASKING_PDF_REQUEST_DEADLINE_S` (30 s) que incluye la espera del semáforo; superarlos ⇒ no analizable `pdf_request_limit`. **Caché por hash**: el resultado (texto o veredicto de falla) se guarda en memoria del proceso por SHA-256 de los bytes, acotado (`MASKING_PDF_CACHE_ENTRIES`, 32), nunca persistido ni registrado, para que el historial que Claude Code y Desktop reenvían en cada turno no re-extraiga el mismo PDF (ni el hostil). **Tope de expansión**: el hijo baja los límites de
     descompresión de `pypdf` (`pypdf.Configuration`, por flujo, 75 MB por defecto en la 6.19.0,
     `pypdf/_configuration.py`) a `MASKING_PDF_MAX_STREAM_BYTES` (25 MB) y corta al superar
     `MASKING_PDF_MAX_TEXT_CHARS` (2 000 000) de texto extraído. Plazo vencido, memoria agotada, salida no
     cero, tope de expansión o de texto superado ⇒ **no analizable** (`pdf_timeout`, `pdf_resource_limit`,
     `pdf_error`; correspondencia en contracts/costuras-base.md §S14) y el pedido se bloquea bajo forzado; el proceso del motor sigue sirviendo. `pypdf` se fija
     en una versión con `pypdf.Configuration` y límites de descompresión (6.19.0 verificada el 2026-10-06), con
     hash (T091); el test de PDF hostil (bomba de compresión y páginas densas) prueba los topes propios aunque
     la librería cambie. Los valores por defecto son iniciales y los ajusta la medición de T097.
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
  informativa con PDF y otra de un pedido típico de Claude Code de solo texto con alcance completo. Los topes de páginas, bytes, tiempo, memoria y expansión acotan el peor caso
  (fallan cerrado). Riesgo de seguridad del parser: corre en un proceso hijo del motor con límites (3b), sin
  credenciales, sobre bytes del propio cliente; los errores del parser cuentan como no analizable y un PDF hostil no
  bloquea el bucle del motor para el resto de la empresa. Costo del aislamiento: el arranque del hijo
  (`python -I -c "import pypdf"`: 0,13–0,15 s medido el 2026-10-06 con `pypdf` 6.19.0 en Python 3.12, fuera
  del motor; T097 lo mide dentro) se suma solo a los pedidos con PDF bajo forzado.
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
- **Límite conocido, fuera de la 057** (QA v2 N3): la separación es **por rol**, y hoy el admin de empresa puede
  dar de alta un usuario con cualquier rol de `VALID_ROLES` (`backend/src/models/user.py:9`; `POST /users` exige
  solo `require_role("admin")`, `backend/src/api/users.py:413-414`), incluidos `compliance_officer` y
  `super_admin`. Es una propiedad previa de la base y la cierra un **arreglo aparte en la base** (otra tarea del
  plan del coordinador, con su propio PR); la 057 no lo implementa ni lo duplica. Referencia en T055 y T080:
  la documentación describe la garantía según el estado de ese arreglo al cerrar T-G (sin él, «no desde el rol
  de administrador de empresa; quien administra usuarios puede designar al responsable de cumplimiento, y
  queda en el registro»); nunca «el administrador no puede relajar» sin ese respaldo.
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
- **Dónde corta la dependencia** (QA v2 N2): en la rama del ensayo el arreglo solo **verificaba** la exposición
  y dejaba el proxy como propuesta (`ENSAYO-SEPARAR-BASES.md:168-195` de `cluna-8/fix-separar-bases-motor`); el
  coordinador confirmó que el proxy y `INTERNAL_ALLOWED_CIDRS` los entrega la **vuelta 2** del arreglo de bases,
  que también es quien prueba `auto` contra el compose real (el ensayo advierte que lo publicado puede llegar
  con la IP del puente de Docker, `:193-195`). La 057 no empeora la exposición previa: la credencial de
  proveedor queda cerrada por la capa 1 (T090) y `/model-catalog` y `/model-access` no devuelven secretos. Por
  eso la dependencia **no** bloquea T-A ni T-B: el gate pasa a **T-H** (T089, T100, T101): `ELEA_REDIRECT=1` no
  se activa en una instalación sin el proxy y S15 de la vuelta 2, y T102 comprueba `/api/v1/internal/*` ⇒ 404
  desde la LAN con la variante `-ext`. El «va antes que esta feature» de la precisión del coordinador (`spec.md:241`) se cumple así: la dependencia va antes de que la feature se **active** en una instalación (T-H).

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

## R33. Arranque de la extensión — S16 (QA v2 N1; FR-031, FR-004d)

- **Hechos**: S1 monta routers y nada más (`sentinel:backend/src/plugins.py:9`, `:81-88`); Eleia y Sentinel crean
  la app con `lifespan=_lifespan` (`backend/src/main.py:80-101`; `sentinel:backend/src/main.py:88`, `:108`); con
  FastAPI 0.111.0 (`backend/requirements.txt:1`) un `APIRouter(on_startup=[…])` incluido no corre bajo `lifespan`
  (ensayo del 2026-10-06 en un entorno aislado con `fastapi==0.111.0`, `starlette==0.37.2`: con `lifespan` solo
  corrió el `lifespan`; sin él, el `on_startup` del router sí). El `_lifespan` ya arranca dos tareas de fondo con
  compuerta propia (`backend/src/main.py:85-89`, `retention_scheduler`).
- **Decisión [BASE], costura nueva S16** (retrocompatible): `backend/src/plugins.py` suma
  `run_plugin_startup()`, que recorre los paquetes de `PLUGIN_PACKAGES` en su orden y llama a `on_startup()` de
  los que lo exponen (opcional; una función síncrona corre con `asyncio.to_thread`, una corrutina se espera);
  el `_lifespan` lo llama antes del `yield`, después de arrancar los schedulers, así que corre **antes de servir**
  el primer pedido **de ese proceso**: con varios workers (`WEB_CONCURRENCY`, 2 en `deploy/docker/compose.prod.yml:115`) corre una vez por worker, a la vez, así que el `on_startup` de la extensión tiene que ser seguro ante concurrencia (cerrojo consultivo de Postgres alrededor de la siembra, más altas idempotentes; análisis de la QA v2, M3). Sin `PLUGIN_PACKAGES`, o sin `on_startup` en el paquete, no hace nada. Un `on_startup` que
  falla se registra con el nombre del paquete y **no** tira el arranque (la extensión decide su respaldo: para
  la redirección, el de R28, y como la siembra es condición de su fail-closed, `/api/v1/redirect/health` lo informa con el 503 del respaldo; registrado en la spec por `speckit-clarify`, Clarifications «QA v2», fila S16 de C-1 y FR-031). `sentinel.redirect.api` expone `on_startup()` → `sentinel/redirect/seed_on_startup.py`.
- **Test**: contra `src.main:app` con su `lifespan` real (`TestClient` como gestor de contexto, con
  `RUN_ALEMBIC_ON_STARTUP=false` para no migrar al importar), no contra un `FastAPI()` suelto: el test de un
  `FastAPI()` sin `lifespan` pasaría aunque el enganche no corriera en la app real.
- **Por qué S16 y no otra cosa**: es el único punto que corre antes de servir en la app real; carga perezosa en
  el primer pedido o en `/health` deja la instalación en respaldo hasta que alguien pida y suma demora al primer
  pedido; que el instalador corra `python -m sentinel.redirect.regions_seed` (T064) en el contenedor solo sirve
  al instalador y no a los perfiles de cliente ni al desarrollo. **Vuelve a Sentinel por HANDOFF** (T085): su
  `main.py` tiene el mismo `lifespan`.

## R34. Caché de análisis por segmento del enmascarado forzado — S17 (decisión del owner, 2026-10-06; FR-027, FR-045, SC-010)

- **Hechos**: el alcance completo de S14 analiza todo lo que sale hacia el destino (R29). Un pedido típico de Claude Code
  (60 herramientas, 24 turnos, 125 KB) son **299 llamadas al analizador y ≈ 93 000 caracteres**
  (`handoff-notas-tramo-e2.md`, medición informativa de `sentinel/tests/perf/test_masking_pdf_overhead.py`); a los 330
  caracteres/s que declara `.env.example` para el analizador real son **≈ 280 s por turno** sin caché. La herramienta
  reenvía el historial completo en cada turno, y el historial casi no cambia entre turno y turno: `litellm/extensions/sentinel_guardian_policy.py`
  (`_FullScopeMasker.prefetch`) solo memoriza **dentro del pedido**, y el análisis previo de `sentinel_guardrail.py` (`inspect_text`,
  tope `INSPECT_CAP` = 16 000) es un texto unido que cambia con cada turno mientras la conversación no pase el tope.
- **Decisión del owner**: el enmascarado forzado **sigue con alcance completo por defecto**. **No** se reduce al último mensaje:
  el cliente reenvía el historial en claro (lo que recibió ya restaurado) y los datos personales viven en los `tool_result`
  (resultados de herramientas que leyeron archivos, bases o correos), no en lo que escribe la persona. La latencia se resuelve con una
  **caché de análisis**, no con menos protección.
- **Diseño [BASE], costura nueva S17** (retrocompatible; genérica, sin cadenas de Elea; vuelve a Sentinel por HANDOFF):
  - **Qué se cachea**: el resultado de **analizar un segmento de texto** = solo detecciones `(inicio, fin, tipo de entidad, puntaje)`.
    **Jamás** el texto, el valor detectado ni un placeholder; los placeholders se siguen generando en cada pedido con el sufijo de S13
    (`PlaceholderMap`), así que la caché no puede romper la restauración ni la estabilidad de la conversación (R18).
  - **Clave**: `SHA-256(versión de configuración | idioma | alcance | texto)`. La **versión de configuración** deriva (hash) de lo
    que cambia el resultado del analizador: región, nombres y entidades propias de la empresa (`custom_names`, `custom_entities`), URL del analizador y la
    sal manual `MASKING_ANALYSIS_CACHE_SALT` (para cuando cambian los reconocedores del analizador sin cambiar nada de lo anterior); cualquier cambio
    **invalida** (otra clave, no se borra). El **alcance** es la empresa: dos empresas no comparten entradas aunque el texto coincida (el aviso
    de que un segmento «ya se vio» no cruza empresas; sin esto la latencia sería un canal lateral para sondear texto ajeno).
  - **Almacenamiento**: en proceso (sin Redis: nada de lo cacheado sale del proceso del motor y se pierde al reiniciar), LRU acotada por entradas
    (`MASKING_ANALYSIS_CACHE_MAX_ENTRIES`, 20 000) y TTL (`MASKING_ANALYSIS_CACHE_TTL_S`, 3 600 s); `MASKING_ANALYSIS_CACHE_ENABLED=false` la apaga
    (queda la memoria por pedido de siempre). Un segmento con más de 1 000 detecciones no se cachea (acota la memoria por entrada).
  - **No se cachea lo que no es del analizador real**: una falla del analizador (`NlpUnavailableError`) no se cachea y pasa tal cual (el
    fail-closed y `nlp_fail_mode` no cambian); el resultado del regex de respaldo del modo `degrade` tampoco (otro analizador, otra clave: no entra).
  - **Análisis previo**: bajo forzado, el análisis previo por tipo (BLOCK vs MASK) se hace **por segmento y por la misma caché** (los mismos
    segmentos que recorre el enmascarado), así que no suma una segunda pasada y un turno N+1 analiza solo lo nuevo; sin forzado queda como hoy.
  - **Equivalencia**: el resultado del enmascarado es **idéntico con y sin caché** (test de equivalencia): la caché solo evita llamar de nuevo al
    analizador con el mismo texto y la misma configuración.
- **Excepción configurable (apagada por defecto)**: dos opciones del operador de la instalación, `MASKING_EXEMPT_SYSTEM_PROMPT` y
  `MASKING_EXEMPT_TOOL_DEFINITIONS` (por defecto `false`), que suman posiciones **opacas** a la tabla `S14_EXEMPT_POSITIONS` de E2 (el `system` del
  pedido y `tools`, en los dos formatos; en el formato OpenAI el `system` son los turnos `system`/`developer`). **Trade-off documentado**: con
  la caché, analizar el `system` y las herramientas cuesta una sola vez por texto y por empresa, así que la exención solo ahorra el primer turno de
  cada conversación nueva con otro `system`; a cambio, el `system` de las herramientas de código lleva datos personales reales (memoria del
  usuario, correo de la cuenta, estado del repositorio con nombres) y las descripciones de herramientas pueden llevar ejemplos con datos. **Apagado = todo
  se analiza.** Encenderlo es una decisión explícita de la instalación: el informe del enmascarado lista los nombres exentos (`exempt`, solo nombres) y el
  guard los copia a la decisión de auditoría, así que queda registrado que el piso se relajó; no hay forma de encenderlo desde el pedido.
- **Alternativas descartadas**: (a) enmascarar solo el último mensaje: deja en claro el historial y los `tool_result`, que es donde está el dato
  (decisión del owner); (b) caché compartida en Redis: persistiría huellas de texto fuera del proceso y sumaría un salto de red por segmento, sin
  necesidad (el costo de un arranque en frío es una conversación, no el servicio); (c) cachear el texto enmascarado: ataría la caché al sufijo de la
  conversación y guardaría el texto (R18, Principio I).
- **Medición** (T113, sin Docker, analizador simulado a 330 caracteres/s): conversación sintética de ≈ 93 000 caracteres; el turno 2 solo analiza lo
  nuevo. La cifra real con el analizador activo la toma la corrida con Docker (T045/T083; 🐳).
- **Por qué S17 y no dentro de S13/S14**: es una costura de base con su propio contrato, variables y test; no cambia ninguna garantía de S13 ni de S14.

## R35. Posiciones estructurales con el NER real: vocabulario cerrado y tipos semánticos — enmienda de N8 sobre S14 (decisión del owner, 2026-10-06; FR-027, SC-006)

- **Hechos** (gate de la 057, analizador real: spaCy `es` + reconocedores de patrón): R29.2 manda que una detección en una posición
  **estructural** (no se reescribe, porque cambiarla rompería el pedido) sea `structural_entity` ⇒ no analizable ⇒ bloqueo. Con el
  analizador simulado de las suites no se veía; con el real, el NER marca como PERSON/LOCATION/ORGANIZATION/URL cadenas del protocolo y
  de las herramientas: `assistant`, `tool_use`, `Read`, `file_path`, `Herramienta3`, `toolu_01A09…`, `0.py`. Resultado medido: un
  pedido `user`/`assistant`/`user` ya se bloqueaba (`assistant` como PERSON) y el pedido sintético de Claude Code (60 herramientas,
  24 turnos, ≈ 93 000 caracteres) daba **206 `structural_entity`**: el forzado completo era inusable para el caso que justifica S14.
- **Decisión del owner**: **no** se vuelve a eximir por nombre de clave ni se apaga el bloqueo de lo estructural (N8 sigue en pie). Se
  separa lo que fija el protocolo de lo que elige el cliente:
  - **(A) Vocabulario cerrado**: el valor de una posición cuyo conjunto de valores lo fija el protocolo (`messages[*].role`, `type` de bloque,
    `…source.type`, `…source.media_type`, `thinking.type`, `tool_choice.type`, `tools[*].type`; en OpenAI además `response_format.type`,
    `tool_choice` cadena, `tool_calls[*].type`) y que **está dentro de ese conjunto** no se analiza. Uno fuera del conjunto (un rol
    `Juan Pérez`, un DNI como rol) se analiza como siempre ⇒ sigue bloqueando. En el esquema de herramientas, las palabras clave del
    JSON Schema, los `type` de JSON y los `format` estándar son el mismo caso.
  - **(B) Vocabulario abierto** (el cliente elige la cadena: `tools[*].name`, `tool_choice.name`, `id` y `name` de `tool_use`,
    `tool_use_id` de `tool_result`, claves de `properties`, `required[*]`, `$ref`; en OpenAI `tool_call_id`, `tool_calls[*].id`,
    `…function.name`, `response_format.json_schema.name`): se ignoran **solo** los tipos de una lista cerrada de NER semántico
    (`STRUCTURAL_IGNORED_ENTITY_TYPES`: PERSON, LOCATION, ORGANIZATION, NRP, URL, DATE_TIME). Los de patrón y los propios de la empresa
    (`custom_entities`) o desconocidos siguen siendo `structural_entity`.
  - **Solo bajo el enmascarado forzado y solo en esas posiciones**: el texto de los mensajes, `tool_result`, `thinking`, `system`,
    `tool_use.input`, las descripciones y los subárboles libres se analizan y enmascaran como antes (los tipos semánticos se siguen
    enmascarando ahí). Una palabra clave de esquema fuera del vocabulario o un campo desconocido de primer nivel se analiza estricto.
- **Detalle que importa (hallado con TDD)**: el descarte de los tipos semánticos va **antes** de resolver solapes. El solapamiento se
  resuelve por la detección más larga (`resolve_overlaps`, FR-009): si el NER marca `leer 30123456` entero como PERSON, esa detección
  larga tapa al DNI que va adentro, y filtrar después la dejaría pasar. Por eso los identificadores se analizan con
  `identifier_entities` (filtra y recién entonces resuelve). Reusa el mismo análisis cacheado de S17 (mismo texto ⇒ mismo resultado
  del analizador, sin llamada nueva).
- **Qué no cambia**: el contrato de S14 (señal, alcance, tabla de posiciones, informe, restauración), la clase de cada posición
  (siguen «estructurales»: no se reescriben) y la garantía de que ningún dato personal viaja en claro: lo único que deja de bloquear es
  una cadena del protocolo o un identificador que el NER confunde con un nombre propio. Los secretos (`SECRET_PATTERNS`) no son un tipo
  del analizador sino un detector aparte: no cambian.
- **Alternativas descartadas**: (a) eximir las posiciones estructurales por completo: un DNI en el nombre de una herramienta saldría en
  claro (reabre N8); (b) reescribir los identificadores enmascarados: rompe el pedido (el destino no reconoce la herramienta);
  (c) listas de nombres propios exentos («Read», «Bash»…): es exención por nombre; (d) bajar el puntaje de NER: no es determinista ni
  explicable; (e) filtrar los tipos semánticos después de resolver solapes: ver «Detalle que importa».
- **Costo/riesgo**: un identificador con un nombre de persona real (`tools[*].name = "juan_perez"`) pasa sin bloquear porque el tipo es
  semántico: es el trade-off aceptado por el owner (un nombre de herramienta no es un dato personal del titular; si lleva un DNI, un
  email, un teléfono, una tarjeta o un IBAN, bloquea).
- **Tests**: `backend/tests/unit/test_masking_vocabulario_estructural.py` (rol `assistant`, 24 turnos con 60 herramientas, vocabulario
  fuera del conjunto, DNI/CUIT/CBU/email/tarjeta/IBAN/teléfono en cada posición abierta, tipo propio de la empresa, texto libre
  intacto, instantánea de las tablas del contrato).

## R36. Escalares numéricos en posiciones estructurales con el NER real — hallazgo del gate «claude -p» sobre R35 (2026-10-06; FR-027, SC-006)

- **Hechos** (pedido REAL de Claude Code 2.x por `/v1/messages?beta=true`, capturado con un servidor local; 21 herramientas, 3 bloques de `system`
  con `cache_control`, un mensaje `role: system` en `messages`, `thinking.display`, `output_config`, `context_management`, `safeguards`; ≈ 75 KB):
  con R35 aplicada el pedido seguía dando 400 `masking_required`. Se repasó el pedido con el recorrido real y el analizador real (sidecar
  del stack): **14 `structural_entity`, todos la misma cadena `1`**, clasificada LOCATION (0,85), en `tools[*].input_schema`: las palabras clave
  numéricas `minLength: 1` de los esquemas. Los demás números (`0`, `256`, `9007199254740991`, `128000`, `0.5`) no se marcan. No era ni el `system`,
  ni las descripciones, ni `cache_control`, ni `metadata.user_id` (no interviene: el pedido real pasa con él), ni los campos nuevos del primer nivel (clave y valor
  pasan sin detección), ni el tipo de bloque.
- **Causa**: R35 cubrió el vocabulario cerrado y los identificadores **de texto**; un escalar numérico en una posición estructural seguía por el
  camino estricto (`("scan", n)`, cualquier detección ⇒ `structural_entity`). El mismo defecto estaba latente en `temperature: 1`, `top_k: 1` y
  `max_tokens: 1`.
- **Decisión**: el valor numérico de una posición estructural es de vocabulario abierto (cualquier número es válido para el protocolo), así que se le
  aplica **la regla (B) tal cual**: se ignoran los tipos semánticos y siguen bloqueando los de patrón y los propios de la empresa. No se exime nada
  nuevo: un DNI como valor numérico sigue bloqueando; el texto de los mensajes, `tool_result`, `thinking`, `system`, `tool_use.input`, descripciones,
  `default`/`examples` y los números de subárboles libres (que se enmascaran como marcador) no cambian.
- **Segunda causa (turno 2 de la misma sesión)**: con los números arreglados, el turno 1 pasaba (DNI enmascarado hacia el destino) y el turno 2
  —el que lleva el `tool_use` del modelo y el `tool_result`— daba 1 `structural_entity`: la CLAVE `is_error` del bloque `tool_result` (booleano que
  manda Claude Code), clasificada LOCATION. No estaba en la tabla de posiciones, así que era «campo desconocido» (clave analizada estricta). Es un
  campo del protocolo, no un dato: se agrega `….is_error@tool_result` a las posiciones estructurales (vocabulario cerrado del protocolo, A). Los campos
  desconocidos de verdad siguen estrictos (S14 punto 3, sin cambios); un valor no booleano en `is_error` también se analiza.
- **Alternativas descartadas**: (a) eximir `minLength` y compañía por nombre de palabra clave: es exención por nombre; (b) tratar el `1` como
  vocabulario cerrado: los números no tienen conjunto cerrado; (c) bajar el puntaje del NER: no es determinista; (d) no analizar los números
  estructurales: un DNI en un `max_tokens` saldría en claro.
- **Tests**: `backend/tests/unit/test_masking_vocabulario_estructural.py` (`test_pedido_real_de_claude_code_con_numeros_de_esquema_no_se_bloquea` con la
  forma del pedido real y un analizador que marca `1` como LOCATION; parámetros `temperature`/`top_k`/`max_tokens`; un DNI numérico sigue bloqueando;
  números de texto libre siguen enmascarándose; el prefetch pide los números al analizador).

## R37. El detector de secretos sin límite izquierdo bloqueaba pedidos auxiliares de Claude Code — hallazgo del gate «claude -p» (2026-10-07; FR-027)

- **Hechos** (fila `blocked_secret`, capa `secret_detection`, modelo `rdx-azure/gpt-5.1-chat`, en `audit_logs` de la corrida de R36; la fila solo trae metadatos, así
  que el cuerpo se **recapturó**): `claude -p` real (Claude Code 2.1.292) por un proxy local del scratchpad hacia la pasarela, 16 pedidos. Repasados con
  `extract_inspect_text` de alcance completo y `detect_secrets`: **3 pedidos auxiliares** (sin herramientas; `max_tokens` 2112 los dos del clasificador del modo auto y 64 el de un
  modelo sin regla, que se rechaza antes por política) llevan en `system[1].text` (un texto FIJO de Claude Code, no del usuario) una palabra inglesa compuesta `task-<palabra>`
  (15 caracteres desde `sk-`, solo letras minúsculas). El patrón `sk-[a-zA-Z0-9]{10,}` (`litellm/extensions/sentinel_guardian_policy.py`, `SECRET_PATTERNS`) la toma como
  «OpenAI API Key». Los pedidos principales (21 herramientas) llevan la misma palabra en `tools[19].description`, pero **después** de los primeros `INSPECT_CAP` = 16 000
  caracteres que entregan los detectores, y por eso pasaban: el bloqueo dependía de la posición, no de la credencial.
- **Causa**: el patrón no mira qué hay antes de `sk-`; cualquier palabra que termine en `sk` (`task`, `risk`, `disk`, `ask`, `desk`, `mask`) seguida de un guion y diez
  letras es «clave». Nada que ver con S14, el NER ni el enmascarado.
- **Decisión**: límite izquierdo `(?<![a-zA-Z0-9])` antes de `sk-`. Es el cambio mínimo que no quita ninguna clave real: una credencial va sola, tras `=`, `:`, comillas, paréntesis,
  `Bearer`, salto de línea o guion bajo, nunca pegada a una letra o dígito anteriores (el test lo fija con 20 contextos y tres largos de clave). Se mantiene el resto del
  patrón (10 alfanuméricos mínimo; `redact_secrets` usa la misma tabla, así que previews y monitor siguen coherentes).
- **Alternativas descartadas**: (a) subir el largo mínimo: pierde claves de test cortas, que es lo que corrigió la spec 010 al bajarlo de 48 a 10; (b) no inspeccionar `system`
  del clasificador por nombre: exención por nombre y hueco para un secreto real en esa posición; (c) quitar la capa bajo forzado: los secretos no salen hacia ningún
  destino. **Fuera de alcance, anotado**: las claves modernas `sk-proj-…` (llevan guiones tras 4 caracteres) no las toma este patrón, mientras que `guardian_service.py:233`
  (el camino de chat de la consola, configurable) sí y no tiene límite izquierdo; ninguna de las dos cosas se cambia acá (**lo cierra R38**).
- **Tests**: `backend/tests/unit/test_secret_detection_limite_izquierdo.py` (73; 11 en rojo antes del cambio): palabras corrientes no son clave, la clave real se detecta en
  cada contexto, los otros patrones no cambian y, con la forma del pedido auxiliar real, el texto fijo pasa y una clave real en esa posición bloquea.

## R38. Las llaves OpenAI actuales no se detectaban en el motor y los dos caminos tenían criterios distintos — cierra el «fuera de alcance» de R37 (2026-10-07; FR-027)

- **Hechos**: el detector de secretos tenía **dos patrones distintos** para la misma llave. El del motor (`SECRET_PATTERNS["OpenAI API Key"]`,
  `litellm/extensions/sentinel_guardian_policy.py:370`, tras R37) pedía `sk-` + 10 alfanuméricos **seguidos**: `sk-proj-…`, `sk-svcacct-…` y `sk-admin-…` llevan un guion
  tras el prefijo, así que **no se detectaban** y salían hacia el destino. El del backend (`GuardianService`, camino de chat de la consola, `sk-(?:proj-)?[A-Za-z0-9_-]{20,}`)
  sí las veía pero **sin límite izquierdo**: `task-implementation-of-the-risk-assessment` (…`sk-` + 20 caracteres con guiones) era «clave» en ese camino, el mismo falso positivo de R37.
- **Causa**: dos literales que evolucionaron por separado (el del motor acaba de cambiar en R37; el del backend no) sin que nada obligara a que coincidieran.
- **Decisión**: **un solo criterio**, `(?<![a-zA-Z0-9])sk-(?:[A-Za-z0-9_-]{20,}|[A-Za-z0-9]{10,})`. La rama larga (guiones y guiones bajos, ≥ 20) va **primero** para que la
  redacción cubra la llave entera y no se quede en el primer tramo alfanumérico; la corta conserva las `sk-<alfanumérico>` de 10 en adelante (las de test cortas que la spec 010
  quiso seguir viendo). El límite izquierdo de R37 se mantiene. `GuardianService` ya no tiene literal propio: `OPENAI_KEY_PATTERN = policy.SECRET_PATTERNS["OpenAI API Key"]`
  (`backend/src/services/guardian_service.py:13`; usado en `:236`), con `policy` ya importado de la librería compartida. Efecto: `sk-proj-`/`sk-svcacct-`/`sk-admin-` se detectan en
  el motor; `task-`/`ask-`/`desk-` largas ya no son clave en el backend; el motor además ve lo que antes solo veía el backend (`sk-ant-…`, llaves con guiones). No baja ninguna
  detección previa, salvo la de una llave pegada a una letra o dígito anteriores (decisión de R37, ahora también en el backend).
- **Alternativas descartadas**: (a) arreglar solo el motor y dejar el literal del backend (queda la divergencia que causó esto; el test de paridad no tendría qué comparar);
  (b) la rama corta primero (la alternancia toma la primera que casa: la redacción de `sk-proj-abc…` cubriría solo el tramo alfanumérico inicial y dejaría el resto de la llave en claro;
  `test_motor_redacta_la_llave_moderna_completa` lo fija).
- **Tests**: `backend/tests/unit/test_secret_detection_llaves_modernas.py` (165; 73 en rojo antes del cambio): las cinco formas modernas en el motor y en el backend, `task-`/`ask-`/`desk-`
  largas que no son clave en ninguno, las viejas y toda detección previa se conservan, la redacción cubre la llave entera (`test_motor_redacta_…`, `test_backend_redacta_…`) y
  `test_un_solo_criterio_en_los_dos_caminos` (paridad). Las llaves de los tests se generan con un `random.Random` con semilla: ninguna es una credencial real.
  `test_secret_detection_limite_izquierdo.py` (R37, 73) y `test_pilot_fixes.py` (Bug 3) siguen verdes.
- **Para Sentinel**: aplicar el mismo patrón en su `policy.py` y en su `guardian_service` (fila «Detector de secretos» del `HANDOFF-elea-a-sentinel.md`).

## R39. Un binario que devuelve una herramienta no se bloquea bajo el forzado: se reemplaza por una nota — enmienda de S14 (decisión del owner por el coordinador, 2026-10-07; FR-027, SC-006)

- **Hechos**: Cowork crea archivos (presentaciones, PDF, documentos, imágenes) ejecutando código en su entorno y **verifica el resultado con capturas de pantalla que
  vuelven como imágenes dentro de un `tool_result`**; además pide `max_tokens` ≈ 64 000. Bajo el enmascarado forzado (S14) una `image` es no analizable
  (`litellm/extensions/sentinel_guardian_policy.py`, `_w_block`, antes `yield ("flag", "image")`), el guard exige `unanalyzable = 0` (`sentinel/engine/redirect_guard.py`, `masking_ok`)
  y el pedido terminaba en `403/400 masking_required`: la tarea se cortaba en la primera captura. La cara Claude ya resolvía el mismo caso **por capacidad** del destino
  (`sentinel/redirect/faces/claude.py:214-290`, `_TOOL_NOTE`/`_omit_unsupported`/`_check_blocks`, porte de Sentinel #46), pero **solo** cuando la ficha del destino no declara la capacidad:
  con un destino que acepta imágenes la captura pasaba tal cual hasta S14, donde era no analizable.
- **Decisión** (la más restrictiva que no rompe Cowork): bajo la señal de forzado, una imagen, un audio o un documento **no analizable que está dentro de un `tool_result`**
  (Anthropic; en OpenAI, el contenido de un mensaje `tool`/`function`) se **reemplaza en el lugar por un bloque de texto con una nota neutra**; el binario **nunca** sale hacia el
  proveedor. Se cuenta aparte (`MaskingTally.replace`, `…policy.py:1086`) y **no suma a `unanalyzable`**. La nota reutiliza el criterio de la de la cara Claude (pide no
  volver a pedir capturas, para no entrar en un bucle) con texto neutro de marca blanca (sin nombres de componentes); la marca de caché válida del bloque pasa a la nota (FR-044).
  `_w_unanalyzable` (`:1476`) decide por el contexto (`in_tool_result`) que `_w_container` fija en las dos rutas de `tool_result` (`:1633-1638`).
- **Auditoría**: el informe del guardrail suma `unanalyzable_replaced` y `unanalyzable_replaced_kinds` solo cuando hubo reemplazos (`sentinel_guardrail.py:740-744`); el guard los
  copia a la decisión (`redirect_guard.py:258-271`, `:658-663`) con conteo entero y nombres de tipo `[a-z0-9_]{1,32}`: nunca contenido. Es el mismo canal de `masking_exempt`. El
  camino de suscripción del backend lo deja en el log, también con solo conteo y tipos (`backend/src/api/gateway.py:543-546`).
- **Lo que no cambia**: lo que **adjunta la persona** en su mensaje (imagen, audio o documento sueltos en un turno `user`) sigue bloqueando; un PDF con texto devuelto por una herramienta
  sigue como texto enmascarado (se ve y se enmascara); `redacted_thinking`, tipos desconocidos, `structural_entity`, `cache_control` inválido y `too_deep` siguen bloqueando dentro de un
  `tool_result`; sin la señal no se toca nada.
- **Costo asumido**: el agente **no revisa su resultado con la vista** bajo el forzado (revisa con texto). Es la contrapartida de que ningún binario salga sin analizar.
- **Alternativas descartadas**: (a) reconocimiento de texto en la imagen (OCR) para analizarla: fase siguiente, no hay motor; (b) permitir el binario hacia destinos «de confianza»: rompe
  el principio de que el forzado no tiene excepciones por destino para lo no analizable; (c) bloquear (lo que había): corta Cowork; (d) quitar el bloque sin nota: el modelo reintentaría
  la captura en bucle.
- **Tests**: `backend/tests/unit/test_masking_binarios_en_tool_result.py` (imagen/documento por URL/PDF ilegible en `tool_result` reemplazados; el texto vecino se enmascara; la marca de
  caché pasa; turnos anteriores; OpenAI `tool`; el PDF con texto sigue como texto; la imagen de la persona bloquea aun junto a un `tool_result`; los no binarios bloquean; el informe cuenta aparte
  y no lleva contenido; sin señal no se toca), `backend/tests/unit/test_masking_posiciones_exentas.py` (la tabla no cambia) y `sentinel/tests/unit/test_redirect_guard.py` (el guard acepta y
  registra `unanalyzable_replaced`; sigue bloqueando con `unanalyzable > 0`).
- **Para Sentinel**: costura S14 retrocompatible; fila nueva en `HANDOFF-elea-a-sentinel.md` §2. La cara Claude y la genérica no cambian.

## R40. Etiqueta por defecto `requested`, Kimi K3 por OpenRouter y modelos distintos por grupo — decisiones del owner por el coordinador (2026-10-07; FR-057, FR-058)

- **Etiqueta** (FR-057). Hechos: el default era `destination` (`models.py`, `admin.py`, formulario del panel), así que el selector de Claude Desktop mostraba «Sonnet · servido por <destino>» y
  el nombre del destino llegaba al cliente. **Decisión**: el default pasa a `requested` (el cliente ve el id Claude que pidió; nunca el destino) en tres lugares que deben coincidir: la columna
  (`sentinel/redirect/models.py:138`, con `server_default`), el esquema de la API (`sentinel/redirect/api/admin.py:279`) y el formulario (`sentinel/frontend/redirect/helpers.ts`, `PublishedTab`);
  y el recorrido de una fila sin modo (`faces/claude.py:30`, `:45`; la fila inferida de `plugin.py:423`). **Migración** `0529902015ad` (id por hash, rama `sentinel_redirect`, sigue a `89a92524eef6`):
  solo `alter_column … server_default`; **las filas existentes no se tocan** (`destination` y `custom` son una elección del administrador). Mostrar el destino o una etiqueta propia sigue siendo
  una elección **por id**. No hay seed que fije el modo (el administrador publica por la API). Tests: `sentinel/tests/unit/test_redirect_etiqueta_solicitada.py` (default; `/v1/models` y respuestas,
  cuerpo y eventos de *streaming*, sin el nombre ni el modelo real del destino; `destination` sigue mostrándolo porque es explícito) y `sentinel/tests/integration/test_migracion_etiqueta_solicitada.py`
  (sube, baja, no toca filas). Para Sentinel: cambio de default **opcional** (retrocompatible; lo que ya tenga publicado no cambia).
- **Kimi K3 por OpenRouter** (FR-058). El id real en la lista pública de OpenRouter (`https://openrouter.ai/api/v1/models`, 2026-10-07) es **`moonshotai/kimi-k3`**: ventana 1 048 576, entrada
  texto/imagen/video, herramientas, precio 0,62 / 15 US$ por millón; existe además la variante `:batch`, que no se usa. **Hallazgo**: el alta guiada **no podía** dar de alta ningún modelo de OpenRouter,
  porque este exige los proveedores permitidos (`providers_allowlist`, FR-032) y el formulario no los pedía ni los mandaba. **Arreglo mínimo y retrocompatible**: `provider_options` compartido en el
  alta en lote (`sentinel/catalog/api/reference.py`) y el campo «Proveedores permitidos» solo para OpenRouter (`sentinel/frontend/models/guided.ts`, `GuidedEntryForm.tsx`). La **ficha** lleva la jurisdicción de
  inferencia, de entidad y de control del **proveedor final**, no las del agregador ni las de quien desarrolló el modelo (ejemplo en `docs/docs/administration/redireccionamiento.md`). Una regla mueve
  `claude-sonnet-…` de Azure a Kimi sin tocar el cliente: `sentinel/tests/integration/test_redirect_sonnet_azure_a_kimi.py` (guard real con dos destinos: mismo id, mismo `model` en la respuesta, otro destino).
- **Grupos** (FR-058). No siempre son tres modelos: con lo que ya existe (ids publicados y reglas con alcance de grupo + perfil de acceso por proveedor) un grupo «Todos» ve tres ids más uno
  extra hacia Kimi y un grupo «Solo Azure» solo los que van a Azure. `/v1/models` de cada llave lista solo lo suyo; el id de otro grupo da el error neutro sin nombrar destinos; un grupo
  restringido a Azure nunca llega a Kimi, ni siquiera por una regla de la empresa. **Sin UI ni modelo de datos nuevos.** Test: `sentinel/tests/integration/test_redirect_grupos_azure_y_todos.py`.
- **Alternativas descartadas**: migrar las filas existentes a `requested` (cambia en silencio una elección del administrador); sembrar un modo por instalación (la etiqueta es dato del administrador,
  no de la instalación); un modelo de datos de «grupos de modelos» (lo que hay alcanza).

## Resolución del QA

Resolución de `qa-plan.md` (`3537847`, QA crítico del plan, tercera pasada) por `speckit-clarify` (5 preguntas
al coordinador, Session 2026-10-06 «QA del plan», más una precisión en el re-análisis), `speckit-plan` y
`speckit-tasks`, el 2026-10-06. Las referencias `archivo:línea` son de este directorio
(`specs/057-porte-sentinel-068-redireccion-modelos/`) en el commit de esta resolución. Ningún hallazgo reabre
P1–P5, D1–D4, D1/D2/D5/D12 legales ni la enmienda del 403.

| Hallazgo | Severidad | Resolución | Dónde (archivo:línea) |
|---|---|---|---|
| B1 — la extensión no llega a lo publicado ni al instalador; el backend publicado no arranca con la variable | Bloqueante | Variantes `-ext` derivadas, `Dockerfile.standalone` con `upgrade heads` condicional y arranque que aborta, opt-in `ELEA_REDIRECT=1`, prueba local antes del runbook con vuelta atrás; premisa de R6 corregida | spec.md:197 (Clarifications); spec.md:71 (Diagnóstico #5); spec.md:592 (FR-004d); research.md:146 (R6); research.md:513 (R27); plan.md:26 (T-H); plan.md:258 (riesgo); contracts/costuras-base.md:14 (S4); quickstart.md:36 (§1b); tasks.md:90 (T088); tasks.md:125 (T091); tasks.md:277 (T100); tasks.md:279 (T102); tasks.md:280 (T103) |
| B2 — `masked_all` solo como dato sembrado; sin seed o región, sale sin forzado; región cae a `eu` | Bloqueante | Respaldo en código forzado y fail-closed con alcance a `region_codes`, sin región ⇒ 403, ninguna fila lo quita; `tenant_region` sin `eu`; seeds al arrancar; compose con `latam_ar`; `/api/v1/redirect/health` | spec.md:803 (FR-031); research.md:558 (R28); data-model.md:66 (§1); data-model.md:103 (piso); contracts/admin-api.md:30; tasks.md:214 (T094); tasks.md:219 (T060); tasks.md:225 (T095) |
| B3 — el forzado no cubre `system`, turnos del asistente, herramientas ni adjuntos; «no analizable bloquea» sin tarea | Bloqueante | Costura S14: todo valor de texto salvo campos estructurales, PDF a texto con `pypdf`, no analizables ⇒ bloqueo, informe con `scope`/`unanalyzable`, guard que lo exige, `count_tokens` no se reenvía bajo forzado; cierra Sentinel T074 por HANDOFF | spec.md:741 (FR-027); spec.md:872 (FR-041); spec.md:1000 (SC-006); research.md:615 (R29); contracts/costuras-base.md:51 (§S14); tasks.md:151 (T034); tasks.md:210 (T056); tasks.md:215 (T096); tasks.md:220 (T061); tasks.md:226 (T097) |
| A2 — FR-016 sin prueba propia; T019 no corre todos los casos de R13 | Alto | Caso de `allowed_models` en T035; T019 corre todos los casos de R13 de Sentinel | research.md:797 (R32); tasks.md:113 (T019); tasks.md:152 (T035) |
| A3 — `rdx-*` y orden de guardrails solo en vivo | Alto | Test offline de `rdx-*` en todos los `call_type`, orden efectivo y metadata del cliente que no relaja; T020 verifica el orden | research.md:797 (R32); tasks.md:114 (T020); tasks.md:126 (T092) |
| A4 — sobre-enmascarado de Claude Desktop (Sentinel 069 T184) ausente | Alto | Registro de riesgos; T045/T083 miden falsos positivos con el forzado encendido; escalamiento si SC-004 no se alcanza; HANDOFF | plan.md:263 (riesgo); research.md:797 (R32); tasks.md:162 (T045); tasks.md:297 (T083); tasks.md:299 (T085) |
| A5 — `DISABLE_SCHEMA_UPDATE=true` presentada como respaldada | Alto | Hipótesis; fuera del override hasta que T019 la ensaye | research.md:111 (R5); plan.md:264 (riesgo); quickstart.md:13 (§0); tasks.md:113 (T019); tasks.md:115 (T021) |
| A6 — `REDIRECT_OPERATOR_TENANT` desarma FR-023 | Alto | Eleia no la define; regiones, `default_posture` y relajaciones por rol real; test con la variable definida | spec.md:714 (FR-023); research.md:717 (R30); data-model.md:127 (§1); contracts/admin-api.md:26; tasks.md:209 (T055); tasks.md:219 (T060) |
| A7 — el admin de empresa puede falsear la ficha de la que depende la relajación | Alto | Campos de residencia y retención de la ficha solo de cumplimiento y super-admin (403) | spec.md:714 (FR-023); research.md:717 (R30); data-model.md:235 (§4); contracts/admin-api.md:76; tasks.md:127 (T099) |
| A8 — una fila `off` del admin de empresa reemplaza el default | Alto | Postura efectiva en dos niveles, 422 `posture_less_strict` con orden total definido (entre modos y por inclusión), destino sin jurisdicción ⇒ 403 con cualquier fila | spec.md:714 (FR-023); spec.md:757 (FR-028); data-model.md:91 (§1); contracts/admin-api.md:21; tasks.md:218 (T098); tasks.md:219 (T060) |
| A9 — T045, T047 y T051 dependen de T-E aunque el plan los ordenaba antes o en paralelo | Alto | Orden A → B → C → E → {D ∥ F} → H → G; T045 con postura explícita de prueba y T083 con el default real | plan.md:232 (orden); quickstart.md:80 (§3); tasks.md:171 (T-D); tasks.md:162 (T045); tasks.md:314 (dependencias) |
| A10 — `/internal/model-credential` entrega credenciales descifradas con solo el secreto; el instalador publica el backend | Alto | Capa 1 en la 057 (404 sin ruta directa). Capas 2 (S15) y 3 (proxy) para **toda** instalación las entrega antes el arreglo de separación de bases (decisión del coordinador en el re-análisis): dependencia que T089 y T101 verifican; T081 lo documenta | spec.md:238 (Clarifications); spec.md:665 (FR-013); research.md:757 (R31); contracts/costuras-base.md:97 (§S15); tasks.md:91 (T089); tasks.md:124 (T090); tasks.md:278 (T101); tasks.md:295 (T081) |
| M1 — gate de T-A con Docker | Medio | Sin cambio: T015 ya 🐳 con aviso al owner | tasks.md:92 (T015) |
| M2 — «cuatro entradas `azure/*`» y `gpt-5.6-luna` sin evidencia | Medio | Tres conversables + embeddings; `gpt-5.6-luna` a confirmar con el owner, con alternativa | research.md:184 (R9); quickstart.md:65 (§2); tasks.md:117 (T023); tasks.md:162 (T045) |
| M3 — S13 y la decisión sellada del 08-sep | Medio | Referencia agregada; T067 prueba que no es estable entre conversaciones | research.md:346 (R18); tasks.md:246 (T067) |
| M4 — `masking_ok` exige `detected == masked` | Medio | Bajo forzado ningún tipo queda exento | research.md:615 (R29); tasks.md:210 (T056); tasks.md:226 (T097) |
| M5 — FR-005/006/012/013/016 con test solo heredado | Medio | T030 lista los heredados (incluidos retiro de oferta y Hub) y exige que no queden saltados | tasks.md:129 (T030) |
| M6 — absorbido por A8 | — | Ver A8 | — |
| M7 — CUIT/CUIL solo con guiones | Medio | Batería con formatos fijados; patrón sin guiones | tasks.md:210 (T056); tasks.md:226 (T097) |
| M8 — texto del bloqueo por enmascarado | Medio | Contratos alineados con las caras copiadas (400 cara Claude, 403 genérica) | contracts/cara-claude.md:72; contracts/cara-generica.md:23; contracts/costuras-base.md:92 |
| M9 — habilitación de entradas bloqueadas por el admin | Medio | Sin cambio (rol de la 068/069; habilitar no relaja la residencia); con A7 el admin no cambia la ficha | data-model.md:179 (§2); tasks.md:127 (T099) |
| M10 — `MASKING_NONCE_KEY` fuera de la lista negra; claves sin definir; release sin generarlas | Medio | Clave con separación de dominio y ancho fijo; `ENV_DENYLIST`, `gen_secrets.sh` y check; el instalador la genera | research.md:350 (R18); data-model.md:280 (§6); tasks.md:252 (T093); tasks.md:277 (T100) |
| M11 — S5b cambia el camino de `redact_enabled=false` | Medio | Test del guardrail en T008 y anotación para el HANDOFF | tasks.md:83 (T008); tasks.md:299 (T085) |
| M12 — gates sin Docker pueden pasar con tests saltados | Medio | `-rs` y 0 saltados entre los críticos | tasks.md:129 (T030); tasks.md:227 (T065); tasks.md:300 (T086) |
| M13 — DoD de docs incompleta | Medio | T079 suma overview, release-notes y compliance (o los declara fuera con motivo) | tasks.md:293 (T079) |
| M14 — estimador de tokens con red | Bajo | `cl100k_base` horneado en la `-ext` y respaldo `caracteres/4`, test offline | research.md:215 (R12); tasks.md:151 (T034); tasks.md:158 (T041); tasks.md:125 (T091) |
| M15 — citas de ids de Sentinel; versión de la enmienda | Bajo | Ids rotulados «de Sentinel» en spec, plan, data-model, contratos y tasks; aviso de divergencia en T001 | spec.md:562; plan.md:22; contracts/cara-claude.md:11; tasks.md:76 (T001); tasks.md:139 (T-C) |
| B-1 — `control_jurisdiction` `String(16)` vs `String(8)` | Bajo | Unificado a `String(8)` | data-model.md:231; research.md:480 (R25) |
| B-2 — cita de `gw_messages` aproximada | Bajo | Sin cambio: sin consecuencia | spec.md:67 |
| §6 — cobertura de escenarios (US3.3, US1.6, US3.7, US3.8, SC-004, SC-006, SC-010) | — | US3.3/SC-006 por B3; US1.6 por A3 y por G1 del re-análisis (política apagada); US3.7 por A6–A8; US3.8 por B2; SC-004 bajo la postura real (A9); SC-010 aclarado | tasks.md:215 (T096); tasks.md:126 (T092); tasks.md:112 (T018); tasks.md:218 (T098); tasks.md:214 (T094); tasks.md:297 (T083); tasks.md:161 (T044) |

### Re-análisis (`speckit-analyze`, solo lectura, 2026-10-06)

Primera corrida sobre esta resolución: 0 CRITICAL, 5 HIGH, 13 MEDIUM, 13 LOW. Se corrigieron así:

| Hallazgo del análisis | Severidad | Resolución | Dónde (archivo:línea) |
|---|---|---|---|
| C1 — FR-004d «idéntico sin la variable» vs. proxy del instalador | HIGH | Pregunta al coordinador: proxy y chequeo de origen para toda instalación, entregados por el arreglo de bases (dependencia); «idéntico» se mide contra la instalación ya corregida | spec.md:238; spec.md:592; research.md:785 (R31); tasks.md:277 (T100); tasks.md:278 (T101) |
| U1 — el respaldo en código no tenía piso frente a filas de cumplimiento | HIGH | Piso de forzado en todo destino bajo el respaldo, sin excepción de rol | data-model.md:103; tasks.md:214 (T094) |
| C2 — T098 rechazaba filas más estrictas; orden dentro del mismo modo indefinido | HIGH | Orden total definido (inclusión de jurisdicciones o de `home`); 422 solo si es menos estricta | data-model.md:109; tasks.md:218 (T098) |
| U2 — `count_tokens` reenviado bajo forzado | HIGH | Bajo forzado nunca se reenvía (estimado local o 404), también en suscripción | spec.md:872 (FR-041); research.md:666 (R29); contracts/cara-claude.md:38; tasks.md:151 (T034); tasks.md:158 (T041); tasks.md:221 (T062) |
| U3 — «todo lo que sale» sin regla para campos fuera de la lista | HIGH | Regla general fail-closed: todo valor de texto salvo una lista cerrada de campos estructurales | spec.md:742 (FR-027); research.md:635 (R29); contracts/costuras-base.md:61; tasks.md:215 (T096) |
| I1–I8, O1–O3, A1, G1 (medios) | MEDIUM | Ids de Sentinel rotulados; 400/403 por cara; alcance del respaldo = `region_codes`; borrado por SQL; quickstart marca qué vale antes de T-E; medición PDF en T097; S14 de docs en T080; imagen del motor «mismo digest base»; T050 escala si sale de `generic.py`; S1–S15; `conversation_ref` alineado; sufijo de 4 hex; FR-014 con política apagada en T018 | quickstart.md:50; tasks.md:50; tasks.md:184 (T050); tasks.md:294 (T080); tasks.md:226 (T097); tasks.md:112 (T018); data-model.md:287 |
| L1–L11 (bajos) | LOW | `masking_relaxation=region` decidible; `unanalyzable_kinds` en S14; 403 en la ficha; `code_fallback`; FR-006/012/030/050 en T030/T079; archivos de test en las filas de tramo; vocabulario horneado; textos de tramos y fases. L12 y D1 (orden de FR/SC y repetición de la regla sin jurisdicción en la spec) se dejan: reordenar la spec cambiaría ids y citas sin efecto en la implementación | data-model.md:273; data-model.md:270; plan.md:244; tasks.md:16 |

### Re-análisis, segunda corrida (`speckit-analyze`, solo lectura)

Sobre las correcciones de la primera corrida: 0 CRITICAL, 1 HIGH, 4 MEDIUM, 10 LOW; los 5 HIGH anteriores, resueltos. Se corrigieron así:

| Hallazgo del análisis | Severidad | Resolución | Dónde (archivo:línea) |
|---|---|---|---|
| U5 — una `allowlist` del admin quitaba el forzado que impone una fila de cumplimiento | HIGH | El forzado de la base se calcula antes de combinar con las filas del admin y se conserva | data-model.md:99; spec.md:719 (FR-023); research.md:731 (R30); tasks.md:218 (T098) |
| U4 — la regla U1 no estaba en FR-031 ni en R30 | MEDIUM | Agregada a FR-031 y R30 | spec.md:809 (FR-031); research.md:732 (R30) |
| I1 — T-H en el resumen del plan seguía diciendo «proxy» | MEDIUM | Reescrito como verificación de la dependencia | plan.md:26 |
| G1 — rutas de la extensión a través del proxy | MEDIUM | T101 exige `/api/v1/redirect/*`, `/api/v1/catalog/*` y la salud por el puerto publicado | tasks.md:278 (T101) |
| G2 — demora del alcance completo sin medir | MEDIUM | Medición informativa de un pedido típico de Claude Code de solo texto en T097, junto a SC-010 | tasks.md:226 (T097); research.md:705 (R29) |
| L1–L10 (bajos) | LOW | T097 en R29; fórmula del sufijo alineada; ids de Sentinel rotulados; `unanalyzable_kinds` en S5b; fila de forzado primero en `count_tokens`; línea suelta del plan; estado de la spec; archivo de perf en T-E; FR-006 → T030; precisión de C1 en el quickstart | research.md:340; contracts/cara-claude.md:39; spec.md:7; tasks.md:393; quickstart.md:25 |

### Re-análisis, tercera corrida (`speckit-analyze`, solo lectura)

Sobre las correcciones de la segunda: 0 CRITICAL, 1 HIGH, 4 MEDIUM, 7 LOW; U5 y los demás, resueltos (≈90 referencias `archivo:línea` de estas tablas verificadas por el análisis). Se corrigieron así:

| Hallazgo del análisis | Severidad | Resolución | Dónde (archivo:línea) |
|---|---|---|---|
| F1 — cambiar el default de región en `compose.prod.yml` afectaba a los perfiles de cliente europeos sin la extensión | HIGH | El default `latam_ar` solo en el compose de desarrollo de Eleia (el instalador ya lo usa); `compose.prod.yml` conserva `eu`; los perfiles que activen la extensión fijan la región | research.md:596 (R28); tasks.md:225 (T095); plan.md:198 |
| C1 — R23 conservaba la fórmula previa a U5 | MEDIUM | Fórmula alineada con data-model §1 | research.md:429 (R23) |
| C2 — T-H del plan aún listaba el proxy | MEDIUM | Quitado | plan.md:218 |
| C3 — T056 bloqueaba con `redact_enabled=false` bajo forzado | MEDIUM | Bajo forzado sale enmascarado; bloquea solo con analizador caído/degradado o no analizable | tasks.md:210 (T056) |
| A1 — `home` vacío en una fila vs. `masked_all` | MEDIUM | Se compara el `home` resuelto; ejemplo de T098 ajustado | data-model.md:114; tasks.md:218 (T098) |
| U1, U2, A2, G1, T1–T3 (bajos) | LOW | Paridad 068 entre filas de cumplimiento declarada; contrato de posturas con la regla U5; SC-010 sin el costo del análisis forzado; test de roles del panel en T063; T139 rotulado; M10 → T093 en el encabezado; comentario del plan | data-model.md:116; contracts/admin-api.md:21; spec.md:1011; tasks.md:222 (T063); tasks.md:31 |

### Re-análisis, cuarta corrida (`speckit-analyze`, solo lectura)

Sobre las correcciones de la tercera: **0 CRITICAL, 0 HIGH**, 2 MEDIUM, 5 LOW (F1 y los demás, resueltos; ≈120 referencias `archivo:línea` de estas tablas verificadas). Los siete se corrigieron igual, por ser baratos:

| Hallazgo del análisis | Severidad | Resolución | Dónde (archivo:línea) |
|---|---|---|---|
| M1 — el default `latam_ar` en el `docker-compose.yml` de la raíz cambiaba la región de la suite de CI | MEDIUM | El default va al override de desarrollo de la extensión; la raíz y `compose.prod.yml` no cambian | research.md:593 (R28); tasks.md:225 (T095); plan.md:243 |
| M2 — ¿una relajación quita el forzado del respaldo en código? | MEDIUM | No: bajo el respaldo ninguna relajación tiene efecto | data-model.md:215 (§3); data-model.md:105 (§1); tasks.md:214 (T094) |
| L1–L5 (bajos) | LOW | Riesgo con el origen correcto de «sin `eu`»; `plugin.py` de T-F después de T-E; test de roles del panel en la fila de T-E; contrato de la ficha alineado con FR-028; la cláusula sin marcador de T095 reemplazada por el respaldo fail-closed | plan.md:259; plan.md:244; contracts/admin-api.md:74 |

## Resolución del QA v2

Resolución de `qa-plan-v2.md` (segunda vuelta del QA crítico, sobre `6e2ad55`) por `speckit-plan` y `speckit-tasks`, el
2026-10-06, con el alcance que fijó el coordinador: N1, N4 y N8 con tarea y test; N2 como dependencia expresada en T089 y
T-H (la cubre la vuelta 2 del arreglo de bases); N3 solo como referencia (arreglo aparte en la base); los bajos, absorbidos.
Las referencias son de este directorio en el commit de esta resolución. Ninguna reabre una decisión del owner (D1, D2, D3,
D5, D10, D12, la enmienda del 403, P1–P5).

| Hallazgo | Severidad | Resolución | Dónde (archivo:línea) |
|---|---|---|---|
| N1 — «seeds al arrancar» sin enganche: S1 solo monta routers y la app usa `lifespan` | Medio | Costura nueva S16 (`run_plugin_startup()` desde el `_lifespan`, antes de servir); `on_startup()` de `sentinel.redirect.api`; tests contra `src.main:app` con su `lifespan` real. Confirmado por ensayo con FastAPI 0.111.0 (el `on_startup` de un router no corre bajo `lifespan`) | spec.md:244 (Clarifications, QA v2); spec.md:623 (C-1, S16); spec.md:810 (FR-031); research.md:583 (R28.4); research.md:820 (R33); contracts/costuras-base.md:25 (S16); plan.md:281 (complejidad); tasks.md:224 (T104); tasks.md:225 (T095); tasks.md:279 (T102) |
| N2 — la dependencia del canal interno era una promesa y frenaba T-A | Medio | Proxy y `INTERNAL_ALLOWED_CIDRS` los entrega la vuelta 2 del arreglo de bases (dato del coordinador); el gate pasa de T-A a T-H; `ELEA_REDIRECT=1` no se activa sin ellos; T102 verifica el 404 desde la LAN | research.md:787 (R31); plan.md:265 (riesgo); tasks.md:91 (T089); tasks.md:277 (T100); tasks.md:278 (T101); tasks.md:279 (T102); quickstart.md:25 (§1) |
| N3 — el admin de empresa puede crear un `compliance_officer` o un `super_admin` | Medio | Fuera de la 057: lo cierra un arreglo aparte en la base (otra tarea del plan del coordinador). Acá solo la referencia y la redacción honesta de la garantía | research.md:746 (R30); plan.md:262 (riesgo); tasks.md:209 (T055); tasks.md:294 (T080) |
| N4 — extracción de PDF síncrona en el motor, sin plazo ni tope de memoria ni de expansión | Medio | Proceso hijo por PDF con `RLIMIT_AS`, plazo con kill, semáforo, `pypdf.Configuration` con tope por flujo y corte de texto; fallo ⇒ no analizable; `pypdf` fijado (6.19.0 verificada) con hash; test de PDF hostil | research.md:678 (R29 3b); contracts/costuras-base.md:79 (S14); plan.md:131 (constitución); plan.md:261 (riesgo); tasks.md:216 (T105); tasks.md:226 (T097); tasks.md:125 (T091); tasks.md:227 (T065) |
| N5 — el default `eu` en tres sitios | Bajo | Un único `tenant_region()` para el tráfico, `list_postures` y `run_fidelity` | research.md:605 (R28.6); tasks.md:219 (T060); tasks.md:214 (T094) |
| N6 — T100 no enumeraba las variables que activan la extensión | Bajo | Lista completa de HANDOFF §2.1 en el test; el instalador falla ante cualquier no-200 de la salud (también 404) | tasks.md:277 (T100) |
| N7 — contexto de build de las `-ext` | Bajo | Contexto = raíz del repo, verificado por `test_ext_images.sh` | tasks.md:125 (T091) |
| N8 — S14: exención por nombre, claves y números (enmendada por R35 y R36 con el NER real) | Medio | Exenciones por posición del protocolo (tabla cerrada en el contrato, opacas/estructurales/libres); detección en posición estructural ⇒ `structural_entity` ⇒ bloqueo; claves y números analizados en subárboles libres; test de colisiones, claves, números, contrabando e instantánea de la tabla | research.md:639 (R29.2); contracts/costuras-base.md:66 (S14); tasks.md:217 (T106); tasks.md:226 (T097); tasks.md:215 (T096) |
| N9 — `compose.prod.yml` inyecta `eu`: el estado es `region_row_missing`, no `region_unresolved` | Bajo | Precisión en R28; T094 lo prueba; T080/T081 lo describen | research.md:600 (R28.5); tasks.md:214 (T094); tasks.md:294 (T080); tasks.md:295 (T081) |
| Observación — T045 mide antes de S14 | — | T045 aclara que su conteo no es la medida de A4 (lo es T083) | tasks.md:162 (T045) |
| §2b(1) — 403 de residencia con «Failed to authenticate» en Claude Desktop | — | Síntoma conocido en la guía de Desktop | tasks.md:293 (T079) |
| M2 — `gpt-5.6-luna` existe (dato del coordinador, no verificado por el QA) | — | Se siembra; la verificación de despliegue (T022) la deja `inactive` si no existe; la spec no lo nombra, sin `speckit-clarify` | research.md:184 (R9); tasks.md:117 (T023); tasks.md:162 (T045); quickstart.md:65 (§2) |

### Re-análisis QA v2 (`speckit-analyze`, solo lectura, 2026-10-06)

Sobre esta resolución: **0 CRITICAL, 0 HIGH**, 5 MEDIUM y 14 LOW (citas `archivo:línea` de esta tabla y de las anteriores verificadas
tras el corrimiento de líneas). Corregidos en el lugar: M1 (caso de origen de T089 en la fila T-H del plan), M3 (siembra concurrente con
varios workers: cerrojo consultivo y test de dos arranques simultáneos, R33 y T095), M4 (criterio determinista del gate en T100), M5 (tope
de PDF por pedido, plazo total y caché por hash: R29 3b, contrato S14, T097, T105), L1–L4, L6–L9, L11, L12 y L14. **Quedan, con motivo**:
M2 y L5 (el texto de la spec sobre «va antes que esta feature», la vuelta 2 y el alcance/estado): el coordinador acotó la enmienda de la
spec a la fila S16 de C-1 y la referencia en FR-031; la lectura «antes de activar (T-H)» queda en R31; si se quiere en la spec, va por
`speckit-clarify` con el coordinador. L10 (cita de la constitución) corregida a Principio I; L13 (T089 en dos partes bajo un solo id): se
deja, las dos partes y sus tramos están explícitos en la tarea.
