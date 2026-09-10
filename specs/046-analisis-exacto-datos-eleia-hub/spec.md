# Feature Specification: Análisis exacto de datos (Excel/CSV) en Eleia Hub

**Feature Branch**: `046-analisis-exacto-datos-eleia-hub`

**Created**: 2026-09-08

**Status**: Draft — lista para `/speckit-plan`. **Investigación cerrada** (10-sep-2026, ver
`specs/RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md` Parte 2 y la
[spec 048](../048-motor-analisis-exacto-dbgpt/spec.md), que retoma el motor deferido acá) — ya no
bloquea `/speckit-plan` de esta spec.

**Repos que toca**: solo `client/` (Eleia Hub) — flujo de usuario, orquestación del pedido, y el
punto de integración hacia el motor de análisis exacto. **NO toca `backend/` ni `litellm/`.** El
único punto compartido con el producto base ("Guardian") es la identidad del usuario ya
autenticado. El motor de análisis exacto en sí (DB-GPT — decisión explícita del dueño del producto,
10-sep-2026, ver [spec 048](../048-motor-analisis-exacto-dbgpt/spec.md)), su despliegue, su
seguridad y cómo se le atribuye costo/presupuesto al usuario, se especifican en esa spec de
backend aparte — acá solo se especifica qué necesita la UI de esa pieza para funcionar.

**Input**: punto 4 del pedido original de 6 puntos del cliente Elea, y el segundo punto del mail
de Tomás del 03-sep ("el almacenamiento del csv parece haberse hecho dentro de una Base Vectorial
con Chunks, lo que hace que no se pueda aplicar un análisis cruzando filas/columnas"). Auditado en
spec 041 US5 y descartado para las rondas anteriores por decisión explícita del usuario (31-ago);
se retoma acá como spec propia porque el cliente lo sigue necesitando.

## Por qué el RAG actual no alcanza (diagnóstico heredado, sin cambios)

El chat RAG responde por similitud semántica sobre fragmentos indexados (embeddings) — no por
cómputo exacto. Preguntas del tipo "sumá todas las filas donde la columna X sea Y" no tienen una
respuesta correcta posible desde un vector store: no hay ninguna fila "más parecida" a una suma.
Se necesita un motor distinto: texto→SQL (o equivalente) sobre los datos reales de la planilla,
no sobre su representación semántica.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preguntar en lenguaje natural y obtener un cálculo exacto (Priority: P1)

Alguien sube un CSV o Excel a un espacio dedicado a análisis exacto (distinto del chat RAG normal,
ver Assumptions sobre la decisión de diseño pendiente) y pregunta algo que requiere cómputo real
sobre los datos ("¿cuántos registros tiene la columna Estado en 'Aprobado'?", "sumá la columna
Monto para los registros de Julián"). La respuesta es el resultado exacto, no una aproximación
semántica.

**Why this priority**: es el pedido explícito del cliente, repetido en dos mensajes distintos
(31-ago y 03-sep) — es la funcionalidad más reclamada de las pendientes.

**Independent Test**: subir una planilla real con columnas numéricas y categóricas conocidas,
hacer una pregunta de suma/conteo/filtro con resultado verificable a mano, y confirmar que la
respuesta coincide exactamente.

**Acceptance Scenarios**:

1. **Given** una planilla cargada, **When** se pregunta un conteo o suma sobre una columna,
   **Then** la respuesta es el valor exacto, verificable contra el archivo original.
2. **Given** una pregunta que cruza dos columnas (p. ej. "monto total por región"), **When** se
   responde, **Then** el desglose es correcto para cada categoría, no solo el total.
3. **Given** una pregunta sobre una columna que no existe en la planilla, **When** se responde,
   **Then** el sistema lo indica claramente en vez de inventar un resultado.
4. **Given** datos personales en la planilla (nombres, DNI), **When** se pregunta sobre ellos,
   **Then** el enmascarado vigente sigue aplicando — el motor de análisis exacto nunca ve ni
   devuelve datos protegidos en claro salvo que la política de desenmascarado lo permita.
5. **Given** el presupuesto agotado, **When** se hace una pregunta de análisis exacto, **Then**
   se rechaza con el mismo mensaje neutro que cualquier otra operación de consumo.

---

### User Story 2 - Distinguir claramente "chat sobre documentos" de "análisis exacto de datos" (Priority: P1)

La persona entiende, desde la interfaz, cuándo está en un espacio de chat RAG normal (respuestas
semánticas, cualquier tipo de documento) y cuándo está en un espacio de análisis exacto (solo
datos tabulares, respuestas de cómputo real) — no se mezclan ni se confunden los dos modos.

**Why this priority**: sin esta distinción, la persona espera que el chat normal haga cómputo
exacto (la queja original) o espera que el análisis exacto entienda documentos no tabulares — dos
formas distintas de decepción evitables con una interfaz clara.

**Independent Test**: un usuario nuevo, sin explicación previa, entiende cuál de los dos modos usar
para una pregunta de cómputo exacto vs. una pregunta de contenido general, solo mirando la interfaz.

**Acceptance Scenarios**:

1. **Given** la interfaz del Hub, **When** el usuario quiere hacer un análisis exacto, **Then**
   hay un camino visible y distinto del chat RAG normal para llegar a esa función.
2. **Given** un archivo no tabular (un PDF, un docx), **When** se intenta usarlo en el modo de
   análisis exacto, **Then** el sistema lo rechaza con una explicación clara, no un error críptico.
3. **Given** una pregunta de contenido general hecha por error en el modo de análisis exacto,
   **When** se procesa, **Then** el sistema aclara que ese modo es solo para cómputo sobre datos
   tabulares, sugiriendo el chat RAG normal.

### Edge Cases

- Una planilla con columnas de nombres poco claros ("Col1", "Col2"): el sistema debe poder listar
  las columnas disponibles para que la persona sepa qué preguntar.
- Una planilla muy grande (más filas de las que el motor puede procesar en un tiempo razonable):
  hay un tope documentado, con aviso claro, no un cuelgue silencioso.
- Múltiples archivos cargados en el mismo espacio de análisis exacto: se define si las preguntas
  pueden cruzar archivos distintos o solo operan sobre uno a la vez (decisión de diseño, ver
  Assumptions).
- El motor de análisis exacto no está disponible: mensaje neutro, sin nombrar la herramienta
  interna.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Eleia Hub MUST ofrecer un modo de análisis exacto de datos, visualmente distinto del
  chat RAG normal, que solo acepta archivos tabulares (CSV/Excel).
- **FR-002**: Las preguntas en este modo MUST resolverse contra los datos reales de la planilla
  (cómputo exacto), no contra una representación semántica/embeddings.
- **FR-003**: El enmascarado de datos personales vigente MUST aplicar igual en este modo que en el
  chat RAG normal — ningún dato protegido llega en claro al motor de análisis exacto salvo que la
  política de desenmascarado ya vigente lo permita.
- **FR-004**: El presupuesto y su enforcement (402) MUST aplicar igual que en cualquier otra
  operación de consumo.
- **FR-005**: Los mensajes de error MUST ser neutros (sin nombrar la herramienta interna del motor
  de análisis exacto), consistente con la spec 044 US5.
- **FR-006**: El sistema MUST poder informar a la persona qué columnas/estructura tiene la
  planilla cargada, para orientar qué preguntas son válidas.

### Key Entities

- **Espacio de análisis exacto**: distinto de un `Workspace` de chat RAG (spec 043) — contiene
  solo archivos tabulares y opera en modo de cómputo, no de recuperación semántica. La relación
  exacta con el modelo de `Workspace`/membresías de la spec 043 (¿es un tipo de espacio más, o una
  entidad separada?) es una decisión de diseño para `plan.md`, no de esta spec.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: En una planilla real de prueba, al menos 9 de 10 preguntas de cómputo exacto
  (suma/conteo/filtro/cruce de dos columnas) devuelven el valor correcto verificado a mano.
- **SC-002**: Un usuario nuevo, sin instrucción previa, identifica correctamente cuál modo usar
  para una pregunta de cómputo exacto en una prueba de usabilidad informal con al menos 3 personas.
- **SC-003**: Ninguna pregunta en las pruebas de aceptación devuelve un dato personal protegido
  en claro fuera de la política de desenmascarado vigente.

## Assumptions

- **Investigación cerrada (10-sep-2026)**: la evaluación de DB-GPT y alternativas
  (`specs/RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md` Parte 2, retomando el trabajo previo
  referenciado en `specs/041-cliente-rag-cobertura-completa-cliente-elea/tasks.md` T050)
  encontró problemas reales en DB-GPT (un solo archivo sin cruces, SQL sin validar, PII sin
  enmascarar, una CVE crítica de RCE) y recomendó un módulo propio con DuckDB en su lugar. El
  dueño del producto decidió igual usar DB-GPT, con las mitigaciones de esos hallazgos como
  requisito — ver [spec 048](../048-motor-analisis-exacto-dbgpt/spec.md). Esta spec no compromete
  la herramienta específica — solo el contrato que la UI necesita de ella (recibir una pregunta en
  lenguaje natural + el archivo/dataset, devolver un resultado exacto y explicable).
- El **motor de análisis exacto en sí** (cómo se despliega, cómo se lo autentica, cómo se le
  atribuye costo al usuario, si corre en el mismo host o en un servicio aparte) es la
  [spec 048](../048-motor-analisis-exacto-dbgpt/spec.md), backend separado — acá solo se
  especifica la experiencia de usuario y el punto de integración que `client/server.js` necesita
  exponer.
- Se asume que "espacio de análisis exacto" es un concepto de interfaz nuevo, no una extensión del
  chat RAG existente — el diseño exacto (tipo de `Workspace` nuevo vs. entidad separada) se decide
  en `plan.md`, coordinando con la spec 043 solo en la medida en que reutilice el modelo de
  pertenencia/aislamiento ya definido ahí (mismo criterio de "solo se comparte con el back la
  identidad del usuario").
- Esta spec no resuelve generación de documentos (spec 045) ni formateo de respuesta (spec 047) —
  son piezas independientes del mismo pedido original del cliente.
