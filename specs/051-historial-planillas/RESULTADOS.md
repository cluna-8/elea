# Resultados de la investigación — historial en Planillas y en el chat directo

**Fecha**: 14-sep-2026. **Método**: mediciones en el stack de desarrollo (motor tabular real,
Guardian real con dos personas y una tercera sin membresía), estimaciones con las planillas reales
de Elea (`df_ventas`, `df_forecast`, `stock`) y una investigación documental sobre gestores de
conversación (sección 9). Todo lo que dice "medido" se corrió; lo que dice "estimado" es cálculo.

## Respuestas a las 10 preguntas de la spec

### 1. Persistencia en el motor: ¿en el mismo `.duckdb` o al lado?

**Al lado, en SQLite. El mismo `.duckdb` queda descartado.** Medido:

| Prueba | Resultado |
|---|---|
| Abrir una conexión de escritura al `.duckdb` mientras hay una de solo lectura abierta (que es como consulta el motor, `store.py:165`) | **Falla**: "Can't open a connection to same database file with a different configuration than existing connections" |
| 50 inserciones de historial en el `.duckdb` con conexión de escritura sola | 937 ms (y obliga a cerrar la lectura) |
| 50 inserciones en `history.sqlite` al lado, con la lectura DuckDB abierta | **9 ms**, la consulta DuckDB sigue funcionando |

Conclusión: un archivo `history.sqlite` por espacio, junto al `.duckdb`, en el mismo volumen
`tabular_data`. Sin bloqueos con las consultas, sin tocar cómo carga ni consulta el motor. SQLite
viene con Python; cero dependencias nuevas.

### 2. Qué se guarda por turno y cuánto pesa

Por turno: `thread_key`, persona (`X-Hub-User-Id`), fecha, pregunta, respuesta en texto, SQL
ejecutado, columnas, **hasta 50 filas** en JSON, modelo usado, y un marcador `stale` si después se
borró una planilla que la consulta usó.

Estimado con las planillas reales: 50 filas del forecast (12 columnas) pesan 17,9 KB en JSON; un
turno completo ronda **19 KB**; mil turnos, **18 MB**. Un año de uso intenso de una persona cabe
en decenas de MB por espacio. Retención propuesta: sin límite por defecto, con borrado por hilo y
por espacio; si el dueño quiere, 365 días configurables por env.

Guardar las 50 filas es lo que permite "Crear presentación" desde una respuesta anterior sin volver
a consultar (pregunta 7).

### 3. Hilos: uno o varios por persona, y el registro en Guardian

**Varios hilos por persona, registrados en Guardian con lo que ya existe.** Medido contra el
backend actual, sin tocarlo, con un espacio `kind = exact_analysis`:

| Acción | Resultado |
|---|---|
| Crear espacio de planillas (bruno) y registrar un hilo `POST /workspaces/{id}/threads` | 200, hilo con dueño |
| Admin (dueño implícito de todos los espacios) lista hilos | Ve **solo los suyos**, no el de bruno |
| Admin intenta borrar el hilo de bruno | 404 "hilo no encontrado" |
| Tercera persona sin membresía lista o crea hilos | 403 "sin acceso a este espacio" |

Es exactamente el mecanismo de Documentos (spec 043). No hace falta ningún cambio en Guardian.

### 4. Aislamiento entre personas sobre las mismas planillas

Resuelto por dos capas, las dos ya existentes: Guardian dice qué hilos son de quién (tabla de
arriba) y el motor guarda cada turno con `thread_key` y persona. El Hub, antes de leer o escribir
un hilo, verifica el dueño contra Guardian (`ownsThreadSlug` en `server.js`, hoy usado para
documentos) y recién ahí pide al motor. El motor, además, rechaza leer un hilo con otra persona en
`X-Hub-User-Id` (defensa en profundidad, como en tabular hoy con los espacios).

### 5. Uso del historial en el modelo y costo

Medido con el armado real de mensajes del motor (`llm.sql_messages`) y un esquema equivalente a
las tres planillas SP10:

| Situación | Tokens de entrada por pregunta |
|---|---|
| Sin historial | 1.193 |
| Con los últimos 5 turnos (lo que hace hoy) | 1.629 (+436) |
| Con 20 turnos, si se mandaran todos | ~2.900 (no se hace: el motor recorta a 5) |
| Resumen de los turnos viejos (≈50 tokens) + últimos 5 | ~1.680 |

Cada turno de planillas cuesta ~87 tokens. Con 5.4-mini, 436 tokens extra son fracciones de
centavo por pregunta. **Conclusión: mandar los últimos 5 turnos sigue siendo suficiente; el resumen
de turnos viejos no se justifica por costo en planillas.** Sí se justifica en el chat directo si se
le da historial (conversaciones largas de texto libre), y ahí la implementación es una llamada a
Guardian cada N turnos. No hace falta un framework para eso (sección 9).

### 6. Datos personales en el historial

Si una planilla trae nombres o DNI, la respuesta puede traerlos y el historial los guarda en claro
dentro del motor, al lado de la planilla que ya los tiene en claro (decisión de la 050: los archivos
crudos viven en el motor, dentro del servidor del cliente; Guardian enmascara solo lo que va al
modelo). No cambia el riesgo: es el mismo dato, en el mismo lugar, con el mismo control de acceso.
Queda escrito y aceptado; si algún día se quiere cifrar en reposo, es una tarea del volumen, no de
esta spec.

### 7. Presentaciones desde el historial

Hoy `POST /api/handoff` vuelve a preguntar al motor (`history: []`) y arma la tabla con las filas
devueltas (`server.js:1418-1434`). Con el historial guardado, `handoff` acepta
`{ tabular: { workspace_id, thread_key, turn_id } }` y toma pregunta, respuesta y las 50 filas
guardadas, sin nueva consulta ni gasto. Esto además resuelve el hallazgo 10 de la prueba en el
servidor (el encadenado falló una vez por un error pasajero de la consulta): si el turno ya
existe, no hay nada que pueda fallar del lado del motor.

### 8. Chat directo: dónde va su historial

Las tres salidas, evaluadas con el mismo criterio de la spec:

| Salida | Cumple reglas 050 | Código nuevo | Observación |
|---|---|---|---|
| (a) Hilo del motor de documentos **sin documentos** ("espacio personal" por persona, creado por el Hub al primer uso) | Sí: el motor guarda lo suyo, Guardian registra el hilo, el Hub sigue sin base | Poco: el Hub ya crea espacios e hilos y ya muestra ese historial | El motor de documentos agrega su prompt de sistema y una búsqueda vacía por pregunta; el modelo lo elige el motor, no "Automático (Guardian decide)". Hay que medir tokens extra |
| (b) Base propia del Hub (SQLite en el volumen del Hub, sin contenedor nuevo) | Sí, con la regla del 14-sep (base propia, nunca la de Guardian) | Medio: rutas de hilos y mensajes en el Hub, UI, migraciones | El Hub deja de ser "sin base"; Node 20 necesita una dependencia nativa para SQLite (`better-sqlite3`) o esperar Node 22 (`node:sqlite`) |
| (c) Sin historial, como hoy, documentado | Sí | Cero | Cada mensaje va solo; no sirve para conversar |

**Medido** (tres mensajes iguales por los dos caminos, modelo `azure-gpt-4o-mini`):

| Mensaje | Chat directo (tokens de entrada) | Motor de documentos sin documentos | ¿Mantuvo el contexto? |
|---|---|---|---|
| 1. "Hola, ¿qué podés hacer por mí?" | 17 | 129 | — |
| 2. "Tres ideas para presentar ventas a dirección" | 25 | 204 | — |
| 3. "¿Cuál de las tres conviene para un público financiero?" | 20 | 383 | **Sí** (el directo no: cada mensaje va solo) |

El motor de documentos agrega ~110 tokens de base (su prompt de sistema) más el historial del
hilo; con 4o-mini es una fracción de centavo por mensaje. A cambio, la conversación tiene memoria.

**Recomendación**: **(a)**. Historial y contexto en el chat directo sin darle base al Hub, sin
dependencias nuevas y con la misma pantalla que Documentos. Costo medido, aceptable. Lo que se
pierde: el modelo lo elige el motor de documentos por espacio, no el selector "Automático"; se
puede fijar el modelo del espacio personal al mismo `auto` si el motor lo permite, o documentarlo.
(b) queda como plan B; (c) descartada.

### 9. Gestor de conversación: framework o propio

**Propio.** Resumen de la investigación documental (detalle al final):

- Las clases de memoria clásicas de LangChain (`ConversationBufferMemory`,
  `ConversationSummaryMemory`) están deprecadas desde 0.3.1, viven en `langchain-classic` y
  tienen fecha de eliminación (2.0). Lo vigente es `create_agent` + checkpointer + middleware de
  resumen (LangGraph), pensado para agentes con herramientas y grafos: mucho más de lo que
  necesitamos.
- Peso medido en instalación limpia: Python langchain + langgraph + checkpointer SQLite = **76 MB
  y 50 paquetes** (arrastra `langsmith` obligatorio); Node = **107 MB y 63 paquetes**. La opción
  propia: 0 dependencias nuevas en Python (`sqlite3` de la biblioteca estándar) y `fetch` nativo
  en Node.
- Riesgo de nombres de tecnología: excepciones y avisos con `langchain_core`, `langsmith`,
  `openai`, y un resumen inyectado en inglés ("Here is a summary of the conversation to date").
  Va contra la regla del dueño.
- Alternativas: Vercel AI SDK (24 MB) no trae persistencia ni resumen; mem0 (129 MB) extrae
  "hechos" con embeddings, otra cosa; LlamaIndex (186 MB) solo Python; Semantic Kernel en modo
  mantenimiento.
- Patrón que sí tomamos: **ventana deslizante + resumen acumulativo**: últimos N turnos literales,
  lo anterior resumido en un texto que se re-resume cada vez; disparo por umbral de tokens; el
  resumen lo hace el modelo más barato **a través de Guardian**, con prompt en español. En
  planillas no hace falta (pregunta 5); en el chat directo, si va por el motor de documentos, el
  historial lo maneja ese motor y tampoco hace falta.

Qué se implementa entonces: en el motor tabular, dos tablas (`threads`, `turns`) en
`history.sqlite` y "últimos 5 turnos" como hoy; en el Hub, nada de memoria propia. Si algún día
se necesitan agentes con herramientas, LangGraph con checkpointer es la opción madura; hoy es peso
muerto.

### 10. Borrado

Borrar una planilla no borra el historial: los turnos que la usaron quedan marcados `stale` y el
Hub los muestra con una nota ("una planilla de esta respuesta ya no está"). Borrar un hilo borra
sus turnos. Borrar el espacio borra `history.sqlite` junto con el `.duckdb`. Quitar a una persona
del espacio no borra sus hilos: quedan inaccesibles (regla 043).

## Opción elegida

**D para planillas**: el motor tabular guarda hilos y turnos en `history.sqlite` por espacio;
Guardian registra el hilo y su dueño con el endpoint que ya existe; el Hub muestra hilos en
Planillas igual que en Documentos. **A para el chat directo, en su variante (a)**: un espacio
personal sin documentos en el motor de documentos, con hilos, sujeto a la medición del hito 1.

Por qué: cumple las reglas de la 050 y la del 14-sep (Guardian intacto y consumido solo por API,
sin base compartida), reutiliza el aislamiento que ya existe, la persona trabaja igual en las dos
secciones, el Hub no suma base ni dependencias nativas, y las mediciones no muestran ningún riesgo
para las consultas actuales.

## Contrato propuesto del motor tabular (`/v1`)

| Ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /spaces/{id}/threads` | — (cabecera `X-Hub-User-Id`) | `{ threads: [ { key, title, created_at, updated_at, turns } ] }` solo de esa persona |
| `POST /spaces/{id}/threads` | `{ key, title? }` | `{ key, title, created_at }` |
| `GET /spaces/{id}/threads/{key}/turns` | `?limit=50&before=<id>` | `{ turns: [ { id, ts, question, answer, sql, columns, rows, model_used, stale } ] }` |
| `DELETE /spaces/{id}/threads/{key}` | — | `{ status: "ok" }` |
| `POST /spaces/{id}/query` (cambia) | `{ question, thread_key?, history? }` | igual que hoy + `turn_id`; si viene `thread_key`, el motor guarda el turno y, si no viene `history`, usa los últimos 5 del hilo |

El motor rechaza con 403 cualquier hilo cuya persona no coincida con `X-Hub-User-Id`. `history`
explícito sigue aceptándose para no romper al Hub actual durante la transición.

## Cambios propuestos en el Hub

- Planillas: lista de hilos por espacio (mismo componente que Documentos), crear/renombrar/borrar,
  cargar turnos al entrar, mandar `thread_key` en cada pregunta. Rutas: `GET/POST/DELETE
  /api/tabular/workspaces/{id}/threads[...]`, `GET .../threads/{key}/turns`. Antes de cada una,
  verificación del dueño del hilo contra Guardian (misma función que Documentos).
- `POST /api/handoff`: acepta `turn_id` y arma la presentación desde el turno guardado.
- Chat directo: espacio personal por persona en el motor de documentos, creado al primer mensaje
  y registrado en Guardian; hilos como en Documentos. La UI del chat directo pasa a ser la misma
  pantalla de Documentos con un espacio sin panel de archivos.
- Instalador: **sin cambios** (todo vive en volúmenes que ya existen).

## Plan de implementación

| Hito | Contenido | Prueba de cierre |
|---|---|---|
| 1. ~~Medición del chat directo~~ **hecha en esta investigación** (pregunta 8): decisión (a) | — | — |
| 2. Motor: hilos y turnos | `history.sqlite`, contrato de arriba, `stale`, tests | 74 tests actuales + nuevos; dos personas sobre el mismo espacio, planillas reales de Elea |
| 3. Hub: Planillas con hilos | Rutas, UI, verificación contra Guardian, `handoff` desde turno | Recargar y volver: el historial está; otra persona no lo ve; presentación desde un turno guardado |
| 4. Hub: chat directo | Según hito 1 | Historial visible al volver; "Automático" sigue decidiendo el modelo, o queda documentado que lo decide el motor |
| 5. Cierre | Docs, CHANGELOG, imágenes con `publish-elea.sh`, prueba en el servidor de Elea con el Chrome del dueño | Misma prueba guiada del 14-sep, con historial |

## Hallazgo colateral (Guardian, a verificar aparte)

En el stack de desarrollo, las tres llamadas del motor de documentos al gateway
(`POST /v1/chat/completions`, 200 en el log del motor) **no dejaron fila en los logs de auditoría
de Guardian**, mientras que las del chat directo sí. En el servidor de Elea (prueba del 14-sep)
esas filas sí aparecen. Puede ser una diferencia de configuración del entorno de desarrollo; no
afecta a esta spec, pero hay que confirmarlo antes de confiar en los costos por cuenta `svc.*`.

## Investigación documental: gestores de conversación (pregunta 9) — informe completo

Realizado el 14-sep-2026 con mediciones de instalación en limpio (Python 3.12, Node 22 con los
mismos paquetes que Node 20). Versiones vigentes: langchain 1.4.0, langchain-core 1.6.3, langgraph
1.2.11; @langchain/core 1.2.11, @langchain/langgraph 1.4.15.

| Stack | Paquetes | Tamaño |
|---|---|---|
| Python: langchain + langgraph + langchain-openai + checkpoint-sqlite + checkpoint-postgres | 50 | 76 MB (23 MB `zstandard` por `langsmith`, obligatorio) |
| Python: solo `openai` | 14 | 24 MB |
| Python: solo `sqlite3` estándar + `httpx` (lo que ya usa el motor) | 0 nuevos | 0 |
| Node: @langchain/core + langgraph + openai + checkpoint-sqlite | 63 | 107 MB |
| Node: Vercel AI SDK (`ai` + openai-compatible) | 13 | 24 MB, sin persistencia ni resumen |
| Node: `fetch` nativo (lo que ya usa el Hub) | 0 nuevos | 0 |

Compatibilidad con un gateway propio (API OpenAI, base URL y cabeceras propias): LangChain la
soporta (`base_url` + `default_headers`; en JS `configuration.baseURL`), con dos avisos: en JS hay
que apagar `streamUsage` si el gateway no soporta `stream_options`, y los campos no estándar se
descartan. Nada de esto hace falta si no se usa el framework.

Riesgos documentados: cambio de API 0.x → 1.0 (memoria clásica eliminada), publicaciones casi
diarias en JS, el middleware de resumen de LangGraph no purga el historial persistido (issue
abierto abr-2026), nombres de terceros en trazas y textos en inglés inyectados al modelo.
Licencias: todo MIT/Apache-2.0.

Fuentes: documentación oficial de LangChain (short-term memory, Python y JS; referencia de
`SummarizationMiddleware` y `langchain-classic`), lista de checkpointers de LangGraph, npm y PyPI
de cada paquete, issues langchainjs #11637 y #11635, deepagents #2876, documentación de Vercel AI
SDK (persistencia), mem0 (config de LLM y LLM.md), LlamaIndex (memory), PyPI de semantic-kernel y
anuncio de Microsoft Agent Framework, guías de resumen de conversación (Mem0, DEV).
