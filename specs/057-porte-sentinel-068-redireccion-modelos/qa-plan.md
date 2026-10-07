# QA crítico del plan — 057 porte de la redirección de modelos (Sentinel 068)

**Rol**: qa-critico (segundo nivel; seguridad, datos sensibles, permisos). **Fecha**: 2026-10-06.
**Rama**: `cluna-8/057-plan-legal`. **Solo lectura** salvo este reporte. Sin Docker, sin subagentes.
**Alcance leído**: `spec.md` completa, `plan.md`, `tasks.md`, `research.md`, `data-model.md`, `contracts/*`, `quickstart.md`,
constitución 2.2.0, HANDOFF de Sentinel (`docs/handoff-068-elea`, 572 líneas), spike de bases (`cluna-8/spike-separar-bases-motor`, incl. §8),
código de Eleia, el repo del instalador (`elea-installer@9754f13`, solo lectura) y el paquete `sentinel/` de Sentinel `6a70855`
(`git archive` a un directorio temporal).

> **Cobertura**: la primera pasada se cortó por límite de uso; la segunda agregó RBAC, escenarios y citas; **esta tercera pasada (reintento)**
> re-verificó B1 y B2 contra el código y encontró B3 y los altos A8–A10 (§1–§2), corrigió el mecanismo de A2 y completó el contraste
> escenario por escenario de US1–US5, Edge Cases y SC (§6, ahora con tabla). **Límite**: todo es lectura; nada se ejecutó (ni Docker ni suites).
> Lo que se afirma «por lectura» y debe confirmarse con un test está marcado **[por lectura]**.

## Veredicto

**Hay 3 bloqueantes** (B1, B2, B3) y 9 hallazgos altos (A2–A10). Ninguno reabre una decisión del owner (D1, D2, D3, D5, D10, D12 ni la enmienda
del 403): son huecos de entrega (B1), de fail-safe del default que el owner decidió (`masked_all`, B2) y de alcance real del enmascarado
forzado que la spec ya promete (B3). A6, A7, A8 y A10 tocan FR-023/FR-013 y deben corregirse antes de integrar T-E. Se recomienda corregir por
`speckit-plan`/`speckit-tasks` (no a mano) antes de despachar T-A (B1) y antes de despachar T-E (B2, B3, A8, A9).
**worker_done: failed** (hay bloqueantes).

---

## 1. Bloqueantes

### B1 — Lo que Eleia publica y el instalador instala no recibe la extensión, y con la variable activa el backend publicado no arranca
- **Evidencia (verificada de nuevo)**: `backend/Dockerfile.standalone:35` ejecuta `alembic upgrade head && uvicorn…`; es la imagen que publica
  `deploy/release/publish-elea.sh:25` (`[backend]=backend/Dockerfile.standalone`) y que consume el instalador (`elea-installer/docker-compose.yml:88`,
  `:48` motor, `:131` panel: **solo imágenes** `ghcr.io/cluna-8/elea-guardian-*:latest`, sin `render_profile.sh`, sin `rendered/`, sin `EXTRA_ENV_FILE`).
  Ni la spec (Diagnóstico #5, `spec.md:71`) ni T004 (`tasks.md:56`) la listan, y `1021c8e` no la toca (solo `backend/Dockerfile`, `entrypoint/backend.sh`,
  `main.py`, `env.py`; Sentinel ni tiene ese archivo).
- **Premisa falsa en el plan**: `research.md:138` afirma «el instalador de Eleia consume `rendered/` (`render_profile.sh`) y los volúmenes». No es así:
  `render_profile.sh`/`populate_volumes.sh`/`bundle.sh` son el camino de los **perfiles de cliente** (`deploy/clients/*`, terraform, bundle air-gapped;
  `deploy/clients/itv-examen/README.md:40`, `deploy/terraform/README.md:15`, `bundle.sh:57`). Eleia en producción es el instalador con imágenes: el motor
  hornea `config.yaml` y `extensions/` (`litellm/Dockerfile:7-8`), el backend hornea `backend/` y `litellm/extensions/` (`Dockerfile.standalone:22-23`) y
  ninguna lleva `sentinel/`, `redirect_*.py`, el fragmento fusionado ni las páginas del panel. T020 (S9/S11) solo sirve al camino de perfiles.
- **Falla**: (1) con `ALEMBIC_EXTRA_VERSION_LOCATIONS` definida hay dos cabezas; `alembic upgrade head` falla («multiple heads») y el `&&` del CMD impide
  levantar uvicorn → crash-loop en la imagen del instalador. (2) `backend/src/main.py:34-43` traga el error de migración (`logger.error(...)` sin abortar):
  un fallo de `upgrade heads` en el arranque queda silencioso. (3) Sin tarea que haga llegar el paquete, el motor y el panel a las imágenes publicadas, T081
  documenta «activación» de algo que el release no puede entregar; el plan no menciona `cluna-8/elea-installer` ni una vez (`grep instalador` en los
  artefactos: solo `research.md:138`, la premisa falsa).
- **Viola**: FR-004b, FR-004c, Constitución VII (config + seed), AGENTS.md («features que tocan el instalador se coordinan en el mismo plan»).
- **Corrección**: tarea en T-A/T-B que (a) agregue la rama `heads` condicional a `Dockerfile.standalone` con test de contrato, (b) haga fallar el arranque
  (no tragar) cuando la variable está definida y la migración falla, (c) decida y planifique la entrega de paquete/motor/panel a las imágenes publicadas
  y al instalador (o declare en spec y docs que el MVP es solo desarrollo y perfiles de cliente), y (d) corrija `research.md:138` por `speckit-plan`.

### B2 — La postura por defecto `masked_all` solo existe como dato sembrado; sin seed o sin región resuelta, el redirigido sale sin enmascarar
- **Evidencia (verificada de nuevo)**: `data-model.md` §1 (sin fila: «respaldo fijo de `region_codes`», de fábrica `reject_offregion`); Sentinel
  `sentinel/redirect/residency.py:90-98` (sin filas ⇒ `allowlist` con `home_default`, sin forzado) y `:37-48` (`region_codes('latam_ar')={LATAM,AR}`,
  `'eu'→{EU}`). La región la lee `tenant_region` (`sentinel:sentinel/redirect/plugin.py:134-137`) de la identidad o de `SENTINEL_ENTITY_REGION` con default
  **`"eu"`**; ambos compose lo defaultean a `eu` (`docker-compose.yml:101,217`; `deploy/docker/compose.prod.yml:112,201`) y solo `.env.example:194` lo pone en
  `latam_ar`. El seed lo carga a mano `python -m sentinel.redirect.regions_seed` (T064, `tasks.md:184`; `quickstart.md:33`): ninguna tarea lo enchufa al despliegue.
- **Falla**: instalación sin el seed, con la fila borrada, o con la variable en su default ⇒ el redirigido a destinos en `{LATAM,AR}` (o `{EU}`) sale
  **sin enmascarado forzado**, contradiciendo D2 («todo el redirigido sale enmascarado»). Ningún test (T053/T057/T064) cubre «sin fila de región». No es fuga
  hacia fuera de región (el resto se rechaza con 403), pero rompe FR-027/FR-031/SC-006 en el default y es fail-open respecto del valor decidido.
- **Viola**: FR-031, FR-027, Constitución I (masking-first).
- **Corrección**: test «instalación Eleia sin fila de región / con `SENTINEL_ENTITY_REGION` por defecto» y decidir el comportamiento seguro (p. ej. el
  respaldo de Eleia es `masked_all`, o chequeo de arranque/`/health` que falle o avise si la política está encendida sin región resuelta); cargar el seed desde
  el camino de despliegue; documentar `SENTINEL_ENTITY_REGION=latam_ar` como obligatoria en el env de la extensión. No cambia el valor decidido por el owner.

### B3 — El «enmascarado forzado» no cubre lo que FR-027/FR-016a/SC-006 prometen, y «lo no analizable bloquea» no tiene implementación en ninguna tarea
- **Evidencia (nueva)**: el guardrail enmascara y cuenta solo texto de turnos `user`: `litellm/extensions/sentinel_guardian_policy.py:880-892` (`mask_body`:
  `role != "user"` ⇒ `continue`; docstring `:882-883` «no el system prompt/tools»), `:874-893` (`_mask_content`: solo bloques `text` y `tool_result` de texto),
  `:734-749` (`extract_inspect_text`: «mismo alcance que el masking»). El informe de S5b (`1a454ed`) cuenta ese mismo alcance (`detected`/`masked`), y el guard
  solo compara contadores (`sentinel:sentinel/engine/redirect_guard.py:118-125`, `:328-330`). Sentinel **no hizo** el bloqueo de no analizables: `068/tasks.md:134`
  (T074 «Postura + verificación de enmascarado + bloqueo de no analizables», `[ ]`) y `:127` (T070, `[ ]`). La 057 dice lo contrario: T061 (`tasks.md:181`)
  «ya bloquea con 403 `masking_required`», T056 (`tasks.md:176`) exige «contenido no analizable ⇒ bloqueo», y la tabla de propiedad de T-E
  (`plan.md:212`) ni siquiera incluye `litellm/extensions/*` (de T-A/T-F).
- **Falla** [por lectura; confirmar con test multi-turno]: bajo `masked_all`, (1) un bloque `image`/`document` (PDF) hacia un destino con visión se reenvía
  sin analizar: informe `completed=True, detected=masked=0` ⇒ `masking_ok` verdadero ⇒ sale con datos personales; (2) en el 2.º turno, el cliente reenvía el
  historial con el texto del **asistente ya restaurado** (la respuesta vuelve des-enmascarada), y los turnos `assistant` (incluidos `tool_use`) no se enmascaran;
  (3) `system` y `tools` salen tal cual (en Claude Code el `system` trae rutas del usuario y entorno). `detected == masked` no puede detectar lo que nadie mira.
- **Viola**: FR-027 («cubre texto, resultados de herramientas y adjuntos; lo no analizable bloquea», `spec.md:635-637`), SC-006 («100 %», `spec.md:868-872`),
  US3 esc. 3 y 5, 068 FR-016a. **No reabre D2**: es implementar lo que la spec ya exige (o corregir su texto con honestidad).
- **Corrección**: por `speckit-plan`/`speckit-tasks`: tarea (con dueño de archivos explícito) que (a) trate como no analizable todo bloque no-texto hacia un
  destino con forzado y bloquee, (b) decida el alcance de `assistant`/`system`/`tools` (enmascarar o declarar el límite en FR-027 y en la doc, 🟡), y (c) test
  multi-turno con respuesta restaurada y re-enviada, con PDF/imagen y con `system` con DNI/CUIT/CBU. Si el owner prefiere declarar el límite en vez de cerrarlo,
  FR-027/SC-006 y T056 deben reescribirse; hoy prometen más de lo que el código garantiza.

---

## 2. Altos

- **A2 — FR-016 (lista de modelos de la llave) se hace cumplir solo en la pasarela, y el plan no lo prueba (mecanismo corregido)**: la pasada anterior decía que el
  motor validaría el id reescrito `rdx-*` contra `models=allowed_models` (`litellm/extensions/custom_auth.py:478`; `ai_engine_client.py:159`). El spike de Sentinel
  indica lo contrario para 1.92.0: con auth propia el motor **no aplica** la lista, aun con `custom_auth_run_common_checks: true`
  (`068/research.md:529`, caso (c); `spike053/config.yaml:22`) ⇒ S10 descartada. Entonces la única barrera es `sentinel:sentinel/redirect/plugin.py:354-357`
  (`allowed and ctx.model not in allowed`; con lista vacía no restringe) y el motor de Eleia es `main-latest@sha256` sin versión confirmada
  (`litellm/Dockerfile:6`; spec 053 dice 1.95.1). Faltan: un test propio (llave con `allowed_models`: id público permitido ⇒ sirve, no permitido ⇒ rechaza,
  vacía ⇒ sirve) —T035 nombra FR-016 sin caso concreto— y que T019 (`tasks.md:87`) corra **todos** los casos de R13 de Sentinel, no el subconjunto que lista
  (el caso (c), el rechazo del cuerpo con `api_base` y la expansión del comodín en `/v1/models` del motor, `068/research.md:529-531`).
- **A3 — Defaults del motor para `rdx-*` y credenciales de entorno**: el fragmento declara `rdx-azure/*` etc. sin credencial; el motor de Eleia tiene
  `AZURE_API_KEY` en el entorno (`litellm/config.yaml:35-74`). Todo depende de que `redirect-guard` rechace sin autorización (`sentinel/engine/redirect_guard.py:307-326`
  y `should_run_guardrail` `:397-403`). Es sólido en el código copiado, pero T019 solo corre en vivo con Docker; falta un test offline de «`rdx-*` sin autorización
  ⇒ 403 también en `call_type` no textuales» y de **orden de guardrails** en el `config.yaml` fusionado (el guard debe ir después de `sentinel-guardian`,
  `litellm/config.yaml:12`; T020 prueba «al final», no el orden efectivo ni la presencia del `masking_report`). Agregar: pedido con `metadata.masking_report`,
  `guardrails` o `disable_global_guardrails` sembrados por el cliente no relaja el forzado (el guard solo lee el home que escribe el guardrail, `:167-171`).
- **A4 — Sobre-enmascarado de Claude Desktop (069 T184 de Sentinel, HANDOFF §3 última fila)** no aparece en ningún artefacto de la 057 (`grep T184` = 0). T184 sigue
  abierta (`069-…/tasks.md:379`, «sin implementar»): 17 PERSON/14 LOCATION/3 PASSPORT falsos por pedido por NER español sobre instrucciones en inglés. Con `masked_all`
  **todo** el tráfico redirigido pasa por el enmascarado, así que pone en riesgo SC-004 (≥95 % sin errores), SC-011 (≥60 % de caché) y el valor de la protección.
  Además la Constitución I admite apagar el enmascarado en «herramientas de código donde el enmascarado rompe el código» (`constitution.md:36-41`) y Claude Code es
  exactamente ese caso: T045/T083 deben medir con el forzado encendido. Debe entrar al registro de riesgos del plan y al HANDOFF de vuelta.
- **A5 — Mitigación `DISABLE_SCHEMA_UPDATE=true` presentada como respaldada**: `research.md:108-111`, T021 (`tasks.md:89`) y `quickstart.md:14` la citan como «mitigación
  del spike §5», pero el spike dice que **no se ensayó** (`ANALISIS-SEPARAR-BASES-MOTOR` §7 ítem 8; §8.10 «sigue sin respaldo experimental»). Con ese flag, además, un motor
  sobre base nueva no crea sus tablas. Reformular como hipótesis y agregar su ensayo a T019/T045. Las demás mitigaciones de R5 son coherentes (FKs solo a `tenants`/`groups`;
  sin cambio de imagen). El instalador usa `:latest` del motor (spike §1.4) y comparte base con el backend (`elea_gateway`): las tablas `sentinel_redirect_*`/`ext_*` y
  `alembic_version` quedan expuestas al baseline destructivo igual que las del backend (H4: el borrado es silencioso para `/health`).
- **A6 — `REDIRECT_OPERATOR_TENANT` desarma la separación de FR-023**: `sentinel:sentinel/redirect/api/admin.py:83-100` declara «autoridad de instalación» (`_is_super`) al
  `tenant_admin` del tenant operador cuando esa variable está definida, y `_manages_postures` (`:99-100`) le da el mismo poder que a cumplimiento. HANDOFF §2.1 la lista para
  instalaciones de un solo tenant —el caso de Eleia— y T021/`extensions.env.example` toman «las variables de HANDOFF §2.1». Ningún artefacto de la 057 la menciona (`grep` = 0).
  Si se define, el administrador de la empresa puede cambiar `default_posture`, crear relajaciones (FR-031a) y cargar credenciales `env:` de instalación, contra FR-023 y
  US3 esc. 7. Decidir explícitamente (no definirla en Eleia, que sí tiene `super_admin`: `backend/src/models/user.py:9`; o limitar las relajaciones a `super_admin`/`compliance_officer`
  reales) y agregar un test de rol con la variable definida a T055.
- **A7 — El administrador de empresa puede falsear los datos de los que depende la relajación**: `sentinel:sentinel/catalog/api/admin.py:41,668-672`
  (`SHEET_WRITERS = ("admin","compliance_officer")`, `PUT /entries/{id}/sheet`). La ficha fija `inference/entity/control_jurisdiction` y `zero_data_retention`, que deciden
  `in_region` (FR-028a) y las precondiciones de la relajación por destino (`data-model.md` §3). `tenant_admin` no puede relajar, pero sí cargar «control = US, retención cero» y, con una
  relajación por región ya hecha por cumplimiento, dejar un destino sin enmascarar; en `quickstart.md` §2.3 la carga la hace «en Modelos» un administrador. Ni `contracts/admin-api.md`
  (§Ficha) ni T087 restringen el rol de escritura de estos campos. Propuesta: campos de residencia/retención editables solo por cumplimiento o super-admin, con registro (FR-008),
  o que un cambio que mejora la clasificación exija confirmación de cumplimiento; test en T087.
- **A8 — «Agregar filas nunca relaja» es falso frente al default: una fila `off` del administrador de empresa reemplaza el default (nuevo; absorbe M6)**:
  `sentinel:sentinel/redirect/api/admin.py:583-598` deja a `require_role("admin","compliance_officer")` crear una fila de **cualquier** modo (`_check_posture:557-563` solo valida
  el nombre del modo), y `residency.py:99-119` calcula la postura efectiva solo entre las **filas** (`off < offregion_masked < allowlist`); el default solo rige sin filas. Una fila
  `off` única ⇒ `Posture(mode="off")` ⇒ `evaluate` permite sin forzado (`:125-126`). El docstring `:585-586` («agregar nunca relaja») vale entre filas, no frente al default.
  El «piso» de la 057 (`data-model.md:83-88`, R23) solo conserva el **enmascarado** cuando el default es `masked_*`; no conserva (a) la restricción de alcance de `reject_offregion`
  ni (b) el rechazo de destinos sin jurisdicción de inferencia, que `data-model.md:75` ubica solo en «sin filas». Falla: con `default_posture` de cumplimiento en `reject_offregion`
  (valor válido, R23), un `tenant_admin` crea `{scope: tenant, mode: "off"}` y alcanza destinos fuera de región sin enmascarar; con `masked_all`, el mismo `off` hace alcanzable un destino
  sin jurisdicción (queda enmascarado por el piso, pero FR-031 y FR-031a dicen que ninguna fila ni relajación lo habilita). **Viola** FR-023, FR-031, FR-031a, US3 esc. 7 y el Edge Case del administrador.
  T055 (`tasks.md:175`) prueba solo `allowlist` bajo `masked_all`. **Corrección**: que T060 trate el default completo (alcance + rechazo sin jurisdicción + piso de enmascarado) como piso
  (`efectiva = más restrictiva(filas ∪ default)`), o que la API rechace con 422 filas menos estrictas que el default a quien no sea cumplimiento/super-admin; tests con filas `off` y
  `offregion_masked` del `tenant_admin` bajo cada valor de `default_posture`, y destino sin jurisdicción con fila `off` ⇒ 403.
- **A9 — Secuencia: T045 (T-C) y T047/T051 (T-D) dependen de T-E aunque el plan los ordena antes o en paralelo (nuevo)**: T045 (`tasks.md:130`) hace la prueba en vivo de la cara Claude con
  Azure sobre `quickstart.md` §1–§4, y `quickstart.md:61` dice «no hace falta postura; rige la postura por defecto (enmascarado forzado en todo destino)». Ese default no existe hasta
  T060/T064 (T-E, `tasks.md:180,184`): hasta entonces `effective_posture` devuelve `allowlist{LATAM,AR}` (`residency.py:95-98`) y un destino de Azure con inferencia en EE. UU. o sin jurisdicción da 403
  (HANDOFF §4.2; §2.2 paso 4 usa una postura explícita). SC-004/SC-009 se medirían bajo una postura que no es la que se entrega. Además `plan.md:203-204` y `tasks.md:247,274` declaran
  «T-D ∥ T-E», pero T047 (`tasks.md:148`) exige `masking_required` y `region_not_allowed` por postura por defecto, y T051 usa Azure: ambos requieren T060/T061. **Corrección**: T045 con una postura
  explícita de prueba (y repetirla tras T-E con el default real), o mover la prueba en vivo después de T-E; T047/T051 dependen de T-E en `tasks.md`/`plan.md`.
- **A10 — `/api/v1/internal/model-credential` entrega credenciales descifradas con solo el secreto compartido y no depende de `CATALOG_DIRECT_ENABLED` (nuevo)**:
  `sentinel:sentinel/catalog/api/internal.py:149-163` devuelve `cr.resolve(...)` (secreto descifrado) para cualquier `tenant` + `entry_id`, protegido solo por `_require_internal_secret`
  (`backend/src/api/internal.py:120-127`, el secreto = `SENTINEL_ENGINE_MASTER_KEY`); `direct_enabled()` (`internal.py:97-101`) solo cambia un flag de `/model-catalog`, no la disponibilidad de la ruta.
  Se monta con `PLUGIN_PACKAGES=sentinel.catalog.api` (HANDOFF §2.1; `quickstart.md:21`). El ingress niega `/api/v1/internal/*` (`deploy/docker/Caddyfile.ingress:20`), pero **el instalador no tiene
  ingress y publica `8091:8000`** (`elea-installer/docker-compose.yml:92`; spike §2.2(b): «la protección es solo el secreto»). Antes de la 057 esa llave no abría en el backend ningún secreto de proveedor de modelos; ahora abre los de todas
  las empresas. **Viola** el espíritu de FR-013 («no en claro en respuestas de API») y FR-014. **Corrección** (genérica y retrocompatible, vuelve por HANDOFF): la ruta
  responde 404 salvo `direct_enabled()` (Eleia lo deja vacío), test que lo fije, y T081 documenta que `/api/v1/internal/*` no se publica fuera de la red de compose.

## 3. Medios y bajos

- **M1 — T-A usa Docker en su gate** (T015, 🐳): correcto y marcado; recordar que `make -C deploy docs-refs` regenera `openapi.json` y debe correrse con aviso al owner.
- **M2 — «Cuatro entradas azure/*» (`spec.md:79`, `litellm/config.yaml:35-74`)**: son 3 modelos conversables + `router-embeddings` (`text-embedding-3-large`, no conversable).
  `gpt-5.6-luna` (T023, `research.md:168`, «disponibles hoy») **no existe** en el repo de Eleia (`grep` = solo la 057) ni hay evidencia de despliegue en el recurso de Azure; el quickstart lo
  usa como destino de opus. Marcarlo «a confirmar con el owner».
- **M3 — S13 y la decisión sellada del 08-sep** (comentario en `litellm/extensions/sentinel_guardian_policy.py:759-773`: un seudónimo estable entre documentos «sería una enmienda constitucional
  aparte, C1»). S13 es por conversación y con clave del servidor y la llave en el HMAC, así que es compatible, pero ni `research.md` R18 ni la enmienda de T001 lo citan; agregar la referencia y
  un test de «no estable entre conversaciones».
- **M4 — `masking_ok` exige `detected == masked`** (`redirect_guard.py:118-125`): un tipo de entidad configurado como no enmascarable por el tenant (`resolve_entity_action`) haría que `masked_all`
  bloquee todo pedido que lo contenga. Verificar la semántica de `detected` (S5b: `detected = len(preview_entities)`, `1a454ed`) y cubrirlo en T056.
- **M5 — FR-005/FR-006/FR-013/FR-016 con test solo heredado**: sin tarea de test propia (resolución por empresa/grupo/usuario/conexión, el chat de la consola intacto, credenciales no visibles en
  API/logs, permisos por alcance). Aceptable por ser copia, pero T030 debería listar los archivos de test heredados que los cubren y exigir que no queden saltados.
- **M6 — (absorbido por A8)**.
- **M7 — SC-006 y los patrones del perfil**: `litellm/extensions/sentinel_guardian_policy.py:143` detecta CUIL/CUIT solo con guiones (`\b\d{2}-\d{8}-\d\b`); un CUIT de 11 dígitos corridos no se
  enmascara. La batería de T056 debe fijar los formatos válidos y T080 documentarlos; si no, «100 % de los identificadores del perfil» (SC-006) no es medible. Con `SENTINEL_ENTITY_REGION`
  en su default `eu` (B2) estos patrones ni se aplican.
- **M8 — Texto del bloqueo por enmascarado**: el contrato (`contracts/cara-claude.md` §7, `cara-generica.md`) fija «El pedido no pudo protegerse para este destino y fue bloqueado.», pero
  `sentinel:sentinel/redirect/faces/generic.py:40-42` agrega «Probá en una conversación nueva.». Alinear contrato y test T047.
- **M9 — Habilitación de entradas bloqueadas**: `enable_entry` (`sentinel:sentinel/catalog/api/admin.py:606-609`) deja habilitar a `admin`; con reglas vacías (D1) es moot, pero si cumplimiento
  carga reglas `jurisdiction`, el administrador de empresa puede deshabilitar el bloqueo con motivo. Confirmar que es lo deseado.
- **M10 — Secretos nuevos sin cobertura (nuevo)**: (a) `MASKING_NONCE_KEY` (T072, `tasks.md:209`) no está en `ENV_DENYLIST`/`ENV_DENY_FRAGMENTS`
  (`sentinel:sentinel/engine/redirect_credentials.py:81-84`: `MASTER_KEY`, `PASSWORD`, `DATABASE`, `FERNET`, `JWT`, `POSTGRES`, `INTERNAL_KEY`) y el motor la recibe en su entorno: una credencial `env:`
  de instalación (`allow_any_env`, `catalog/credentials.py:56-68`) podría leerla y mandarla a una `api_base` elegida; agregarla a la lista negra con test. (b) Ningún artefacto dice **qué clave
  del servidor** deriva `sentinel_conversation_ref` y el identificador de afinidad (T068 `tasks.md:205`, T073 `tasks.md:210`, FR-043); definirla (¿`MASKING_NONCE_KEY` u otra?). (c) Nadie genera ni valida
  `REDIRECT_INTERNAL_KEY` ni `MASKING_NONCE_KEY` en el camino de release (`deploy/release/gen_secrets.sh`, `checks/test_no_default_secrets.sh`): sin la primera el guard responde 503 `authz_key_missing`
  (seguro, pero la política encendida no sirve nada); sin la segunda el nonce vuelve a aleatorio (seguro, sin caché).
- **M11 — S5b cambia el camino de `redact_enabled=false` para todo el tráfico (nuevo)**: `1a454ed` hace que, con redact desactivado, el guardrail llame igual al analizador (`reporte["detected"] = len(await _analyze(...))`)
  y devuelva (`git show 1a454ed -w`, bloque `if not identity.get("redact_enabled", True)`): hoy ese camino no llama a Presidio. Es «sin extensión» pero **no** «idéntico» (FR-001/SC-001): latencia y carga
  del analizador para tenants con redact apagado. T003/T018 usan motor falso y no lo ven. Agregar un test del guardrail (sin cambio de filas de auditoría ni de respuesta; analizador caído ⇒ no bloquea) a T008 y
  documentarlo en el HANDOFF.
- **M12 — Gates «sin Docker» pueden pasar en verde con tests saltados (nuevo)**: la RLS de las tablas nuevas se verifica por texto del SQL emitido
  (`sentinel/tests/integration/test_redirect_migrations_offline.py:91-107`), y esos tests hacen `importorskip("alembic")` (`:26`) y se saltean sin el venv del backend (docstring `:7-8`); el aislamiento real (FR-051, T025, T052)
  exige Postgres. T030 y T065 deben exigir «0 tests saltados» en los marcados como críticos y declarar que FR-051 solo queda 🟢 con la suite 🐳.
- **M13 — Definition of Done de docs incompleta (nuevo)**: T079–T081 no incluyen `docs/docs/compliance/index.md` (`:159` «Forzar región EU … Bloquea llamadas a modelos fuera de la UE», `:62-63` GDPR/AI Act),
  `docs/docs/overview/index.md` ni `docs/docs/release-notes/index.md`, que la feature afecta (AGENTS.md DoD, punto 1). Decidir cuáles se tocan y cuáles se declaran fuera.
- **M14 — Estimador de tokens con red (nuevo, bajo)**: T041 (`tasks.md:126`, R12) usa `tiktoken` `o200k_base`; el repo usa `cl100k_base` (`backend/src/services/token_counter.py:17`) y tiktoken descarga el
  vocabulario en el primer uso. En un servidor sin salida, el intento puede demorar `pre_request` antes de caer al 404. Hornear el vocabulario (`TIKTOKEN_CACHE_DIR`) o fijar el fallback a `chars/4`; test offline.
- **M15 — Citas de IDs de Sentinel (nuevo, bajo)**: T139 existe solo en la rama del HANDOFF (`docs/handoff-068-elea:specs/068-…/tasks.md:170`), no en `6a70855`, aunque la spec fija `6a70855` como fuente;
  y `spec.md:489,516` citan «tasks T001–T007…» de la 068 con la misma forma que las T001–T087 propias: rotularlas «T… de Sentinel». La enmienda de T001 llevaría a Eleia a 2.3.0 mientras Sentinel ya tiene otra
  2.3.0 y 2.4.0 (`6a70855:.specify/memory/constitution.md:3,244`): numerar la versión con aviso de divergencia en el Sync Impact Report.
- **B-1 (bajo)** `control_jurisdiction String(16)` vs `entity_jurisdiction String(8)` (`sentinel/catalog/models.py:152`): unificar.
- **B-2 (bajo)** `spec.md:67`: `gw_messages` está en `gateway.py:1636` (decorador); la función arranca después. Cita aproximada, sin consecuencia.

## 4. Citas, hashes e IDs — verificación

**Eleia (archivo:línea citados en spec/plan/research/tasks/contracts)** — verificadas de nuevo contra el árbol actual (script sobre todos los `archivo:línea` de los artefactos):
`ci.yml:50`, `chat.py:1402`, `gateway.py:1636/1989/2014-2017/2031/2039/2047-2069/2053`, `main.py:38/105/113/120`, `audit.py:47`, `user.py:9`,
`audit_service.py:422`, `entrypoint/backend.sh:30`, `backend/Dockerfile:19`, `test_profile_renders.sh:26`, `bundle.sh:98-99/186-187`,
`populate_volumes.sh:45-46`, `render_profile.sh:29`, `litellm/config.yaml:12/19-25/35-74`, `litellm/Dockerfile:6`, `.env.example:194`, `deploy/Makefile:45-49`,
`sentinel_guardrail.py:20/626`, `sentinel_guardian_policy.py:141/154/510/776-784`, `199fe429762a…py:22-23` (cabeza única, `down_revision 7a6fee614cfd`; `010` existe, `010_multitenant_foundation.py:50`):
**correctas**. Observaciones: `frontend/package.json:19` apunta a la línea de `react` (válida); `sentinel_guardrail.py:467-495` es el inicio del hook (el informe de enmascarado no existe, correcto);
`litellm/config.yaml:35-74` ver M2. **Omisión**: `backend/Dockerfile.standalone:35` (B1). **Premisa falsa**: `research.md:138` (B1). Las citas sin ruta (`api/legacy.py:157`, `seed.py:86`, `migrate.py:101`,
`bundle.sh:98`, `populate_volumes.sh:45`, `render_profile.sh:29`, `sentinel_guardian_policy.py:776`) son abreviaturas de rutas completas ya verificadas.

**Sentinel `6a70855`** (`sentinel:`): `catalog/api/admin.py:503/608-609`, `legacy.py:157`, `seed.py:86`, `migrate.py:101`, `credentials.py:56-68`,
`catalog/models.py:31-33/43/108-109/120-123/146-163/155`, `redirect_guard.py:328-330`, `generic.py:41`, `resolver.py:156-157`, `0615e56e8251…:23-25`,
`claude.py:255`, `residency.py` (rangos citados) y `redirect_catalog.py:71-133`: **correctas**.

**Hashes**: los 16 de HANDOFF §1(a), `9c17500`, `efb2c94`, `14edbc7`, `9fe188f`, `fd515ff`, `76ab37a`, `62edcdc`, `26c62d3`, `8736b4a`, `5fafefc`, `abfc4b7`, `c82bb1b`,
`1a90377`, `1aa3984`, `8131588`, `86788b8`, `1492788` existen y son ancestros de `origin/main` (`6a70855`); `8c525db` (HANDOFF) existe en su rama; `f8118e7`, `8999e27`, `a5a88e2`, `199bb23`, `05511a9` existen en Eleia.
**Orden de cherry-picks** (T004–T012) coincide con HANDOFF §1(a) + Anexo A (16 + 2; ADAPT-024 por `checkout` de 2 archivos). **Tests nombrados** (`test_alembic_extra_versions`, `test_models_hidden_entries`,
`test_plugin_routers`, `test_gateway_plugins`, `test_audit_routing_decision`, `test_gateway_openai_route`, `test_encryption_multifernet`, `registry.test.ts`, `test_compose_extra_env_file.sh`,
`test_guardrail_masking_report.py`) existen en `6a70855`. **API de `encryption_service`** (`encrypt`/`decrypt`/`CifradoNoDisponible`) se conserva con ADAPT-024; los símbolos de `gateway.py` que importa
`gateway_openai.py` existen en Eleia.
**Imports del paquete**: `sentinel/**` importa de `src.*` solo módulos que existen en Eleia, salvo `src.plugins` (lo trae S1) y los tres hooks opcionales (`access_hook`, `model_route_hook`,
`residency_heuristic`), ausentes y tolerados por `try/except ImportError` según HANDOFF §1(b). `gateway._audit` (`gateway.py:1041`) y `keys_api.generate_key` existen.
**IDs**: tareas T001–T087 sin colisión ni hueco (T087 intercalada en T-B por diseño; el encabezado de `tasks.md` lo dice). Las 62 FR de la spec (56 + 004a/b/c + 028a + 030a + 031a) y los 14 SC
tienen fila en la trazabilidad (`tasks.md:297-351`); todos los IDs de tarea citados en la trazabilidad existen — cobertura nominal; la calidad por FR está en M5, A2 y B3. Los IDs de tareas de Sentinel
citados (T016/T017, T066–T077, T080–T091, T093, T094, T123–T135, T183, T192) existen en su `tasks.md` y se corresponden con lo que la 057 les atribuye (T139: ver M15).

## 5. Migraciones y cherry-picks (riesgo)

- Cadena (verificada en los archivos): la rama `sentinel_redirect` cuelga de `010` (`0615e56e8251`: `down_revision=None`, `depends_on="010"`, `branch_labels=("sentinel_redirect",)`) y encadena
  `7b2d4f8a9c10 → c3f1a7d9e204 → e4a9c15b7d30 → a7d2f9c4b816 → d5b8e3a1c742 → f7a3c1d9e508`, igual que `data-model.md` §0 y HANDOFF §1(c); la migración del wizard (`b8c4d7e2a915`, otra rama
  `sentinel_onboarding`) debe quedar fuera, como dice T017. Una sola cabeza sin variable y dos con ella. La nueva migración (T026) debe hacerse por `alembic revision` colgada de `f7a3c1d9e508`;
  T016 cubre el cálculo de cabezas. **Pero** B1: el camino `Dockerfile.standalone` y el arranque silencioso de `main.py` no cumplen el contrato «con variable ⇒ `heads`».
- Base compartida con el motor: ninguna tabla nueva toca `LiteLLM_*`; las tablas de la extensión quedan expuestas igual que las del backend ante el baseline destructivo del motor (spike §1.3: base nueva con
  backend primero, restauración sin `_prisma_migrations`, subida de imagen con migraciones pendientes). El instalador comparte base (`elea_gateway`) y baja el motor por `:latest`. No se empeora, pero tampoco
  se mitiga: ver A5 y la advertencia de rollback (FR-004b). Si el baseline borra `alembic_version`, el siguiente arranque con `upgrade heads` reaplica la rama de la extensión sobre una base vacía de sus datos.
- Riesgo de orden: T001 (constitución) debe ir antes de integrar T-B (el código copiado ya responde 403); está bien planteado. T-A→T-B→T-C→{T-D∥T-E}→T-F→T-G es consistente con la propiedad de archivos de
  `plan.md:206-214` salvo A9. Los archivos re-tocados en serie (`redirect_guard.py`, `plugin.py`, `.env.example`) están ordenados.
- Dependencias de ejecución: T026 (migración) antes de T027/T060; T087 después de T026 (`tasks.md:250`): coherente.

## 6. Cobertura de escenarios, Edge Cases y SC contra tareas (tabla completa)

**Historias** (✔ = tarea y test propios; ◐ = solo heredado de Sentinel o solo en vivo 🐳; ✖ = sin tarea/test):

| Escenario | Tarea / test | Estado |
|---|---|---|
| US1.1 lista de tiers, etiqueta, ventana | T035 (`test_face_claude_contract.py`) | ✔ |
| US1.2 responde el destino, `model` = id público, auditoría | T035, T036, T045 | ✔ |
| US1.3 cambio de destino < 1 min | T030 (`test_redirect_propagation.py`, heredado), T045 | ◐ |
| US1.4 id no publicado → regla por tier / 404 | T035 | ✔ |
| US1.5 sin credencial/baja → fallback o error | T035 | ✔ |
| US1.6 `rdx-*`/`api_base` del cliente, con política encendida **o apagada** | T035 (encendida), T019 (solo en vivo 🐳) | ◐ (A3: falta offline y el caso apagada) |
| US1.7 `safeguards`/betas | T032, T033, T039, T040 | ✔ |
| US1.8 sondeo de 1 token / Azure | T038, T045 | ✔ |
| US2.1–2.2 idéntico con política apagada, con y sin extensión | T003, T018, T015 | ✔ (M11: el camino `redact=false` no se ve con motor falso) |
| US2.3 destinos de otra empresa no aparecen | T018 | ✔ |
| US2.4 id solo de otro grupo ⇒ mismo error de hoy | T018 | ✔ |
| US3.1–3.2 allowlist con fallback / sin destino | T053, T054 | ✔ |
| US3.3 enmascarado forzado restaurado (texto, tool results, **adjuntos**) | T056 | ✖ parcial: adjuntos y turnos `assistant` sin implementación (B3) |
| US3.4 analizador caído ⇒ bloqueo | T056 | ✔ |
| US3.5 ningún override relaja | T053, T056 | ✔ (A3, A8) |
| US3.6 suscripción: postura sí, redirección no | T059, T062 | ✔ |
| US3.7 admin de empresa no relaja | T055 | ◐ (A6, A7, A8 lo desarman por tres vías) |
| US3.8 default sin postura (EE. UU./Brasil/UE enmascarados; sin jurisdicción ⇒ 403) | T053, T057 | ✔ (B2: no cubre «sin fila de región») |
| US3.9 apagada y sin postura ⇒ igual que hoy | T018, T053 | ✔ |
| US3.10 relajación por destino (precondiciones) | T053, T057, T087 | ✔ (A7) |
| US3.11 control fuera de `AMERICAS` | T054, T057, T087 | ✔ |
| US4.1 Cowork con herramientas, varios turnos | T031, T037, T045 | ◐ (corpus + vivo) |
| US4.2 sin cortes por inactividad | T036, T042 | ✔ |
| US4.3 saturación / límite de tasa reintentable | T035 | ✔ |
| US4.4 PDF sin visión ⇒ rechazo explícito | T035 | ✔ |
| US4.5 ventana real ⇒ compacta sin «prompt demasiado largo» | T035 (lista con ventana), T045 | ◐ (solo el dato; el efecto, en vivo) |
| US4.6 destino nativo | — | ✖ deliberado (Clarifications P5, 🟡); coherente con SC-004 |
| US4.7 ≥ 10 pasos, historial idéntico y caché | T067–T071, T066, T078 | ✔ (A4) |
| US5.1–5.4 alias, `model`, `model_not_found`/`region_not_allowed` | T046, T047 | ✔ (M8; A9) |
| US5.5 puerta con política apagada = misma política base | T048 | ✔ |

**Edge Cases**: id sin destino activo y id en dos alcances → ◐ (solo tests heredados del resolver, no listados en T030); todos los destinos fallan → T035; formato inesperado a mitad de stream → T036 (parcial);
política cambia en medio de sesión y sin rastros de razonamiento de otro destino → T030 (propagación) + T037; caché de respuestas del motor → T071 (el guard ya la maneja: `redirect_guard.py:140-149`
`namespace` + `no-cache` con mapa de enmascarado; el test debe apuntar ahí); función exclusiva del proveedor → T035; suscripción personal con política encendida → T033; sin id de sesión → T068; dos conversaciones
con los mismos datos → T067; destino sin jurisdicción → T053; nube con control fuera → T054/T057; admin agrega postura con forzado vigente → T055 (A8); dos perfiles en una instalación → T052 (parcial: RLS por texto, M12);
costura no portable → T084/T085.

**SC**: SC-001/002 → T003/T015/T018 (ver M11); SC-003 → T083 (medición manual); SC-004 → T045 (solo traducido, bajo qué postura: A9); SC-005/006 → T054/T056/T065 (**SC-006 inalcanzable: B3, M7**);
SC-007 → T036 (con upstream falso; el real, en T045); SC-008 → T035; SC-009 → T030/T045; SC-010 → T044 (mide solo el plugin contra upstream instantáneo, no la ruta real: aceptable pero decirlo);
SC-011/012 → T066/T078 (A4); SC-013 → T015/T082 (+ T035/T047 para textos); SC-014 → T051. Todos tienen tarea; los de Docker/vivo (SC-003, 004, 011, 012, 014) dependen de aviso al owner.

**RBAC de `contracts/admin-api.md`** contra `sentinel:sentinel/redirect/api/admin.py` y `catalog/api/admin.py`: el alias `admin` = `tenant_admin`/`super_admin` (`backend/src/auth/rbac.py:23-26`) existe y los roles de la spec
(`backend/src/models/user.py:9`) cubren la matriz; las escrituras nuevas de regiones/relajaciones (T060) deben quedar en `("compliance_officer","super_admin")`; ver A6/A7/A8 para los agujeros.
**Citas de `data-model.md`/`research.md` a Sentinel**: `residency.py:19/26-27/37/90/98/122-135`, `semaforo.py:47-118`, `models.py:31/43` verificadas (rangos aproximados pero correctos).

## 7. Verificado en esta pasada y qué falta

- **B1 y B2 siguen valiendo**, con evidencia reforzada (instalador y `tenant_region`).
- **No verificado** (requiere ejecutar): B3 en vivo (multi-turno, PDF), el orden efectivo de guardrails del motor fijado, el comportamiento de `/v1/models` del motor con comodines en la versión real, las suites,
  `make -C deploy check*` y todo lo marcado 🐳; el servidor real de Elea (versión del motor, override de compose). Nada de esto se corrió: no se usó Docker.
- **Concurrencia**: durante esta pasada otro proceso commiteó sobre este mismo archivo (`2001d13`, segunda pasada, 10:52); esta versión parte de ese commit y lo conserva, con las correcciones indicadas (A2) y el agregado de B3, A8–A10 y M10–M15.
