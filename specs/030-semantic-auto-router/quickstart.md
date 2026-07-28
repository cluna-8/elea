# Quickstart — 030 Auto-router semántico

## Prerrequisitos (una vez)

```bash
# Modelo de embeddings local (639 MB) — también va al INSTALL de la sede
ollama pull qwen3-embedding:0.6b
```

El catálogo del motor necesita la entrada `router-embeddings` (litellm/config.yaml en dev;
en el stack camara ya existe apuntando a nomic — cambiarla a qwen3) y el motor se REINICIA
tras tocar su config (`docker restart <proyecto>-litellm-1`).

## Checkpoint temprano (research R1 — ANTES de codear UI)

Verificar la ruta LiteLLM→Ollama de embeddings end-to-end:

```bash
curl -s http://localhost:4000/v1/embeddings -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"router-embeddings","input":["hola mundo"]}' | head -c 200
```

Esperado: JSON con `data[0].embedding` (lista de floats). Si falla, plan B de R1
(alias openai-compatible `http://host:11434/v1`).

## Probar la decisión (sin UI)

```bash
# 1. Ver/editar config
curl -s -H "Authorization: Bearer $ADMIN_JWT" http://localhost/api/v1/chat/router-config | jq .

# 2. Chat con Auto — 3 prompts, 3 destinos (SC-004)
for msg in "escribí una función en python que ordene fechas" \
           "resumime este documento en tres puntos" \
           "hola, ¿qué tal?"; do
  curl -s http://localhost/api/v1/chat/completions \
    -H "Authorization: Bearer $ADMIN_JWT" -H "Content-Type: application/json" \
    -d "{\"message\": \"$msg\", \"model\": \"auto\"}" \
    | jq '.pipeline_metadata.layer_llm.auto_router'
done
```

Esperado: rutas premium / económico / local respectivamente, con score ≥ threshold.

## Verificar SC-003 (switch OFF = cero embeddings)

```bash
# Apagar por PUT (o por el panel) y repetir un chat "auto":
# - responde el default_model
# - docker logs <proyecto>-litellm-1 SIN llamadas nuevas a /v1/embeddings
# - auto_router.reason == "switch_off"
```

## Benchmark SC-001 (≥8/9 contra el stack levantado)

```bash
python3 specs/030-semantic-auto-router/bench_embeddings.py --live
# (adaptado en tasks: modo --live pega al motor /v1/embeddings con las rutas del
#  auto_router.json del volumen, no a Ollama directo)
```

## Verificar degradación honesta (FR-004)

```bash
# Parar Ollama (o poner timeout_seconds: 0.001) y mandar un chat "auto":
# - responde 200 por el default_model
# - auto_router.degraded == true, reason embed_timeout|embed_error
# - la fila de audit_logs tiene routing_decision con degraded true
```

## Verificar fallback siempre-a-local (US3 / SC-005)

```bash
# Romper el api_base de un cloud (PATCH credencial) + restart motor; consultarlo:
# - 200 servido por el local en ≤15 s
# - campo model de la respuesta = modelo local REAL
# - badge de degradado visible en el Playground
```

## Dónde mirar

- Panel: «Modelos & Ollama» → sección «Ruteo inteligente».
- Vitrina: «Conexiones en vivo» — eventos de chat con ruta+score.
- Auditoría: Logs de Auditoría — columna/detalle con routing_decision.
- Config real: volumen litellm_config → `auto_router.json`.
