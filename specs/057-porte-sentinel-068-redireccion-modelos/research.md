# Research — 057 Porte de la redirección de modelos (Sentinel 068)

**Fecha**: 2026-10-06 · **Fuentes de solo lectura**: Sentinel `origin/main` `6a70855`, HANDOFF
`docs/handoff-068-elea` `8c525db`, spike `specs/ANALISIS-SEPARAR-BASES-MOTOR-2026-10.md` (rama
`cluna-8/spike-separar-bases-motor`). `sentinel:` = archivo de Sentinel en `6a70855`; sin prefijo =
este repo.

Formato: **Decisión** · **Por qué** · **Alternativas**. Las decisiones D1–D4 (R13–R16) tenían opciones
abiertas y se preguntaron al coordinador. **Respuesta del owner (2026-10-06)**: D2 = A, D3 = A, D4 = A;
D1 = mecanismo A (todo por datos), pero el **valor por defecto** que siembra Eleia queda **pendiente de
un análisis legal** (si en América, sobre todo en Sudamérica, se pueden usar modelos globales o chinos;
postura del owner: «por qué bloqueo, si América está permitido y no tiene GDPR»). Por la misma razón, el
default de postura para destinos fuera de región sin postura explícita pasa a ser **configurable**
(R23). El plan no se frena por esto.

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
     (`depends_on`), ni a la imagen ni a la versión del motor; (c) el plano motor de la extensión no
     lee la base: habla por HTTP interno (`sentinel:sentinel/engine/redirect_catalog.py:71-133`), y la
     ruta directa queda apagada (`CATALOG_DIRECT_ENABLED` vacío); (d) T016 lo verifica con un test
     offline sobre el `ScriptDirectory`; (e) las pruebas en vivo corren sobre la base existente de
     desarrollo (libro del motor presente) o con bases separadas, nunca con una base nueva y el backend
     primero; el override de desarrollo de la extensión agrega `DISABLE_SCHEMA_UPDATE=true` al motor
     (mitigación del spike §5) para que una prueba no dispare el diff.
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
    las variables de HANDOFF §2.1 desde un `.env` local ignorado. Cubre la T021 que Sentinel no hizo.
- **Por qué**: Sentinel reemplazó S9/S11 con su `deploy.sh` de nix (HANDOFF §1(a) «No hacen falta»),
  que Eleia no tiene; el instalador de Eleia consume `rendered/` (`render_profile.sh`) y los volúmenes.
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
    cargados con `python -m sentinel.catalog.seed` (idempotente). Destinos disponibles hoy:
    `gpt-5.6-luna` (no está en `litellm/config.yaml`: se carga solo en el catálogo), `gpt-5.1-chat`,
    `gpt-5.4-mini`, `gpt-4o-mini` (`litellm/config.yaml:35-74`). La jurisdicción de inferencia **no**
    se presume (spec §Assumptions): el seed la deja vacía y el quickstart obliga a cargarla.
- **Por qué**: el síntoma del 6-oct («Resource not found», HANDOFF §2.4) es un `real_model` que no
  coincide con un despliegue (HANDOFF §4.1).
- **Alternativas**: listar despliegues por la API de gestión de Azure (otra credencial y otro permiso);
  no verificar (deja el error opaco que FR-020 prohíbe).

## R10. T139: campos desconocidos hacia destinos traducidos

- **Decisión**: `normalize_for_translated` (`sentinel:sentinel/redirect/faces/claude.py:255`) pasa a
  trabajar con una **lista permitida** de campos de primer nivel de la Messages API (`model`,
  `messages`, `system`, `max_tokens`, `stop_sequences`, `stream`, `temperature`, `top_p`, `top_k`,
  `tools`, `tool_choice`, `metadata`); todo lo demás (p. ej. `safeguards`, Diagnóstico #20) se quita y
  sus **nombres** (nunca valores) quedan en `extensions.redirect.dropped_fields`. Hacia nativos no se
  filtra.
- **Por qué**: una lista negra (`safeguards`) se rompe con el próximo campo nuevo de Claude Code.
- **Alternativas**: lista negra; parche del cliente `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`
  (HANDOFF §2.4: no reemplaza a T139).

## R11. T094: cabeceras beta

- **Decisión**: hacia destinos **nativos**, `anthropic-beta` se reenvía filtrado por una lista
  permitida que es dato de la extensión (default acotado y editable por el super-admin); hacia
  traducidos, todas se descartan (`forward_headers_allowlist` de S2). El mismo `pre_request` rechaza
  con 401 una credencial de suscripción personal hacia un destino de otro proveedor con la política
  encendida (FR-042).
- **Por qué**: FR-040; el reenvío ciego de betas es lo que hoy rompe el 404 con `?beta=true`.
- **Alternativas**: reenviar todas a nativos (riesgo de betas que cambian facturación o retención).

## R12. T093: `count_tokens` hacia traducidos

- **Decisión**: respuesta temprana en `pre_request`: estimación local con `tiktoken` (`o200k_base`)
  sobre el cuerpo ya normalizado → `{"input_tokens": N}`; si el estimador no está disponible, 404
  `not_found_error` para que la herramienta estime sola (contrato 068 §count_tokens). Nativos: reenvío.
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
`sentinel:sentinel/catalog/models.py:118-123`; control en `sentinel:sentinel/redirect/resolver.py:156`).

- **Opción A (recomendada)**: regla **por datos**: una entrada nace `blocked_by_default` si su
  proveedor está en una lista, o el host de su `api_base` coincide con una lista sembrada y editable,
  o su jurisdicción de entidad o de inferencia está en una lista sembrada. Seed en
  `deploy/redirect-seeds/habilitacion-explicita.yaml`; la regla es genérica y vuelve por HANDOFF.
- **Opción B**: solo por proveedor (`deepseek` + `zai`): no cubre Qwen ni Kimi por `openai_compatible`.
- **Opción C**: solo por jurisdicción `CN` declarada: depende de que el administrador la cargue bien.
- **Recomendación**: A — cubre las tres vías de alta sin depender de un solo dato.
- **Estado**: **mecanismo A decidido** por el owner (2026-10-06): listas editables de proveedores, hosts
  de `api_base` y jurisdicciones, genéricas, con migración en la rama de la extensión (junto con R13).
  **El valor por defecto de Eleia queda PENDIENTE del análisis legal**: el código no presume bloqueo.
  - La regla de Sentinel (`provider == "deepseek"` fijo) se reemplaza por la lectura de las listas;
    para no cambiar el comportamiento de Sentinel, su seed de paridad es `providers: [deepseek]`.
  - Eleia siembra sus listas desde `deploy/redirect-seeds/habilitacion-explicita.yaml`, que se escribe
    **con la decisión del análisis legal** (tarea T028). Mientras el análisis no esté, el archivo
    queda con las tres listas **vacías** y un encabezado «pendiente del análisis legal»; con listas
    vacías ningún destino nace bloqueado y todo funciona (test obligatorio, T025).
  - Opciones que el análisis puede elegir para el seed de Eleia: (a) listas vacías (nada bloqueado por
    defecto); (b) solo proveedores (`deepseek`, `zai`); (c) proveedores + hosts de APIs oficiales
    chinas (`api.deepseek.com`, `dashscope*.aliyuncs.com`, `open.bigmodel.cn`, `api.moonshot.cn`,
    `api.moonshot.ai`, `api.minimax*`); (d) (c) + jurisdicción `CN`. Cualquiera es solo dato: no toca
    código.

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
  de la región («Admisible AMERICAS»).
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
  2. **Bloqueo por defecto** de la API oficial: mecanismo por datos (R14); el valor de Eleia es
     **pendiente del análisis legal**, y la variante con listas vacías tiene que andar.
  3. **Residencia**: con la postura explícita *fuera de región con enmascarado forzado*, un destino
     fuera de `AMERICAS` sale enmascarado y, con el analizador caído, se bloquea (FR-027). Sin postura
     explícita rige el **default configurable de postura fuera de región** (R23): de fábrica, rechazo
     (FR-031, spec US3 esc. 8); el valor de Eleia es **pendiente del análisis legal**.
  4. **Alojados en América**: los mismos modelos servidos por proveedores con inferencia y entidad en
     `AMERICAS` (Azure AI Foundry o AWS en EE. UU./Brasil, o OpenRouter con proveedores de EE. UU.) se
     usan sin enmascarado forzado (`evaluate` con `inside=True`,
     `sentinel:sentinel/redirect/residency.py:122-135`).
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
  descarta). Con él, `nonce = HMAC(MASKING_NONCE_KEY, tenant | llave | conversación)[:4]`, y el
  índice por valor sigue el esquema determinista de la 043 pero con esa clave del servidor. Sin
  identificador o sin clave, el comportamiento es el de hoy (aleatorio). Genérica para las dos líneas;
  vuelve por HANDOFF (Sentinel T131/T132).
- **Por qué**: la caché del proveedor exige el mismo historial enmascarado byte a byte (FR-045); la
  clave del servidor mantiene el sufijo impredecible y la llave en el HMAC impide compartirlo entre
  personas.
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
- **Alcance**: la enmienda **no** fija los valores pendientes del análisis legal (bloqueo por defecto de
  APIs chinas, R14; default de postura fuera de región, R23).
- **Por qué**: spec §Assumptions «Constitución»; el CRITICAL de `speckit-analyze` por el 503 del
  Principio II queda cerrado como «enmienda aprobada, pendiente de aplicar».

## R22. Docker y verificación en vivo

Todo lo que usa Docker se pide antes al owner con `ask` y se espera: suite del backend en contenedor,
`make -C deploy check`, `check-docs`, `docs-refs` (exporta `openapi.json` por contenedor,
`deploy/Makefile:45-49`), el spike D14 y las pruebas en vivo. Los tests de la extensión y del panel
corren sin Docker (venv del backend con `PYTHONPATH` y Vitest). Ids públicos de ejemplo: los que la
versión instalada de Claude Code / Desktop reconoce (Claude Code rechaza en el cliente ids que no
conoce, HANDOFF §2.4), por ejemplo `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-4-5`.

## R23. Default de postura para destinos fuera de región sin postura explícita (pendiente del análisis legal)

Pedido del owner (2026-10-06): la lectura «una API china habilitada sin postura explícita se rechaza
con 403» queda como **comportamiento configurable**, no fija.

- **Decisión (mecanismo)**: cada región del perfil (R13) lleva un dato `offregion_default` que
  `effective_posture` (`sentinel:sentinel/redirect/residency.py:90-120`) usa **solo** cuando el pedido
  es redirigido y no hay ninguna fila de postura para el alcance:

  | Valor | Qué pasa con un destino fuera de la región | Dentro de la región |
  |---|---|---|
  | `reject` (**default de fábrica**) | rechazo 403 «Modelo no disponible para tu región» (FR-031 y US3 esc. 8 tal como están escritos) | se sirve sin forzado |
  | `masked` | se sirve con enmascarado forzado y bloqueo si el analizador cae (equivale a `offregion_masked` implícito) | se sirve sin forzado |
  | `allow` | se sirve sin forzado (equivale a postura `off` para los redirigidos) | se sirve sin forzado |

  Una postura explícita de cumplimiento siempre gana sobre este default; el tráfico **no** redirigido
  sigue en `off` sin postura (FR-007). Cambiar el dato queda en el registro de configuración (FR-008) y
  solo pueden hacerlo cumplimiento o el super-admin (FR-023).
- **Valor para Eleia**: **pendiente del análisis legal** (tarea T064 lo siembra desde
  `deploy/redirect-seeds/regions.americas.yaml` con lo que decida el análisis). Hasta entonces la región
  `AMERICAS` se siembra con el default de fábrica `reject`, que es lo que dicen la spec y Sentinel.
- **Nota de alcance**: si el análisis elige `masked` o `allow` como valor de Eleia, el texto de FR-031 y
  del escenario 8 de US3 describe solo el default de fábrica; el coordinador decide si hace falta una
  enmienda de la spec (no se reabre en este plan).
- **Por qué**: la base legal de las transferencias la cubre el cliente fuera del sistema (spec
  §Assumptions); el sistema solo tiene que poder expresar la decisión como dato.
- **Alternativas**: dejar el rechazo fijo (lo que pide cambiar el owner); default por empresa en vez de
  por región (posible a futuro con la misma columna en el nivel empresa de la tabla de regiones).
