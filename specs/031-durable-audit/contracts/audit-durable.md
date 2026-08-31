# Contract — 031 Auditoría durable

## Fila de bloqueo en `audit_logs` (sin cambio de esquema)

| Columna | Valor en bloqueo |
|---|---|
| compliance_status | `blocked_<motivo>` (convención D1; los existentes `blocked_prohibited`/`blocked_secret` no cambian) |
| blocked_by_layer | código de capa del registry 027 (obligatorio en bloqueos) |
| model | modelo solicitado (o efectivo si venía de «auto», con routing_decision poblado) |
| prompt_tokens / completion_tokens | 0 / 0 |
| cost_usd | 0 |
| masked_entities | conteos por tipo si el punto los tiene (jamás valores) |
| user_id / api_key_id / tenant_id / user_group_id | atribución disponible (NULL si anónimo — el intento se registra igual) |
| latency_ms | hasta el momento del bloqueo |

Filtro canónico de bloqueos (API + UI): `compliance_status LIKE 'blocked%'`.

## POST /api/v1/internal/audit (existente — extensión retrocompatible)

Campos nuevos OPCIONALES en `AuditEntry` (los que falten hoy): `compliance_status`
(default actual se conserva), `blocked_by_layer`. El INSERT (internal.py:90) incorpora las
columnas. Emisor nuevo: `sentinel_guardrail.py` en bloqueo (antes solo el logger de éxito).
Auth: mismo secreto interno. Reglas: el guardrail POSTea ANTES de rechazar; 1 reintento.

## GET /api/v1/internal/audit/probe (nuevo, secreto interno)

200 `{"writable": true}` si un `SELECT 1` sobre la sesión de auditoría responde dentro del
timeout corto; 503 si no. Lo usa el guardrail del motor en modo `closed` (pre-check).
Cacheable 5 s por el llamador si la latencia lo exige (riesgo R2 del research).

## Config

`SENTINEL_AUDIT_FAIL=open|closed` (env; default `open` si ausente/ilegible). La leen: backend
(audit_service + chat + gateway) y extensiones del motor. compose.prod.yml la cablea a
ambos contenedores; el perfil camara la declara `open` explícita.

## GET /api/v1/health (endpoint nuevo; el /health raíz NO cambia)

Decisión de implementación (T009, aceptada): el `/health` raíz es el healthcheck del
contenedor — meterle Redis+DB convertiría una degradación en reinicio en loop. El bloque
`audit` vive en `GET /api/v1/health`, **autenticado** (admin/compliance_officer): publicar
«llevo N eventos sin registrar» a anónimos es señalar el mejor momento para fugar datos.

```jsonc
"audit": { "mode": "open", "lost_events": 0, "last_failure_at": null }
```
En `closed` con auditoría caída el estado global del health refleja degradado.

## Semántica `closed` (FR-005)

- chat/passthrough: pre-check de escribibilidad ANTES de llamar al proveedor → 503 honesto
  `{"detail": "auditoría no disponible — la instalación exige registro (audit_fail=closed)"}`
  (texto final en implementación, mismo tono que el 402 de licencias).
- motor: guardrail pre-check vía `/internal/audit/probe` → rechazo honesto mismo mensaje.
- Petición ya aceptada (streaming en curso): se completa; el corte aplica a las siguientes.

## Contador de pérdidas (Redis)

- `sentinel:audit:lost` — INCR al agotar reintentos (backend y extensiones motor).
- `sentinel:audit:last_fail` — SET timestamp ISO en cada pérdida.
- Sin TTL (constancia hasta reset manual/redeploy de Redis). Redis caído → solo logger.

## UI

- **Logs de Auditoría**: filtro «Bloqueados» (LIKE blocked%), badge rojo por fila
  bloqueada (estado explícito, no tokens 0/0); banner ámbar si `health.audit.lost_events
  > 0`: «N eventos no registrados desde HH:MM».
- **Seguridad y Guardianes**: 5 cloud = tarjeta «próximamente / no instalado», sin toggle
  (backend rechaza activación sin guardrail cargado); 3 reales = toggle actual + badge de
  plano(s) de ejecución.
- **Retención de Datos**: política editable + chip «purga automática: llega con la 018».
