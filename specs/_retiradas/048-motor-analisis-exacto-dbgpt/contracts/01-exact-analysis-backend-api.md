# Contrato 1: `/api/v1/exact-analysis/*` — lo que `client/` (Eleia Hub) consume

Este es el único contrato que la spec 046 (`client/`) necesita conocer — nunca habla con DB-GPT
directamente (FR-002 lo prohíbe a nivel de red).

## `POST /api/v1/exact-analysis/workspaces`

Crea un espacio de análisis exacto. Mismo contrato que `POST /workspaces` (spec 043 contrato 1)
con `kind` fijo en `"exact_analysis"` — el caller no lo elige.

**Auth**: sesión JWT válida (igual que cualquier endpoint de `client/`).

**Request**: `{ "display_name": string }`

**Response 200**: `{ "id": uuid, "engine_slug": string, "display_name": string, "kind":
"exact_analysis", "role": "owner" }`

## `POST /api/v1/exact-analysis/workspaces/{id}/files`

Sube una planilla (`.csv`/`.xlsx`/`.xls`) al espacio. Enmascara antes de indexar en DB-GPT (reusa
el pipeline de enmascarado existente).

**Auth**: sesión JWT + membresía del espacio (403 si no es miembro).

**Response 200**: `{ "file_id": string, "columns": [string], "rows_detected": int }` — las
columnas se devuelven para que la UI (spec 046 US1 edge case) pueda mostrarlas.

## `POST /api/v1/exact-analysis/workspaces/{id}/query`

Pregunta en lenguaje natural sobre los archivos del espacio.

**Auth**: sesión JWT + membresía + presupuesto no agotado (402 si lo está, ANTES de reenviar
nada a DB-GPT — FR-008).

**Request**: `{ "question": string }`

**Response 200**: `{ "answer": string, "sql_executed": string | null, "model_used": string }`

**Response 402**: mismo mensaje neutro de presupuesto agotado que el resto de la plataforma
(`MENSAJE_PRESUPUESTO_AGOTADO` en `client/server.js`, o su equivalente del lado del backend).

**Response 502**: mensaje neutro sin nombrar "DB-GPT" (FR-009) — "El servicio de análisis de
datos no está disponible. Intentá de nuevo en unos minutos."

---

# Contrato 2: backend → DB-GPT — DESCUBRIR EN IMPLEMENTACIÓN, no adivinar

Ver `research.md` R2. Este archivo se completa (o se reemplaza por
`contracts/02-dbgpt-real-api.md`) durante `/speckit-implement`, tras inspeccionar tráfico real
contra una instancia viva del contenedor `exact-analysis-engine` — el mismo método ya usado con
éxito este mes contra AnythingLLM. **No escribir `exact_analysis_service.py` contra un contrato
supuesto.**
