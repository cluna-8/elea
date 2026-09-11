# Contrato 3 — Identificador de documento en el enmascarado

**Consumido por**: spec 044, US3 (P1).

## Cambio en `POST /gw/inspect`

Campo nuevo, opcional, en el body:
```json
{"text": "...", "tool": "elea-rag-client", "document_id": "a1b2c3d4-...uuid-v4"}
```

- `document_id` MUST ser generado por el cliente (Hub Chat) **una vez por subida**, MUST reenviarse
  igual en todos los chunks del mismo documento, y MAY reutilizarse en un reintento de la misma
  subida (mismo resultado, ver Edge Case de la spec 043).
- Si se omite, el comportamiento es el actual (nonce aleatorio por request) — **sin regresión**
  para otros clientes del despliegue compartido Guardian (FR-021).
- No es PII, no se persiste más allá de la vida del request y de lo que ya persiste la bóveda de la
  spec 042 bajo su clave de placeholder habitual (sin cambio ahí).

## Garantía de determinismo (FR-020/022/023)

Con el mismo `document_id`, el mismo valor detectado (mismo string exacto, ver límites de span en
`diagnostico.md` §2) MUST producir el mismo placeholder `[TIPO_n_hex]` en cualquier chunk de esa
subida. Con `document_id` distinto (otra subida, incluso del mismo contenido), el placeholder para
el mismo valor MUST ser distinto — no se crea un identificador estable entre documentos.

## Respuesta de `/gw/inspect` (sin cambios de forma)

Sigue devolviendo `masked` y `replacements` como hoy; el resumen agregado por documento completo
(para el "resumen de protección por documento" de la 044 US3) lo arma el Hub Chat sumando las
respuestas de sus propios chunks — no requiere un endpoint nuevo, salvo que `tasks.md` decida que
conviene un endpoint de cierre de documento (`POST /gw/inspect/close` o similar) para simplificar
el cliente; si se agrega, es una extensión de este contrato, no un contrato nuevo.

## Documentos subidos antes de este cambio (FR-008 de la 044)

No hay forma de saber, del lado del motor, si un documento viejo tiene placeholders no
relacionables — esa marca la lleva el Hub Chat (fecha de subida vs. fecha de despliegue de esta
feature, o un flag propio que el Hub ya gestione). Este contrato no expone nada nuevo para eso.
