# Quickstart — verificación viva de la gobernanza honesta (027)

Guía de verificación manual mapeada a los Success Criteria de la [spec](./spec.md).
Cada escenario es reproducible con el stack dev de Docker Compose. Los `layer_key`
exactos y el contrato de la API los fijan [data-model.md](./data-model.md) y
[contracts/](./contracts/); acá se usan los códigos del registry `GOVERNANCE_LAYERS`.

## Prerrequisitos

Stack dev arriba (`docker compose up -d`) con los puertos reales del
`docker-compose.yml`: backend **:8091** (línea 85), motor **:4010** (línea 44),
frontend **:8090** (línea 130), Postgres **:5433** (línea 13). Master key del motor:
`basa_master_key_9999` (default de `docker-compose.yml:47`).

```bash
API="http://localhost:8091/api/v1"
MK="basa_master_key_9999"

# Sesión admin (el primer login bootstrapea el usuario admin — users.py:34-45)
TOK=$(curl -s $API/users/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# Virtual key (sk-basa-…) para tráfico hacia modelos de la pasarela:
# seed_client (specs/019-integration-surfaces/spikes-batch1.md) u onboarding existente.
# Para SC-006 la Connection debe tener tool_type=claude-code (superficie CONFIABLE, D5).
KEY="sk-basa-…"

# Token de suscripción para el passthrough /gw/v1/messages. En dev sin suscripción real
# alcanza un placeholder: el upstream rechazará el reenvío, pero la política y la
# atribución corren ANTES y quedan registradas igual.
SUB_TOKEN="sk-ant-oat-placeholder-dev"
```

---

## SC-001 — Cero capas fantasma: el estado que se muestra es el que corre

**UI**: abrir `http://localhost:8090` → login admin → página **Gobernanza**.
Esperado:

- Las capas del **piso** (interceptar/registrar, detección de PII, bloqueo de
  secretos — más la evaluación AI-Act como evaluación) y `pii_masking`
  (gobernable, on por default) figuran **aplicándose**.
- Las capas de proveedor sembradas (`guardian_service.py:70-141`: moderación de
  contenido, anti-inyección, content-safety Azure ×2, Bedrock, Presidio) figuran
  **no_disponible** o **requiere_credencial**, con motivo. **Ninguna como activa.**

**API** (misma verdad, automatizable):

```bash
# 1) Estado calculado del backend
curl -s $API/governance/status -H "Authorization: Bearer $TOK" | python3 -m json.tool

# 2) La sonda directa al motor confirma que solo existe UN guardrail cargado
curl -s http://localhost:4010/guardrails/list -H "Authorization: Bearer $MK"
#    → una sola entrada: "basa-guardian". Los 5 nombres de proveedor del seed NO están.

# 3) Cruce SC-001: ninguna capa de plano engine con estado aplicandose fuera de la sonda
curl -s $API/governance/status -H "Authorization: Bearer $TOK" | python3 -c '
import sys,json
capas=json.load(sys.stdin)["layers"]
malas=[c for c in capas
       if c["estado_efectivo"]=="aplicandose" and "engine" in c.get("planes",[])
       and c["tier"]!="floor"]
print("engine aplicandose:", [c["layer_key"] for c in malas] or "solo lo confirmado por la sonda ✅")'
```

Chequeo white-label (Principio VII): la respuesta de `/governance/status` **no**
contiene nombres de guardrail del proveedor (`engine_guardrail_name` sigue `None`
en la API pública, patrón de `guardians.py:57`); el payload crudo de la sonda
jamás llega a la UI.

---

## SC-002 — Resumen por modo en una sola vista

En la página **Gobernanza**, el bloque de resumen por modo responde en una vista:
*qué protege hoy al tráfico de suscripción* y *qué protege al tráfico hacia
modelos de la pasarela* (piso + opcionales resueltas por la cascada), sin leer
código ni archivos, en menos de 1 minuto. La misma agrupación viene en el payload
de `GET /governance/status` (bloque por `connection_mode`), así el criterio es
verificable por API además de a ojo.

---

## SC-003 / FR-004 — Capa opcional solo para modelos de la pasarela

```bash
# 1) Decisión por alcance: una capa opcional ON solo para modelos de la pasarela
#    (layer_key opcional del registry — ver data-model.md; contrato exacto en contracts/)
curl -s -X PUT $API/governance/profile -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d '{"scope_type":"connection_mode","scope_value":"gateway-models","layer_key":"content_moderation","decision":"on"}'

# 2) Tráfico de SUSCRIPCIÓN: passthrough /gw/v1/messages con token de suscripción
#    (en dev sin suscripción real el upstream puede rechazar el token: la evaluación
#    del perfil y la atribución ocurren ANTES del reenvío y quedan registradas igual)
curl -s $API/gw/v1/messages -H "Authorization: Bearer $SUB_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"model":"claude-sonnet-4-20250514","max_tokens":50,"messages":[{"role":"user","content":"ping suscripcion"}]}'

# 3) Tráfico hacia MODELO DE LA PASARELA: chat del producto contra el motor
curl -s $API/chat/completions -H "Authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -d '{"message":"ping pasarela","model":"ollama-qwen3-4b"}'

# 4) Las capas aplicadas DIFIEREN y quedan en applied_layers del audit
docker compose exec db psql -U basa_admin -d basa_gateway -c \
  "SELECT jsonb_pretty(applied_layers), blocked_by_layer
     FROM audit_logs ORDER BY timestamp DESC LIMIT 2;"
```

Esperado: el pedido de pasarela lista la capa opcional (o su estado honesto
`not_configured`/`requires_credential` si el motor no la tiene cargada — nunca
`applied` fabricado); el de suscripción **no** la lista. El piso aparece en ambos.
`applied_layers` lleva solo códigos y estados (C1) — jamás texto ni PII.

---

## SC-004 — El piso no se puede apagar

```bash
# Intentar apagar una capa de tier=floor → 422, y el intento queda registrado
curl -s -o /dev/null -w "%{http_code}\n" -X PUT $API/governance/profile \
  -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d '{"scope_type":"tenant_default","scope_value":"*","layer_key":"secret_detection","decision":"off"}'
#   → 422

# El intento rechazado tiene su entrada de auditoría (FR-003)
curl -s "$API/audit-logs?limit=5" -H "Authorization: Bearer $TOK" | python3 -m json.tool
```

Verificación estructural extra: `governance_profiles` no tiene ninguna fila capaz
de representar el piso apagado — el piso vive en el registry en código (D1), no en
la DB.

---

## SC-005 — Todo bloqueo es atribuible a una capa

```bash
# Provocar un bloqueo con un secreto de formato sk- clásico (secret_detection, action BLOCK)
curl -s -o /dev/null -w "%{http_code}\n" $API/chat/completions \
  -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d '{"message":"mi clave es sk-abcdef1234567890abcdef1234567890abcdef123456","model":"ollama-qwen3-4b"}'
#   → 4xx con motivo de bloqueo

# Atribución en el evento del monitor (feed Redis, monitor.py:23)
curl -s "$API/gw/events?limit=3" | python3 -m json.tool
#   → el evento del bloqueo lleva blocked_by_layer = "secret_detection" (código del
#     registry, no el nombre de display) y el desglose applied_layers

# Donde exista fila durable, blocked_by_layer es queryable con un WHERE plano:
docker compose exec db psql -U basa_admin -d basa_gateway -c \
  "SELECT timestamp, blocked_by_layer FROM audit_logs
     WHERE blocked_by_layer IS NOT NULL ORDER BY timestamp DESC LIMIT 5;"
```

> **Nota honesta (corte con la 018, research D6)**: en el plano motor un bloqueo
> hace `return reason` → LiteLLM levanta 400 → el logger de éxito no se dispara;
> y en el backend los `raise` preceden al log. **La fila durable del bloqueo NO es
> de esta spec**: 027 define los campos, emite la atribución en el punto de bloqueo
> y la publica en el evento de monitor; la durabilidad es alcance de la 018. Este
> quickstart verifica la atribución donde 027 la promete — no la marca verde donde
> no puede sostenerla.

---

## SC-006 — Cambiar la postura desde la UI, sin tocar archivos

1. En la página **Gobernanza**, cambiar una decisión (p. ej. `pii_masking` → off
   para la superficie `claude-code` — legal por D5 refinada: la relajación aplica
   **solo** a Connections con `tool_type=claude-code`, superficie confiable; el
   tráfico con superficie UA-derivada no se relaja jamás). El guardado es **por
   control** (autosave con rollback, D7): no hay botón global, no hay estado sin
   guardar que perder.
2. Sin reiniciar contenedores ni editar ningún archivo:

```bash
# El cambio ya está en el estado calculado
curl -s $API/governance/status -H "Authorization: Bearer $TOK" | grep -A3 pii_masking

# Invalidación del cache de identidad del motor (60 s por key_hash,
# custom_auth.py:64-66): tráfico INMEDIATO por la key afectada ya refleja
# la decisión nueva — sin esperar el minuto
curl -s $API/gw/v1/messages -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model":"ollama-qwen3-4b","max_tokens":50,"messages":[{"role":"user","content":"Escribe a laura.perez@hospital.es"}]}'
docker compose exec db psql -U basa_admin -d basa_gateway -c \
  "SELECT jsonb_pretty(applied_layers) FROM audit_logs ORDER BY timestamp DESC LIMIT 1;"
```

Si el segundo pedido siguiera aplicando la decisión vieja durante ~1 minuto, la
invalidación no funciona y SC-006 es **falso** — es exactamente el gotcha que el
plan obliga a cubrir (Constraints, plan.md).

### El caso redact-off: PII detectada, no enmascarada por configuración

Con `pii_masking` en off (paso anterior), mandar un prompt con PII (el email de
arriba). Esperado (D8 / FR-002): la detección del piso **sí corre**, y el registro
dice explícitamente *"PII detectada, no enmascarada por configuración"* — en
`applied_layers`, `pii_detection` queda `applied` con su `count` y `pii_masking`
queda `skipped`, visible también en la vista de Gobernanza. La PII **nunca
desaparece del relato**. Y en la vitrina (`/gw/events`), el `masked_preview` sigue
**enmascarado para display** aunque el tráfico haya salido en claro (contrato del
evento §10): la postura legítima de D8 jamás convierte el feed en canal de fuga.

---

## SC-007 — Tenant nuevo: piso activo y postura default sin configurar nada

```bash
# 1) Crear un tenant fresco (sin ninguna fila de gobernanza)
docker compose exec backend python -c "
from src.database import SessionLocal
from src.models.tenant import Tenant
db = SessionLocal()
t = Tenant(name='Tenant Quickstart 027', slug='qs-027')
db.add(t); db.commit(); print(t.id)"

# 2) Cero configuración para él…
docker compose exec db psql -U basa_admin -d basa_gateway -c \
  "SELECT count(*) FROM governance_profiles WHERE tenant_id = '<ID_DEL_PASO_1>';"
#   → 0

# 3) …y aun así su estado muestra piso activo + postura default EXPLÍCITA
#    (tenant_id: solo tier super-admin — garantía (g) del contrato; el admin de
#     una instalación single-tenant lo tiene)
curl -s "$API/governance/status?tenant_id=<ID_DEL_PASO_1>" -H "Authorization: Bearer $TOK" | python3 -m json.tool
#   → capas del piso aplicándose; opcionales con su default de producto declarado
#     (ausencia de fila = heredar, D2 — nunca un estado vacío ni ambiguo)
```

---

## Estado honesto con el motor caído (fail-closed)

```bash
docker stop basa-litellm
sleep 35   # TTL del cache de la sonda ~30 s (D4)

curl -s $API/governance/status -H "Authorization: Bearer $TOK" | python3 -m json.tool
#   → toda capa de plano engine cae a "no_disponible" con motivo (motor inalcanzable),
#     JAMÁS "aplicandose". El copy distingue "no la aplicamos nosotros" de
#     "estás desprotegido" (FR-013).

docker start basa-litellm && sleep 35
curl -s $API/governance/status -H "Authorization: Bearer $TOK"
#   → los estados se recuperan solos al volver la sonda
```

---

## Resultados esperados (resumen)

| SC | Verde cuando |
|---|---|
| SC-001 | Ninguna capa `aplicandose` sin confirmación de la sonda/evidencia; proveedor = `no_disponible`/`requiere_credencial` |
| SC-002 | Un solo lugar responde qué protege cada modo, <1 min, sin archivos |
| SC-003 | Las `applied_layers` de suscripción vs pasarela difieren según lo configurado; piso en ambas |
| SC-004 | `off` sobre tier=floor → 422 + intento auditado |
| SC-005 | `blocked_by_layer` con código de capa en el evento del monitor (fila durable: 018) |
| SC-006 | Cambio desde la UI visible al instante en status y en el tráfico (cache invalidado) |
| SC-007 | Tenant sin filas → piso activo + defaults explícitos |
| — | Motor caído → `no_disponible` con motivo; redact-off → "PII detectada, no enmascarada por configuración" |

Suite automatizada equivalente (cuando exista, Fase 2): contract test SC-001 contra
la imagen pineada + integración de perfil por modo/superficie —
`docker compose run --rm --no-deps backend pytest tests/contract/ tests/integration/ -q`.
