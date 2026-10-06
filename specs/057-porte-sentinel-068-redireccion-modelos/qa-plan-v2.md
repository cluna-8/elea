# QA crítico del plan, segunda vuelta — 057 porte de la redirección de modelos (Sentinel 068)

**Rol**: qa-critico (segundo nivel; seguridad, datos sensibles, permisos). **Fecha**: 2026-10-06.
**Rama**: `cluna-8/057-plan-fix`, partiendo de `6e2ad55` (resolución del QA y re-análisis). **Solo lectura** salvo este reporte. Sin Docker, sin subagentes.
**Alcance** (acotado, no se reabre lo verificado): la tabla «Resolución del QA» de `research.md:743-832` y lo que cita (`spec.md`, `plan.md`,
`tasks.md`, `data-model.md`, `contracts/*`, `quickstart.md`), contra `qa-plan.md` (`3537847`) y el **código real**: Eleia (este árbol), Sentinel `6a70855`
(`git archive` de `sentinel/` y `backend/src/plugins.py` a un directorio temporal), el instalador (`elea-installer` `main@9754f13` y la rama
`cluna-8/fix-separar-bases-motor`, solo lectura) y la rama `fix-separar-bases-elea`.
**Límite**: es lectura. «Cerrado» significa *resuelto en spec/plan/tasks con tarea, test que falla primero y cita que coincide con el código*; no hay código de la 057
todavía, así que nada se ejecutó (ni suites, ni Docker). Lo que depende de comportamiento en ejecución está marcado **[por lectura]**.

## Veredicto

**B1, B2 y B3: cerrados.** **A2–A10: cerrados**, con A10 cerrado solo en lo que la 057 implementa (capa 1, T090): las capas 2 y 3 son una dependencia sin código en
ninguna rama (N2). **M1–M15 y B-1/B-2: cerrados** o aceptados con motivo. **No hay altos nuevos.** Hay **4 medios nuevos** (N1–N4) y 3 bajos (N5–N7); ninguno reabre una decisión
del owner (D1, D2, D3, D5, D10, D12, la enmienda del 403, P1–P5). Se corrigen por `speckit-plan`/`speckit-tasks` (no a mano), N1 y N4 antes de despachar T-E, N2 antes de despachar T-A.
**worker_done: succeeded** (B1–B3 cerrados, sin altos nuevos).

---

## 1. Estado de cada hallazgo de `qa-plan.md`

### Bloqueantes

| Id | Estado | Evidencia (archivo:línea) | Comprobación contra el código |
|---|---|---|---|
| **B1** imagen publicada / instalador | **Cerrado** | Diagnóstico #5 suma `Dockerfile.standalone:35` (`spec.md:71`); FR-004d (`spec.md:580`); R27 (`research.md:512-555`) y premisa de R6 corregida (`research.md:146-152`); S4 incluye `Dockerfile.standalone` y el aborto del arranque (`contracts/costuras-base.md`, fila S4); T088 (`tasks.md:81`, TDD: `test_standalone_heads.sh` + `test_arranque_migraciones_falla.py`), T091 (`tasks.md:116`), T100–T103 (`tasks.md:265-268`); riesgo (`plan.md:252`), T-H (`plan.md:26`) | `backend/Dockerfile.standalone:35` sigue con `alembic upgrade head` fijo y `backend/src/main.py:40-43` sigue tragando el error: la tarea ataca lo real. El mecanismo es el de `1021c8e` (CMD `t=head; [ -n "$ALEMBIC_EXTRA_VERSION_LOCATIONS" ] && t=heads` y `upgrade_target()` en `main.py`), que T004 trae y T088 extiende. R27/R6 citan bien: `publish-elea.sh:23-27` (backend/engine/frontend), `litellm/Dockerfile:7-8`, `Dockerfile.standalone:22-23`; instalador `main`: `:48` motor, `:88` backend, `:92` `8091:8000`, `:131` panel, `:64`/`:112` `latam_ar`. Falta residual: N6, N7 |
| **B2** `masked_all` solo como dato | **Cerrado** (con N1) | FR-031 (`spec.md:790`); R28 (`research.md:557-594`); `data-model.md:60-71` (respaldo en código) y `:99-105` (piso); `contracts/admin-api.md:30` (`/api/v1/redirect/health`); T094 (`tasks.md:205`), T060 (`tasks.md:208`), T095 (`tasks.md:213`); `plan.md:253` | Confirmé el defecto original en Sentinel: `redirect/plugin.py:134-137` cae a `"eu"` y `redirect/residency.py:94-98` sin filas devuelve `allowlist[home]` sin forzado. La decisión (respaldo = lo más estricto entre `reject_offregion` y `masked_all`, región sin resolver ⇒ 403, ninguna fila ni relajación lo quita) cierra el fail-open sin tocar el valor del owner. F1/M1 verificados: `docker-compose.yml:101,217` y `deploy/docker/compose.prod.yml:112,201` conservan `eu`; `compose.prod.yml` lo empaqueta `deploy/release/bundle.sh:58` para todo perfil de cliente; `.env.example:194` y el instalador (`:64`,`:112`) ya usan `latam_ar` |
| **B3** alcance del forzado / no analizable | **Cerrado** | FR-027 (`spec.md:728`), FR-041 (`spec.md:858`), SC-006 (`spec.md:986`); R29 (`research.md:596-656`); S14 (`contracts/costuras-base.md`, §S14); T034 (`tasks.md:142`), T056 (`tasks.md:201`), T096 (`tasks.md:206`), T061 (`tasks.md:209`), T097 (`tasks.md:214`); propiedad de archivos de T-E con `litellm/extensions/*` (`plan.md:237`) y T-F después (`plan.md:238`) | Las citas «hoy» coinciden: `mask_body` solo `role == "user"` (`litellm/extensions/sentinel_guardian_policy.py:880-892`), `_mask_content` solo `text`/`tool_result` (`:858-878`), `extract_inspect_text` (`:734-749`), CUIT con guiones (`:143`); `masking_ok` compara `detected == masked` (`redirect_guard.py:118-125`, `:328-330`). S14 es retrocompatible (sin la señal, `scope="user"`), con regla general fail-closed, PDF a texto, no analizable ⇒ `masking_required`, informe sin `scope` no pasa, `count_tokens` no se reenvía bajo forzado. Cierra los tres vectores de B3 (adjuntos, turnos `assistant` reenviados restaurados, `system`/`tools`). Residual: N4 |

### Altos

| Id | Estado | Evidencia | Nota |
|---|---|---|---|
| **A2** FR-016 sin prueba propia | Cerrado | `research.md:722-727` (R32), T035 (`tasks.md:143`: llave con `allowed_models` permitido/no permitido/vacía; `rdx-*` nunca contra la lista), T019 (`tasks.md:104`: todos los casos de R13) | Consistente con la barrera real: `sentinel:redirect/plugin.py:354-357` |
| **A3** `rdx-*` y orden de guardrails | Cerrado | `research.md:728-732`, T092 (`tasks.md:117`), T020 (`tasks.md:105`) | T092 cubre `call_type` no textuales, orden en el `config.yaml` fusionado y metadata del cliente que no relaja |
| **A4** sobre-enmascarado (069 T184) | Cerrado | `plan.md:255`, `research.md:733-736`, T045 (`tasks.md:153`), T083 (`tasks.md:285`), T085 (`tasks.md:287`) | Ver N5 (T045 mide antes de S14) |
| **A5** `DISABLE_SCHEMA_UPDATE` | Cerrado | `research.md:108-112` (R5), `plan.md:256`, `quickstart.md:13`, T019 (`tasks.md:104`), T021 (`tasks.md:106`) | Reformulada como hipótesis fuera del override hasta ensayarla |
| **A6** `REDIRECT_OPERATOR_TENANT` | Cerrado (con N3) | FR-023 (`spec.md:701`), R30 (`research.md:657-690`), T055 (`tasks.md:200`), T060 (`tasks.md:208`), `quickstart.md:26` | La variable no existe en ningún archivo de Eleia ni en el instalador (`grep`: solo specs). El código usa `_is_super` en el catálogo entero (`sentinel:catalog/api/admin.py:188-235,449-467,594-718`); T060 solo cambia regiones/postura/relajaciones. Con la variable sin definir, `_is_super` ≡ `super_admin`: coherente |
| **A7** ficha editable por el admin | Cerrado | `data-model.md:235`, `contracts/admin-api.md:76`, T099 (`tasks.md:118`) | Cubre `SHEET_WRITERS` (`sentinel:catalog/api/admin.py:41`, `put_sheet` `:668-675`) |
| **A8** fila `off` reemplaza el default | Cerrado | `data-model.md:91-116`, `contracts/admin-api.md:21`, T098 (`tasks.md:207`), T060 | Orden total definido (entre modos y por inclusión de `home`/jurisdicciones), 422 `posture_less_strict`, piso calculado antes de combinar con filas del admin (U5), destino sin jurisdicción ⇒ 403 con cualquier fila. Coincide con el defecto real: `effective_posture` solo mira filas (`residency.py:99-119`) y `create_posture` acepta cualquier modo (`admin.py:583-598`); `created_by_role` existe (`admin.py:595`) |
| **A9** secuencia | Cerrado | `plan.md:226`, `tasks.md:162,302`, T045 (`tasks.md:153`) | Orden A→B→C→E→{D∥F}→H→G; T045 con postura explícita; T083 repite con el default real. Coherente con `tasks.md:302,311` |
| **A10** `/internal/model-credential` | **Cerrado en lo propio (capa 1)**; capas 2–3 **abiertas como dependencia** (N2) | R31 (`research.md:689-718`), T090 (`tasks.md:115`), T089 (`tasks.md:82`), T101 (`tasks.md:266`), `spec.md:238` | La ruta sigue entregando `cr.resolve(...)` con solo el secreto (`sentinel:catalog/api/internal.py:149-163`) y `direct_enabled()` (`:97-101`) no la apaga: T090 lo arregla en la ruta HTTP. Eso cierra por sí solo la exposición de credenciales de proveedor que A10 denunciaba |

### Medios y bajos

| Id | Estado | Evidencia |
|---|---|---|
| M1 | Cerrado (sin cambio, correcto) | T015 🐳 (`tasks.md:83`) |
| M2 | Cerrado | `research.md:184`, `quickstart.md:65`, T023 (`tasks.md:108`), T045: `gpt-5.6-luna` «a confirmar con el owner» con alternativa |
| M3 | Cerrado | `research.md:345`, T067 (`tasks.md:234`) |
| M4 | Cerrado | `research.md:596` (R29: ningún tipo queda exento bajo forzado), T056 (`tasks.md:201`), T097 |
| M5 | Cerrado | T030 (`tasks.md:120`) lista los tests heredados que cubren FR-005/006/012/013/016 y exige que no queden saltados |
| M7 | Cerrado | T097 (patrón sin guiones), T056 (batería con formatos) |
| M8 | Cerrado y **verificado contra el código**: la cara Claude responde 400 `invalid_request_error` con «…bloqueado. Probá en una conversación nueva.» (`sentinel:redirect/faces/claude.py:94-98`) y la genérica 403 `masking_required` (`faces/generic.py:40-42`); los contratos lo dicen igual (`contracts/cara-claude.md:72`, `cara-generica.md:23`) |
| M9 | Aceptado sin cambio, con motivo (`data-model.md:179`); con A7 el admin no cambia la ficha |
| M10 | Cerrado | `research.md:349`, T093 (`tasks.md:240`), T100 (`tasks.md:265`) |
| M11 | Cerrado | T008 (`tasks.md:74`: `test_guardrail_redact_off_057.py`), T085 |
| M12 | Cerrado | T030/T065/T086 con `-rs` y 0 saltados entre los críticos |
| M13 | Cerrado | T079 (`tasks.md:281`) suma overview, release-notes y compliance o los declara fuera con motivo |
| M14 | Cerrado | T034 (`tasks.md:142`), T041 (`tasks.md:149`: `cl100k_base` horneado y respaldo `caracteres/4`), T091 |
| M15 | Cerrado | T001 (`tasks.md:67`: aviso de divergencia de versión), ids «de Sentinel» rotulados |
| B-1 | Cerrado | `data-model.md:231` (`String(8)`) |
| B-2 | Aceptado (cita aproximada sin consecuencia) |

### Re-análisis (`research.md:784-832`)

Revisé las cuatro corridas: los HIGH/MEDIUM que declaran resueltos tienen cambio en los artefactos y ninguno contradice el código (F1 y M1 verificados arriba; C3
«`redact_enabled=false` bajo forzado sale enmascarado» está en T056 `tasks.md:201` y S14). Las ≈52 citas `tasks.md:N (Txxx)` de `research.md` apuntan a la línea
de la tarea correcta (script: 0 discordancias); ids T001–T103 sin hueco ni duplicado (103 tareas).

---

## 2. Hallazgos nuevos

Severidad: **Alto** = viola una FR/SC o abre una vía de fuga sin barrera; **Medio** = el plan no es implementable o no garantiza lo que dice, con barrera de respaldo; **Bajo** = precisión.

### N1 — Medio — «Seeds al arrancar» (T095) no tiene dónde engancharse: S1 monta solo routers y Eleia arranca con `lifespan`
- **Evidencia**: T095 (`tasks.md:213`) y R28 (`research.md` punto 4) cargan regiones y reglas con «un enganche de arranque del router de la extensión (S1)» en `sentinel/redirect/seed_on_startup.py`.
  S1 (`backend/src/plugins.py` de Sentinel `6a70855`) solo valida y monta `(APIRouter, prefix)`; no tiene punto de arranque. La app de Eleia se crea con `lifespan=_lifespan` (`backend/src/main.py:81,101`, FastAPI 0.111.0,
  `backend/requirements.txt:1`): con `lifespan`, los `on_startup` de un router incluido **no se ejecutan** **[por lectura; confirmar con test contra `src.main:app`]**.
- **Falla**: la extensión arranca sin cargar el seed; rige el respaldo de T094 (fail-closed, `/api/v1/redirect/health` 503 `region_row_missing`). No hay fuga —el respaldo es el fail-safe que B2 pedía— pero
  la instalación queda degradada para siempre: `masked_all` de Eleia no se aplica como dato, no hay relajación por región ni por destino (el respaldo las ignora, `data-model.md:105,215`) y T100 hace
  «fallar visible» al instalador. El test previsto (`test_seed_al_arrancar.py`) con un `FastAPI()` suelto pasaría sin probar nada.
- **Viola**: FR-031 (seed al arrancar, `spec.md:790`), FR-004d (activación que funcione).
- **Corrección** (por `speckit-plan`/`tasks`): fijar el mecanismo —costura nueva de base en el `_lifespan` (retrocompatible, sin la variable no hace nada, como `retention_scheduler`), o carga perezosa en el
  primer pedido/`health`—, y que el test use `src.main:app` con su lifespan real. Mientras tanto no cuenten con T095 para quitar el 503.

### N2 — Medio — A10, capas 2 y 3: «las entrega el arreglo de separación de bases» no es lo que ese arreglo contiene
- **Evidencia**: `spec.md:238`, R31 (`research.md:701-716`), `tasks.md:82,266,311` dicen que el arreglo de bases entrega `INTERNAL_ALLOWED_CIDRS=auto` y el proxy. En el instalador
  (`cluna-8/fix-separar-bases-motor`, 3 commits sobre `main`), `ENSAYO-SEPARAR-BASES.md:168-195` solo **verifica la exposición** y lo deja como «**Propuesta mínima … (no aplicada)**»; `docker-compose.yml:129` sigue
  publicando `8091:8000`; no hay proxy ni `INTERNAL_ALLOWED_CIDRS` en esa rama. En Eleia, `fix-separar-bases-elea` (`03463a5`, 12 archivos) tampoco toca `backend/src/api/internal.py`: `grep INTERNAL_ALLOWED_CIDRS` = 0.
  Además el ensayo dice que **filtrar por IP de origen no sirve** («el puerto publicado llega con la IP del puente de Docker, indistinguible», `:193-195`); S15 `auto` (subredes menos puerta de enlace) propone lo contrario
  sin prueba, y puede variar con Docker Desktop/rootless.
- **Falla**: la dependencia es una promesa, no un artefacto. T089 (gate de T-A: «si no está integrado, parar y escalar») va a **detener T-A**; y si el arreglo se cierra solo con el proxy, S15 nunca existe y T089/T101 verifican algo que no está.
  El riesgo de fondo (identidad/auditoría del motor alcanzables por la LAN con la llave maestra, `ENSAYO:171-184`) es previo a la 057; la credencial de proveedor ya queda cerrada por T090.
- **Viola**: FR-013 (en la parte de dependencia), coherencia del plan (`plan.md:273`).
- **Corrección**: confirmar con el coordinador que el arreglo de bases incluye proxy y S15 (con su ensayo de `auto` en el compose real) y reflejarlo en su alcance; si solo incluye el proxy, bajar S15 a «opcional» en R31/`costuras-base.md`/T089 para que el gate no sea imposible.

### N3 — Medio — La separación de funciones de FR-023 (A6–A8) es por rol, y el admin de empresa puede crear un `compliance_officer` o un `super_admin`
- **Evidencia**: `POST /users` exige solo `require_role("admin")` (`backend/src/api/users.py:413-414`), acepta cualquier rol de `VALID_ROLES` (`backend/src/models/user.py:9`:
  `super_admin`, `tenant_admin`, `compliance_officer`, …; `_validar_alta` `users.py:312-346` solo gatea licencia para `client`) y `effective_roles` mapea `tenant_admin`/`super_admin` a `admin` (`auth/rbac.py:23-36`).
  La migración dice que `super_admin` «NO se autogenera» (`alembic/versions/010_multitenant_foundation.py:14`): ninguna ruta del instalador lo crea (`install.sh:128` da de alta usuarios `client`), así que en una instalación así quien hace de cumplimiento es, en la práctica, un usuario creado por el admin **[por lectura: no vi el alta del primer admin; confirmar]**.
- **Falla**: R30 y T055/T098/T099 prueban que *el rol* `tenant_admin` no relaja; pero el mismo admin crea (con registro) un usuario `compliance_officer` y relaja el piso de D2, la ficha y las relajaciones. US3 esc. 7 y el Edge Case
  del administrador se cumplen al pie de la letra y no en la intención. Es una propiedad previa de la base (y del diseño de Sentinel 068), no un defecto de lo que la 057 agrega.
- **Viola**: FR-023 y US3 esc. 7 en su intención; la honestidad de la doc (AGENTS.md DoD) si T080 afirma «el administrador no puede relajar».
- **Corrección**: decisión del owner, no del plan: (a) T080 redacta la garantía como «no desde el rol de administrador de empresa; quien administra usuarios puede designar al responsable de cumplimiento (queda auditado)» y T055 prueba que
  el alta de ese rol queda en el registro, o (b) una costura retrocompatible que limite crear `compliance_officer`/`super_admin` a `super_admin`. No reabre D2.

### N4 — Medio — La extracción de PDF corre síncrona dentro del motor y sin tope de tiempo ni de memoria
- **Evidencia**: R29 (`research.md:596-656`) y T097 (`tasks.md:214`) limitan páginas (200) y bytes (20 MB) y cuentan los errores del parser como no analizable, pero no hay tope de **tiempo**, de **expansión** (compresión de streams) ni ejecución
  fuera del bucle de eventos. `pypdf` es síncrono (en el repo ya se usa por lotes en otro contenedor, `client/extract_text.py:36-38`); en el motor la llamada ocurre en el guardrail asíncrono del proxy.
- **Falla** **[por lectura]**: un PDF de 20 MB con streams que se expanden mucho, o con 200 páginas densas, bloquea el bucle del motor segundos (también a otros usuarios) o consume memoria; la entrada es del cliente. No hay fuga (falla cerrado si termina), pero es un vector de degradación del servicio para toda la empresa, y T097 solo mide «informativo».
- **Viola**: Constitución §Security (entrada no confiable) y SC-010 en espíritu.
- **Corrección**: T096/T097 con test de PDF hostil (bomba de compresión, páginas densas): extracción en hilo/proceso con timeout y tope de memoria, error ⇒ no analizable; fijar `pypdf` en una versión con límites de descompresión (ya queda con hash en T091).

### N5 — Bajo — Consistencia de `"eu"` por defecto: T094 nombra un solo sitio
- **Evidencia**: T060/T094 cambian `tenant_region` (`sentinel:redirect/plugin.py:134-137`), pero otros dos sitios repiten el default: `redirect/api/admin.py:571` (`list_postures`, lo que muestra el panel) y `redirect/api/us5.py:197` (`run_fidelity`, que
  evalúa la postura con `ensure_allowed`).
- **Falla**: con región sin resolver, el panel muestra una postura efectiva `allowlist[EU]` y la prueba de fidelidad decide con `eu` mientras el tráfico real da 403. Es de presentación y de la prueba, no del tráfico.
- **Corrección**: un único `tenant_region()` compartido (T060) y T094 que cubra los tres sitios.

### N6 — Bajo — T100 no enumera las variables que **activan** la extensión
- **Evidencia**: `sentinel/docker/backend.Dockerfile:9-12` (Sentinel) aclara que «nada se activa por estar en la imagen»: `GATEWAY_PLUGINS`, `PLUGIN_PACKAGES`, `ALEMBIC_EXTRA_VERSION_LOCATIONS` y `REDIRECT_INTERNAL_KEY` vienen por el archivo de entorno (S12).
  T100 (`tasks.md:265`) lista `REDIRECT_INTERNAL_KEY`, `MASKING_NONCE_KEY`, región y seeds, pero no las otras tres (ni las del motor). Si el archivo no las lleva, `ELEA_REDIRECT=1` levanta una `-ext` inerte y `GET /api/v1/redirect/health`
  responde 404, no 503: el chequeo «falla visible si da 503» no lo detecta.
- **Corrección**: enumerar la lista completa de HANDOFF §2.1 en el test de T100 y que el instalador falle también con 404/no-200 del `health`.

### N7 — Bajo — Contexto de build de las `-ext`
- **Evidencia**: `deploy/release/publish-elea.sh:25-27` fija el contexto del motor en `litellm` y del panel en `frontend`; las `-ext` necesitan `sentinel/engine/redirect_*.py`, `sentinel/frontend/pages` y `deploy/release/fragment_merge.py`,
  fuera de esos contextos (el `backend.Dockerfile` de Sentinel ya exige «la RAÍZ del repo»). T091 (`tasks.md:116`) no dice que el contexto de las tres `-ext` es la raíz.
- **Corrección**: precisarlo en T091 y en su `test_ext_images.sh`.

### Observación (no es hallazgo): T045 mide antes de S14
T045 (`tasks.md:153`) cuenta falsos positivos con el alcance **actual** (solo `user`), antes de que T097 amplíe el enmascarado a `system`/herramientas; el número que importa para SC-004/SC-011 es el de T083 (`tasks.md:285`), que ya se repite con el default real.
El plan lo dice; solo conviene no tomar el conteo de T045 como medida del riesgo A4.

---

## 3. Contraste con la constitución (`.specify/memory/constitution.md` 2.2.0)

- **I (masking-first)**: B2 y B3 lo refuerzan (forzado fail-closed con piso, alcance completo). El informe `masking_report` y `unanalyzable_kinds` llevan solo contadores y nombres de tipo (S14, `contracts/costuras-base.md`). OK.
- **II/auditoría metadata-only**: `dropped_fields`, `betas_dropped`, `default_posture_applied`, `masking_relaxation`, `masking_scope` son nombres/valores sin contenido (`data-model.md:270-273`); T035 y T049 prueban que la fila no lleva texto ni secretos. OK.
- **III (multi-tenant)**: tablas nuevas con `tenant_id` + RLS (T026); la FR-051 solo queda 🟢 con la suite 🐳 (T030, declarado). OK.
- **IV/VII (onboarding como datos; config + seed, nunca fork)**: reglas vacías y `masked_all` son seed (T028, T064); las `-ext` derivan de las imágenes base sin modificarlas (R27). OK. N3 es el único punto donde el «dato» (rol) se puede cambiar desde dentro.
- **VI (LiteLLM nativo)**: `pypdf` y los `redirect_*.py` entran en una imagen derivada del motor, sin parchear LiteLLM. OK (N4 es de robustez, no de principio).
- **Línea Eleia/Sentinel**: todo lo base es genérico y vuelve por HANDOFF (T085); no se cita GDPR/AI Act como norma del perfil (T079/T080 usan Ley 25.326/AAIP). OK.

## 4. Qué se verificó y cómo (evidencia)

- `git log`: `6e2ad55` es la HEAD; `git status` limpio al empezar.
- Script sobre `research.md`: 52 referencias `tasks.md:N (Txxx)` → 0 discordancias; `grep '^- \[ \] T'` → 103 tareas, 0 ids duplicados.
- Líneas «hoy» de Eleia leídas: `backend/Dockerfile.standalone:22-23,35`, `backend/src/main.py:28-43,81-101`, `litellm/Dockerfile:1-8`, `deploy/release/publish-elea.sh:18-32`,
  `litellm/extensions/sentinel_guardian_policy.py:120-157,730-752,855-893`, `docker-compose.yml:101,217`, `deploy/docker/compose.prod.yml:112,201`, `.env.example:194`, `backend/src/api/users.py:312-415`, `backend/src/models/user.py:9`, `backend/src/auth/rbac.py:23-36`.
- Sentinel `6a70855` (extraído con `git archive`): `redirect/plugin.py:134-137`, `redirect/residency.py:85-135`, `redirect/api/admin.py:75-100,550-600`, `redirect/api/us5.py:180-215`, `engine/redirect_guard.py:100-130,320-335`,
  `catalog/api/internal.py:90-165`, `catalog/api/admin.py:30-45,660-675`, `redirect/faces/claude.py:85-102`, `redirect/faces/generic.py:30-48`, `docker/backend.Dockerfile`, `backend/src/plugins.py`, y el diff de `1021c8e`.
- Instalador: `main@9754f13` `docker-compose.yml` líneas `:48,:64,:88,:92,:112,:131`; rama `fix-separar-bases-motor`: `ENSAYO-SEPARAR-BASES.md:166-200`, `docker-compose.yml:129`; `fix-separar-bases-elea` `03463a5 --stat` y `grep INTERNAL_ALLOWED_CIDRS`.
- **No se corrió**: suites, `make -C deploy check*`, Docker, ni nada de lo marcado 🐳. No hay código de producto cambiado, por lo que no corresponde correr las suites del proyecto; la verificación de B1–B3 en ejecución queda para T088/T094–T097 y T102.

## 5. Para el coordinador

1. **N2 primero**: confirmar el alcance real del arreglo de bases (proxy y S15) antes de despachar T-A; T089 lo va a frenar.
2. **N1 y N4 antes de T-E**: mecanismo de arranque del seed (con `lifespan`) y topes de tiempo/memoria del PDF.
3. **N3**: decisión del owner (redactar la garantía honestamente o limitar el alta de roles de cumplimiento/super).
4. N5–N7: ediciones menores de T060/T094, T100 y T091 por `speckit-tasks`.
