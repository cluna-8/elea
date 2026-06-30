# Feature 007 — Rate Limiting & Quotas (Redis-backed)

## Objetivo
Implementar rate limiting por clave virtual usando Redis, aplicando los límites `rpm_limit` y `tpm_limit` que ya existen en el modelo `APIKey`. Devuelve 429 con `Retry-After` cuando se supera el umbral.

## Alcance
- Middleware Redis en el pipeline de chat que verifica rpm y tpm antes de reenviar al motor de IA
- Contadores con ventana deslizante de 60 segundos (INCR + EXPIRE)
- Header `X-RateLimit-Remaining-Requests` y `X-RateLimit-Remaining-Tokens` en cada respuesta
- UI: columnas rpm/tpm en tabla de llaves, editable al crear/ver llave

## Fuera de alcance
- Rate limiting por usuario o grupo (se hereda de la llave)
- Rate limiting global del tenant

## Modelo de datos
`APIKey.rpm_limit` (INT DEFAULT 60) y `APIKey.tpm_limit` (INT DEFAULT 100000) ya existen en DB via migración 005.

## Comportamiento
```
Redis key: ratelimit:key:{key_id}:rpm → INCR, EXPIRE 60s si nuevo
Redis key: ratelimit:key:{key_id}:tpm → INCR by tokens_used, EXPIRE 60s si nuevo
```
Si rpm > rpm_limit → 429 `{"detail": "Límite de solicitudes por minuto superado."}`
Si tpm > tpm_limit → 429 `{"detail": "Límite de tokens por minuto superado."}`

## Restricción white-label
No exponer nombres internos de Redis ni del motor en los mensajes de error.
