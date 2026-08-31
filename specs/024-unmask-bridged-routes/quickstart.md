# Quickstart — verificación viva del round-trip (024)

Prerrequisitos: stack dev arriba (`docker compose up -d` — backend :8091, motor :4010),
Ollama en el host con el modelo local (`OLLAMA_CONTEXT_LENGTH=32768 ollama serve` +
`ollama pull qwen3:4b`), y una virtual key byok (seed del spike batch 1 o
`seed_client` — ver `specs/019-integration-surfaces/spikes-batch1.md`).

```bash
KEY="sk-sentinel-…"          # virtual key byok
GW="http://localhost:8091/api/v1/gw"

# 1) No-streaming: el email DEBE volver en claro (hoy: placeholder)
curl -s $GW/v1/messages -H "Authorization: Bearer $KEY" -H "content-type: application/json" \
  -d '{"model":"ollama-qwen3-4b","max_tokens":800,"messages":[{"role":"user","content":"El paciente con email laura.perez@hospital.es llamó ayer. Repite la frase tal cual. /no_think"}]}' \
  | grep -o "laura.perez@hospital.es" && echo "✅ unmask no-streaming"

# 2) Streaming: ídem sobre los deltas concatenados
curl -sN $GW/v1/messages -H "Authorization: Bearer $KEY" -H "content-type: application/json" \
  -d '{"model":"ollama-qwen3-4b","max_tokens":800,"stream":true,"messages":[{"role":"user","content":"El paciente con email laura.perez@hospital.es llamó ayer. Repite la frase tal cual. /no_think"}]}' \
  | grep -o '"text": "[^"]*"' | paste -sd' ' - | grep -o "laura" && echo "✅ unmask streaming"

# 3) Protección de ida intacta: el modelo debe citar el PLACEHOLDER, no el valor
#    (pedirle "escribe el texto exacto que ves como email" → [EMAIL_ADDRESS_…])

# 4) Atribución: el evento lleva tool/client/tenant no-nulos
curl -s "$GW/events?limit=1" -H "Authorization: Bearer $KEY" | python3 -m json.tool
#    → "tool": "...", "client": "spike-ollama", "tenant": "default"   (hoy: null)

# 5) Suite automatizada equivalente:
docker compose run --rm --no-deps backend pytest tests/unit/test_unmask_shapes.py tests/e2e/test_engine_roundtrip_e2e.py -q
```
