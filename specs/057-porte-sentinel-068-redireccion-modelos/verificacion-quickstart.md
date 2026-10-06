# Verificación en vivo del quickstart (T083) — parte 1: vocabulario estructural con el NER real

**Estado de T083: abierta.** Este documento registra solo la parte del gate que cerró la enmienda de N8
(research R35; `contracts/costuras-base.md` §S14 «Vocabulario cerrado y tipos semánticos»; T114–T115). La corrida completa del
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
