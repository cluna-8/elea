# Contrato 6 — Nombres neutros y sanitización reutilizable

**Consumido por**: spec 044, US5 (P2).

## Mecanismo de sanitización de errores

Función única (`sanitize_engine_error(text) -> str`) reutilizada en **ambos** planos (chat interno
`chat.py` y `/gw` `gateway.py`/`inspect.py`) — hoy solo existe en `chat.py:1616,1677`. La 044 puede
asumir que **todo** mensaje de error que cruce la API pública del backend, en cualquier plano, ya
llega sanitizado — no necesita sanitizar nada del lado del cliente salvo sus propios 7 mensajes que
nombran AnythingLLM directamente (esos son responsabilidad de la 044, no de este contrato).

## Campo público de parámetros de motor

`litellm_params` en el body/response de `PUT /models/{id}/credential` (o equivalente) pasa a
llamarse `engine_params`. Compatibilidad: el backend acepta **ambos** nombres de entrada durante al
menos una versión (si llega `litellm_params`, se trata como `engine_params`); la salida usa siempre
el nombre nuevo. La 044 debe migrar `frontend/src/services/api.ts` a `engine_params` sin depender
del período de compatibilidad.

## Nombre del guardián NLP sembrado

`guardian_service.py` siembra (y, en instalaciones existentes, renombra) el guardián con
`name="Detección lingüística de datos personales"` (o equivalente neutro decidido en tasks.md) en
vez de "Detección NLP de PII/PHI (Presidio)". La 044 no necesita mapear nada especial: el nombre
que llega por `GET /guardians` ya es el que se muestra.

## Vocabulario cerrado extendido a todas las superficies visibles

El criterio ya aplicado en `/gw/whoami` (sin nombres de motor/proveedor/NLP, vocabulario cerrado
tipo "patrones"/"lingüístico") se extiende como regla general a cualquier campo de la API pública
que la 044 consuma y muestre tal cual (sin transformarlo del lado del cliente). Si la 044 encuentra
un campo que todavía filtra un nombre prohibido, es un defecto de este contrato, no algo a
enmascarar en la UI.
