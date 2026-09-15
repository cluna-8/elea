# Prompt de investigación — generación de documentos + DB-GPT (otra ventana de Claude)

**Fecha**: 10-sep-2026. **Para qué**: investigación de mercado/técnica para dos piezas que
siguen `Draft` sin motor definido — spec 045 (generación de documentos, incluidas
presentaciones) y spec 046 (análisis exacto de datos Excel/CSV). Ninguna de las dos toca
código; el resultado alimenta la próxima ronda de `/speckit-plan` de esas dos specs.

Usá una sesión con acceso a internet (WebSearch/WebFetch). No hace falta tocar el repo ni
el stack levantado — esto es research puro, para volver con una recomendación.

---

## Prompt (copiar y pegar tal cual en la otra sesión)

```
Necesito investigación de mercado/técnica para dos piezas de un producto (Eleia
Hub/Guardian: gateway de IA con RAG, air-gapped/on-premise, spec-kit workflow). Ninguna
de las dos existe todavía en el código — es research para decidir QUÉ construir, no para
tocar código. Contexto de las specs en
/home/drexgen/Documents/ELEA/LLMADMIN-Elea/elea/specs/045-generacion-carga-documentos-eleia-hub/spec.md
y .../_retiradas/046-analisis-exacto-datos-eleia-hub/spec.md si querés leerlas antes de arrancar —
no hace falta.

## Parte 1 — Generación de documentos desde plantillas (spec 045)

Necesitamos que el chat pueda GENERAR documentos a pedido (no solo leerlos) — al menos
.docx y .pptx (presentaciones), idealmente también .pdf y .xlsx — a partir de una
plantilla y datos que arma el modelo. El usuario mencionó recordar algo llamado "open
design" o similar pero no está seguro del nombre exacto — buscalo, y si no es eso,
identificá cuál es la herramienta real a la que se puede estar refiriendo.

Investigá y compará al menos estas familias de opciones (buscá alternativas también si
encontrás algo mejor):
- **Carbone.io** (open source, generación desde plantillas .docx/.pptx/.xlsx/.pdf con
  datos JSON, self-hostable)
- **docxtemplater** / **PptxGenJS** (librerías JS, generación programática, no plantilla
  visual completa en todos los casos)
- **python-docx** / **python-pptx** (librerías Python, control total pero hay que armar
  el documento a mano, sin motor de plantillas)
- **Gotenberg** / **unoconv** / **LibreOffice headless** (conversión, no generación desde
  plantilla en sí, pero pueden ser la pieza de renderizado final)
- **OnlyOffice Document Server** / **Collabora Online** (self-hosted, más pesados, pensados
  para edición colaborativa, ver si sirven como motor de generación también)
- Cualquier herramienta específica de "IA genera presentaciones" open source que
  encuentres (buscá términos como "open source AI presentation generator",
  "open source docx template engine self-hosted", "open source pptx generation from
  template")

Para cada opción que evalúes, necesito:
1. ¿Es realmente open source (licencia, no solo "hay un free tier")?
2. ¿Se puede correr 100% self-hosted / air-gapped (sin llamar a un SaaS)?
3. ¿Soporta plantillas reales (un .docx/.pptx de ejemplo con placeholders) o solo
   generación programática desde cero?
4. ¿Qué tan mantenido está (último commit, issues abiertos, adopción real)?
5. Esfuerzo de integración estimado: ¿es una librería que se llama desde código, o un
   servicio aparte que hay que levantar (Docker) y hablarle por API?
6. Costo real de correrlo (recursos, licencias de terceros si usa LibreOffice de fondo, etc).

Terminá con una RECOMENDACIÓN concreta (una opción principal + una alternativa), no una
lista neutra de pros/contras sin conclusión.

## Parte 2 — ¿DB-GPT cubre lo que necesita el cliente para Excel?

El cliente (Tomás, analista de Data) reportó textualmente: "el almacenamiento del csv
parece haberse hecho dentro de una Base Vectorial con Chunks definidos, lo que hace que
no se pueda aplicar un análisis cruzando filas/columnas o incluso otros archivos como el
que se suele aplicar en áreas como Finanzas/BI."

Lo que necesita en criollo: poder hacer preguntas tipo "sumá la columna X para todos los
que tienen Y", "cruzá este archivo con este otro por la columna Z", sobre datos
tabulares reales (Excel/CSV), con precisión exacta (no aproximación semántica de un RAG).

Investigá **DB-GPT** (eosphoros-ai/DB-GPT en GitHub) específicamente:
1. ¿Soporta texto→SQL/consulta natural sobre archivos Excel/CSV subidos por el usuario
   (no solo bases de datos ya conectadas)? Si es así, ¿cómo — los convierte a una tabla
   SQL/DuckDB internamente?
2. ¿Soporta cruzar/joinear MÚLTIPLES archivos subidos en la misma consulta?
3. ¿Es 100% self-hosted / air-gapped? ¿Qué modelo usa para el texto→SQL — puede usar un
   proveedor propio (Azure OpenAI, que es lo que ya usa este producto) o exige un modelo
   específico?
4. ¿Qué tan pesado es desplegarlo (requisitos de recursos, dependencias, complejidad de
   instalación)? ¿Tiene imagen Docker oficial?
5. ¿Qué tan maduro/mantenido está (actividad reciente, versión estable, casos de uso
   reales documentados en producción, no solo demos)?
6. ¿Hay forma de integrarlo como servicio aparte (API) desde una app externa (Node.js/
   Python), o exige usar su propia UI/framework completo?
7. Si DB-GPT NO es la mejor opción para este caso puntual (subida de archivo → preguntas
   tabulares exactas, sin admin de infraestructura de BI), buscá 2-3 alternativas open
   source más chicas/simples para ese caso específico (buscá términos como
   "open source natural language to SQL Excel/CSV self-hosted",
   "open source chat with spreadsheet local", "text-to-SQL DuckDB open source"). Candidatos
   a considerar si los encontrás: PandasAI (open source, Python, consultas en lenguaje
   natural sobre dataframes/CSV/Excel), Vanna.ai (open source, texto→SQL), o cualquier otro
   que sea más liviano que DB-GPT.

Terminá con una RECOMENDACIÓN concreta: ¿DB-GPT es la pieza correcta para este caso, o
hay algo más simple que cumple lo mismo con menos complejidad operativa? Si recomendás
algo distinto a DB-GPT, decilo claro — no hace falta forzar la opción que ya se había
mencionado si no es la mejor.

## Formato del resultado

Escribí todo en
/home/drexgen/Documents/ELEA/LLMADMIN-Elea/elea/specs/RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md
con dos secciones claras (Parte 1 y Parte 2), cada una con la tabla comparativa y la
recomendación final destacada arriba de todo (para que se lea rápido sin tener que leer
todo el detalle). Citá fuentes/links de donde sacaste cada dato.
```

---

## Qué hago yo cuando termine

Cuando el usuario me avise, leo `specs/RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md` y lo
uso para completar la sección de Research/decisiones técnicas de las specs 045 y 046
antes de mandarlas a `/speckit-plan` — esto no toca código todavía, es la pieza que
esas dos specs están esperando para dejar de estar bloqueadas en "Draft".
