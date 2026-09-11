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

## Riesgo real encontrado en producción (11-sep) — CERRADO para `.xlsx` más tarde el mismo día

Subiendo un `.xlsx` real (con datos de facturación reales: CUIT, nombre completo, email
personal, teléfono, domicilio) la respuesta del motor volvió con **todos esos datos en texto
plano, sin ninguna protección** — la confirmación en producción del gap ya documentado arriba
(el enmascarado de CSV, bugs 2 y 3, NO corría para `.xlsx`/`.xls`; T090 de la 048 quedaba
pendiente para Excel binario). No era un bug nuevo: era el gap conocido manifestándose con
datos reales de un cliente (Drexgen SAS) en vez de datos de prueba.

**Primera decisión del dueño del producto (11-sep, mitigación inmediata)**: no bloquear
`.xlsx` ni implementar el enmascarado binario todavía — avisar explícitamente ANTES de subir.
Implementado un `confirm()` nativo en `uploadExactAnalysisFile()` que decía que el archivo NO
se enmascaraba.

**Segunda decisión, mismo día, más tarde**: cerrar el gap de raíz para `.xlsx` (la opción que
antes se había evaluado y descartado por tiempo). Implementado `maskXlsxBuffer()` en
`client/server.js`: lee el `.xlsx` con `exceljs`, enmascara **celda por celda** (más simple y
más seguro que el enfoque fila-por-fila de CSV — cada celda ya tiene un límite real en el
archivo, no hace falta reconstruir nada por delimitador, así que es imposible que una entidad
"cruce" un límite de celda), excluye siempre la primera fila de cada hoja (encabezado, mismo
criterio que CSV) y las celdas no-texto (números/fechas, nunca candidatos de PII), y
re-empaqueta un `.xlsx` real con `workbook.xlsx.writeBuffer()`.

**Por qué `exceljs` y no el paquete `xlsx` (SheetJS) de npm**: `xlsx@0.18.5` (la última
versión publicada al registro público de npm) tiene dos vulnerabilidades de severidad alta sin
parche disponible ahí — prototype pollution y ReDoS (SheetJS solo publica las versiones
parchadas en su propio CDN, no en npm, por una disputa con el registro). Este código parsea
archivos subidos por cualquier persona autenticada; una dependencia con esas vulnerabilidades
conocidas sobre ESE input es exactamente el tipo de agujero que un producto de protección de
datos no puede tener. Verificado con `npm audit` antes de decidir.

**`.xls` (formato binario legado) sigue sin enmascarar**: `exceljs` no lo soporta (solo
`.xlsx`/`.csv`). El aviso `confirm()` se mantiene, pero acotado solo a `.xls` — recomienda
guardar como `.xlsx` desde Excel/Sheets. Mucho menos común hoy que `.xlsx` en la práctica.

Verificado: `client/tests/integration/test_xlsx_masking_046.test.js` (enmascara celda por
celda con un doble HTTP real de `/gw/inspect`, nunca el encabezado ni las celdas numéricas;
una celda bloqueada por gobernanza bloquea todo el documento) y en vivo contra el stack real
— subida vía `curl` de un `.xlsx` con nombres de prueba (`Julian Test Perez`, `Maria Test
Gomez`), confirmadas 4 llamadas a `/gw/inspect` en los logs del backend (una por celda de
texto de datos, nunca el encabezado ni los montos), y una pregunta posterior sobre el archivo
ya enmascarado que el motor respondió correctamente (`total_monto: 300.0` para Marketing,
`depto` intacto y usable para el filtro SQL).

## Corrida de QA real (11-sep) — checklist en Chrome (T107 repetido por otra persona/sesión) —
## 1 bloqueante y 5 menores encontrados, bloqueante corregido el mismo día

Se corrió el guion completo de 8 casos en `http://localhost:8095` (usuaria `ana`). 7/8 pasaron
en la corrida original; el que falló era un bug real de presentación, no de cálculo.

**Bloqueante (corregido el mismo día)**: la respuesta de `POST /exact-analysis/.../query` volvía
con un bloque `<chart-view content="{...}">` embebido, saltos de línea como la secuencia literal
`\n` (dos caracteres) y comillas del JSON escapadas como `&quot;` — `askExactAnalysisQuestion()`
lo asignaba tal cual a `answerText.textContent`, así que la persona veía el JSON crudo del motor
pegado después de la respuesta. El SQL (`sql_executed`) viaja aparte del `answer` y por eso el
recuadro de SQL siempre se vio bien — solo la respuesta en sí quedaba sin procesar. Arreglado con
`limpiarRespuestaExactAnalysis()` (`client/public/index.html`): saca el bloque `<chart-view>`
(redundante con el recuadro de SQL), convierte los `\n` literales en saltos reales y decodifica
las entidades más comunes (`&quot;`, `&amp;`, `&#39;`). Verificado en vivo tras reconstruir el
contenedor: la misma pregunta que antes mostraba el JSON crudo ahora responde con texto legible.

**Menor (corregido el mismo día)**: el archivo rechazado por extensión (ej. un `.pdf`) quedaba
con su nombre pegado al lado de "Seleccionar archivo" tras el aviso de error, como si hubiera
quedado cargado — `uploadExactAnalysisFile()` ahora limpia `input.value` también en el camino de
error (ya lo hacía el camino de cancelar el aviso de Excel).

**Menores abiertos, no corregidos esta ronda**:
- El recuadro de columnas detectadas (`#exact-analysis-columns`) queda siempre vacío — el
  backend nunca devuelve `data.columns` en la respuesta de subida, solo
  `{conv_uid, file_name, select_param}`. O se implementa la detección de columnas del lado del
  backend, o se saca el elemento de la UI (hoy es un recuadro vacío inofensivo, no roto).
- Al cerrar sesión SIN recargar la página, los nombres de los espacios (de ambos modos) siguen
  visibles un instante en el DOM detrás del overlay de login (`rgba(...,0.92)`, no 100% opaco).
  Mismo `handleLogout()` sin re-render ya reportado el 10-sep para el resto del Hub — no es un
  bug nuevo de esta spec, pero ahora también alcanza a "Análisis exacto". Recargar la página lo
  resuelve. Fuera de alcance de la 046 corregirlo acá.
- `askExactAnalysisQuestion()` no pre-chequea el presupuesto del lado del cliente antes de
  llamar (el chat normal sí lo hace con `currentBudget.status === 'exceeded'`) — el backend
  corta igual con el mensaje neutro correcto, así que no es un agujero de seguridad, pero es una
  ida y vuelta de más e inconsistente con el resto del Hub. Además, con presupuesto agotado la
  SUBIDA del archivo igual se permite; solo se corta al preguntar.
- Fuera de alcance de esta spec: el panel de branding (`:8090`) arranca titulado con el nombre
  de otro cliente ("Sentinel Secure AI Gateway") hasta que carga el branding real, y las claves
  de `localStorage` siguen siendo `sentinel_session_token`/`basa_current_user` — cosmético, no
  afecta la función, pero se ve en una demo.

Detalle completo, tabla de resultados caso por caso y el payload crudo real antes del fix quedan
documentados en la guía de QA publicada (checklist interactivo, ver enlace en el mensaje al
equipo de QA).

## Implementation Strategy

MVP = T098-T104 (US1 completo) — ya demuestra el flujo real pedido. T105 (US2) y T106/T107 cierran
la entrega. **Estado al cierre (11-sep): completo y verificado en vivo**, con un gap conocido
documentado arriba (enmascarado
de valores categóricos repetidos en filas de datos) — ninguno bloquea el flujo principal.
