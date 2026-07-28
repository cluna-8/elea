# Data Model (Fase 1) — 030 Auto-router semántico

## 1. `auto_router.json` — config caliente del router

Vive en `/app/litellm_config/auto_router.json` (volumen `litellm_config`; fallback dev:
`litellm/auto_router.json` del repo, mismo helper de path que el config del motor).
Lectura: en cada decisión de ruteo. Escritura: PUT admin, atómica (tmp + `os.replace`).

```jsonc
{
  "enabled": true,                      // switch global (pedido explícito de JF)
  "default_model": "camara-comercio-local",  // referencia EXPLÍCITA a un modelo del catálogo
  "timeout_seconds": 5,                 // timeout de la llamada de embeddings (panel)
  "embedding_model": "router-embeddings",    // nombre en el catálogo del motor
  "routes": [
    {
      "name": "Código y análisis",      // etiqueta legible (NO es el modelo — ver research R4)
      "description": "Consultas de código, análisis y razonamiento — modelo premium",
      "target_model": "gpt-4o",         // referencia al catálogo real
      "score_threshold": 0.45,
      "tier": "premium",                // opcional, cosmético (badge en panel)
      "utterances": ["escribí una función en python", "…"]
    },
    {
      "name": "Redacción y resumen",
      "target_model": "gpt-4o-mini",
      "score_threshold": 0.45,
      "tier": "economy",
      "utterances": ["resumime este texto", "…"]
    },
    {
      "name": "Conversación trivial",
      "target_model": "camara-comercio-local",
      "score_threshold": 0.45,
      "tier": "local",
      "utterances": ["hola, ¿qué tal?", "gracias, nos vemos", "…"]
    }
  ]
}
```

**Validación en el PUT** (422 si falla): `enabled` bool; `default_model` string no vacío;
`timeout_seconds` número > 0 y ≤ 60; `routes` lista (puede ser vacía); por ruta: `name` y
`target_model` no vacíos, `0 < score_threshold ≤ 1`, `utterances` lista no vacía de
strings no vacíos. NO se valida que `target_model` exista en el catálogo al guardar
(el catálogo puede cambiar después igualmente): la ruta rota se SEÑALA en el GET
(`target_ok: false`) y el runtime degrada al default (nunca 500).

**Semántica runtime** (port de llm-guardian + adaptaciones, research R2/R5):
- `enabled: false` → decisión inmediata `default_model`, **cero** llamadas de embeddings
  (SC-003), `degraded: false`, `reason: "switch_off"`.
- Clasificación: embed(utterances de todas las rutas + query[:500]) → coseno → gana el
  mayor score que supere el umbral de SU ruta (best-of; empate exacto = primera declarada).
- Bajo umbral → default (`reason: "below_threshold"`, `degraded: false` — es el diseño,
  no un fallo).
- Timeout / motor caído / config corrupta / `target_model` inexistente en catálogo →
  default con `degraded: true` y `reason` concreto (`embed_timeout`, `embed_error`,
  `config_error`, `target_missing`) — SIEMPRE registrado (FR-004).
- Cache Redis `autoroute:emb:sha256(modelo:v3-local-qwen:texto)`, TTL 7 días.

## 2. Decisión de ruteo (objeto en memoria → 3 superficies)

```jsonc
{
  "requested": "auto",            // lo que pidió el usuario
  "route": "Código y análisis",   // ruta ganadora (null si default)
  "score": 0.61,                  // score de la ganadora (0.0 si default)
  "model_selected": "gpt-4o",     // decisión del router
  "degraded": false,              // true = hubo fallo y se degradó al default
  "reason": null                  // switch_off | below_threshold | embed_timeout |
                                  // embed_error | config_error | target_missing | null
}
```

Superficies (research R6): `pipeline_metadata.layer_llm.auto_router` (Debugger),
campo opcional `routing` del evento de vitrina, columna `routing_decision` de auditoría.
Metadata-only: jamás texto del prompt.

## 3. Migración 013 — columna de auditoría

```text
alembic/versions/013_auto_router_decision.py
  down_revision = <revision id de 012_governance_profiles_audit_attribution>

  ALTER TABLE audit_logs ADD COLUMN routing_decision JSONB NULL;
```

- Nullable, sin default, sin backfill (las filas viejas no tuvieron ruteo).
- Sin índice (se consulta como detalle de fila, no se filtra por ella en v1).
- **NO** tocar `applied_layers` (contrato C1) ni `guardian_events` (hash-chain 021 lo lee
  posicionalmente). `routing_decision` queda FUERA del payload de la hash-chain — la
  cadena existente no cambia (verificar con los tests de licensing en el gate).
- Modelo: `backend/src/models/audit.py` + nuevo parámetro keyword-only
  `routing_decision: dict | None = None` en `audit_service.log_transaction`.

## 4. Catálogo del motor (sin cambio de schema, entradas nuevas)

- `router-embeddings` → `ollama/qwen3-embedding:0.6b` en `litellm/config.yaml` (dev) y
  `deploy/clients/camara-comercio/config.yaml.tmpl` (piloto). Excluido del dropdown del
  chat (GET /models ya filtra o se filtra por nombre — verificar en implementación; no
  debe aparecer como modelo conversable).
- `router_settings` base en el template del piloto: `disable_cooldowns: true`,
  `num_retries: 2`, `timeout: 30` (research R8).
- Pseudo-modelo «auto» — NO existe en el motor: lo inyecta `GET /chat/models` al principio
  de la lista cuando `enabled: true` (`{model_name: "auto", provider: "auto",
  is_configured: true, is_eu_compliant: true}`) → el Playground/portal lo muestran (y por
  ser el primero, queda preseleccionado); ModelsPage lo filtra de su tabla admin.
