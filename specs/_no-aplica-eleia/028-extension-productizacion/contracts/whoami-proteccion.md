# Contrato: bloque `proteccion` en `GET /gw/whoami` (US4)

Extiende la respuesta actual de `whoami` (hoy solo `{ok, user, team, key_label}`, inspect.py:140) con un bloque `proteccion` calculado server-side. La extensión lo consume para el chip de honestidad; **no** lo hardcodea.

## Respuesta (conectado)

```json
{
  "ok": true,
  "user": "...",
  "team": "...",
  "key_label": "...",
  "proteccion": {
    "deteccion": "patrones",
    "titulo": "Detección por patrones",
    "detalle": "En esta superficie la detección de datos personales funciona por patrones conocidos —correo, teléfono, documentos de identidad, credenciales—. No usa análisis lingüístico: puede no reconocer nombres de persona o direcciones escritos en texto libre. <_PISO_SIGUE literal>",
    "capas_delegadas": ["content_moderation", "prompt_injection"]
  }
}
```

## Reglas

- `deteccion ∈ {"patrones", "linguistico"}` — vocabulario **cerrado**, sin nombres de motor (nunca "regex" ni "presidio" en UI de cliente). Regla: plano `gateway` + `pii_detection.requires_service is None` ⇒ `"patrones"`. Hoy `requires_service` está vacío → siempre `"patrones"`.
- `detalle` **termina** con el literal `_PISO_SIGUE` de `backend/src/services/governance_status.py` (fuente única de copy). Un test de contrato verifica que `detalle.endswith(_PISO_SIGUE)`.
- `capas_delegadas` sale de las capas delegables en modo suscripción (moderación, prompt-injection).
- **Fallback** (backend viejo sin el bloque): la extensión asume `"patrones"` (la promesa más chica), nunca `"linguistico"`.

## Prohibido

- Devolver un "protegido" genérico o un booleano de "seguro".
- Nombres de motor/tecnología en cualquier campo visible.
- Que la extensión hardcodee el texto de `detalle` (rompería la fuente única del día que la superficie use análisis lingüístico).

## US5 (motivo de bloqueo) — referencia

El contrato de bloqueo en `/gw/inspect` ya está definido y **implementado por la 027**: `specs/027-governance-configurable-enforcement/contracts/api-gobernanza.md`, sección "Bloqueo en /gw/inspect (superficie browser)". Shape: `{"ok": false, "blocked": true, "blocked_by_layer": "<layer>", "motivo": "<catálogo cerrado>"}`. La 028 solo consume este contrato en la extensión (parsear + mostrar `motivo`, nunca `blocked_by_layer` crudo).
