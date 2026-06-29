# Changelog — Feature 007: Rate Limiting & Quotas

## [1.0.0] — 2026-06-30

### Added

**Backend**
- `backend/requirements.txt` — `redis==5.0.8`
- `backend/src/services/redis_client.py` — singleton Redis con fail-open: si Redis no está disponible, el rate limiting se omite sin romper el servicio
- `backend/src/services/rate_limiter.py` — `check_rpm(key_id, rpm_limit)` y `check_tpm(key_id, tpm_limit, tokens_used)`; patrón INCR + EXPIRE 60s; lanza `RateLimitExceeded` con `retry_after`
- `backend/src/api/chat.py` — verifica RPM antes de llamar al motor; verifica TPM después con tokens reales; headers `X-RateLimit-Remaining-Requests` y `X-RateLimit-Remaining-Tokens` en cada respuesta; renamed param `response → http_resp` para evitar colisión con variable httpx
- `backend/src/api/keys.py` — campos `rpm_limit` y `tpm_limit` en `KeyCreateSchema`, `KeyResponseSchema` y persistencia en DB
- `docker-compose.yml` — servicio `basa-redis` con healthcheck; variables `REDIS_HOST` y `REDIS_PORT` en entorno de litellm

**Frontend**
- `frontend/src/pages/UsersPage.tsx` — columna "Límites RPM/TPM" en tabla de llaves; inputs `rpm_limit` y `tpm_limit` en modal de nueva llave (defaults: 60 RPM, 100 000 TPM)

### Bugs Fixed
- `backend/src/api/chat.py` — renombrado parámetro `response: Response` a `http_resp: Response` para evitar que el objeto FastAPI `Response` tapara la variable local `response` del cliente httpx, lo que causaba que todos los errores de red retornaran 500 en lugar de activar el fallback simulado

### Design Decisions
- **Fail-open**: si Redis no responde, la llamada continúa sin rate limiting. Esto evita que Redis sea un punto único de fallo en un sistema sanitario.
- **Ventana fija de 60s**: se usa INCR + EXPIRE en lugar de sliding window para simplicidad y atomicidad sin Lua scripts.
- **TPM post-call**: los tokens reales solo se conocen tras la respuesta del motor, por lo que el check TPM se hace a posteriori. El límite se aplica en la siguiente llamada.
