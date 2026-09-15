# Generación de documentos — cómo se decidió hacerlo

La decisión está repartida en cuatro specs y dos informes de investigación. Esto es el mapa y el
resumen. **Nada acá es nuevo**: es lo que ya dicen esas fuentes, junto.

| Fuente | Qué aporta |
|---|---|
| [`RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md`](RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md) | Investigación del motor de plantillas determinista |
| [`RESULTADOS-INVESTIGACION-DOCGEN-AGENTICO.md`](RESULTADOS-INVESTIGACION-DOCGEN-AGENTICO.md) | Investigación de los enfoques agénticos |
| [`045`](045-generacion-carga-documentos-eleia-hub/) | El pedido original del cliente (recortada) |
| [`049`](049-motor-generacion-documentos/) | El motor en sí — **la spec principal** |
| [`050`](050-ia-hub-conector-motores/) | Cómo se repartió, y el contrato reservado |

---

## De dónde sale

El pedido del cliente estaba en la **spec 045 US2**: que se puedan generar documentos y
presentaciones desde el chat, **con la papelería real de Elea**. Ese es el punto: lo que ya
existía —el generador propio de AnythingLLM— crea documentos **desde cero**, nunca parte de la
plantilla real del cliente. Un informe genérico de tres colores no sirve.

La 045 dejó el motor deferido a "una spec de backend aparte". Esa es la **049**.

Antes de decidir se hicieron **dos investigaciones**, cerradas el **10-sep-2026**, y el dueño del
producto eligió construir la arquitectura híbrida que las dos dejaron recomendada.

## La arquitectura: dos modos

Comparten los mismos scripts y el mismo endpoint de descarga.

### Modo plantilla — el default

El LLM **no escribe el documento**. Produce un **JSON validado** contra un schema derivado de la
plantilla real del cliente, y el backend lo vuelca con librerías deterministas:

| Formato | Librería |
|---|---|
| `.docx` | `docxtpl` |
| `.xlsx` | `openpyxl` |
| `.pdf` | `Gotenberg` (convierte desde los anteriores) |

**Por qué así:** es determinista, barato (0,8–2,5k tokens, 5–15 s) y auditable. El mismo pedido
con los mismos datos da el mismo archivo byte a byte, salvo metadatos como la fecha.

### Modo libre — opt-in, no default

Para pedidos sin plantilla. El LLM **escribe código** en un sandbox efímero **sin red**
(`llm-sandbox`/smolagents `CodeAgent`, o `codex exec` como subproceso), usando skills **propias de
Eleia** que envuelven los mismos scripts deterministas del modo plantilla.

**Por qué no es el default:** cuesta 3 a 10 veces más y no es reproducible. Se habilita por rol y
presupuesto (spec 047).

> Las skills tienen que ser propias. Las de Anthropic son licencia propietaria y no se pueden
> reutilizar acá.

## Cómo lo repartió la spec 050 (12-sep)

La 050 partió el trabajo en motores separados, y la generación de documentos quedó en dos:

| Qué | Quién lo hace | Estado |
|---|---|---|
| **Presentaciones** (`.pptx`) | **Presenton** (motor 3 de la 050) | 🟢 **Hecho y en producción** — plantilla corporativa de Elea creada y usada |
| **Documentos** (`.docx`, `.xlsx`, `.pdf`) | **docgen**, motor 4 — spec 049 | 🔴 **No construido** |

Consecuencia práctica: **`pptx-automizer` sale de la 049.** Al planificar esa spec hay que quitarlo
y toda mención a `.pptx` — eso ya lo cubre Presenton.

De la 045 queda vigente **sólo US1** (carga de `.pptx` y otros formatos al RAG). La generación se
fue a 050 y 049.

## El contrato ya está reservado

La 050 dejó **botón y rutas reservados** en el Hub, y el contrato escrito en
[`050/contracts/03-motores.md` §3.4](050-ia-hub-conector-motores/contracts/03-motores.md), para que
el motor entre sin rediseñar nada:

```
Servicio: http://docgen:8091/v1     Red: docgen-net
Auth:     Authorization: Bearer <DOCGEN_INTERNAL_TOKEN>  +  X-Hub-User-Id

GET  /v1/templates  → { templates: [ { id, name, kind: docx|xlsx, fields: [...] } ] }
POST /v1/documents
     { template_id?, content, instructions?, export_as: docx|xlsx|pdf, mode: template|free }
     200 → archivo binario + cabecera X-Docgen-Mode
     422 plantilla incompatible · 403 free_mode_not_allowed (spec 047) · 504

docgen → Guardian engine: llave svc.docgen (can_act_on_behalf), X-Guardian-Acting-User.
     Modo plantilla: ≤ 2 llamadas al modelo.
     Modo libre: sandbox sin red; sólo el modelo sale por Guardian.
```

## Qué falta

**Construir el motor 4.** La 049 está en `Draft`, sin `plan.md` ni `tasks.md`, y su propio
encabezado dice: *"Implementación prevista para las semanas posteriores a la 050, no ahora."*

El camino sería `/speckit-plan` sobre la 049 ya recortada — es decir, con el alcance
`docx/xlsx/pdf` y sin `pptx-automizer`.

Es también el punto 4 de los pendientes de la 050 (junto con la spec 047, que es la que define el
opt-in por rol y presupuesto del modo libre).
