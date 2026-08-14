"""El ataque murió: tráfico real disfrazado de cadena de licencias (spec 018, FR-002/FR-003).

Este archivo es la prueba de que la CRÍTICA del gate adversarial del 13-ago está cerrada, y lo
afirma donde el cliente lo sufre: sobre la tabla real, con la vitrina real, el `verify_chain`
real y el export de true-up real, todos leyendo la MISMA tabla al mismo tiempo.

## El ataque, en una línea de body

`audit_logs.model` la escribe el INSPECCIONADO — en el passthrough sale del cuerpo del pedido
(`api/gateway.py:1455`) y se persiste antes de que conteste el motor. Y `license` no es un
modelo: es la marca de los eslabones de la hash-chain de licencias (021,
`licensing/audit_events.py:190`). Mientras la exclusión de retención se apoyó sólo en esa
columna, `{"model": "license"}` compraba tres cosas de un saque, y las tres sobre una fila que
podía ser un BLOQUEO REAL:

1. **inmortal** — todos los predicados de clase niegan la exclusión, así que ningún `WHERE` la
   levanta y ninguna purga la borra. Datos personales sin fecha de muerte es el Art. 5.1.e al
   revés, o sea el modo de falla exacto que la 018 vino a cerrar;
2. **invisible** — la vitrina saca la cadena de los dos baldes (`api/audit.py:271`), así que un
   intento impedido dejaba de contarse entre los bloqueos: el inspeccionado se borraba del
   reporte eligiendo cómo se llama su propio tráfico;
3. **veneno** — los dos lectores de la cadena releen TODAS las filas `model='license'`, hoy por
   un lector único (`audit_events.chained_entries`, `licensing/audit_events.py:130`) que
   consumen `verify_chain` (`:159`) y el export de true-up (`licensing/trueup_export.py`, que lo
   importa en su `:31`). Una fila ajena ahí adentro puede hacer que el deployment se acuse solo
   de manipulación y que le falle el true-up al cliente: la evidencia con la que el operador le
   factura, rota desde un body.

Es el mismo hallazgo que ya se había cazado para el campo `tool` en `api/inspect.py:88-137`,
donde está escrita la doctrina de la casa: «un firewall cuyo reporte de cobertura lo escribe el
inspeccionado no es un reporte».

## Qué prueba este archivo y qué NO

La defensa se pagó en dos capas y cada una tiene sus propios tests:

* **capa A** (`services/retention/classifier.py`) sacó la exclusión de la columna `model` y la
  puso en la FORMA de `guardian_events`: se purga lo que es demostrablemente TRÁFICO, y el
  primer evento de una fila de la cadena trae marcas (`seq`, `prev_hash`, `event_type`) que
  sólo escribe el emisor de la 021 dentro de la transacción que avanza el head bajo
  `FOR UPDATE`. Desde el dictamen del manager del 14-ago **no hay condición sobre `model`ni
  siquiera como aditiva** — «la exclusión la compra la FORMA, no el literal»—, y por eso una
  fila que dice `license` con forma de tráfico es un spoof, y muere. Sus bordes —las dos formas
  nulas, `["seq"]`, el `seq` en segunda posición— se miden sobre el predicado en
  `tests/unit/test_retention_classifier.py`, y el acoplamiento con el emisor real lo clava allá
  `test_la_forma_que_emite_el_emisor_real_no_es_purgable`;
* **capa B** (`gateway.sanear_modelo_declarado`) sacó el literal del codominio de lo auditable
  en los dos escritores. Su comportamiento —saneo, orden sanear→auditar→rechazar, el 422— se
  mide en `test_modelo_reservado_licencia.py`.

Acá NO se re-miden esas piezas. Acá se siembra el dataset ABUSIVO —tráfico de verdad, con
estados de bloqueo de verdad, disfrazado de cadena en todas las formas que la columna admite— y
se le exigen **las cuatro cosas a la vez, sobre la misma tabla y en la misma corrida**:

1. **mortal**: cada fila spoofeada cae en exactamente UNA clase de retención, por los dos
   caminos (el SQL que borra y el Python que explica la corrida). Las DOS excepciones —las
   formas nulas de `guardian_events`— son expectativa declarada, con su motivo escrito en el
   `DATASET`: no prueban ser tráfico, no se borran, y el residuo lo cuenta el purgador;
2. **visible**: aparece en la vitrina (`api/audit.py`) en el balde que le corresponde — el
   officer la tiene que poder ver. Las SIETE filas que declaran el literal pelado son la
   excepción DECLARADA (columna `balde` = `FUERA_DE_BALDES`): la vitrina las excluye de los dos
   baldes por `~dice_licencia()` y el test afirma las dos mitades de ese hueco —ni en uno ni en
   el otro, y sin embargo presentes en el listado SIN filtro—. El porqué entero está abajo, en
   «El acoplamiento con `api/audit.py`»;
3. **cadena sana**: `verify_chain` sigue verde con todo el dataset abusivo adentro, y el export
   de true-up no se lleva ni una fila ajena;
4. **el centinela también**: la fila saneada `license__cliente` es igual de mortal y de visible.

Las cuatro juntas importan porque el bug era exactamente eso: una fila que ganaba las tres
propiedades de un saque. Probarlas de a una, cada una en su archivo, deja sin cubrir el único
escenario que el atacante monta — la fila que está viva, en la tabla, mientras los cuatro
lectores la miran.

## El acoplamiento con `api/audit.py`, ya CONSUMADO (dictamen del 14-ago, punto b)

Los asserts del punto 2 miden la vitrina REAL por HTTP, o sea que dependen de qué exclusión
aplique `api/audit.py::_build_query`. Ese archivo no es de este agente y **ya migró**: hoy
excluye por el LITERAL PELADO (`~dice_licencia()`, `api/audit.py:271`, leído en la fuente),
como en `main`, y no por `~es_licencia()` (literal **más** el `seq` del eslabón), que era lo
que aplicaba cuando este archivo se escribió.

La predicción que estaba escrita acá se cumplió tal cual: las SIETE filas del `DATASET` con
`model='license'` salieron de los DOS baldes y el punto 2 se puso rojo para ellas —ocho rojos
medidos: las siete filas más el invariante de conjunto—. Lo que se corrigió fue la columna
`balde` de esas filas, a `FUERA_DE_BALDES`; la vitrina no se tocó y el dictamen no se volvió a
discutir.

No es una regresión: es el comportamiento heredado de `main` que el dictamen aceptó
explícitamente («un spoof viejo con `model='license'` sigue invisible en la vitrina… pero ahora
es purgable por forma, así que el problema se extingue solo con las corridas»). Y el
compensador no es una promesa, es un hecho que este mismo archivo mide en el punto 1: **cinco
de esas siete filas caen en una clase de retención** y mueren con su plazo; las dos que no son
las de `guardian_events` nulo, que no mueren por el fail-closed del portón y las cuenta el
residuo (ver el bloque de esas dos filas en el `DATASET`). O sea que el residuo invisible se
extingue con las corridas en vez de quedarse para siempre, que es exactamente el trato.

El hueco se afirma, no se deja como ausencia: para cada una de esas siete filas el punto 2 pide
que NO esté en `bloqueados` ni en `permitidos`, y que siga apareciendo en el listado SIN filtro
`estado` —la mitad reversible del dictamen: la fila se salió del filtro, no de la pantalla—. El
invariante de conjunto compara contra el subconjunto NO reservado y además afirma la disjunción
por separado. Un test que sólo las sacara de la lista esperada seguiría pasando el día que la
exclusión se ensanche y se lleve puesto al centinela.

El centinela y el tráfico normal NO se movieron: no declaran el literal, así que siguen visibles
con las dos exclusiones. Ésa es justamente la parte del punto 2 que sigue midiendo el daño.

Y por eso el dataset convive con una cadena LEGÍTIMA emitida por el emisor real
(`emit_license_event`, no un dict a mano): la mitad difícil de este hallazgo no es matar al
spoof, es matarlo SIN tocar los eslabones de verdad. Si la defensa se pasara de estricta, la
purga borraría un eslabón que `verify_chain` relee y el deployment se acusaría solo de tamper —
el incidente de confianza de FR-003 causado por la defensa en vez de por el ataque.

## Por qué el punto 4 es una red y no una redundancia

`license__cliente` es hoy una fila mortal y visible por el mismo motivo que cualquier otra: no
es el literal reservado. Pero es la que se pone roja el día que alguien escriba un
`LIKE 'license%'` en un lector nuevo —y en LIKE el `_` es comodín de un carácter, así que
`'license_%'` también la agarra—. Ese día el centinela dejaría de ser el lugar donde el intento
queda VISIBLE y pasaría a ser un segundo escondite, con el agravante de que lo estrenaría la
defensa. El test existe para que ese cambio no pueda entrar callado.

## Que este archivo muerde está MEDIDO, no supuesto

Corrida de mutación del 14-ago sobre los 41 tests de este archivo. El número es cuántos se
ponen rojos; la columna «unit» es el MISMO mutante medido sobre
`tests/unit/test_retention_classifier.py` (74 tests), y está para que se vea dónde muerde cada
cosa en vez de reclamar cobertura que vive en otro lado:

| mutación                                                        | acá | unit |
|-----------------------------------------------------------------|-----|------|
| el portón deja de nombrar la lista vacía (`= '[]'::jsonb`)        |  13 |   11 |
| VUELVE la condición aditiva `model <> 'license'` al portón        |   5 |    2 |
| capa B revertida (`sanear_modelo_declarado` pasa todo intacto)    |   2 |    0 |
| saco `event_type` de las marcas de la cadena                      |   0 |    4 |
| saco la guarda `jsonb_typeof(primero) = 'object'`                 |   0 |    4 |
| saco `guardian_events IS NOT NULL`                                |   0 |    3 |
| `dice_licencia()` compara por PREFIJO en vez de por igualdad      |  0† |    2 |
| `_modelo()` sin su `coalesce`                                     |   0 |    1 |
| el EMISOR deja de escribir el eslabón (`guardian_events=[]`)      |   0 |    1 |
| el EMISOR renombra las tres marcas de la cadena                   |   0 |    1 |

Un test que no se cae con ninguna mutación es decoración, así que la columna de ceros hay que
leerla y no esconderla: **este archivo ya casi no muerde los bordes finos del portón**, y es
consecuencia buscada del dictamen del 14-ago. Con la exclusión colgando de la FORMA y sin
condición sobre `model`, las QUINCE filas de este dataset traen cinco formas de
`guardian_events` —`[]` en once, las dos nulas, y dos listas de objetos sin `seq` en la primera
posición— sobre las que el portón tiene DOS respuestas nada más: trece purgables y dos residuo.
Así que los bordes —tipos raros del primer evento, marcas de a una, el trivalente— se miden
donde se pueden sembrar de a una: en el archivo unit, con `_FORMAS` y
rollback. Lo que este archivo sigue midiendo, y ningún otro, es el escenario COMPLETO: las
cuatro propiedades a la vez, sobre la misma tabla, con la cadena legítima viva y los cuatro
lectores mirando.

Las variantes de caja llevan escrito arriba por qué se sostienen igual, en vez de figurar como
cobertura que no cubre.

† Ese cero se midió cuando la vitrina excluía con `~es_licencia()`: este archivo no consumía
`dice_licencia()` por ningún lado y la mutación no lo tocaba. Con la migración adentro
(`api/audit.py:271`) sí lo consume, así que se RE-MIDIÓ y da 5 — ver la tabla de abajo. Las
otras filas siguen valiendo sin re-medir: son mutaciones del portón, del emisor y de la capa B,
y ninguno de los asserts que la enmienda tocó (los del punto 2, que hablan sólo con la vitrina
por HTTP) los consume.

## La enmienda del 14-ago también está medida

Los asserts del punto 2 cambiaron de forma (apareció `FUERA_DE_BALDES`), así que se midieron
aparte. Las cuatro primeras son mutaciones del DATASET —mover la columna `balde`—, que es cómo
se mide un assert de expectativa; las dos últimas mutan a la vitrina desde ESTE archivo, con
`monkeypatch` sobre `api.audit`, porque ni `api/audit.py` ni `classifier.py` son de este agente
y no se tocan ni para medir:

| mutación                                                            | rojos |
|---------------------------------------------------------------------|-------|
| `spoof_lista_vacia` vuelve a `BLOQUEADOS`                             |   3   |
| `spoof_permitido` vuelve a `PERMITIDOS`                               |   3   |
| `centinela_bloqueo` pasa a `FUERA_DE_BALDES`                          |   3   |
| `normal_bloqueado` pasa a `FUERA_DE_BALDES`                           |   3   |
| `dice_licencia()` por PREFIJO (`model LIKE 'license%'`)               |   5   |
| la exclusión por literal se aplica TAMBIÉN al listado sin filtro      |   9   |

Las cuatro de arriba dan los mismos tres rojos, y no es casualidad: caen la fila, el invariante
de conjunto y la guarda de expectativa (`test_el_dataset_esta_entero_en_la_tabla`), que es la
que impide apagar un rojo moviendo una fila de columna. Las dos de abajo son las que importan:
la del prefijo es el `LIKE 'license%'` del punto 4 —se lleva puesto al centinela y caen sus dos
filas, el invariante, el test del punto 4 y el e2e del bloqueo real—, y la última es la única
que muerde la mitad «y sigue visible sin filtro» del hueco: nueve rojos, las siete filas
reservadas más el invariante más la cadena legítima. Sin esa mitad, «no está en ningún balde»
pasaría verde el día que la fila desapareciera de la pantalla entera.

Un mutante que NO se cae y no es un agujero, anotado para que la próxima corrida no lo persiga:
que el emisor deje de escribir SÓLO `event_type` (dejando `seq` y `prev_hash`) da 0 rojos en los
dos archivos, y está bien — la fila sigue protegida por las otras dos marcas. El que tiene que
romper es el emisor que se queda sin NINGUNA marca, y rompe (las dos últimas filas de la tabla).
"""
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import null

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_retencion_dataset_abusivo"
LOGS = "/api/v1/audit-logs"
GW = "/api/v1/gw/v1/messages"
AUDIT_INTERNO = "/api/v1/internal/audit"

SECRETO_INTERNO = "secreto-interno-del-dataset-abusivo"
CABECERA_INTERNA = {"X-Basa-Internal": SECRETO_INTERNO}

# Los dos literales del hallazgo. Van a mano y no importados de `gateway`/`classifier` a
# propósito: si mañana alguien renombra el centinela o afloja el literal reservado, este archivo
# tiene que ponerse ROJO y no seguirlo en silencio. Un test que importa la constante que está
# midiendo se pone de acuerdo consigo mismo y no prueba nada.
RESERVADO = "license"
CENTINELA = "license__cliente"

CLASE_USO = "usage_metadata"
CLASE_SEGURIDAD = "security_events"
CLASE_CONFIG = "config_audit"

BLOQUEADOS = "bloqueados"
PERMITIDOS = "permitidos"

# Tercer valor de la columna `balde` del DATASET, y NO un valor del parámetro `estado` de la
# API —ahí sólo existen los dos de arriba (`api/audit.py::EstadoFiltro`)—. Es la expectativa
# «esta fila no está en NINGUNO de los dos baldes», que desde la migración de la vitrina a
# `~dice_licencia()` es lo que le pasa a toda fila que declare el literal reservado.
#
# Va como tercer estado y no como «sacar esas filas de la lista esperada» a propósito: una
# ausencia no se puede afirmar por fila, y lo que hay que afirmar acá es el hueco entero —ni en
# uno ni en el otro, y aun así visible sin filtro—. Ver «El acoplamiento con `api/audit.py`».
FUERA_DE_BALDES = "fuera_de_baldes"

# Eslabones legítimos que se emiten para que la cadena tenga algo real que verificar. Tres y no
# uno: con un solo eslabón, un `verify_chain` que dejara de mirar la contigüidad seguiría verde.
ESLABONES = 3

# Dispara `SECRET_PATTERNS["OpenAI API Key"]` ⇒ bloqueo por regex pura de la librería
# compartida, sin depender del sidecar NLP (que la suite apaga a propósito, ver conftest).
SECRETO = "sk-ABCdefghij0123456789"


# ── El dataset abusivo ────────────────────────────────────────────────────────────────
#
# (marca, model, compliance_status, guardian_events, clase esperada,
#  balde esperado: `BLOQUEADOS`, `PERMITIDOS` o `FUERA_DE_BALDES`).
#
# La marca es la identidad de la fila DENTRO del test: los `compliance_status` se repiten entre
# formas, así que un assert que fallara por estado no diría cuál de los SIETE disfraces con el
# literal pelado se coló. Se compara por id y la marca es cómo se lee ese id cuando el assert
# revienta.
#
# Todas las filas `license` de acá llevan un `compliance_status` de BLOQUEO salvo donde se
# aclara, y eso no es decoración: el caso que hace grave al hallazgo es el atacante que se
# esconde detrás de un intento impedido de verdad. Una semilla con `passed` a secas probaría el
# mecanismo sin probar el daño.
#
# Las filas se siembran por DB directa porque lo que se mide son los cuatro LECTORES sobre la
# tabla, no por qué puerta entró cada fila. Los dos escritores vivos se ejercitan aparte, por
# HTTP, al pie del archivo.
DATASET = [
    # ── El spoof en todas las formas que el jsonb admite sin traer un `seq` de cadena ──
    #
    # LAS SIETE FILAS QUE DECLARAN EL LITERAL PELADO VAN `FUERA_DE_BALDES`, y el motivo se
    # escribe acá porque es donde se lee la columna: desde el dictamen del 14-ago (punto b) la
    # vitrina excluye por LITERAL (`~dice_licencia()`, `api/audit.py:271`), así que ninguna de
    # estas filas está en `bloqueados` ni en `permitidos`. Es comportamiento HEREDADO de `main`
    # —no una regresión de esta ronda— y el dictamen lo aceptó a cambio de lo que el punto 1 de
    # este mismo archivo mide: ahora estas filas SÍ son purgables por FORMA (cinco de las siete
    # caen en una clase; las dos nulas son el residuo del bloque de abajo), así que el spoof
    # invisible se extingue con las corridas en vez de quedarse para siempre.
    #
    # Lo que NO se hace es devolverles un balde para apagar el rojo: eso sería volver a poner el
    # criterio de la vitrina en manos del inspeccionado. Lo que sí se exige —y es una afirmación,
    # no un hueco— es que no estén en NINGUNO de los dos y que sigan visibles en el listado sin
    # filtro `estado`, que es la mitad reversible del trato.
    #
    # Lo que escribe hoy cualquier pedido que no disparó ningún guardián: el disfraz más
    # barato y el que un atacante consigue sin hacer nada especial.
    ("spoof_lista_vacia", RESERVADO, "blocked_secret", [], CLASE_SEGURIDAD, FUERA_DE_BALDES),
    # ── Las DOS formas nulas: el residuo del fail-closed (dictamen del manager, 14-ago, c) ──
    #
    # Éstas NO mueren, y la clase esperada es `None` a propósito. El motivo entero, porque es
    # una inversión de expectativa y no se enmienda un test sin escribir por qué:
    #
    # El portón pregunta «¿esta fila es demostrablemente TRÁFICO?» y sólo entonces habilita el
    # borrado. Un `guardian_events` nulo **no prueba nada**: no es un array vacío (el tráfico
    # que no disparó ningún guardián), no es un objeto que se pueda inspeccionar, no es nada. Y
    # lo que está del otro lado de la duda no es una fila de metadata cualquiera: puede ser un
    # eslabón de la cadena con el jsonb en un estado que este código no reconoce, y borrarlo es
    # irreversible —`verify_chain` lee el hueco como manipulación y el true-up pierde
    # historial—. Entre borrar de más y borrar de menos, el default del depto va del lado
    # REVERSIBLE.
    #
    # Lo que NO se acepta es el «y nadie se entera», que era la otra mitad del problema: la
    # corrida de purga cuenta esas filas en `filas_no_clasificadas`, y **también en la corrida
    # `dry_run`** — el officer que ensaya la purga tiene que ver el residuo ANTES de apretar el
    # botón. Ese contador lo implementa OTRO agente en `services/retention/purger.py`, y NO vive
    # sobre `ResultadoPurga` (que es por CLASE, y un residuo no tiene clase) sino sobre el
    # dataclass `ResultadoCorrida` (`purger.py:345-346`), que es el rastro de la corrida entera;
    # viaja con `cutoff_no_clasificadas` al lado, porque el número sin el umbral bajo el que se
    # contó no significa nada. El umbral es el más antiguo de las políticas vigentes, así que el
    # contador es un PISO: estas dos filas recién suman cuando estén vencidas bajo TODAS. Acá se
    # lo nombra para que la decisión de no borrar y la de contar queden escritas juntas, que es
    # como se toman.
    #
    # SQL NULL de verdad (la columna es nullable desde la 003): `NULL -> 0` es NULL y todo lo
    # que se le pregunte después también.
    ("spoof_jsonb_nulo", RESERVADO, "blocked_prohibited", null(), None, FUERA_DE_BALDES),
    # El JSON `null`, que NO es lo mismo y por eso va aparte: pasarle `None` a esta columna no
    # escribe SQL NULL, porque el tipo JSON de SQLAlchemy trae `none_as_null=False` por default
    # y persiste el literal `'null'::jsonb`. Se ve en que `jsonb_typeof` devuelve `'null'` en
    # vez de NULL. Hacen falta las DOS sembradas: sólo la de arriba muerde el trivalente de SQL.
    ("spoof_json_null", RESERVADO, "blocked_by_policy", None, None, FUERA_DE_BALDES),
    # Un evento de guardián REAL: es un objeto, pero un contador de cadena no es algo que el
    # motor tenga cómo poner ahí. Es la forma que tendría la fila de un bloqueo del plano chat.
    ("spoof_evento_de_guardian", RESERVADO, "blocked_by_policy",
     [{"type": "PII_MASKING", "action": "mask", "count": 2}], CLASE_SEGURIDAD, FUERA_DE_BALDES),
    # El `seq` empujado una posición. Los dos lectores de la cadena leen `guardian_events[0]` y
    # nada más; un clasificador que barriera la lista entera protegería filas que la cadena ni
    # mira, y este disfraz sería gratis.
    ("spoof_seq_en_el_segundo", RESERVADO, "blocked_nlp_unavailable",
     [{"type": "SECRET_DETECTION"}, {"seq": 1, "prev_hash": "0" * 64}],
     CLASE_SEGURIDAD, FUERA_DE_BALDES),
    # El mismo disfraz sobre tráfico que NO se bloqueó: la otra mitad del daño. Sin la enmienda,
    # un pedido servido se borraba del balde de permitidos, o sea del denominador con el que el
    # officer lee cualquier tasa.
    ("spoof_permitido", RESERVADO, "passed", [], CLASE_USO, FUERA_DE_BALDES),
    # Y sobre un cambio de configuración: es la fila que prueba que el portón viaja en TODOS los
    # predicados de clase y no en dos. Si sólo lo llevaran `security_events` y `usage_metadata`,
    # ésta sería la única inmortal y no se vería en ningún assert de las demás. (Que la vitrina
    # la cuente como «permitida» y no en un balde propio es el hueco conocido del filtro binario
    # —los `config_change*` no son ni bloqueo ni rechazo—, no algo que esta ronda cambie.)
    ("spoof_config", RESERVADO, "config_change_nlp_fail_mode", [], CLASE_CONFIG,
     FUERA_DE_BALDES),

    # ── Variantes de caja y espacios ──
    #
    # Por los dos escritores vivos no llegan: la capa B compara `strip().casefold()`, así que las
    # desaloja antes de escribir. Se siembran igual por dos motivos.
    #
    # 1. El clasificador es la ÚLTIMA línea para las filas que YA están escritas. La capa B saca
    #    el literal del codominio DESDE AHORA, pero no sanea hacia atrás la base de un cliente
    #    instalado (mismo argumento que el de la guarda de la cadena en
    #    `licensing/audit_events.py:103`), y en esa base `License` con esa caja existe. Tiene que
    #    morir y verse igual. (Cuando este bloque se escribió había además un plano vivo SIN
    #    saneo —`api/chat.py`—; ya no: hoy pasa por `_modelo_auditable` (`chat.py:503`), que
    #    reusa `sanear_modelo_declarado`, en los SEIS escritores de la columna. Ver HALLAZGO 1.)
    # 2. Son la red del arreglo EQUIVOCADO. Quien lea el informe del gate como «el problema es la
    #    caja» y responda normalizando el `model` en el clasificador en vez de sacar la columna
    #    del portón deja estas cuatro filas inmortales y silenciosas: `TRIM/LOWER` + exclusión
    #    por `model` las manda a las cuatro a la exclusión y este bloque se pone rojo.
    #
    # Desde el dictamen del 14-ago el portón ni mira `model`, así que estas cuatro caen por donde
    # cae cualquier fila con `guardian_events=[]`: son tráfico y mueren. Eso las vuelve
    # indistinguibles de `normal_bloqueado`/`normal_permitido` para la PURGA — su valor hoy está
    # del lado de la VITRINA y del punto 2, donde el `LIKE`/prefijo/normalización de un lector
    # nuevo sí las movería de balde.
    ("caja_capitalizada", "License", "blocked_secret", [], CLASE_SEGURIDAD, BLOQUEADOS),
    ("caja_mayusculas", "LICENSE", "blocked_prohibited", [], CLASE_SEGURIDAD, BLOQUEADOS),
    ("espacios_alrededor", " license ", "blocked_by_policy", [], CLASE_SEGURIDAD, BLOQUEADOS),
    ("espacios_raros", "\tlicense\n", "passed", [], CLASE_USO, PERMITIDOS),

    # ── El centinela (requisito 4) ──
    #
    # Lo que la capa B deja escrito cuando el cliente declara el literal. Tiene que ser una fila
    # como cualquier otra: mortal, visible y en su balde. El día que un lector nuevo use
    # `LIKE 'license%'` —o `'license_%'`, que en LIKE es lo mismo porque el `_` es comodín— estas
    # dos filas se van del balde y este bloque lo dice.
    ("centinela_bloqueo", CENTINELA, "blocked_secret", [], CLASE_SEGURIDAD, BLOQUEADOS),
    ("centinela_permitido", CENTINELA, "passed", [], CLASE_USO, PERMITIDOS),

    # ── Control: tráfico normal ──
    #
    # Para que «cae en security_events» signifique algo hay que ver una fila que cae ahí sin
    # disfraz. Si el dataset entero fuera `license`, un clasificador roto que mandara TODO a
    # `security_events` pasaría el archivo completo.
    ("normal_bloqueado", "claude-3-5-sonnet-20241022", "blocked_secret", [],
     CLASE_SEGURIDAD, BLOQUEADOS),
    ("normal_permitido", "ollama-qwen3-4b", "passed", [], CLASE_USO, PERMITIDOS),
]

# Marcas que declaran el literal reservado en `model`. Son las que un lector ingenuo
# (`WHERE model = 'license'`) se llevaría puestas, y las que el punto 3 exige que la cadena y el
# true-up NO toquen.
DISFRAZADAS = tuple(marca for marca, modelo, *_ in DATASET if modelo == RESERVADO)

# ── Formas que NO se siembran, y por qué se decidió sacarlas ──────────────────────────
#
# Esta lista existe para que la ausencia sea una DECISIÓN visible en el diff y no un olvido.
# Son primeros `guardian_event` que no son un objeto —o que lo son pero sin `prev_hash`—.
#
# El motivo por el que se sacaron CADUCÓ, y se anota en vez de borrarse: cuando este archivo se
# escribió, cualquiera de ellas en la tabla hacía que los dos lectores de la cadena **reventaran**
# con una excepción sin capturar en vez de dar un veredicto, así que el punto 3 (`verify_chain`
# verde, true-up limpio) no se podía ni afirmar. Eso era el HALLAZGO 2, y ya está CERRADO: los
# dos lectores comparten hoy `chained_entries` con la guarda de tipo `_is_chain_link`
# (`licensing/audit_events.py:87,130`), que saltea la fila deforme en vez de caerse.
#
# Siguen sin sembrarse acá por dos motivos, y ninguno es el de antes:
#
# * **hoy ningún escritor puede producirlas**: `guardian_events` no es declarable por el cliente
#   en ninguno de los tres productores, y eso es exactamente lo que clava
#   `test_ningun_escritor_deja_que_el_cliente_le_ponga_el_seq_a_su_propia_fila`. Ese test es la
#   razón por la que estas formas son teóricas; si se pusiera rojo, dejan de serlo;
# * **ya tienen archivo propio**: el escenario «fila deforme viva + cadena legítima, y los dos
#   lectores tienen que sobrevivir» es lo que mide
#   `tests/integration/test_cadena_filas_deformes.py`.
#   Duplicarlo acá sería pagar dos veces la misma afirmación.
#
# La mitad que SÍ se puede afirmar sin los lectores de la cadena —qué hace el portón con cada
# una— ya la cubre la tabla `_FORMAS` de `tests/unit/test_retention_classifier.py`, sobre el
# predicado y con rollback, y ahí están sembradas de a una: `["seq"]`, `["consequence"]`, `[7]`,
# `{"seq": 1}` y el objeto con marcas dan todas NO PURGABLE (fail-closed), que es lo contrario
# de lo que uno esperaría de una fila deforme y por eso se mide allá y no se supone acá. La
# lista completa, con el efecto MEDIDO de cada forma sobre los dos lectores ANTES de la guarda,
# está en la tabla del HALLAZGO 2 al pie de este archivo — y `_is_chain_link` la cita desde el
# fuente, así que se queda como registro de lo que se arregló.


# ── Semilla ───────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    client.headers.update(admin_headers(client))
    cadena = sembrar_cadena_legitima(factory)
    marcas = sembrar_dataset_abusivo(factory)
    yield client, factory, marcas, cadena
    cleanup()


def sembrar_cadena_legitima(factory):
    """`ESLABONES` eslabones por el emisor REAL de la 021, sobre una tabla en cero.

    Por el emisor y no por dicts a mano: lo que este archivo tiene que proteger es la cadena que
    el producto emite, con la forma que el producto le da. Un `{"seq": n}` escrito acá probaría
    que sigue excluido un eslabón que nadie emite, y el día que `_append_chained` cambie de forma
    nadie se enteraría por este lado.

    La tabla arranca vacía —incluida `license_runtime_state`— para que el `checked` de
    `verify_chain` y el `counter` del true-up sean números exactos y no «al menos». Un
    «al menos N» pasaría igual con una fila ajena colada adentro, que es justo lo que se mide.

    Devuelve [(id, entry)] ordenado por `seq`.
    """
    from src.licensing.audit_events import EVENT_SEAT_LIMIT, emit_license_event
    from src.models.audit import AuditLog
    from src.models.license_state import LicenseRuntimeState
    db = factory()
    try:
        db.query(AuditLog).delete()
        db.query(LicenseRuntimeState).delete()
        db.commit()
        for i in range(ESLABONES):
            emit_license_event(db, EVENT_SEAT_LIMIT, license_id="lic_test_0001",
                               seats_used=10 + i, max_seats=10, reason=f"eslabon-{i}")
        filas = db.query(AuditLog).filter(AuditLog.model == RESERVADO).all()
        return sorted(((str(f.id), f.guardian_events[0]) for f in filas),
                      key=lambda par: par[1]["seq"])
    finally:
        db.close()


def sembrar_dataset_abusivo(factory):
    """El `DATASET` en la tabla, con timestamps escalonados. Devuelve marca → id."""
    from src.models.audit import AuditLog
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        base = datetime.utcnow() - timedelta(minutes=len(DATASET))
        marcas = {}
        for i, (marca, modelo, estado, eventos, _clase, _balde) in enumerate(DATASET):
            fila_id = uuid.uuid4()
            db.add(AuditLog(
                id=fila_id, tenant_id=DEFAULT_TENANT_ID,
                timestamp=base + timedelta(minutes=i), model=modelo,
                prompt_tokens=0, completion_tokens=0, cost_usd=0,
                pii_detected=False, compliance_status=estado, latency_ms=7,
                guardian_events=eventos,
            ))
            marcas[marca] = str(fila_id)
        db.commit()
        return marcas
    finally:
        db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────────────


def clases_que_reclaman(factory, fila_id):
    """Las clases cuyo PREDICADO SQL levanta esta fila: el camino que BORRA."""
    from src.models.audit import AuditLog
    from src.services.retention import classifier
    db = factory()
    try:
        return [c for c in classifier.clases()
                if db.query(AuditLog.id)
                    .filter(classifier.predicado(c), AuditLog.id == fila_id).count()]
    finally:
        db.close()


def clase_en_memoria(factory, fila_id):
    """Lo que dice `clase_de()` de la fila LEÍDA de la tabla: el camino que EXPLICA la corrida.

    Leída y no construida en memoria a propósito — el purgador arma su rastro con lo que trae la
    query, y en la columna jsonb lo que se le pasa al constructor y lo que queda persistido no
    siempre coinciden.
    """
    from src.models.audit import AuditLog
    from src.services.retention import classifier
    db = factory()
    try:
        return classifier.clase_de(db.query(AuditLog).filter(AuditLog.id == fila_id).one())
    finally:
        db.close()


def ids_de_la_vitrina(client, **params):
    payload = client.get(LOGS, params={**params, "limit": 100}).json()
    return {fila["id"] for fila in payload["logs"]}


def nombres(marcas, ids):
    """ids → marcas, para que el assert que falla diga «spoof_clave_suelta» y no un UUID."""
    inverso = {fila_id: marca for marca, fila_id in marcas.items()}
    return sorted(inverso.get(fila_id, fila_id) for fila_id in ids)


def _params(marca):
    """Los tres datos del DATASET que un test necesita, buscados por marca."""
    for fila in DATASET:
        if fila[0] == marca:
            return fila
    raise KeyError(marca)


MARCAS = tuple(fila[0] for fila in DATASET)

# Las dos mitades de la columna `balde`, partidas una sola vez y acá: el invariante de conjunto
# compara contra la primera y afirma el hueco con la segunda.
MARCAS_EN_BALDES = tuple(fila[0] for fila in DATASET if fila[5] != FUERA_DE_BALDES)
MARCAS_FUERA_DE_BALDES = tuple(fila[0] for fila in DATASET if fila[5] == FUERA_DE_BALDES)


def test_el_dataset_esta_entero_en_la_tabla(harness):
    """Guarda de la semilla: si una fila no llegara a persistirse —un jsonb que el driver
    rechaza, un estado que no entra en la columna—, los tests de abajo pasarían por vacío y el
    archivo entero mentiría en verde."""
    _client, factory, marcas, cadena = harness
    from src.models.audit import AuditLog
    db = factory()
    try:
        assert db.query(AuditLog).count() == len(DATASET) + ESLABONES
    finally:
        db.close()
    assert sorted(marcas) == sorted(MARCAS)
    assert [entry["seq"] for _id, entry in cadena] == list(range(1, ESLABONES + 1))

    # Y la guarda de la EXPECTATIVA, que es la que impide apagar un rojo moviendo de columna:
    # `FUERA_DE_BALDES` tiene que ser exactamente «declara el literal pelado», porque ése y no
    # otro es el criterio con el que la vitrina excluye (`~dice_licencia()`). Si mañana una fila
    # sin el literal se cae de su balde, lo que hay que corregir es el lector que ensanchó la
    # exclusión —el `LIKE 'license%'` del punto 4—, no esta columna; y si una fila con el
    # literal aparece en un balde, la exclusión se aflojó. Las dos cosas son hallazgos, no
    # ajustes de dataset.
    assert MARCAS_FUERA_DE_BALDES == DISFRAZADAS, (
        "las dos columnas de expectativa dejaron de decir lo mismo: fuera de los baldes está "
        f"{MARCAS_FUERA_DE_BALDES} y el literal lo declaran {DISFRAZADAS}")


# ── 1. MORTAL ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("marca", MARCAS)
def test_cada_fila_del_dataset_cae_en_exactamente_una_clase(harness, marca):
    """La regla 1 del contrato del clasificador, sobre el dataset que el ataque monta.

    Se exige la clase EXACTA y no «alguna clase» por dos motivos. Uno: «alguna» pasaría con un
    clasificador que mandara todo a la misma bolsa, y el plazo con el que muere una fila es el
    entregable de esta spec. Dos: se pregunta por los DOS caminos —el predicado SQL, que es el
    que borra, y `clase_de()`, que es el que le explica al auditor qué se borró— y pedir el mismo
    literal a los dos es la única forma de que no puedan ponerse de acuerdo en la respuesta
    equivocada.

    La clase esperada `None` es una expectativa de PLENO DERECHO, no un caso sin cubrir: son
    las dos formas nulas de `guardian_events`, que el portón deja del lado de «no se puede
    demostrar que sea tráfico» a propósito (fail-closed). El motivo largo, con el contador que
    lo compensa, está escrito en el `DATASET`, en el bloque de esas dos filas.
    """
    _client, factory, marcas, _cadena = harness
    _marca, modelo, estado, _eventos, clase, _balde = _params(marca)
    fila_id = marcas[marca]
    esperadas = [] if clase is None else [clase]

    if clase is None:
        assert clases_que_reclaman(factory, fila_id) == [], (
            f"«{marca}» (model={modelo!r}, estado={estado!r}) volvió a ser purgable. Su "
            "`guardian_events` es nulo, o sea que NO prueba que la fila sea tráfico, y del otro "
            "lado de esa duda puede haber un eslabón de la cadena con el jsonb en un estado que "
            "el código no reconoce: borrarlo es irreversible. Si el cambio es deliberado, se "
            "discute con el dictamen del 14-ago (punto c) delante, no se ajusta el test.")
        assert clase_en_memoria(factory, fila_id) is None, (
            f"«{marca}»: el gemelo Python le puso clase a una fila que el SQL deja afuera. El "
            "rastro de la corrida contaría como purgada una fila que sigue en la tabla.")
        return

    assert clases_que_reclaman(factory, fila_id) == esperadas, (
        f"«{marca}» (model={modelo!r}, estado={estado!r}) no la reclama exactamente {clase!r}: "
        "si la lista está vacía la fila es INMORTAL —ninguna purga la borra y nadie se entera—, "
        "y la columna `model` la elige el cliente (`gateway.py:1455`). Desde el dictamen del "
        "14-ago la exclusión cuelga SÓLO de la FORMA de `guardian_events`, que es lo único que "
        "escribe el emisor de la 021 y no un body.")
    assert clase_en_memoria(factory, fila_id) == clase, (
        f"«{marca}»: el gemelo Python del clasificador no dice lo mismo que el SQL. El rastro de "
        "la corrida le informaría al auditor una clase distinta de la que se borró.")


def test_ningun_eslabon_legitimo_queda_reclamado_por_una_clase(harness):
    """La otra mitad, y la que importa primero: endurecer la exclusión no puede dejar afuera a un
    eslabón de verdad.

    Si esto se pusiera rojo, la purga borraría una fila que `verify_chain` relee y el deployment
    se acusaría SOLO de manipulación — el incidente de confianza de FR-003 provocado por la
    defensa y no por el ataque.
    """
    _client, factory, _marcas, cadena = harness
    for fila_id, entry in cadena:
        assert clases_que_reclaman(factory, fila_id) == [], (
            f"el eslabón seq={entry['seq']} quedó reclamado por una clase de retención")
        assert clase_en_memoria(factory, fila_id) is None, (
            f"clase_de() le puso clase al eslabón seq={entry['seq']}: el rastro diría que la "
            "evidencia de licencias tiene fecha de vencimiento. No la tiene.")


# ── 2. VISIBLE ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("marca", MARCAS)
def test_cada_fila_del_dataset_aparece_en_el_balde_que_le_corresponde(harness, marca):
    """La vitrina REAL (`api/audit.py`), con auth de officer y por HTTP.

    Se mide contra la pantalla y no contra la primitiva a propósito: la invisibilidad no era un
    problema del predicado, era el número que el officer lee. Y se afirman las dos mitades —está
    en su balde y NO está en el otro—: una fila que apareciera en los dos rompería la partición y
    el officer sumaría más que el total.

    `FUERA_DE_BALDES` es una rama de pleno derecho y no un caso sin cubrir: son las SIETE filas
    que declaran el literal pelado, que la vitrina saca de los DOS baldes desde que migró a
    `~dice_licencia()` (dictamen del 14-ago, punto b). Para ellas se afirma el hueco ENTERO —ni
    en uno ni en el otro— y además que siguen en el listado sin filtro `estado`, que es la mitad
    reversible del trato: la fila salió del filtro, no de la pantalla. Sin esa segunda mitad,
    «no está en ningún balde» sería indistinguible de «se borró de la vitrina», que es
    justamente el daño nº2 que este archivo mide.
    """
    client, _factory, marcas, _cadena = harness
    _marca, modelo, estado, _eventos, _clase, balde = _params(marca)
    fila_id = marcas[marca]

    if balde == FUERA_DE_BALDES:
        for balde_ajeno in (BLOQUEADOS, PERMITIDOS):
            assert fila_id not in ids_de_la_vitrina(client, estado=balde_ajeno), (
                f"«{marca}» (model={modelo!r}, estado={estado!r}) volvió a aparecer en "
                f"«{balde_ajeno}». La vitrina excluye por LITERAL PELADO y esta fila lo declara, "
                "así que o la exclusión se aflojó o el `model` de la fila cambió: las dos son "
                "hallazgos y se miran en `api/audit.py::_build_query`, no en esta columna.")
        assert fila_id in ids_de_la_vitrina(client), (
            f"«{marca}» tampoco aparece en el listado SIN filtro. Estar fuera de los baldes es "
            "aceptable porque es REVERSIBLE —la fila se sigue viendo y el officer la puede "
            "explicar—; si además desaparece de la pantalla, el spoof recuperó la invisibilidad "
            "entera y el dictamen del 14-ago (punto b) deja de sostenerse.")
        return

    otro = PERMITIDOS if balde == BLOQUEADOS else BLOQUEADOS

    assert fila_id in ids_de_la_vitrina(client, estado=balde), (
        f"«{marca}» (model={modelo!r}, estado={estado!r}) no aparece en «{balde}»: el "
        "inspeccionado se borró del reporte eligiendo cómo se llama su propio tráfico.\n"
        f"ANTES DE TOCAR NADA, mirá el `model`: esta fila NO declara {RESERVADO!r} pelado, así "
        "que la exclusión por literal de la vitrina (`~dice_licencia()`) no la alcanza. Si aun "
        "así se cayó del balde, alguien ENSANCHÓ esa exclusión —prefijo, `LIKE 'license%'`, "
        "normalización de caja— y lo que se corrige es ese lector, no la columna `balde` del "
        "DATASET: mover la columna acá es apagar el testigo que mide el daño.")
    assert fila_id not in ids_de_la_vitrina(client, estado=otro), (
        f"«{marca}» aparece además en «{otro}»: los dos baldes dejaron de ser complementarios.")


def test_los_dos_baldes_cubren_el_dataset_entero_sin_huecos_ni_solapes(harness):
    """El invariante de conjunto, que ningún test por fila alcanza a ver.

    `bloqueados` + `permitidos` tiene que ser EXACTAMENTE el dataset MENOS los dos conjuntos que
    la vitrina excluye —las siete filas que declaran el literal y la cadena legítima—, y la
    intersección vacía. Es lo que hace que la pantalla se pueda leer: sin esto, una fila puede
    estar en su balde y aun así haber tráfico invisible o contado dos veces en la vista filtrada.

    Los dos huecos se AFIRMAN por separado en vez de quedar como una lista esperada más corta, y
    la diferencia no es de estilo: una lista corta pasa igual el día que la exclusión se ensanche
    y se lleve puesto al centinela —el `LIKE 'license%'` del punto 4—, porque el conjunto seguiría
    coincidiendo con lo esperado si además se ajustara la columna. Afirmar «estas y sólo estas
    están fuera» es lo que convierte al hueco en una medición.
    """
    client, _factory, marcas, cadena = harness
    bloqueados = ids_de_la_vitrina(client, estado=BLOQUEADOS)
    permitidos = ids_de_la_vitrina(client, estado=PERMITIDOS)
    en_algun_balde = bloqueados | permitidos
    reservadas = {marcas[m] for m in MARCAS_FUERA_DE_BALDES}

    assert bloqueados & permitidos == set()
    assert nombres(marcas, en_algun_balde) == sorted(MARCAS_EN_BALDES)
    assert reservadas & en_algun_balde == set(), (
        f"{nombres(marcas, reservadas & en_algun_balde)} declaran {RESERVADO!r} y aparecieron en "
        "un balde: la vitrina dejó de excluir por el literal pelado.")
    assert reservadas <= ids_de_la_vitrina(client), (
        "…y el hueco es de los BALDES, no de la pantalla: sin filtro `estado` esas filas se "
        "tienen que seguir viendo. Es la mitad reversible del dictamen del 14-ago (punto b), o "
        "sea la razón por la que se aceptó dejarlas fuera del filtro.")
    assert {fila_id for fila_id, _ in cadena} & en_algun_balde == set()


def test_la_cadena_legitima_no_entra_en_ningun_balde_pero_se_ve_sin_filtro(harness):
    """La exclusión es de un FILTRO de tráfico, no un borrado de la pantalla.

    «Se venció la licencia del deployment» no puede aparecer junto a «alguien intentó pegar el
    padrón de socios» —de ahí que no esté en los baldes—, pero es auditoría durable y el officer
    tiene que poder verla para explicar por qué ese día no se sirvió nada.
    """
    client, _factory, _marcas, cadena = harness
    fuera_de_baldes = {fila_id for fila_id, _ in cadena}
    assert fuera_de_baldes & ids_de_la_vitrina(client, estado=BLOQUEADOS) == set()
    assert fuera_de_baldes & ids_de_la_vitrina(client, estado=PERMITIDOS) == set()
    assert fuera_de_baldes <= ids_de_la_vitrina(client)


# ── 3. CADENA SANA ────────────────────────────────────────────────────────────────────


def test_verify_chain_sigue_verde_con_el_dataset_abusivo_en_la_tabla(harness):
    """El daño nº3, medido sobre el lector real y con el ataque presente.

    `verify_chain` relee TODAS las filas `model='license'` (por `chained_entries`,
    `audit_events.py:130`) y acusa manipulación ante cualquier hueco. Con SIETE filas de tráfico
    declarando ese literal en la misma tabla, el reporte tiene que seguir diciendo `ok` y contar
    SÓLO los eslabones reales.

    `checked` exacto y no «al menos»: un contador que subiera con las filas ajenas significaría
    que la cadena las adoptó, y a partir de ahí cualquier purga de esas filas —que son mortales,
    justamente— dejaría un hueco que el verificador leería como tamper. El cliente vería un
    deployment acusándose solo por una fila que otro cliente escribió.
    """
    _client, factory, _marcas, _cadena = harness
    from src.licensing.audit_events import verify_chain
    db = factory()
    try:
        reporte = verify_chain(db)
    finally:
        db.close()
    assert reporte["issues"] == []
    assert reporte["ok"] is True
    assert reporte["checked"] == ESLABONES, (
        "la cadena adoptó filas ajenas: `verify_chain` cuenta más eslabones de los que emitió "
        "el emisor de la 021.")


def test_el_export_de_trueup_no_se_lleva_ni_una_fila_ajena(harness, monkeypatch, tmp_path):
    """El otro lector de la cadena, y el que le cuesta plata al cliente.

    El true-up es el papel con el que el operador renueva: si arrastra una fila ajena, el
    verificador lado-Basa lo rechaza (`cadena interna inválida`) y el cliente se queda sin poder
    demostrar su historial. Se exige el payload EXACTO —los mismos `seq` que emitió el emisor— y
    además que el documento firmado verifique de punta a punta: `verify_export` recorre la cadena
    interna eslabón por eslabón, así que es el assert que de verdad detecta un intruso.
    """
    from src.licensing import deployment_key, trueup_export
    _client, factory, _marcas, cadena = harness
    monkeypatch.setenv(deployment_key.DEPLOYMENT_KEY_ENV, str(tmp_path / "deployment_key.pem"))
    deployment_key.ensure_deployment_key()

    doc = trueup_export.generate_signed_export(session_factory=factory)

    assert [e["seq"] for e in doc["events"]] == [entry["seq"] for _id, entry in cadena]
    assert doc["counter"] == ESLABONES
    assert doc["range"] == {"from_seq": 1, "to_seq": ESLABONES}
    # No levanta ⇒ firma válida, cadena interna contigua y head coherente con el historial.
    trueup_export.verify_export(doc, deployment_key.public_key_pem())


def test_los_lectores_de_la_cadena_ignoran_las_filas_que_solo_dicen_license(harness):
    """El mismo hecho dicho por fila, para que el assert nombre al disfraz que se coló.

    Los dos tests de arriba miran totales; éste mira el `id` de cada spoof contra lo que la
    cadena adoptó. Si mañana un disfraz nuevo comprara la exclusión, los totales dirían «hay uno
    de más» y esto dice CUÁL.
    """
    _client, factory, marcas, cadena = harness
    from src.models.audit import AuditLog
    db = factory()
    try:
        declaran = {str(f.id) for f in db.query(AuditLog).filter(AuditLog.model == RESERVADO)}
    finally:
        db.close()

    de_la_cadena = {fila_id for fila_id, _ in cadena}
    ajenas = {marcas[m] for m in DISFRAZADAS}
    # Los dos conjuntos comparten el `WHERE model = 'license'` de los lectores ingenuos…
    assert ajenas | de_la_cadena == declaran
    # …y sin embargo ninguna ajena es un eslabón.
    assert ajenas & de_la_cadena == set()
    # Y ninguna ajena se coló en lo que el clasificador protege POR SER CADENA. La expectativa
    # sale del `DATASET`, no de un «is not None» parejo, y ese matiz es el dictamen del 14-ago
    # (punto c): las dos filas de `guardian_events` nulo tampoco se borran, pero NO porque el
    # clasificador las tome por eslabones —no las toma— sino porque su forma no prueba que sean
    # tráfico. Pedirles clase acá sería exigir que la purga borre ante la duda.
    for marca in DISFRAZADAS:
        esperada = _params(marca)[4]
        assert clase_en_memoria(factory, marcas[marca]) == esperada, (
            f"«{marca}» dejó de clasificar como {esperada!r}. Si era una fila con clase y ahora "
            "no la tiene, se volvió inmortal disfrazada de cadena; si era una de las dos formas "
            "nulas y ahora tiene clase, el fail-closed del portón se dio vuelta.")


# ── 4. EL CENTINELA ───────────────────────────────────────────────────────────────────


def test_el_centinela_es_igual_de_mortal_y_de_visible_que_cualquier_fila(harness):
    """La red contra el `LIKE 'license%'` que todavía nadie escribió.

    Hoy pasa por los mismos asserts que el resto (está en `DATASET`), y aun así vive como test
    propio: cuando se ponga rojo, el mensaje tiene que nombrar el motivo. Un lector nuevo que
    excluya por prefijo convierte al centinela —el lugar donde el intento queda VISIBLE— en un
    segundo escondite, estrenado por la defensa. Ojo con el nombre: en LIKE el `_` es comodín de
    un carácter, así que `'license_%'` tampoco sirve para esquivarlo.
    """
    client, factory, marcas, _cadena = harness
    for marca, clase, balde in (("centinela_bloqueo", CLASE_SEGURIDAD, BLOQUEADOS),
                                ("centinela_permitido", CLASE_USO, PERMITIDOS)):
        fila_id = marcas[marca]
        assert clases_que_reclaman(factory, fila_id) == [clase], (
            f"«{marca}»: el centinela dejó de ser mortal. Alguien excluyó por prefijo y la fila "
            "saneada quedó tan inmortal como la que la capa B vino a desalojar.")
        assert fila_id in ids_de_la_vitrina(client, estado=balde), (
            f"«{marca}»: el centinela dejó de ser visible. El intento que la capa B registró a "
            "propósito volvió a desaparecer del reporte.")


def test_el_centinela_no_se_cuela_en_la_cadena_ni_en_el_true_up(harness):
    """Y no es un eslabón, obviamente — pero el `WHERE model = 'license'` de los dos lectores es
    de igualdad exacta y esto es lo que lo clava. Si alguien lo relajara a un prefijo para
    «tener todo junto», el centinela pasaría a envenenar la cadena, que es el daño nº3 servido
    por la puerta de la defensa."""
    _client, factory, marcas, _cadena = harness
    from src.models.audit import AuditLog
    db = factory()
    try:
        declaran = {str(f.id) for f in db.query(AuditLog).filter(AuditLog.model == RESERVADO)}
    finally:
        db.close()
    for marca in ("centinela_bloqueo", "centinela_permitido"):
        assert marcas[marca] not in declaran


# ── Los dos escritores vivos, de punta a punta ────────────────────────────────────────
#
# Todo lo de arriba siembra por DB directa: mide a los LECTORES, que es donde el daño se
# consuma. Lo que sigue cierra el círculo por el otro lado — el pedido HTTP real que un atacante
# manda — y afirma las cuatro propiedades sobre la fila que ESE pedido dejó.
#
# Va acá y no en `test_modelo_reservado_licencia.py` (que mide la capa B: saneo, orden, 422)
# porque lo que se pregunta es distinto: no «qué se escribió» sino «qué le pasa después a lo que
# se escribió», con la cadena legítima viva en la misma tabla.


class _RespuestaFalsa:
    status_code = 200
    headers = {"content-type": "application/json"}
    content = json.dumps({"content": [{"type": "text", "text": "ok"}],
                          "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()

    def json(self):
        return json.loads(self.content)


class _ClienteFalso:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, *_args, **_kwargs):
        return _RespuestaFalsa()


class _HttpxMudo:
    """Doble del `httpx` del gateway: en esta suite no hay proveedor al que llamar.

    Mudo y sin contador a propósito: que el rechazo ocurra ANTES del proveedor ya lo mide
    `test_modelo_reservado_licencia.py` con un espía. Acá el doble sólo existe para que el camino
    feliz no salga a la red — lo que se mide es la fila que quedó."""

    def AsyncClient(self, *_args, **_kwargs):  # noqa: N802 — espeja el nombre real
        return _ClienteFalso()


@pytest.fixture
def escritores(harness, monkeypatch):
    """El gateway apuntado a la base del test y sin proveedor, y el secreto de `/internal`.

    `gateway` abre sus PROPIAS sesiones (ese plano se autentica con el OAuth del cliente, no con
    la sesión del request), así que sin este patch las filas se irían a la base del compose.
    """
    from src.api import gateway
    _client, factory, _marcas, _cadena = harness
    monkeypatch.setattr(gateway, "SessionLocal", factory)
    monkeypatch.setattr(gateway, "httpx", _HttpxMudo())
    monkeypatch.setenv("LITELLM_MASTER_KEY", SECRETO_INTERNO)
    return harness


def filas_nuevas(factory, conocidos):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return [f for f in db.query(AuditLog).all() if str(f.id) not in conocidos]
    finally:
        db.close()


def ids_conocidos(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return {str(fila_id) for (fila_id,) in db.query(AuditLog.id)}
    finally:
        db.close()


def test_el_bloqueo_real_escondido_bajo_el_literal_muere_y_se_ve(escritores):
    """El caso feo del hallazgo, entero y por la puerta real.

    Un pedido que trae material secreto —o sea, un intento que el firewall SÍ impide— declarando
    `model: "license"`. Antes esa fila salía con el literal puesto: inmortal, fuera del balde de
    bloqueados y dentro del universo que relee la cadena. Ahora tiene que quedar con el centinela,
    caer en `security_events`, aparecer entre los bloqueos y no tocar la cadena.
    """
    client, factory, _marcas, cadena = escritores
    from src.licensing.audit_events import verify_chain
    previos = ids_conocidos(factory)

    respuesta = client.post(GW, json={"model": RESERVADO,
                                      "messages": [{"role": "user",
                                                    "content": f"la clave es {SECRETO}"}]})
    assert respuesta.status_code == 400, respuesta.text

    nuevas = filas_nuevas(factory, previos)
    assert len(nuevas) == 1, "el intento tenía que dejar UNA fila durable"
    fila_id, estado = str(nuevas[0].id), nuevas[0].compliance_status
    assert nuevas[0].model == CENTINELA
    assert estado == "blocked_secret"

    assert clases_que_reclaman(factory, fila_id) == [CLASE_SEGURIDAD]
    assert fila_id in ids_de_la_vitrina(client, estado=BLOQUEADOS)
    db = factory()
    try:
        assert verify_chain(db)["checked"] == ESLABONES
    finally:
        db.close()
    assert fila_id not in {eslabon for eslabon, _ in cadena}


def test_ningun_escritor_deja_que_el_cliente_le_ponga_el_seq_a_su_propia_fila(escritores):
    """La pregunta que había que contestar en el fuente y no suponer: **¿puede un cliente
    inyectar `guardian_events`?**

    No, y por construcción en los dos escritores vivos. `/internal/audit` declara su payload en
    `AuditEntry` (`api/internal.py:190-221`) y ahí no existe el campo —el INSERT ni siquiera
    nombra la columna, así que la fila nace con el default `[]` de la 003—; y `/gw` arma la fila
    en `_audit` (`api/gateway.py:933`), que jamás le pasa `guardian_events` al
    `log_transaction` de `:978`. El tercer productor de esa columna es la respuesta del MOTOR,
    que el cliente no escribe.

    Eso es lo que sostiene el ancla entera: si el `seq` fuera declarable desde un body, la capa A
    no serviría de nada — el atacante compraría la exclusión con el mismo pedido con el que
    compraba el literal. Por eso se afirma acá y no se deja en un comentario: el día que alguien
    agregue el campo a `AuditEntry` «para pasar los eventos del motor», este test se pone rojo y
    la conversación ocurre antes del merge y no en el gate siguiente.
    """
    client, factory, _marcas, _cadena = escritores
    from src.services.retention import classifier
    inyectado = [{"seq": 999, "prev_hash": "0" * 64, "event_type": "license_loaded"}]

    for etiqueta, hacer_pedido in (
        ("gw", lambda: client.post(GW, json={
            "model": RESERVADO, "guardian_events": inyectado,
            "messages": [{"role": "user", "content": "hola"}]})),
        ("internal", lambda: client.post(AUDIT_INTERNO, headers=CABECERA_INTERNA, json={
            "model": RESERVADO, "compliance_status": "blocked_prohibited",
            "guardian_events": inyectado, "latency_ms": 3})),
    ):
        previos = ids_conocidos(factory)
        hacer_pedido()
        nuevas = filas_nuevas(factory, previos)
        assert len(nuevas) == 1, f"{etiqueta}: el intento tenía que dejar UNA fila durable"
        fila = nuevas[0]

        assert not fila.guardian_events, (
            f"{etiqueta}: el cliente escribió `guardian_events`. Con eso puede fabricar el `seq` "
            "y comprarse la exclusión de la cadena: el ancla de la capa A deja de ser un hecho "
            "que sólo produce el emisor de la 021.")
        assert fila.model == CENTINELA, f"{etiqueta}: el literal reservado llegó a la columna"
        assert classifier.clase_de(fila) is not None, (
            f"{etiqueta}: la fila quedó sin clase, o sea inmortal")


# ══════════════════════════════════════════════════════════════════════════════════════
# HALLAZGOS ABIERTOS — salieron de escribir este archivo, NO se arreglan acá.
#
# Van en prosa y no como tests rojos por el criterio de la casa: un test que afirma el
# comportamiento defectuoso lo convierte en contrato y se pone rojo el día que alguien lo
# arregla. Lo que sigue está MEDIDO (reproductor incluido), no inferido.
# ══════════════════════════════════════════════════════════════════════════════════════
#
# ── HALLAZGO 1 — parte (a) CERRADA, parte (b) ABIERTA ─────────────────────────────────
#
# **(a) el TERCER escritor de `audit_logs.model` sin sanear: CERRADO.** Cuando este archivo se
# escribió, la capa B sólo cubría `api/gateway.py` y `api/internal.py`, y el plano CHAT escribía
# la misma columna con el `str` libre de `ChatRequest.model` sin pasar por
# `sanear_modelo_declarado`. Reproducido entonces en vivo contra la app real (dos filas durables,
# las dos bloqueos de VERDAD):
#
#     POST /api/v1/chat/completions {"model": "license", "message": "<práctica prohibida>"}
#       → 400 · fila durable model='license' compliance_status='blocked_prohibited'
#     POST /api/v1/chat/completions {"model": "license", "message": "la clave es sk-…"}
#       → 400 · fila durable model='license' compliance_status='blocked_by_policy'
#
# Ya no: `api/chat.py` sanea con `_modelo_auditable` (`chat.py:503`), que reusa la MISMA
# `gateway.sanear_modelo_declarado` y sólo le agrega un `logger.warning` —en `/gw` el intento se
# contesta con 422 y se ve, acá el pedido sigue su curso—. Cubre los seis escritores por dos
# lugares: el helper `_registrar_bloqueo` (`chat.py:582`, que es por donde escriben los CINCO
# rechazos; el saneo, en `:670`) y el camino feliz (`chat.py:1778`, con el porqué desde
# `:1767`). El saneo va en el helper y no en cada call-site a propósito, y está escrito allá:
# el sexto rechazo que alguien agregue no se olvidaría ruidosamente, dejaría una fila que el
# DPO no ve.
#
# **(b) los agregados que excluyen por `model` a mano: SIGUE ABIERTA.** Verificado en la fuente
# el 14-ago: `api/compliance.py:369,379`, `api/reports.py:139` y `api/analytics.py:88,110` siguen
# filtrando `model != 'license'` en vez de consumir la primitiva del clasificador como ya hizo la
# vitrina en T005. Con la parte (a) cerrada ninguna fila NUEVA puede entrar por ahí, así que lo
# que queda vivo es el pasado: una fila vieja con el literal —la base de un cliente ya instalado,
# que la capa B no puede sanear hacia atrás— se sigue borrando del informe ejecutivo del DPO, y
# cada uno de esos cinco lectores es una copia más del criterio que la 018 vino a unificar
# (FR-002 sin terminar). Medido en su momento, con dos filas de esas en la tabla:
#
#     GET /api/v1/compliance/dashboard → audit_stats.total_logs = 0
#     GET /api/v1/reports/executive    → audit.total_transactions = 0
#
# ── HALLAZGO 2 (ALTA como defensa en profundidad): CERRADO ────────────────────────────
# ── los dos lectores de la cadena no validaban la forma de `guardian_events[0]` ───────
#
# **Estado al 14-ago: arreglado, y no por este archivo.** Los dos lectores comparten hoy UN solo
# lector —`audit_events.chained_entries` (`licensing/audit_events.py:130`), que
# `trueup_export.py:31` importa en vez de copiar— y ese lector filtra con la guarda de tipo
# `_is_chain_link` (`audit_events.py:87`): `isinstance(dict)`, las DOS claves (`seq` y
# `prev_hash`) y `seq` entero. La fila deforme se saltea en vez de tumbar la lectura, y sin
# entrar a `issues` —acusar tamper por una fila que el emisor nunca escribió sería el deployment
# acusándose solo—. El escenario completo lo mide
# `tests/integration/test_cadena_filas_deformes.py`.
#
# La tabla de abajo se conserva —y `_is_chain_link` la cita desde el fuente— porque es el
# registro MEDIDO de lo que se arregló, no una descripción del código de hoy. Era así:
# `verify_chain` y la copia `_chained_entries` del export hacían `"seq" in r.guardian_events[0]`
# y después `e["seq"]` / `e["prev_hash"]`, sin mirar de qué tipo era ese primer evento. Con UNA
# fila `model='license'` deforme en la tabla:
#
#   guardian_events        | verify_chain                    | true-up export
#   -----------------------|---------------------------------|---------------------------------
#   ["seq"]                | TypeError (string indices)      | TypeError (string indices)
#   ["consequence"]        | TypeError (string indices)      | TypeError (string indices)
#   [7]                    | TypeError (int no iterable)     | TypeError (int no iterable)
#   [["seq"]]              | TypeError (list indices)        | TypeError (list indices)
#   [{"seq": 1}]           | KeyError: 'prev_hash'           | **adopta la fila** (events +1)
#   [{"seq":1,"prev_hash":"x"}] | acusa TAMPER (ok=False)    | **adopta la fila** (events +1)
#
# El substring es el detalle que lo vuelve barato: `"seq" in "consequence"` es True, así que no
# hace falta ni escribir la clave. Y las dos últimas filas son el hallazgo original COMPLETO,
# los tres daños de una: el clasificador las considera eslabones legítimos (son objetos con
# clave `seq`), o sea inmortales e invisibles, y encima el verificador acusa manipulación
# mientras el export se las lleva puestas — el lado-Basa rechaza ese true-up por «cadena interna
# inválida» y el cliente se queda sin poder demostrar su historial.
#
# Nada de esto era alcanzable desde un pedido, y ESE era el único motivo por el que no se
# arreglaba en el acto: `guardian_events` no es declarable por el cliente en ninguno de los tres
# productores (lo verifica
# `test_ningun_escritor_deja_que_el_cliente_le_ponga_el_seq_a_su_propia_fila`).
# Lo que lo volvió urgente igual es que la capa B no sanea hacia atrás: en la base de un cliente
# ya instalado una sola fila vieja alcanzaba, y la cadena es la evidencia con la que se factura.
# Un lector de evidencia que se cae con una excepción sin capturar en vez de reportar el problema
# es la mitad del incidente que FR-003 vino a evitar.
#
# Lo que la guarda NO cambia, y por eso las dos últimas filas de la tabla siguen importando: una
# fila ajena BIEN FORMADA (objeto con `seq` int y `prev_hash`) sigue siendo adoptada por los dos
# lectores, y el clasificador la sigue tratando como eslabón, o sea inmortal. Es la asimetría
# deliberada que anota `_is_chain_link`: la cadena nunca deja de leer un eslabón que la purga
# protege, al precio de que una fila deforme CON forma de objeto siga sin morir.
#
# ── HALLAZGO 3 (BAJA): el centinela no es un literal reservado ─────────────────────────
#
# `sanear_modelo_declarado` compara por igualdad contra `license`, así que un cliente que declare
# directamente `license__cliente` lo escribe TAL CUAL en la columna. La fila sigue siendo mortal
# y visible —lo cubren los tests del punto 4— y por eso esto es BAJA y no ALTA. Lo que se pierde
# es honestidad del registro: el centinela significa «acá el cliente declaró el literal
# reservado» y ese significado lo puede falsificar cualquiera. Si alguna vez se cuenta o se
# alerta sobre él («cuántos intentos de usurpación hubo»), el número lo escribe el inspeccionado
# — el mismo modo de falla, un piso más abajo.
#
# ── Variantes probadas que NO están vivas (para que nadie las vuelva a buscar) ─────────
#
# * caja y espacios (`License`, `LICENSE`, ` license `, `\tlicense\n`): la capa B normaliza con
#   `strip().casefold()` ANTES de comparar, y la comparación de los lectores es por igualdad
#   exacta, así que la normalización es un superconjunto — todo lo que los lectores llamarían
#   `license` la capa B ya lo desalojó. Sembradas igual en el `DATASET`, porque el clasificador
#   es la última línea para las filas que YA están escritas: la capa B protege el futuro y no
#   sanea hacia atrás la base de un cliente instalado;
# * truncamiento a 128 (`internal.py:289`): el saneo corre ANTES del recorte y el recorte sólo
#   puede devolver `license` si el string ya era exactamente `license`, que es el caso que el
#   saneo agarra. No hay orden de esas dos operaciones que fabrique el literal;
# * `guardian_events` con un `seq` fabricado por el cliente: no hay campo por donde entre (ver
#   HALLAZGO 2 y el test que lo clava).
