# Quickstart: Motor de análisis exacto de datos (DB-GPT)

Validación end-to-end contra un despliegue local, mismo criterio que los quickstarts de 043/044.

## Prerrequisitos

- `docker compose up` de este repo con el servicio `exact-analysis-engine` agregado (ver
  `plan.md` Project Structure).
- Credenciales reales de Azure OpenAI ya en `.env` (mismas que usa el resto del producto).
- Un usuario de prueba con sesión válida en el Hub.
- Una planilla real con al menos dos archivos relacionables (para probar el cruce, FR-010) y una
  columna con un dato personal (para probar el enmascarado, US3).

## Pasos

1. **Aislamiento de red (SC-003)**: `docker network inspect` de la red donde corre
   `exact-analysis-engine` confirma que ningún puerto está publicado al host; desde un contenedor
   fuera de la red interna del backend, un intento de conexión al contenedor falla.
2. **Crear espacio de análisis exacto**: `POST /api/v1/exact-analysis/workspaces`.
3. **Subir dos planillas relacionadas** al mismo espacio.
4. **Preguntar algo que cruce ambas** ("¿cuánto sumó X en la planilla A para los que aparecen en
   la planilla B?") → la respuesta es correcta, verificada a mano contra los archivos originales
   (SC-001).
5. **Costos → Gasto por usuario**: confirmar que el gasto de esa pregunta aparece bajo la persona
   real, con un modelo del catálogo de Eleia (SC-002).
6. **Enmascarado**: preguntar algo que NO involucre directamente la columna de dato personal y
   confirmar, en el log de auditoría de la llamada saliente, que la columna protegida no viajó en
   claro (SC-004).
7. **Aislamiento entre personas**: con una segunda persona y su propio espacio, confirmar que
   ninguna pregunta de una ve datos de la planilla de la otra (US2 de spec.md).
8. **Motor caído**: parar el contenedor `exact-analysis-engine` y preguntar algo → mensaje neutro,
   sin nombrar "DB-GPT", sin error técnico crudo (mismo estándar que el bug ya corregido en el
   chat RAG, CHANGELOG 044 §14).

## Qué confirma cada paso

Cada paso mapea 1:1 a un `SC-00X` de `spec.md` — si alguno falla, la spec no está lista para
cerrarse como implementada, sin importar que el código "compile".
