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

## 5. Hallazgo aparte (no es de esta enmienda)

Con stream, el motor registra `IndexError: list index out of range` en `litellm/llms/anthropic/experimental_pass_through/adapters/streaming_iterator.py:611`
(`chunk.choices[0]`): Azure manda un chunk con `choices` vacío (anotaciones de filtro de contenido) y el adaptador de Anthropic del motor fijado lo
desreferencia. El cliente recibe 200 con la respuesta cortada (≈ 2,6 KB) y **no se escribe fila de auditoría** del pedido en stream (la fila se
escribe al cerrar el stream). Ocurre después de enmascarar y de salir hacia el destino; es del adaptador del motor, no de la política. Queda para
T083/T078 (medición de caché y auditoría en stream) y para el coordinador.

## 6. Tests (sin Docker)

- `backend/tests/unit/test_masking_vocabulario_estructural.py`: **21 passed** (el descarte previo a los solapes se encontró con un test que falló primero).
- `backend/tests/unit` + `backend/tests/contract`: 1696 passed, 12 skipped, **6 failed** (`test_route_parity.py`, piden el host `db`; los mismos 6 de la base).
- `sentinel/tests`: **2438 passed, 13 skipped** (los 13 de siempre, con motivo).
- Fuera de esta corrida: `make -C deploy check`/`check-docs` y la suite del backend en contenedor (el brief solo autorizó Docker para el motor).
