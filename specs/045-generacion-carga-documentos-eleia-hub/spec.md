# Feature Specification: Carga completa de formatos y generación de documentos (incluidas presentaciones) en Eleia Hub

**Feature Branch**: `045-generacion-carga-documentos-eleia-hub`

**Created**: 2026-09-08

**Status**: Draft — **recortada el 12-sep-2026 por la [spec 050](../050-ia-hub-conector-motores/spec.md)**:
queda vigente solo US1 (carga de `.pptx` y otros formatos al RAG). US2 (generación de documentos y
presentaciones) pasa a la 050 (presentaciones, motor Presenton) y a la
[spec 049](../049-motor-generacion-documentos/spec.md) (docx/xlsx/pdf). Lista para `/speckit-plan`
solo en ese alcance.

**Repos que toca**: solo `client/` (Eleia Hub). **NO toca `backend/` ni `litellm/`.** El único
punto compartido con el producto base ("Guardian") es la identidad del usuario ya autenticado
(sesión/JWT existente, contrato de usuarios de la spec 043) — no se pide ni se asume ningún
endpoint nuevo del backend. El motor de generación de documentos (investigación cerrada 10-sep-
2026, arquitectura híbrida: plantillas deterministas + modo libre agéntico opt-in) se especifica
en la [spec 049](../049-motor-generacion-documentos/spec.md), backend aparte.

**Input**: puntos 1 y 2 del pedido original de 6 puntos del cliente Elea (compartido 31-ago,
auditado en la spec 041 US1 y US4, retomados acá como specs de UI completas): carga de documentos
en todos los formatos pedidos (`.pptx` falta hoy) y generación de documentos —incluidas
presentaciones— a partir de un pedido en el chat.

## Diagnóstico (heredado de la spec 041, verificado 31-ago, sin cambios desde entonces)

| Punto | Estado hoy |
|---|---|
| Carga de `.docx`, `.txt/.csv/.json/.md`, `.pdf`, `.xlsx/.xls` | ✅ Funciona (`client/extract_text.py`) |
| Carga de `.pptx` | ❌ Cae al manejador genérico, lee bytes binarios como texto — mismo patrón de bug ya visto y arreglado en `.xlsx` y `.pdf` |
| Generación de documentos a pedido (pptx/docx/pdf/xlsx) | ❌ No existe ningún camino de salida de archivos, solo de entrada |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Carga de presentaciones (Priority: P1)

Alguien sube un archivo `.pptx` a un espacio. Eleia Hub extrae el texto real de cada diapositiva
(título + contenido), lo enmascara igual que cualquier otro documento (con el mismo `document_id`
determinista de la spec 044 US3, ya que es el mismo camino de subida), y queda disponible para
preguntar en el chat, citando la diapositiva exacta como fuente.

**Why this priority**: mismo patrón de bug ya visto dos veces (xlsx, pdf); es uno de los formatos
que el cliente pidió explícitamente desde el principio.

**Independent Test**: subir un `.pptx` real con un dato personal en una diapositiva → se enmascara
→ preguntar por el contenido de una diapositiva puntual devuelve la respuesta correcta citando
"Diapositiva N", con el mismo patrón de prueba ya usado para xlsx/csv/docx/pdf.

**Acceptance Scenarios**:

1. **Given** un `.pptx` con texto en varias diapositivas, **When** se sube, **Then** el texto
   extraído conserva la diapositiva de origen de cada fragmento para que la cita de fuente en el
   chat diga "Diapositiva 3", no solo el nombre del archivo.
2. **Given** un `.pptx` con un DNI en una diapositiva, **When** se sube, **Then** el dato queda
   enmascarado antes de indexarse, igual que en cualquier otro formato.
3. **Given** un `.pptx` con diapositivas sin texto (solo imágenes), **When** se sube, **Then** el
   Hub no falla — indexa lo que sí tiene texto y no revienta en las vacías.

---

### User Story 2 - Generación de documentos a pedido, incluidas presentaciones (Priority: P2)

Alguien le pide al chat, en lenguaje natural, que arme un documento (una presentación de N
diapositivas sobre un tema, un resumen en Word, una planilla) y recibe un archivo descargable con
ese contenido, generado a partir de la conversación y, si corresponde, de los documentos ya
cargados en el espacio.

**Why this priority**: es el punto más grande del pedido original del cliente — hoy no existe
ningún camino de salida de archivos. Prioridad P2 (no P1) porque requiere investigación de
alcance antes de comprometer una fecha (ver Assumptions).

**Independent Test**: pedir en el chat "armame una presentación de 5 diapositivas sobre los temas
del documento X" → se recibe un archivo `.pptx` real, descargable, con 5 diapositivas y contenido
relacionado al documento citado.

**Acceptance Scenarios**:

1. **Given** un pedido en lenguaje natural de generar un documento, **When** el chat lo procesa,
   **Then** el resultado es un archivo real del formato pedido (pptx/docx/pdf/xlsx), no una
   descripción en texto de cómo sería el documento.
2. **Given** un pedido de presentación basado en un documento ya cargado en el espacio, **When**
   se genera, **Then** el contenido generado es coherente con ese documento (no inventado sin
   relación).
3. **Given** un pedido de generar un documento con datos personales de un documento fuente
   enmascarado, **When** se genera la salida, **Then** el archivo generado respeta la misma
   política de enmascarado que el chat normal (no se filtra un dato protegido a través del
   documento generado).
4. **Given** el archivo generado, **When** el usuario lo descarga, **Then** puede abrirlo con las
   herramientas estándar del formato (PowerPoint/LibreOffice para pptx, Word/LibreOffice para
   docx, etc.) sin corrupción.
5. **Given** un pedido de generación mientras el usuario tiene el presupuesto agotado, **When**
   lo pide, **Then** se rechaza con el mismo mensaje neutro de presupuesto que cualquier otra
   operación de consumo (reutiliza el enforcement de la spec 044 US2).

### Edge Cases

- Un `.pptx` con diapositivas que combinan texto y tablas: el extractor debe capturar ambos, no
  solo el texto suelto.
- Un pedido de generación ambiguo ("hacé un resumen"): el chat pide precisión (formato, tamaño)
  en vez de generar algo al azar, o aplica un default razonable documentado.
- Un pedido de generación que excede un límite razonable de tamaño (p. ej. "una presentación de
  200 diapositivas"): se aplica un tope documentado, con aviso claro, no un cuelgue silencioso.
- El motor de generación no está disponible: mensaje neutro ("no se pudo generar el documento,
  probá de nuevo"), sin nombrar la herramienta interna usada.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Eleia Hub MUST extraer texto real de archivos `.pptx` (por diapositiva, con
  referencia de diapositiva conservada) con el mismo pipeline de enmascarado que el resto de los
  formatos soportados.
- **FR-002**: La subida de `.pptx` MUST seguir el mismo contrato de `document_id` determinista que
  el resto de los formatos (spec 044 US3) — no es un camino de subida distinto, es un manejador
  más dentro del mismo flujo.
- **FR-003**: Eleia Hub MUST ofrecer, desde el chat, un camino para pedir la generación de un
  documento en lenguaje natural, sin requerir un formulario técnico separado.
- **FR-004**: El resultado de una generación MUST ser un archivo real, descargable, del formato
  pedido — nunca una descripción en texto de cómo sería el archivo.
- **FR-005**: La generación de documentos MUST respetar el enmascarado vigente: un documento
  generado a partir de fuentes con datos protegidos MUST NOT filtrar esos datos en claro salvo que
  la política de desenmascarado ya vigente lo permita (mismo criterio que el chat normal).
- **FR-006**: La generación de documentos MUST consumir presupuesto y estar sujeta al mismo
  enforcement de 402 que cualquier otra operación (spec 044 US2), sin un camino separado que lo
  esquive.
- **FR-007**: Los mensajes de error de este flujo MUST ser neutros (sin nombrar la herramienta de
  generación usada internamente), consistente con la spec 044 US5.

### Key Entities

- **Documento generado**: archivo resultante de un pedido de generación — formato, tamaño,
  espacio de origen, documentos fuente citados (si aplica).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Subir un `.pptx` real con un dato personal en una diapositiva produce una respuesta
  correcta y con cita de diapositiva en el 100% de las pruebas manuales realizadas.
- **SC-002**: Un pedido de generación de presentación en lenguaje natural produce un archivo
  `.pptx` real abrible sin corrupción en al menos 9 de 10 intentos con pedidos razonables.
- **SC-003**: Ningún documento generado en las pruebas de aceptación filtra un dato marcado como
  protegido en el documento fuente.

## Assumptions

- **Investigación cerrada (10-sep-2026)**: el "Document Generation Agent" del motor de documentos
  actual (modo `@agent`) genera desde cero con tres temas de color fijos, sin partir de la
  plantilla real del cliente — no alcanza para el pedido (`RESULTADOS-INVESTIGACION-DOCGEN-
  DBGPT.md` Parte 1). La arquitectura elegida es un motor propio con dos caminos: plantillas
  deterministas por defecto y un modo libre agéntico opt-in (`RESULTADOS-INVESTIGACION-DOCGEN-
  AGENTICO.md`) — especificado en la [spec 049](../049-motor-generacion-documentos/spec.md).
- Esta spec asume que existe **un punto de integración** desde `client/server.js` hacia el motor
  de la [spec 049](../049-motor-generacion-documentos/spec.md) — no prescribe los detalles
  internos de esa pieza. El plan de esta spec debe dejar ese punto de integración como una
  interfaz clara (URL/función configurable).
- US1 (carga de pptx) no depende de ninguna decisión de US2 — puede implementarse y entregarse de
  forma completamente independiente y sin investigación previa (mismo patrón que xlsx/pdf).
- El enmascarado y el presupuesto reutilizan lo ya construido en 043/044 — esta spec no redefine
  ninguna de esas dos piezas.
