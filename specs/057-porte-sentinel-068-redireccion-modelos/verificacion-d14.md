# Verificación D14 (T019) — spike del motor fijado

Corrida del 2026-10-06 en la PC del owner (Docker local, **sin red** para el spike y sin credenciales: upstreams falsos), sobre la
imagen del motor **fijada** de `litellm/Dockerfile:6` (digest `sha256:80ea654c…`), a través de `elea-guardian-engine:057-gate`
(la misma base más la configuración y las extensiones de Eleia; el spike usa su propio `config.yaml`, no el de producción).

- **Versión real del motor en la imagen fijada**: `litellm 1.92.0` (`importlib.metadata.version("litellm")` dentro de la imagen). Es la
  versión que dice research R7 y la del spike de Sentinel; **no** la `1.95.1` que cita la spec 053.
- **Guion**: `spike053/` de la 068 (`sentinel/specs/068-…/spike053`: `config.yaml`, `fake_upstream.py`, `spike_auth.py`, `spike_guard.py`).
  La imagen no trae `curl`, así que `run_cases.sh` se portó **tal cual, caso por caso**, a `evidencia/spike-d14-run_cases.py` (mismo
  `config.yaml`, mismos upstreams «real» y «atacante», mismas llaves `sk-open` y `sk-limited`).
- **Comando**: `docker run --rm --network none --entrypoint sh -v <spike053>:/spike:ro ghcr.io/cluna-8/elea-guardian-engine:057-gate -c
  'mkdir -p /tmp/work && cp /spike/* /tmp/work/ && cd /tmp/work && python3 run_cases.py'`.

## Resultado — todos los casos de R13 de Sentinel

| Caso (research R13 de Sentinel, `068/research.md:466-540`) | Resultado en `1.92.0` fijada | ¿Igual que R13? |
|---|---|---|
| (a) comodín `rdx-openai-compat/*` → `openai/*`, chat/completions, no-stream (A1) y stream (A2) | **200**; el upstream recibe `model=gpt-destino` y `Bearer CLAVE-REAL-DEL-DESTINO` fijado por el guard; la entrada del comodín no tiene credencial | ✅ |
| (b) credencial y base por pedido desde el guard, **sin** `configurable_clientside_auth_params` | funciona (los valores del guard ganan; 0 pedidos al upstream atacante) | ✅ |
| Anti-desvío: el cliente manda `api_base`/`api_key` en el cuerpo (B1; B3 en un modelo normal) | el **propio motor** lo rechaza en la auth: **401** «api_base is not allowed in request body… Clientside passthrough requires explicit admin opt-in»; 0 pedidos al atacante | ✅ (R13 anotó 500 genérico; en la imagen fijada es **401**: mejor, y la pasarela igual quita esos campos antes) |
| `rdx-*` sin autorización interna (B2) | **403** «destino no autorizado» del guard | ✅ |
| Cara Anthropic `/v1/messages` → `openai/*` (A3) | **404** (el motor usa Responses y el upstream solo-chat no la tiene) | ✅ (confirma la corrección 2 de R13: familias solo-chat usan `hosted_vllm/*`) |
| Cara Anthropic `/v1/messages` → familia chat `hosted_vllm/*` (A3b) | **200**, traducido, el upstream recibe `qwen-destino` | ✅ |
| (c) llave con lista (`sk-limited` = `["pro"]`) pidiendo `rdx-*` con autorización (C1) | **200**: con auth propia el motor **no aplica** `models` de la llave (C2, pedir `pro`, también 200) ⇒ la única barrera de FR-016 es la de la pasarela (A2/T035) | ✅ |
| `/v1/models` del motor con `sk-open` (D1) | **212 ids**: lista el comodín **y lo expande** con el catálogo del proveedor (`rdx-openai-compat/o1-2024-12-17`, …) ⇒ `models_filter` y entradas ocultas son obligatorios | ✅ |

**Veredicto D14: pasa. No hay gate de re-plan**; el diseño (guard fija credencial y base por pedido, familias `rdx-*` con comodín y sin
credencial, `rdx-*` sin autorización rechazado) se mantiene sobre la imagen fijada. Salida completa de la corrida: ver el bloque
«Salida» al final.

## Ensayo de `DISABLE_SCHEMA_UPDATE=true` sobre bases existentes (QA A5, research R5)

Sobre **copias** (`pg_dump | psql` a una base temporal, borrada al terminar) de las bases reales del stack local de esta corrida: la del
backend (`basa_gateway`, 41 tablas, la «base compartida» de R5: tablas ajenas al motor) y la propia del motor (`sentinel_engine`,
74 tablas). Un motor de prueba (la misma imagen, `config.yaml` del spike) apunta a cada copia. Script: `evidencia/spike-a5-ensayo.sh`.

| Caso | Tablas antes → después | Resultado |
|---|---|---|
| copia de la base del backend, **sin** la variable | 41 → **42** | el motor **no arrancó** (`prisma migrate deploy`: «The database schema is not empty… baseline»); escribió en una base ajena (una tabla de más) |
| copia de la base del backend, `DISABLE_SCHEMA_UPDATE=true` | 41 → 41 (misma huella) | el motor **arranca** (`/health/liveliness` 200) y **no toca nada**: ninguna tabla ajena borrada ni creada. Sus propias tablas **no existen** («`LiteLLM_UserTable` does not exist»): sin persistencia de llaves/gasto |
| copia de la base del motor, `DISABLE_SCHEMA_UPDATE=true` | 74 → 74 (misma huella) | arranca y no cambia el esquema |

Conclusión: la variable es **segura para tablas ajenas** (no borra ni crea nada), pero con ella el motor **no crea sus tablas**, así que
solo sirve sobre una base que ya tiene el esquema del motor. En esta línea el compose base ya da al motor su base propia
(`ENGINE_DB`, `docker-compose.yml:78,106`; `db-engine-init`), por lo que **no hace falta usarla en ningún override**: `compose.dev.yml` y
el entorno de la extensión siguen **sin** `DISABLE_SCHEMA_UPDATE` (`sentinel/docker/compose.dev.yml:19-20`). La regla de
`quickstart.md §0` («nunca una base nueva arrancando el backend antes que el motor») sigue vigente para instalaciones con base
compartida.

## Salida de la corrida (resumen sin credenciales)

```
litellm 1.92.0
A1  → 200   upstream real: auth "Bearer CLAVE-REAL-DEL-DESTINO", model "gpt-destino", stream false
A2  → 200   (stream)  upstream real: model "gpt-destino", stream true
A3  → 404   (openai/* por Responses sobre un upstream solo-chat)
A3b → 200   familia chat: model "qwen-destino"
B1  → 401   api_base is not allowed in request body…   (evil: 0 hits)
B2  → 403   destino no autorizado
B3  → 401   api_base is not allowed in request body…   (línea base, sin guard)
C1  → 200   sk-limited pide rdx-*: el motor no aplica la lista
C2  → 200   sk-limited pide pro
D1  → 212 ids en /v1/models (el comodín se expande)
```
