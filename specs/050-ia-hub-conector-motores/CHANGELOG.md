# CHANGELOG — spec 050 (IA Hub: Hub conector + motores)

## Estado al cierre (14-sep-2026) y pendientes

**Hecho y verificado**: hitos 1 a 6, prueba integral local 12/12, multiusuario 17/17, plantilla
corporativa de Elea creada y usada, imágenes publicadas (`2026-09-14`), handoff a Sentinel escrito.

**Pendiente, por decisión del dueño (14-sep, "dejemos pendiente el instalador")**:
1. **Instalador desde cero** (`elea-installer`): validado en sintaxis y con el stack de desarrollo,
   **no** ejecutado en una máquina limpia. Choca con los puertos del stack dev (8090/8091/8095/8097/3001).
   Al probarlo: `./install.sh` dos veces (la primera genera `.env`), verificar que crea `svc.tabular` y
   `svc.presenton`, que el Hub muestra las tres secciones y que `http://localhost:8097/templates` exige
   admin. Después, sincronizar solo `elea-installer` a Azure DevOps (regla del 31-ago) y actualizar
   `eleavdmia` en caliente sin tocar volúmenes.
2. Atribución de gasto por persona en el engine (`acted_for_user_id` en filas de éxito) — Guardian.
3. Allow-list de términos de negocio por tenant en el NLP ("OTC", "FASON" como PERSON) — Guardian.
4. Spec 047 (formato de respuesta, presupuesto por rol) y spec 049 (motor de documentos docx/xlsx/pdf).
5. Visibilidad uniforme de las imágenes en `ghcr.io/cluna-8` (hoy mezclada).
6. Dos tarjetas fantasma "HUB Elea" (0/6 y 2/6) en la pantalla de plantillas de Presenton local:
   tareas muertas, cosméticas.


## 13-sep-2026 — Cambio en Guardian: restitución de placeholders en streaming de la API OpenAI

**Fuera del alcance original de la 050 ("NO toca `litellm/`"), aprobado explícitamente por el
dueño el 13-sep tras el diagnóstico.**

- **Síntoma real (hito 4, Presenton):** las diapositivas generadas traían `[PERSON / 0 / 66a5]`
  en vez de "OTC"/"FASON" (términos que el NLP tomó por nombres de persona).
- **Causa raíz, verificada con la llave `svc.presenton` directo contra `engine:4000`:** sin
  streaming, texto, JSON (`response_format`) y tool calls volvían restituidos; **con
  `stream: true` los tres volvían con placeholders**. El hook
  `async_post_call_streaming_iterator_hook` de `litellm/extensions/sentinel_guardrail.py` solo
  reescribía frames SSE crudos (ruta `/v1/messages` de Anthropic); los chunks de
  `/v1/chat/completions` llegan como objetos `ModelResponseStream` y caían en la rama "objeto ya
  parseado: se entrega tal cual". Presenton usa streaming y no permite apagarlo.
- **Arreglo:** `sentinel_guardian_policy.unmask_openai_chunk()` + `flush_openai_carries()`
  (reutilizan `unmask_text` y `safe_split`; carry por choice y por tool call para placeholders
  partidos entre deltas; el carry pendiente se vuelca en el chunk con `finish_reason` o en un
  chunk extra si el stream se trunca). El hook aplica esto a la rama de objetos/dicts. La ruta
  SSE de Anthropic no cambia.
- **Pruebas:** `backend/tests/unit/test_unmask_openai_stream_050.py` (9 casos: entero, partido,
  partido en el corchete, tool call, dict, sin placeholders, truncado, finish con carry, hook
  completo). Suite de unmask/guardrail existente: 345 verdes, la única falla es la regional
  preexistente. En vivo: los tres modos de streaming restituidos; presentación regenerada sin
  tokens y con los valores reales.
- **Segundo caso (13-sep, hito 5):** con `response_format` JSON por streaming, restituir un
  original con salto de línea o comillas dentro de la cadena JSON rompía el parseo del cliente
  (Presenton: "Invalid control character at: line 1 column 67"). Ahora, si la petición pidió
  JSON (`request_wants_json`) o se trata de `arguments` de un tool call, el original se
  restituye escapado como contenido de cadena JSON (`json_string_map`). Texto plano no cambia.
  4 tests más (30 en total en el archivo).
- **Alcance no cubierto:** la bóveda (placeholders ecoados de requests pasados) sigue aplicando
  solo al camino no-streaming, igual que antes.

## 14-sep-2026 — Diccionario de datos por espacio (FR-027) y cierre de la documentación

- tabular `PUT /v1/spaces/{ws}/dictionary` + Hub `PUT /api/tabular/workspaces/{id}/dictionary` +
  clic en la columna en la UI. Probado con `stock_21052026.xlsx` (columnas SAP `Ce.`, `Alm.`,
  `UMB`, `decision_de_empleo`): con "vacío = pendiente" el SQL contó también las cadenas vacías.
- Imágenes republicadas: las 4 del repo `elea` (`latest` y `2026-09-14`).
- Documentación: `client/README.md` reescrito, `tabular/README.md`, `docs/api-reference/configuration.md`,
  `docs/administration/eleia-hub-workspaces.md` (planillas, presentaciones, plantillas, multiusuario),
  README del instalador. Spec 050 pasa a **Implementada**.

## 14-sep-2026 — Administración de plantillas reusando la pantalla de Presenton

Decisión del dueño: "sacar todo lo posible de Presenton para evitar desarrollar en el Hub".
- El Hub publica la pantalla de Presenton (`/templates`, `/custom-template`) en un segundo puerto
  (`PRESENTON_ADMIN_PORT`, 8097) con un proxy que exige sesión del Hub con rol admin; la cookie
  del Hub no viaja a Presenton; Presenton sigue sin puertos. Pestaña "Plantillas" solo para admins.
  Miniatura de la plantilla elegida en el modal (`/api/presentations/templates/{id}/thumbnail`).
- Probado en vivo con `HUB Elea.pptx` (6 diapositivas). Tres obstáculos reales y sus ajustes:
  1. El firewall bloqueaba con "detector de datos personales no disponible": el prompt de cada
     diapositiva (HTML) supera lo que el analyzer procesa en 15 s (~330 chars/s). Nuevo
     `SENTINEL_NLP_TIMEOUT_S` (default 15, sin cambios; 60 en los composes con motores).
  2. 429 del engine: la llave `svc.presenton` tenía 100k tokens/min y Presenton manda 6 slides
     con imagen en paralelo. Llave recreada con rpm 300 / tpm 2.000.000; el instalador acepta
     rpm/tpm por cuenta.
  3. `azure-gpt-5.1-chat` no sirve para este flujo (rate limit de Azure, timeouts, 500). Se
     mantiene `azure-gpt-5.4-mini`; en el primer intento salieron 5/6 layouts (uno inválido por
     validación de esquema de Presenton, que exige los 6).
- La sesión del Hub vive en memoria: cada rebuild del contenedor cierra las sesiones.

## 13-sep-2026 — Hito 5: encadenado y plantillas modelo

- `POST /api/handoff`: respuesta + pregunta a un espacio de planillas → presentación. Si la
  consulta a planillas falla, no se genera nada y se avisa (FR-014). Probado real: investigación
  del chat + "ventas por unidad de negocio 2025" → PPTX de 6 slides con plantilla `executive`,
  43 s, sin tokens.
- Plantillas modelo (pedido del dueño): `GET /api/presentations/templates` lista las integradas
  de Presenton y las propias del cliente (primero); `template` en generate y handoff; selector
  en el modal. Crear plantillas propias desde el PPTX corporativo queda pendiente (acción admin).
- Flags por motor ausente verificados con test (Hub solo con Guardian).

## 12-sep-2026 — Hitos 1 a 4 (ver memoria del proyecto y `git log` de la rama)

- Hito 1: enmascarado eliminado del Hub; DB-GPT retirado; FR-041 (`kind` al crear espacio).
- Hito 2: motor `tabular/` (DuckDB) con alias `tN`, detección de encabezado real, modelo
  `azure-gpt-5.4-mini` (5/5 con planillas reales de Elea vs 3/5 de 4o-mini).
- Hito 3: Hub `/api/tabular/*`, `/api/features`, UI de planillas igual al chat.
- Hito 4: Presenton v0.9.7-beta (puerto 80, `DISABLE_AUTH=true`), `/api/presentations/generate`,
  artefactos por persona, botón "Crear presentación", panel "Mis archivos".
