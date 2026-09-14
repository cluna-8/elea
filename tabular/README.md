# tabular — motor de análisis de Excel/CSV de Eleia Hub

Spec: [050-ia-hub-conector-motores](../specs/050-ia-hub-conector-motores/spec.md), contrato
[03-motores.md §3.2](../specs/050-ia-hub-conector-motores/contracts/03-motores.md).

**Qué hace:** recibe archivos `.csv`/`.xlsx` de un espacio, los carga en una base DuckDB propia
de ese espacio (cada hoja = una tabla), y responde preguntas en lenguaje natural pidiéndole el
SQL a Guardian, validándolo como solo lectura y ejecutándolo con límites. Cruza archivos con
`JOIN` de forma nativa.

**Qué NO hace:** no habla con ningún proveedor de modelos (solo con `engine:4000/v1` de Guardian,
con su llave `svc.tabular`); no autoriza personas (eso lo hace el Hub contra Guardian antes de
llamar acá); no guarda conversación (el Hub manda un historial corto en cada pregunta); no usa
embeddings.

## API (`/v1`, red interna)

Cabeceras obligatorias: `Authorization: Bearer <TABULAR_INTERNAL_TOKEN>` y `X-Hub-User-Id`
(se reenvía a Guardian como `X-Guardian-Acting-User`).

| Ruta | Qué hace |
|---|---|
| `POST /v1/spaces` `{workspace_id}` | crea la base del espacio (201 / 409 si existe) |
| `POST /v1/spaces/{ws}/files` multipart `file` | carga csv/xlsx (≤ 50 MB); devuelve tablas, columnas, filas y muestra |
| `GET /v1/spaces/{ws}/files` | lista archivos y tablas |
| `DELETE /v1/spaces/{ws}/files/{file_id}` | borra archivo y sus tablas |
| `PUT /v1/spaces/{ws}/dictionary` `{tables: {alias: {columna: descripción}}}` | diccionario de datos: qué significa cada columna; viaja al modelo en cada pregunta |
| `POST /v1/spaces/{ws}/query` `{question, history[]}` | `{sql, columns, rows, answer, model_used}` |
| `GET /health` | sin auth, para el healthcheck |

Errores con código estable en `detail.code`: `unauthorized`, `missing_user`, `space_not_found`,
`space_exists`, `unsupported_format`, `file_too_large`, `empty_file`, `no_files`, `unsafe_sql`,
`sql_error`, `not_answerable`, `engine_error` (con `status` 400/401/402 del engine), `timeout`.

## Cómo ve el modelo cada espacio

Por cada tabla: alias corto `tN` (vista DuckDB; el nombre largo confundía al firewall, que lo
tomaba por un nombre de persona), nombre legible (archivo y hoja original), columnas con tipo,
rótulo original de la planilla y descripción del diccionario si la hay, 5 filas de ejemplo, y las
columnas en común entre tablas (claves para JOIN). El encabezado real se detecta aunque haya
título y notas arriba (planillas armadas a mano). Acentos normalizados en los nombres técnicos.

## Seguridad del SQL (FR-023), dos capas

1. `app/sqlguard.py`: una sola sentencia `SELECT`/`WITH`; sin funciones de archivo ni de
   sistema; sin tablas que sean rutas o URLs; solo tablas del espacio; `LIMIT 500` forzado.
   Lo que no pasa se rechaza, nunca se "sanea". Un reintento con el motivo al modelo. Si sqlglot
   no puede interpretar la consulta (p. ej. muy larga), pasa una validación conservadora sin AST
   (forma SELECT, sin palabras ni funciones prohibidas, sin comentarios ni comillas sin cerrar) y
   la decide la conexión de solo lectura.
2. `app/store.py`: la consulta corre en una conexión DuckDB `read_only=True` con
   `enable_external_access=false`, `memory_limit`, `threads=2`, `lock_configuration=true`
   y `interrupt()` a los 20 s.

## Modelo

Default `azure-gpt-5.4-mini` (`TABULAR_MODEL`). Comparado el 12-sep-2026 con tres planillas reales
de Elea (ventas 10.920 filas, forecast 37.379, stock 3.393) contra la verdad calculada con pandas:
5.4-mini acertó 5/5 (incluidos dos JOIN ventas↔forecast y un top-5 con nombre de producto);
4o-mini acertó 3/5, no resolvía los JOIN e inventaba conteos en la redacción.

## Desarrollo

```bash
cd tabular && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest -q
```

Compose: perfil `tabular` (`docker compose --profile tabular up -d --build tabular`). Variables en
`.env.example` (sección "Motor tabular"). La llave `svc.tabular` la crea el instalador
(`elea-installer/install.sh`, `create_service_key`).
