# Research (Fase 0) — 030 Auto-router semántico

Decisiones cerradas con evidencia. Formato: Decisión / Racional / Alternativas descartadas.

## R1 — Modelo de embeddings: `qwen3-embedding:0.6b` local vía el motor

**Decisión**: `router-embeddings` en el config del motor apunta a
`ollama/qwen3-embedding:0.6b` (639 MB). El backend embebe vía `POST {motor}/v1/embeddings`
con master key (patrón `ai_engine_client`).

**Racional**: benchmark del 28-jul (`bench_embeddings.py`, 9 queries en español contra las
rutas reales): qwen3-embedding:0.6b = **8/9**; nomic-embed-text = 7/9 y
granite-embedding:278m = 7/9 (ambos fugan chitchat a premium). El fallo restante
(«hola, ¿qué tal?» → premium 0.55) se elimina por diseño con la tercera ruta
"conversación trivial"→local. llm-guardian usaba Azure para embeber → inaceptable aquí
(el prompt saldría del host para DECIDIR el ruteo, violando Principio I + residencia).

**Alternativas descartadas**: nomic/granite (peor score, fuga de chitchat); Azure/OpenAI
embeddings (residencia); auto-router nativo de LiteLLM (su config loader exige una key
OpenAI viva solo para construir el índice — motivo original del servicio propio en
llm-guardian, sigue vigente).

**Pendiente de verificar en implementación (checkpoint en tasks)**: la ruta LiteLLM
`ollama/qwen3-embedding:0.6b` por `/v1/embeddings` (el benchmark pegó a Ollama directo
`/api/embed`). Si LiteLLM usara un endpoint viejo de Ollama, el quickstart lo detecta con
un curl antes de codear UI.

## R2 — Punto de inserción en el plano de chat

**Decisión**: la decisión de ruteo ocurre AL PRINCIPIO del endpoint
(`chat.py`, tras parsear el request y ANTES del pipeline de protección): si
`request.model == "auto"` → `AutoRouterService.route(mensaje)` → se fija el **modelo
efectivo** y el resto del pipeline corre exactamente como si el usuario lo hubiera elegido
a mano (FR-010). Se conserva `requested_model="auto"` + la decisión como metadata.

**Racional** (mapa Explore 28-jul, file:line):
- `ChatRequest.model` es hoy `str` obligatorio sin validación (chat.py:425-431) → «auto» entra como valor sentinela sin cambio de schema.
- El único punto donde el modelo cambia hoy es `routed_model = guardian_res["model"]` (chat.py:739, guardián sensitive_routing) — se mantiene: puede re-rutear DESPUÉS del auto-router (prioridad del guardián sobre la conveniencia).
- Asimetría existente request.model vs routed_model: auditoría (1139), coste (1066) y presupuesto (1182) usan `request.model`; el motor (891) y layer_llm (1256) usan `routed_model`. Con «auto», TODOS los consumidores de "qué modelo" deben ver el modelo efectivo (ver R7 coste).

**Alternativas descartadas**: rutear después del masking (innecesario: el embedding es
local, FR-003; y el masking degradaría la señal semántica); pseudo-modelo registrado en el
motor (patching/config del motor para algo que es del plano backend — viola VI de espíritu).

## R3 — Config caliente: `auto_router.json` en el volumen `litellm_config`

**Decisión**: `/app/litellm_config/auto_router.json`, leído por el backend en cada
decisión (cache de vectores aparte, ver R5), escrito por el PUT admin de forma atómica
(tmp + `os.replace`). Schema en data-model.md (switch `enabled`, `default_model`,
`timeout_seconds`, `embedding_model`, rutas con `target_model` desacoplado).

**Racional**: no existe patrón previo de config JSON caliente en el backend (Explore §6:
los únicos `open()` son el config.yaml del motor y el seed de onboarding) — pero el volumen
`litellm_config` YA está montado RW en el backend (compose.prod.yml:57), chowneado
(populate_volumes.sh:42) y poblado por el flujo de release. Mismo path-resolution helper
que `_get_config_path()` (chat.py:401-405) con fallback al repo para dev. llm-guardian usó
exactamente este path (`/app/litellm_config/auto_router.json`) — el port es directo.

**Alternativas descartadas**: DB (las rutas son config de despliegue/seed white-label, no
datos de negocio; el JSON viaja en el bundle como el config.yaml; además evita migración+
CRUD ORM para una entidad que se edita entera); volumen nuevo dedicado (tocar
compose.prod.yml + populate_volumes.sh + bundle.sh sin ganancia).

## R4 — Rutas con `target_model` desacoplado del nombre

**Decisión**: cada ruta tiene `name` (etiqueta legible), `target_model` (referencia al
catálogo real del motor) y opcional `tier`. El `default_model` es una referencia explícita
a UN modelo del catálogo. El panel señala «ruta rota» si `target_model` no existe en el
catálogo (GET /chat/models) y el runtime cae al default (nunca 500).

**Racional**: en llm-guardian `route.name` ERA el nombre del modelo (auto_router.json:
`"name": "azure-gpt-5.1-chat"`) — acoplamiento que rompe al renombrar/borrar modelos y no
responde «¿con N modelos de Ollama, a cuál va?». La respuesta del spec: al que la ruta
declare; y el default configurable apunta a UNO explícito.

## R5 — Cache de vectores: Redis por hash, versión v3, cero ascii-fold

**Decisión**: cache `autoroute:emb:sha256(f"{modelo}:{version}:{texto}")` TTL 7 días
(idéntico a llm-guardian) con `_CACHE_VERSION = "v3-local-qwen"`. Se ELIMINA `_ascii_fold`.

**Racional**: el ascii-fold era workaround documentado de un bug del proxy Azure
(auto_router_service.py:34-42 de llm-guardian) — con embeddings locales no aplica, y
quitarlo mejora la señal en español (acentos/ñ). El bump de versión evita mezclar vectores
del pipeline viejo (el propio comentario del servicio original exige esto). La edición de
utterances aplica en la siguiente consulta sin restart: cada consulta relee el JSON y los
vectores se resuelven por hash de contenido (utterance nueva = miss = embed).

## R6 — Transparencia: Debugger + vitrina + auditoría durable

**Decisión** (FR-006), tres superficies:
1. **Debugger Técnico**: objeto `auto_router` dentro de `pipeline_metadata.layer_llm`
   (chat.py:1255-1263, ya lleva `model_used`): `{requested, route, score, model_selected,
   degraded, reason}`.
2. **Vitrina «Conexiones en vivo»**: el camino exitoso del chat HOY NO PUBLICA (solo los 3
   bloqueos, chat.py:598/728/839 — hueco confirmado por Explore §3). Se añade publicación
   de éxito del plano chat vía `_publish_monitor` (gateway.py:609-648) con campo opcional
   `routing`. El docstring de `_publish_monitor` declara contrato de 3 productores → el
   campo es OPCIONAL (los otros productores no lo mandan) y monitor.py lo renderiza solo
   si está. SC-004 (3 prompts → 3 modelos con ruta y score en la vitrina) depende de esto.
3. **Auditoría durable**: columna nueva `routing_decision` JSONB **nullable** en
   `audit_logs` + migración `013_auto_router_decision.py` (precedente exacto: la 012 de la
   027). Metadata-only: `{requested, route, score, model_selected, degraded, reason}` —
   cero texto del prompt.

**Alternativas descartadas**: meter la decisión en `applied_layers` (PROHIBIDO por contrato
C1 — solo códigos del registry y contadores, audit.py:34-38); en `guardian_events`
(congelado: la hash-chain 021 lo relee posicionalmente, licensing/audit_events.py:92-93).

## R7 — Coste y presupuesto sobre el modelo EFECTIVO

**Decisión**: con «auto», `BudgetService.calculate_cost` (chat.py:1066) y `update_budget`
(1182) reciben el modelo efectivo (el que contestó), no el literal «auto». Se aprovecha
para pasar el modelo REAL de la respuesta del motor (campo `model`, honesto tras fallback
— verificado en vivo 28-jul) en lugar de `request.model`.

**Racional**: FR-009/Principio V (coste honesto). Con «auto» el literal `auto` no
pricearía nada; y el gap ya existía: si el motor cae al fallback local, el coste se
calculaba con el modelo pedido (cloud) — este fix lo cierra de paso para el caso auto y
queda anotado para generalizar (no se toca el camino no-auto en esta spec más allá de lo
necesario, para no ensanchar el blast radius pre-demo).

## R8 — Fallback siempre-a-local (US3): write en el alta + seed del piloto

**Decisión**: (a) `register_model` (POST /chat/models, chat.py:1306-1348): si el modelo
nuevo NO es provider ollama y existe ≥1 modelo local en el catálogo, se escribe
`router_settings.fallbacks += {nuevo: [local_default]}` reutilizando la lógica del PUT
existente (chat.py:1442-1467); `local_default` = el `default_model` del router config si es
local, si no el primer ollama del catálogo. (b) El template del piloto
(`config.yaml.tmpl` de camara-comercio) gana bloque `router_settings` base
(`disable_cooldowns: true, num_retries: 2, timeout: 30`) — hoy NO lo tiene (verificado:
los fallbacks solo podían nacer del PUT). (c) Sin fallback local→cloud: el writer se niega
si el modelo origen es ollama (regla existente que se conserva, ahora enforced en el write).

**Racional**: decisión sellada de JF 28-jul («que siempre vaya a local, sí»). El motor lee
config.yaml solo al arrancar → el fallback escrito EN el alta viaja en el mismo restart que
el alta misma exige (gotcha operativo ya documentado en INSTALL). Verificado en vivo: caída
de OpenAI → 200 en 11,4 s por qwen local, campo `model` honesto.

## R9 — «Auto» fuera del plano chat: /gw responde el default local

**Decisión**: si llega `model=="auto"` por /gw (byok de coding tools), el gateway lo
reescribe al `default_model` del router config antes de reenviar al motor (una línea en el
camino byok, gateway.py:~801). Sin embeddings, sin clasificación: v1 declara «Auto» como
feature del plano chat (asunción de spec).

**Racional**: el motor no conoce ningún modelo «auto» → hoy sería un 400 del motor. Los
coding tools declaran modelo explícito; esto es solo red de seguridad del edge case.

## Riesgos abiertos (van a tasks como checkpoints tempranos)

1. **LiteLLM ↔ Ollama embeddings** (R1): verificar `/v1/embeddings` end-to-end antes de la
   UI. Mitigación: si la ruta ollama/* de embeddings falla, alias OpenAI-compatible de
   Ollama (`openai/qwen3-embedding:0.6b` con api_base `http://host:11434/v1`).
2. **Latencia SC-002**: qwen3-0.6b embebe ~20 utterances + query; con cache caliente solo
   la query (1 vector). El benchmark ya midió tiempos aceptables en el Mac; la sede (Ryzen)
   se mide en el preflight del jueves.
3. **Sede sin el modelo**: `ollama pull qwen3-embedding:0.6b` entra al INSTALL y al
   preflight de la visita (asunción de spec). Si falta → degradación registrada al default
   (FR-004), la demo de «Auto» no rompe nada más.
