# QA crítico del plan — 057 porte de la redirección de modelos (Sentinel 068)

**Rol**: qa-critico (segundo nivel; seguridad, datos sensibles, permisos). **Fecha**: 2026-10-06.
**Rama**: `cluna-8/057-plan-legal`. **Solo lectura** salvo este reporte. Sin Docker.
**Alcance leído**: `spec.md` completa, `plan.md`, `tasks.md`, `research.md`, `data-model.md`, `contracts/*`, `quickstart.md`,
constitución 2.2.0, HANDOFF de Sentinel (`docs/handoff-068-elea`, 572 líneas), spike de bases (`cluna-8/spike-separar-bases-motor`),
código de Eleia y el paquete `sentinel/` de Sentinel `6a70855` (extraído a un directorio temporal).

> **Cobertura honesta**: la revisión se cortó por límite de uso. **Hecho**: citas de Eleia y de Sentinel, hashes, orden de
> cherry-picks, imports del paquete contra el backend de Eleia, trazabilidad FR→tarea (nominal), lógica de residencia/guard,
> migraciones y entrega. **No hecho**: contraste escenario por escenario de US1–US5 y de los Edge Cases contra tareas/tests
> (solo muestreado), SC-001…SC-014 uno a uno, verificación de las ~25 citas de `data-model.md`/`research.md` a `sentinel:…` fuera de
> las listadas en §4, y la revisión de `contracts/admin-api.md` contra RBAC real (`backend/src/models/user.py:9`).

## Veredicto

**Hay 2 bloqueantes** (B1, B2) y 4 hallazgos altos. Ninguno reabre una decisión del owner: son huecos de entrega y de
fail-safe del default que el owner decidió (`masked_all`). Se recomienda corregirlos por `speckit-tasks`/`speckit-plan`
(no a mano) antes de despachar T-A (B1) y antes de integrar T-E (B2). Las decisiones D1/D2/D5/D12/D3/D10 y la enmienda del 403 **no se tocan**.

---

## 1. Bloqueantes

### B1 — La imagen que Eleia publica no queda cubierta por S4 (con la extensión activa no arranca)
- **Evidencia**: `backend/Dockerfile.standalone:35` ejecuta `alembic upgrade head`; es la imagen que publica `deploy/release/publish-elea.sh:25`
  (`[backend]=backend/Dockerfile.standalone`). Ni la spec (Diagnóstico #5, `spec.md:71`) ni T004 (`tasks.md:56`) la listan, y `1021c8e`
  no la toca (solo `backend/Dockerfile`, `entrypoint/backend.sh`, `main.py`, `env.py`; Sentinel ni tiene ese archivo).
- **Falla**: con `ALEMBIC_EXTRA_VERSION_LOCATIONS` definida hay dos cabezas; `alembic upgrade head` falla («multiple heads») y el
  `&&` del CMD impide levantar uvicorn → crash-loop en la imagen del instalador. Además `backend/src/main.py:34-43` traga el error
  de migración (`logger.error(...)` sin abortar): un fallo de `upgrade heads` en el arranque queda silencioso.
- **Viola**: FR-004b, FR-004c, Constitución VII (config + seed), AGENTS.md (features que tocan el instalador se coordinan en el mismo plan).
- **Relacionado (Alta, A1)**: no hay ninguna tarea que haga llegar `sentinel/` (backend a `/opt/sentinel-ext`, `PYTHONPATH`) ni el
  build del panel con `VITE_PLUGIN_PAGES_DIR` a las imágenes publicadas (`publish-elea.sh:23-26`, `publish.sh:41-42`); solo T021 cubre
  **desarrollo**. `sentinel/docker/{backend,frontend}.Dockerfile` vienen en la copia pero nadie los conecta. T081 documenta
  «activación» de algo que el release no puede entregar. El plan no menciona `cluna-8/elea-installer` ni una vez
  (`grep instalador` en los artefactos: solo `research.md:138`).
- **Corrección**: tarea en T-A/T-B que (a) agregue la rama `heads` condicional a `Dockerfile.standalone` con test de contrato, (b) haga
  fallar el arranque (no tragar) cuando la variable está definida y la migración falla, y (c) decida y planifique la entrega de
  paquete/panel a las imágenes publicadas y al instalador (o declare explícitamente que el MVP es solo desarrollo y lo diga en spec/docs).

### B2 — La postura por defecto `masked_all` solo existe como dato sembrado; sin seed o sin región, el redirigido sale sin enmascarar
- **Evidencia**: `data-model.md` §1 (fallback «respaldo fijo de `region_codes`», de fábrica `reject_offregion`);
  Sentinel `sentinel/redirect/residency.py:90-120` (con `region_codes('latam_ar')={LATAM,AR}` y sin filas ⇒ `allowlist` sin forzado).
  El seed lo carga a mano `python -m sentinel.redirect.regions_seed` (T064; `quickstart.md` §2): ninguna tarea lo enchufa al despliegue.
  Además la región depende de `SENTINEL_ENTITY_REGION`, cuyo default en ambos compose es `eu` (`docker-compose.yml:101,217`;
  `deploy/docker/compose.prod.yml:112,201`) y solo `.env.example:194` lo pone en `latam_ar`.
- **Falla**: instalación sin el seed (o con la fila borrada/otra región) ⇒ destinos en `{LATAM,AR}` (o `{EU}` si falta la variable) salen
  **sin enmascarado forzado**, contradiciendo la decisión D2 del owner («todo el redirigido sale enmascarado»). Ningún test (T053/T057/T064)
  cubre «sin fila de región». No es fuga hacia fuera de región (el resto se rechaza), pero sí rompe FR-027/FR-031/SC-006 en el default.
- **Viola**: FR-031, FR-027, Constitución I (masking-first).
- **Corrección**: test «instalación Eleia sin fila de región» + decidir el comportamiento seguro (p. ej. chequeo de arranque/`/health` que
  falle o avise si la política está encendida sin región resuelta; cargar el seed desde el camino de despliegue; documentar
  `SENTINEL_ENTITY_REGION=latam_ar` como obligatoria en el env de la extensión). No cambia el valor decidido por el owner.

---

## 2. Altos

- **A2 — Restricción por llave en el motor (FR-016) sin verificar**: `litellm/extensions/custom_auth.py:478` pasa `models=allowed_models` de la
  llave al motor y `backend/src/services/ai_engine_client.py:159` los manda en `/key/generate`. Si una llave tiene `allowed_models`, el motor
  validará el modelo **reescrito** (`rdx-*`) contra esa lista. La spec dice que S10 no se porta porque «la lista se resuelve en la
  pasarela» (FR-002/FR-016), pero ninguna tarea prueba el caso (T035 nombra FR-016 sin un caso concreto). Falta test: llave con
  `allowed_models` + id público permitido ⇒ sirve; id público no permitido ⇒ rechaza; y confirmar cómo pasa el motor la restricción.
- **A3 — Defaults del motor para `rdx-*` y credenciales de entorno**: el fragmento declara `rdx-azure/*` etc. sin credencial; el motor de Eleia
  tiene `AZURE_API_KEY` en el entorno (`litellm/config.yaml:35-74`). Todo depende de que `redirect-guard` rechace sin autorización
  (`sentinel/engine/redirect_guard.py:307-320` y `should_run_guardrail`). Es sólido en el código copiado, pero T019 (D14) solo se corre en vivo
  con Docker; falta un test offline de «`rdx-*` sin autorización ⇒ 403 también en `call_type` no textuales» y de **orden de guardrails** en el
  `config.yaml` fusionado (el guard debe ir después de `sentinel-guardian`, `litellm/config.yaml:12`; T020 prueba «al final», no el orden efectivo
  ni la presencia del `masking_report`).
- **A4 — Sobre-enmascarado de Claude Desktop (069 T184 de Sentinel, HANDOFF §3 última fila)** no aparece en ningún artefacto de la 057
  (`grep T184` = 0). Con `masked_all` **todo** el tráfico redirigido pasa por el enmascarado, y el HANDOFF reporta 17 PERSON/14 LOCATION/3 PASSPORT
  falsos por pedido en el prompt de sistema. Pone en riesgo SC-004 (≥95 % sin errores), SC-011 (≥60 % de caché) y el bloqueo por `detected != masked`
  (`sentinel/engine/redirect_guard.py:118-125`). Debe entrar al registro de riesgos del plan y al HANDOFF de vuelta.
- **A5 — Mitigación `DISABLE_SCHEMA_UPDATE=true` presentada como respaldada**: `research.md:108-111`, T021 y `quickstart.md` §0 la citan como
  «mitigación del spike §5», pero el propio spike dice que **no se ensayó** (`ANALISIS-SEPARAR-BASES-MOTOR-2026-10.md` §7 ítem 8; `[no verificado]`).
  Con ese flag, además, un motor sobre base nueva no crea sus tablas. Reformular como hipótesis y agregar su ensayo a T019/T045. Las demás
  mitigaciones de R5 son coherentes (FKs solo a `tenants`/`groups`; sin cambio de imagen). Nota: el instalador usa `:latest` del motor
  (spike §1.4), fuera del control de esta feature pero relevante para el rollback (FR-004b).

## 3. Medios y bajos

- **M1 — T-A usa Docker en su gate** (T015, 🐳): correcto y marcado; recordar que `make -C deploy docs-refs` regenera `openapi.json` y debe correrse con aviso al owner.
- **M2 — «Cuatro entradas azure/*» (`spec.md:79`, `litellm/config.yaml:35-74`)**: son 3 modelos conversables + `router-embeddings`
  (`text-embedding-3-large`, no conversable). `gpt-5.6-luna` (T023, `research.md:168`, «disponibles hoy») **no existe** en el repo de Eleia ni hay
  evidencia de despliegue en el recurso de Azure; el quickstart lo usa como destino de opus. Marcarlo «a confirmar con el owner».
- **M3 — S13 y la decisión sellada del 08-sep** (comentario en `litellm/extensions/sentinel_guardian_policy.py:760-770`: un seudónimo estable
  entre documentos «sería una enmienda constitucional aparte, C1»). S13 es por conversación y con clave del servidor y la llave en el HMAC, así que
  es compatible, pero ni `research.md` R18 ni la enmienda de T001 lo citan; agregar la referencia y un test de «no estable entre conversaciones».
- **M4 — `masking_ok` exige `detected == masked`** (`sentinel/engine/redirect_guard.py:118-125`): un tipo de entidad configurado como no enmascarable
  por el tenant haría que `masked_all` bloquee todo pedido que lo contenga. Verificar la semántica de `detected` (S5b, `1a454ed`) y cubrirlo en T056.
- **M5 — FR-005/FR-006/FR-013/FR-016 con test solo heredado**: sin tarea de test propia (el chat de la consola intacto; credenciales no visibles
  en API/logs; permisos por alcance). Aceptable por ser copia, pero T030 debería listar los archivos de test heredados que los cubren.
- **M6 — Piso con fila explícita `off`**: T053/T055 prueban `allowlist` bajo `masked_all`; agregar el caso de una fila `off` («apagada», FR-022) bajo el piso.
- **B-1 (bajo)** `control_jurisdiction String(16)` vs `entity_jurisdiction String(8)` (`sentinel/catalog/models.py:152`): unificar.
- **B-2 (bajo)** `spec.md:67`: `gw_messages` está en `gateway.py:1636` (decorador); la función arranca después. Cita aproximada, sin consecuencia.

## 4. Citas, hashes e IDs — verificación

**Eleia (archivo:línea citados en spec/plan/research/tasks/contracts)** — verificadas contra el árbol actual:
`ci.yml:50`, `chat.py:1402`, `gateway.py:1636/1989/2014-2017/2031/2039/2047-2069/2053`, `main.py:38/105/113/120`, `audit.py:47`, `user.py:9`,
`audit_service.py:422`, `entrypoint/backend.sh:30`, `backend/Dockerfile:19`, `test_profile_renders.sh:26`, `bundle.sh:98-99/186-187`,
`populate_volumes.sh:45-46`, `render_profile.sh:29`, `litellm/config.yaml:12/19-25`, `litellm/Dockerfile:6`, `.env.example:194`,
`sentinel_guardrail.py:20/626`, `sentinel_guardian_policy.py:141/510/784`, `199fe429762a…py:22-23` (cabeza única, `down_revision 7a6fee614cfd`):
**correctas**. Observaciones: `frontend/package.json:19` apunta a la línea de `react` (válida); `sentinel_guardrail.py:467-495` es el inicio del hook (el informe de
enmascarado no existe, correcto); `litellm/config.yaml:35-74` ver M2. **Omisión**: `backend/Dockerfile.standalone:35` (B1).

**Sentinel `6a70855`** (`sentinel:`): `catalog/api/admin.py:503/608-609`, `legacy.py:157`, `seed.py:86`, `migrate.py:101`, `credentials.py:56-68`,
`catalog/models.py:31-33/43/108-109/120-123/146-163/155`, `redirect_guard.py:328-330`, `generic.py:41`, `resolver.py:156-157`, `0615e56e8251…:23-25`,
`claude.py:255`, `residency.py` (rangos citados) y `redirect_catalog.py:71-133`: **correctas** (en `residency.py` `effective_posture` y `evaluate` están en los rangos citados).

**Hashes**: los 16 de HANDOFF §1(a), `9c17500`, `efb2c94`, `14edbc7`, `9fe188f`, `fd515ff`, `76ab37a`, `62edcdc`, `26c62d3`, `8736b4a`, `5fafefc`, `abfc4b7`, `c82bb1b`,
`1a90377`, `1aa3984`, `8131588`, `86788b8`, `1492788` existen y son ancestros de `6a70855`; `f8118e7`, `8999e27`, `a5a88e2`, `199bb23`, `05511a9` existen en Eleia.
**Orden de cherry-picks** (T004–T012) coincide con HANDOFF §1(a) + Anexo A (16 + 2; ADAPT-024 por `checkout` de 2 archivos).
**Imports del paquete**: `sentinel/**` importa de `src.*` solo módulos que existen en Eleia, salvo `src.plugins` (lo trae S1) y los tres hooks
opcionales (`access_hook`, `model_route_hook`, `residency_heuristic`), ausentes y tolerados por `try/except ImportError` según HANDOFF §1(b). `gateway._audit`
(`gateway.py:1041`) y `keys_api.generate_key` existen.
**IDs**: tareas T001–T087 sin colisión (T087 intercalada en T-B por diseño; el encabezado de `tasks.md` lo dice). Las 62 FR de la spec tienen fila en la
trazabilidad (`tasks.md:297-351`) — cobertura nominal; la calidad por FR está en M5/A2.

## 5. Migraciones y cherry-picks (riesgo)

- Cadena: la rama `sentinel_redirect` cuelga de `010` (`0615e56e8251:23-25`); una sola cabeza sin variable y dos con ella: coherente con HANDOFF §1(c).
  La nueva migración (T026) debe hacerse por `alembic revision` colgada de `f7a3c1d9e508`; T016 cubre el cálculo de cabezas. **Pero** B1: el camino
  `Dockerfile.standalone` y el arranque silencioso de `main.py` no cumplen el contrato «con variable ⇒ `heads`».
- Base compartida con el motor: ninguna tabla nueva toca `LiteLLM_*`; las tablas de la extensión quedan expuestas igual que las del backend ante
  el baseline destructivo del motor (spike §1.3: base nueva con backend primero, restauración sin `_prisma_migrations`, subida de imagen con migraciones
  pendientes). No se empeora, pero tampoco se mitiga: ver A5 y la advertencia de rollback.
- Riesgo de orden: T001 (constitución) debe ir antes de integrar T-B (el código copiado ya responde 403); está bien planteado.

## 6. Qué verificar a continuación (no hecho)

US1–US5 y Edge Cases escenario por escenario; SC-001…SC-014; `contracts/admin-api.md` contra roles reales; citas restantes de `data-model.md`/`research.md`.
