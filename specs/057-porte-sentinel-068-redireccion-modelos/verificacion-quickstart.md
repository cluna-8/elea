# Verificación en vivo del quickstart (T083) — parte 1: vocabulario estructural con el NER real

**Estado de T083: abierta.** Este documento registra solo la parte del gate que cerró la enmienda de N8
(research R35 y R36; `contracts/costuras-base.md` §S14 «Vocabulario cerrado y tipos semánticos»; T114–T116) y el falso positivo del detector de secretos que apareció en la misma corrida (research R37; T117). La corrida completa del
quickstart (SC-003, SC-004, SC-009 con la postura por defecto, falsos positivos A4/A9) sigue pendiente.

Fecha: 2026-10-06. Sin credenciales ni contenido en este archivo; la llave de prueba se lee de un archivo local (modo 600) y nunca se imprime.

## 1. Antes (motor con la política anterior, medición del worker previo del gate)

Pedido sintético de Claude Code (60 herramientas, 24 turnos de `tool_use`/`tool_result`, `system` grande, un DNI en el primer mensaje;
≈ 100 000 caracteres de texto, 125 KB) a `POST /api/v1/gw/v1/messages?beta=true`, `claude-sonnet-5-5`, stream:

| Pedido | HTTP | Resultado |
|---|---|---|
| turno 1 en frío (24 turnos) | **400** | «El pedido no pudo protegerse para este destino y fue bloqueado» (`structural_entity`; 206 detecciones con el NER real) |
| turno 2 (26 turnos), y repetido | **400** | ídem |

## 2. Qué se reconstruyó y recreó (Docker, con OK del owner)

- Imagen del motor `ghcr.io/cluna-8/elea-guardian-engine:057-gate-ext`, reconstruida con el código de `3d327c4`: la base `057-gate` traía la
  política vieja, así que se construyó antes `litellm/` como tag temporal `…:057-gate-new-base` (`litellm/Dockerfile`) y sobre ella
  `sentinel/docker/engine.Dockerfile` (`pypdf 6.19.0`, 4 `redirect_*.py`, `identifier_entities` presente en `/app/extensions/sentinel_guardian_policy.py`).
- Contenedor `elea057-engine` recreado con `--no-deps engine` (`-p elea057`, `STACK_PREFIX=elea057`), los mismos `--env-file` y
  `-f docker-compose.yml -f sentinel/docker/compose.dev.yml` más un override fuera del repo que fija la imagen `-ext` y quita los bind mounts de
  `sentinel/docker/.dev/` (el de `config.yaml` era un **directorio** vacío creado por Docker: el motor estaba en crash-loop con
  `IsADirectoryError: '/app/config.yaml'`, y el de `extensions` no tenía la política). Config y extensiones salen ahora de la imagen. Mismo
  `environment`/`env_file`. Resultado: `healthy`. El frontend (`sentinel-frontend`) no se tocó.
- Primer intento sin `STACK_PREFIX`: Compose creó `sentinel-engine`; se recreó enseguida con el prefijo correcto (queda un solo motor).

## 3. Después (misma ruta, mismo pedido, mismo script)

| Pedido | HTTP | Tiempo | DNI en la respuesta |
|---|---|---|---|
| turno 1 en frío, 24 turnos, 60 herramientas, stream | **200** | 27,3 s | no |
| turno 2 (26 turnos) | **200** | 2,2 s (caché de análisis, S17) | no |
| turno 2 repetido | **200** | 2,1 s | no |
| sin stream, 24 turnos, 60 herramientas | **200** | 3,5 s | no |

El pedido llegó a Azure (`gpt-5.1-chat`, `200 OK` en el log del motor); el cuerpo que salió es el enmascarado.

**Auditoría del pedido sin stream** (`audit_logs`, solo metadatos): `compliance_status = passed`, `pii_detected = true`,
`masked_entities = [PERSON ×5, DNI ×2, URL ×24, LOCATION ×1, DATE_TIME ×1]`, `blocked_by_layer` vacío. **El DNI del mensaje sale enmascarado**
(los tipos semánticos se siguen enmascarando en el texto; solo dejaron de bloquear en las posiciones estructurales).

## 4. Controles en vivo (no stream, `max_tokens: 32`)

| Pedido | HTTP |
|---|---|
| `user` / `assistant` / `user` | **200** (antes bloqueaba: `assistant` como PERSON) |
| DNI en el nombre de una herramienta (`tools[0].name = "leer 30123456"`) | **400** protegido (bloquea) |
| DNI como clave de `properties` del esquema | **400** (bloquea) |
| email como nombre de herramienta | **400** (bloquea) |

## 5. Hallazgo aparte: `IndexError` en el stream hacia Azure — arreglado (2026-10-06)

**Causa (verificada en el motor, LiteLLM 1.92.0).** `/v1/messages` hacia un destino traducido fija `stream_options.include_usage`
(`adapters/handler.py:474`). Con eso el stream de LiteLLM devuelve los chunks sin `choices` (`streaming_handler.py`, rama
`include_usage` → `model_response.choices = []`) y Azure manda uno al inicio (anotaciones del filtro de contenido) y otro con el `usage`
al final. El adaptador de Anthropic lee `chunk.choices[0]` (`adapters/streaming_iterator.py:611` y `:856`): `IndexError`, 200 con la respuesta
cortada (≈ 2,6 KB) y sin fila de auditoría del pedido en stream (la fila se escribe al cerrar el stream). Los chunks con `usage` y
`choices` vacío no llegan al adaptador (el stream les quita el `usage` y descarta los vacíos), así que lo único que se pierde al
filtrar es lo que el adaptador no puede traducir.

**Arreglo (nuestro código, motor sin tocar).** `sentinel/engine/redirect_guard.py`: `install_empty_choices_filter()` envuelve
`AnthropicAdapter.translate_completion_output_params_streaming` y le pasa el stream sin los chunks de `choices` vacío (sync y async;
idempotente; devuelve `False` si el motor no tiene ese adaptador). Lo instala el constructor de `RedirectGuard`. Es el punto equivalente al
pedido: los hooks de stream por chunk de LiteLLM (`async_post_call_streaming_deployment_hook`) solo corren en el chunk final, y el hook de
iterador ya recibe bytes SSE. Test rojo primero: `sentinel/tests/unit/test_guard_stream_choices_vacios.py` (8 casos; el que reproduce el
`IndexError` con un stream estilo Azure `choices=[]` al inicio y al final por el adaptador falso con el contrato del real).

**En vivo.** Imagen `…:057-gate-ext` reconstruida solo en su capa `-ext` sobre `…:057-gate-new-base` (`litellm/` no cambió desde `3d327c4`;
`free -h`: 2,7 GiB disponibles) y `elea057-engine` recreado con `--no-deps engine`, mismo override y mismos `--env-file`: `healthy`.
`measure.py` (stream, 24/26 turnos, 60 herramientas): 3 × **200**, 13,8 s en frío y 3,3–3,6 s después, respuesta **8,6 KB** completa (antes
≈ 2,6 KB cortada). Una sonda con el parseo del SSE: `message_start` → 62 `content_block_delta` → `message_delta` (`stop_reason: max_tokens`,
`input_tokens 34264`, `output_tokens 64`) → `message_stop`. `docker logs` del motor desde la recreación: **0** `IndexError`/`Traceback`.
**Auditoría en stream** (`audit_logs`, solo metadatos): 9 pedidos en stream → 9 filas, `compliance_status = passed`, `pii_detected = true`,
`prompt_tokens 34264–35058`, `completion_tokens 64`, `cache_hit = false`.

**Upstream y alternativas descartadas.** El defecto está presente en LiteLLM 1.92.0 (la versión que fija el motor). Una búsqueda web no encontró un issue ni un
arreglo en BerriAI/litellm (sin verificar en el repositorio; queda para quien actualice el motor: si lo arreglaron, el filtro sobra y es inocuo). Sacar
`include_usage` no es opción: lo fija el adaptador (`handler.py:474`) después de cualquier cosa que el guard ponga en el pedido. Caché en la fila: el destino
no informó tokens de caché en estas corridas (`price_cache_missing: true` en la decisión de la fila); lo que se verificó es que la fila se escribe, con los tokens
de entrada/salida. La medición de caché sigue en T083/T078.

Una cosa que cambia al dejar de cortarse la respuesta: en algunas corridas el modelo cita el DNI del pedido («el identificador aparece
anonimizado (`30123456`)») y el campo `dni_en_claro_en_respuesta` de `measure.py` sale `true`. Es el desenmascarado de la respuesta (el
cliente recibe lo que él mismo envió; la política lo hace a propósito) y no determinista (en 4 de 9 corridas se cita); no es el cuerpo que sale
hacia el destino, que no se reabrió en esta pasada. El campo del script ya no sirve como prueba de «no sale en claro»: eso se mide en el
cuerpo saliente.

## 6. Tests (sin Docker)

- `backend/tests/unit/test_masking_vocabulario_estructural.py`: **21 passed** (el descarte previo a los solapes se encontró con un test que falló primero).
- `backend/tests/unit` + `backend/tests/contract`: 1696 passed, 12 skipped, **6 failed** (`test_route_parity.py`, piden el host `db`; los mismos 6 de la base).
- `sentinel/tests`: **2438 passed, 13 skipped** (los 13 de siempre, con motivo).
  Tras el arreglo del stream (§5), con un venv fuera del repo (`backend/requirements.txt` + `pytest-asyncio`, sin Docker): **2446 passed, 13 skipped** (los
  8 casos nuevos) y la batería T003 `backend/tests/contract/test_gw_no_regresion_057.py`: **26 passed**.
- Fuera de esta corrida: `make -C deploy check`/`check-docs` y la suite del backend en contenedor (el brief solo autorizó Docker para el motor).

## 6b. `claude -p` real contra el motor: dos causas que el pedido sintético no tenía (2026-10-06, research R36)

**Síntoma.** `claude -p 'Leé clientes.csv y decime cuántas filas tiene' --model claude-sonnet-5-5 --allowedTools Read` (`ANTHROPIC_BASE_URL=…/api/v1/gw`, llave virtual
leída de un archivo local y nunca impresa, `CLAUDE_CONFIG_DIR` propio, directorio de prueba con un `clientes.csv` de 3 filas inventadas) daba **400 `masking_required`**
con el motor `-ext` que ya pasaba el pedido sintético de 60 herramientas (§3). Los pedidos bloqueados no dejan fila con el informe del enmascarado, así que la causa
no se leyó de la auditoría: se **capturó el pedido real** (servidor local en el scratchpad, sin Docker, fuera del repo; nada de ese contenido está en archivos versionados)
y se lo repasó con el recorrido real (`_w_body`) y el analizador real del stack, registrando por cada no analizable la posición, el tipo de operación y los tipos de NER.

| # | Pedido | No analizables | Posición | Qué es |
|---|---|---|---|---|
| 1 | turno 1 (21 herramientas, `system` en 3 bloques con `cache_control`, un mensaje `role: system`, `thinking.display`, `output_config`, `context_management`, `safeguards`) | **14** `structural_entity` | `tools[*].input_schema` | la cadena **`1`** (`minLength: 1`) clasificada LOCATION por el NER real: un escalar numérico estructural iba por el camino estricto |
| 2 | turno 2 (con el `tool_use` del modelo y el `tool_result`) | **1** `structural_entity` | `messages[*].content[*].is_error` | la CLAVE `is_error` (booleano del protocolo en `tool_result`) clasificada LOCATION: no estaba en la tabla de posiciones ⇒ «campo desconocido» ⇒ clave analizada estricta |

Descartados con el mismo método: el `system` largo, las descripciones de herramientas, `cache_control`, `metadata.user_id`, los campos nuevos del primer nivel, los tipos de bloque y
los ids `call_…` del destino traducido (0 no analizables en esas posiciones).

**Arreglo (dentro de A+B, sin relajar nada fuera).** (1) `_w_scan` emite los escalares numéricos como `scan_open` (`litellm/extensions/sentinel_guardian_policy.py`,
rama numérica de `_w_scan`): vocabulario abierto ⇒ se ignoran los tipos semánticos y un patrón (un DNI como `minLength`) sigue bloqueando; el texto libre y los números de
subárboles libres no cambian. (2) `….is_error@tool_result` entra en las posiciones estructurales (S14_EXEMPT_POSITIONS, `anthropic.structural`): es un nombre de campo del
protocolo; un valor no booleano ahí se sigue analizando y los campos desconocidos de verdad siguen estrictos. Contrato: `contracts/costuras-base.md` §S14 y research R36.
**Test rojo primero**: `backend/tests/unit/test_masking_vocabulario_estructural.py` (la forma del pedido y del turno 2 reales con un analizador que marca `1` e `is_error` como
LOCATION; +10 casos (21 → 31); el de turno 2 y el de números fallaron antes del cambio) y la instantánea de posiciones en `test_masking_posiciones_exentas.py`.

**En vivo.** `free -h`: 2,5 GiB disponibles (≥ 1,5). Imagen `…:057-gate-ext` reconstruida (la capa de `litellm/` cambió, así que primero `litellm/Dockerfile` como tag temporal
`…:057-claude-code-base` y encima `sentinel/docker/engine.Dockerfile`; el archivo trae `is_error@tool_result`) y `elea057-engine` recreado con `--no-deps engine`, el mismo override y los mismos
`--env-file`: `healthy`. Con solo el arreglo (1) el turno 1 pasaba y el turno 2 seguía en 400 (la causa 2 se vio recién ahí); con ambos, `claude -p` responde («el archivo `clientes.csv`
tiene 4 filas»: el encabezado y 3 filas), ~70 s en frío por el NER (cada turno pasa por el analizador).

**Auditoría de esa corrida** (`audit_logs`, solo metadatos): 4 filas del pedido real, todas `compliance_status = passed`, `blocked_by_layer` vacío, destino `gpt-5.1-chat`,
`routing_decision.extensions.redirect` con `forced_masking: true`, `masking_scope: full`, `masking_verified: true`; `masked_entities` con DNI ×1 en el turno 1 y **×3 una vez leído el
`clientes.csv`** (los tres DNI del archivo salen enmascarados hacia el destino), más PERSON/URL/LOCATION/EMAIL_ADDRESS/PHONE_NUMBER/DATE_TIME del `system` y de las herramientas.
Otras dos filas del mismo instante: `blocked_by_policy` (`claude-sonnet-5`, sin regla) y `blocked_secret` (capa `secret_detection`, «OpenAI API Key», sobre `rdx-azure/gpt-5.1-chat`):
son pedidos auxiliares del cliente, no el principal; el segundo **no se investigó** (queda para quien siga: qué cuerpo dispara el detector de secretos) y hubo `429` del destino en reintentos.

**Tests (sin Docker, venv fuera del repo).** `backend/tests/unit` + `backend/tests/contract`: **1706 passed, 12 skipped, 6 failed** (`test_route_parity.py`, piden el host `db`: los mismos 6
de la base; antes 1696 passed); `sentinel/tests`: **2446 passed, 13 skipped**; T003 `test_gw_no_regresion_057.py`: **26 passed**. `make -C deploy check`/`check-docs` y la suite del backend en
contenedor **no se corrieron** (el brief solo autorizó Docker para el motor); no se tocó `docs/docs/**` ni la API ni `.env.example`.

## 6c. El `blocked_secret` del pedido auxiliar: palabras como `task-…` contaban como clave (2026-10-07, research R37, T117)

**Síntoma.** En la corrida de §6b, dos filas del mismo instante eran `blocked_by_policy` y `blocked_secret` (capa `secret_detection`, tipo genérico); la segunda quedó sin investigar. La fila
trae solo metadatos, así que se **recapturó** el pedido: `claude -p` con el mismo comando de §6b, `CLAUDE_CONFIG_DIR` propio, proxy local en el scratchpad (fuera del repo) hacia
la pasarela; 16 pedidos, todos con `status` registrado.

| Pedidos | `max_tokens` | Herramientas | Posición de lo detectado | Qué es |
|---|---|---|---|---|
| 3 auxiliares (el clasificador del modo auto ×2 y uno con un modelo sin regla) | 2112 / 64 | 0 | `system[1].text`, desde el carácter 2470 | una palabra inglesa compuesta `task-<palabra>`: 15 caracteres desde `sk-`, solo letras; texto fijo de Claude Code |
| 13 principales (21 herramientas) | 128000 | 21 | `tools[19].description`, carácter 171 | la misma palabra, **fuera** de los 16 000 primeros caracteres que miran los detectores: no bloqueaba |

**Veredicto: falso positivo, no un secreto.** Ningún valor detectado es una credencial (letras minúsculas de un diccionario, sin dígitos) y el texto es el del programa, no el del usuario.
Causa en `SECRET_PATTERNS` (`litellm/extensions/sentinel_guardian_policy.py`): `sk-[a-zA-Z0-9]{10,}` sin límite izquierdo. Arreglo: `(?<![a-zA-Z0-9])` (research R37).
**Test rojo primero**: `backend/tests/unit/test_secret_detection_limite_izquierdo.py` (11 de 73 fallaron antes). Con el arreglo, `detect_secrets` sobre los 16 pedidos capturados: **0 detecciones**
(antes: los 16 contenían la cadena y 3 caían dentro de lo inspeccionado).

**No se reconstruyó el motor** (el brief solo lo permitía si hacía falta): el efecto en vivo requiere la imagen `-ext` con este archivo; hasta entonces el motor corriendo sigue con el patrón viejo.

**Tests (sin Docker, venv fuera del repo).** `backend/tests/unit` + `backend/tests/contract`: **1779 passed, 12 skipped, 6 failed** (`test_route_parity.py`, piden el host `db`: los mismos 6 de la base; antes 1706 passed);
`sentinel/tests`: **2446 passed, 13 skipped**; no se tocó `docs/docs/**`, la API ni `.env.example`; `make -C deploy check`/`check-docs` y la suite del backend en contenedor **no se corrieron** (sin aviso previo para Docker).

## 6d. Llaves OpenAI actuales (`sk-proj-`, `sk-svcacct-`, `sk-admin-`) y un solo criterio en los dos caminos (2026-10-07, research R38)

**Hallazgo.** Los dos caminos del detector de secretos tenían patrones distintos para la misma llave: el motor (`SECRET_PATTERNS["OpenAI API Key"]`,
`litellm/extensions/sentinel_guardian_policy.py:370`) pedía `sk-` + 10 alfanuméricos seguidos, así que `sk-proj-…` (guion tras `proj`) **no se detectaba**; el backend
(`backend/src/services/guardian_service.py`, `sk-(?:proj-)?[A-Za-z0-9_-]{20,}`) sí la veía pero **sin límite izquierdo**, y `task-implementation-of-the-risk-assessment`
(…`sk-` + 20 caracteres con guiones) era «clave» en ese camino.

**Cambio.** Un patrón: `(?<![a-zA-Z0-9])sk-(?:[A-Za-z0-9_-]{20,}|[A-Za-z0-9]{10,})` (rama larga primero: la redacción cubre la llave entera). El backend lo toma de la librería
compartida (`OPENAI_KEY_PATTERN = policy.SECRET_PATTERNS["OpenAI API Key"]`, `guardian_service.py:13`, que ya importaba `policy`): ya no hay un segundo literal.
No baja ninguna detección previa salvo la de una llave pegada a una letra o dígito anteriores (el límite de R37, ahora también en el backend); el motor detecta además lo
que antes solo veía el backend (`sk-ant-…`, llaves con guiones). Sin llaves reales: los tests las generan con un `random.Random` con semilla.

**Test rojo primero**: `backend/tests/unit/test_secret_detection_llaves_modernas.py` (165): **73 fallaban** antes (las 5 formas modernas en el motor; `task-…`/`ask-…`/`desk-…` largas
en el backend; `sk-ant-…` y `sk-<10>` en el camino que no las veía; la redacción completa; la paridad). Con el cambio: 165 passed, y `test_secret_detection_limite_izquierdo.py` (73) y
`test_pilot_fixes.py` (Bug 3) siguen verdes.

**Docker (con OK del owner; `free -h` antes de cada build: disponible 2,5 / 2,6 / 3,4 GiB).** Motor: `litellm/` → `…/elea-guardian-engine:057-gate-new-base`, luego
`sentinel/docker/engine.Dockerfile` → `:057-gate-ext`; `elea057-engine` recreado solo, mismo `-p elea057`, `STACK_PREFIX`, `--env-file` y `-f` de §2 más el override de la imagen `-ext`
sin bind mounts: `healthy`. Backend (cambió): `backend/Dockerfile.standalone` → `…/elea-guardian-backend:057-secretos-base`, luego `sentinel/docker/backend.Dockerfile` →
`:057-secretos-ext`; `elea057-backend` recreado solo con un override equivalente (imagen `-ext`, `volumes: !reset []`: antes montaba `backend/`, `litellm/`, `sentinel/` y los seeds del worktree
`057-gate`; ahora 0 montajes; mismo `environment`/`env_file`, puerto 8091): arrancó (`/health` 200, `alembic` sin cambios). `db`, `redis`, `nlp-analyzer` y `sentinel-frontend` no se tocaron.
En vivo, dentro de los contenedores recreados: el motor detecta las cuatro formas (`sk-proj-`, `sk-svcacct-`, `sk-admin-`, `sk-` vieja) y no `task-…`/`ask-…`/`desk-…` largas; el patrón del backend
detecta `sk-proj-…` y no `task-implementation-of-the-risk-assessment`.

**`claude -p` real** (`CLAUDE_CONFIG_DIR` propio, `ANTHROPIC_BASE_URL=http://localhost:8091/api/v1/gw`, llave virtual leída de `~/.elea057-gate/virtual.key` sin imprimirla,
`--model claude-sonnet-5-5 --allowedTools Read`, `clientes.csv` de 3 filas inventadas en un directorio de prueba): respondió («clientes.csv tiene 4 filas»: encabezado + 3), exit 0.
Auditoría de los 8 minutos siguientes (solo metadatos: `compliance_status` y `blocked_by_layer` de `audit_logs`): **4 filas `passed`, 0 bloqueadas, ninguna `blocked_secret`**.

**Tests (sin Docker, venv fuera del repo).** `backend/tests/unit` + `backend/tests/contract` (incluye T003, `test_gw_no_regresion_057.py`): **1944 passed, 12 skipped, 6 failed** (`test_route_parity.py`,
piden el host `db`: los mismos 6; antes 1779 passed + los 165 nuevos); `sentinel/tests` (con `litellm[proxy]==1.95.1`, `fastapi==0.111.0`, `starlette==0.37.2`, sin `NLP_ANALYZER_URL`/`INTERNAL_ALLOWED_CIDRS`):
**2446 passed, 13 skipped**. Con `litellm 1.92.0` y `fastapi 0.142` un test de `sentinel/tests` falla también en `HEAD` (las rutas `/api/v1/redirect` no se montan): es del entorno, no del cambio.
No se tocó `docs/docs/**` (ninguna página describe el patrón de llaves), la API ni `.env.example`; `make -C deploy check`/`check-docs` y la suite del backend en contenedor **no se corrieron** en este tramo.

## 7. Gate final (T082 y T086) — corrida con Docker, 2026-10-06

Rama `cluna-8/057-gate-final` sobre `b5fafda`. Docker con OK del owner, **proyecto de compose propio** `-p elea057gate` (`STACK_PREFIX=elea057gate`,
solo `db` y `redis`, **sin puerto publicado al host** con un override fuera del repo: `db: ports: !reset []`); el stack `elea057`, `sentinel-frontend` y el
puerto 5433 no se tocaron. `free -h` antes de cada build/suite: disponible 2,3–2,6 GiB (≥ 1,5 GiB). Sin `.env` en el worktree (la suite lo cubre:
`backend/tests/conftest.py:29-31` fija un `JWT_SECRET_KEY` de suite).

| Paso | Comando | Resultado |
|---|---|---|
| Suite del backend en contenedor, Postgres real | `docker compose -p elea057gate -f docker-compose.yml -f <override> run --rm --no-deps backend pytest tests/ -q` | **3314 passed, 25 skipped**, exit 0, 388,97 s |
| Gate de artefactos | `make -C deploy check` | **exit 0**: imágenes, white-label, secretos, tofu, **check-docs OK** (12 pasos), trust-kit, Redis, admisión, límites locales, category_file, EXTRA_ENV_FILE, **entrega de extensiones (T020), `heads` (T088), variantes `-ext` (T091), región por defecto (T095: 4 mutaciones detectadas)** |
| Deriva de references | `make -C deploy docs-refs` | `openapi.json` idéntico (git sin cambios) y `configuration.md` 51 variables sin cambios: **no hay deriva real** |
| Hub | `cd client && npm ci && npm test` | 43 passed, 0 fallos |
| Panel | `cd frontend && npm ci && npm test` | 9 archivos, **36 passed** |
| Consola de la extensión | `cd sentinel/frontend && npx vitest run` y `npx tsc -p .` (`node_modules` → `frontend/node_modules`) | **25 archivos, 264 passed**; `tsc` sin errores |
| Extensión (Python) | contenedor del backend + `litellm[proxy]==1.92.0` y `pypdf` (pip resolvió `litellm 1.95.1` con el pin del backend como restricción) y `fastapi==0.111.0`/`starlette==0.37.2` (los pines del backend), `PYTHONPATH=.:backend LITELLM_MODE=PRODUCTION`, contra el mismo Postgres: `pytest sentinel/tests -q -rs` | **2446 passed, 13 skipped**, exit 0 |
| T104–T106 | `pytest tests/unit/test_masking_pdf_hostil.py test_masking_alcance_completo.py test_plugin_startup.py` en el contenedor, sin y con `pypdf 6.19.0` | **64 passed, 0 skipped** en ambos casos |
| Redacción (D10, R26) | `grep -rniE 'anonimiz\|cumple con\|conforme a\|transferencia l[ií]cita' docs/docs sentinel/frontend` | 3 coincidencias nuevas, **las tres niegan** («no es anonimización»: `integrations/index.md:436`, `administration/redireccionamiento.md:245`, `overview/index.md:292`); el resto (`compliance/dpa-dsr-retention.md`, `compliance/index.md`) es anterior a la 057, derechos del interesado y escenarios, no el enmascarado |

Los 13 skips de `sentinel/tests` son los mismos de T017/T030, ninguno de migraciones, RLS, resolución ni credenciales: 6 por `deploy/clients/nix/**` o
`release.yml` de Sentinel (no existen en Eleia), 2 por `src.services.model_route_hook` (el chat por catálogo, que esta base no trae; `sentinel/tests/unit/test_chat_route.py:15`
y `test_unsupported_params.py:248`), 3 por `trusted_attribution`/`mark_attribution`, 1 por `residency_heuristic` y 1 por `fd515ff`. Los 25 del backend
son de esa suite (hay marcas `skipif`/`importorskip` en `test_chat_smoke.py`, `test_gw_info_neutral.py` y `e2e/test_guardrail_behavior_e2e.py`); no se listaron los motivos uno por uno en esta corrida (sin `-rs`).

### Hallazgos del gate

1. **`test_docs_apiref.sh` daba «openapi.json DESACTUALIZADO» en frío (causa clara, arreglado).** Con la imagen del backend sin construir, el
   `docker compose run` del check la construía en el medio y el progreso de BuildKit se colaba por stdout dentro del JSON; con la imagen ya construida el mismo
   check pasaba y `docs-refs` regeneraba un archivo idéntico. Es el defecto que ya tenía `docs-refs` (comentario del `Makefile`, ensayo 2026-10-06 §6.3), que
   construye antes. `deploy/release/checks/test_docs_apiref.sh` ahora hace `docker compose build backend >&2` antes del export. Rojo → verde: primera
   corrida de `make check` (falló solo ese paso), después la imagen borrada y el check solo → verde, y `make -C deploy check` completo → exit 0.
   Como el check cortaba el `make` en `check-docs`, los checks siguientes no habían corrido en la primera pasada; corrieron todos en la segunda.
2. **`sentinel/tests` desde el servicio `backend` del compose falla 9 tests si no se borran dos variables (entorno, no código).** El servicio cablea
   `NLP_ANALYZER_URL=http://nlp-analyzer:3000` (`docker-compose.yml:251`) e `INTERNAL_ALLOWED_CIDRS=auto` (`:206`); `backend/tests/conftest.py` las borra pero
   `sentinel/tests/conftest.py` no. Sin el sidecar, la pasarela cierra en falso (`blocked_nlp_unavailable`, 400 en vez de 200: 1 test del contrato y 8 de la
   batería de no regresión). Con `unset NLP_ANALYZER_URL INTERNAL_ALLOWED_CIDRS` (como en el venv del T086) pasa todo. No se tocó `sentinel/tests/conftest.py`
   (viene de Sentinel); queda anotado para quien corra esta suite en el contenedor.

### Qué queda de T086 (no cerrado)

T086 sigue **abierto**: lo de esta máquina está verde, pero el ítem «los tests del instalador (T100, T101, T103, en su repo)» no se puede dar por cumplido desde
acá: esas tres tareas siguen sin marcar y se trabajan en `cluna-8/elea-installer` (worktree `057-tramo-h`). Tampoco están hechas T083/T102 (con Azure) ni las salidas
resumidas en el PR. T082 sí queda cerrada.

### Limpieza

`docker compose -p elea057gate … down` (contenedores, red y volumen del proyecto propio), imagen `elea057gate-backend` y la creada por `docker compose` sin `-p`
desde los checks (`057-gate-final-backend`, redes `057-gate-final_*`), todas creadas por esta corrida.
