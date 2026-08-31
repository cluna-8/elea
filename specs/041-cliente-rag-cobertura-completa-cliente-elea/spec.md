# Feature Specification: Cobertura completa de los 6 puntos del cliente Elea en el cliente RAG

**Feature Branch**: `041-cliente-rag-cobertura-completa-cliente-elea`

**Created**: 2026-08-31

**Status**: Borrador — pendiente de retomar. Depende de
[040-cliente-rag-elea-completo](../040-cliente-rag-elea-completo/spec.md) (ya construido,
probado con archivos reales, instalador funcionando en `eleavdmia` — ver tasks.md de esa
spec para el detalle de lo hecho el 31-ago).

**Input**: Mensaje literal del cliente Elea (compartido por el usuario, 31-ago), los 6
puntos originales del piloto. Esta spec audita cuáles cubre hoy el **cliente RAG**
concretamente (no el Guardian en general) y qué falta.

## Estado real por punto, verificado contra el código (31-ago)

| # | Punto del cliente | Estado en el cliente RAG | Evidencia |
|---|---|---|---|
| 1 | Generación de documentos (pptx, docx, pdf, xlsx, csv, txt) | ❌ No existe | El cliente solo tiene `/api/workspaces/upload` (lectura). Ningún endpoint genera archivos. |
| 2 | Carga de documentos (pptx, docx, pdf, xlsx, csv, txt) | 🟡 Parcial | `client/extract_text.py` tiene manejador para `.docx`, `.txt/.csv/.json/.md`, `.pdf` (agregado 31-ago), `.xlsx/.xls`. **Falta `.pptx`** — cae al `else` genérico que lee bytes binarios como texto, mismo bug que tuvieron xlsx y pdf antes de arreglarlos. |
| 3 | Búsqueda, síntesis y respuesta sobre documentos subidos | ✅ Funciona | RAG vía AnythingLLM. Bug raíz arreglado 31-ago: `similarityThreshold` default de AnythingLLM (0.25) no encontraba nada con contenido tipo tabla — ahora 0.05 por default en todo workspace nuevo. Verificado con CSV real de prescripciones médicas. |
| 4 | Cruces CSV/Excel, NO vectorial | ❌ No existe | El RAG vectorial responde por similitud semántica, no por cómputo exacto ("sumá todas las filas donde X"). Requiere un motor tipo DB-GPT (texto→SQL/DuckDB), descartado explícitamente para esta ronda (decisión del usuario, 31-ago). |
| 5 | Formateo de respuesta (mail, lista, resumen) | ❌ No existe | El chat no tiene ningún "modo de salida" — el modelo responde libre. No hay plantillas ni un parámetro que le pida "formato mail" al pedido. |
| 6 | Presupuesto a nivel rol (además de usuario y equipo) | 🟡 Cubierto por convención, no por feature | `Budget.group_id` en el Guardian ya permite presupuesto por `Group`, y un `Group` puede representar un rol (Analista, Coordinador, Supervisor). Pero es 100% manual desde el panel admin — no hay concepto de "rol" en el modelo de datos ni en la UI del cliente. |

## User Scenarios & Testing

### User Story 1 - Carga de PPTX (Priority: P1)

Alguien sube una presentación `.pptx` a un workspace. Se extrae el texto real de las
diapositivas (título + contenido de cada una), se enmascara igual que cualquier otro
documento, y queda disponible para preguntar sobre su contenido en el chat RAG.

**Por qué esta prioridad**: mismo patrón de bug ya visto 2 veces (xlsx, pdf) — subir un
pptx hoy probablemente falla en silencio o indexa basura, y es uno de los 6 formatos que
el cliente pidió explícitamente.

**Criterio de aceptación**: subir un `.pptx` real con datos personales en una diapositiva
→ se detectan y enmascaran esos datos → preguntar por el contenido de una diapositiva
puntual devuelve la respuesta correcta citando la fuente (mismo patrón de prueba que se
usó para validar xlsx/csv/docx/pdf el 31-ago).

**Implementación sugerida**: `python-pptx` (misma familia que `python-docx`, ya en uso)
en `extract_text.py`, iterando `slide.shapes` → `shape.text_frame.text` por diapositiva.

### User Story 2 - Formateo de respuesta a pedido (Priority: P2)

El chat permite pedir explícitamente un formato de salida (mail, lista con viñetas,
resumen ejecutivo, tabla) y el modelo responde en ese formato, no en prosa libre por
default.

**Nota de diseño a resolver antes de codear**: ¿esto es (a) una instrucción de sistema que
se le agrega al prompt según un selector en la UI ("Formato: [Mail ▾]"), o (b) dejarlo
librado a que el usuario lo pida en lenguaje natural ("redactalo como mail") y no es una
feature de producto sino un hábito de uso? El cliente Elea dice explícitamente "Hoy en
día no formatea" — sugiere que (a) es lo esperado: un control visible, no depender de que
cada persona sepa pedirlo bien.

### User Story 3 - Presupuesto por rol, como concepto de primera clase (Priority: P2)

Un admin puede asignarle presupuesto a un ROL (ej. "Analista de Calidad") sin tener que
armar manualmente un `Group` + `Budget` desde requests HTTP — un flujo claro en el panel
o en `create-tester.sh`/equivalente.

**Nota**: no hace falta cambiar el modelo de datos del Guardian (`Budget.group_id` ya
alcanza) — el trabajo es de UX/documentación: dejar clarísimo que "rol" = "Group" en este
producto, y facilitar crear un Group+Budget en un solo paso.

### User Story 4 - Generación de documentos (Priority: P3, la más grande)

Punto 1 completo — generar pptx/docx/pdf/xlsx a partir de un pedido en el chat ("armame
una presentación de 5 diapositivas sobre..."). Esto es un cambio de arquitectura, no un
fix puntual: hoy el cliente no tiene NINGÚN camino de salida de archivos, solo de entrada.

**Investigar antes de diseñar** (no asumir): AnythingLLM tiene un "Document Generation
Agent" (confirmado por búsqueda web 31-ago, `docs.anythingllm.com/agent/usage/
document-generation-agent`) — evaluar si alcanza vía su modo `@agent` en vez de construir
generación de documentos desde cero.

### User Story 5 - Cruces CSV/Excel exactos (Priority: P3)

Punto 4 completo — requiere sumar un motor de cómputo exacto (candidato ya evaluado en el
laboratorio previo: DB-GPT, texto→SQL sobre DuckDB). Es la pieza más grande de todas —
un servicio nuevo, no un ajuste del cliente actual. Explícitamente fuera de esta ronda por
decisión del usuario (31-ago); queda documentado acá para no perderlo de vista.

## Fuera de alcance de esta spec

- Todo lo de [040](../040-cliente-rag-elea-completo/spec.md) — ya resuelto, no se repite acá.
- El instalador (`elea-installer`) — funcional, deployado en `eleavdmia` (servidor VPN de
  Elea) el 31-ago. Ver notas de esa sesión para el detalle de la instalación remota.
