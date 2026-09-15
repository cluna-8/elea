# Resultados de QA — spec 046 (Análisis exacto de datos en Eleia Hub)

> **⚠️ Addendum del 15-sep-2026 — leer antes que el resto.**
> Esta corrida es del **11-sep** y describe la arquitectura **anterior a la spec 050**. Todo lo que
> sigue vale como registro histórico de lo que se probó y se encontró, pero varias de sus
> conclusiones ya no describen el sistema actual. Ver §"Estado al 15-sep" al final.

**Fecha:** 11-sep-2026
**Entorno:** stack local ya levantado — Eleia Hub `http://localhost:8095` (perfil `rag` de `docker compose`, `STACK_PREFIX=eleae2e`)
**Navegador:** Chrome (Browser pane). El selector de archivos del sistema operativo no es manejable por automatización — se inyectó el `File` real disparando el mismo evento `change` que dispara una persona eligiendo el archivo a mano; el `confirm()` nativo del aviso de Excel también se interceptó para leer su texto y decidir confirmar/cancelar. La lógica probada en ambos casos es la real de la app; lo no ejercitado es el pintado del diálogo del navegador/SO en sí.
**Usuario:** `ana` (rol `client`), cuenta de prueba ya existente — no de un cliente real.
**Checklist seguido:** guion de 8 casos publicado como artifact interactivo (privado, editable por quien lo abre — por eso este archivo, para que el hallazgo quede versionado y con fecha, sin que nadie lo pise).

**Archivos usados (no son documentación, son insumos, no versionados en git):**
- `~/Descargas/ventas_qa.xlsx` — fixture sintético (`depto`, `vendedor`, `monto`; una fila `Marketing` = `300`). Datos 100% inventados — en el momento de esta corrida, `.xlsx` todavía no pasaba por enmascarado (ver actualización abajo).
- `~/Descargas/archivo_no_soportado_qa.pdf` — para el Caso 3 (formato rechazado).

> **Actualización posterior a esta corrida (11-sep, más tarde el mismo día):** el riesgo de
> `.xlsx` sin enmascarar descripto en todo este documento (Casos 2/4, sección de "Riesgos
> conocidos") **se cerró**. `.xlsx` ahora se enmascara celda por celda del lado del servidor
> (`maskXlsxBuffer()`, `client/server.js`, con `exceljs`) antes de salir del Hub. El aviso
> `confirm()` que se describe abajo para "Excel" quedó acotado solo a `.xls` (formato binario
> legado, sin soporte de la librería). Detalle completo en
> `specs/046-analisis-exacto-datos-eleia-hub/tasks.md`. Esta corrida se deja intacta como
> registro histórico de lo que era cierto en ese momento — no se reescribe retroactivamente.

---

## Resultado por caso

### Caso 1 — Los dos modos nunca se mezclan 🟢

Creado el espacio `QA - no borrar` (kind `exact_analysis`) desde el modo "Análisis exacto". Vuelto al modo "💬 Chat": el espacio **no aparece** en "ESPACIOS DE TRABAJO". Solo aparece en su propia lista dentro de "Análisis exacto". Regresión del leak de espacios (corregido el mismo día en un commit anterior) verificada cerrada.

### Caso 2 — Subir el Excel real y preguntar 🔴 **FALLA (dos veces, sobre dos arreglos distintos)**

Subido `ventas_qa.xlsx` desde Descargas. El SQL generado es exacto:

```sql
SELECT SUM(monto) AS total_ventas FROM data_analysis_table WHERE depto = 'Marketing';
```

y el motor calcula bien (`total_ventas: 300.0`, confirmado contra el backend). El problema es siempre lo que ve la persona en la respuesta, no el cálculo:

- **Primer estado (antes de cualquier fix):** la respuesta salía sin procesar — el motor (DB-GPT) devuelve `answer` con un bloque `<chart-view content="{...}">` embebido al final, con los saltos de línea como la secuencia literal `\n` (dos caracteres) y las comillas del JSON escapadas como `&quot;`. La persona veía ese JSON crudo pegado después del texto.
- **Segundo estado (tras el primer fix, mismo día):** el fix (`limpiarRespuestaExactAnalysis()`) sacaba el bloque `<chart-view>` entero asumiendo que era redundante con el recuadro de SQL — pero el recuadro de SQL solo muestra la **consulta** (`sql_executed`), nunca el **resultado**. El resultado (`data: [{total_ventas: 300.0}]`) vive únicamente adentro del `content` del `<chart-view>`. Borrarlo sin más dejaba a la persona leyendo el razonamiento y el SQL, pero **sin ver nunca el número**. Verificado contra el backend con el fix ya en el contenedor: `'300' in answer` → `True`; `'300' in limpiarRespuestaExactAnalysis(answer)` → `False`.
- **Tercer intento (mismo día, después de este reporte):** en vez de descartar el `<chart-view>`, se parsea su `content` (decodificando entidades + `JSON.parse`) y se agrega el resultado real al final del texto.
- **✅ Re-verificado por una corrida de QA independiente (11-sep 10:15), con el fix ya en el contenedor — el Caso 2 CIERRA.** Probado por la UI real, como `ana`, con el mismo `ventas_qa.xlsx`:
  - *Una fila, una columna* (`¿Cuánto suman las ventas del departamento de Marketing?`) → la respuesta termina en **`Resultado: 300`**. Sin `<chart-view>`, sin `\n` literales, sin `&quot;`, recuadro de SQL visible. Es la rama `filas.length === 1 && columnas.length === 1` de `formatearFilasChartView()`.
  - *Varias filas* (`¿Cuánto suma el monto por cada departamento?`) → se ejercita la rama de tabla y devuelve las cuatro filas, todas correctas contra el fixture:
    ```
    departamento: Ventas,    total_monto: 3025
    departamento: Logistica, total_monto: 1350
    departamento: Soporte,   total_monto: 970
    departamento: Marketing, total_monto: 300
    ```
    (suman 5645, que coincide con el total general verificado en el Caso 6).

  Con esto quedan cubiertas las dos ramas del formateador, no solo el caso trivial.

### Caso 3 — Formato no soportado se rechaza con claridad 🟢

Subido `archivo_no_soportado_qa.pdf`. Aviso claro: *"Este modo solo acepta planillas (.csv, .xlsx, .xls) — para otro tipo de documento, usá el chat normal."* Nada se rompe.

🟡 El nombre del archivo rechazado quedaba pegado al lado de "Seleccionar archivo" después del aviso, como si hubiera quedado cargado (bug #2 de la tabla). **Corregido y verificado en el código el mismo día**: `uploadExactAnalysisFile()` ahora limpia `input.value` en los dos caminos de error.

### Caso 4 — Cancelar el aviso de Excel no sube nada 🟢

Texto del aviso correcto: dice explícitamente que el Excel no se enmascara y que datos personales reales pueden volver expuestos. Al cancelar: **cero requests** de subida (verificado interceptando `fetch`), sin mensaje de "subiendo", selector de archivo vacío.

### Caso 5 — El chat normal sigue igual que siempre 🟢

RAG responde normal ("Respondió: azure-gpt-4o-mini"). Sin bloque `<chart-view>` y sin recuadro de SQL (contenedor oculto, 0×0) — el modo "Análisis exacto" no contaminó el chat normal.

### Caso 6 — El SQL nunca queda oculto 🟢

Tres preguntas distintas sobre el mismo archivo: suma filtrada (300), suma total (5645), `COUNT DISTINCT` (6). Las tres con su propio recuadro de SQL visible, nunca colapsado por defecto. El motor calculó bien las tres.

### Caso 7 — Sin sesión, las rutas no responden 🟢 (con un matiz)

Las tres rutas de `/api/exact-analysis/*` devuelven `401` sin sesión. Tras **recargar** sin sesión no queda ningún dato visible.

🟡 Si se cierra sesión **sin recargar la página**, los nombres de los espacios (de ambos modos) quedan visibles un instante en el DOM detrás del overlay de login, que es `rgba(238,240,245,0.92)` — 92% opaco, no 100%. Es el mismo `handleLogout()` sin re-render ya reportado el 10-sep (`RESULTADOS-PRUEBA-MANUAL-UI.md`, bug #10) para el resto del Hub — no es un bug nuevo de esta spec, pero ahora también alcanza a "Análisis exacto". Recargar la página lo resuelve.

### Caso 8 — Presupuesto agotado 🟢

No se saltó: se le asignó tope `$0` a `ana` para la prueba (revertido después). Mensaje neutro: *"Alcanzaste tu presupuesto. Contactá a tu administrador."* Sin error técnico, sin SQL, sin respuesta.

🟡 A diferencia del chat normal (que pre-chequea `currentBudget.status === 'exceeded'` antes de llamar), `askExactAnalysisQuestion()` no lo hace — siempre sale el request y se espera el `402`. No es un agujero de seguridad (el backend corta igual), pero es una ida y vuelta de más e inconsistente con el resto del Hub. Además, con presupuesto agotado **la subida del archivo sí se permite** — solo se corta al preguntar.

---

## Bugs encontrados

| # | Severidad | Descripción | Estado |
|---|---|---|---|
| 1 | **Bloqueante** | La respuesta de "Análisis exacto" nunca mostraba el resultado del cálculo: primero salía como JSON crudo (`<chart-view>`, `\n` literales, `&quot;`); el primer arreglo lo limpiaba pero también borraba el único lugar donde vivía el número. | **CERRADO** — tercer intento (parsear `<chart-view>` y mostrar el resultado) **re-verificado por QA independiente el 11-sep 10:15**, en las dos ramas del formateador (una fila y varias filas). |
| 2 | Menor | El archivo rechazado por extensión quedaba con su nombre pegado al selector, como si hubiera quedado cargado. | Corregido y verificado en el código el mismo día. |
| 3 | Menor | El recuadro de columnas detectadas (`#exact-analysis-columns`) queda siempre vacío — el backend nunca devuelve `data.columns` en la respuesta de subida. | Abierto. No bloquea el uso (recuadro vacío, no roto). |
| 4 | Menor, preexistente | Al cerrar sesión sin recargar, los nombres de los espacios de ambos modos quedan visibles un instante detrás del overlay de login (92% opaco). Mismo bug del `handleLogout()` reportado el 10-sep para el resto del Hub. | Abierto, fuera de alcance de esta spec. |
| 5 | Menor | El corte por presupuesto agotado no se pre-chequea del lado del cliente en "Análisis exacto" (sí lo hace el chat normal) — el backend corta igual, no es un agujero. | Abierto, mejora de consistencia. |
| 6 | Cosmético, fuera de alcance | El panel de administración (`:8090`) arranca titulado "Sentinel Secure AI Gateway" hasta que carga el branding real; las claves de `localStorage` siguen siendo `sentinel_session_token`/`basa_current_user`. | Fuera de alcance de spec 046. |

## 🟢 Todo OK

- **Caso 1** — Aislamiento entre el modo Chat y el modo Análisis exacto: correcto en ambas direcciones.
- **Caso 4** — Aviso de riesgo de Excel: texto correcto, camino de cancelar limpio, cero requests.
- **Caso 5** — El chat normal (RAG) no quedó afectado por el trabajo de esta spec.
- **Caso 6** — Transparencia de SQL: siempre visible, nunca oculto, en las tres preguntas probadas.
- **Caso 7 y 8** — Seguridad de sesión y corte de presupuesto: correctos del lado del backend, con matices menores de UX ya anotados.
- El SQL generado por el motor fue exacto en las cuatro preguntas distintas que se probaron; el cálculo en sí nunca falló — todo lo que falló en el Caso 2 fue de **presentación**, no de exactitud.

## Riesgos conocidos (no son bugs de esta corrida)

- **`.xlsx`/`.xls` no se enmascaran** — mitigado con un aviso explícito antes de subir (Casos 2 y 4), decisión de producto, no corregido de raíz.
- **Valores categóricos repetidos en un CSV** podrían enmascararse de forma inconsistente entre filas (cada fila es una llamada independiente al NER) — no se pudo disparar en esta corrida porque se usó `.xlsx`, que no pasa por enmascarado.

## Lo prioritario

**Ya no hay bloqueantes: los 8 casos cierran.** El Caso 2 se re-verificó de forma independiente
el 11-sep 10:15 con el tercer intento del fix ya en el contenedor, en las dos ramas del
formateador. Los bugs 1 y 2 quedan cerrados; los 3, 4, 5 y 6 siguen abiertos pero son menores y
ninguno bloquea el uso normal.

Dos cosas a tener en cuenta antes de dar la spec 046 por lista para producción:

1. **El fix vive en el working tree, sin commitear.** `client/public/index.html` figura como
   modificado en `git status` sobre la rama `044-hub-chat-panel-admin`. Si el contenedor se
   reconstruye desde `git` sin ese cambio, el bloqueante vuelve. Commitearlo es el siguiente paso.
2. **El gap de CSV nunca se probó.** Las dos corridas fueron con `.xlsx`, que no pasa por
   enmascarado. El riesgo conocido de valores categóricos repetidos en un `.csv` sigue sin
   ejercitarse — conviene una corrida corta con un CSV antes del piloto.

---

## Estado al 15-sep-2026 (addendum)

Revisión del repo cuatro días después de la corrida. **Nada quedó sin commitear**: los tres
repos (`elea`, `elea-installer`, `llm-guardian`) están limpios y `elea` está a la par de
`origin`. Lo que sigue es la traza de qué pasó con cada hallazgo.

### Lo que se cerró

| Hallazgo | Estado | Dónde |
|---|---|---|
| #1 Bloqueante — la respuesta no mostraba el resultado | Cerrado | `e16482a` (saca el payload crudo) + `f141797` (muestra el resultado del cálculo) |
| #2 Archivo rechazado pegado en el selector | Cerrado | mismo día, verificado en código |
| Riesgo conocido — `.xlsx` sin enmascarar | Cerrado y **después retirado** (ver abajo) | `10ad1e5` (`maskXlsxBuffer()` celda por celda con `exceljs`) |
| "El fix vive en el working tree, sin commitear" | Resuelto | `e16482a`; el punto 1 de "Lo prioritario" ya no aplica |

### Lo que cambió de raíz: spec 050 (12-sep)

`904dd37` reemplazó la arquitectura sobre la que corrió este QA. Dos consecuencias directas
sobre este informe:

1. **El motor DB-GPT ya no está en el cliente.** `chart-view` no aparece ni una vez en
   `client/public/index.html`, y con él se fue `limpiarRespuestaExactAnalysis()`. El bloqueante
   #1 no puede reaparecer por esa vía: el camino tabular ahora pasa por el motor propio
   (`tabular/`, DuckDB). **La regresión que este informe pedía vigilar ya no aplica tal cual** —
   habría que re-escribir el Caso 2 contra el motor nuevo.

2. **El Hub ya no enmascara.** Citando el comentario en `client/server.js:249`:

   > Spec 050 (12-sep-2026): el Hub YA NO enmascara. Guardian es firewall + base de usuarios y no
   > recibe archivos: los documentos suben crudos al motor de documentos local y la PII se
   > enmascara únicamente cuando el motor manda el prompt por `engine:4000/v1/chat/completions`.
   > El bloque de enmascarado por trozos (`maskText`/`maskCsvText`/`maskXlsxBuffer`,
   > `/gw/inspect`, `MASKING_VIRTUAL_KEY`) se retiró entero.

   Es decir: el `maskXlsxBuffer()` que cerró el gap el 11-sep **ya no existe** —`exceljs` tampoco
   está en `client/package.json`— y el `confirm()` que avisaba "este Excel no se enmascara"
   tampoco (0 ocurrencias). No es un retroceso: el enmascarado se movió al borde del LLM.

   **Consecuencia para QA:** los Casos 2 y 4 de este guion prueban un aviso y un camino de
   enmascarado que ya no están donde estaban. **Los dos riesgos conocidos de este informe —el de
   `.xlsx` y el de valores repetidos en `.csv`— hay que re-evaluarlos contra el punto nuevo**, no
   darlos por cerrados ni por abiertos en base a lo que dice acá. El mecanismo por trozos que
   causaba el gap de CSV se retiró; si la propiedad se repite en el borde del motor es algo que
   **no se probó**.

### Menores que siguen pendientes de re-verificar

- **#3 (recuadro de columnas vacío):** el modelo del cliente ahora sí lleva columnas
  (`exactAnalysisFiles = [{file_id, name, tables:[{name, columns, rows}]}]`,
  `client/public/index.html:1669`). Pinta a resuelto por el motor nuevo, **sin verificar en vivo**.
- **#4 (restos en el DOM al salir sin recargar):** no se volvió a probar. Era del `handleLogout()`
  general, no de esta spec.
- **#5 (presupuesto sin pre-chequeo en el cliente):** no se volvió a probar.
- **#6 (branding de otro cliente):** **medio corregido.** `frontend/index.html:12` ya dice
  `<title>Guardian</title>` — la marca base neutra, correcta según la regla de nomenclatura. Pero
  la clave de sesión sigue siendo `sentinel_session_token`
  (`frontend/src/services/auth.ts:3`), o sea la marca de Evidenze sigue en el storage de una
  instancia de Elea.

### Qué haría falta

Una corrida corta de QA contra el motor tabular nuevo, con un `.csv` (no `.xlsx`), que re-escriba
los Casos 2 y 4 sobre el punto de enmascarado actual. Hasta entonces, este informe sirve como
historia de spec 046, no como foto del sistema.
