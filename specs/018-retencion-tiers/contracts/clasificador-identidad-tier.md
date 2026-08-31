# Contratos internos — 018

> **Ronda de enmiendas del 13-ago-2026.** El gate adversarial reprobó el PR por una crítica del
> Contrato 1 y por tres afirmaciones falsas del Contrato 2. Las correcciones van marcadas
> *(enmienda aprobada por el manager 13-ago)* donde muerden. Se enmienda la letra, no el
> alcance: las cuatro dicen lo que el código hace y por qué, que es lo que un contrato tiene
> que poder afirmar sin que nadie lo verifique dos veces.
>
> **Ronda del 14-ago-2026 (dictamen firmado del manager).** El gate adversarial volvió a
> reprobar, esta vez la enmienda del 13-ago: el ancla `model='license'` **y** `seq` habría
> BORRADO evidencia legítima. La regla 2 queda **derogada y reescrita** — la exclusión de la
> cadena ya no mira la columna `model` en absoluto: **«la exclusión la compra la FORMA, no el
> literal»**. Entran además dos reglas nuevas: la **5**, que escribe la asimetría vitrina/purga
> en el contrato y no sólo en un docstring, y la **6**, que le pone contador al residuo del
> fail-closed. Las reglas 1 y 4 llevan además una precisión de letra, porque hablaban de «la
> exclusión de la cadena» cuando lo que el portón deja afuera es más que la cadena. Lo que
> cambia acá es la letra Y el comportamiento: un spoof `model='license'` con forma de tráfico
> deja de ser inmortal.

## Contrato 1 · Clasificador de clases de retención (FR-002/FR-003)

**Módulo**: `backend/src/services/retention/classifier.py` — LA única definición de «qué fila pertenece a qué clase».

```
clases() -> list[str]                       # las 4 clases seed, orden estable
predicado(clase: str) -> ColumnElement      # predicado SQLAlchemy sobre AuditLog
clase_de(fila: AuditLog) -> str | None      # clasificación de una fila (para tests de partición)
```

Reglas del contrato:

1. **Partición total de lo purgable**: toda fila de `audit_logs` que **pase el portón** matchea exactamente una clase; lo que el portón deja afuera no matchea ninguna, y eso no es un limbo accidental sino la decisión fail-closed de la regla 6. Test de partición obligatorio sobre dataset sembrado que cubra todos los emisores actuales (blocked%, rejected%, config_change_*, license, tráfico normal). *(precisión 14-ago: la letra decía «una clase o la exclusión de la cadena», y desde el dictamen lo que queda afuera es más que la cadena — regla 2.)*

2. **La cadena de licencias es exclusión ESTRUCTURAL, anclada a la FORMA de `guardian_events`** *(enmienda aprobada por el manager 14-ago; DEROGA la del 13-ago — ver «La enmienda anterior y por qué se cayó»)*. Lo único que habilita un `DELETE` es un portón: la fila se purga sólo si su `guardian_events` **prueba que es tráfico**. Ningún `predicado()` de clase devuelve una fila que no pasó el portón y no existe parámetro para incluirla (FR-003).

   La regla, en la frase del dictamen: **«la exclusión la compra la FORMA, no el literal — dictamen 14-ago».** La columna `model` **no participa del portón en ninguna forma**: la misma forma de `guardian_events` contesta lo mismo diga `license`, `gpt-4o` o nada.

   **Por qué el criterio no puede colgar de `model`.** Esa columna la escribe el INSPECCIONADO: en el passthrough el nombre del modelo sale del cuerpo del pedido y se persiste (`api/gateway.py:1455`), así que cualquiera con una API key válida elige qué dice esa columna en su propia fila. Con la exclusión colgada de ahí, `{"model": "license"}` compraba tres cosas de una sola línea de body:

   1. **inmortalidad** — los predicados de clase negaban la exclusión, así que esa fila (incluido un bloqueo REAL) no caía en ninguna clase y no la borraba ninguna purga. Datos personales sin fecha de muerte es el Art. 5.1.e al revés: el modo de falla exacto que esta spec vino a cerrar;
   2. **invisibilidad** — la vitrina y los agregados de cobertura sacan la cadena por esa MISMA columna (`api/audit.py::_build_query`, `api/analytics.py:88,110`), así que la fila no aparecía ni entre los bloqueados ni entre los permitidos: el inspeccionado se borraba del reporte eligiendo cómo se llama su propio tráfico. **Ojo con la conclusión**: esto NO es un argumento para que la vitrina cambie de criterio — ahí el literal es seguro por la Capa B y volver a él es el dictamen (regla 5). Es el argumento para que la PURGA, que es irreversible, no se apoye en la misma columna;
   3. **veneno para la cadena** — el lector único de la cadena (`chained_entries`, `licensing/audit_events.py:130`, compartido por `verify_chain` `:159` y por el export de true-up, que lo importa en `licensing/trueup_export.py:31`) relee TODAS las filas `model='license'` (`audit_events.py:150`). Una fila ajena y deforme puede hacer que el deployment se acuse solo de TAMPER y que le falle el true-up al cliente: el ataque le rompe al operador la evidencia con la que factura.

   **El precedente de la casa** es `api/inspect.py:88-137`, donde el mismo bug se cazó y se cerró para el campo `tool` de la superficie browser. Ahí está escrita la doctrina — «un firewall cuyo reporte de cobertura lo escribe el inspeccionado no es un reporte» — y también la forma de la respuesta, que es la que se copia acá: **saneo con vocabulario cerrado, no rechazo.** Rechazar dejaría al atacante irse SIN FILA, que es peor que la fila mal etiquetada: el intento desaparece del registro entero en vez de quedar visible con otro nombre.

   **El portón invierte la pregunta.** No pregunta «¿es de licencia?» —que es lo que sólo se puede contestar leyendo una columna del inspeccionado— sino **«¿es demostrablemente TRÁFICO?»**, y sólo entonces habilita el borrado. Todo lo que no lo demuestre queda fuera de lo purgable: es fail-closed por construcción, y el precio está escrito en la regla 6.

   **La forma del predicado es parte del contrato.** SQL normativo, transcripto de la compilación real de `services/retention/classifier.py::_es_purgable()` contra el dialecto `postgresql` (no de memoria):

   ```sql
   audit_logs.guardian_events IS NOT NULL
   AND jsonb_typeof(audit_logs.guardian_events) = 'array'
   AND (audit_logs.guardian_events = CAST('[]' AS JSONB)
        OR jsonb_typeof((audit_logs.guardian_events -> 0)) = 'object'
           AND NOT jsonb_exists((audit_logs.guardian_events -> 0), 'seq')
           AND NOT jsonb_exists((audit_logs.guardian_events -> 0), 'prev_hash')
           AND NOT jsonb_exists((audit_logs.guardian_events -> 0), 'event_type'))
   ```

   Una propiedad de consumo y cuatro piezas del SQL, y las cinco son el contrato:

   - **Viaja en POSITIVO** y en TODOS los predicados de clase, no negado y no en uno solo. Es lo que hace que «no existe camino de configuración que purgue la evidencia de licencias» sea cierto por construcción y no por disciplina del próximo que agregue una clase. Es también el cambio de postura frente al trivalente de SQL: en la letra del 13-ago la exclusión viajaba NEGADA y un NULL ahí volvía la fila inmortal en silencio; acá un NULL **no habilita el borrado**, que es el lado seguro.
   - `IS NOT NULL` + `jsonb_typeof(…) = 'array'`: sin ellas una columna nula o un jsonb que no es lista se colarían como «tráfico» por la puerta del NULL. Son además lo que impide que el resto reviente: `jsonb_array_length` sobre un no-array levanta error y Postgres no garantiza el orden de evaluación de un `AND`, así que la lista vacía se comprueba comparando contra `'[]'::jsonb` —que es total— y no contando.
   - `= '[]'::jsonb` como rama propia: es el caso MAYORITARIO del producto (el tráfico que no disparó ningún guardián) y hay que nombrarlo aparte porque en una lista vacía no hay primer evento que mirar — `'[]'::jsonb -> 0` es NULL y toda la rama siguiente daría NULL. Sin esta rama el predicado deja de ser bivaluado justo en el caso más común.
   - `jsonb_typeof(guardian_events -> 0) = 'object'` antes de mirar las marcas: `jsonb_exists` es la forma función del operador `?`, y `?` sobre un jsonb que no es objeto no falla — sobre un número devuelve false y sobre un string compara el string ENTERO contra la clave. Sin el chequeo de tipo, `[7]` y `["consequence"]` se volverían purgables (las tres marcas contestan «no») mientras `["seq"]` seguiría protegido de casualidad. El gemelo Python pide `isinstance(primero, dict)` por lo mismo, con un borde propio: `"seq" in 7` es `TypeError` y el que se lo come es el purgador.
   - **Las tres marcas, en el `[0]` y no barriendo la lista**: el primer evento es el único que relee el lector de la cadena (`chained_entries`, `audit_events.py:152-154`). Barrer protegería filas que la cadena ni mira, y eso es inmortalidad regalada.

   **Comportamiento normativo, medido contra Postgres 16 real** — sembrando cada forma y evaluando el predicado EN SQL, no razonándolo (la tabla es el oráculo, no al revés). La fila del eslabón vigente no se sembró a mano: se pidió llamando a `emit_license_event`, el emisor de verdad.

   | forma de `guardian_events` | ¿purgable? |
   |---|---|
   | `[]` — tráfico normal, y también el spoof de lista vacía | **sí** |
   | evento de guardián real, `[{"type":"ES_NIF","count":2}]` | **sí** |
   | el sobre del motor, `[{"upstream": […]}]` (`api/chat.py:559-561`) | **sí** |
   | el `seq` en el SEGUNDO elemento | **sí** |
   | eslabón US5 en adelante (`seq` + `prev_hash` + `event_type`) | no |
   | **licencia pre-US5: `event_type`, sin `seq` ni `prev_hash`** | **no** |
   | tráfico con blob forjado (cualquiera de las tres marcas en el `[0]`) | no |
   | SQL `NULL` · el JSON `null` (`'null'::jsonb`) | no |
   | `["seq"]`, `["consequence"]`, `[7]` — primer elemento que no es objeto | no |
   | un objeto pelado (`{"seq": 1}`, que no es lista) | no |

   **Por qué las TRES marcas y no sólo `seq`.** `seq` y `prev_hash` las escribe `_append_chained` (`licensing/audit_events.py:253-263`) desde la 021 US5; `event_type` existe desde la 021 US1 y nunca se fue. Con las tres, el predicado **no depende del vocabulario**: no enumera tipos de evento, pregunta si el primer evento tiene forma de eslabón, así que el día que la cadena estrene un evento nuevo la fila sigue trayendo `event_type` y sigue protegida sin que nadie toque el clasificador. Un ancla que listara `license_loaded`, `license_grace`… envejecería con el primer evento nuevo, y envejecer acá significa borrar evidencia.

   **La enmienda anterior y por qué se cayó.** La letra del 13-ago decía: es de la cadena la fila con `model='license'` **y** con `seq` en su primer `guardian_event`. Cerraba el spoof, pero anclar en `seq` habría **borrado irreversiblemente filas de licencia legítimas**, y está verificado en el historial del repo:

   - `git log -S'"seq"' -- backend/src/licensing/audit_events.py` devuelve **un solo commit**: `9cd7b99` (021 US5, 20-jul-2026), el mismo que introduce `"prev_hash"`;
   - `git log -S'"event_type"'` sobre el mismo archivo devuelve `0a8cda1` (021 US1, 16-jul-2026).

   O sea que entre el 16 y el 20 de julio el emisor de la 021 escribió filas de licencia LEGÍTIMAS, con el `model='license'` puesto, que **no traen `seq` ni `prev_hash`**. Con el ancla del 13-ago esas filas no eran «de la cadena»: caían en clase mortal por su `compliance_status` —varias escriben `blocked_by_policy`, el default de `_COMPLIANCE_BY_EVENT` (`audit_events.py:271`)— y el purgador las borraba. Destrucción irreversible de evidencia de licencia causada por nuestro propio fix: el incidente de confianza de FR-003 provocado por la defensa en vez de por el ataque. El portón por forma las protege por `event_type`, y lo clava `test_la_licencia_pre_us5_no_la_borra_nadie`.

   **Y por qué cayó también la condición aditiva.** Hasta el 14-ago al portón se le sumaba `coalesce(model,'') <> 'license'` como defensa en profundidad. No protegía **ninguna fila legítima**, medido:

   - el emisor de la cadena (`_append_chained`, `licensing/audit_events.py:247-277`) es **escritor único** de `model='license'` en el fuente y escribe siempre UNA sola forma — `{event_type, license_id, seats_used, max_seats, reason, ts, prev_hash, seq}` (`:254-263`) —, que el portón excluye por `seq`, por `prev_hash` y por `event_type`, cualquiera de las tres;
   - la única otra forma legítima que existe es la pre-US5, y el portón también la excluye, por `event_type`. Las DOS formas legítimas quedan protegidas por la forma sola;
   - lo único que la aditiva mantenía con vida eran los SPOOFS `model='license'` **ya escritos** en la base de un cliente instalado — y les compraba inmortalidad PERMANENTE. La Capa B impide los NUEVOS, no limpia los VIEJOS.

   Costo puro: cero filas legítimas protegidas, filas de tráfico inmortales de regalo. **Cambio de comportamiento de esta ronda**: un spoof `model='license'` con forma de tráfico ahora tiene clase y muere con su plazo (`test_la_exclusion_la_compra_la_forma_no_el_literal`).

   **El requisito que compra el acoplamiento (exigencia del manager, 14-ago).** Desde que cayó la aditiva, la forma es la ÚNICA defensa de la evidencia de licencias en la purga: no hay una segunda red debajo. Por eso el contrato exige un **test verdugo** que acople el emisor al portón — que tome la salida REAL de `_append_chained` llamando a `emit_license_event` (**no un fixture**) y afirme en SQL que esa fila NO es purgable por el portón. Si mañana alguien le cambia la forma al emisor —le saca `event_type`, lo renombra—, el rojo aparece EN EL ACTO y no como filas de licencia muriendo en la purga de un cliente. Lo implementa `tests/unit/test_retention_classifier.py::test_la_forma_que_emite_el_emisor_real_no_es_purgable`, y afirma además que el primer evento trae al menos una de las marcas: sin eso, un emisor que cambiara de forma podría seguir dando `False` por accidente y el test no distinguiría «protegida por la marca» de «protegida por casualidad».

   **Asimetría con los lectores de la cadena: SUPERCONJUNTO, y es deliberada.** El portón **no** protege exactamente las mismas filas que los lectores consideran eslabón. Ellos deciden con `_is_chain_link` (`licensing/audit_events.py:87`), que exige un dict con `seq` **y** `prev_hash`, con `seq` entero. El portón protege además: las licencias pre-US5, las formas que traen sólo una de las dos claves, y todo lo que no sabe reconocer (columna nula, jsonb que no es lista, primer evento que no es objeto). Son **dos preguntas distintas sobre las mismas filas**, no dos respuestas a la misma: la purga protege EVIDENCIA (todo lo que escribió nuestro emisor, se pueda releer como eslabón o no) y los lectores verifican ESLABONES (sólo lo que se puede releer como tal). Un evento pre-US5 es las dos cosas a la vez — evidencia que no se reconstruye y no-eslabón —, y cada lado contesta la suya.

   Lo que importa es la DIRECCIÓN: proteger de MÁS cuesta filas de metadata vivas de más; proteger de MENOS borra una fila que los lectores esperan, y eso es un hueco de `seq` que `verify_chain` reporta como manipulación y un true-up que le falla al cliente. **Regla derivada: el portón nunca se puede volver más estricto que `_is_chain_link` sin discutirlo acá primero.**

   **Dos capas, no un reemplazo.** El saneo del literal reservado en la puerta (`gateway.sanear_modelo_declarado`, `api/gateway.py:908`, consumido también por el plano motor en `api/internal.py:279`) desaloja al okupa al centinela `license__cliente`. Son independientes a propósito: la Capa B impide que el literal se escriba de ahora en más; el portón hace que escribirlo no sirva de nada. A las filas que ya estén en la tabla de una instalación viva sólo las alcanza el portón — y desde esta ronda las alcanza de verdad, en vez de dejarlas inmortales.

3. **Consumidores obligatorios**: purgador y vitrina (`api/audit.py` — sus constantes locales `BLOQUEADO_LIKE`/`MODELO_LICENCIA`/rechazados se reemplazan por llamadas al clasificador). Criterio: paridad exacta de resultados de la vitrina pre/post refactor. El purgador consume `predicado()`/`clase_de()`; la vitrina consume las primitivas sueltas (`es_bloqueo()`, `es_rechazo()` y la exclusión de la cadena). **Compartir el módulo no es compartir el criterio de exclusión de la cadena**: purga y vitrina excluyen distinto, a propósito — regla 5.

4. **Un emisor nuevo con literal no clasificado DEBE romper un test — y lo rompe por censo del fuente, no por caer en un limbo** *(enmienda aprobada por el manager 13-ago)*. La letra original («debe romper el test de partición») se leía, junto con la firma `clase_de() -> str | None`, como si existiera un tercer estado «sin clasificar». No existe, y no debe existir: los prefijos del mapeo son TOTALES y lo que nadie previó cae en la clase fail-safe `usage_metadata` (365 d). Entre «murió con el plazo equivocado» y «no muere nunca y nadie se entera», la spec eligió lo primero — el segundo es el modo de falla que la 018 vino a matar, así que una regla que EXIJA el limbo para poder detectar el emisor nuevo estaría pidiendo el bug como mecanismo de alarma. `None` significa una sola cosa y no dos: **la fila no pasó el portón** *(precisión 14-ago: la letra decía «eslabón de la cadena», y eso es sólo una parte de lo que el portón deja afuera — también quedan las licencias pre-US5 y las formas que el portón no reconoce, regla 6)*.

   La presión de la regla se conserva entera y por un camino mejor: el test de partición (`tests/unit/test_retention_classifier.py`) **censa los `compliance_status` que emite el FUENTE de los dos planos** y los contrasta contra el inventario `EMISORES_VIGENTES` del clasificador; un emisor nuevo sin inventariar pone el test en rojo con su `archivo:línea`. Muerde cuando alguien ESCRIBE el emisor, no cuando alguien se acuerda de sembrar una fila con él en un dataset de test — que es lo mejor que podía dar la letra original. Ya cazó uno real: `blocked_entity_type` (plano motor, `sentinel_guardrail.py:594`) clasificaba bien por prefijo, pero nadie había decidido su plazo por escrito.

5. **La VITRINA excluye la cadena por LITERAL y la PURGA por FORMA, y eso NO es una inconsistencia** *(dictamen del manager 14-ago, punto b — va en el contrato y no sólo en un docstring)*. La frase normativa, textual:

   > **purga = por forma (irreversible → no confía en nadie); vitrina = por literal (reversible → y el literal ya es nuestro gracias a la Capa B)**

   Las dos mitades son el argumento:

   - **irreversible vs reversible**. Un `DELETE` mal decidido destruye evidencia que no se reconstruye, así que ahí no se confía en una columna que escribe el inspeccionado; una fila mal escondida de un balde de la pantalla se sigue viendo en el listado sin filtro, que la muestra igual;
   - **el literal ya es nuestro**. La Capa B (`gateway.sanear_modelo_declarado`, consumida por `api/gateway.py` en la puerta y por `api/internal.py:279` del lado del motor) desaloja `license` al centinela `license__cliente` antes de que toque la columna, así que en una instalación nueva el cliente no lo puede escribir. Si alguien saca ese saneo, el criterio de la vitrina deja de ser una exclusión y pasa a ser un escondite que se pide con una API key: **las dos se leen juntas o no se leen.**

   **Por qué la vitrina NO puede usar «literal + `seq`»**, que fue lo que se probó en la ronda del 13-ago: con esa exclusión una fila de licencia **pre-US5** —`event_type`, sin `seq`— se le muestra al officer en el balde «bloqueados», mezclada con los intentos de fuga de los usuarios. Medido: `total=1` donde `main` da `0`. Es superficie viva de cliente y no se negocia — la vitrina vuelve al literal pelado, como en `main`.

   **Piezas obligatorias de esta regla**, para que no quede en prosa:

   - el criterio de la vitrina es el literal pelado, y se pide al clasificador (`dice_licencia()`), nunca con una constante suelta en la pantalla — eso es lo que FR-002 compra;
   - la frase normativa de arriba va **textual** en el docstring de `api/audit.py::_build_query`, que es donde la va a leer el próximo que toque el filtro;
   - la medición va como test y no como afirmación: `tests/unit/test_retention_classifier.py::test_por_que_la_vitrina_no_puede_usar_es_licencia` (las dos primitivas contestan distinto sobre la fila pre-US5) y `tests/integration/test_audit_filtro_estado.py::test_la_licencia_pre_us5_tampoco_entra_en_ninguno_de_los_dos_baldes` (la superficie, extremo a extremo).

   **NOTA (no bloqueante), y es HERENCIA de `main`, no una regresión de esta ronda**: un spoof VIEJO con `model='license'` que ya esté en la base de una instalación sigue invisible en la vitrina. Lo que cambió es que ahora ES purgable por forma, así que el problema **se extingue solo con las corridas de purga** en vez de quedarse para siempre.

6. **Fail-closed con contador: lo que el portón deja atrás se CUENTA** *(dictamen del manager 14-ago, punto c)*. Un `guardian_events` nulo —el SQL `NULL` o el JSON `null`— **no prueba que la fila sea tráfico**, así que no se borra. Eso es el fail-closed y es correcto; la mitad inaceptable era el «nadie se entera».

   Requisito de contrato: **la corrida de purga reporta `filas_no_clasificadas`**, y lo reporta **también en la corrida `dry_run`** — el officer que ensaya la purga tiene que ver el residuo ANTES de apretar el botón, no después. El contador vive en el resultado de la CORRIDA (`purger.ResultadoCorrida`, T008) y no en el de cada clase (`ResultadoPurga`) —un residuo que no se pudo clasificar no tiene clase a la que colgarse—, y tampoco en el clasificador: la decisión de no borrar y la de contar son la misma decisión partida en dos archivos.

   Doctrina del depto que las une, y que es la que gobierna los desempates de esta spec: **entre borrar de más y borrar de menos, el default va del lado REVERSIBLE.** Los tests que exigían que esas filas murieran quedan enmendados con ese motivo escrito.

   Ojo con no confundir esta dirección con la del reparto por clases, que es la opuesta a propósito: el reparto es fail-SAFE (un `compliance_status` que nadie inventarió cae igual en una clase MORTAL) porque ahí lo que está en juego es una fila de TRÁFICO que si sobrevive rompe el Art. 5.1.e sin que nadie se entere; el portón es fail-CLOSED porque ahí lo que está en juego puede ser evidencia que no se reconstruye.

## Contrato 2 · Identidad batch bajo RLS (FR-006 — costura 017)

Todo job batch que toque tablas bajo RLS declara identidad con el mecanismo existente:

```python
with tenant_context(None, bypass=True):    # database.py:65
    with session_factory() as db:          # la sesión NACE y MUERE acá adentro
        ...                                # trabajo del job
```

*(enmienda aprobada por el manager 13-ago — tres correcciones sobre la letra original, que era falsa en las tres.)*

**a. El snippet no compilaba.** Decía `tenant_context(bypass=True)`, y la firma real es `tenant_context(tenant_id, bypass=False)` con `tenant_id` **posicional** (`database.py:65`): copiar el contrato tal cual daba `TypeError`. La forma correcta es `tenant_context(None, bypass=True)`, y ese `None` no es relleno para satisfacer a la firma — dice «este job no es de ningún tenant», que es exactamente el motivo por el que necesita el bypass.

**b. El precedente citado no existe.** La letra original ofrecía `gateway.py:901` como precedente del bypass. Ahí no hay ningún bypass: hay `with tenant_context(tid):` (hoy `gateway.py:977`, dentro de `_audit`, `:933`), tenant SCOPEADO y sin bypass — el opuesto semántico exacto de lo que se estaba citando. La verdad, que es lo que un contrato tiene que decir: **este PR estrena `bypass=True` en producción.** Antes de esta rama no había un solo `bypass=True` en `backend/src` (`git grep bypass=True HEAD -- backend/src`: cero resultados); el mecanismo estaba ejercitado únicamente en `tests/test_rls_isolation.py:196-210`. Los tres primeros usuarios de producción nacen acá: el emisor de la cadena (`licensing/audit_events.py:324`, el `with` de `emit_state_event`; `:247` es sólo la firma de `_append_chained`), el reconciliador de licencias (`licensing/reconcile.py:208`) y el purgador (T008).

   Que el precedente sea falso no es un error de referencia: convierte «esto ya se hace así en producción» en el argumento que sostiene la regla, cuando el argumento verdadero es el contrario — se hace por primera vez, nadie tiene la costumbre todavía, y por eso la regla (c) va escrita en vez de darse por sabida.

**c. El bypass no muere con el `with`: muere con la TRANSACCIÓN.** El listener de `database.py:44-61` inyecta `set_config('app.bypass_rls', 'on', true)` en `after_begin`, y ese tercer argumento es `is_local` — o sea `SET LOCAL`, que vive hasta el commit/rollback y no hasta que el context manager salga. Lo que el `with` sí revierte son los ContextVar (por eso el bypass no queda de default de sesión, y eso está testeado). El GUC ya inyectado se queda puesto en la transacción abierta.

   De ahí sale la regla operativa, que es la que hace que ese `with` alcance: **la sesión se abre y se cierra DENTRO del bloque; el módulo recibe `session_factory` y JAMÁS una `Session` ya viva.** Una sesión creada afuera que dispare su primera consulta adentro abre su transacción adentro y se lleva el bypass a TODO lo que haga después, ya fuera del bloque — un bypass de RLS fugado de su alcance, en el proceso que además hace `DELETE`. Pedir una factory no lo vuelve imposible (nada impide un `lambda: db_ya_viva`), lo vuelve VISIBLE: el camino natural es abrir adentro, y colar una sesión viva hay que escribirlo a propósito y se ve en el diff. Patrón vivo del que sí es precedente después de esta rama: `licensing/audit_events.py::emit_state_event`, que crea y cierra su sesión dentro del bloque.

Reglas:

1. **Prohibido** `SessionLocal()` pelado en jobs (el emisor de la cadena, `audit_events.py`, se corrige a este contrato en esta spec). El pelado funciona hoy sólo porque la policy permisiva `tenant_isolation_bootstrap` de la 010 sigue viva; cuando la 017 la elimine, un job sin identidad declarada pasa de borrar a NO VER FILAS — retención que aparenta estar enforced sin estarlo, el peor modo de falla posible para esta spec.
2. El bypass es **explícito y localizado** — nunca un default de sesión — y su alcance real es la transacción, no el bloque léxico (ver **c**).
3. **Criterio verificable (SC-004)**: fixture de harness que (a) dropea `tenant_isolation_bootstrap` y (b) conecta con un rol NOSUPERUSER; la suite de purga + el emisor de la cadena pasan bajo esa fixture. Ese es el mundo que la 017 activa después — acá se prueba antes.

## Contrato 3 · Capa de tier sobre el registry 027 (FR-008)

- Clave: `enforcement_tier_estricto` — alta en el registry puro compartido (`sentinel_governance.py`), decision `on`/`off`.
- Semántica: `on` = `estricto`, `off`/ausente = `estándar`. La capa de piso `ai_act_evaluation` se evalúa SIEMPRE, cualquiera sea el tier (invariante 027).
- Consumidores backend:
  1. **Pisos/topes de retención** en `PUT /compliance/retention` (tabla research.md D7) — violación → error de validación (SC-005).
  2. **Postura de auditoría**: tier `estricto` exige `SENTINEL_AUDIT_FAIL=closed`; incoherencia → health degradado + evento auditado. **No** se reescribe el env ni se toca el espejo triple del motor.
  3. Consecuencias de capas con grado (bloquear vs registrar) según resolución 027 vigente.
- Cambio de tier: auditado con valor anterior y nuevo (SC-006). El plano motor no consume esta capa en v1 (decisión de diseño — evita rebundle).
- **Costura 037/perfil**: el bloque `compliance_tier` reservado en el schema del perfil (sellado con Cristian/Falime 13-ago) escribe esta capa al instalar; la licencia autoriza los juguetes, el perfil solo configura.

## Contrato 4 · Arranque seguro del purgador (FR-001) *(enmienda aprobada por el manager 13-ago)*

Dos perillas gobiernan que la primera imagen con purgador adentro no borre nada de nadie. Ninguna de las dos alcanza sola, y por eso entran juntas al contrato:

| perilla | default | qué gobierna |
|---------|---------|--------------|
| `SENTINEL_PURGE_ENABLED` | **`false`** | interruptor maestro: el scheduler ni se despierta |
| `SENTINEL_PURGE_DRY_RUN` | **`true`** | simulacro: resuelve cutoff, CUENTA y deja rastro, no borra |

**`SENTINEL_PURGE_ENABLED=false` en los tres lugares donde se declara** (`.env.example`, `docker-compose.yml`, `deploy/docker/compose.prod.yml`). Por qué el default cambió de `true`: un job de `DELETE` retroactivo no se enciende con un `docker pull`. El `.env` de la sede se escribe HOY y la imagen con purgador llega después, así que un `true` acá sería ese pull encendiendo, solo, un borrado sobre datos del cliente sin que nadie lo hubiera decidido. Encender es un paso EXPLÍCITO del runbook: reinicio del backend, con el conteo del simulacro ya firmado. La tensión con el Art. 5.1.e queda escrita y aceptada: una retención que todavía no purga se arregla con un `true`; una purga que se encendió sola y borró de más no se arregla con nada.

**`SENTINEL_PURGE_DRY_RUN=true`** es la séptima perilla y la única que NO viene de la tabla sellada del plan. Entra ahora justamente porque los nombres de este bloque todavía no están publicados en la doc del cliente: agregarla después de publicar ya no sería agregar una perilla, sería cambiar el contrato de configuración de las instalaciones que existan. Semántica (`purger.py`, §Simulacro y `purgar_clase`): se resuelve el cutoff de cada clase con el MISMO predicado que usaría para borrar, se cuenta lo que caería y se escribe el rastro marcado `dry_run: true`; no se emite ni el `DELETE` de `audit_logs` ni el `NULL` de `human_reviews.response_text`.

Por qué default y no modo de debug: la primera corrida real de una instalación no tiene el backlog de un día, tiene el de toda la vida de la caja, y lo borrado no vuelve. El simulacro es lo que le permite al DPO ver el número —«se van 412.000 filas de esta clase, con este cutoff»— y FIRMAR antes de que pase. Encender la purga y descubrir el alcance leyendo el rastro de lo ya borrado es el orden inverso.

Reglas:

1. **`run_now` y `dry_run` son ejes ORTOGONALES** — uno es CUÁNDO y el otro es SI BORRA — y la combinación más pedida es la cruzada: «corré ahora y decime cuánto se iría». Un simulacro es además lo único honesto que se puede correr fuera de la ventana o en horario de oficina: no toma locks de escritura.
2. **En simulacro, `ok`/`partial` hablan del CONTEO, no del borrado.** `ok` es «terminé de contar todo el backlog vencido»; leerlo como «la clase quedó al día» en una corrida con `dry_run: true` es leer mal, porque ahí no quedó al día nada.
3. **`ResultadoPurga.dry_run` es obligatorio en el constructor, sin default.** Es lo que le da sentido a `rows_deleted` (en simulacro, ese número es lo que se HABRÍA borrado): sin el campo, simulacro y corrida real dejan un rastro idéntico y el registro pasa a afirmar borrados que nunca ocurrieron — un rastro de purga que miente sobre si purgó es peor que no tenerlo, porque es el papel con el que el DPO contesta una reclamación. Un default —cualquiera de los dos— sería la puerta para que una rama nueva se olvide de setearlo y quede clasificada en el modo equivocado en silencio.
