---

description: "Task list — spec 046: Análisis exacto de datos (Excel/CSV) en Eleia Hub"

---

# Tasks: Análisis exacto de datos (Excel/CSV) en Eleia Hub

**Numeración**: continúa la secuencia global (última usada: T097, spec 048).

## Phase 1: Setup

- [X] T098 Rutas proxy en `client/server.js`: `POST /api/exact-analysis/workspaces`,
      `POST /api/exact-analysis/workspaces/:id/files`, `POST /api/exact-analysis/workspaces/:id/query`
      — 1:1 hacia el backend (spec 048, ya probado en vivo), con la misma sesión del Hub

## Phase 2: User Story 1 - Preguntar y obtener un cálculo exacto (Priority: P1)

- [X] T099 [US1] Tab lateral "Análisis exacto" en el sidebar — sección propia, nunca mezclada
      con la lista de espacios RAG (FR-001/US2). **Bug real encontrado en vivo (11-sep) y
      corregido el mismo día**: los espacios `kind=exact_analysis` SÍ quedaban aislados en su
      propia sección dentro del modo "Análisis exacto", pero también aparecían en la lista de
      espacios del modo Chat normal — `GET /api/workspaces` (backend de `renderWorkspaceList()`
      de `#view-hub`) no filtraba por `kind`. Corregido en `client/server.js`: la ruta ahora
      excluye `kind=exact_analysis` de su respuesta (mismo criterio inverso que ya usaba
      `/api/exact-analysis/workspaces`, que solo INCLUYE ese kind). Regresión cubierta en
      `client/tests/contract/test_workspaces.test.js` y verificado en vivo por Chrome: el
      espacio "Ventas Setiembre" (`exact_analysis`) deja de aparecer en "ESPACIOS DE TRABAJO"
      del modo Chat, sigue apareciendo en "ESPACIOS DE ANÁLISIS EXACTO" de su propio modo.
- [X] T100 [US1] Lista + creación de espacios de análisis exacto (reusa el modal de "+ Nuevo",
      con el `kind` correcto)
- [X] T101 [US1] Subida de archivo — solo `.csv`/`.xlsx`/`.xls` (rechazo claro de otros formatos,
      Edge Case de spec.md), muestra columnas detectadas si el backend las devuelve (FR-006)
- [X] T102 [US1] Panel de pregunta/respuesta — input de pregunta, respuesta, y el SQL ejecutado
      visible (Pipeline Transparency) — nunca oculto, a diferencia del chat RAG
- [X] T103 [US1] Presupuesto agotado (402) → mismo mensaje neutro ya usado en el resto del Hub
- [X] T104 [US1] Motor no disponible (502) → mensaje neutro, sin nombrar "DB-GPT" (FR-005)

## Phase 3: User Story 2 - Distinguir del chat RAG (Priority: P1)

- [X] T105 [US2] Copy explícito en la sección ("Para cálculos exactos sobre planillas — sumas,
      conteos, cruces. No es el chat de documentos.") — cierra SC-002

## Phase 4: Polish

- [X] T106 [P] Test de integración `client/tests/integration/test_exact_analysis_ui_046.test.js`
      — dobles HTTP reales (`node:http`), cubre: creación de espacio, filtrado por `kind` en el
      listado, subida (multipart real, no JSON mentido — regresión del bug #1 de abajo), rechazo
      de formatos no tabulares, pregunta con SQL, sin sesión → 401 en las 3 rutas, y que el
      encabezado del CSV nunca llegue al enmascarado (regresión del bug #3 de abajo).
- [X] T107 Verificación en vivo por Chrome real (Browser pane) — el guion de US1 completo,
      clickeando/subiendo/preguntando por la sesión autenticada real del navegador (no por API
      directa) — es lo que el dueño del producto pidió ver. Confirmado 11-sep: login como `ana`,
      creación del espacio "Ventas Setiembre", subida de `ventas_setiembre2.csv`, pregunta
      "¿Cuánto suman las ventas del departamento de Marketing?" → respuesta correcta (300.0) con
      `SELECT SUM(monto) AS total_ventas FROM data_analysis_table WHERE depto = 'Marketing';`
      visible en el box de transparencia SQL.

## Bugs reales encontrados y corregidos en vivo (11-sep), no detectados por las pruebas de la
## spec 048 (esas solo probaban el motor por curl/Python, nunca por la UI real — el motivo
## explícito por el que se arrancó esta spec 046)

1. **`eleaFetch` fuerza siempre `Content-Type: application/json`**: la subida de archivo
   (`FormData`/multipart) llegaba con un Content-Type mintiendo "json" — el backend nunca podía
   parsear `doc_file` (422 crudo, sin ningún log de error propio, porque es un rechazo de
   FastAPI antes de tocar código de aplicación). Arreglado: la ruta de subida usa un `fetch()`
   directo, sin pasar por `eleaFetch`, dejando que `fetch`/`FormData` arme su propio boundary
   multipart — mismo criterio que ya usaba (más arriba en el mismo archivo) la subida de
   documentos a AnythingLLM, por la misma razón.
2. **El enmascarado de CSV corrompía la estructura tabular**: `maskText` junta varias líneas
   en un mismo trozo de hasta 4000 caracteres antes de mandarlo al analizador NER — Presidio/
   spaCy no tratan el salto de línea como límite duro, así que detectaban entidades que
   ABARCABAN dos filas (medido en vivo: `"Julian,1200\nVentas"` salió como una sola entidad) y
   las reemplazaban por un solo placeholder — fusiona dos filas en una y corre las columnas. El
   motor de análisis exacto entonces rechazaba el archivo con un 422 genérico. Arreglado con
   una función de enmascarado dedicada para CSV (`maskCsvText`) que enmascara fila por fila —
   hace imposible que una entidad cruce un límite de fila.
3. **El enmascarado marcaba con falsos positivos el encabezado y valores categóricos cortos**
   (`"depto"` como `PERSON`, `"Marketing"`/`"Ventas"` como `LOCATION`), lo que rompía la
   semántica que el motor necesita para armar el SQL — la consulta terminaba filtrando contra un
   placeholder inexistente y devolvía `null` sin ningún error visible (peor que no enmascarar:
   una respuesta vacía silenciosa se lee como "no hay datos", no como "algo salió mal").
   **Decisión del dueño del producto (11-sep)**: excluir SIEMPRE la primera fila (encabezado)
   del enmascarado — un nombre de columna no es PII real, y protegerlo rompía la funcionalidad
   sin ganar nada. Las filas de datos (2 en adelante) se siguen enmascarando fila por fila, ahí
   es donde puede haber PII real. **Gap conocido, documentado a propósito** (mismo criterio que
   el gap de `.xlsx` sin enmascarar, T090 de la 048): un valor categórico repetido en muchas
   filas (p.ej. un nombre de departamento que se repite) todavía puede dar falso positivo fila
   por fila y quedar enmascarado de forma inconsistente entre filas — cada fila es una llamada
   independiente al NER, sin memoria de "esto ya lo vi antes y decidí que es una categoría, no
   PII". Excluir el encabezado cierra el caso más común y más dañino (el nombre de columna,
   que aparece una sola vez pero rompe el SQL entero); no cierra el caso general de valores
   categóricos repetidos en las filas de datos, que queda fuera de esta ronda.
4. **Los espacios `kind=exact_analysis` se filtraban al aparecer en su propio modo, pero
   también aparecían en el sidebar del modo Chat normal** (`GET /api/workspaces`, backend de
   `renderWorkspaceList()` de `#view-hub`, no filtraba por `kind`) — mezcla parcial de los dos
   modos, contra FR-001. Arreglado el mismo día tras reportarlo: la ruta ahora excluye
   `kind=exact_analysis` de su respuesta. Regresión cubierta en
   `client/tests/contract/test_workspaces.test.js` y verificado en vivo.

## Riesgo real encontrado en producción (11-sep), NO corregido — decisión explícita del dueño
## del producto de mitigar con aviso, no con bloqueo ni con enmascarado de .xlsx

Subiendo un `.xlsx` real (con datos de facturación reales: CUIT, nombre completo, email
personal, teléfono, domicilio) la respuesta del motor volvió con **todos esos datos en texto
plano, sin ninguna protección** — la confirmación en producción del gap ya documentado arriba
(el enmascarado de CSV, bugs 2 y 3, NO corre para `.xlsx`/`.xls`; T090 de la 048 sigue
pendiente para Excel binario). No es un bug nuevo: es el gap conocido manifestándose con datos
reales de un cliente (Drexgen SAS) en vez de datos de prueba.

**Decisión del dueño del producto (11-sep, tras revisar tres opciones)**: no bloquear `.xlsx`
ni implementar el enmascarado binario todavía — en su lugar, avisar explícitamente ANTES de
subir. Implementado en `uploadExactAnalysisFile()` (`client/public/index.html`): un
`confirm()` nativo al elegir un archivo `.xlsx`/`.xls` que dice textualmente que el archivo
NO se enmascara y que datos personales reales pueden volver sin proteger en la respuesta —
la persona decide con esa información, la subida no se bloquea. El texto de estado durante la
subida también cambia ("sin enmascarar — Excel") para no sugerir una protección que no ocurre.
**El riesgo de fondo sigue sin cerrarse** — solo se lo hace visible antes de cada subida. Si en
algún momento se decide cerrar el gap de raíz, la opción evaluada y descartada esta ronda era:
leer el `.xlsx` celda por celda, enmascarar cada celda (mismo criterio fila-por-fila que ya
tiene el CSV) y reempaquetar como `.xlsx` real antes de subir.

## Implementation Strategy

MVP = T098-T104 (US1 completo) — ya demuestra el flujo real pedido. T105 (US2) y T106/T107 cierran
la entrega. **Estado al cierre (11-sep): completo y verificado en vivo**, con un gap conocido
documentado arriba (enmascarado
de valores categóricos repetidos en filas de datos) — ninguno bloquea el flujo principal.
