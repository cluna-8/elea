# CHANGELOG — spec 051: historial de conversaciones en Planillas y chat personal

## 14-sep-2026 — Implementación (aprobada por el dueño el mismo día)

Decisión de fondo (RESULTADOS.md): el motor de planillas guarda hilos y turnos; Guardian solo
registra de quién es cada hilo con el endpoint que ya tenía; el Hub muestra hilos como en
Documentos y no suma base de datos; el chat directo pasa a un espacio personal sin documentos en
el motor de documentos. Sin frameworks de conversación (LangChain descartado con mediciones).

### Motor tabular (`tabular/`)

- `app/history.py` (nuevo): `history.sqlite` por espacio, al lado del `db.duckdb` (DuckDB no
  admite escritura mientras las consultas usan la conexión de solo lectura, medido). Tablas
  `threads`, `turns`, `summaries`. Hilos y turnos son de una persona (`X-Hub-User-Id`); otra
  persona recibe 403.
- Rutas nuevas: `GET/POST /v1/spaces/{ws}/threads`, `PATCH/DELETE …/threads/{key}`,
  `GET …/threads/{key}/turns?limit=&before=`, `GET …/turns/{id}`.
- `POST …/query` acepta `thread_key`: guarda el turno (pregunta, respuesta, SQL, columnas, hasta
  50 filas, modelo) y devuelve `turn_id`; si no viene `history`, arma el contexto con el resumen
  acumulado + los últimos 5 turnos del hilo. Sin `thread_key` funciona igual que antes.
- **Resumen de conversaciones largas**: cada 5 turnos viejos (fuera de la ventana de 5) el motor
  pide a Guardian un resumen acumulado en español (`SUMMARY_SYSTEM`) y lo guarda; nunca rompe la
  consulta que lo disparó (si falla, se reintenta en la próxima). Env:
  `TABULAR_HISTORY_WINDOW`, `TABULAR_HISTORY_SUMMARY_EVERY`, `TABULAR_HISTORY_ROWS`.
- **Preguntas sobre la conversación** ("resumime lo que hablamos", "¿qué te pregunté?"): regla 11
  del prompt de SQL → el modelo responde `CHAT: …` y el motor devuelve el texto sin SQL ni segunda
  llamada. Encontrado en la prueba en vivo: sin esto el modelo escribía tres `SELECT '…' AS resumen`
  y la consulta se rechazaba.
- Borrar una planilla marca `stale` los turnos cuya consulta la usó (`DELETE …/files/{id}` devuelve
  `stale_turns`).
- Pruebas: `tests/test_history_051.py` (5) → **79** en total.

### Hub (`client/`)

- Rutas: `GET/POST /api/tabular/workspaces/{id}/threads`, `PATCH/DELETE …/threads/{key}`,
  `GET …/threads/{key}/turns`. Crear un hilo lo registra en Guardian (`POST /workspaces/{id}/threads`,
  `engine_thread_slug` = key) y en el motor; leer, preguntar, renombrar o borrar verifica primero
  el dueño contra Guardian (`ownsThreadSlug`, la misma función que Documentos); la lista de hilos
  es la intersección de lo que Guardian dice que es tuyo y lo que el motor tiene.
- `POST …/query` acepta `thread_key` (verificado contra Guardian) y devuelve `turn_id`.
- `POST /api/handoff` acepta `tabular: { workspace_id, thread_key, turn_id }`: arma la presentación
  desde el turno guardado, sin nueva consulta. Y para la consulta normal, **un reintento** ante
  5xx del motor (hallazgo 10 de la prueba en el servidor del 14-sep).
- `POST /api/workspaces/personal` (nuevo): crea una vez, o devuelve, el espacio "Mi chat ·
  <usuario>" en el motor de documentos, registrado en Guardian a nombre de la persona, con prompt
  de asistente en español y sin documentos.
- UI: Planillas con panel de hilos ("Principal" al primer uso, "+ Hilo", renombrar, eliminar),
  historial cargado al elegir un hilo (pregunta, respuesta, tabla, SQL, aviso si una planilla ya
  no está), "Crear presentación" desde una respuesta guardada preselecciona la planilla y usa el
  turno si se deja la pregunta vacía. "Mi chat" aparece primero en la lista de espacios y se abre
  por defecto al entrar.
- Pruebas: `tests/integration/test_historial_051.test.js` (3) → **40** en total.

### Guardian

Sin cambios. Se usa el registro de hilos existente (`/workspaces/{id}/threads`), verificado con
espacios `kind = exact_analysis` y tres personas (dueña, otra miembro, una sin membresía).

### Prueba en vivo (stack de desarrollo, planilla real `df_ventas_21052026.xlsx`, admin y bruno)

| Comprobación | Resultado |
|---|---|
| Crear hilo, preguntar "unidades en marzo 2025" | turno 1 guardado, 5.504.288 (= pandas) |
| "¿Y en abril? Compará con el mes anterior" | 6.438.674 vs 5.504.288, +934.386: **usó el contexto del hilo** |
| Recargar: turnos con SQL, filas y respuesta | 2 turnos persistidos |
| bruno (miembro del espacio) lista/pregunta en el hilo de admin | 403 / 403 |
| Presentación desde el turno 1 guardado | OK en 31 s, sin consulta nueva |
| 11 preguntas y luego "resumime todo desde el principio" | Con el disparo a 5 turnos y la regla `CHAT:`, la respuesta cubre marzo, abril, mayo, junio… (resumen acumulado + últimos 5) |
| "Mi chat": dos mensajes encadenados | Mantiene el contexto; historial persistido (4 mensajes) |

### Documentación

`tabular/README.md`, `client/README.md`, `docs/docs/administration/eleia-hub-workspaces.md`
(secciones "Historial por hilo en Planillas" y "Mi chat"), `docs/docs/api-reference/configuration.md`
(tres variables nuevas, opcionales), `specs/ROADMAP-guardian.md`. Instalador: sin cambios (los
datos viven en volúmenes que ya existen; las variables nuevas tienen default).

### Límites conocidos

- En "Mi chat" el modelo lo decide el motor de documentos para ese espacio (no el selector
  "Automático (Guardian decide)"); el chat directo sin espacio sigue disponible con el selector,
  pero sin historial.
- El resumen acumulado se actualiza cada 5 turnos: entre medio, el modelo ve el resumen anterior
  más los últimos 5 turnos (un turno puede quedar momentáneamente fuera de los dos).
- Los turnos guardan hasta 50 filas de resultado; si la consulta devolvió más, la tabla completa
  no se conserva (solo el total).
