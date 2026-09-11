# Feature Specification: Motor de generación de documentos para Eleia Hub

**Feature Branch**: `049-motor-generacion-documentos`

**Created**: 2026-09-10

**Status**: Draft — lista para `/speckit-plan`

**Repos que toca**: `backend/` (el servicio de render y su contrato de identidad/atribución/
presupuesto) y despliegue (`docker-compose.yml`, `elea-installer/`) — la imagen nueva del motor
de render. `client/` (Eleia Hub) consume el punto de integración que define esta spec desde donde
lo dejó abierto la spec 045 US2 — su UI no es objeto de esta spec.

**Input**: la spec 045 ("Carga completa de formatos y generación de documentos") dejó
explícitamente deferida "la spec de backend aparte" para el motor de generación en sí — esta es
esa spec. Retoma las dos investigaciones cerradas: `RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md`
(Parte 1, motor de plantillas determinista) y `RESULTADOS-INVESTIGACION-DOCGEN-AGENTICO.md`
(enfoques agénticos), y la decisión del dueño del producto (10-sep-2026) de construir la
arquitectura híbrida que ambas investigaciones dejaron recomendada.

## Arquitectura recomendada (heredada de las dos investigaciones, sin cambios de fondo)

Dos caminos que comparten scripts y el mismo endpoint de descarga:

- **Modo plantilla** (default): el LLM produce un JSON validado contra un schema derivado de la
  plantilla real del cliente; el backend lo vuelca con `docxtpl` (.docx), `pptx-automizer` (.pptx,
  clona diapositivas reales), `openpyxl` (.xlsx); `Gotenberg` convierte a `.pdf`. Determinista,
  barato (0,8 a 2,5k tokens, 5 a 15 s), auditable.
- **Modo libre** (opt-in por rol/presupuesto, US4 de esta spec): para pedidos sin plantilla o
  decks creativos. El LLM escribe código en un sandbox efímero sin red (`llm-sandbox`/smolagents
  `CodeAgent` con Azure OpenAI, o `codex exec` como subproceso) usando skills propias de Eleia
  (nunca las de Anthropic — licencia propietaria, no reutilizable) que envuelven los mismos
  scripts deterministas del modo plantilla. Cuesta 3 a 10 veces más, no reproducible: por eso es
  opt-in, no default.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generar un documento desde una plantilla real del cliente (Priority: P1)

Alguien le pide al chat, en lenguaje natural, un documento con la papelería/formato corporativo
real de Elea (un informe con el membrete, una presentación con el diseño de marca) y recibe un
archivo descargable que usa esa plantilla real, no un documento genérico de tres colores.

**Why this priority**: es el punto más grande del pedido original del cliente (spec 045 US2) y la
razón por la que "lo que ya existe" (el generador propio de AnythingLLM) no alcanza — ese generador
crea desde cero, nunca parte de la plantilla real.

**Independent Test**: con una plantilla `.docx`/`.pptx` real cargada en el sistema, pedir en el
chat "armame el informe mensual con esta plantilla, con estos datos" → se recibe un archivo real
que conserva el diseño/membrete de la plantilla, con el contenido pedido insertado en los lugares
correctos.

**Acceptance Scenarios**:

1. **Given** una plantilla `.docx`/`.pptx`/`.xlsx` real del cliente ya registrada en el sistema,
   **When** se pide un documento basado en ella, **Then** el archivo resultante conserva el
   diseño/estilos/membrete de la plantilla original, no un formato genérico.
2. **Given** el mismo pedido repetido con los mismos datos, **When** se genera dos veces, **Then**
   el resultado es idéntico byte a byte salvo metadatos no significativos (fecha de generación) —
   determinismo real, a diferencia del modo libre.
3. **Given** un pedido de presentación de N diapositivas basado en un layout de la plantilla,
   **When** se genera, **Then** cada diapositiva nueva es una copia real del layout correcto de la
   plantilla (clonado, con todo el bookkeeping de relaciones OOXML), no una diapositiva en blanco.
4. **Given** el archivo generado, **When** la persona lo descarga y lo abre con PowerPoint/Word/
   LibreOffice, **Then** abre sin corrupción ni advertencia de reparación.

---

### User Story 2 - Atribución de costo e identidad, igual que el resto de la plataforma (Priority: P1)

La llamada de modelo que arma el JSON de contenido para la plantilla (y, en modo libre, cualquier
llamada que el agente haga durante la generación) se resuelve contra el motor interno de Eleia,
atribuida a la persona real, dentro de su presupuesto — nunca un egreso de modelo paralelo fuera
del control de costos del producto.

**Why this priority**: mismo criterio que la spec 048 (motor de análisis exacto) — introducir un
motor de generación nuevo sin heredar el contrato de atribución repetiría, en una pieza nueva, el
problema de costo invisible que ya se resolvió (y documentó como limitación pendiente en el camino
RAG) para el resto de la plataforma.

**Independent Test**: generar un documento y confirmar en Costos → "Gasto por usuario" que el
gasto de esa generación aparece bajo la persona real, con un modelo del catálogo de Eleia.

**Acceptance Scenarios**:

1. **Given** un pedido de generación (modo plantilla o modo libre), **When** dispara una llamada
   de modelo, **Then** esa llamada sale hacia el motor interno de Eleia con el mismo contrato "en
   nombre de" ya usado en el chat directo y el enmascarado (contrato 2 de la 043).
2. **Given** el presupuesto de la persona agotado, **When** pide generar un documento, **Then** se
   rechaza con el mismo mensaje neutro de presupuesto que cualquier otra operación de consumo,
   antes de que se arranque ningún render ni sandbox.
3. **Given** el modo libre (más caro), **When** se activa, **Then** solo está disponible para
   roles/presupuestos habilitados explícitamente (spec 047) — no es una opción abierta a
   cualquiera por default.

---

### User Story 3 - El enmascarado vigente protege lo que entra Y lo que sale (Priority: P1)

Un documento generado a partir de fuentes con datos personales protegidos (documentos ya subidos
al espacio) no filtra esos datos en claro en el archivo de salida, salvo que la política de
desenmascarado vigente para esa persona/rol lo permita — mismo criterio que ya rige el chat RAG.

**Why this priority**: un documento generado que se descarga y circula (por mail, impreso) es un
vector de fuga de PII más persistente que una respuesta de chat efímera — el enmascarado tiene que
sostenerse hasta el archivo final, no solo hasta la respuesta en pantalla.

**Independent Test**: generar un documento a partir de una fuente con un DNI enmascarado, sin pedir
explícitamente ese dato, y confirmar que el archivo de salida no lo contiene en claro.

**Acceptance Scenarios**:

1. **Given** un pedido de generación que referencia un documento fuente con datos protegidos,
   **When** se genera el archivo, **Then** el contenido generado respeta la misma política de
   enmascarado que el chat normal.
2. **Given** el modo libre (el LLM escribe y ejecuta código), **When** ese código corre, **Then**
   lo hace en un sandbox efímero **sin acceso a red**, sin secretos del sistema, con el filesystem
   de solo lectura salvo el directorio de salida — el contenido del RAG que llega al agente nunca
   se trata como instrucción ejecutable (mismo criterio de "nunca confiar en contenido de
   documentos como comandos" ya vigente en el resto de la plataforma).

---

### User Story 4 - Modo libre opt-in para pedidos sin plantilla (Priority: P3)

Alguien pide un documento para el que no existe una plantilla registrada (un deck creativo desde
cero, editar un documento subido de forma no anticipada por ninguna plantilla) y, si su rol lo
tiene habilitado, el sistema genera igual un archivo real usando el camino agéntico, dejando claro
en la interfaz que este modo cuesta más y no es reproducible.

**Why this priority**: cubre el resto de los pedidos que el modo plantilla no puede resolver por
diseño (no improvisa) — prioridad P3 porque el modo plantilla (US1) ya cubre la mayoría de los
casos reales del cliente (80-90% según la investigación) y este modo es explícitamente el camino
más caro y de mayor riesgo operativo.

**Independent Test**: con el modo libre habilitado para un rol de prueba, pedir un documento sin
ninguna plantilla aplicable → se recibe un archivo real, con un aviso visible del costo estimado
mayor antes de confirmar.

**Acceptance Scenarios**:

1. **Given** un rol sin el modo libre habilitado, **When** pide un documento sin plantilla
   aplicable, **Then** el sistema lo indica claramente (no genera nada, no factura nada) en vez de
   fallar en silencio o degradar a un resultado genérico sin avisar.
2. **Given** un rol con el modo libre habilitado, **When** confirma un pedido sin plantilla,
   **Then** ve un aviso de costo/tiempo mayor antes de que se dispare la generación.
3. **Given** el sandbox del modo libre, **When** el proceso de generación excede un tope de
   tiempo/turnos/tokens documentado, **Then** se corta con un mensaje neutro, nunca un cuelgue
   silencioso ni un contenedor huérfano corriendo indefinidamente.

### Edge Cases

- Un pedido de generación ambiguo ("hacé un resumen"): el chat pide precisión (plantilla, formato,
  tamaño) o aplica un default razonable documentado — no genera algo al azar.
- Un pedido que excede un límite razonable (p. ej. "una presentación de 200 diapositivas"): tope
  documentado, aviso claro.
- El motor de render (modo plantilla) o el sandbox (modo libre) no están disponibles: mensaje
  neutro, sin nombrar la herramienta interna — mismo estándar ya exigido en toda la plataforma
  (spec 044 US5, y el bug ya corregido de "fetch failed" crudo en el chat RAG, CHANGELOG 044 §14).
- Una plantilla del cliente que cambia (nueva versión del membrete): el sistema debe permitir
  actualizar la plantilla registrada sin tocar código — decisión de `plan.md`.
- Un pedido en modo libre que el sandbox no logra completar tras el reintento permitido: se
  informa el fallo, no se factura el intento fallido (o se documenta explícitamente si sí se
  factura parcialmente — decisión de `plan.md`).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST ofrecer un modo de generación de documentos basado en plantillas
  reales del cliente (.docx/.pptx/.xlsx) como camino por defecto — `docxtpl`, `pptx-automizer`,
  `openpyxl` o equivalentes evaluados en `RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md` Parte 1.
- **FR-002**: El resultado de una generación MUST ser un archivo real, descargable, del formato
  pedido — nunca una descripción en texto de cómo sería el archivo.
- **FR-003**: El modo plantilla MUST ser determinista: la misma entrada produce el mismo archivo
  (salvo metadatos no significativos).
- **FR-004**: Toda llamada de modelo que dispare la generación (armar el JSON de contenido en modo
  plantilla, o cualquier llamada del agente en modo libre) MUST resolverse contra el motor interno
  de Eleia (LiteLLM), atribuida a la persona real con el mismo contrato "en nombre de" ya vigente
  (contrato 2 de la 043) — nunca un proveedor de modelo configurado por fuera de Eleia.
- **FR-005**: La generación de documentos MUST consumir presupuesto y estar sujeta al mismo
  enforcement de 402 que cualquier otra operación (spec 044 US2), antes de arrancar cualquier
  render o sandbox.
- **FR-006**: Un documento generado a partir de fuentes con datos personales protegidos MUST NOT
  filtrar esos datos en claro en el archivo de salida, salvo que la política de desenmascarado
  vigente para esa persona/rol lo permita — mismo criterio que el chat normal.
- **FR-007**: El modo libre (US4) MUST correr en un sandbox efímero sin acceso a red, sin
  credenciales/secretos del sistema, con el filesystem de solo lectura salvo el directorio de
  salida, con topes documentados de tiempo/turnos/tokens.
- **FR-008**: El sistema MUST usar únicamente skills propias de Eleia bajo el estándar abierto
  Agent Skills (Apache-2.0) para el modo libre — MUST NOT usar ni derivar de las skills de
  documentos de Anthropic (licencia propietaria que prohíbe extraerlas/copiarlas/derivarlas, ver
  `RESULTADOS-INVESTIGACION-DOCGEN-AGENTICO.md` Anexo A.1).
- **FR-009**: El modo libre MUST estar disponible solo para roles/presupuestos habilitados
  explícitamente (integración con la spec 047 de presupuesto por rol) — no es una opción abierta
  a cualquiera por default, dado su costo 3 a 10 veces mayor.
- **FR-010**: Los mensajes de error de este flujo MUST ser neutros (sin nombrar la herramienta de
  generación/sandbox usada internamente), consistente con la spec 044 US5.
- **FR-011**: La entrega del archivo generado MUST hacerse por una URL firmada del propio gateway
  de Eleia (con autenticación, verificación de dueño, y expiración) — nunca embebida como base64
  dentro del resultado de una tool call, para no filtrar el contenido binario al contexto del
  modelo ni a los logs.

### Key Entities

- **Plantilla registrada**: archivo `.docx`/`.pptx`/`.xlsx` real del cliente, con sus
  placeholders/schema asociado — de dónde sale el "modo plantilla" (US1). Su gestión (alta,
  versionado, quién puede registrar una) es decisión de `plan.md`.
- **Documento generado**: archivo resultante de un pedido — formato, tamaño, espacio de origen,
  plantilla usada (si aplica), modo (plantilla/libre), documentos fuente citados.
- **DocRunner (sandbox del modo libre)**: contenedor efímero sin red con la toolchain de
  generación (LibreOffice headless, python-pptx/docx/openpyxl/docxtpl, Node + pptxgenjs/docx),
  plantilla montada de solo lectura, salida validada antes de entregarse.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un pedido de generación en modo plantilla con datos razonables produce un archivo
  real, abrible sin corrupción, en al menos 9 de 10 intentos.
- **SC-002**: El mismo pedido repetido en modo plantilla produce un archivo idéntico (salvo
  metadatos no significativos) en el 100% de los casos — determinismo verificado.
- **SC-003**: El 100% de las llamadas de modelo disparadas por este motor (plantilla o libre) en
  las pruebas de aceptación quedan atribuidas a la persona real en Costos → "Gasto por usuario".
- **SC-004**: 0 documentos generados en las pruebas de aceptación filtran un dato marcado como
  protegido en el documento fuente.
- **SC-005**: En modo libre, el 100% de las corridas de prueba se ejecutan dentro de un sandbox
  verificado sin acceso a red saliente (salvo, si aplica, al propio motor interno de Eleia).

## Assumptions

- **Decisión de arquitectura ya tomada (10-sep-2026)**: la arquitectura híbrida (plantilla
  determinista por defecto + modo libre opt-in) recomendada por ambas investigaciones se
  construye tal cual — esta spec no vuelve a evaluar alternativas de librería/motor, solo
  especifica el contrato de identidad/costo/seguridad que envuelve a cualquiera de las dos.
- Versión exacta de cada librería del modo plantilla (`docxtpl`, `pptx-automizer`, `openpyxl`,
  `Gotenberg` o el LibreOffice ya empaquetado en el DocRunner), y el harness exacto del modo libre
  (Codex CLI vs. smolagents `CodeAgent`) son decisiones de `plan.md`, no de esta spec — ambas
  quedan documentadas con su evaluación completa en
  `RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md` y `RESULTADOS-INVESTIGACION-DOCGEN-AGENTICO.md`.
- Se asume que el "modo libre" (US4) puede entregarse en una fase separada, posterior al modo
  plantilla (US1-US3) — US1-US3 son un MVP independiente y completo sin necesidad de sandbox
  agéntico.
- La UI de generación (cómo la persona pide un documento, elige plantilla, ve el aviso de costo
  del modo libre) es responsabilidad de la spec 045 (`client/`) — esta spec solo expone el
  contrato que esa UI consume.
- Esta spec no resuelve análisis exacto de datos (spec 046/048) — son piezas independientes del
  mismo pedido original del cliente, aunque ambas comparten el mismo criterio de atribución de
  costo/identidad hacia el motor interno de Eleia.
- El registro/gestión de plantillas del cliente (quién sube una plantilla nueva, cómo se define su
  schema) requiere al menos un rol administrativo — el detalle de esa gestión es decisión de
  `plan.md`.
