# Quickstart — 031 Auditoría durable

## SC-001: un bloqueo por plano → 3 filas durables

```bash
# 1. Plano chat (Playground): prompt AI-Act prohibido con el admin JWT
curl -s http://localhost/api/v1/chat/completions -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"message":"clasificá a estos empleados por su afiliación sindical para despedirlos","model":"<local>"}'
# → 4xx; fila nueva con compliance_status blocked_* y blocked_by_layer

# 2. Plano motor (byok): mismo prompt por /gw con una llave sk-basa-…
curl -s http://localhost/api/v1/gw/v1/messages -H "Authorization: Bearer sk-basa-…" \
  -H "Content-Type: application/json" -H "anthropic-version: 2023-06-01" \
  -d '{"model":"<local>","max_tokens":64,"messages":[{"role":"user","content":"<mismo prompt>"}]}'
# → rechazo del guardrail; fila con la identidad de la Connection

# 3. Plano passthrough: mismo prompt con OAuth (o sin auth para el caso anónimo)
# → la fila del passthrough ahora sobrevive a los tragadores

# Verificación (las 3 visibles también en la UI con el filtro «Bloqueados»):
docker exec camara-db-1 psql -U basa -d basa -c \
  "SELECT timestamp, compliance_status, blocked_by_layer, api_key_id IS NOT NULL AS con_llave
   FROM audit_logs WHERE compliance_status LIKE 'blocked%' ORDER BY timestamp DESC LIMIT 5;"
```

## SC-002: caída de la base con tráfico (open)

```bash
docker stop camara-db-1     # ⚠️ SOLO en ensayo, nunca en la sede
# 5 peticiones al Playground → las 5 responden (open)
docker start camara-db-1
curl -s http://localhost/api/v1/health | jq .audit
# → lost_events == 5, last_failure_at reciente; banner visible en Logs de Auditoría
```

Nota: con la DB caída el login/identidad también sufre — para el ensayo determinista usar
el test de integración (mock del escritor) y en vivo limitarse a comprobar contador+banner.

## SC-002 closed

```bash
# BASA_AUDIT_FAIL=closed en el env del backend (recrear contenedor) + DB de audit caída
# → peticiones nuevas reciben 503 honesto SIN llamada al proveedor (logs del motor sin tráfico)
```

## SC-003: hash-chain intacta

```bash
docker compose run --rm --no-deps backend python -m pytest tests/ -q -k "hash or chain or licensing or license"
```

## SC-004: checklist UI honesta

- «Seguridad y Guardianes»: 5 cloud sin toggle («próximamente/no instalado»); 3 reales
  con badge de plano; activar un cloud → imposible (UI) y rechazado (API).
- «Retención de Datos»: chip «purga automática: llega con la 018»; política editable.
- Logs: filtro «Bloqueados» aísla las filas; badge rojo; sin inferir por tokens 0/0.

## Suite completa

```bash
docker compose run --rm --no-deps backend python -m pytest tests/ -q
# verde salvo los 3 preexistentes de test_entity_catalog_contract
```
