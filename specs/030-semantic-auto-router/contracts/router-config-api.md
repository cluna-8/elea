# Contract — Router config API + superficies de la decisión

## GET /api/v1/chat/router-config  (admin-only)

200:
```jsonc
{
  "enabled": true,
  "default_model": "camara-comercio-local",
  "default_model_ok": true,          // ¿existe en el catálogo?
  "timeout_seconds": 5,
  "embedding_model": "router-embeddings",
  "embedding_model_ok": true,        // ¿existe la entrada en el catálogo del motor?
  "routes": [
    { "name": "Código y análisis", "description": "…", "target_model": "gpt-4o",
      "target_ok": true,             // false = ruta rota (señal en panel, runtime → default)
      "score_threshold": 0.45, "tier": "premium", "utterances": ["…"] }
  ]
}
```
- `*_ok` son campos COMPUTADOS en el GET contra `GET /chat/models` — no se persisten.
- 403 si no-admin (mismo guard que el resto de endpoints admin de chat.py).
- Config ausente/corrupta en disco → 200 con defaults seguros (`enabled: false`, rutas
  vacías) + campo `"config_error": true` para que el panel lo muestre — nunca 500.

## PUT /api/v1/chat/router-config  (admin-only)

Body = el mismo objeto SIN los campos computados (`*_ok`, `config_error`).
Validación → data-model.md §1. 200 devuelve el config releído (con computados).
Escritura atómica (tmp + os.replace). Efecto: la SIGUIENTE consulta ya usa lo nuevo
(sin restart de nada). 422 con detalle por campo si falla validación.

## GET /api/v1/chat/models  (existente — extensión)

Cuando `enabled: true`, se antepone el pseudo-modelo:
```jsonc
{ "model_name": "auto", "provider": "auto", "model_id": "auto",
  "is_configured": true, "is_eu_compliant": true }
```
- Primero en la lista → Playground/portal lo preseleccionan (comportamiento actual:
  eligen el índice 0).
- `router-embeddings` (el modelo de embeddings) NO debe listarse como conversable.
- ModelsPage filtra `provider === "auto"` de su tabla de gestión.

## POST /api/v1/chat/completions  (existente — extensión)

- `model: "auto"` → decisión ANTES del pipeline (research R2); el resto del request/
  response no cambia de forma.
- `pipeline_metadata.layer_llm.auto_router` = objeto decisión (data-model.md §2);
  ausente (no null) cuando el request no fue «auto».
- Coste/presupuesto calculados sobre el modelo efectivo que contestó (FR-009, research R7).

## Evento de vitrina (Redis sentinel:gw:events)  (contrato de 3 productores — extensión)

Campo NUEVO OPCIONAL `routing` en el dict del evento (solo lo emite el plano chat y solo
en requests «auto»):
```jsonc
"routing": { "route": "Código y análisis", "score": 0.61,
             "model_selected": "gpt-4o", "degraded": false }
```
- Los productores existentes (gateway, sentinel_audit_logger del motor) NO lo mandan — el
  consumidor (monitor.py) lo renderiza solo si está presente.
- NUEVO: el plano chat publica también el ÉXITO (hoy solo publica bloqueos): status
  reutiliza los existentes de la vitrina (allowed/masked según entidades), tool =
  "chat-ui", con `routing` si aplica. Requisito de SC-004.

## Fila de auditoría  (existente — extensión)

`audit_logs.routing_decision` JSONB nullable = objeto decisión completo (data-model.md §2).
NULL en todo request no-«auto». Fuera de la hash-chain 021 (sin cambio en la cadena).

## GET /api/v1/gw/*  (edge case)

Body byok con `model: "auto"` → se reescribe al `default_model` del router config antes de
reenviar al motor. Sin clasificación semántica en /gw v1.
