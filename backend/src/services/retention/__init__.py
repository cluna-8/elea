"""Enforcement de retención (spec 018 — «Retención con dientes»).

Hasta acá, la retención del producto era una DECLARACIÓN: `retention_policies` (seed 004)
guarda cuántos días vive cada clase de dato, la pantalla del DPO lo muestra, el DPA lo
promete… y nadie borraba nada. La fila del día 500 seguía ahí. Este paquete es la parte que
convierte esa promesa en un hecho verificable ante un auditor (RGPD Art. 5.1.e).

Qué vive acá:

- `classifier.py` — LA única definición de «qué fila de `audit_logs` pertenece a qué clase
  de retención» (FR-002), consumida por el purgador Y por la vitrina de auditoría. Sin un
  solo lugar, purgador y vitrina cuentan cosas distintas sobre la misma tabla.
- `purger.py` — la corrida (US1): cutoff contra el reloj de la DB, DELETE por lotes acotados
  dentro de la ventana horaria (T008), muerte del único texto real durable
  (`human_reviews.response_text`, FR-004/T009) y rastro auditable de cada corrida
  (`purge_log` por clase + fila resumen `config_audit`, FR-005/T010). Invocable a mano por CLI
  (`python -m src.services.retention.purger --run-now`). Simulacro por default: no borra hasta
  `BASA_PURGE_DRY_RUN=false`.

Qué NO vive acá, a propósito:

- El **scheduler** es el módulo hermano `services/retention_scheduler.py`, siguiendo el
  precedente de `licensing/reconcile.py`: quién decide CUÁNDO se corre es una preocupación
  distinta de QUÉ se borra, y el purgador tiene que ser invocable a mano (`--run-now`) sin
  arrastrar un thread.
- La **fuente de configuración** de los plazos: hoy es `retention_policies` (013/004) y
  mañana el PolicyBundle de la 036 (FR-003 de Cristian). Este paquete CONSUME la fuente
  vigente; no la reemplaza ni la duplica.
- El **plano motor** (`litellm/`): la purga es un job del backend, no toca el espejo triple
  ni exige rebundle (decisión de diseño de la 018).

Invariante permanente del paquete: la cadena de evidencia de licencias (spec 021) NO se purga
jamás. `verify_chain` acusa manipulación ante cualquier hueco y el true-up exige historial
completo — borrar un eslabón no es un bug, es un incidente de confianza con el cliente. La
exclusión es estructural en el clasificador: no hay parámetro, env ni pantalla que la levante.

Y la mitad nueva, abierta el 13-ago y sellada el 14: **decir `license` no alcanza para comprar
la exclusión.** La regla ya no se apoya en la columna `model` — hoy no la mira en absoluto —,
porque esa columna la escribe el INSPECCIONADO: en el passthrough el nombre del modelo sale del
cuerpo del pedido y se persiste tal cual (`api/gateway.py:1455`). Colgar de ahí una fila que
ninguna purga toca era vender, por una línea de body y con cualquier API key válida, tres cosas
de una: inmortalidad para datos personales (el Art. 5.1.e al revés, o sea el modo de falla que
esta spec vino a cerrar), invisibilidad en la vitrina y en los agregados de cobertura
(`api/analytics.py:88,110`), y una fila deforme metida en el barrido de la cadena, que puede
hacer que el deployment se acuse solo de TAMPER.

Lo que ancla la exclusión es la FORMA de `guardian_events`, y nada más: **«la exclusión la
compra la FORMA, no el literal» (dictamen del manager, 14-ago).** El portón invierte la
pregunta — no dice «¿es de licencia?» sino «¿es demostrablemente TRÁFICO?» — y sólo si la
respuesta es sí habilita el `DELETE`. Queda fuera de lo purgable la columna nula (el SQL `NULL`
y el JSON `null`), el jsonb que no es un array, el array cuyo primer evento no es un objeto, y
el array cuyo primer evento trae cualquiera de las tres marcas que escribe el emisor de la
cadena: `event_type` (021 US1, 0a8cda1, 16-jul-2026),
`prev_hash` y `seq` (021 US5, 9cd7b99, 20-jul-2026). El predicado y sus bordes viven en
`classifier.py`; el porqué completo, en el Contrato 1 de
`specs/018-retencion-tiers/contracts/`.

**El portón NO protege exactamente las mismas filas que los lectores de la cadena, y esa
asimetría es deliberada.** Protege un SUPERCONJUNTO. `verify_chain` y el export de true-up
comparten un solo lector (`chained_entries`, `licensing/audit_events.py:130`) que decide con
`_is_chain_link` (`:87`): exige un dict con `seq` **y** `prev_hash`, con `seq` entero. El
portón protege además —y esos lectores ignoran— las filas de licencia legítimas anteriores a
la US5 (`event_type`, sin `seq` ni `prev_hash`: la ventana 16→20-jul), las que traen sólo
`prev_hash`, y cualquier forma que no sepa reconocer (`guardian_events` nulo, un jsonb que no
es lista, un primer evento que no es objeto).

No son dos respuestas distintas a la misma pregunta: son dos preguntas distintas sobre las
mismas filas. La purga protege EVIDENCIA — todo lo que escribió nuestro emisor, se pueda releer
como eslabón o no —; los lectores verifican ESLABONES — sólo lo que se puede releer como tal —.
Un evento pre-US5 es evidencia de licencia que no se reconstruye y NO es un eslabón
verificable: las dos cosas a la vez, y cada lado contesta la suya.

Por eso lo que importa es la DIRECCIÓN de la asimetría, no su tamaño. Proteger de más cuesta
filas de metadata vivas de más. Proteger de menos borra una fila que los lectores esperan —
hueco de `seq` que `verify_chain` reporta como manipulación, historial que le falta al true-up
—, y eso es el incidente de confianza de FR-003 provocado por la defensa en vez de por el
ataque. De ahí la regla: este portón nunca se puede volver más estricto que `_is_chain_link`
sin que alguien lo discuta primero en el Contrato 1.

Esto convive con el saneo del literal reservado en la puerta del gateway
(`gateway.sanear_modelo_declarado`, Capa B), y no lo reemplaza: el saneo impide que el literal
se escriba de ahora en más; el portón hace que escribirlo no sirva de nada, ni antes ni ahora.
A las filas que YA estén en la tabla de una instalación viva sólo las alcanza el portón, y
desde el dictamen del 14-ago las alcanza de verdad: un spoof `model='license'` con forma de
tráfico dejó de ser inmortal y muere con su clase, así que el residuo viejo se extingue solo
con las corridas de purga en vez de quedarse para siempre.

Ojo con una asimetría más, que también es del dictamen y NO es una inconsistencia: la VITRINA
(`api/audit.py`) excluye la cadena de sus baldes por el LITERAL pelado, no por el portón.
«Purga = por forma (irreversible → no confía en nadie); vitrina = por literal (reversible → y
el literal ya es nuestro gracias a la Capa B)». El argumento completo está en el docstring de
`classifier.dice_licencia()` y en la regla 5 del Contrato 1.
"""
