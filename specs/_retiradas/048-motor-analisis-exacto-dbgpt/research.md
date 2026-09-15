# Research: Motor de análisis exacto de datos (DB-GPT)

Fase 0 de `/speckit-plan`. Resuelve los `NEEDS CLARIFICATION` que dejó `spec.md`/`plan.md`.
Confirmado contra fuentes primarias el 10-sep-2026 (además de lo ya relevado en
`specs/RESULTADOS-INVESTIGACION-DOCGEN-DBGPT.md` Parte 2).

## R1 — ¿DB-GPT soporta un proveedor de modelo OpenAI-compatible propio (para apuntar al motor de Eleia)?

**Decisión**: sí, nativo, vía la imagen `eosphorosai/dbgpt-openai` (liviana, solo el proxy
model — sin dependencias de un modelo local pesado) y el archivo de config
`configs/dbgpt-proxy-openai.toml`, confirmado verbatim:

```toml
[[models.llms]]
name = "${env:LLM_MODEL_NAME:-gpt-4o}"
provider = "${env:LLM_MODEL_PROVIDER:-proxy/openai}"
api_base = "${env:OPENAI_API_BASE:-https://api.openai.com/v1}"
api_key = "${env:OPENAI_API_KEY}"

[[models.embeddings]]
name = "${env:EMBEDDING_MODEL_NAME:-text-embedding-3-small}"
provider = "${env:EMBEDDING_MODEL_PROVIDER:-proxy/openai}"
api_url = "${env:EMBEDDING_MODEL_API_URL}"
api_key = "${env:OPENAI_API_KEY}"
```

**Rationale**: `OPENAI_API_BASE` puede apuntar a cualquier endpoint OpenAI-compatible — LiteLLM
(el motor interno de Eleia) YA expone ese contrato (`http://engine:4000/v1`) para otros
consumidores. `LLM_MODEL_NAME` se fija a uno de los deployments reales del catálogo de Eleia
(p. ej. `azure-gpt-4o-mini`), nunca un modelo elegido por DB-GPT. `OPENAI_API_KEY` es la llave de
servicio `svc.dbgpt-excel` (nueva, ver data-model.md), no una credencial de Azure directa.

**Alternatives considered**: apuntar DB-GPT directo a Azure OpenAI con sus propias credenciales —
descartado, viola FR-004/FR-005 (el pedido explícito de esta ronda: "que use a Eleia para los
modelos y el costo") y reintroduce el mismo problema de costo invisible ya resuelto para el resto
de la plataforma.

**Embeddings**: DB-GPT también necesita un modelo de embeddings (para indexar la planilla antes
de resolver texto→SQL sobre ella — confirmar en implementación si esto es solo para
metadata/esquema o también para contenido; si es contenido, el mismo criterio de enmascarado
previo aplica igual que a los LLM calls). Se resuelve con el mismo `provider=proxy/openai`
apuntando a un deployment de embeddings de Eleia si el catálogo lo tiene, o queda como decisión de
implementación si no.

## R2 — ¿Cuál es el contrato HTTP real que el backend debe hablarle a DB-GPT (API de "chat excel")?

**Decisión**: **NO hay una API REST pública documentada** — confirmado (`RESULTADOS-
INVESTIGACION-DOCGEN-DBGPT.md` Parte 2: "La API que sirve Chat Excel es la v1 interna no
documentada, con respuestas en un formato 'vis' pensado para su propio front"; búsqueda adicional
del 10-sep no encontró OpenAPI/swagger ni ejemplos de `curl` oficiales). El repositorio expone
solo su web UI (`:5670`) y un SDK Python — ninguno de los dos es el contrato que este backend
necesita (llamadas HTTP server-to-server, atribuidas por request).

**Rationale de cómo se resuelve, sin bloquear el resto de la spec**: el mismo método ya usado con
éxito este mes contra otro motor sin API pública clara (AnythingLLM, cuyos endpoints reales —
`/thread/new`, el envoltorio en array de `/workspace/{slug}`, etc. — se descubrieron inspeccionando
tráfico real de red contra una instancia viva, no leyendo documentación). **Tarea de
implementación, no de este documento**: levantar el contenedor `exact-analysis-engine` en el
entorno de desarrollo, inspeccionar con las herramientas de red del navegador los llamados reales
que hace su web UI al subir una planilla y preguntar, y documentar el contrato exacto
descubierto (rutas, payloads, forma de la respuesta) en `contracts/dbgpt-real-api.md` ANTES de
escribir `exact_analysis_service.py` — no se adivina el contrato de memoria.

**Riesgo documentado**: una API interna no versionada puede cambiar entre versiones de DB-GPT sin
aviso — por eso FR-001 exige pin por digest (nunca `:latest`): un bump de versión es un evento
deliberado que re-verifica este contrato, igual que ya exige el Principio VI para LiteLLM.

**Alternatives considered**: usar el SDK Python de DB-GPT embebido en el backend en vez de HTTP —
descartado, acoplaría el proceso del backend al runtime/dependencias de DB-GPT (viola la
separación de contenedores del Principio VII) y complicaría el aislamiento de red de FR-002 (un
import Python no respeta fronteras de red).

## R3 — ¿Cómo se valida que el SQL que DB-GPT genera es de solo lectura?

**Decisión**: `sqlglot` (MIT, sin binarios nativos, parsea SQL a un AST) para verificar que el
statement raíz sea `SELECT` o `WITH ... SELECT` antes de que el backend confíe en la respuesta de
DB-GPT como "ejecutada de forma segura" — nota importante: **DB-GPT ejecuta el SQL él mismo,
puertas adentro**; el backend no puede interceptar la ejecución en sí (no reimplementa el motor de
DB-GPT, Principio VI). Lo que SÍ puede hacer el backend es:

1. Configurar DB-GPT, si lo soporta (a confirmar en implementación, ver Assumptions de
   `data-model.md`), en un modo de conexión de solo lectura a nivel de la base de datos donde
   monta las planillas (defensa en profundidad real, no solo de parseo).
2. Auditar el SQL devuelto en la respuesta (si DB-GPT lo expone, cosa habitual en herramientas
   texto→SQL para mostrar "cómo se calculó") con `sqlglot`, y marcar/alertar si alguna vez aparece
   algo que no sea lectura — señal de que el contrato R2 cambió o de un intento de manipulación.

**Rationale**: dado que DB-GPT es quien ejecuta, la defensa real de FR-003 es de **capas**: (a) el
storage donde DB-GPT indexa las planillas se monta de solo lectura cuando el motor lo permite, (b)
auditoría del SQL ejecutado como evidencia y alarma temprana. Documentar esto explícitamente
como limitación conocida (no una garantía absoluta a nivel de aplicación) es más honesto que
prometer un enforcement que el backend no puede hacer cumplir desde afuera de un proceso de
terceros.

**Alternatives considered**: correr el motor SQL nosotros mismos (el módulo propio DuckDB que la
investigación original recomendaba) — es justamente la alternativa que el dueño del producto
descartó a favor de usar DB-GPT (ver spec.md, sección "Por qué esta spec existe"); queda como plan
B documentado si la mitigación de capas de este research no resulta suficiente en la práctica.

## R4 — Aislamiento de red del contenedor (FR-002)

**Decisión**: red Docker dedicada (`exact-analysis-net`), sin `ports:` publicados en el servicio
`exact-analysis-engine`, y el servicio `backend` se agrega a esa red ADEMÁS de la red principal
(`sentinel-network`) — mismo patrón que ya usa `anythingllm` en `docker-compose.yml` hoy (`expose:
"3001"` sin `ports:`, solo alcanzable desde la red interna). Se verifica con un scan de red desde
un contenedor de otra red en las pruebas de aceptación (SC-003).

**Rationale**: reusa un patrón ya presente y probado en el mismo compose, cero superficie nueva de
configuración de red que aprender.
