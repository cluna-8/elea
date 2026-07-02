# Plan — Feature 007: Rate Limiting & Quotas

> As-built: documenta lo que se implementó.

## Archivos creados

| Archivo | Descripción |
|---------|-------------|
| `backend/src/services/redis_client.py` | Singleton Redis (compartido con 006) |
| `backend/src/services/rate_limiter.py` | `check_rpm(key_id, limit)` y `check_tpm(key_id, limit, tokens)` con ventana deslizante 60s |

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `backend/src/api/chat.py` | Rate limit RPM pre-call (429 si supera); rate limit TPM post-call con tokens reales; headers `X-RateLimit-Remaining-Requests` y `X-RateLimit-Remaining-Tokens` |
| `backend/requirements.txt` | `redis` agregado |
| `frontend/src/pages/UsersPage.tsx` | Columnas rpm_limit / tpm_limit en tabla de llaves virtuales |

## Decisiones clave

- Ventana deslizante con `INCR + EXPIRE` en Redis: contador por `key_id:rpm` y `key_id:tpm:{minuto}`.
- TPM se verifica post-call porque los tokens reales se conocen en la respuesta del motor.
- Límites `0` = sin restricción (no bloquea).
- Si Redis no responde, rate limiting se omite (fail-open) — consistente con política de alta disponibilidad del servicio.
