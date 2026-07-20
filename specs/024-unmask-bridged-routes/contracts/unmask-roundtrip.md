# Contrato — Round-trip de restauración byok (rutas bridged)

Invariantes que los tests (unit + e2e) hacen cumplir. Aplican a TODA respuesta byok del
motor cuyo request fue enmascarado, sea cual sea el modelo/proveedor que la sirvió.

## No-streaming (respuesta JSON)

1. **Equivalencia salvo reemplazos**: la respuesta entregada al cliente es idéntica a la
   del motor salvo que cada placeholder del mapping fue sustituido por su valor original.
   Ids, `usage`, `stop_reason`, orden y tipos de bloques: intactos (FR-003).
2. **Cobertura de campos**: `text`, `thinking` y `input` de tools (deep) se restauran
   (FR-002) — en respuestas shape-objeto Y shape-dict (D1).
3. **Fail-safe**: sin mapping disponible → respuesta tal cual, HTTP y body intactos
   (FR-005). Jamás un 5xx causado por la restauración.

## Streaming (SSE / items del iterator)

4. **Restauración inter-fragmento**: un placeholder partido entre items se reconstruye
   completo; el texto emitido concatenado es igual al texto original concatenado con los
   reemplazos aplicados — sin pérdida ni duplicación (FR-004).
5. **Framing intacto**: la estructura de eventos SSE que recibe el cliente (tipos de
   evento, índices de bloque, orden) es la misma que emitió el motor; solo cambia el
   contenido textual de los deltas (FR-003).
6. **Cierre limpio**: en fin de stream (normal o truncado), todo carry retenido se emite
   restaurado — 0 texto del usuario perdido (FR-004).
7. **Shape desconocido → passthrough**: un item que el adaptador no reconoce se entrega
   intacto (FR-005); nunca se descarta ni se rompe el stream.

## Evento de monitor (byok)

8. **Identidad completa**: todo evento originado por tráfico byok identificado lleva
   `tool`, `client` y `tenant` no-nulos (FR-006 — hoy: null).
9. **Metadata-only**: el evento jamás contiene `pii_tokens` ni contenido sin enmascarar
   (invariante existente que los tests re-assertan tras el cambio).

## Protección de ida (no regresión)

10. **El upstream nunca ve el dato real**: con masking activo, el prompt que llega al
    modelo contiene placeholders, no valores (SC-003 — mismo estándar de evidencia del
    spike: verificable pidiendo al modelo citar lo que ve).
