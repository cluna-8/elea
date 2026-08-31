"""Clasificador de clases de retención — la ÚNICA definición de «qué fila es de qué clase».

Spec 018, FR-002/FR-003 · Contrato 1 de `specs/018-retencion-tiers/contracts/`.

## Estado real de este módulo (14-ago-2026)

- El mapeo está COMPLETO (T003) y su test de partición (T004,
  `tests/unit/test_retention_classifier.py`) está VERDE. Ese test no lee este archivo para
  acomodarle las expectativas: censa los `compliance_status` del FUENTE de los dos planos y
  los contrasta contra `EMISORES_VIGENTES`, así que la presión de la regla 4 (abajo) existe y
  muerde hoy — un emisor nuevo sin inventariar lo pone en rojo con su `archivo:línea`.
- El primer consumidor EN PRODUCCIÓN es la vitrina de auditoría (`api/audit.py`, T005), que
  importa las tres primitivas en `api/audit.py:19` y filtra con `es_bloqueo()`, `es_rechazo()`
  y `~dice_licencia()` (`:271`). La migración que pedía el dictamen del 14-ago —de
  `~es_licencia()` a `~dice_licencia()`— YA OCURRIÓ, en este mismo PR: `dice_licencia()` tiene
  hoy su consumidor de producción y no queda ningún llamador de `es_licencia()` en
  `backend/src` (medido, ver su docstring). La pantalla quedó con un puntero a este módulo, no
  con una constante suelta con el literal.
- **Dos preguntas distintas, dos criterios distintos, y esto es el resumen de por qué**
  (dictamen del manager, 14-ago; el argumento largo está más abajo en «El portón» y en
  «La vitrina excluye por LITERAL»):

      purga   = por FORMA    (irreversible → no confía en nadie)
      vitrina = por LITERAL  (reversible   → y el literal ya es nuestro gracias a la Capa B)

- **El purgador YA consume este módulo.** `purger.py` (`run_once`) arma el `WHERE` del
  `DELETE` por lotes con `predicado()` y recorre `clases()`; el scheduler (T011) lo
  dispara desde `main.py:89`. La vitrina (T005, ver arriba) sigue siendo consumidor de
  sólo lectura.

## Por qué el mapeo vive en código y no en el esquema (research.md D1)

`audit_logs` no tiene columna `log_type`. Las 4 políticas del seed 004
(`alembic/versions/004_compliance_tables.py`, líneas 100-109) se distinguen ÚNICAMENTE por
literales de otras columnas — `model`, `compliance_status` —, y la vitrina de auditoría ya
duplicaba ese criterio en constantes locales. Agregar la columna sería más limpio, pero exige
migración sobre la tabla más caliente del producto y renegociar el rabbit-hole sellado de la
Parte 4 del BRIEF de Cristian («no tocar el esquema de `audit_logs`»). Se eligió un
clasificador único en código: una sola verdad, cero migraciones, y el esquema queda intacto.

## Las 4 clases (seed 004 — plazos por defecto, editables por el DPO)

| clase             | plazo default | qué es                                            |
|-------------------|---------------|---------------------------------------------------|
| `prompt_content`  | 90 d          | contenido de prompts/respuestas                    |
| `usage_metadata`  | 365 d         | metadatos de uso: tokens, coste, modelo, timestamp |
| `security_events` | 365 d         | bloqueos de guardianes y alertas de seguridad      |
| `config_audit`    | 730 d         | cambios de configuración del sistema               |

Los nombres son los `log_type` de `retention_policies`: son la llave con la que el purgador
busca el plazo VIGENTE (que el DPO pudo haber cambiado). Este módulo mapea filas → clase; no
lee plazos ni decide vencimientos.

## El mapeo, en una tabla

Se resuelve en dos pasos y en este orden — la habilitación del borrado SIEMPRE primero:

| se mira                                                   | va a                          |
|-----------------------------------------------------------|-------------------------------|
| la fila NO es demostrablemente tráfico (ver abajo)         | **nada**: no se purga         |
| `compliance_status` empieza `config_change`                | `config_audit`                |
| `compliance_status` empieza `blocked`                      | `security_events`             |
| todo el resto                                              | `usage_metadata`              |
| —                                                          | `prompt_content` (cero filas) |

El primer renglón es el PORTÓN, y es el único: la columna `model` NO aparece en esta tabla —
«la exclusión la compra la FORMA, no el literal» (dictamen 14-ago). Los tres renglones
siguientes reparten lo que pasó el portón.
Que el reparto sea por prefijos totales, con `usage_metadata` de fail-safe, no es comodidad: un
literal de estado que nadie previó cae en una clase MORTAL (365 d) en vez de quedar sin
predicado y sobrevivir para siempre. Entre «murió con el plazo equivocado» y «no muere nunca y
nadie se entera», la spec eligió lo primero. Ojo con no confundir ese fail-safe con el
fail-CLOSED del portón: son direcciones opuestas a propósito y el porqué está abajo, en «Las
dos direcciones».

## El portón: «¿es demostrablemente TRÁFICO?», no «¿es de licencia?»

Una ronda anterior ancló la exclusión de la cadena a `model='license'` **y** `seq` en
`guardian_events[0]`. Cerraba el spoof, pero tenía un agujero histórico que la purga convierte
en pérdida irreversible, y está VERIFICADO en el propio historial del repo:

    0a8cda1 (16-jul, 021 US1)  emit_license_event → guardian_events=[{event_type, license_id,
    1a93cf3 (17-jul, 021 US3)                                        seats_used, max_seats,
    8e8f705 (17-jul, 021 US4)                                        reason, ts}]
    9cd7b99 (20-jul, 021 US5)  _append_chained → recién acá aparecen `prev_hash` y `seq`

O sea que entre el 16 y el 20 de julio el emisor de la 021 escribió filas de licencia
LEGÍTIMAS, con el `model='license'` puesto, que **no traen `seq`**. Con el ancla anterior esas
filas no eran «de la cadena», caían en la clase mortal por su `compliance_status` y el purgador
las borraba: destrucción irreversible de evidencia de licencia causada por nuestro propio fix,
que es el incidente de confianza de FR-003 provocado por la defensa en vez de por el ataque.

El predicado nuevo invierte la pregunta. En vez de «¿es de licencia?» pregunta **«¿es
demostrablemente tráfico?»**, y sólo entonces habilita el borrado:

    guardian_events IS NOT NULL
    AND jsonb_typeof(guardian_events) = 'array'
    AND ( guardian_events = '[]'::jsonb
          OR ( jsonb_typeof(guardian_events->0) = 'object'
               AND NOT (guardian_events->0 ? 'seq')
               AND NOT (guardian_events->0 ? 'prev_hash')
               AND NOT (guardian_events->0 ? 'event_type') ) )

Medido contra Postgres 16 real (la tabla es el oráculo de los tests, no al revés). La columna
`model` no entra en la medición porque **no entra en el predicado**: la misma forma contesta lo
mismo diga `license`, `gpt-4o` o nada.

| forma de `guardian_events`                                  | borrable |
|-------------------------------------------------------------|----------|
| `[]` — tráfico normal, y también el spoof de lista vacía    | **sí**   |
| evento de guardián real `[{"type":"ES_NIF","count":2}]`      | **sí**   |
| el sobre del motor `[{"upstream": […]}]` (`chat.py:559-561`) | **sí**   |
| `[{}]`                                                      | **sí**   |
| el `seq` en el SEGUNDO elemento                             | **sí**   |
| SQL `NULL`                                                  | no       |
| el JSON `null` (`'null'::jsonb`)                            | no       |
| eslabón con `seq` (021 US5 en adelante)                     | no       |
| **licencia pre-US5: `event_type`, sin `seq` ni `prev_hash`** | **no**   |
| tráfico con blob forjado (`seq`/`prev_hash`/`event_type`)    | no       |
| `["seq"]` — primer elemento que no es objeto                | no       |
| `["consequence"]`, `[7]` — ídem, y son las que muerden      | no       |
| un objeto pelado (`{"seq": 1}`, que no es lista)             | no       |

Tres propiedades del predicado, y las tres son el contrato:

1. **No depende del vocabulario.** No enumera tipos de evento: pregunta si el primer evento
   tiene FORMA de eslabón. `event_type` es la marca que la cadena estrenó en la 021 US1 y no
   soltó nunca (`audit_events.py:255`); `prev_hash` y `seq`, las que agregó US5
   (`audit_events.py:261-262`). El día que la cadena estrene un evento nuevo, la fila sigue
   trayendo `event_type` y sigue protegida sin que nadie toque este archivo. Un ancla que
   listara `license_loaded`, `license_grace`… envejecería con el primer evento nuevo, y
   envejecer acá significa borrar evidencia.
2. **Es estrictamente BIVALUADO**: ninguna de las formas que la columna admite —ni el SQL NULL,
   ni el JSON `null`, ni el objeto que no es lista— devuelve NULL. Está medido y hay test
   propio que lo afirma forma por forma
   (`test_retention_classifier.py::test_el_porton_estructural_nunca_devuelve_null`). Por eso NO
   lleva un `coalesce(…, false)` ni se consume con `IS NOT TRUE`: la envoltura defensiva
   taparía justamente la regresión que ese test tiene que ver. Y si algún día la bivalencia se
   rompiera, el daño está acotado por la propiedad 3 — el predicado se consume en POSITIVO, así
   que un NULL no borra.

   Ojo con qué pieza la sostiene: la rama `= '[]'::jsonb` no está sólo por comodidad de leer.
   Sin ella, el caso MAYORITARIO del producto (la lista vacía) devuelve NULL, porque
   `'[]'::jsonb -> 0` es NULL y todo lo que se le pregunte después también. Medido con
   mutación: sacarla pone en rojo el test de bivalencia de `lista vacía`.
3. **Es fail-closed.** Cualquier forma que no reconozca cae del lado de «no se purga». El
   trivalente de SQL, que en la versión anterior era una mina (la exclusión viajaba NEGADA, y
   un NULL ahí volvía la fila inmortal en silencio), acá falla hacia el lado seguro por
   construcción.

### Las dos direcciones, que parecen contradictorias y no lo son

El reparto por prefijos es fail-SAFE (lo desconocido MUERE) y el portón es fail-CLOSED (lo
desconocido NO muere). La diferencia no es de criterio sino de qué se está jugando:

* un `compliance_status` que nadie inventarió sigue siendo una fila de TRÁFICO — metadata de un
  pedido. Que sobreviva rompe el Art. 5.1.e y nadie se entera; que muera con el plazo de al
  lado cuesta una decisión mal tomada y visible. Se elige que muera;
* un `guardian_events` con forma que nadie reconoce PUEDE SER un eslabón de la cadena. Que
  sobreviva cuesta una fila de metadata viva de más; que muera destruye evidencia que no se
  reconstruye —`verify_chain` lee el hueco como manipulación y el true-up pierde historial—.
  Se elige que sobreviva.

Lo que se paga por la propiedad 3, escrito para que se pueda discutir: **una fila cuyo
`guardian_events` no sea un array, o cuyo primer evento traiga una de las tres marcas, no la
borra nadie.** Hoy eso no le pasa a ninguna fila de tráfico y no es por suerte: los tres
caminos por los que una fila entra a `audit_logs` la dejan siempre como array —
`audit_service.log_transaction` persiste `guardian_events or []` (`audit_service.py:361`);
`/internal/audit` ni nombra la columna en su INSERT, así que la fila nace con el `DEFAULT '[]'`
de la 003; y el plano chat arma la lista con `_eventos_de_la_fila` (`chat.py:577-579`), que
mete el blob del motor DENTRO de un sobre nuestro—. Ese sobre es la pieza que sostiene el
portón: sin él, la posición 0 de una fila de tráfico la elegiría el upstream y bastaría con que
contestara un `event_type` para comprarse la inmortalidad. Con él, la posición 0 es de la casa.

### Lo que el fail-closed deja atrás se CUENTA (dictamen 14-ago, punto c)

Un `guardian_events` nulo —el SQL NULL o el JSON `null`— **no prueba que la fila sea tráfico**,
así que no se borra. Eso es correcto y es el fail-closed, pero deja un residuo, y el «nadie se
entera» es la mitad inaceptable: la corrida de purga reporta `filas_no_clasificadas` para que
ese residuo tenga número. **También en la corrida `dry_run`** — el officer que ensaya la purga
tiene que ver el residuo ANTES de apretar el botón, no después.

Ese contador NO vive en este archivo ni en este PR: lo implementará `purger.py` (T008) sobre
el resultado de la CORRIDA (`ResultadoCorrida`), no sobre el de cada clase (`ResultadoPurga`)
— un residuo que no se pudo clasificar, por definición, no tiene clase a la que colgarse.
Acá se nombra para que la decisión de no borrar y la de contar se lean juntas: son la misma
decisión partida en dos archivos. La doctrina que las une, del depto: entre borrar de más y
borrar de menos, el default va del lado REVERSIBLE.

### La condición aditiva `model <> 'license'` CAYÓ (dictamen del manager, 14-ago)

Hasta el 14-ago al portón se le sumaba `coalesce(model, '') <> 'license'` como defensa en
profundidad. Ya no está, y el motivo es que **no protegía ninguna fila legítima**:

* el emisor de la cadena (`licensing/audit_events.py::_append_chained`, `:252-262`) es
  ESCRITOR ÚNICO de `model='license'`, y escribe siempre UNA sola forma —
  `{event_type, license_id, seats_used, max_seats, reason, ts, prev_hash, seq}`—. El portón por
  forma la excluye por `seq`, por `prev_hash` y por `event_type`, cualquiera de las tres;
* la única otra forma legítima que existe es la pre-US5 (16→20-jul, sin `seq` ni `prev_hash`),
  y el portón también la excluye, por `event_type`. Las DOS formas legítimas están protegidas
  por la forma sola: medido, no inferido;
* o sea que lo único que la aditiva mantenía con vida eran los SPOOFS `model='license'` que ya
  estuvieran en la base de un cliente instalado — y les compraba inmortalidad PERMANENTE. La
  Capa B (`gateway.sanear_modelo_declarado`) impide los NUEVOS, no limpia los VIEJOS. Costo
  puro: cero filas legítimas protegidas, filas de tráfico inmortales de regalo.

La frase del dictamen, que es la regla: **«la exclusión la compra la FORMA, no el literal»**.

Lo que ese acoplamiento exige a cambio está escrito como test y no como comentario:
`test_retention_classifier.py::test_la_forma_que_emite_el_emisor_real_no_es_purgable` toma la
salida REAL de `emit_license_event` (no un fixture) y afirma en SQL que esa fila NO es purgable
por el portón. Si alguien le cambia la forma al emisor —le saca `event_type`, lo renombra—, el
rojo aparece en el acto y no como filas de licencia muriendo en la purga de un cliente.

## La VITRINA excluye por LITERAL, y eso NO es una inconsistencia

`api/audit.py` no usa el portón: excluye la cadena de sus baldes por el LITERAL pelado, o sea
`model = 'license'` — la primitiva es `dice_licencia()` (la migración de esa línea está pendiente
del lado de `api/audit.py`; ver «Estado real» arriba). La regla del dictamen del 14-ago, textual:

    purga = por forma (irreversible → no confía en nadie); vitrina = por literal (reversible →
    y el literal ya es nuestro gracias a la Capa B)

Las dos mitades importan. **Irreversible vs reversible**: un DELETE mal decidido destruye
evidencia que no se reconstruye, así que ahí no se confía en una columna que escribe el
inspeccionado; una fila mal escondida de una pantalla se arregla mirando el listado sin filtro,
que sigue mostrándola. **El literal ya es nuestro**: la Capa B (`gateway.sanear_modelo_declarado`,
consumida por `api/gateway.py` en la puerta y por `api/internal.py:279` del lado del motor)
desaloja `license` al centinela `license__cliente` antes de que toque la columna, así que en una
instalación nueva el cliente no puede escribirlo.

Por qué la vitrina NO usa `~es_licencia()` (literal **y** `seq`), que fue lo que se probó antes:
con esa exclusión una fila de licencia PRE-US5 —`event_type`, sin `seq`— se le muestra al
officer en el balde «bloqueados», mezclada con los intentos de fuga de los usuarios. Medido:
`total=1` donde el `main` da `0`. Es superficie viva de cliente.

NOTA (no bloqueante, y es HERENCIA de `main`, no una regresión de esta ronda): un spoof VIEJO
con `model='license'` que ya esté en la base de una instalación sigue invisible en la vitrina.
Lo que cambió es que ahora ES PURGABLE por forma, así que el problema se extingue solo con las
corridas de purga en vez de quedarse para siempre.

## `prompt_content` no tiene filas en `audit_logs`, y eso es el producto funcionando

`AuditService.log_transaction` promete «absolutely no raw prompt text or PII is recorded»
(`services/audit_service.py:282`) y lo cumple: lo que se persiste son tipos y contadores
(`masked_entities` = `[{"type": "PERSON", "count": 2}]`), no texto. O sea que sobre
`audit_logs` la clase `prompt_content` es el conjunto VACÍO, y su plazo de 90 d muerde en
otro lado: `human_reviews.response_text`, el único contenido real durable de la caja
(`models/compliance.py:84`), que el purgador pone a NULL con este mismo plazo (FR-004, T009).

Ese vacío está DECLARADO (`CLASES_SIN_FILAS_EN_AUDIT_LOGS`), no descubierto por accidente:
un `WHERE` que no matchea nada borra cero filas sin error, y una clase que aparenta correr
sin tocar nada es indistinguible de una purga rota. Si mañana alguien mete contenido en
`audit_logs`, lo que hay que cambiar es esta declaración, y el cambio se ve en el diff.

## Reglas del contrato

1. **Partición total de lo PURGABLE**: toda fila que pase el portón matchea exactamente una
   clase. Sin esto, «purga al día 91» es mentira para las filas que quedaran sin predicado.
   Lo que el portón deja afuera no es un limbo accidental: es la decisión explícita de la
   propiedad 3, y `clase_de()` la nombra devolviendo `None`.
2. **La evidencia de licencias no se purga, y la regla NO depende de ninguna columna que el
   cliente escriba**: se purga lo que es demostrablemente tráfico, y nada más. Ningún predicado
   de clase devuelve una fila que no pasó el portón, y no existe parámetro para incluirla
   (FR-003). Desde el 14-ago la columna `model` no participa del portón en ninguna forma.
3. **Consumidores**: el purgador (T008, `purger.py`, `run_once`) YA consume
   `predicado()`/`clases()` para el DELETE por lotes; la vitrina (`api/audit.py:19`, T005)
   —consumidor de sólo lectura, ya no el único— consume
   `es_bloqueo()`, `es_rechazo()` y `dice_licencia()`.
   Purga y vitrina NO comparten el criterio de exclusión de la cadena, y eso es deliberado:
   ver «La VITRINA excluye por LITERAL» arriba.
4. **Un emisor nuevo con literal no clasificado DEBE romper el test de partición.** Eso es
   una feature: obliga a decidir explícitamente cuánto vive el dato nuevo, en vez de dejarlo
   caer en un limbo inmortal.

## Cómo se relaciona con los dos lectores de la cadena

`chained_entries` (`licensing/audit_events.py:130`) considera eslabón LEGIBLE al primer evento
que sea un dict con `seq` **y** `prev_hash`, con `seq` entero (`_is_chain_link`, `:87`). Este
portón protege un SUPERCONJUNTO de eso: además de esas dos claves mira `event_type`, y además
saca de lo purgable cualquier forma que no sea un array de objetos.

La dirección de esa asimetría es lo que importa. Proteger de MÁS cuesta filas de metadata que
viven de más. Proteger de MENOS borraría una fila que los lectores de la cadena esperan, y eso
es un hueco de `seq` que `verify_chain` reporta como manipulación y un true-up que le falla al
cliente. Entre las dos, la spec elige siempre la primera — y por eso este portón nunca se puede
volver más estricto que `_is_chain_link` sin que alguien lo discuta acá.

## Doctrina heredada (no se borra: se muda)

El POR QUÉ de cada literal estaba escrito en las constantes locales de `api/audit.py`. Cuando
se fueron de la vitrina (T005), el argumento se mudó con ellas — resumirlo o dejarlo huérfano en
un archivo que ya no las define es perderlo. Vive ahora en `dice_licencia()`, `es_bloqueo()` y
`es_rechazo()`, las tres primitivas que reemplazaron a `MODELO_LICENCIA`, `BLOQUEADO_LIKE` y
`RECHAZADO_LIKE`; la vitrina quedó con un puntero a acá, no con una copia resumida.

Ojo con el nombre de la primera: es `dice_licencia()` y no `es_licencia()`, y la distinción es
el punto. `dice_licencia()` es el LITERAL pelado —lo que la vitrina consume— y `es_licencia()`
es literal **más** `seq`, o sea «eslabón VERIFICABLE». Dos preguntas, dos nombres; el detalle de
quién consume cuál está en sus docstrings.

## Nota para T010/T017: escribir en `config_audit` es escribir un literal

La clase de una fila la decide su `compliance_status`, no la intención de quien la escribe.
La fila resumen de cada corrida de purga (FR-005) y el evento de cambio de tier (SC-006)
tienen que vivir 730 d, así que su `compliance_status` DEBE empezar con `config_change` —
igual que el único emisor de configuración que ya existe
(`api/guardians.py:334`, `config_change_nlp_fail_mode`). Con cualquier otro literal caen en
`usage_metadata` y mueren a los 365 d, silenciosamente y con la data-model diciendo otra cosa.
"""
from typing import Dict, List, Optional

from sqlalchemy import and_, cast, false, func, literal
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.elements import ColumnElement

from ...models.audit import AuditLog

# ── Las 4 clases (llaves de `retention_policies.log_type`, seed 004:100-109) ──────────
CLASE_PROMPT_CONTENT = "prompt_content"
CLASE_USAGE_METADATA = "usage_metadata"
CLASE_SECURITY_EVENTS = "security_events"
CLASE_CONFIG_AUDIT = "config_audit"

# Orden ESTABLE = el del seed. No es cosmético: es el orden en que el purgador recorre las
# clases, y usar el mismo que la migración hace que «la tercera clase» signifique lo mismo
# leyendo el código o leyendo el seed.
_CLASES = (
    CLASE_PROMPT_CONTENT,
    CLASE_USAGE_METADATA,
    CLASE_SECURITY_EVENTS,
    CLASE_CONFIG_AUDIT,
)

# Clases cuyo predicado sobre `audit_logs` es vacío A PROPÓSITO (ver el docstring del módulo).
# Se declara en vez de dejarse implícito para que el purgador y los tests puedan afirmar la
# intención: «esta clase no borra filas de auditoría» es un hecho del diseño, no el síntoma
# de un predicado mal escrito.
CLASES_SIN_FILAS_EN_AUDIT_LOGS = frozenset({CLASE_PROMPT_CONTENT})

# ── Los literales del mapeo ───────────────────────────────────────────────────────────
#
# `model='license'`: la marca que el emisor de la hash-chain de licencias (021) le pone a sus
# filas. Son transiciones del ciclo de vida del deployment, NO tráfico, y varias escriben
# `compliance_status='blocked_by_policy'` (`licensing/audit_events.py:271`, el default de
# `_COMPLIANCE_BY_EVENT`), o sea que caen de lleno en el prefijo de bloqueo. Ese es el motivo por
# el que la vitrina las saca de sus baldes: si mirara sólo el estado, media cadena aparecería
# entre los intentos bloqueados de los usuarios.
#
# Dónde se usa este literal, y dónde NO:
#
# * SÍ en `dice_licencia()` — el criterio de VISIBILIDAD de la vitrina, y en `es_licencia()`,
#   que le suma el `seq`;
# * NO en el portón de la purga. Cayó el 14-ago por dictamen del manager: la exclusión de la
#   purga la compra la FORMA de `guardian_events`, no este literal (el argumento medido está en
#   el docstring del módulo, sección «La condición aditiva … CAYÓ»).
MODELO_LICENCIA = "license"

# Las tres claves con las que se reconoce que el primer `guardian_event` tiene FORMA de eslabón
# de la cadena de licencias. **Son la ÚNICA defensa de la evidencia de licencias en la purga**:
# desde que cayó la condición aditiva sobre `model` (14-ago) no hay una segunda red debajo.
#
# Van a mano y NO importadas de `licensing` a propósito, por el mismo motivo que los
# `compliance_status` del inventario: el clasificador corre en un job batch y no se ata a media
# app para leer una constante. El precio de escribirlas dos veces lo pagan DOS tests, y ahora
# uno de los dos acopla este archivo con el emisor real:
#
# * `test_la_forma_que_emite_el_emisor_real_no_es_purgable` llama a `emit_license_event` (el
#   emisor de verdad, no un fixture) y exige en SQL que la fila que deja NO sea purgable;
# * `test_la_licencia_pre_us5_no_la_borra_nadie` siembra a mano la forma histórica —que el
#   emisor de hoy ya no puede producir— y exige lo mismo.
#
# Por qué estas tres y no sólo `seq`:
#
# * `seq` y `prev_hash` las escribe `_append_chained` (`audit_events.py:253-262`) desde la US5
#   (9cd7b99, 20-jul) y son las que releen los dos lectores de la cadena;
# * `event_type` es la que existe DESDE LA US1 (0a8cda1, 16-jul) y nunca se fue. Es la que
#   protege a las filas de licencia legítimas escritas entre el 16 y el 20 de julio, que no
#   tienen `seq` y que un ancla anterior mandaba a una clase mortal — o sea que el purgador
#   habría borrado evidencia de licencia real. También es la que hace que este predicado NO
#   dependa del vocabulario: un evento de cadena nuevo trae `event_type` sin que nadie lo
#   inventaríe acá.
CLAVE_SEQ_CADENA = "seq"
CLAVE_PREV_HASH_CADENA = "prev_hash"
CLAVE_EVENT_TYPE_CADENA = "event_type"

MARCAS_DE_LA_CADENA = (CLAVE_SEQ_CADENA, CLAVE_PREV_HASH_CADENA, CLAVE_EVENT_TYPE_CADENA)

# `blocked…` es el filtro canónico de «el firewall impidió este pedido por política»
# (convención D1; misma que usan la vitrina, el dashboard y los tests de la 031). Es lo que la
# clase `security_events` quiere decir con «eventos de guardianes»: hubo un veredicto y el
# pedido no pasó. Emisores vivos en los tres planos — ver `EMISORES_VIGENTES`.
PREFIJO_BLOQUEADO = "blocked"

# Los rechazos NUESTROS —por capacidad (`rejected_saturated`, `services/engine_gate.py`: el
# tope de admisión devolvió 503 porque no había turno hacia el motor) y por presupuesto
# agotado (`rejected_budget`, `services/budget_service.py`: 402 del gate de presupuesto,
# issue #157)— NO empiezan con `blocked` a propósito: en ninguno de los dos el firewall
# impidió nada. El de capacidad ni siquiera es una decisión sobre el pedido —no había turno
# hacia el motor—, y el de presupuesto es un tope ADMINISTRATIVO nuestro, no una infracción
# del usuario: el pedido era perfectamente lícito y aun así no se sirvió. Contarlos entre los
# bloqueos inflaría «cuántos intentos bloqueó el firewall» con pedidos que nadie bloqueó.
# Ref: gate adversarial del PR #135 (H4), decisión JF 12-ago-2026; issue #157.
#
# Para la VITRINA eso los deja fuera de los dos baldes del filtro binario (ni bloqueados ni
# permitidos) — de ahí que esta primitiva exista aunque no delimite ninguna clase.
# Para la RETENCIÓN, en cambio, sí tienen casa: la fila es metadata de uso (modelo, ts, cero
# tokens, cero coste) y muere con `usage_metadata`. Que no sea un bloqueo no la vuelve
# especial para el reloj — sólo para el conteo.
PREFIJO_RECHAZADO = "rejected"

# `config_change…` es la convención de los cambios de configuración auditados. Hoy la estrena
# un solo emisor (`api/guardians.py:334`, `config_change_nlp_fail_mode`), pero es la que
# gobierna la clase de 730 d — la más larga del seed, porque un auditor pregunta «¿quién
# aflojó esto y cuándo?» dos años después.
PREFIJO_CONFIG = "config_change"

# ── Inventario de emisores vivos (es lo que T004 muerde para la regla 4) ──────────────
#
# `compliance_status` → clase esperada, con dónde se emite. Esto NO decide la clasificación
# (la deciden los prefijos de arriba, que son totales): es el inventario contra el que el test
# de partición verifica que cada literal que el producto emite HOY cae donde alguien decidió
# que caiga. Un emisor nuevo que no figure acá tiene que poner el test en rojo — así la
# pregunta «¿cuánto vive este dato?» se contesta cuando se escribe el emisor y no dos años
# después, cuando un auditor la haga.
#
# Los literales van a mano y no importados de sus módulos a propósito: importar
# `engine_gate`/`budget_service`/`sentinel_guardian_policy` desde acá ataría el clasificador —que
# corre en un job batch— a media app, y un rename igual clasificaría bien (el prefijo no
# cambia). Lo que se busca acá es el INVENTARIO, no el acoplamiento.
#
# Ojo con `passed`, `flagged_high_risk` y `blocked_by_policy`: los emite también la cadena de
# licencias. La clase que figura acá es la de una fila de TRÁFICO con ese estado; las filas de
# la cadena no llegan al reparto porque no pasan el portón.
EMISORES_VIGENTES: Dict[str, str] = {
    # Tráfico que el firewall resolvió sin impedirlo.
    "passed": CLASE_USAGE_METADATA,             # compliance_service.py:38,60 · motor · internal.py (default)
    "flagged_high_risk": CLASE_USAGE_METADATA,  # compliance_service.py:55 (alto riesgo AI-Act, no bloqueo)
    "allowed": CLASE_USAGE_METADATA,            # legado: nadie lo emite hoy, analytics.py:212 lo sigue contando
    "upstream_error": CLASE_USAGE_METADATA,     # gateway.py — pasó las capas y falló el destino
    # gateway.STATUS_PASSTHROUGH_CANCELADO (#158): el cliente cortó el stream del passthrough
    # antes de que drenara entero (o antes de que arrancara). Pasó las capas —el firewall no
    # impidió nada— y no es un rechazo NUESTRO: es metadata de un pedido que no se llegó a servir
    # completo, así que vive con `usage_metadata` (365 d), igual que `upstream_error`. No es
    # `blocked` (nadie lo bloqueó) ni `rejected` (no fue un tope nuestro), así que el reparto por
    # prefijo ya lo mandaba acá; esta línea vuelve esa clasificación una decisión inventariada.
    "passthrough_cancelled": CLASE_USAGE_METADATA,
    "degraded_nlp_regex": CLASE_USAGE_METADATA,  # policy.STATUS_NLP_DEGRADED — ver HALLAZGO abajo
    # Rechazos NUESTROS: el pedido no se sirvió y el motivo no fue del usuario.
    "rejected_saturated": CLASE_USAGE_METADATA,  # engine_gate.STATUS_SATURATED (#135)
    "rejected_budget": CLASE_USAGE_METADATA,     # budget_service.STATUS_BUDGET_EXHAUSTED (#157)
    # Bloqueos: una capa dictaminó y el pedido no pasó.
    "blocked_prohibited": CLASE_SECURITY_EVENTS,       # chat.py · compliance_service.py:45 · motor
    "blocked_by_policy": CLASE_SECURITY_EVENTS,        # chat.py (guardián de postura)
    "blocked_residency": CLASE_SECURITY_EVENTS,        # chat.py (residencia de datos)
    "blocked_secret": CLASE_SECURITY_EVENTS,           # gateway.py · sentinel_guardrail.py:500
    # Sólo del plano MOTOR: entidad cuyo tipo tiene acción BLOCK en la política del tenant
    # (`sentinel_guardrail.py:594` → `_auditar_bloqueo(compliance_status=…)` → `/internal/audit-logs`).
    # Faltaba en este inventario y lo cazó el censo del fuente de T004 — que es exactamente para
    # lo que existen los dos: el literal ya clasificaba bien por prefijo, pero nadie había
    # decidido su plazo por escrito.
    "blocked_entity_type": CLASE_SECURITY_EVENTS,
    "blocked_nlp_unavailable": CLASE_SECURITY_EVENTS,  # policy.STATUS_NLP_BLOCKED (D10 fail-closed)
    # Configuración.
    "config_change_nlp_fail_mode": CLASE_CONFIG_AUDIT,  # guardians.py:334
    # H4 del gate de #137: MISMA clase que `config_change_nlp_fail_mode` — es la misma
    # convención `config_change…` (línea 412), el mismo emisor (`_escribir_fila_compliance`,
    # guardians.py) y la misma pregunta de auditor dos años después («¿quién cambió la
    # región de compliance de este tenant, y cuándo?»).
    "config_change_region": CLASE_CONFIG_AUDIT,  # guardians.py (_auditar_cambio_postura_tenant)
}

# HALLAZGO abierto, anotado acá para que no se pierda entre el código: `degraded_nlp_regex` es
# el gemelo fail-OPEN de `blocked_nlp_unavailable` (constitución D10) — el analizador NLP no
# contestó y se siguió con regex, o sea protección degradada. Por semántica del seed eso suena
# a «alerta de seguridad» (365 d de `security_events`), pero por literal cae en
# `usage_metadata`. Hoy da igual —las dos clases traen 365 d por defecto— y el día que el DPO
# acorte `usage_metadata` la evidencia de la degradación moriría antes que la de su gemelo
# bloqueado. NO se fuerza acá una excepción por literal: la spec no la contempla y una regla
# especial escondida en el clasificador es peor que una asimetría documentada. Decisión de
# producto pendiente.

# ── Primitivas (la doctrina mudada de `api/audit.py`; T005 las consume) ───────────────


def _estado() -> ColumnElement:
    """`compliance_status` como texto comparable, con NULL tratado como cadena vacía.

    La columna es NOT NULL en el esquema, así que hoy el `coalesce` no cambia ni una fila.
    Está igual por dónde falla si eso cambiara: `NOT (NULL LIKE 'blocked%')` es NULL, no TRUE,
    y una fila con estado nulo no matchearía NINGÚN predicado — o sea, pasaría el portón y
    después se volvería inmortal en el reparto, que es justo lo que la regla 1 prohíbe. Con el
    `coalesce`, cae en `usage_metadata` y muere. El gemelo Python (`clase_de`) hace lo mismo
    con `or ""`, y ahí el caso no es hipotético: un `AuditLog` construido en memoria y todavía
    sin flush llega con `compliance_status=None`.
    """
    return func.coalesce(AuditLog.compliance_status, "")


def _modelo() -> ColumnElement:
    """`model` como texto comparable, con NULL tratado como cadena vacía.

    Usos vivos, auditados el 14-ago: `dice_licencia()` y `es_licencia()`. Las DOS son
    primitivas de la VITRINA — el portón de la purga ya no mira esta columna—, y las dos se
    consumen NEGADAS. Ahí es donde el `coalesce` se gana el lugar.

    Medido contra el Postgres del compose (no inferido):

        NULL = 'license'                     → NULL
        NOT (NULL = 'license')                → NULL          ← la fila desaparece del listado
        coalesce(NULL,'') = 'license'         → False
        NOT (coalesce(NULL,'') = 'license')   → True           ← la fila se sigue viendo

    O sea: sin el `coalesce`, una fila con `model` nulo se le esconde al officer en silencio,
    que es el daño nº2 del gate adversarial servido por la puerta de la defensa. Con él, «no
    dice nada» significa «no es de licencia» y no «no se sabe».

    En `es_licencia()` el mismo `coalesce` sólo muerde en un rincón, y conviene saberlo para no
    perseguir un mutante equivalente: `es_licencia()` es un AND contra `_trae_seq_de_cadena()`,
    y en SQL `NULL AND FALSE` es FALSE (medido), así que una fila sin `seq` y con `model` nulo
    sale bien igual. El rincón que sí muerde es la fila con `model` NULL cuyo primer evento
    trae `seq`: ahí `NULL AND TRUE` es NULL y la negación vuelve a esconderla.
    """
    return func.coalesce(AuditLog.model, "")


def es_trafico_demostrable() -> ColumnElement:
    """El PORTÓN: TRUE sólo si la forma de `guardian_events` prueba que la fila es tráfico.

    Es lo ÚNICO que habilita un `DELETE` — desde el dictamen del 14-ago no hay condición
    aditiva sobre `model` ni sobre ninguna otra columna que el cliente escriba. El argumento
    completo —el agujero histórico de las filas de licencia pre-US5, por qué la pregunta se
    invirtió y por qué la aditiva cayó— está en el docstring del módulo, sección «El portón».

    Las cuatro piezas del SQL, y qué pasa si alguien saca cualquiera:

    * `IS NOT NULL` + `jsonb_typeof(…) = 'array'`: sin ellas, una columna nula o un jsonb que
      no es lista se colarían como «tráfico» por la puerta del NULL. Y además son lo que hace
      que el resto no pueda reventar: `jsonb_array_length` sobre un no-array **levanta error**,
      y Postgres NO garantiza el orden de evaluación de un `AND`, así que la comprobación de
      lista vacía se escribe comparando contra `'[]'::jsonb` —que es total— y no contando.
    * `= '[]'::jsonb`: es el caso mayoritario del producto (el tráfico que no disparó ningún
      guardián) y hay que nombrarlo aparte porque en una lista vacía no hay primer evento que
      mirar: `'[]'::jsonb -> 0` es NULL y todo lo de la rama siguiente daría NULL.
    * `jsonb_typeof(guardian_events->0) = 'object'`: es lo que impide que un primer evento que
      NO es un objeto conteste «no tengo ninguna de las tres marcas» y pase por tráfico.
      `jsonb_exists` es la forma función del operador `?`, y `?` sobre un jsonb que no es objeto
      no falla: sobre un número devuelve false y sobre un string compara el string ENTERO contra
      la clave. Así que sin el chequeo de tipo, `[7]` y `["consequence"]` se volverían purgables
      —las tres marcas contestan «no»— mientras que `["seq"]` seguiría protegido de casualidad,
      porque ahí el string entero SÍ coincide con la clave. Apoyarse en esa casualidad es no
      tener la guarda. El gemelo Python pide `isinstance(primero, dict)` por el mismo motivo y
      con un borde propio: sin ella, `"seq" in 7` es `TypeError` y el que se lo come es el
      purgador.
    * las tres marcas negadas: la lista está en `MARCAS_DE_LA_CADENA`, con el porqué de cada
      una. Se miran en el `[0]` y no barriendo la lista porque el primer evento es el único que
      releen los lectores de la cadena (`chained_entries`, `audit_events.py:130`); barrer
      protegería filas que la cadena ni mira, y eso es inmortalidad regalada.

    **Nunca devuelve NULL** — medido contra Postgres forma por forma, y con test propio que lo
    afirma para cada una. Por eso no lleva `coalesce(…, false)`: la envoltura no cambiaría ninguna
    respuesta de hoy y taparía la regresión que ese test existe para ver. Y aunque la
    bivalencia se rompiera, este predicado se consume en POSITIVO: un NULL no habilita el
    borrado, que es el lado seguro.
    """
    eventos = AuditLog.guardian_events
    primero = eventos[0]
    sin_marcas_de_cadena = and_(
        *(~func.jsonb_exists(primero, marca) for marca in MARCAS_DE_LA_CADENA)
    )
    return (
        eventos.is_not(None)
        & (func.jsonb_typeof(eventos) == "array")
        & (
            (eventos == cast(literal("[]"), JSONB))
            | ((func.jsonb_typeof(primero) == "object") & sin_marcas_de_cadena)
        )
    )


def es_trafico_demostrable_en_memoria(fila: AuditLog) -> bool:
    """Gemelo Python de `es_trafico_demostrable()`, para `clase_de()`.

    Tiene que decir EXACTAMENTE lo mismo en las mismas filas: el purgador BORRA con el
    predicado SQL y EXPLICA su corrida con el camino Python, así que una divergencia es un
    `purge_log` que le miente al auditor sobre qué se borró. Hay test que compara los dos
    caminos fila por fila sobre el dataset entero.

    La guarda de forma es completa y en ese orden —lista → no vacía → `[0]` es dict → mirar las
    tres claves— porque cada paso es un NULL del `->` de Postgres escrito a mano, y sacar
    cualquiera rompe algo distinto: sin el primero, un `guardian_events` que no es lista revienta
    con `TypeError`; sin el segundo, un `[]` revienta con `IndexError`; sin el tercero, `in`
    sobre un primer evento que no es dict busca SUBCADENA (`"seq" in "consequence"` es `True`) o
    directamente revienta (`"seq" in 7` es `TypeError`). Y el que se come la excepción no es un
    test: es el purgador armando el rastro de su corrida.

    Devuelve `bool` de verdad y nunca `None`: es el gemelo de un predicado bivaluado, y un
    `None` acá sería falsy por accidente en vez de por decisión.
    """
    eventos = fila.guardian_events
    if not isinstance(eventos, list):
        return False
    if not eventos:
        return True
    primero = eventos[0]
    if not isinstance(primero, dict):
        return False
    return not any(marca in primero for marca in MARCAS_DE_LA_CADENA)


def _es_purgable() -> ColumnElement:
    """Lo que habilita un `DELETE`: el portón estructural, y NADA más.

    Desde el dictamen del manager del 14-ago esto es exactamente `es_trafico_demostrable()`.
    La función se mantiene como el punto de acoplamiento —`predicado()` la llama, y el día que
    haya una segunda condición se agrega acá y viaja sola a las cuatro clases— pero hoy no suma
    ninguna: **la exclusión la compra la FORMA, no el literal**.

    Qué se sacó y por qué, en corto (el argumento medido está en el docstring del módulo):
    `coalesce(model,'') <> 'license'` no protegía ni una fila legítima. El emisor de la cadena
    es escritor único de `model='license'` y escribe una sola forma, que el portón ya excluye
    por `seq`/`prev_hash`/`event_type`; y la otra forma legítima, la pre-US5, la excluye por
    `event_type`. Lo único que la aditiva mantenía vivo eran los spoofs ya escritos en la base
    de un cliente instalado, y les daba inmortalidad PERMANENTE — la Capa B tapa lo nuevo, no
    lo viejo.

    Viaja en TODOS los predicados de clase, no en uno: es la única forma de que «no existe
    camino de configuración que purgue la evidencia de licencias» sea cierto por construcción y
    no por disciplina de quien escriba el próximo predicado.
    """
    return es_trafico_demostrable()


def _es_purgable_en_memoria(fila: AuditLog) -> bool:
    """Gemelo Python de `_es_purgable()`. Misma condición, y hoy es una sola.

    Existe por simetría con el gemelo SQL y para que `clase_de()` y `predicado()` se lean como
    la misma regla dicha dos veces. Si alguna vez `_es_purgable()` vuelve a tener más de una
    condición, ésta es la que tiene que crecer con ella o los dos caminos empiezan a contar
    distinto — que es la mitad del contrato de este módulo.
    """
    return es_trafico_demostrable_en_memoria(fila)


def _trae_seq_de_cadena() -> ColumnElement:
    """TRUE sólo si el primer `guardian_event` es un OBJETO con clave `seq`.

    Mitad de `es_licencia()` («eslabón VERIFICABLE»), que no es el portón de la purga ni el
    criterio de la vitrina — ver su docstring, que lista sus llamadores. Se apoya en que el
    `->` de Postgres NO revienta cuando no hay un primer evento: devuelve SQL NULL con la
    columna en NULL, con `[]` y con un jsonb que no es lista. El `coalesce(…, false)` es
    load-bearing para cualquiera que consuma `es_licencia()` NEGADA: un NULL ahí vuelve
    `NOT (… AND NULL)` = NULL y la fila desaparece del listado en silencio.

    El `jsonb_typeof(…) = 'object'` tampoco es decoración: `jsonb_exists` es la forma función
    del operador `?`, y `?` sobre un jsonb STRING compara el string ENTERO contra la clave, así
    que sin el chequeo `["seq"]` pasaría por eslabón sin ser nada.
    """
    primero = AuditLog.guardian_events[0]
    return func.coalesce(
        (func.jsonb_typeof(primero) == "object")
        & func.jsonb_exists(primero, CLAVE_SEQ_CADENA),
        false(),
    )


def _trae_seq_de_cadena_en_memoria(fila: AuditLog) -> bool:
    """Gemelo Python de `_trae_seq_de_cadena()`, con las mismas guardas de forma."""
    eventos = fila.guardian_events
    if not isinstance(eventos, list) or not eventos:
        return False
    return isinstance(eventos[0], dict) and CLAVE_SEQ_CADENA in eventos[0]


def dice_licencia() -> ColumnElement:
    """El LITERAL pelado: `model = 'license'`. Criterio de **VISIBILIDAD**, no de borrado.

    Es lo que consume la vitrina (`api/audit.py::_build_query`) para sacar la cadena de los
    baldes «bloqueados»/«permitidos». Vive acá y no como constante suelta en la pantalla por lo
    mismo que las otras primitivas: dos copias del criterio es que un día la pantalla informe
    «3 bloqueos» y la purga cuente esas mismas filas de otra manera.

    **El criterio de BORRADO es OTRO y es el portón por forma** (`es_trafico_demostrable()`).
    Que no coincidan es el dictamen del manager del 14-ago, no un descuido, y la razón cabe en
    una línea:

        purga = por forma (irreversible → no confía en nadie); vitrina = por literal
        (reversible → y el literal ya es nuestro gracias a la Capa B)

    Las dos mitades del argumento:

    * **reversible**. Una fila mal escondida de un balde se sigue viendo en el listado sin
      filtro; un `DELETE` mal decidido no se deshace. Por eso la purga no acepta un criterio que
      dependa de una columna que escribe el inspeccionado (`gateway.py:1455`) y la pantalla sí;
    * **el literal ya es nuestro**. `gateway.sanear_modelo_declarado` (Capa B), consumida por
      `api/gateway.py` y por `api/internal.py:279`, desaloja `license` al centinela
      `license__cliente` antes de que toque la columna. Si alguien saca ese saneo, esta
      primitiva deja de ser una exclusión y pasa a ser un escondite que se pide cualquiera con
      una API key — las dos se leen juntas o no se leen.

    Y por qué el literal y no `es_licencia()` (literal **más** `seq`), que fue lo que se probó
    antes: con `~es_licencia()` una fila de licencia LEGÍTIMA pre-US5 —`event_type`, sin `seq`—
    se le muestra al officer entre los bloqueos, mezclada con intentos de fuga. Medido: `total=1`
    donde `main` da `0`. Es superficie viva de cliente y por eso vuelve al literal, como en
    `main`.

    NOTA heredada de `main`, anotada para que no se descubra dos veces: un spoof VIEJO con
    `model='license'` ya escrito en la base de una instalación sigue invisible en la vitrina.
    No es una regresión de esta ronda; y ahora ES purgable por forma, así que se extingue con
    las corridas de purga.

    No tiene gemelo en Python porque no tiene consumidor en Python: la vitrina es SQL. Si
    alguna vez lo necesita, es `(fila.model or "") == MODELO_LICENCIA` y va con su test.
    """
    return _modelo() == MODELO_LICENCIA


def es_licencia() -> ColumnElement:
    """«Eslabón VERIFICABLE de la cadena»: `model='license'` **y** `seq` en el primer evento.

    Es la pregunta más fuerte de las tres que este módulo sabe hacer sobre la cadena, y la que
    contesta «esta fila la escribió el emisor de la 021 de la US5 en adelante, y los dos
    lectores de la cadena la pueden leer». Ninguna de las otras dos la contesta:

    | primitiva                   | pregunta                            | quién decide con ella |
    |-----------------------------|-------------------------------------|-----------------------|
    | `es_trafico_demostrable()`  | ¿es demostrablemente TRÁFICO?        | la PURGA (borra)      |
    | `dice_licencia()`           | ¿DICE `license`?                     | la VITRINA (muestra)  |
    | `es_licencia()`             | ¿es un eslabón VERIFICABLE?          | ver llamadores abajo  |

    **Llamadores, MEDIDOS el 14-ago** con
    `grep -rn 'es_licencia' backend/src/ litellm/ --include='*.py'`:

    * **ninguno en producción**. El `grep` devuelve la `def` de acá abajo y prosa de
      comentarios/docstrings, y nada más. La vitrina —que era el único consumidor— ya migró a
      `~dice_licencia()` en este mismo PR (`api/audit.py:271`, import en `:19`);
    * los tests que miden la primitiva:
      `tests/unit/test_retention_classifier.py`,
      `tests/integration/test_audit_paridad_clasificador.py` (mitades 1 y 2 por separado).

    O sea que, migrada la vitrina, **esta primitiva quedó SIN consumidor en producción**. Se
    mantiene por dictamen del manager: es la única que sabe decir «eslabón verificable», y el
    consumidor natural es el lector ÚNICO de la cadena, que hoy la relee con un
    `WHERE model='license'` pelado (`chained_entries`, `licensing/audit_events.py:150`;
    lo consumen `verify_chain` —`:170`— y `trueup_export.build_payload` —`:65`—). Que no la use
    todavía es un hecho, no una recomendación
    — si en la próxima ronda nadie la reclama, la conversación que corresponde es si se borra,
    no si se le inventa un uso.

    Ojo con lo que esta primitiva NO es: no es la exclusión de la purga y no lo es desde la
    ronda anterior. Preguntada sobre una fila de licencia pre-US5 contesta `False` —no trae
    `seq`— y eso es correcto para «¿es verificable?» y equivocado para «¿se puede borrar?». Por
    eso la purga no la usa.
    """
    return (_modelo() == MODELO_LICENCIA) & _trae_seq_de_cadena()


def es_bloqueo() -> ColumnElement:
    """«El firewall impidió este pedido por política» — el filtro canónico `blocked…`.

    OJO: por sí sola incluye eslabones de licencia (varios escriben `blocked_by_policy`).
    Quien la use para hablar de TRÁFICO tiene que combinarla con una exclusión de la cadena, y
    cuál depende de para qué: `predicado(CLASE_SECURITY_EVENTS)` la combina con el portón por
    forma porque va a BORRAR; la vitrina la combina con `~dice_licencia()` porque va a MOSTRAR.
    El porqué de que sean distintas está en el docstring de `dice_licencia()`.
    """
    return _estado().startswith(PREFIJO_BLOQUEADO, autoescape=True)


def es_rechazo() -> ColumnElement:
    """Rechazos NUESTROS (`rejected…`): ni bloqueados ni servidos.

    No delimita ninguna clase de retención —esas filas mueren con `usage_metadata`— pero es
    media definición del filtro binario de la vitrina, que las deja fuera de los dos baldes
    (el motivo largo está arriba, en `PREFIJO_RECHAZADO`). Vive acá para que la vitrina no
    vuelva a tener criterio propio sobre qué fila es qué.
    """
    return _estado().startswith(PREFIJO_RECHAZADO, autoescape=True)


def _es_cambio_config() -> ColumnElement:
    """Cambios de configuración auditados (`config_change…`).

    `startswith(..., autoescape=True)` y no `like('config_change%')` porque en LIKE el `_` es
    comodín de un carácter: el literal crudo también matchearía `configXchange…`. Con
    autoescape el SQL sale escapado y dice exactamente lo mismo que el `str.startswith` del
    gemelo Python — que los dos no se separen es la mitad del contrato de este módulo.
    """
    return _estado().startswith(PREFIJO_CONFIG, autoescape=True)


def clases() -> List[str]:
    """Las 4 clases de retención del seed 004, en orden ESTABLE.

    Estable importa por dos motivos: el purgador recorre siempre en el mismo orden (una
    corrida interrumpida se retoma sin que el orden cambie qué quedó pendiente) y los tests
    comparan listas, no conjuntos — un reordenamiento accidental se ve.

    Lo que el portón deja afuera NO está en esta lista: no es una clase de retención, es la
    decisión de no purgar (regla 2).
    """
    # Lista nueva en cada llamada: la tupla de módulo es la verdad y nadie la muta por
    # accidente desde el purgador.
    return list(_CLASES)


def predicado(clase: str) -> ColumnElement:
    """Predicado SQLAlchemy sobre `AuditLog` que selecciona las filas de `clase`.

    Es lo que `purger.run_once` mete en el `WHERE` de su DELETE por lotes.
    Ojo con no leer de más: la VITRINA no llama a `predicado()`. Consume las primitivas sueltas
    (`es_bloqueo`, `es_rechazo`, `dice_licencia`), que es lo que FR-002 pide —una sola
    definición de «qué fila es qué», sin constantes duplicadas en la pantalla— y no «el mismo
    predicado para borrar y para mostrar»: el criterio de exclusión de la cadena es distinto en
    cada lado a propósito, y el porqué está en `dice_licencia()`.

    Ningún predicado devuelve una fila que no haya pasado el portón (regla 2): no se purga lo
    que no es demostrablemente tráfico, y no hay parámetro para pedir lo contrario.

    Una `clase` fuera de `clases()` es un error del programa, no un caso de negocio: levanta
    `ValueError` en vez de devolver un predicado vacío. Un `WHERE` que no matchea nada borra
    cero filas SIN error, y la purga aparentaría estar corriendo.
    """
    if clase not in _CLASES:
        raise ValueError(
            f"clase de retención desconocida: {clase!r}. Las del seed 004 son {list(_CLASES)}"
        )

    if clase in CLASES_SIN_FILAS_EN_AUDIT_LOGS:
        # Vacío DECLARADO, no accidental (ver el docstring del módulo): `prompt_content` no
        # tiene filas en `audit_logs` porque la tabla es metadata-only por diseño. Su plazo
        # muerde sobre `human_reviews.response_text` y eso lo hace el purgador (T009), no un
        # predicado sobre esta tabla.
        return false()

    # El portón viaja en TODOS los predicados de clase, no en uno solo: es lo que hace que la
    # regla 2 sea cierta por construcción y no por disciplina del próximo que agregue una clase.
    purgable = _es_purgable()

    if clase == CLASE_CONFIG_AUDIT:
        return purgable & _es_cambio_config()
    if clase == CLASE_SECURITY_EVENTS:
        return purgable & es_bloqueo()
    # `usage_metadata` es el complemento EXACTO de las otras dos dentro de lo purgable (mismo
    # orden de evaluación que `clase_de`): así las tres juntas cubren todo lo que pasó el portón
    # sin solapamiento — la partición de la regla 1 es cierta por construcción, no por enumerar
    # bien los literales.
    return purgable & ~_es_cambio_config() & ~es_bloqueo()


def clase_de(fila: AuditLog) -> Optional[str]:
    """Clase de UNA fila ya cargada, o `None` si la fila no es purgable.

    `None` significa exactamente una cosa: **la fila no pasó el portón**, o sea que no se puede
    demostrar que sea tráfico. Cubre a los eslabones de la cadena de licencias (con `seq`), a
    las filas de licencia legítimas anteriores a la 021 US5 (con `event_type` y sin `seq`) y a
    las formas que el portón no reconoce — `guardian_events` nulo (SQL NULL o JSON `null`), un
    jsonb que no es lista, un primer evento que no es un objeto. Es la decisión fail-closed del
    módulo: ante la duda no se borra evidencia.

    Lo que `None` ya NO cubre desde el 14-ago: «cualquier fila que diga `model='license'`». Una
    fila con ese literal y un `guardian_events` de tráfico (`[]`, por ejemplo) es un SPOOF —el
    emisor de la cadena nunca escribió esa forma— y desde el dictamen tiene clase, o sea que
    muere con su plazo. Ese es el cambio de comportamiento de esta ronda.

    Cualquier OTRA fila tiene clase — esa es la regla 1, y el test de partición de T004 la
    verifica sobre un dataset con todos los emisores vivos: `blocked%`, `rejected%`
    (saturación y presupuesto 402), `config_change_*`, `license` y tráfico normal.

    Es el gemelo en Python de `predicado()`: mismo mapeo, otra forma de preguntarlo (uno
    viaja al motor SQL, el otro clasifica objetos en memoria para el rastro de la corrida). Si
    los dos se separan, el purgador BORRA según uno y le EXPLICA al auditor con el otro — el
    `purge_log` pasa a mentir sobre qué se borró. Por eso salen de la MISMA tabla de literales
    de este módulo, no de dos copias que alguien tiene que acordarse de sincronizar, y por eso
    hay un test que los compara fila por fila sobre el dataset entero.
    """
    # Portón primero y por su propia columna: un eslabón de la cadena con `blocked_by_policy`
    # tiene que salir por acá ANTES de que nadie le mire el estado.
    if not _es_purgable_en_memoria(fila):
        return None

    # `or ""` por el mismo motivo que el `coalesce` de `_estado()`, con un caso real de más:
    # un `AuditLog` recién construido en un test todavía no tiene estado y clasificarlo no
    # debería reventar con AttributeError.
    estado = fila.compliance_status or ""

    if estado.startswith(PREFIJO_CONFIG):
        return CLASE_CONFIG_AUDIT
    if estado.startswith(PREFIJO_BLOQUEADO):
        return CLASE_SECURITY_EVENTS
    # Resto = metadata de uso, incluidos los `rejected…` (el pedido no se sirvió, pero lo que
    # queda escrito de él es su metadata) y cualquier literal que todavía nadie inventarió.
    # Nunca `prompt_content`: `audit_logs` no guarda contenido.
    return CLASE_USAGE_METADATA
