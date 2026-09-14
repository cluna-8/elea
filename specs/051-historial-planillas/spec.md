# Feature Specification: Historial de conversaciones en Planillas — investigación de la mejor opción

**Feature Branch**: `051-historial-planillas`

**Created**: 2026-09-14

**Status**: 🔍 **Investigación** — esta spec define qué hay que averiguar y con qué criterio se elige;
no implementa. Sale de la prueba guiada en el servidor de Elea del 14-sep-2026
([PRUEBA-SERVIDOR-ELEA-2026-09-14.md](../050-ia-hub-conector-motores/PRUEBA-SERVIDOR-ELEA-2026-09-14.md),
hallazgo 5): en la sección Planillas la pregunta y la respuesta desaparecen al recargar.

**Repos/carpetas que puede tocar la implementación**: `tabular/` (motor de planillas), `client/`
(Eleia Hub). `backend/` (Guardian) solo si la opción elegida usa el registro de hilos que ya
existe (`/workspaces/{id}/threads`), sin cambiarlo. **No toca `litellm/`.**

**Input**: decisión del dueño (14-sep): "hagamos el spec de investigar la mejor opción así lo
armamos bien". **Regla sellada el mismo día**: Guardian y el Hub **no comparten base de datos**.
Guardian es el gateway con las políticas, lo usan otros programas además del Hub y tiene que
poder actualizarse solo; el Hub cambia todo el tiempo y no puede arriesgar la base de Guardian.
Si el Hub necesita guardar, es con base propia y ciclo de vida propio.

**Principio que está detrás (dueño, 14-sep)**: la relación Guardian ↔ Hub es **cliente ↔
proveedor**, y por eso el login del Hub es por API. Nada de código compartido, nada de base
compartida, nada de imports cruzados: lo único que los une es el contrato de la API de Guardian
(login, identidad, presupuesto, modelos, chat, registro de espacios e hilos). Consecuencias: (1)
todo dato del Hub vive en el Hub o en sus motores, Guardian solo guarda lo que le llega por su
API; (2) cada uno cambia de versión sin tocar al otro mientras respete el contrato; (3) el SSO lo
resuelve Guardian y el Hub lo hereda por la misma API. Reglas heredadas de la 050 que esta spec no puede romper: Guardian no guarda
mensajes ni conoce los motores; el Hub es un conector fino que no guarda mensajes de chat; cada
motor guarda lo suyo; una persona solo ve su trabajo.

---

## 1. Situación actual (verificada 14-sep en local y en el servidor)

- El motor tabular (`tabular/`) recibe `POST /v1/spaces/{id}/query {question, history[≤5]}` y
  **usa** el historial que le mandan para preguntas encadenadas, pero **no guarda nada**: ni la
  pregunta, ni la respuesta, ni el SQL ejecutado (`tabular/app/main.py:67-152`).
- El Hub guarda el historial **solo en memoria del navegador** (`exactAnalysisHistory` en
  `client/public/index.html:1889`) y lo manda en cada pregunta. Al recargar o cambiar de sección se
  pierde. Al volver al día siguiente, también.
- En Documentos el historial sí persiste porque el motor de documentos guarda hilos y mensajes, y
  Guardian registra qué hilo es de quién (`/workspaces/{id}/threads`, spec 043). Planillas no tiene
  hilos: un espacio, una sola conversación efímera.
- **Chat directo** (modelo "Automático" sin espacio, `POST /api/chat` sin `slug`): tampoco se
  guarda en ningún lado y **cada mensaje va solo**, sin los anteriores (`server.js`, rama
  `via: 'direct'`). Guardian deja solo la fila de auditoría, sin texto. Verificado 14-sep a
  pedido del dueño: el Hub no guarda ni lo de documentos (lo guarda su motor) ni lo del chat.
- Las respuestas de planillas contienen **datos del negocio** (cifras, nombres de productos) y el
  SQL ejecutado. Hoy nada de eso queda escrito en el servidor una vez respondido.

## 2. Qué se quiere (historias de usuario)

- **US1**: como persona que trabaja con planillas, al volver a un espacio quiero ver mis preguntas
  anteriores con sus respuestas y la consulta que las produjo, para no repetirlas y para citar el
  resultado.
- **US2**: como persona con varios temas sobre las mismas planillas, quiero poder separar
  conversaciones (hilos) como en Documentos, o al menos borrar el historial de un espacio.
- **US3**: como administrador, quiero que el historial respete el aislamiento de la 043: cada
  persona ve solo lo suyo, aunque el espacio sea compartido; quitar a alguien del espacio lo deja
  sin acceso a sus hilos (sin borrarlos).
- **US4**: como dueño del producto, quiero que el historial sirva también para "Crear
  presentación" desde una respuesta anterior y para el encadenado planilla → presentación.

## 3. Opciones a evaluar

| Opción | Dónde se guarda | A favor | En contra / dudas a resolver |
|---|---|---|---|
| **A. El motor tabular guarda** (igual que el motor de documentos guarda lo suyo) | Tabla `history` en el `.duckdb` del espacio, o SQLite/JSON al lado; hilos por `thread_key` | Coherente con la 050: cada motor guarda lo suyo; el Hub sigue fino; el SQL y las filas quedan junto a los datos que las produjeron | Las consultas corren con conexión `read_only`; la escritura del historial necesita la conexión de carga (ver `store.py:165`). Riesgo de bloqueo entre carga y consulta. Retención y tamaño (¿guardar filas o solo la respuesta?) |
| **B. El Hub guarda** | Archivo por persona en el volumen `client_artifacts` (como "Mis archivos") | Cero cambios en el motor; ya existe el patrón de índice por persona | Rompe "el Hub no guarda mensajes" (decisión sellada 12-sep); no sirve si otro cliente distinto del Hub usa el motor; historial y datos en lugares distintos |
| **C. Guardian guarda** | Tabla nueva en Guardian | Aislamiento por persona ya resuelto | **Descartada de entrada**: Guardian no guarda mensajes ni conoce los motores (regla del dueño). Solo puede registrar *qué hilo es de quién*, como ya hace |
| **E. Base propia del Hub, separada de Guardian** (decisión del dueño, 14-sep) | Contenedor propio del Hub (Postgres chico o SQLite en el volumen del Hub), **nunca la instancia `db` de Guardian** | Un solo esquema de hilos y turnos para planillas y chat directo; el Hub se actualiza y se rompe por separado; Guardian queda intacto | El Hub deja de ser "sin base" (decisión 050): medir qué gana; el instalador suma un servicio; respaldo aparte del de Guardian |
| **D. Hilos registrados en Guardian + mensajes en el motor** (la A con hilos, espejo exacto de Documentos) | Motor: mensajes por `thread_key`; Guardian: registro de hilo y dueño (`/workspaces/{id}/threads` con `engine_thread_slug`) | Misma experiencia que Documentos (hilos, renombrar, borrar); aislamiento por persona con el mecanismo existente; sin cambios en Guardian | Más trabajo en el Hub (UI de hilos en Planillas); hay que confirmar que el registro de hilos acepta espacios `kind = exact_analysis` sin tocar el backend |

## 4. Preguntas que la investigación tiene que responder

1. **Persistencia en el motor**: ¿se puede escribir el historial en el mismo `.duckdb` sin
   interferir con las consultas de solo lectura (`read_only=True` abre el archivo en otro modo)? Si
   no, ¿SQLite al lado (`history.sqlite` por espacio) o un JSON por hilo? Medir con un espacio de
   40.000 filas y 50 preguntas.
2. **Qué se guarda por turno**: pregunta, respuesta en texto, SQL, columnas, filas (¿todas, ≤50,
   ninguna?), modelo, fecha, persona (`X-Hub-User-Id`), `thread_key`. Tamaño estimado por turno y
   política de retención (¿90 días como la bóveda? ¿ilimitado?).
3. **Hilos**: ¿un hilo por persona por espacio (mínimo, US1/US3) o varios hilos por persona
   (US2)? ¿Registrar en Guardian con `POST /workspaces/{id}/threads` funciona hoy para espacios
   `exact_analysis`? Probar contra el backend actual sin modificarlo.
4. **Aislamiento**: con espacio compartido, dos personas preguntando sobre las mismas planillas
   no deben verse entre sí. Verificar que el motor filtre por `thread_key` y que el Hub verifique
   el dueño del hilo contra Guardian antes de leer (mismo patrón que `ownsThreadSlug` en
   `server.js`).
5. **Uso del historial en el modelo**: hoy se mandan los últimos 5 turnos. Con historial
   persistido, ¿se siguen mandando 5, o se resume? Medir costo por pregunta con historial largo.
6. **Datos personales**: si una planilla tiene nombres o DNI y la respuesta los incluye, el
   historial los guarda en claro dentro del motor (igual que la planilla misma). Confirmar que es
   aceptable (los datos ya viven crudos en el motor por decisión de la 050) y dejarlo escrito.
7. **Presentaciones desde el historial** (US4): confirmar que `POST /api/handoff` puede tomar una
   respuesta guardada por `thread_key` + índice, en vez de re-preguntar.
8. **Chat directo**: ¿se resuelve en esta misma spec o en otra? Para planillas hay un motor que
   puede guardar; para el chat directo no hay motor (Guardian no guarda mensajes por regla). Las
   salidas posibles: (a) el chat directo pasa a ser un hilo del motor de documentos sin
   documentos; (b) un almacén mínimo de hilos en el Hub, rompiendo "el Hub no guarda mensajes";
   (c) queda sin historial, como hoy, y se documenta. Recomendar una con el mismo criterio de la
   sección 5.
9. **Gestor de conversación** (pedido del dueño): evaluar LangChain / LangGraph (memoria de
   conversación: buffer, ventana, resumen de turnos viejos) u otro gestor preparado, contra una
   implementación propia mínima (guardar turnos, mandar los últimos N, resumir los anteriores con
   una llamada a Guardian). Condiciones que no se negocian: toda llamada a un modelo sale por
   Guardian (`/chat/completions` del backend con el token de la persona, o `engine:4000/v1` con
   llave `svc.*`), nunca directo a un proveedor; ningún nombre de tecnología visible; dependencias
   y tamaño de imagen acotados. Medir: tokens por pregunta con y sin resumen, calidad de las
   preguntas encadenadas sobre planillas reales, líneas de código que agrega cada camino.
10. **Borrado**: borrar un archivo de planilla, ¿invalida el historial que lo usó? Propuesta: no,
   se marca. Borrar el espacio borra todo.

## 5. Criterios para elegir

En este orden: (1) no rompe las reglas de la 050 (Guardian sin mensajes, Hub fino, motor dueño de
sus datos); (2) aislamiento por persona con el mecanismo que ya existe; (3) mismo comportamiento
que Documentos para la persona (no aprender dos formas de trabajar); (4) menor cantidad de código
nuevo en el Hub; (5) sin riesgo para las consultas actuales (rendimiento, bloqueos).

**Hipótesis de partida**: la opción **D** para planillas, con la **E** como candidata si se decide
dar historial también al chat directo (un solo esquema de hilos y turnos para los dos casos) (motor guarda mensajes por hilo, Guardian registra el
hilo, Hub muestra igual que Documentos). La investigación la confirma o la tumba con las
mediciones de la sección 4.

## 6. Entregables de la investigación

- `RESULTADOS.md` en esta carpeta con las respuestas a las 10 preguntas, mediciones y la opción
  elegida.
- Contrato propuesto del motor: `GET/POST /v1/spaces/{id}/threads`, `GET /v1/spaces/{id}/threads/{key}/messages`,
  `DELETE …`, y el cambio en `query` para que guarde el turno.
- Cambios propuestos en el Hub (rutas y UI) y en el instalador (ninguno esperado).
- Plan de implementación con hitos y pruebas (con planillas reales de Elea y de CDCV, dos personas).

## 7. Fuera de alcance

Cambios en Guardian más allá de usar el registro de hilos existente; búsqueda dentro del historial; exportación (queda para después).
