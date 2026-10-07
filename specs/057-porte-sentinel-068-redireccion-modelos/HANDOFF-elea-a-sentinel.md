# Handoff — spec 057 (Elea) para llevar a Sentinel: lo nuevo de la base que salió del porte de la 068

**Fecha**: 6-oct-2026. **Origen**: `github.com/cluna-8/elea`, rama de integración `cluna-8/057-int` (tramos
T-A a T-F y la documentación de T-G; la entrega por el instalador, T-H, sigue abierta). **Destino**:
`cluna-8/sentinel` (producto base, «Guardian»). **Instalador**: `cluna-8/elea-installer` **sí** se toca (T089,
T100–T103, todavía sin hacer) pero no es parte de este handoff. Este documento **no edita nada del repo de
Sentinel**: lo entrega el coordinador de Elea y lo toma la sesión de Sentinel.

Eleia es la adaptación para América de la base Guardian (perfil Argentina, Ley 25.326/AAIP); Sentinel es la
línea de Europa. Todo lo de abajo está escrito **genérico** (sin cadenas de Elea/Eleia): lo que es de la línea
América (la región `AMERICAS`, `masked_all`, las reglas de habilitación vacías, el catálogo de Azure de
ejemplo) son **datos de seed** y se listan aparte (§8) para que Sentinel **no** los copie. El registro de
adaptaciones (lo que se tocó al traer sus commits) está en [`CHANGELOG.md`](./CHANGELOG.md); acá va lo que
**Elea agregó y tiene que volver**.

> **Estado honesto de la verificación.** Todo lo que sigue tiene pruebas automatizadas sin contenedores
> (proveedor simulado, motor falso). **Ninguna prueba en vivo se corrió** (T019, T045, T051, T066, T078,
> T083) y el gate con Docker (`make -C deploy check`, la suite del backend en contenedor, `docs-refs`) está
> pendiente: los resultados de esas corridas **no existen todavía** y no se inventan acá. Donde este
> documento diga «se midió», es con el analizador simulado.

---

## 1. Costuras de base nuevas o ampliadas (todas retrocompatibles)

Regla común: **sin la variable o la señal que la activa, el comportamiento es idéntico al de Sentinel `main`**
(cada una tiene su test «sin extensión ⇒ idéntico»; la batería de no-regresión de la pasarela
`backend/tests/contract/test_gw_no_regresion_057.py`, 26 casos contra un JSON grabado, pasa antes y después
de cada pick). Contrato completo: `specs/057-…/contracts/costuras-base.md`.

| Costura | Qué hace | Dónde | Prueba |
|---|---|---|---|
| **S9** extensiones extra del motor | `EXTRA_ENGINE_EXTENSIONS` (rutas): `populate_volumes.sh` y `bundle.sh` copian esos archivos al volumen de extensiones del motor y al paquete air-gapped. Vacía ⇒ volumen y paquete idénticos por hash | `deploy/release/populate_volumes.sh`, `deploy/release/bundle.sh` | `deploy/release/checks/test_extension_delivery.sh` |
| **S11** fragmentos de perfil | `PROFILE_FRAGMENTS` (rutas YAML): `render_profile.sh` fusiona cada fragmento al `config.yaml` renderizado con `deploy/release/fragment_merge.py` (`model_list` y `guardrails` se agregan al final; un `model_name` o `guardrail_name` duplicado ⇒ el render **falla**). Vacía ⇒ salida idéntica byte a byte | `deploy/release/fragment_merge.py`, `deploy/release/render_profile.sh` | idem |
| **S13** marcadores estables por conversación | Con `MASKING_NONCE_KEY` (≥ 32 caracteres) y la referencia `sentinel_conversation_ref` en la metadata interna, el sufijo del marcador es `HMAC(k, "nonce"∣empresa∣llave∣ref)[:4]` y el **índice por valor** `HMAC(HMAC(k, "idx"∣…), tipo∣valor∣probe)`: el mismo valor en la misma conversación da el mismo marcador sin importar el orden de aparición (un dato nuevo en el turno siguiente no mueve los viejos). Otra conversación, llave, empresa o clave ⇒ otro sufijo. Sin clave o sin ref, aleatorio como siempre. La gramática `[TIPO_n_xxxx]` y la restauración (SSE, chunks OpenAI) no cambian. El informe lleva `nonce_scope = "conversation"` **solo cuando rige S13** | `litellm/extensions/sentinel_guardian_policy.py:808` (`NONCE_KEY_ENV`), `:871` (`PlaceholderMap.for_conversation`), `sentinel_guardrail.py` | `backend/tests/unit/test_masking_nonce_conversacion.py` (16) |
| **S13** — quién escribe la referencia | La **pasarela** descarta `sentinel_conversation_ref` del cuerpo y de `metadata`/`litellm_metadata` **antes** de los enganches `pre_engine`; el enganche de la extensión escribe el suyo. Sin marca por tipo (a diferencia de S14) porque el valor viaja por HTTP: el motor solo lo recibe de la pasarela, su único cliente | `backend/src/api/gateway_plugins.py:118-123` | `backend/tests/unit/test_gateway_plugins.py` |
| **S14** alcance completo del enmascarado forzado (**cierra la T074 de Sentinel**) | Ver §2 | `litellm/extensions/sentinel_guardian_policy.py`, `sentinel_guardrail.py`, `sentinel_pdf_extract.py`, `backend/src/api/gateway.py:418-453`, `:1826-1844` | `backend/tests/unit/test_masking_alcance_completo.py`, `test_masking_pdf_hostil.py`, `test_masking_posiciones_exentas.py`, `test_gateway_masking_scope_057.py` |
| **S15** origen del canal interno | `INTERNAL_ALLOWED_CIDRS` (lista de CIDR o `auto`): `_require_internal_secret` exige además que el par de transporte (nunca `X-Forwarded-For`) esté en la lista. **No la implementó la 057**: la entrega el arreglo de separación de bases (vuelta 2; `${INTERNAL_ALLOWED_CIDRS-auto}` sin dos puntos, para que un vacío puesto a propósito se respete). Está en este árbol | `backend/src/api/internal.py`, `docker-compose.yml:206`, `deploy/docker/compose.prod.yml:103` | `harness/tests/test_internal_origen_wiring.py` |
| **S16** arranque de extensiones | `run_plugin_startup()` corre el `on_startup()` opcional (síncrono con `asyncio.to_thread`, o corrutina) de cada paquete de `PLUGIN_PACKAGES`, en el orden de la variable, **antes del `yield` del `_lifespan`** y después de arrancar los schedulers; un fallo se registra con el nombre del paquete y **no** tira el arranque. **El `main.py` de Sentinel tiene el mismo `lifespan`** (`sentinel:backend/src/main.py:88`, `:108`) | `backend/src/plugins.py:104`, `backend/src/main.py:102-104` | `backend/tests/unit/test_plugin_startup.py` (contra `src.main:app` con su `lifespan` real; incluye el canario de que `APIRouter(on_startup=…)` **no corre** bajo `lifespan` en FastAPI 0.111.0: por eso la costura existe) |
| **S17** caché de análisis por segmento | Ver §3 | `litellm/extensions/sentinel_guardian_policy.py:1769`, `:1856` | `backend/tests/unit/test_masking_analysis_cache.py` (24) |
| **Detector de secretos** (R37, R38) | La clave `sk-…` de `SECRET_PATTERNS` exige límite izquierdo (`(?<![a-zA-Z0-9])`): palabras como `task-implementation` o `risk-assessment` ya no son «OpenAI API Key» (el clasificador del modo auto de Claude Code las lleva en su `system` fijo y la capa rechazaba el pedido). **R38:** el cuerpo acepta también las llaves actuales `sk-proj-…`, `sk-svcacct-…` y `sk-admin-…` (llevan guiones y guiones bajos): `(?<![a-zA-Z0-9])sk-(?:[A-Za-z0-9_-]{20,}|[A-Za-z0-9]{10,})`, rama larga primero para que la redacción cubra la llave entera. El camino del backend (`GuardianService`) deja de tener su patrón propio y usa `OPENAI_KEY_PATTERN = policy.SECRET_PATTERNS["OpenAI API Key"]` (un solo criterio). Toda clave que se detectaba antes se sigue detectando (salvo la pegada a una letra o dígito anteriores, decisión de R37). **Sentinel: aplicar el mismo patrón en su `policy.py` y en su `guardian_service`** | `litellm/extensions/sentinel_guardian_policy.py` (`SECRET_PATTERNS`), `backend/src/services/guardian_service.py` (`OPENAI_KEY_PATTERN`) | `backend/tests/unit/test_secret_detection_limite_izquierdo.py` (73), `backend/tests/unit/test_secret_detection_llaves_modernas.py` (165) |
| **S2** ampliada | `GatewayContext.body` (opcional) y lectura del cuerpo de `count_tokens` solo con plugins y en POST; `ctx.model` saneado. Sin esto la T093 de Sentinel no se puede hacer | `backend/src/api/gateway_plugins.py`, `backend/src/api/gateway.py` (`_plain_passthrough`) | `backend/tests/unit/test_gateway_plugins.py` (+7) |
| **S4** ampliada | La imagen **publicada** (`Dockerfile.standalone`) migra a `heads` solo con `ALEMBIC_EXTRA_VERSION_LOCATIONS`, y el arranque **aborta** si una migración falla cuando hay ramas de extensión (sin la variable, igual que antes). Sentinel no migraba en la imagen publicada | `backend/Dockerfile.standalone:35-37`, `backend/src/main.py` | `deploy/release/checks/test_standalone_heads.sh`, `backend/tests/unit/test_arranque_migraciones_falla.py` |
| **Cifrado** (ADAPT-024) | Ya es de Sentinel (`14edbc7`); se confirma que entra tal cual | `backend/src/services/encryption_service.py` | `test_encryption_multifernet.py` |

### El cambio de auditoría del camino no-stream de `gateway.py` ⚠

`backend/src/api/gateway.py:1996-2012` (camino no-stream de `/v1/messages`, suscripción/passthrough): `_audit(...)` ahora corre
**después** de `map_response`/`map_error` y dentro de un `try/finally`. Si el enganche lanza, la fila sale igual con la
decisión que haya y estado `upstream_error`. **Sin plugins la fila es la de siempre** (test
`backend/tests/unit/test_gateway_audit_after_map_response.py`, escrito antes). Se hizo para que un plugin sume lo que lee de la
respuesta (los tokens de caché del destino) a su `routing_decision` antes de que se escriba la fila. Autorizado por el coordinador
de Elea el 2026-10-06. **Límite**: las filas del camino con llave del producto (byok) las escribe el logger de auditoría del
motor con la decisión que el guard fijó *antes* de la respuesta; ese logger **no se tocó**, así que esas filas no llevan
`cache_read_tokens`/`cache_write_tokens` (seguimiento posible: que el logger sume `usage.cache_*` a la decisión de confianza).

### S5b: el cambio de camino con `redact_enabled=false` (QA M11) ⚠

`sentinel:1a454ed` (S5b) cambia un camino: con el enmascarado apagado el guardrail llama ahora al analizador **una vez y solo
para contar** (`masked=0`); suma latencia y carga del analizador para las empresas con el enmascarado apagado, y un analizador
caído ahí **no** bloquea ni degrada (`completed=False`). Test: `backend/tests/unit/test_guardrail_redact_off_057.py`. **Sentinel
ya lo tiene si trajo S5b**; se lo avisa para que lo anote.

---

## 2. S14 — alcance completo del enmascarado forzado, con PDF y bloqueo de lo no analizable

**Qué cierra**: la T074 de Sentinel («el enmascarado forzado no cubría `system`, turnos del asistente ni adjuntos, y “lo no analizable
bloquea” no tenía tarea»). Con `masked_all` y Claude Code, el cliente reenvía el historial entero en cada pedido y los datos viven en los
`tool_result`: enmascarar solo el último mensaje del usuario no protege.

- **Señal con marca de procedencia por tipo**: `ForcedMaskingSignal` (subclase de `dict`) + `mark_forced_masking`; la del cliente (un
  `dict` plano) se descarta del cuerpo y de ambos `metadata`. Solo la escribe la pasarela (`pre_engine` de la extensión) o llega por
  `governance_overrides["masking_scope"] = "full"` en el camino de suscripción (solo ese valor). `policy.py:989`, `:993`.
- **Resolutor** del forzado: el guard de la extensión corre **después** del guardrail base y no ve el grant; la extensión registra al
  importarse `register_forced_masking_resolver(fn)` (`policy.py:1018`) con una función `fn(data, user_api_key_dict, call_type) -> bool` que
  verifica el token firmado; el guardrail base pone la marca. **Un resolutor que lanza cuenta como forzado** (falla cerrado). Se registra
  en las dos copias del módulo de política que pueden convivir en el motor (`extensions.sentinel_guardian_policy` y el plano).
- **Alcance**: `mask_body(body, analyze, pmap, *, scope="user"|"full", fmt="anthropic"|"openai", tally=, skip_keys=)`. Con `full`: `system`
  (texto y bloques; en OpenAI, turnos `system`/`developer`), todos los turnos `user` y `assistant` (`text`, valores de texto de
  `tool_use.input`, `tool_result`, `thinking`; en OpenAI `content` y `tool_calls[].function.arguments`), descripciones de herramientas y, como
  regla general **fail-closed**, **todo valor de texto** del cuerpo a cualquier profundidad, salvo la lista cerrada de posiciones de abajo.
  Claves de objeto y escalares numéricos de los subárboles libres **se analizan** (booleanos y `null`, no). Un solo recorrido (generadores)
  sirve para enmascarar e inspeccionar. `unmask_deep` restaura **claves** (`policy.py:2137`): una clave enmascarada que el modelo repite en su
  `tool_use` vuelve restaurada.
- **Posiciones exentas por ruta, nunca por nombre de clave** (QA v2 N8): tabla `S14_EXEMPT_POSITIONS` (`policy.py:1088`), cerrada, por formato:
  **opaca** (ni se analiza ni se reescribe: `model`, `…signature`, `…source.data`, `cache_control` con forma validada…), **estructural** (se
  analiza y no se reescribe: ids y nombres de herramienta, `role`, `type`, parámetros numéricos, palabras clave de JSON Schema…; **una detección ahí
  ⇒ no analizable `structural_entity` ⇒ bloqueo**, porque reescribirla rompería el pedido) y **libre** (todo lo demás). Un test compara la tabla
  con la del contrato: agregar o quitar una posición es un cambio de contrato con test. Motivo de la regla: `claude-sonnet-4-5-20250929` contiene
  un fechado que cumple el patrón de DNI de `latam_ar`.
- **PDF** (QA v2 N4): un PDF con texto se convierte a texto, se enmascara y se reemplaza por un bloque de texto, **en un proceso hijo**
  (`litellm/extensions/sentinel_pdf_extract.py`, lanzado con `python -I <ruta>`, no `-m`: con `-I` el directorio de las extensiones no está en
  `sys.path`): `RLIMIT_AS` y `RLIMIT_CPU` = plazo + 5 s **antes** de importar `pypdf`; `pypdf.Configuration` con los límites de descompresión
  bajados; entorno mínimo (sin credenciales); semáforo por proceso; plazo con *kill* de todo el grupo; caché en memoria por SHA-256 (texto o
  veredicto, jamás en disco ni registrado). `pypdf` **6.19.0** fijado con hashes en `sentinel/docker/engine-requirements.txt` (instalar con
  `pip install --require-hashes -r …`). Topes (todas opcionales; valor inválido ⇒ el de por defecto): `MASKING_PDF_MAX_PAGES` (200),
  `MASKING_PDF_MAX_BYTES` (20 MB), `MASKING_PDF_MAX_MEMORY_MB` (512), `MASKING_PDF_TIMEOUT_S` (20), `MASKING_PDF_MAX_CONCURRENCY` (2),
  `MASKING_PDF_MAX_STREAM_BYTES` (25 MB), `MASKING_PDF_MAX_TEXT_CHARS` (2 000 000), `MASKING_PDF_MAX_PER_REQUEST` (5),
  `MASKING_PDF_REQUEST_DEADLINE_S` (30), `MASKING_PDF_CACHE_ENTRIES` (32). Son del **motor**, no del backend.
- **Con la señal**: enmascarado encendido y `nlp_fail_mode = block` aunque la empresa diga otra cosa (precedencia sobre `degrade` y sobre
  `redact_enabled=false`, enmienda constitucional 2.3.0 [D15] de Elea); ningún tipo de entidad del perfil queda exento.
- **Camino de suscripción** (`backend/src/api/gateway.py:418-453`, `:1826-1844`): `evaluate_request_policy(..., masking_scope=)`. Con
  `governance_overrides["masking_scope"] = "full"` enmascara todo y **bloquea** lo no analizable: 400 con la forma de Anthropic y el texto
  del guard (`MASKING_REQUIRED_MESSAGE`, `policy.py:514`), fila `blocked_residency` atribuida a la capa `pii_masking`. Sin el override, la
  llamada es idéntica a la de siempre.
- **Vocabulario cerrado y tipos semánticos en las posiciones estructurales** (enmienda de N8, decisión del owner de Elea 2026-10-06; research R35;
  `contracts/costuras-base.md` §S14; `policy.py` `S14_CLOSED_VOCABULARY`, `S14_OPEN_IDENTIFIERS`, `STRUCTURAL_IGNORED_ENTITY_TYPES`) ⚠ **cambia el
  comportamiento de S14 con el NER real**: con el analizador real, `assistant`, `tool_use`, `Read`, `file_path` o un id `toolu_…` salen como
  PERSON/LOCATION y, como una posición estructural no se reescribe, TODO pedido con un mensaje `assistant` o con herramientas se bloqueaba
  (60 herramientas, 24 turnos: 206 `structural_entity`). Ahora, solo bajo el forzado y solo en las posiciones estructurales: **(A)** el valor de
  vocabulario cerrado del protocolo (roles, `type` de bloque, `tool_choice.type`, `thinking.type`, `source.type`/`media_type`, palabras clave y
  `type`/`format` del esquema) dentro del conjunto no se analiza (fuera del conjunto, como antes); **(B)** en los identificadores (nombres de
  herramienta, claves de esquema, ids y nombres de `tool_use`/`tool_result`) se ignoran solo los tipos semánticos (PERSON, LOCATION, ORGANIZATION,
  NRP, URL, DATE_TIME) y bloquean los de patrón y los propios de la empresa. El descarte va **antes** de resolver solapes
  (`_FullScopeMasker.identifier_entities`): si no, un PERSON que cubre `leer 30123456` tapa al DNI. Mensajes, `tool_result`, `thinking`, `system` y
  los subárboles libres no cambian. Test: `backend/tests/unit/test_masking_vocabulario_estructural.py` (incluye la instantánea de las tablas);
  **Sentinel debe correr esa suite con su analizador real**: las suites con analizador simulado no veían el problema.
  **Ampliación (research R36)**: el valor NUMÉRICO de una posición estructural (`temperature`, `top_k`, `max_tokens`, `minLength`, `maxItems`…) es
  también vocabulario abierto: `_w_scan` lo emite como `scan_open` (mismo descarte de tipos semánticos, patrón sigue bloqueando). Con el NER real la
  cadena `1` sale LOCATION y los esquemas de herramientas de Claude Code (`minLength: 1`, 14 veces) bloqueaban todo pedido. Test:
  `test_pedido_real_de_claude_code_con_numeros_de_esquema_no_se_bloquea`.
  **Ampliación (research R39)**: `reasoning_effort` (primer nivel, los dos formatos) es posición estructural de vocabulario cerrado (`none`, `minimal`,
  `low`, `medium`, `high`, `xhigh`). La cara de la pasarela lo escribe hacia un destino traducido con `thinking` u `output_config.effort` (sonnet/opus
  siempre) y el NER real marca su NOMBRE como LOCATION (0,85): sin la posición, todo pedido con esfuerzo era `structural_entity`. Si Sentinel tiene una
  cara que agrega campos de primer nivel, cada uno entra a la tabla S14 (el test `sentinel/tests/unit/test_face_claude_campos_propios_s14.py` ata los dos planos).
- **CUIT/CUIL sin guiones** en `latam_ar` (`policy.py:151`, `\b\d{2}-?\d{8}-?\d\b`): el paracaídas regex lo hereda. **Es del perfil `latam_ar`**: a
  Sentinel solo le sirve si usa ese perfil.

### Contrato del informe (`masking_report`; solo conteos y nombres de tipo)

`{completed, degraded, detected, masked, scope, unanalyzable, unanalyzable_kinds}` **siempre** (`scope = "user"` sin la señal), más:

- **`signed_thinking`** (entero, opcional): solo bajo forzado y solo si > 0; cantidad de bloques `thinking` **con `signature`** cuyo texto
  cambió al enmascarar. **No suma a `unanalyzable` ni a `unanalyzable_kinds`** (hacia un traducido la extensión reconstruye la firma). El guard
  bloquea con `masking_required` **solo si el destino es nativo** y `signed_thinking > 0` (`sentinel/engine/redirect_guard.py:121`, `:131`). **Nombre
  alineado en T108** (era el provisional `signed_thinking_detections`): si Sentinel ya usa otro, hay que unificarlo.
- `nonce_scope` (`"conversation"`), solo cuando rige S13; `exempt` (nombres), solo si hay exenciones activas.
- Bajo forzado, `detected` y `masked` son los del recorrido (por pedazo, no del preview unido): `detected == masked` solo si nada quedó sin
  reescribir; una detección en una posición estructural suma a `detected` y no a `masked`.
- Los tests de S5b (`test_guardrail_masking_report.py`, `test_guardrail_redact_off_057.py`) se ajustaron a la forma nueva.
- **El guard** (`masking_ok(report, forced=True)`, `redirect_guard.py:198`) exige `completed ∧ ¬degraded ∧ detected = masked ∧ unanalyzable = 0 ∧
  scope = "full"`; un informe sin `scope` (un guardrail anterior a S14) **bloquea** ⚠.

**Vocabulario de `unanalyzable_kinds`** (cerrado; solo nombres): `image`, `audio`, `document_url`, `document`, `unknown_block`,
`redacted_thinking`, `structural_entity`, `cache_control` (forma fuera del protocolo), `too_deep` (anidación > 100) y los de PDF: `pdf_no_text`,
`pdf_error`, `pdf_resource_limit`, `pdf_timeout`, `pdf_request_limit`, `pdf_unavailable`. **`pdf_unavailable`, `cache_control`, `too_deep`,
`unknown_block`, `document`, `document_url` y `audio` no están en `data-model.md` §5 de la 068**: Sentinel debe sumarlos a su contrato.

**Riesgos y decisiones abiertas de S14**: (a) `document` con `source.type = "text"` se enmascara como texto aunque la tabla marque `source.data`
como opaco (más estricto que el contrato); (b) el texto de inspección bajo forzado (AI-Act, secretos, preview de tipos que bloquean) mantiene el
tope `INSPECT_CAP` (16 000 caracteres) heredado; el enmascarado recorre todo; (c) **falsos positivos aceptados (fail-closed)**: con el
analizador real, un id de `tool_use`, un nombre de herramienta o un `seed` que el NER/regex lea como entidad bloquea el pedido
(`structural_entity`); **el conteo real lo hará T083, aún sin correr**.

---

## 3. S17 — caché de análisis por segmento, y las exenciones opcionales de S14 (decisión del owner de Elea, research R34)

El forzado sigue con alcance completo **por defecto**; la latencia se resuelve con una caché, no con menos protección.

- **Qué guarda**: por segmento analizado, solo `(inicio, fin, tipo, puntaje)`. **Jamás** el texto, el valor ni el marcador. Clave
  `SHA-256(versión de configuración∣idioma∣empresa∣texto)`; la versión es un hash de reconocedores, nombres y entidades propias de la empresa,
  región, URL del analizador y `MASKING_ANALYSIS_CACHE_SALT`: cualquier cambio da otra clave. No se comparte entre empresas.
- LRU por entradas + TTL, **en proceso** (se pierde al reiniciar). Variables (todas opcionales): `MASKING_ANALYSIS_CACHE_ENABLED` (`true`),
  `…_MAX_ENTRIES` (20 000), `…_TTL_S` (3 600), `…_SALT` (vacía). Una falla del analizador **no se cachea** y sube igual (fail-closed); el regex
  de respaldo de `degrade` no entra; más de 1 000 detecciones no se cachea. El enmascarado es **idéntico con y sin caché** (test).
- ⚠ **cambia**: bajo forzado el análisis previo por tipo (BLOCK vs MASK) corre **por segmento** (los mismos que recorre el enmascarado), no
  sobre el texto unido y recortado a `INSPECT_CAP`; AI-Act y secretos siguen mirando el texto unido.
- **Medición local** (analizador **simulado**, `sentinel/tests/perf/test_masking_cache_turno2.py`): conversación sintética de ≈ 93 000
  caracteres; turno 1 en frío **299 llamadas / 93 487 caracteres** (≈ 283 s modelados a 330 car/s); turno 2 con caché **8 llamadas / 2 460
  caracteres** (≈ 7,5 s); sin caché 307 / 95 947. **La cifra con el analizador real queda para T045/T083**; si el analizador no paraleliza,
  la ayuda del prefetch es nula.
- **Exenciones opcionales, apagadas** (`S14_EXEMPT_POSITIONS_OPTIONAL`, `policy.py:1163`): `MASKING_EXEMPT_SYSTEM_PROMPT` y
  `MASKING_EXEMPT_TOOL_DEFINITIONS` (`false` por defecto) suman posiciones **opacas** (`system` y turnos `system`/`developer`; `tools`/
  `functions`). Solo las enciende la instalación (un pedido no puede); el informe lleva `exempt` (nombres) y el guard lo copia a la decisión
  (`masking_exempt`). Secretos y AI-Act siguen mirando todo. Trade-off: con la caché, la exención solo ahorra el **primer** análisis de cada
  texto.
- `.env.example`: estas variables están **comentadas** (ver §7).

---

## 4. Lo que la cara Claude trae de las tareas de Sentinel que quedaron sin hacer

El contrato de la cara Claude de la 068 rige tal cual; Elea **hizo** lo que Sentinel no (ids de tarea **de Sentinel**; sus tests viajan):

| Tarea de Sentinel | Qué | Dónde |
|---|---|---|
| **T139** | Lista permitida de campos de primer nivel hacia traducidos (`FIELD_ALLOWLIST`, `dropped_field_names`); `dropped_fields` acotado a 128 caracteres en la decisión. Hacia nativo no se filtra. Motivo: «Unrecognized request argument supplied: safeguards» | `sentinel/redirect/faces/claude.py:174`, `:304` |
| **T094** | `redirect/betas.py`: lista de betas como **dato** (`REDIRECT_BETA_ALLOWLIST`: en blanco = default acotado, `none` = ninguna); `_apply_betas` en `pre_engine` decide con el destino final (nativo: las de la lista; traducido: todas descartadas, `betas_dropped`); `_subscription_foreign` (401 `authentication_error` neutro de una credencial de suscripción hacia otro proveedor, FR-042). La edición desde el panel quedó fuera | `sentinel/redirect/betas.py`, `sentinel/redirect/plugin.py` |
| **T093** | `redirect/token_estimate.py` (`cl100k_base` solo con vocabulario en disco y hash verificado; si no, `caracteres/4`; **nunca red**) y `_count_tokens`: traducido o forzado ⇒ estimado o 404; nativo sin forzado ⇒ reenvío con el id `rdx-*`. El conteo escribe su propia fila (la pasarela no audita respuestas tempranas de `count_tokens`) con `count_tokens_mode` | `sentinel/redirect/token_estimate.py:27-60`, `sentinel/redirect/plugin.py:464` |
| **T090** | `redirect/thinking.py`: firma HMAC atada al **destino** y al texto (clave derivada de la de la autorización con otro dominio), `ThinkingSigner` en el stream, firma en el no-stream, reconstrucción en el turno siguiente solo para el destino que lo exige (`provider_options.reasoning_replay` o proveedor `deepseek`) y descarte sin rastros del resto. **Precisión sobre D7 de la 068**: ahí la firma era «sobre el texto»; atarla al destino evita que el razonamiento de un destino llegue a otro | `sentinel/redirect/thinking.py:50` |
| **T091** | `stream.py`: `usage` con los cuatro contadores en `message_start` (y `message_delta` sin ceros que pisen al inicio: el SDK acumula), falla del destino o `event: error` ajeno ⇒ `event: error` neutro y cierre **sin** `message_stop`. ⚠ cambia un test heredado: la falla a mitad del stream ya no propaga en la cara Claude (sí en la genérica) | `sentinel/redirect/stream.py:206` |
| **US1 esc. 4, FR-015, FR-018** | Un id `claude-*` no publicado cae a la regla por tier inferido de su nombre (`infer_tier`), solo con política `on` y llave del producto; sin regla ⇒ 404 neutro. Estaba en el `data-model` de Sentinel (`family_tier`) pero no en el plugin | `sentinel/redirect/faces/claude.py` |
| **FR-035** | Herramientas del servidor del proveedor original (`web_search*`, `web_fetch*`, `code_execution*`) hacia un traducido ⇒ 400 `capability_rejected: …`, nunca ignoradas | `sentinel/redirect/faces/claude.py` |
| **T126/T131/T132** (caché) | S13 (§1) + `redirect/session_ids.py`: `conv = HMAC(k, "conv"∣empresa∣sesión)` y `affinity = HMAC(k, "affinity"∣empresa∣sesión∣agente)`; sesión = `x-claude-code-session-id` o `…_session_<id>` del `user_id` de `metadata`; **el identificador original de la sesión nunca llega al motor ni al destino**. La afinidad va **firmada** en la autorización (`Grant.affinity`) y solo si el destino declara `session_affinity` (OpenRouter por defecto); el guard la manda como `session_id` en el cuerpo de OpenRouter y como `x-session-id` en los demás; el que manda el cliente se descarta | `sentinel/redirect/session_ids.py:42-65`, `sentinel/engine/redirect_guard.py:350` |
| **T127–T135** (caché) | Marcas `cache_control` conservadas cuando el destino las declara (y la marca de un bloque reemplazado por una nota pasa a la nota); precio de caché `cache_read_per_mtok`/`cache_write_per_mtok` (`cost_params` fija `cache_read_input_token_cost` y `cache_creation_input_token_cost`, los nombres que honra `completion_cost`: test con la versión instalada) con `price_per_mtok` como **única** conversión; `price_cache_missing`; tokens de caché en la auditoría (Claude, chat OpenAI/OpenRouter y Responses) y `costs.compare` con `cache_hit_rate`; casillas del panel | `sentinel/engine/redirect_credentials.py:107-140`, `sentinel/redirect/costs.py:118`, `sentinel/frontend/redirect/DestinationsTab.tsx` |
| **F1** (069 de Sentinel) | `c974dc5` y `6ca0419` entraron por `cherry-pick -x`; no hay nada que devolver | — |

**Defecto latente corregido**: `_select_by_capability` reasignaba `plan.decision` tras una sustitución por capacidad y la auditoría de la
pasarela dejaba de ver `omitted`, `dropped_fields`, etc. (ahora actualiza en el lugar).

---

## 5. Región como dato, residencia y habilitación — [BASE] (cambian el comportamiento de Sentinel ⚠)

Migración nueva y tablas en §6. Reemplaza como fuente de verdad a `_ZONES`/`_REGION_PREFIX`/`region_codes` fijos (que quedan como respaldo).

- **Región como dato** (`sentinel/redirect/residency.py:52` `region_codes`, `:109` `resolve_profile`, `:151` `resolve_region`, `:296`
  `effective_posture`, `:365` `evaluate`): `sentinel_redirect_region` con `jurisdictions`, `region_profiles`, `is_zone` y **`default_posture`** (cuatro
  valores: `reject_offregion` —**valor de fábrica, paridad con Sentinel**—, `masked_offregion`, `masked_all` = `offregion_masked` con casa vacía, y
  `allow`). Resolución: empresa > instalación > respaldo fijo.
- **Piso de enmascarado**: el forzado que impone `default_posture` (`masked_all`/`masked_offregion`) **se mantiene** aunque las filas no lo pidan; solo lo
  quita una **relajación** o un cambio de `default_posture`. Postura efectiva en dos niveles: las filas de `compliance_officer`/`super_admin` son la
  base; las del `tenant_admin` **solo restringen** (una `off` suya no tiene efecto; una `allowlist` suya interseca; la API rechaza con 422
  `posture_less_strict` una fila menos estricta que la efectiva).
- **Respaldo en código** (QA B2): pedido redirigido sin fila de región ⇒ `offregion_masked` con casa vacía (forzado y fail-closed en todo destino) **y** alcance
  limitado a `region_codes(región)`; región sin resolver ⇒ 403 `region_not_allowed` a todo lo redirigido. `default_posture_applied = code_fallback` en la
  auditoría y `GET /api/v1/redirect/health` responde 503 `region_row_missing` / `region_unresolved` (sin sesión, sin datos de empresas). Mientras rige, ninguna
  postura de ningún rol quita el forzado ni amplía el alcance, y las relajaciones no tienen efecto.
  - ⚠ **cambia**: sin fila de región, el redirigido sale forzado y limitado a `region_codes` (antes: `allowlist[región]` sin forzado).
    **Sentinel debe sembrar su fila `reject_offregion`** (con `regions_seed`) **para conservar el comportamiento sin fila**: la nota que su equipo tiene que
    leer antes de adoptar esto es «sembrá tu fila `reject_offregion` para conservar el comportamiento previo».
- ⚠ **`tenant_region` único, sin caída a `eu`** (QA v2 N5): `tenant_region`, `list_postures` y `run_fidelity` usan **una sola función**,
  `residency.resolve_profile`; sin valor en la identidad ni en `SENTINEL_ENTITY_REGION` la región queda **sin resolver** (el catálogo ya resolvía «sin variable ⇒
  ninguna»; la pasarela cae a `eu`: dos resoluciones distintas de lo mismo). **Ojo**: `docker-compose.yml:139`, `:262` y `deploy/docker/compose.prod.yml:127`, `:220`
  fijan `${SENTINEL_ENTITY_REGION:-eu}`: sin pasarla por el entorno, el perfil resuelve a `eu` y, si no hay fila `eu`, `region_row_missing`.
- ⚠ **Un destino sin jurisdicción de inferencia se rechaza con cualquier postura, fila o relajación** (antes, `off` lo dejaba pasar).
- **`control_jurisdiction` y la regla «en región»** (D12): columna nueva en la ficha (`ext_compliance_sheet`); `provider_legal_entity` se muestra como «Entidad
  responsable». Un destino está en una región solo si la jurisdicción de **inferencia**, la de la **entidad** y la de **control** la satisfacen.
  ⚠ **Cambio para Sentinel**: una ficha **sin control cargado deja de contar como en región** (bajo `allowlist` se trata como entidad ajena, `foreign_entity`;
  bajo `offregion_masked`, como fuera de región ⇒ forzado). El **semáforo** del catálogo usa la misma regla y se evalúa **contra la región del perfil**, no contra una
  regla fija «admisible UE» (el valor interno `eu_ok` se conserva; la etiqueta es «Dentro de <región>», nunca «Admisible»). `sentinel/catalog/region.py`,
  `sentinel/catalog/semaforo.py`.
- **Relajaciones del enmascarado forzado** (D5, FR-031a): **por región** (cambiar `default_posture` de `masked_all` a `masked_offregion`: el super-admin sobre la
  fila de instalación, o cumplimiento con una fila de nivel empresa que gana para su empresa) o **por destino** (`sentinel_redirect_masking_relaxation`, una vigente por
  destino, baja con historial). La relajación por destino exige jurisdicciones de inferencia, entidad **y** control cargadas, `zero_data_retention = true` y, en
  un agregador, una lista de proveedores no vacía (422 con el motivo si no); **nunca hay relajaciones sembradas**. **H2**: se revoca sola
  (`revoke_reason = precondicion_incumplida`) si la ficha deja de cumplir, o si cambian `provider`, `api_base`, `real_model`, `is_aggregator` o la lista de
  proveedores, o al archivar (`sentinel/catalog/relaxation.py`). Ninguna relajación habilita un destino sin jurisdicción de inferencia ni vuelve alcanzable
  un destino fuera de una `allowlist`.
- **Habilitación explícita por datos** (D1, FR-029): `ext_catalog_enablement_rule` (`kind` = `provider` · `api_host` · `jurisdiction`; `jurisdiction` compara inferencia,
  entidad y control) **reemplaza** el `provider == "deepseek"` fijo de `catalog/api/admin.py`, `catalog/seed.py` y `catalog/api/legacy.py`; cargador idempotente
  `python -m sentinel.catalog.habilitacion <archivo>`. La paridad con Sentinel es el seed `provider: deepseek`. Las reglas de una empresa solo aplican a las entradas de esa
  empresa y solo **agregan**. Habilitar no relaja la residencia. `catalog/migrate.py` (migración única de la 068) copia `api_base` sin validar (H1 no la cubre).
- **H1–H3 (QA del tramo T-B)**:
  - **H1** — `api_base` de las entradas de **empresa**: https y hosts públicos (los metadatos de nube y los esquemas que no son http(s) se rechazan siempre);
    `CATALOG_ALLOW_PRIVATE_API_BASE` (apagada) permite http o red interna para modelos locales de una instalación de **una** empresa. `sentinel/catalog/api_base.py`.
  - **H2** — la relajación por destino se revoca al cambiar el destino (arriba).
  - **H3** — el interino de T-B no era el default de D2 (sin postura regía `allowlist` sin forzado y la región caía a `eu`): lo cierra el piso, el respaldo en código
    y `tenant_region` único (arriba). **Esto es lo que más cambia en Sentinel.**
- **OpenRouter con cero retención** (R19, FR-032): todo pedido a un destino `openrouter` sale con `zdr`, `data_collection = deny` y `only` = la lista de proveedores
  permitidos **firmada en la autorización**; el `provider` del cliente se descarta (`provider` en `CLIENT_CREDENTIAL_FIELDS`); sin lista ⇒ 503 `destination_misconfigured`;
  `openrouter_zdr` en la auditoría. Alta o PATCH de `openrouter` sin `providers_allowlist` ⇒ 422; `zdr`/`data_collection` en contra ⇒ 422. `Grant.provider_options` firmado.
- **Verificación de despliegue de Azure** (R9, FR-020): credencial **adoptada** (referencia `env:AZURE_API_KEY` de la instalación, fuera de la lista negra, más `api_version`, sin
  duplicar el secreto). Al dar de alta o editar una entrada `azure` se verifica que `real_model` sea un despliegue del recurso (prueba de 16 tokens por la ruta del guard,
  inyectable); sin despliegue queda `inactive` con «El despliegue <x> no existe en el recurso configurado» y `POST /entries/{id}/check` lo re-verifica
  (`validation.classify_deployment_response`). **La prueba real contra el motor no se corrió** (T045/gate).
- **Roles**: las escrituras de regiones, `default_posture` y relajaciones exigen el **rol real** `compliance_officer` o `super_admin`: la autoridad de instalación derivada
  de `REDIRECT_OPERATOR_TENANT` (`sentinel/redirect/api/admin.py:83-100`) **no** alcanza para esas tres cosas (sí sigue valiendo para filas de postura) y Eleia **no define** esa
  variable. Los cinco campos de residencia y retención de la ficha (`provider_legal_entity`, `entity_jurisdiction`, `control_jurisdiction`, `inference_jurisdiction`,
  `zero_data_retention`) los escribe solo cumplimiento o super-admin (el admin de empresa recibe 403 si el cuerpo cambia alguno; repetir el valor no cuenta). Esa garantía
  se apoya en **otro** arreglo ya entregado: crear o asignar `compliance_officer`/`super_admin` solo lo hace un `super_admin`
  (`backend/src/auth/rbac.py:37-48`; ver `specs/HANDOFF-elea-a-sentinel-alta-roles-cumplimiento.md`).
- **Canal interno** (QA A10, FR-013): `/internal/model-credential` queda **cerrada sin la ruta directa**: la credencial descifrada solo sale por HTTP con
  `CATALOG_DIRECT_ENABLED` encendida (vacía en Eleia); sin ella, 404 aunque el secreto sea el correcto. La llamada en proceso del chat de la consola sigue
  funcionando. Las tres rutas de la extensión dependen de la **misma** `_require_internal_secret` de la base. Test `test_internal_model_credential_gate.py`.
- **`MASKING_NONCE_KEY` en `ENV_DENYLIST`** (`sentinel/engine/redirect_credentials.py:81`, y el fragmento `NONCE_KEY`): no se puede referenciar como credencial de un
  modelo. El release la genera distinta por instalación (`deploy/release/gen_secrets.sh:46`, `rand_hex 32`); `test_no_default_secrets.sh` exige que ningún artefacto
  versionado la traiga con valor literal o `${…:-valor}` y que el que activa la extensión (`GATEWAY_PLUGINS`) la declare.
- **Guard y orden de guardrails** (QA A3): `rdx-*` sin autorización ⇒ 403 en todo `call_type`; en el config fusionado `redirect-guard` corre **después** de `sentinel-guardian`;
  `metadata.masking_report`, `guardrails` y `disable_global_guardrails` del cliente no relajan el forzado (el guard solo lee el informe que escribe el guardrail de la base).
- **Panel**: Residencia con postura por defecto, relajaciones y pre-completado; etiqueta «Dentro de <región>»; el texto de `EntryForm` ya no nombra a Sentinel (H7).
  ⚠ **No se portan** las costuras de la consola (`access_hook`, `model_route_hook`, `residency_heuristic`: ADAPT-027/028 de Sentinel): en Eleia los perfiles de acceso rigen en la
  pasarela y no en el chat de la consola (CHANGELOG §2, QA H4). **Es una diferencia entre las bases**, no algo para portar.

---

## 6. La migración nueva y su id

| Qué | Valor |
|---|---|
| Revisión | **`89a92524eef6`** (`sentinel/migrations/89a92524eef6_redirect_region_y_habilitacion.py`), generada con `alembic revision` (id por hash) |
| Rama | `sentinel_redirect`, colgada de **`f7a3c1d9e508`** (la última de la 069) |
| Cadena resultante | backend (una sola cabeza, sin cambios): `… → 7a6fee614cfd → 199fe429762a`; extensión: `0615e56e8251 → … → f7a3c1d9e508 → 89a92524eef6`. Sin `ALEMBIC_EXTRA_VERSION_LOCATIONS`: `heads = ['199fe429762a']`; con la variable: dos cabezas y `upgrade heads` (S4) |
| Tablas | `sentinel_redirect_region` (con `default_posture`), `ext_catalog_enablement_rule`, `sentinel_redirect_masking_relaxation` (una vigente por destino, baja con historial) y la columna `control_jurisdiction` en la ficha |
| RLS | Filas de instalación legibles por toda empresa, escritura con *bypass*. **H9 (info)**: las tres tablas heredan la política RLS permisiva `tenant_isolation_bootstrap` de la base (`…:57-65`); 🟡 hasta la suite con Docker |
| Garantías | Ninguna migración de la extensión crea, altera ni borra tablas `LiteLLM_*` ni `_prisma_migrations`; sus FKs apuntan solo a `tenants`, `groups` y tablas propias (test `sentinel/tests/integration/test_migraciones_cadena_base.py`) |
| Cargadores | `python -m sentinel.redirect.regions_seed <archivo>` (todo o nada; crea y **no pisa** lo que un administrador cambió) y `sentinel/redirect/seed_on_startup.py` (`REDIRECT_SEED_FILES`, cerrojo consultivo de Postgres, un archivo inválido no frena a los demás), expuesto como `on_startup()` de `sentinel.redirect.api` y llamado por S16 |

**El riesgo de la base compartida**: la base del motor y la del producto pueden vivir en el mismo Postgres. El migrador del motor compara la base a la que apunta con su esquema y
**elimina toda tabla ajena** como «deriva» (reproducido en ensayo; `specs/ANALISIS-SEPARAR-BASES-MOTOR-2026-10.md`). Por eso: (a) **nunca** arrancar una base nueva con el backend antes
que el motor; (b) no cambiar la versión ni el digest base del motor (la variante `-ext` deriva de él); (c) `DISABLE_SCHEMA_UPDATE=true` en el motor es una **hipótesis sin ensayar**
(spike D14, T019, sin correr): no se usa; (d) respaldo de las dos bases antes de aplicar las migraciones, porque **volver a una versión sin la extensión después de aplicarlas no
está soportado** (FR-004b). Ninguna migración de la extensión toca `_prisma_migrations` (T102 lo verifica con Docker, sin correr).

---

## 7. Entrega y configuración

- **`sentinel/docker/compose.dev.yml`** (T021): override opcional con `-f`; monta `./sentinel` como paquete en el backend (`PYTHONPATH=/opt/sentinel-ext`), los seeds
  de `deploy/redirect-seeds` en `/opt/sentinel-ext/seeds` y, en el motor, los `redirect_*.py` junto a las extensiones de la base y el `config.yaml` fusionado (los genera
  `sentinel/docker/prepare-dev.sh`). **Nada se activa por estar montado**: la extensión se enciende con `GATEWAY_PLUGINS`/`PLUGIN_PACKAGES`. Sin secretos ni `DISABLE_SCHEMA_UPDATE`;
  `INTERNAL_ALLOWED_CIDRS` no va acá (la fija el compose base). Plantilla de entorno sin secretos: `sentinel/extensions.env.example`.
- **Imágenes `-ext`** (T091, QA B1): Dockerfiles derivados de `BASE_IMAGE` para backend, panel y motor (`sentinel/docker/{backend,frontend,engine}.Dockerfile`, contexto =
  raíz del repo); **el `engine.Dockerfile` derivado** deriva del **mismo digest** de la imagen publicada del motor y solo agrega los archivos de la extensión y `pypdf`
  (`engine-requirements.txt`, con hashes). Tag propio `<versión>-ext`, **jamás mueven `latest`**; `deploy/release/publish-elea.sh` las construye después de las base, con `DRY_RUN`.
  Test sin Docker: `deploy/release/checks/test_ext_images.sh`.
- **Variables** (resumen; ver `sentinel/extensions.env.example`): `GATEWAY_PLUGINS`, `PLUGIN_PACKAGES`, `ALEMBIC_EXTRA_VERSION_LOCATIONS`, `REDIRECT_INTERNAL_KEY` (≥ 32),
  `MASKING_NONCE_KEY` (≥ 32, backend **y** motor), `SENTINEL_ENTITY_REGION`, `REDIRECT_SEED_FILES`, `REDIRECT_CRED_<NOMBRE>`, `REDIRECT_CACHE_TTL_S`,
  `REDIRECT_FIDELITY_BUDGET_USD`, `REDIRECT_GATEWAY_URL`, `REDIRECT_BETA_ALLOWLIST`, `CATALOG_ALLOW_PRIVATE_API_BASE`, `FERNET_PREVIOUS_KEYS`. **No definir `REDIRECT_OPERATOR_TENANT`** en
  una instalación que quiera la garantía de «el admin de empresa no relaja».
- **`.env.example`**: `FERNET_PREVIOUS_KEYS`, `GATEWAY_PLUGINS`, `PLUGIN_PACKAGES` (con la nota de `on_startup()`) e `INTERNAL_ALLOWED_CIDRS` están declaradas; `MASKING_PDF_*`,
  `MASKING_NONCE_KEY`, `MASKING_ANALYSIS_CACHE_*` y `MASKING_EXEMPT_*` están **comentadas** a propósito: una variable real que solo lee el motor en Python (que `docs/tools/drift_gate.py` no
  escanea) hace fallar el gate de deriva («declarada y ningún plano la consume»). Cuando el instalador las pase por el compose se descomentan y se regenera la referencia
  (`make -C deploy docs-refs`).
- **Documentación de producto**: la 057 agregó `administration/redireccionamiento.md`, las tres guías de integración y §7 de operaciones, todas **genéricas y marca-neutras**; Sentinel puede
  tomarlas cambiando solo el marco normativo (en Europa rigen GDPR y EU AI Act; acá no).

---

## 8. Lo que es de la línea América y Sentinel **no** debe copiar

Son **datos** o textos del perfil, no código de base:

| Dato | Archivo | Nota |
|---|---|---|
| Región `AMERICAS` con `default_posture: masked_all` | `deploy/redirect-seeds/regions.americas.yaml` | Sentinel siembra su propia región (p. ej. la lista de países de Europa) con `reject_offregion` si quiere paridad |
| Reglas de habilitación **vacías** | `deploy/redirect-seeds/habilitacion-explicita.yaml` | Sentinel conserva `provider: deepseek` |
| Catálogo de ejemplo de Azure | `deploy/redirect-seeds/catalog-seed.azure-demo.yaml` | Con jurisdicciones de entidad y control **vacías y obligatorias** |
| Perfil `latam_ar` y el patrón CUIT/CUIL | `policy.py:151`, `:233` | Solo si Sentinel tiene clientes de ese perfil |
| Marco normativo (Ley 25.326/AAIP) en la documentación | `docs/docs/compliance/**` | En Sentinel rigen GDPR y EU AI Act |

La constitución de Elea quedó en **2.3.0** (D13 403 `permission_error` para rechazos de residencia, D14 nombres de proveedor solo como datos del administrador o literales del protocolo, D15
default de residencia por región y precedencia del forzado sobre `degrade` y `redact_enabled=false`); **Sentinel ya tiene sus propias 2.3.0 y 2.4.0**: las numeraciones divergen (aviso en el
Sync Impact Report). La 2.4.0 de Sentinel ya enmendó el 403.

---

## 9. Resultado de la primera prueba en vivo de la cara genérica

**Pendiente: no hay resultado.** T051 (opencode y Aider en modo estándar contra Azure, SC-014) **no se corrió** (requiere Docker y aviso previo al owner de Elea). Lo que sí hay son cuatro
pruebas automatizadas con el guard real y un destino simulado (`sentinel/tests/contract/test_face_generic_eleia.py`, `integration/test_face_generic_e2e_eleia.py`,
`integration/test_face_generic_restauracion.py`, `backend/tests/contract/test_gateway_openai_policy_off_057.py`), que **nacieron en verde**: `faces/generic.py` no necesitó ajustes. Cuando T051 se corra,
el resultado va a `specs/057-…/verificacion-cara-generica.md` y este handoff se enmienda. Igual para T045 (cara Claude), T066/T078 (caché), T083 (quickstart completo, incluida la medición de SC-003 y los
falsos positivos del enmascarado por tipo, A4 — **el sobre-enmascarado de Claude Desktop, T184 de la 069 de Sentinel, sigue abierto**: con `masked_all` todo el tráfico se enmascara y la tasa real de
falsos positivos no está medida).

---

### Piso de `api_version` de Azure solo para Responses — [BASE] (oct-2026)

El puente a Responses (T193, `bridge_to_responses`) escribe `rdx-<fam>/responses/<m>` ANTES de que se escriba la credencial, así que
la `api_version` de la credencial Azure (p. ej. `2024-10-21`) viajaba también a Responses. Responses nace en `2025-03-01-preview` y
`2025-04-01-preview` suma el resumen de razonamiento (changelog de Microsoft, *api-version-lifecycle*; hoy Microsoft documenta la API v1
sin `api-version` para lo nuevo). Qué portar, todo retrocompatible:

- `sentinel/engine/redirect_guard.py`: `AZURE_RESPONSES_MIN_API_VERSION`, `raise_responses_api_version(data, provider, call_type)` — solo `azure`,
  solo si el modelo ya es `/responses/` o la cara es `responses`/`aresponses`, y solo si la versión es una fecha anterior al piso (`v1`, `latest`,
  vacío no se tocan). Se llama **después** de `data.update(to_litellm_params(...))` en `apply_redirect`; chat/completions conserva la de la credencial.
  Auditoría: el nombre `api_version` en `adjusted_params`, nunca un valor.
- `sentinel/engine/redirect_catalog.py`: la misma llamada, tras `data.update(params)` en la ruta directa del catálogo.
- `sentinel/frontend/catalog/{helpers.ts,ui.tsx}`: `apiVersionBelowResponsesFloor` y el aviso (`role="status"`, no bloquea) en `SecretFields`,
  que usan las tres entradas de credencial (Credenciales, ficha, alta guiada).
- Tests: `sentinel/tests/unit/test_guard_azure_responses_api_version.py`, `sentinel/frontend/catalog/__tests__/azure.apiVersion.test.tsx`.
- Doc: una línea en `administration/redireccionamiento.md` y una fila en `integrations/claude-desktop.md` (🟡: sin prueba en vivo contra Azure).

## 10. Cómo verificar después de portar

Con el venv del backend, sin Docker:

```bash
# base: costuras y masking (S2, S4, S13, S14, S16, S17, informe)
PYTHONPATH=.:backend pytest backend/tests/unit/test_gateway_plugins.py backend/tests/unit/test_plugin_startup.py \
  backend/tests/unit/test_alembic_extra_versions.py backend/tests/unit/test_arranque_migraciones_falla.py \
  backend/tests/unit/test_masking_alcance_completo.py backend/tests/unit/test_masking_pdf_hostil.py \
  backend/tests/unit/test_masking_posiciones_exentas.py backend/tests/unit/test_masking_nonce_conversacion.py \
  backend/tests/unit/test_masking_analysis_cache.py backend/tests/unit/test_masking_exencion_opcional.py \
  backend/tests/unit/test_guardrail_masking_report.py backend/tests/unit/test_guardrail_redact_off_057.py \
  backend/tests/unit/test_gateway_audit_after_map_response.py backend/tests/unit/test_gateway_masking_scope_057.py -q -rs
# no-regresión de la pasarela (debe pasar sin ninguna variable de la extensión)
PYTHONPATH=.:backend pytest backend/tests/contract/test_gw_no_regresion_057.py -q
# extensión
PYTHONPATH=.:backend LITELLM_MODE=PRODUCTION pytest sentinel/tests -q -rs
# checks sin Docker del release
for t in test_extension_delivery test_ext_images test_standalone_heads test_no_default_secrets test_entity_region_default; do
  bash deploy/release/checks/$t.sh; done
```

Verificar **por mutación** (lo hizo la 053): sacar el `scope == "full"` de `masking_ok` o la marca de procedencia por tipo de S14 y confirmar que los tests nuevos fallan. Con `pypdf` instalado
(`pip install --require-hashes -r sentinel/docker/engine-requirements.txt`) y **0 saltados** entre los críticos (T105/T106). Lo que **no** se corrió y corresponde a Sentinel cuando lo adopte:
la suite del backend en contenedor, `make -C deploy check`, las migraciones de la base y de la extensión por `upgrade heads` con una base real, la RLS real y la corrida con dos workers.

---

## 11. Pendientes que este handoff NO cierra

- **T-H** (instalador): activación opt-in (`ELEA_REDIRECT=1`), proxy del canal interno y su gate (T089, T100–T103). La documentación los marca 🔵.
- **Verificación en vivo** (🐳, aviso previo al owner de Elea): T019 (spike D14 del motor fijado), T045, T051, T066, T078, T083, T102; y el gate final (T082, T086).
- **Tokens de caché en las filas byok**: el logger de auditoría del motor sigue sin sumarlos (§1).
- **Afinidad de sesión y marcas de caché por proveedor**: el efecto real sobre los aciertos (SC-011: ≥ 60 % desde el 2.º paso; SC-012) **no se midió**; solo el mecanismo está probado.
- **Latencia del forzado completo con el analizador real** (§2, §3): la cifra existe solo con el analizador simulado.
- **Codex CLI**: sin camino gobernado (el producto no expone «Responses»); la pestaña «Kits» de la extensión **igual** genera un kit con ese nombre (`sentinel/redirect/kits.py`, `_codex`).
  Sentinel debería decidir si lo oculta mientras no haya superficie.
- **`catalog/migrate.py`** copia `api_base` sin validar (H1).
- **Idioma/jurisdicción**: ningún código nombra un país de preocupación (FR-020, FR-028a): son datos (reglas de habilitación por `jurisdiction`).
