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
armamos bien". Reglas heredadas de la 050 que esta spec no puede romper: Guardian no guarda
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
8. **Borrado**: borrar un archivo de planilla, ¿invalida el historial que lo usó? Propuesta: no,
   se marca. Borrar el espacio borra todo.

## 5. Criterios para elegir

En este orden: (1) no rompe las reglas de la 050 (Guardian sin mensajes, Hub fino, motor dueño de
sus datos); (2) aislamiento por persona con el mecanismo que ya existe; (3) mismo comportamiento
que Documentos para la persona (no aprender dos formas de trabajar); (4) menor cantidad de código
nuevo en el Hub; (5) sin riesgo para las consultas actuales (rendimiento, bloqueos).

**Hipótesis de partida**: la opción **D** (motor guarda mensajes por hilo, Guardian registra el
hilo, Hub muestra igual que Documentos). La investigación la confirma o la tumba con las
mediciones de la sección 4.

## 6. Entregables de la investigación

- `RESULTADOS.md` en esta carpeta con las respuestas a las 8 preguntas, mediciones y la opción
  elegida.
- Contrato propuesto del motor: `GET/POST /v1/spaces/{id}/threads`, `GET /v1/spaces/{id}/threads/{key}/messages`,
  `DELETE …`, y el cambio en `query` para que guarde el turno.
- Cambios propuestos en el Hub (rutas y UI) y en el instalador (ninguno esperado).
- Plan de implementación con hitos y pruebas (con planillas reales de Elea y de CDCV, dos personas).

## 7. Fuera de alcance

Cambios en Guardian más allá de usar el registro de hilos existente; historial del chat directo
(modelo `auto` sin espacio); búsqueda dentro del historial; exportación (queda para después).
