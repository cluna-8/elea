# Prueba en el servidor de Elea (`eleavdmia`) — 14-sep-2026

Después de actualizar el servidor con `elea-installer` (spec 050), prueba guiada desde el Chrome
del dueño (logueado como `admin`) sobre `http://eleavdmia:8095` (Hub), `:8090` (panel de
Guardian) y `:8097/templates` (plantillas). Todo con archivos reales de la carpeta de Elea.

## 1. Documentos: subir un archivo, preguntar, historial, paso por Guardian

| Paso | Resultado |
|---|---|
| Crear espacio "Estrategia post workshop" | OK |
| Subir `Analisis Post Workshop - Perspectiva Estrategia v08.pdf` (1,8 MB) | **FALLA (500)**: el PDF es imagen escaneada, sin texto extraíble (1 carácter). El motor de documentos lo rechaza. Reproducido en local. |
| Subir `Informe HUB IA.docx` (1.518 palabras) | OK, indexado en segundos |
| Pregunta: "¿Qué propone el Informe HUB IA? 3 puntos y personas/empresas" | Respuesta correcta y con fuente citada; modelo `azure-gpt-4o-mini` (Guardian decide) |
| Pregunta con datos personales (Juan Pérez, DNI, teléfono, email) | Respuesta con los datos **reales restituidos** (bóveda funciona) |
| Guardian, "Conexiones en vivo" | La petición sale de `svc.anythingllm-provider` con **PERSON, DNI, PHONE_NUMBER, EMAIL_ADDRESS enmascarados**; el prompt visible en el panel ya va con placeholders `[PERSON_0_b312]` |
| Guardian, "Logs de auditoría" | Fila con `[PII]`, tokens y costo ($0.000263) |
| Historial | Al recargar y volver a elegir el espacio, el documento y las dos preguntas con sus respuestas **siguen ahí** (viven en el motor de documentos) |

Problemas anotados:

1. **PDF escaneado sin texto → error genérico.** El Hub dice "El servicio de documentos no aceptó
   este archivo"; debería decir "el PDF no tiene texto (escaneado); hace falta OCR". Y falta OCR
   (Tesseract en `extract_text.py`) para ese tipo de documento, que en Elea existe.
2. **Falsos positivos del NLP en imperativos**: "Prepará" y "Encabezala" se enmascararon como
   `LOCATION`. Consecuencia visible: el modelo firmó la nota "Atentamente, Encabezala". Refuerza el
   pendiente de allow-list / ajuste del detector (spec 050, pendientes).
3. Al entrar al Hub no queda ningún espacio elegido: hay que hacer clic en el espacio para ver su
   historial. Menor.
4. La hora de los mensajes cambia de formato al recargar (`16:18` → `02:18 PM`). Cosmético.

## 2. Planillas (SP10): cargar las tres planillas y preguntar

| Paso | Resultado |
|---|---|
| Crear espacio "SP10 ventas forecast stock" | OK |
| Subir `df_ventas` (10.920 filas), `df_forecast` (37.379), `stock` (3.393) | OK, columnas detectadas y mostradas |
| Pregunta: marzo 2025, ventas vs forecast V03 por unidad de negocio, mayor desvío | **PRIMARY CARE 2.576.009 vs 5.705.307, desvío -3.129.298: idéntico a pandas** |
| Historial | **NO se guarda**: al recargar, el espacio muestra las planillas pero la pregunta y la respuesta desaparecen (por diseño de la 050: el motor tabular no guarda conversación). Anotado a pedido del dueño. |

Problemas anotados:

5. **Historial de planillas no persiste** (ver arriba). Propuesta: guardar preguntas/respuestas por
   espacio en el motor tabular (`/v1/spaces/{id}/history`) o en el Hub; decisión del dueño.
6. **La misma planilla se puede subir dos veces** (quedó `df_forecast` duplicado como `t2` y `t3`
   durante la prueba; se borró por API). Conviene rechazar o avisar si el nombre ya existe.
7. La respuesta devolvió solo la fila del mayor desvío; se pidió "por unidad de negocio" y la
   tabla completa (5 filas) habría sido mejor. Menor, de prompt.

## 3. Plantilla corporativa y descarga

| Paso | Resultado |
|---|---|
| `http://eleavdmia:8097/templates` como admin | OK (pantalla de Presenton publicada por el Hub) |
| New Template → subir `HUB Elea.pptx` → fuentes de respaldo (Montserrat, Space Mono) → Continue | Análisis de 6 diapositivas, ~2 min |
| Create Template "HUB Elea" | Quedó **0 de 6 layouts (0 %)** varios minutos, con un aviso "Instance not configured. Ask the administrator to configure the AI providers in Settings"; al rato terminó sola: **6 layouts, plantilla lista** y visible en el Hub como "HUB Elea (propia)", primera de la lista |
| Crear presentación desde la respuesta del informe, plantilla HUB Elea, 5 diapositivas, **sumando la planilla SP10** ("los 5 productos con más unidades en marzo 2025") | Primer intento: **502** "No se pudo consultar la planilla" (la misma pregunta directa en Planillas respondió en 9 s: ALERNIX 288.648, GENIOL PLUS 219.102, GENIOL 1GR 178.189, AZIATOP 155.820, EVRA 153.296). Segundo intento idéntico: **OK en ~80 s** |
| "Mis archivos" → Descargar | PPTX de 84 KB, 5 diapositivas verificadas leyendo el archivo: portada con la plantilla de Elea, 3 diapositivas del informe y la 5.ª "Top 5 productos por unidades vendidas" con los datos reales de la planilla |

Problemas anotados:

10. **El encadenado planilla → presentación falló la primera vez (502)** y funcionó la segunda con
    los mismos datos. La pregunta directa tardó 9 s, así que no es el timeout de 20 s del motor;
    sospecha: primera consulta "fría" del motor tabular en el servidor (carga del DuckDB) o un
    error transitorio del modelo. Hay que loguear el detalle en el Hub (hoy el mensaje es genérico)
    y reintentar una vez antes de fallar.
11. **Aviso de Presenton "Instance not configured"** durante la creación de la plantilla, aunque
    la generación funcionó. Es de la UI de Presenton con `CAN_CHANGE_KEYS=false`; confunde al
    admin. Ver si se puede ocultar (o documentar que se ignora).
12. El clic en "Descargar" abre el diálogo nativo del navegador y en la traza de red figuró un
    503 mientras la descarga por `fetch` de la misma URL devolvió 200 con el PPTX válido.
    Verificar en el Chrome del dueño que el archivo baja bien (probablemente el 503 es del
    interceptor de descargas del navegador automatizado, no del Hub).

## 4. Observaciones de marca y tecnología (pedido del dueño)

8. **El panel de Guardian en el servidor no tiene la marca de Eleia**: título "Sentinel Secure AI
   Gateway" y logo genérico. **Causa encontrada**: el tag `latest` de `elea-guardian-frontend` en
   el registro seguía apuntando a la imagen del 31-ago (nginx, título Sentinel); la publicación de
   hoy dejó bien el tag `2026-09-14` pero no `latest`. Corregido: `latest` re-apuntado a la imagen
   de hoy (vite, título "Guardian" + `loadBranding()`). Verificado en local que, recreando el
   contenedor con esa imagen y el mount `./branding`, `/branding/brand.json` responde "Eleia
   Guardian" con el logo. **Falta en el servidor**: `docker compose pull frontend && docker compose
   up -d frontend` (lo corre el dueño). Mejora pendiente: imagen de producción (nginx) con
   `/srv/branding`, como anota el compose del instalador.
9. **Nombres de tecnología visibles** que el dueño no quiere mostrar (para más adelante): en el
   panel, "Modelos & Ollama"; en el motor y su documentación, "LiteLLM" (el título del panel dice
   "Sentinel Gateway Proxy" en los logs). Regla: el cliente no debe poder evaluar la tecnología por
   los nombres. Tarea futura: barrido de "litellm", "Ollama", "Presenton", "AnythingLLM" en UI,
   docs y mensajes de error.

## 5. Resumen para el dueño

Funciona en el servidor: documentos (subida, respuesta con fuente, enmascarado y restitución
verificados en Guardian, historial), planillas SP10 (respuesta exacta), plantilla corporativa
"HUB Elea" creada y usada, presentación con datos de planilla descargable.

Para arreglar ya (orden sugerido): 8 (marca en el panel: un comando en el servidor), 1 (PDF
escaneado: mensaje claro + OCR), 10 (reintento en el encadenado), 5 (historial de planillas, si el
dueño lo quiere), 6 (planilla duplicada). Para más adelante, por pedido explícito: 9 (sacar
"LiteLLM", "Ollama" y demás nombres de tecnología de todo lo visible) y 2 (falsos positivos del
detector).
