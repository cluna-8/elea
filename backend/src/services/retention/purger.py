"""Purgador: el proceso que efectivamente borra lo vencido (spec 018, FR-001/004/005).

⚠ ESTADO (US1, PR de purga real), escrito para que nadie lea de más:

* **implementado acá**: la corrida por clase (cutoff contra el reloj de la DB, `DELETE` por
  lotes dentro de la ventana), el simulacro, el **contador de residuo**
  (`filas_no_clasificadas`, dictamen del manager del 14-ago punto (c)) — todo T008 —, y ahora
  las tres cosas que faltaban: **T009** (`human_reviews.response_text` → NULL al purgar
  `prompt_content`, FR-004), **T010** (rastro auditable: entrada en `purge_log` por clase + fila
  resumen `config_audit` por corrida, FR-005) y el **entrypoint de CLI** (`--run-now`, FR-001).
  Los puntos **1, 2 y 3** de «Las tres cosas que hace una corrida», acá abajo, describen ahora
  lo que este archivo HACE, no sólo su contrato. La forma del rastro no se inventó: sale de
  `ResultadoCorrida`/`ResultadoPurga`, que ya la fijaban.

El scheduler que lo despierta (`services/retention_scheduler.py`, T011) sigue siendo un
esqueleto: en producción nadie invoca esto por sí solo todavía, pero el purgador ya es invocable
a mano por CLI (`python -m src.services.retention.purger --run-now`, ver el `__main__` al pie).

## Las tres cosas que hace una corrida

1. **Borra las filas vencidas de `audit_logs`** de cada clase del clasificador: edad medida
   contra el **reloj de la DB** (no el del proceso — con varios workers y contenedores, el
   único reloj que no discute consigo mismo es el del servidor), `DELETE` por lotes de
   `BASA_PURGE_BATCH_SIZE` con una pausa de `BASA_PURGE_BATCH_PAUSE_MS` entre lote y lote.
2. **Mata el único texto real durable** (FR-004): al purgar `prompt_content`,
   `human_reviews.response_text` de las revisiones vencidas pasa a `NULL`. La fila de
   revisión PERSISTE — el DPO tiene que poder demostrar que la revisión ocurrió; lo que
   muere es el contenido. Sin esto, «purga al día 91» no borra el único texto que de verdad
   existe en la caja (`models/compliance.py:84`).
3. **Deja rastro auditable** (FR-005): entrada en el `purge_log` JSONB de la clase (que la
   004 dejó preparado y nadie escribía nunca) + una fila resumen de clase `config_audit` en
   `audit_logs`. Todo metadata-only: conteos, rangos, duración. JAMÁS contenido — el rastro
   de una purga no puede reintroducir lo que la purga vino a borrar (Security Constraint 1).

## Por qué lotes y ventana, y no un DELETE y listo

`audit_logs` es la tabla más caliente del producto: sin particiones, con cuatro índices y
con la vitrina, analytics, costes y el export leyendo encima. La primera corrida de una
instalación con meses de datos puede tener un backlog enorme; un DELETE único de millones de
filas se toma locks y bloat por un rato largo y le tumba la pantalla al officer. Se converge
por lotes con pausa (cede la tabla a los lectores calientes) y solo dentro de la ventana
horaria. Criterio verificable: SC-003 — con la purga corriendo y backlog real, los 4 SLOs de
oro del examen de carga siguen verdes. Un purgador glotón reprueba el examen del ciclo 250.

## Identidad bajo RLS (Contrato 2, FR-006)

Todo trabajo de este módulo va dentro de `with tenant_context(None, bypass=True):`
(`database.py`). **Prohibido `SessionLocal()` pelado**: hoy funciona sólo porque la policy
permisiva `tenant_isolation_bootstrap` de la 010 sigue viva; cuando la 017 la elimine, un job
sin identidad declarada pasa de borrar a NO VER FILAS — retención que aparenta estar
enforced sin estarlo, el peor modo de falla posible para esta spec.

Y la regla que hace que ese `with` alcance, porque no es la que parece: **la sesión se abre y
se cierra DENTRO del bloque; este módulo recibe `session_factory` y JAMÁS una `Session` ya
viva.** El bypass no muere con el `with`, muere con la TRANSACCIÓN. El listener de
`database.py:44-61` inyecta `set_config('app.bypass_rls', 'on', true)` en `after_begin`, y ese
tercer argumento es `is_local`: o sea `SET LOCAL`, que vive hasta el commit/rollback y no
hasta que el context manager salga. Lo que sale del `with` son los ContextVar (por eso el
bypass no queda de default de sesión, y eso sí está testeado); el GUC ya inyectado se queda
puesto en la transacción abierta. Una sesión creada AFUERA que dispare su primera consulta
ADENTRO abre su transacción adentro y se lleva el bypass a TODO lo que haga después, ya fuera
del bloque — un bypass de RLS que escapa su alcance, en el proceso que además hace `DELETE`.
Pedir una factory no lo vuelve imposible (nada impide un `lambda: db_ya_viva`), lo vuelve
VISIBLE: el camino natural es abrir adentro, y colar una sesión viva hay que escribirlo a
propósito y se ve en el diff.

Precedente vivo del patrón: `licensing/audit_events.py::emit_state_event`, que crea Y cierra
su sesión dentro del bloque.

## Idempotencia

No hay estado de corrida persistido ni cursor: el predicado es «vencida AHORA» contra el
reloj de la DB. Una corrida interrumpida que se relanza no duplica efecto (lo borrado ya no
está) ni saltea filas (lo vencido sigue vencido). La interrumpida queda registrada con
`result: partial` — el auditor ve que se cortó, no un hueco inexplicable.

## Simulacro (`BASA_PURGE_DRY_RUN`, default `true`)

En simulacro la corrida hace TODO menos borrar: resuelve el cutoff de cada clase, CUENTA las
filas que caerían y escribe el rastro igual, con `dry_run: true`. Nada se elimina, ni en
`audit_logs` ni en `human_reviews.response_text`.

Por qué es el default y no un modo de debug: la primera corrida real de una instalación no
tiene backlog de un día, tiene el de toda la vida de la caja, y lo borrado no vuelve. El
simulacro es lo que le permite al DPO ver el número —«se van 412.000 filas de esta clase, con
este cutoff»— y FIRMAR antes de que pase. Encender la purga y descubrir el alcance por el
rastro de lo ya borrado es exactamente el orden inverso.

Un simulacro es también lo único honesto que se puede correr fuera de la ventana o en horario
de oficina: no toma locks de escritura, así que se puede pedir a mano el día que el officer
pregunta cuánto se iría, sin esperar a las 02:00.

## El piso del plazo: DEFENSA DUPLICADA a propósito (dictamen del manager, 14-ago)

**«El endpoint valida para dar buen error, el purgador valida para no destruir» (dictamen del
manager, 14-ago, textual).** La validación de rangos de `PUT /api/v1/compliance/retention` es
FR-007 (T015, US2) y llega después; ésta es la segunda red, y va a seguir existiendo cuando
aquélla entre, porque la defensa va en el PUNTO DE DESTRUCCIÓN y no sólo en la puerta.

Qué hay MEDIDO hoy, que es lo que la hace algo más que una precaución teórica (14-ago, contra la
app real y el Postgres del compose):

* `PUT /api/v1/compliance/retention` con `retention_days: 0` y con `-30` devuelve **HTTP 200** y
  los persiste, en toda clase que no sea `config_audit`. `RetentionPolicySchema.retention_days`
  es un `int` pelado sin `ge=` (`api/compliance.py:107`) y la única validación de rango del PUT
  es `config_audit >= 365` (`api/compliance.py:334`, que sí contesta 422). O sea que la tabla de
  la que este módulo lee acepta hoy plazos que no definen ninguna frontera;
* sin este piso, una corrida real con la política en 0 —y también con `-30`— resuelve
  `cutoff = AHORA` (reloj de la DB) y **borra una fila escrita ESE MISMO DÍA**. Medido acá
  quitando el chequeo y corriendo
  `test_retention_piso_plazo.py::test_un_plazo_no_positivo_no_borra_ni_una_fila`, que muere
  justo en el assert de la fila de hoy.

Un plazo de cero días no significa «purgá todo lo vencido»: significa «todo está vencido».

La regla, entonces: un `retention_days` por debajo de `PLAZO_MINIMO_DIAS` se rechaza ANTES de
restar el cutoff y antes de que ninguna consulta toque `audit_logs`. El único punto por el que
pasa el plazo de una clase es `_plazo_en_dias`, y ahí vive el chequeo — uno solo, en el paso
obligado, en vez de repartido por las ramas.

### Aborta la CLASE, no la corrida entera

Un plazo inválido es un hecho DE UNA CLASE: vive en su fila de `retention_policies` (`log_type`
es UNIQUE) y el cutoff de las otras tres sale de sus propias filas. Seguir con ellas no es
«purgar con un plazo inválido», es purgar con los tres plazos válidos que quedan.

Desde el operador, que es como pidió pensarlo el dictamen: una clase mal configurada de cuatro.
Abortando sólo ésa, no se destruye ni una fila de la clase rota (el lado reversible), las otras
tres siguen enforced, y corregir el número y volver a correr repara exactamente lo que estaba
roto — la corrida es idempotente y no hay cursor que reponer (§Idempotencia). Abortando la
corrida entera, un número mal tecleado apaga la retención de TODO el producto en un job que
corre de madrugada y sin nadie mirando: se cambia un fallo acotado y ruidoso por una
no-conformidad ancha del Art. 5.1.e — la que esta spec vino a cerrar — y no se protege nada a
cambio, porque sobre las otras tres clases no hay ninguna duda.

Además es el contrato que este módulo YA tenía y no uno nuevo: `run_once` declara que una clase
que falla no cancela a las demás, y `_plazo_en_dias` ya levanta `LookupError` cuando la clase no
tiene fila. «Plazo inválido» es de la misma familia que «clase sin plazo»: no hay frontera
creíble para ESA clase. Cómo se ve en el rastro: `result: error`, `cutoff: None` (que significa
exactamente «se cayó antes de resolver la frontera», ver `ResultadoPurga`) y `rows_deleted: 0`.
Llamada suelta a `purgar_clase` —la operación manual— la excepción sale en la cara del operador.

### Vale también para el simulacro

Sí, y por dos motivos; el segundo es el que lo cierra:

1. **el simulacro es lo que el DPO FIRMA.** Un ensayo con la política en 0 no reportaría un
   número conservador: reportaría el conteo bajo `cutoff = AHORA`, o sea la clase entera, y con
   `result: ok` al lado. Le hace firmar un número inventado, que es el modo de falla que el
   simulacro existe para evitar;
2. **el simulacro tiene que ser la MISMA corrida menos el `DELETE`.** Si validara distinto que
   la real dejaría de predecirla, y un ensayo verde seguido de una corrida roja es el peor
   resultado posible para lo único que existe para anticipar la corrida.

Estructuralmente sale gratis, y no por casualidad: el chequeo está antes de la bifurcación
—`_plazo_en_dias` se llama para calcular el `cutoff`, y las dos ramas cuelgan de ese `cutoff`—,
así que no hay forma de agregar un camino nuevo que se lo saltee sin quitarle también el cutoff.

El contador de residuo tiene el mismo problema por el mismo motivo y se trata igual, en
`cutoff_de_residuo`: un umbral inválido convertiría el residuo en «la tabla entera».

### Por qué el piso es `> 0` y no un mínimo por clase

Buscado en la fuente el 14-ago, no en la memoria:

* `classifier.py` no define ningún mínimo, y no por olvido: lo dice él mismo —«este módulo mapea
  filas → clase; no lee plazos ni decide vencimientos» (`classifier.py:57-58`)—. Lo único que
  tiene es una tabla de plazos POR DEFECTO en su docstring (`:47-54`), que son los del seed y no
  pisos;
* el **seed 004** crea la tabla SIN CHECK. Medido contra el Postgres del compose,
  `retention_policies` tiene exactamente tres constraints —PK, `UNIQUE (log_type)` y la FK de
  tenant— y ninguna de rango (`pg_constraint`, 14-ago). El único «mínimo» que aporta el seed es
  PROSA dentro del `justification` de `config_audit` («No reducible por debajo de 365 días»,
  `alembic/versions/004_compliance_tables.py:107`), y esa columna la pisa cualquier PUT
  (`api/compliance.py:337`): medido el 14-ago, un PUT que no manda `justification` la deja en
  `null`. Es un texto editable por el operador, no un mínimo legible por código;
* el único mínimo por clase EN VIGOR hoy es el `config_audit >= 365` del endpoint
  (`api/compliance.py:334`), que es de FR-007/T015 y no de este archivo;
* la tabla de mínimos por clase y por tier existe, pero en el PLAN: `research.md` §D7 «Pisos/
  topes por tier», rotulada «defaults del plan, ajustables en tasks», y cuelga de
  `enforcement_tier_estricto`, que el 14-ago no aparece en ninguna línea de `backend/` ni de
  `frontend/`. Sin tier resuelto no hay mínimo por clase que leer.

Así que el piso de este módulo es `> 0` y se dice en voz alta. Como la columna es `INTEGER NOT
NULL` (`004_compliance_tables.py:92`, `models/compliance.py:96`), «mayor que cero» se escribe
`>= 1`: `PLAZO_MINIMO_DIAS = 1`. Es el menor plazo con el que el cutoff cae en el PASADO, que es
la única propiedad que este módulo necesita para no borrar el presente.

No se copia el 365 acá: sería una segunda definición de un número que pertenece a FR-007 y que
allá depende del tier (365 estándar / 730 estricto), o sea que nacería con fecha de vencimiento.
Cuando T015 traiga los mínimos por clase, este piso sigue siendo el SUELO —el que no depende de
ninguna política ni de ningún tier— y el de la clase se apila encima.

## El residuo: `filas_no_clasificadas` (dictamen del manager, 14-ago, punto c)

El clasificador es fail-closed: una fila cuyo `guardian_events` no prueba que sea tráfico
—NULL de SQL, el `'null'::jsonb`, un jsonb que no es lista, un primer evento que no es un
objeto— **no la reclama ninguna clase**, así que ningún `WHERE` de esta corrida la levanta y no
se borra. Eso está decidido y no se discute acá: entre borrar de más y borrar de menos, el
default del depto va del lado reversible, porque del otro lado de la duda puede haber un
eslabón de la cadena de licencias en un estado que este código no reconoce.

Lo que sí se paga acá es la otra mitad del problema, que era el «y nadie se entera»: **la
corrida CUENTA ese residuo y lo dice**, en el resultado y en el log. Y lo dice también en el
simulacro — «el officer que ensaya la purga tiene que ver el residuo ANTES de apretar el
botón» (dictamen, textual). Un contador que sólo apareciera en la corrida real le mostraría el
número a quien ya borró.

Qué cuenta exactamente, porque «no clasificada» a secas contaría dos cosas distintas:

1. **vencida** — más vieja que el cutoff MÁS ANTIGUO de las políticas vigentes (o sea
   `reloj_db - max(retention_days)`, hoy los 730 d de `config_audit`). Una fila que ninguna
   clase reclama tampoco tiene plazo propio, así que el único umbral que no admite discusión es
   el que la deja vencida bajo TODAS las políticas a la vez. El número es por eso un PISO: una
   fila deforme de 400 días existe y no se cuenta todavía. Se elige el piso a propósito —
   «estas filas están vencidas mires la política que mires» es una afirmación que el officer
   puede llevar a un auditor; «vencidas bajo alguna» no;
2. **que ninguna clase reclama** — `NOT (predicado(c1) OR … OR predicado(c4))`, armado con
   `classifier.predicado()` y nada más. No hay una segunda definición de las clases acá: si el
   clasificador cambia, el residuo lo sigue solo;
3. **y cuyo `guardian_events` no es inspeccionable**. Esta tercera condición es la que separa
   la DUDA de la exclusión POR DISEÑO. Los eslabones de la cadena de licencias tampoco los
   reclama ninguna clase, pero no son residuo: son la exclusión permanente de FR-003, están
   bien formados y el purgador sabe perfectamente por qué no los toca. Contarlos junto a las
   filas deformes convertiría el contador en «todo lo que la purga no se llevó» y, en una caja
   con dos años de cadena, el officer leería un número grande que no le señala ningún problema.
   Lo que se cuenta es lo que el purgador NO PUDO decidir.

La tercera condición es una pregunta distinta de la del clasificador —«¿esta fila es
inspeccionable?» vs. «¿es demostrablemente tráfico?»— y por eso se escribe acá y no se importa
de allá: `classifier.py` no expone hoy ninguna primitiva que la conteste, y no es de este
agente en esta ronda. Es estructural (mira la FORMA del jsonb, jamás `model`), o sea que no
reintroduce por la puerta del contador el literal que el dictamen sacó del portón. Si algún día
aparece un segundo consumidor, el lugar donde vive es `classifier.py`, con las otras primitivas.
"""
import logging
import math
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import DateTime, and_, case, cast, false, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.elements import ColumnElement

from ...database import SessionLocal, tenant_context
from ...models.audit import AuditLog
from ...models.compliance import HumanReview, RetentionPolicy
from ...models.tenant import DEFAULT_TENANT_ID
from ..audit_service import AuditService
from . import classifier

if TYPE_CHECKING:  # sólo para el anotado: el job batch no importa el ORM para leer su firma
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Lo que este módulo acepta para hablar con la base: una FÁBRICA de sesiones, nunca una
# `Session` ya viva. El alias existe para que la regla del docstring («la sesión se abre y se
# cierra dentro del bloque») esté también en la firma y no sólo en prosa: con una factory, la
# transacción —y el `SET LOCAL` del bypass que viaja con ella— nace y muere adentro del
# `tenant_context`. Es una anotación, no un candado; el candado es la revisión.
FabricaDeSesiones = Callable[[], "Session"]

# ── Perillas de FR-001 (tabla del plan; declaradas en `.env.example` y cableadas en los dos
# composes). Los nombres viven UNA sola vez acá: el purgador, el scheduler y los tests las
# leen de estas constantes, no de literales repartidos. Los defaults son los del plan y son
# los que la doc del producto promete — cambiarlos es cambiar el contrato publicado.
ENV_WINDOW = "BASA_PURGE_WINDOW"
ENV_WINDOW_TZ = "BASA_PURGE_WINDOW_TZ"
ENV_BATCH_SIZE = "BASA_PURGE_BATCH_SIZE"
ENV_BATCH_PAUSE_MS = "BASA_PURGE_BATCH_PAUSE_MS"

DEFAULT_WINDOW = "02:00-05:00"
DEFAULT_WINDOW_TZ = "Europe/Madrid"
DEFAULT_BATCH_SIZE = 5000
DEFAULT_BATCH_PAUSE_MS = 200

# La séptima perilla, y la única que NO viene de la tabla sellada del plan: entró el 13-ago,
# a tiempo porque los nombres de este bloque todavía no estaban publicados en la doc del
# cliente. Se paga ahora justamente por eso — agregarla después de publicar ya no es agregar
# una perilla, es cambiar el contrato de configuración de las instalaciones que existan.
# El default `true` es la mitad de la red de H7: la otra mitad es `BASA_PURGE_ENABLED=false`
# en `.env.example` y en los dos composes. Juntas, la primera imagen con purgador dentro no
# borra nada de nadie: hay que encenderla A MANO y, aun encendida, la primera corrida cuenta
# antes de borrar. Ninguna de las dos alcanza sola.
ENV_DRY_RUN = "BASA_PURGE_DRY_RUN"
DEFAULT_DRY_RUN = True

# Resultado de una corrida, tal cual viaja al `purge_log` (data-model.md §Corrida de purga).
# En simulacro significan lo mismo pero sobre el CONTEO, no sobre el borrado: `ok` es «terminé
# de contar todo el backlog vencido». Leerlo como «al día» en una corrida con `dry_run: true` es
# leer mal — ahí no quedó al día nada, justamente porque no se borró. `partial` NO aparece en
# simulacro, y eso es una consecuencia del cuerpo y no una promesa: el conteo es UNA consulta
# agregada, así que no hay lotes entre los que la ventana pueda cerrarse.
RESULTADO_OK = "ok"           # la clase quedó al día: no queda nada vencido
RESULTADO_PARCIAL = "partial"  # se acabó la ventana (o se cortó) con backlog pendiente
RESULTADO_ERROR = "error"      # la corrida falló; el rastro queda igual, con el motivo

# ── El rastro auditable (FR-005/T010): dos representaciones, las dos metadata-only ────
# El `purge_log` JSONB de cada clase se capa a las ÚLTIMAS 50 corridas por clase (data-model.md
# §«Corrida de purga»): sin tope, el registro de una instalación vieja crece sin límite dentro
# de una fila.
PURGE_LOG_MAX = 50

# La fila resumen POR CORRIDA vive en `audit_logs` como clase `config_audit` (730 d). Para que
# el clasificador la mande a esa clase su `compliance_status` DEBE empezar con `config_change`
# —igual que el único emisor de configuración que ya existe (`api/guardians.py:334`,
# `config_change_nlp_fail_mode`)—; con cualquier otro literal caería en `usage_metadata` y
# moriría a los 365 d (classifier.py, «Nota para T010/T017»). El `model` NO es `license`, así
# que el lector único de la cadena (`chained_entries`) jamás la relee.
COMPLIANCE_RESUMEN_PURGA = "config_change_retention_purge"
RESUMEN_KIND = "retention_purge_summary"  # marca del blob: no es un evento de guardián


@dataclass(frozen=True)
class ResultadoPurga:
    """Lo que una corrida deja escrito de sí misma — metadata-only, sin excepción.

    Es a la vez la entrada del `purge_log` JSONB (capado a las últimas 50 corridas por clase,
    para que el registro no crezca sin límite) y el cuerpo de la fila resumen `config_audit`.
    Con estos campos un auditor reconstruye QUÉ se borró y CUÁNDO sin acceso a la DB, que es
    exactamente lo que pide SC-002.

    `cutoff` es la frontera de edad que se aplicó (todo lo anterior murió); `rows_deleted` y
    `batches` cuentan; `window` deja escrito bajo qué ventana se corrió. Ningún campo lleva
    contenido de prompt, valor detectado ni identificador de sujeto.

    `dry_run` dice si esto fue un simulacro, y es lo que le da sentido a `rows_deleted`: en
    simulacro ese número es lo que se HABRÍA borrado y en la tabla no cambió nada. Sin el
    campo, las dos corridas dejan un rastro idéntico y el registro pasa a afirmar borrados que
    nunca ocurrieron — un rastro de purga que miente sobre si purgó es peor que no tenerlo,
    porque es el papel con el que el DPO responde una reclamación.

    Va SIN default a propósito: que sea obligatorio obliga a cada sitio que construya un
    resultado a decir en qué modo corrió. Un default (cualquiera de los dos) es la puerta para
    que una rama nueva olvide setearlo y quede clasificada en el modo equivocado en silencio.

    `cutoff` es `Optional` desde el 14-ago, y el `None` tiene un solo significado: la corrida de
    esa clase se cayó ANTES de resolver la frontera (típico: la clase no tiene fila en
    `retention_policies`). Escribir ahí una fecha inventada —el `started_at`, por ejemplo— sería
    dejar en el rastro una frontera que nunca se aplicó, y el rastro es el papel con el que el
    DPO contesta una reclamación. Con `result: error` al lado, `None` se lee sin ambigüedad.
    """

    run_id: str
    clase: str
    started_at: datetime
    finished_at: Optional[datetime]
    cutoff: Optional[datetime]
    rows_deleted: int
    batches: int
    window: str
    result: str
    dry_run: bool


@dataclass(frozen=True)
class ResultadoCorrida:
    """El rastro de la CORRIDA ENTERA: las clases más lo que no es de ninguna clase.

    Existe por el contador de residuo del dictamen del 14-ago (punto c). Un residuo no tiene
    clase —esa es literalmente su definición— así que el número no cabe en `ResultadoPurga`:
    repetido en las cuatro entradas invita a que alguien lo sume por clase y reporte cuatro
    veces las mismas filas; atribuido a una sola, miente sobre a qué clase pertenecen. Y la
    forma de la entrada de `purge_log` que fija `data-model.md` §«Corrida de purga» es POR
    CLASE: dejarla intacta y poner el contador en el nivel que le corresponde es lo que permite
    respetar ese contrato y agregar el campo sin tocarlo *(campo agregado sobre el contrato
    sellado, anotado acá como pide el encargo)*.

    Dónde va a parar cuando T010 escriba el rastro: la fila resumen `config_audit` es POR
    CORRIDA (tasks.md T010), así que es el hogar natural de `filas_no_clasificadas`; las
    entradas de `purge_log` siguen siendo por clase y con sus campos de siempre.

    `filas_no_clasificadas` es `Optional[int]` y el `None` NO es lo mismo que el `0`: `0` es
    «conté y no hay residuo», `None` es «no lo pude contar» (la corrida falló antes, o no hay
    políticas de las que sacar el umbral). Reportar `0` cuando no se contó sería exactamente el
    «nadie se entera» que el contador vino a cerrar, con el agravante de estar firmado.

    `cutoff_no_clasificadas` viaja al lado del número porque sin él el número no significa
    nada: es el umbral bajo el que se contó (ver §«El residuo» del módulo).

    `revisiones_residuo_fr004` (#215) es el residuo GEMELO del lado `human_reviews`: filas cuyo
    `created_at` es NULL o no es un timestamp válido (`pg_input_is_valid`, #232 — forma de
    fecha NO alcanza, ver §«Residuo de FR-004»), así que el purgador de FR-004 nunca puede
    decidir si su `response_text` venció. Mismo contrato `Optional[int]` que
    `filas_no_clasificadas` (`None`="no se pudo contar", `0`="conté y no hay") pero SIN cutoff
    propio — no depende de la edad, ver §«Residuo de FR-004» en el módulo — y, a propósito, NO
    viaja en la fila resumen `config_audit`: esa forma la sella `data-model.md` con enmiendas
    explícitas del manager y #215 no trae una (ver el mismo §).
    """

    run_id: str
    started_at: datetime
    finished_at: datetime
    dry_run: bool
    clases: Tuple[ResultadoPurga, ...]
    filas_no_clasificadas: Optional[int]
    cutoff_no_clasificadas: Optional[datetime]
    revisiones_residuo_fr004: Optional[int]


def _entero_de_env(nombre: str, default: int, minimo: int = 1) -> int:
    """Perilla entera del entorno, con el mismo criterio que las de admisión: un valor malo
    GRITA y se usa el default, en vez de tumbar el job o de aplicar un cero silencioso.

    El precedente es `services/engine_gate.py:84` (`_env_int`), que warnea y cae al default
    tanto por «no es un entero» como por «fuera de rango» — mismo criterio y hasta el mismo
    nombre de parámetro para el piso.

    `minimo` es 1 para el tamaño de lote (un lote de cero filas es un bucle que no avanza) y 0
    para la pausa, donde «sin pausa» es una configuración legítima de una caja chica y no un
    error: sin ese 0, la única forma de pedir «sin pausa» sería un valor inválido que cae en los
    200 ms del default, o sea lo contrario de lo que se pidió.
    """
    crudo = os.getenv(nombre, "")
    if not crudo.strip():
        return default
    try:
        valor = int(crudo)
    except ValueError:
        logger.warning("purga: %s=%r inválido, uso el default %s", nombre, crudo, default)
        return default
    if valor < minimo:
        logger.warning("purga: %s=%r por debajo del mínimo %s, uso el default %s",
                       nombre, crudo, minimo, default)
        return default
    return valor


def _dry_run_de_env() -> bool:
    """`BASA_PURGE_DRY_RUN`. Cualquier cosa que no sea un «no» explícito es simulacro.

    La asimetría es deliberada y es la mitad de la red de H7: un typo (`fasle`, `flase`, `nope`)
    deja la corrida en SIMULACRO, que es el lado que no borra. Lo que apaga el simulacro es
    `false`/`0`/`no`/`off`, y el `.env.example` y los dos composes escriben `true`/`false`.

    Esto se aparta a propósito del giro más común del producto —`os.getenv(X, "…").lower() ==
    "true"` (`main.py:131`, `services/optimization_service.py:34`, `api/chat.py:82`)—, y el
    motivo es que con esa forma el valor seguro depende de cómo se llame la perilla. Acá la
    perilla se llama en positivo (`DRY_RUN=true` es «no borres»), así que un `== "true"` haría
    que CUALQUIER valor raro —incluido un `1`, que en el resto del producto significa «sí»—
    apagara el simulacro y encendiera un `DELETE` retroactivo. El que decide el lado seguro es
    el significado de la perilla, no la costumbre de la casa.
    """
    crudo = os.getenv(ENV_DRY_RUN, "")
    if not crudo.strip():
        return DEFAULT_DRY_RUN
    return crudo.strip().casefold() not in {"false", "0", "no", "off"}


def _hhmm(texto: str) -> Optional[Tuple[int, int]]:
    """`HH:MM` → (hora, minuto), o `None` si no lo es."""
    partes = texto.strip().split(":")
    if len(partes) != 2:
        return None
    try:
        hora, minuto = int(partes[0]), int(partes[1])
    except ValueError:
        return None
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        return None
    return hora, minuto


def _parsear_ventana(ventana: str) -> Optional[Tuple[int, int]]:
    """`HH:MM-HH:MM` → (minuto_inicio, minuto_fin) del día, o `None` si es inválida.

    Una ventana con inicio == fin se rechaza como inválida a propósito: no hay forma de leerla
    sin adivinar («nunca» o «siempre»), y las dos lecturas son caras — una apaga la retención en
    silencio y la otra deja al purgador corriendo a las 11 de la mañana contra la tabla más
    caliente del producto.
    """
    if ventana.count("-") != 1:
        return None
    crudo_inicio, crudo_fin = ventana.split("-")
    inicio, fin = _hhmm(crudo_inicio), _hhmm(crudo_fin)
    if inicio is None or fin is None:
        return None
    minutos_inicio = inicio[0] * 60 + inicio[1]
    minutos_fin = fin[0] * 60 + fin[1]
    if minutos_inicio == minutos_fin:
        return None
    return minutos_inicio, minutos_fin


def en_ventana(ahora: datetime, ventana: Optional[str] = None,
               tz: Optional[str] = None) -> bool:
    """¿Se puede purgar en este instante?

    `ventana` es `HH:MM-HH:MM` en la hora local de la instalación (`BASA_PURGE_WINDOW_TZ`),
    no en la del contenedor: el proceso corre en UTC y «las 02:00» de un operador de Madrid
    no son las 02:00 del contenedor. Una ventana que cruza medianoche (`23:00-02:00`) es
    válida y hay que soportarla — es la forma natural de decir «de madrugada».

    Un valor malformado no tumba el arranque: se loguea warning y se usa el default, con el
    mismo criterio que las perillas de admisión (`services/engine_gate.py`). Una purga que no
    corre por un typo es preferible a un backend que no levanta, pero tiene que GRITARLO.

    `ahora` sin tzinfo se interpreta como **UTC**, que es lo que el purgador le pasa (el reloj
    de la DB leído como `timezone('utc', now())`, verificado contra el Postgres 16 del compose:
    devuelve `timestamp without time zone` en UTC). Un `datetime` con tzinfo se convierte.

    El intervalo es semiabierto `[inicio, fin)`: así dos ventanas contiguas (`23:00-02:00` y
    `02:00-05:00`) no se solapan en el minuto de la juntura.
    """
    crudo_ventana = ventana if ventana is not None else os.getenv(ENV_WINDOW, "")
    crudo_ventana = crudo_ventana.strip() or DEFAULT_WINDOW
    limites = _parsear_ventana(crudo_ventana)
    if limites is None:
        logger.warning("purga: %s=%r inválida, uso el default %r",
                       ENV_WINDOW, crudo_ventana, DEFAULT_WINDOW)
        limites = _parsear_ventana(DEFAULT_WINDOW)

    crudo_tz = tz if tz is not None else os.getenv(ENV_WINDOW_TZ, "")
    crudo_tz = crudo_tz.strip() or DEFAULT_WINDOW_TZ
    try:
        zona = ZoneInfo(crudo_tz)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("purga: %s=%r desconocida, uso el default %r",
                       ENV_WINDOW_TZ, crudo_tz, DEFAULT_WINDOW_TZ)
        zona = ZoneInfo(DEFAULT_WINDOW_TZ)

    if ahora.tzinfo is None:
        ahora = ahora.replace(tzinfo=ZoneInfo("UTC"))
    local = ahora.astimezone(zona)
    minutos = local.hour * 60 + local.minute

    inicio, fin = limites
    if inicio < fin:
        return inicio <= minutos < fin
    # Ventana que cruza medianoche: es la unión de [inicio, 24:00) y [00:00, fin).
    return minutos >= inicio or minutos < fin


def _reloj_db(db: "Session") -> datetime:
    """El reloj de la DB como `datetime` naive en UTC — el ÚNICO reloj de esta corrida.

    Naive-en-UTC y no aware por una razón de tipos, no de gusto: `audit_logs.timestamp` es
    `TIMESTAMP WITHOUT TIME ZONE` y lo escriben `datetime.utcnow()` de varios procesos. El
    cutoff tiene que ser comparable con esa columna sin que Postgres tenga que adivinar una
    zona, y `timezone('utc', now())` devuelve exactamente eso (medido contra el Postgres 16 del
    compose: `pg_typeof` = `timestamp without time zone`, valor en UTC).

    Por qué el de la DB y no `datetime.utcnow()`: con varios workers y contenedores, el único
    reloj que no discute consigo mismo es el del servidor (§Identidad/idempotencia del módulo).
    """
    return db.execute(select(func.timezone("UTC", func.now()))).scalar_one()


# ── El piso del plazo: la segunda red (dictamen 14-ago) ───────────────────────────────
#
# El porqué completo está en §«El piso del plazo» del docstring del módulo. Acá, lo mínimo:
# el purgador NO acepta un plazo que ponga el cutoff en el presente o en el futuro, venga por
# donde venga. Hoy viene por el PUT, que contesta 200 a 0 y a -30 en toda clase que no sea
# `config_audit` (`api/compliance.py:107,334`; medido el 14-ago); mañana puede venir por la
# fuente de la 036. La defensa va en el punto de destrucción.

PLAZO_MINIMO_DIAS = 1
"""El menor plazo con el que el cutoff cae en el PASADO. `retention_days` es `INTEGER NOT NULL`
(`004_compliance_tables.py:92`), así que «mayor que cero» se escribe `>= 1`. No es un mínimo por
clase: hoy no hay ninguno legible por código (ver §«Por qué el piso es `> 0`»)."""


class PlazoDeRetencionInvalido(ValueError):
    """El plazo configurado no sirve para calcular una frontera de edad, así que no se borra.

    Existe como clase propia —y no como un `ValueError` pelado— por dos razones prácticas:
    el nombre aparece en el traceback que deja `run_once`, que hoy es medio rastro de la corrida
    (T010 todavía no escribe el `purge_log`); y le da a T015 y a los tests una forma de
    distinguir «plazo fuera de rango» de cualquier otro `ValueError` del camino. Hereda de
    `ValueError` para no romper a quien ya lo capture así (`classifier.predicado` levanta
    `ValueError` para una clase inexistente en la misma llamada).
    """


def _plazo_en_dias(db: "Session", clase: str) -> int:
    """Días de retención vigentes para `clase`, de `retention_policies` (fuente 013/004).

    Una clase sin fila es un error, no un caso de negocio: el seed 004 las crea las cuatro y
    `log_type` es UNIQUE global. Devolver un default acá sería inventarle un plazo al dato de un
    cliente; devolver «cero filas» dejaría la purga aparentando correr. Levanta y la corrida
    registra esa clase en `error`.

    Y acá vive el PISO (§«El piso del plazo» del módulo): un plazo `<= 0` levanta
    `PlazoDeRetencionInvalido` y esa clase aborta sin borrar ni contar nada. Es el paso obligado
    —el único punto por el que pasa el plazo de una clase— y está antes de que el llamador reste
    el cutoff y antes de que ninguna consulta toque `audit_logs`: con la política en 0, el cutoff
    sería AHORA y el `DELETE` se llevaría filas escritas hoy (medido por el gate adversarial del
    14-ago). Vale igual en simulacro, porque el conteo bajo ese cutoff es el número que firma el
    DPO.
    """
    dias = db.execute(
        select(RetentionPolicy.retention_days).where(RetentionPolicy.log_type == clase)
    ).scalars().first()
    if dias is None:
        raise LookupError(
            f"retención: la clase {clase!r} no tiene fila en retention_policies (seed 004). "
            "Sin plazo no hay cutoff y esta corrida no borra nada de esa clase."
        )
    dias = int(dias)
    if dias < PLAZO_MINIMO_DIAS:
        raise PlazoDeRetencionInvalido(
            f"retención: la clase {clase!r} tiene retention_days={dias} en retention_policies, "
            f"por debajo del mínimo del purgador ({PLAZO_MINIMO_DIAS} día). Con un plazo <= 0 el "
            "cutoff cae en el presente o en el futuro y el DELETE se llevaría filas escritas "
            "hoy: esta clase aborta sin borrar ni contar nada (las demás siguen). Corregí el "
            "plazo en retention_policies y volvé a correr."
        )
    return dias


# ── El residuo: lo que ninguna clase reclama (dictamen 14-ago, punto c) ───────────────


def _ninguna_clase_la_reclama() -> ColumnElement:
    """TRUE si NINGÚN predicado del clasificador levanta esta fila.

    Se arma con `classifier.predicado()` sobre `classifier.clases()` y con nada más: acá no
    vive una segunda definición de las clases (FR-002 pide UNA), así que si el clasificador
    cambia el reparto, el residuo lo sigue sin que nadie tenga que acordarse.

    El `coalesce(..., false)` es la única decisión propia y va del lado de CONTAR de más: hoy
    los predicados son bivaluados (el portón está medido forma por forma y nunca devuelve NULL),
    pero si alguno empezara a devolver NULL, sin el `coalesce` la negación daría NULL y la fila
    desaparecería del conteo — o sea, el «nadie se entera» de vuelta, y esta vez desde adentro
    del contador que vino a cerrarlo. Con él, una fila sobre la que el clasificador no contesta
    se cuenta como residuo, que es el lado ruidoso.
    """
    return ~func.coalesce(
        or_(*(classifier.predicado(clase) for clase in classifier.clases())),
        false(),
    )


def _guardian_events_no_inspeccionable() -> ColumnElement:
    """TRUE si el `guardian_events` de la fila no se puede ni mirar.

    Las tres formas, y por qué las tres:

    * `IS NULL` — SQL NULL. La columna es nullable y `NULL -> 0` es NULL: no hay nada que leer;
    * `jsonb_typeof(...) <> 'array'` — el `'null'::jsonb` (que NO es lo mismo: `typeof` dice
      `'null'`), un objeto pelado, un número. No es una lista de eventos;
    * lista no vacía cuyo primer elemento no es un objeto (`[7]`, `["consequence"]`). Se compara
      contra `'[]'::jsonb` en vez de contar porque `jsonb_array_length` sobre un no-array
      **levanta error** (medido: `ERROR: cannot get array length of a non-array`) y Postgres no
      garantiza el orden de evaluación de un `AND` — el mismo motivo por el que el portón del
      clasificador se escribe así.

    Forma por forma, MEDIDO contra el Postgres 16 del compose (14-ago). Ninguna devuelve NULL:

        SQL NULL      → true    | 'null'::jsonb   → true    | '[]'            → false
        {"upstream":[]} → true  | [7]             → true    | ["consequence"] → true
        7             → true    | [{"type":"PII"}] → false  | eslabón (seq…)  → false

    Qué NO es esto: no es «la fila no es purgable». Un eslabón de la cadena de licencias tampoco
    es purgable y su `guardian_events` es perfectamente inspeccionable — es una lista con un
    objeto adentro que trae las marcas de la cadena. Esa fila está excluida POR DISEÑO (FR-003)
    y no es residuo: el purgador sabe exactamente por qué no la toca. Residuo es lo que el
    purgador no PUDO decidir, y esta función es la que traza esa frontera.

    Es estructural a propósito: mira la forma del jsonb y jamás `model`. El contador no
    reintroduce por su puerta el literal que el dictamen del 14-ago sacó del portón.
    """
    eventos = AuditLog.guardian_events
    primero = eventos[0]
    return or_(
        eventos.is_(None),
        func.jsonb_typeof(eventos) != "array",
        and_(
            eventos != cast(literal("[]"), JSONB),
            func.jsonb_typeof(primero) != "object",
        ),
    )


def es_residuo() -> ColumnElement:
    """El predicado del contador: ninguna clase la reclama **y** no se la pudo inspeccionar.

    Las dos mitades hacen falta y ninguna sobra (§«El residuo» del módulo). Hoy toda fila no
    inspeccionable falla también el portón, así que la primera mitad no descarta ninguna de las
    que trae la segunda; está igual porque es la que hace que el número signifique «lo que esta
    corrida no se llevó» y no «lo que tiene el jsonb raro»: el día que el clasificador aprenda a
    reclamar alguna de estas formas, la fila pasa a morir con su clase y deja de contarse acá
    sola, sin que nadie tenga que venir a mantener este archivo.
    """
    return _ninguna_clase_la_reclama() & _guardian_events_no_inspeccionable()


def cutoff_de_residuo(db: "Session") -> datetime:
    """Frontera bajo la que se cuenta el residuo: `reloj_db - max(retention_days)`.

    El plazo MÁS LARGO de las políticas vigentes, no el más corto: una fila que ninguna clase
    reclama no tiene plazo propio, y el único umbral que no se discute es el que la deja vencida
    bajo TODAS las políticas a la vez. El número que sale es por eso un piso (§«El residuo»).

    Se lee de la tabla y no de una constante: el DPO puede subir un plazo, y el día que lo haga
    el umbral del residuo se mueve con él.

    El piso del §«El piso del plazo» también rige acá, y por el mismo motivo aunque esto no
    borre: con el umbral parado en AHORA, el contador reportaría «toda fila indecidible de la
    tabla está vencida» y el officer firmaría ese número. Se valida el `max`, que es el número
    que de verdad se usa: un plazo inválido suelto no lo distorsiona (`max <= 0` sólo puede pasar
    si NINGUNA política es válida, porque cualquier valor `>= 1` gana el máximo), y esa clase ya
    aborta sola por su propio camino. Cuando levanta, `run_once` lo registra y deja
    `filas_no_clasificadas=None` — «no lo pude contar», que es distinto de `0`.
    """
    dias = db.execute(select(func.max(RetentionPolicy.retention_days))).scalar_one_or_none()
    if dias is None:
        raise LookupError(
            "retención: no hay ninguna fila en retention_policies (seed 004) — sin plazos no "
            "hay umbral bajo el que contar el residuo."
        )
    dias = int(dias)
    if dias < PLAZO_MINIMO_DIAS:
        raise PlazoDeRetencionInvalido(
            f"retención: el plazo MÁS LARGO de retention_policies es retention_days={dias}, por "
            f"debajo del mínimo del purgador ({PLAZO_MINIMO_DIAS} día), o sea que ninguna "
            "política vigente es válida. Sin umbral creíble el residuo no se cuenta: el rastro "
            "dice `filas_no_clasificadas=None` en vez de firmar un número inventado."
        )
    return _reloj_db(db) - timedelta(days=dias)


def contar_no_clasificadas(db: "Session", cutoff: datetime) -> int:
    """Cuántas filas vencidas al `cutoff` son residuo. NO borra nada, ni acá ni en su llamador.

    Una sola consulta agregada por corrida (ver el costo medido en el docstring de `run_once`).
    """
    return db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.timestamp < cutoff, es_residuo())
    ).scalar_one()


# ── El único texto real durable (FR-004, T009): `human_reviews.response_text` ──────────
#
# `audit_logs` es metadata-only por diseño (`AuditService.log_transaction` promete «no raw
# prompt text or PII»), así que la clase `prompt_content` es el conjunto VACÍO sobre esa tabla
# (`classifier.CLASES_SIN_FILAS_EN_AUDIT_LOGS`). Su plazo de 90 d muerde en el ÚNICO contenido
# real durable de la caja: `human_reviews.response_text` (`models/compliance.py:84`). Al vencer,
# el texto pasa a NULL y la fila de revisión PERSISTE como metadata (quién revisó, cuándo,
# veredicto): el DPO tiene que poder demostrar que la revisión ocurrió; lo que muere es el
# contenido (FR-004, scenario 4). El `audit_log_id` queda huérfano lógico documentado (sin FK,
# `models/compliance.py:77`) — no se persigue (Edge Case de spec.md).
#
# CRITERIO DE EDAD — decisión documentada (ambigüedad de spec, resuelta por el lado conservador
# para privacidad). Ni `spec.md` FR-004 (scenario 4) ni `data-model.md:53` fijan sin ambigüedad
# QUÉ timestamp de `human_reviews` decide «vencida»: la columna es «el texto superó el plazo de
# `prompt_content`», sin nombrar `created_at` ni `reviewed_at`. Se elige `created_at`, por dos
# razones que apuntan al mismo lado:
#   1. es el timestamp MÁS TEMPRANO —una revisión se CREA y recién después se revisa, así que
#      `created_at <= reviewed_at`—, y el brief manda elegir el más temprano ante la duda: el
#      contenido muere ANTES, que es el lado seguro para privacidad (Art. 5.1.e);
#   2. `reviewed_at` es NULLABLE (`models/compliance.py:82`): una revisión abierta que nunca se
#      cerró tendría `reviewed_at IS NULL` y su texto viviría para siempre. Atar la muerte del
#      contenido a que alguien haya apretado «revisado» es exactamente el modo de falla que la
#      018 vino a cerrar. **Corrección (#215):** `created_at` NO tiene garantía de no-null — el
#      `default=lambda: datetime.utcnow().isoformat()` (`:83`) es del ORM, dispara sólo en el
#      `insert()` de SQLAlchemy que no fija el valor a mano; la columna en sí es
#      `Column(String, ...)` SIN `nullable=False`, o sea nullable en el DDL. Cualquier fila que
#      no pase por ESE `insert()` — carga masiva, fixture, una migración vieja — puede llegar con
#      `created_at=NULL` o con un string que no es fecha. Antes de #215 eso rompía el `cast` de
#      abajo para TODA la corrida FR-004, no sólo para esa fila (ver §«Residuo de FR-004»).
# El plazo sale de `retention_policies` (log_type=`prompt_content`, seed 004 = 90 d), por el
# MISMO `_plazo_en_dias` que las demás clases: el piso `PLAZO_MINIMO_DIAS` también rige acá.
#
# `created_at` es un `String` ISO-8601 (naive UTC, `datetime.utcnow().isoformat()`), no un
# `DateTime`: se castea a timestamp en SQL para compararlo con el cutoff (naive UTC del reloj de
# la DB). Postgres parsea el separador `T`.
#
# ── Residuo de FR-004 (#215) ────────────────────────────────────────────────────────────
#
# `created_at=NULL` o basura son dos formas del MISMO problema que el residuo de `audit_logs`
# (§«El residuo» arriba en este módulo): una fila que el purgador no puede leer no puede decidir
# si venció, y el fail-closed del depto dice que ante esa duda no se borra — pero tampoco se
# esconde. Dos consecuencias, cada una con su propio blindaje:
#
# 1. **El `cast` no puede reventar la corrida entera.** Un `AND` con el chequeo de casteabilidad
#    primero NO alcanza: Postgres no garantiza el orden de evaluación de los operandos de
#    `AND`/`OR` (doc oficial, Chapter 4 «Expression Evaluation Rules» — «do not write queries
#    that depend on the order of evaluation of WHERE or HAVING»), así que un plan de query puede
#    evaluar igual el `cast` sobre una fila que ese chequeo rechazaría, y revienta con basura real
#    de todos modos. `CASE WHEN` SÍ es evaluación condicional garantizada (mismo capítulo: es el
#    mecanismo que la propia doc recomienda para esto). Verificado empírico contra Postgres 16
#    pineado antes de escribir esto (NULL/vacío/basura no revientan con `CASE`, sí revientan con
#    `AND`-primero bajo cierto plan) — no por lectura de la doc sola.
#    **Corrección #232 (gate del Manager, P1):** el chequeo de casteabilidad en sí era regex de
#    FORMA (`^\d{4}-\d{2}-\d{2}`), no de VALIDEZ — basura con forma de fecha pero sin fecha real
#    (`'0000-00-00'`, `'2024-02-30'`) pasaba la regex, entraba al `cast` de la rama `THEN`, y lo
#    reventaba igual. Ahora es `pg_input_is_valid(created_at, 'timestamp')` (PG16, pineado):
#    valida de verdad, sin reventar. El argumento de CASE-vs-AND de este punto no cambia — sigue
#    aplicando a CUALQUIER chequeo de guarda, regex o función — lo que cambió es QUÉ se pone en la
#    rama `WHEN`.
# 2. **El residuo se cuenta y se loggea** (mismo espíritu que `filas_no_clasificadas`), pero es
#    un contador MÁS SIMPLE: no depende de un cutoff. El de `audit_logs` cuenta «vencida pero
#    indecidible» y por eso necesita un umbral (`cutoff_de_residuo`); acá la pregunta es sólo «¿se
#    puede leer la columna?» — no hay forma de saber si una fila con `created_at` podrido está
#    vencida o no, así que se cuenta SIEMPRE que exista, sin importar la edad. Vive en
#    `ResultadoCorrida.revisiones_residuo_fr004` — NO en la fila resumen `config_audit`: esa forma
#    la sella `data-model.md` §«Corrida de purga» con enmiendas explícitas del manager (`dry_run`
#    13-ago, `filas_no_clasificadas` 14-ago) y #215 no trae una — el contador vive en el objeto y
#    en el log, persistirlo es una decisión de spec que no es de este PR.


# Corrección (#232, gate del Manager — P1): la primera versión de esto chequeaba FORMA
# (`^\d{4}-\d{2}-\d{2}`), no VALIDEZ. Basura que PASA esa regex pero no es timestamp real
# —`'0000-00-00'` (zero-date de MySQL), `'2024-02-30'` (30 de febrero)— matcheaba la forma,
# entraba al `cast`, y lo reventaba igual (`InvalidDatetimeFormat`, aborta la corrida FR-004
# ENTERA) — Y ADEMÁS no contaba como residuo (la negación de la regex daba `False`, no
# `True`): tierra de nadie, ni se purga ni se cuenta. `pg_input_is_valid` (PG16, pineado acá)
# es la forma canónica de testear casteabilidad SIN reventar — valida de verdad, no sólo la
# forma. Verificado empírico contra Postgres 16 pineado: `'0000-00-00'` y `'2024-02-30'` dan
# `false` acá (correctamente rechazadas), NULL/vacío/basura también, fechas reales con y sin
# microsegundos dan `true` — antes de escribir el fix, no por lectura de la doc sola.
#
# Fixes de revisores externos, REFUTADOS y descartados (registro del PR): una regex más
# estricta seguiría siendo chequeo de FORMA (cualquier regex de fecha deja pasar alguna
# combinación año-mes-día inválida); `to_timestamp(..., formato)` + `NULLIF` NO es más seguro
# — hace overflow SILENCIOSO (`'2024-02-30'` se convierte en 1-mar sin error), que es PEOR
# que abortar: un dato mal escrito en vez de un fallo ruidoso.


def _created_at_es_casteable() -> ColumnElement:
    """`True` si `created_at` es un timestamp válido de verdad — no sólo con forma de fecha.
    `pg_input_is_valid` corre el parser real de Postgres sin levantar excepción ante basura,
    que es justo lo que un regex de forma no puede garantizar. `NULL` da `NULL` acá —ni
    verdadero ni falso—, así que una fila con `created_at=NULL` no matchea ACÁ (y tampoco su
    negación: `NOT NULL` también es `NULL`). El residuo (`_created_at_es_residuo_fr004`) por
    eso necesita su propio `IS NULL` explícito, no alcanza con negar esta función."""
    return func.pg_input_is_valid(HumanReview.created_at, "timestamp")


def _created_at_casteado() -> ColumnElement:
    """`cast(created_at AS timestamp)`, blindado con `CASE WHEN` (§«Residuo de FR-004» arriba:
    un `AND` con el chequeo primero NO garantiza que Postgres no evalúe igual el `cast` sobre
    una fila que ese chequeo rechaza). La rama `ELSE NULL` nunca corre el `cast`; una fila con
    `created_at` NULL o inválida (NULL, vacía, basura, o con forma de fecha pero sin fecha
    real) devuelve `NULL` acá, que en la comparación de abajo (`< cutoff`) es `NULL` — o sea
    que ninguna fila indecidible entra jamás a `_revision_con_texto_vencido`."""
    return case((_created_at_es_casteable(), cast(HumanReview.created_at, DateTime)),
                else_=None)


def _created_at_es_residuo_fr004() -> ColumnElement:
    """NULL o no-casteable: lo que el purgador NUNCA puede decidir si venció. Complemento
    EXACTO de `_created_at_es_casteable()` — casteable ↔ residuo particiona TODA fila sin
    tierra de nadie (#232). A diferencia del residuo de `audit_logs` (`es_residuo()`), NO
    depende de un cutoff — no es «vencida pero indecidible», es «no hay forma de saber su
    edad» — así que no hace falta un umbral propio."""
    return or_(HumanReview.created_at.is_(None), ~_created_at_es_casteable())


def _revision_con_texto_vencido(cutoff: datetime) -> ColumnElement:
    """Revisión cuyo `response_text` ya venció al `cutoff` y todavía existe.

    `response_text IS NOT NULL` no es sólo optimización: es lo que hace el barrido idempotente y
    por lotes —una fila ya anulada deja de matchear, así que el lote siguiente avanza solo, igual
    que el `DELETE` de `audit_logs` no vuelve a levantar lo ya borrado—. `_created_at_casteado()`
    ya blinda el `cast`: una fila con `created_at` NULL/podrido da `NULL < cutoff` → `NULL` → no
    matchea, sin que haga falta excluirla acá aparte (#215).
    """
    return and_(
        _created_at_casteado() < cutoff,
        HumanReview.response_text.isnot(None),
    )


def _residuo_fr004_con_texto_vivo() -> ColumnElement:
    """Residuo FR-004 que además importa: `response_text` todavía existe. Una fila ya anulada (o
    que nunca tuvo texto) no tiene nada que «viva para siempre» — contarla sería ruido, no señal
    (#215)."""
    return and_(_created_at_es_residuo_fr004(), HumanReview.response_text.isnot(None))


def contar_residuo_fr004(db: "Session") -> int:
    """Revisiones cuyo `response_text` el purgador nunca va a poder anular porque su
    `created_at` es NULL o no es un timestamp válido — no depende de cutoff (ver
    `_created_at_es_residuo_fr004`). NO borra nada, ni acá ni en su llamador (#215)."""
    return db.execute(
        select(func.count(HumanReview.id)).where(_residuo_fr004_con_texto_vivo())
    ).scalar_one()


def _contar_texto_de_revisiones_vencido(db: "Session", cutoff: datetime) -> int:
    """Cuántas revisiones se anularían al `cutoff`. NO escribe: es el número del simulacro."""
    return db.execute(
        select(func.count(HumanReview.id)).where(_revision_con_texto_vencido(cutoff))
    ).scalar_one()


def _anular_texto_de_revisiones_vencidas(
    db: "Session", cutoff: datetime, tamano_lote: int, pausa: float,
    run_now: bool, ventana: str,
) -> Tuple[int, int, str]:
    """`UPDATE human_reviews SET response_text=NULL` por lotes dentro de la ventana (FR-004).

    Es el gemelo EXACTO del `DELETE` por lotes de `audit_logs` —misma ventana, mismo
    `tamano_lote`, misma pausa, mismo criterio de `partial`—: la muerte del contenido no puede
    tener un régimen de lotes distinto que la de la metadata. Devuelve `(anuladas, lotes,
    resultado)`.
    """
    anuladas = 0
    lotes = 0
    resultado = RESULTADO_OK
    while True:
        if not run_now and not en_ventana(_reloj_db(db), ventana):
            queda = db.execute(
                select(HumanReview.id).where(_revision_con_texto_vencido(cutoff)).limit(1)
            ).first()
            resultado = RESULTADO_PARCIAL if queda else RESULTADO_OK
            break
        lote = (
            select(HumanReview.id)
            .where(_revision_con_texto_vencido(cutoff))
            .limit(tamano_lote)
            .scalar_subquery()
        )
        afectadas = (db.query(HumanReview).filter(HumanReview.id.in_(lote))
                     .update({HumanReview.response_text: None}, synchronize_session=False))
        db.commit()
        anuladas += afectadas
        lotes += 1
        if afectadas < tamano_lote:
            break        # el último lote vino corto: no queda texto vencido
        if pausa:
            time.sleep(pausa)   # cederle la tabla a los lectores calientes (SC-003)
    return anuladas, lotes, resultado


def purgar_clase(clase: str, *, session_factory: Optional[FabricaDeSesiones] = None,
                 run_now: bool = False, run_id: Optional[str] = None) -> ResultadoPurga:
    """Purga una clase hasta agotarla o hasta que se acabe la ventana.

    `run_now=True` saltea el chequeo de ventana: es para los tests y para la operación
    manual (un DPO que acaba de acortar un plazo y quiere el efecto ya). NO es el camino del
    scheduler — el scheduler siempre respeta la ventana.

    `run_now` NO implica corrida real: el simulacro se gobierna por `BASA_PURGE_DRY_RUN`
    (default `true`), que se relee del entorno en cada corrida como el resto de las perillas.
    Son dos ejes distintos a propósito — uno es CUÁNDO y el otro es SI BORRA — y la
    combinación más pedida es justamente la cruzada: «corré ahora y decime cuánto se iría».
    Con `dry_run` activo el cuerpo cuenta con el mismo predicado y el mismo cutoff que usaría
    para borrar, pero no emite ni el `DELETE` de `audit_logs` ni el `NULL` de
    `human_reviews.response_text`; el resultado se devuelve igual y marcado `dry_run=True`. La
    escritura del rastro (`purge_log` + fila resumen `config_audit`) es de `run_once` y sólo
    ocurre en corrida REAL — el simulacro no escribe (§Simulacro; T010).

    `session_factory` se inyecta en los tests (DB de test); en producción es `SessionLocal`.
    Es una FÁBRICA, no una sesión: el cuerpo la llama DENTRO de
    `tenant_context(None, bypass=True)` y cierra ahí mismo lo que abrió. Recibir una `Session`
    ya viva sería el bug de la sección «Identidad bajo RLS» del docstring del módulo — el
    bypass se escaparía del bloque con la transacción.

    `run_id` lo pasa `run_once` para que las cuatro clases de una misma corrida compartan
    identificador en el rastro; llamada suelta, se genera uno.

    **Un plazo `<= 0` aborta esta clase antes de tocar nada** (`PlazoDeRetencionInvalido`, desde
    `_plazo_en_dias`): es la segunda red del §«El piso del plazo» del módulo, duplicada a
    propósito respecto de la validación del endpoint —«el endpoint valida para dar buen error, el
    purgador valida para no destruir», dictamen del 14-ago—. Llamada desde `run_once`, la clase
    queda en `error` y las otras tres corren igual; llamada a mano, la excepción sube.

    La clase `prompt_content` borra 0 filas de `audit_logs` —su predicado es vacío POR DISEÑO
    (`classifier.CLASES_SIN_FILAS_EN_AUDIT_LOGS`): la tabla es metadata-only— y en su lugar, en
    corrida REAL, anula `human_reviews.response_text` de las revisiones vencidas (FR-004/T009);
    su `rows_deleted` cuenta las revisiones cuyo texto murió. Lo que esta función NO hace, para
    que nadie lo lea de más: no escribe el rastro (`purge_log` ni la fila resumen `config_audit`)
    — eso lo orquesta `run_once` por corrida (FR-005/T010).
    """
    predicado = classifier.predicado(clase)   # `ValueError` de una vez si la clase no existe
    fabrica = session_factory or SessionLocal
    run_id = run_id or uuid.uuid4().hex
    ventana = (os.getenv(ENV_WINDOW, "").strip() or DEFAULT_WINDOW)
    tamano_lote = _entero_de_env(ENV_BATCH_SIZE, DEFAULT_BATCH_SIZE)
    pausa = _entero_de_env(ENV_BATCH_PAUSE_MS, DEFAULT_BATCH_PAUSE_MS, minimo=0) / 1000.0
    dry_run = _dry_run_de_env()

    # La sesión se abre y se cierra DENTRO del bloque: el bypass viaja en un `SET LOCAL` que
    # muere con la TRANSACCIÓN, no con el `with` (§«Identidad bajo RLS» del módulo).
    with tenant_context(None, bypass=True):
        db = fabrica()
        try:
            started_at = _reloj_db(db)
            cutoff = started_at - timedelta(days=_plazo_en_dias(db, clase))

            if dry_run:
                # Simulacro: MISMO predicado y MISMO cutoff, cero escrituras. `batches` es los
                # lotes que la corrida real habría necesitado — el officer quiere saber si son
                # tres o tres mil antes de abrir la ventana. No mira la ventana: un conteo no
                # toma locks de escritura, así que es lo único honesto que se puede pedir a
                # mano en horario de oficina (§Simulacro del módulo). Para `prompt_content` el
                # número que caería no está en `audit_logs` (su predicado es vacío por diseño)
                # sino en `human_reviews.response_text` (FR-004): se cuenta lo que se anularía.
                if clase == classifier.CLASE_PROMPT_CONTENT:
                    filas = _contar_texto_de_revisiones_vencido(db, cutoff)
                else:
                    filas = db.execute(
                        select(func.count(AuditLog.id))
                        .where(predicado, AuditLog.timestamp < cutoff)
                    ).scalar_one()
                lotes = math.ceil(filas / tamano_lote) if filas else 0
                return ResultadoPurga(
                    run_id=run_id, clase=clase, started_at=started_at,
                    finished_at=_reloj_db(db), cutoff=cutoff, rows_deleted=filas,
                    batches=lotes, window=ventana, result=RESULTADO_OK, dry_run=True,
                )

            if clase == classifier.CLASE_PROMPT_CONTENT:
                # FR-004/T009: `prompt_content` no tiene filas en `audit_logs` (vacío declarado);
                # su plazo mata el único texto real durable, `human_reviews.response_text`. Mismos
                # lotes/ventana que el `DELETE` de abajo.
                borradas, lotes, resultado = _anular_texto_de_revisiones_vencidas(
                    db, cutoff, tamano_lote, pausa, run_now, ventana)
                return ResultadoPurga(
                    run_id=run_id, clase=clase, started_at=started_at,
                    finished_at=_reloj_db(db), cutoff=cutoff, rows_deleted=borradas,
                    batches=lotes, window=ventana, result=resultado, dry_run=False,
                )

            borradas = 0
            lotes = 0
            resultado = RESULTADO_OK
            while True:
                if not run_now and not en_ventana(_reloj_db(db), ventana):
                    # Ventana cerrada. `partial` SÓLO si de verdad quedó backlog: un `partial`
                    # sobre una clase que ya estaba al día le haría leer al auditor una purga a
                    # medias donde no la hubo, y `partial` es justamente la señal que tiene que
                    # poder creer. El `LIMIT 1` es para saber si queda ALGO, no cuánto.
                    queda = db.execute(
                        select(AuditLog.id)
                        .where(predicado, AuditLog.timestamp < cutoff).limit(1)
                    ).first()
                    resultado = RESULTADO_PARCIAL if queda else RESULTADO_OK
                    break
                lote = (
                    select(AuditLog.id)
                    .where(predicado, AuditLog.timestamp < cutoff)
                    .limit(tamano_lote)
                    .scalar_subquery()
                )
                caidas = (db.query(AuditLog).filter(AuditLog.id.in_(lote))
                          .delete(synchronize_session=False))
                db.commit()
                borradas += caidas
                lotes += 1
                if caidas < tamano_lote:
                    break        # el último lote vino corto: no queda nada vencido
                if pausa:
                    time.sleep(pausa)   # cederle la tabla a los lectores calientes (SC-003)

            return ResultadoPurga(
                run_id=run_id, clase=clase, started_at=started_at, finished_at=_reloj_db(db),
                cutoff=cutoff, rows_deleted=borradas, batches=lotes, window=ventana,
                result=resultado, dry_run=False,
            )
        finally:
            db.close()


# ── El rastro auditable de una corrida (FR-005, T010) ─────────────────────────────────
#
# SC-002: un auditor reconstruye QUÉ se borró, CUÁNDO y bajo QUÉ política SÓLO con el registro.
# Dos representaciones (data-model.md §«Corrida de purga»), las dos metadata-only SIN EXCEPCIÓN
# (Security Constraint 1): el rastro de una purga JAMÁS puede reintroducir lo que la purga vino a
# borrar. Nada de prompt, valor detectado ni identificador de sujeto — sólo conteos, rangos
# temporales, duración y resultado. Los dataclasses `ResultadoPurga`/`ResultadoCorrida` ya son
# metadata-only por construcción, así que serializarlos es seguro.
#
# Sólo se escribe en corrida REAL: el simulacro no toma locks de escritura (§Simulacro), así que
# no deja rastro en tabla. `run_once` llama esto únicamente cuando `dry_run` es falso.


def _iso(dt: Optional[datetime]) -> Optional[str]:
    """`datetime` → ISO-8601, preservando el `None` (cutoff sin resolver, corrida sin residuo)."""
    return dt.isoformat() if dt is not None else None


def _resultado_purga_a_dict(r: ResultadoPurga) -> dict:
    """La entrada del `purge_log` de una clase: los campos de `ResultadoPurga`, sin inventar
    ninguno (la FORMA la fija el dataclass, data-model.md §«Corrida de purga»). Metadata-only."""
    return {
        "run_id": r.run_id,
        "clase": r.clase,
        "started_at": _iso(r.started_at),
        "finished_at": _iso(r.finished_at),
        "cutoff": _iso(r.cutoff),
        "rows_deleted": r.rows_deleted,
        "batches": r.batches,
        "window": r.window,
        "result": r.result,
        "dry_run": r.dry_run,
    }


def _agregar_a_purge_log(db: "Session", r: ResultadoPurga) -> None:
    """Agrega el `ResultadoPurga` de una clase a su `retention_policies.purge_log`, capado a las
    últimas `PURGE_LOG_MAX` corridas por clase.

    La lista se REASIGNA (no se muta in-place): el JSONB por default no rastrea mutaciones de
    lista, así que reasignar es lo que marca la columna sucia para el `UPDATE`.
    """
    pol = (db.query(RetentionPolicy)
           .filter(RetentionPolicy.log_type == r.clase).one_or_none())
    if pol is None:
        # Una clase sin fila no debería pasar (seed 004 crea las cuatro), pero si la corrida la
        # registró en `error` por «clase sin plazo», no hay dónde escribir su entrada: se dice y
        # se sigue, sin tumbar el resto del rastro.
        logger.warning("purga %s: la clase %s no tiene fila en retention_policies; su entrada "
                       "de purge_log se omite", r.run_id, r.clase)
        return
    entradas = list(pol.purge_log or [])
    entradas.append(_resultado_purga_a_dict(r))
    pol.purge_log = entradas[-PURGE_LOG_MAX:]
    db.commit()


def _escribir_fila_resumen(db: "Session", corrida: "ResultadoCorrida") -> None:
    """La fila resumen POR CORRIDA en `audit_logs`, clase `config_audit` (FR-005, SC-002).

    Va por el escritor de eventos de auditoría del producto (`AuditService.log_transaction`, el
    mismo path de compliance que usa el único emisor de configuración vivo,
    `api/guardians.py::_auditar_cambio_postura_tenant`). El `compliance_status` empieza con
    `config_change` para caer en `config_audit` (730 d) y no en `usage_metadata` (classifier
    §«Nota para T010»); el `model` NO es `license`, así que el lector de la cadena la ignora.

    Metadata-only: el blob que viaja en `guardian_events` son los campos de
    `ResultadoCorrida`/`ResultadoPurga` (run_id, timestamps, cutoff, conteos, ventana, resultado,
    dry_run, residuo) — cero contenido. El `filas_no_clasificadas` (residuo, POR CORRIDA) vive
    acá, que es su hogar natural (data-model / `ResultadoCorrida`), no en las entradas por clase.
    """
    resumen = {
        "kind": RESUMEN_KIND,
        "run_id": corrida.run_id,
        "started_at": _iso(corrida.started_at),
        "finished_at": _iso(corrida.finished_at),
        "dry_run": corrida.dry_run,
        "clases": [_resultado_purga_a_dict(r) for r in corrida.clases],
        "filas_no_clasificadas": corrida.filas_no_clasificadas,
        "cutoff_no_clasificadas": _iso(corrida.cutoff_no_clasificadas),
    }
    AuditService.log_transaction(
        db=db,
        model=COMPLIANCE_RESUMEN_PURGA,
        prompt_tokens=0, completion_tokens=0, cost_usd=0.0,
        pii_detected=False, masked_entities=[],
        compliance_status=COMPLIANCE_RESUMEN_PURGA, latency_ms=0,
        processing_purpose="administrative",
        guardian_events=[resumen],
        tenant_id=DEFAULT_TENANT_ID,
    )


def _persistir_rastro(session_factory: FabricaDeSesiones, corrida: "ResultadoCorrida") -> None:
    """Persiste el rastro auditable de una corrida REAL (FR-005/T010). No propaga.

    Un fallo del rastro NO puede voltear una purga ya commiteada —las filas borradas no vuelven—:
    se loguea y se sigue, mismo criterio fail-soft que el resto de los escritores de auditoría del
    producto (`_auditar_cambio_postura_tenant`, `emit_state_event`). La sesión se abre y se cierra
    DENTRO del `tenant_context(None, bypass=True)`: el bypass viaja en un `SET LOCAL` que muere
    con la transacción (Contrato 2, §«Identidad bajo RLS» del módulo).
    """
    with tenant_context(None, bypass=True):
        db = session_factory()
        try:
            for r in corrida.clases:
                _agregar_a_purge_log(db, r)
            _escribir_fila_resumen(db, corrida)
        except Exception:  # noqa: BLE001 — el rastro no tumba la corrida, pero GRITA
            logger.exception("purga %s: no se pudo persistir el rastro auditable de la corrida",
                             corrida.run_id)
        finally:
            db.close()


def run_once(*, session_factory: Optional[FabricaDeSesiones] = None,
             run_now: bool = False) -> ResultadoCorrida:
    """Una pasada por TODAS las clases del clasificador, en su orden estable, **y el residuo**.

    Es el punto de entrada del scheduler (T011) y el que usa el quickstart. Trae un resultado
    por clase (`.clases`); una clase que falla no cancela a las demás (su `ResultadoPurga`
    queda en `error` y la corrida sigue): la purga de metadata de uso no tiene por qué caerse
    porque la de contenido tropezó. **Un plazo `<= 0` cae por esa misma puerta** y es una
    decisión, no una casualidad: el §«El piso del plazo» del módulo explica por qué aborta la
    clase y no la corrida entera.

    Devuelve un `ResultadoCorrida` y no la lista pelada porque el residuo no es de ninguna clase
    — el porqué está en el docstring de ese dataclass. Nadie consumía la lista todavía (el
    scheduler es esqueleto), así que el cambio no arrastra a ningún llamador vivo.

    **El contador sale SIEMPRE que la corrida corra**, en real y en simulacro: «el officer que
    ensaya la purga tiene que ver el residuo ANTES de apretar el botón» (dictamen del manager,
    14-ago, textual). Sale en el objeto y en el log; en corrida REAL, además, en el rastro en
    tabla (`filas_no_clasificadas` viaja en la fila resumen `config_audit`, T010). El simulacro no
    escribe, así que ahí el log es lo único que le queda al operador. Con residuo el log es
    `warning`, no `info`: el número existe para que alguien se entere.

    **El rastro auditable de la corrida REAL (FR-005/T010)** lo persiste `_persistir_rastro` al
    cierre: una entrada por clase en su `retention_policies.purge_log` (capado a las últimas
    `PURGE_LOG_MAX`) y UNA fila resumen `config_audit` por corrida. Metadata-only sin excepción, y
    fail-soft: un fallo del rastro no vuelve a poner las filas borradas, así que se loguea y la
    corrida devuelve su `ResultadoCorrida` igual.

    Fuera de la ventana (y sin `run_now`) la corrida no hace NADA y lo dice: `clases` vacío y
    `filas_no_clasificadas=None`, que es «no se contó» y no «no hay». Contar igual sería pagar
    un barrido por tick de scheduler sobre la tabla más caliente del producto para volver a
    escribir el mismo número de hace una hora.

    ## Costo del contador — MEDIDO, no estimado (14-ago, Postgres 16 del compose)

    Es **UNA consulta agregada por corrida**: no una por clase, y no una segunda pasada por las
    filas que las clases ya recorrieron. No se puede sacar de las consultas de las clases, y no
    por comodidad: el residuo es EXACTAMENTE lo que ninguna de ellas levanta, así que no aparece
    en ninguno de sus resultados ni en sus conteos.

    `EXPLAIN (ANALYZE, BUFFERS)` sobre `audit_logs` con 200.000 filas repartidas al azar en 900
    días (37.334 vencidas al plazo de 730 d), tras `ANALYZE`:

    | consulta                                    | plan                          | tiempo  |
    |---------------------------------------------|-------------------------------|---------|
    | residuo, backlog entero (simulacro)         | Bitmap Index Scan + Heap      |  7,4 ms |
    | residuo tras los DELETE (corrida real)      | el mismo, 92 filas            |  3,3 ms |
    | conteo de UNA clase (simulacro, ×4)         | Parallel Seq Scan             | 12,2 ms |
    | el `SELECT … LIMIT 5000` que elige un lote‡ | Parallel Seq Scan             |  4,1 ms |

    El índice de las dos primeras es `ix_audit_logs_timestamp`.

    ‡ es la SELECCIÓN del lote, no el `DELETE`: lo que la fila de abajo cuesta de verdad —el
    borrado, los índices y el bloat— no está en esos 4,1 ms y se mide en SC-003, no acá.

    O sea que el contador sale **más barato que el conteo de una sola clase**, y la corrida hace
    cuatro de ésos: el filtro por `timestamp` lo resuelve por índice y sólo mira las filas
    vencidas, mientras que los predicados de clase matchean media tabla y el planner se va a seq
    scan. Contra la corrida entera es ruido, y contra el `DELETE` por lotes —que es lo que de
    verdad le cuesta a la tabla— ni se ve.

    Lo que sí conviene saber para el día que esto crezca: el costo del contador escala con
    **cuántas filas hay más viejas que el plazo más largo**, no con el tamaño de la tabla. En
    una instalación al día son pocas (las purgadas ya no están); en la PRIMERA corrida de una
    caja con años de backlog son todas las viejas de golpe, y ahí conviene mirarlo con el resto
    del examen de SC-003.
    """
    run_id = uuid.uuid4().hex
    fabrica = session_factory or SessionLocal
    dry_run = _dry_run_de_env()
    ventana = (os.getenv(ENV_WINDOW, "").strip() or DEFAULT_WINDOW)
    # `started_at`/`finished_at` de la CORRIDA salen del reloj del PROCESO: miden cuánto duró el
    # job y tienen que existir aunque la DB deje de contestar a mitad. La EDAD de las filas —lo
    # único que decide un borrado— sale siempre del reloj de la DB (`_reloj_db`), igual que la
    # comprobación de ventana de acá abajo, que se hace con una sesión propia por eso mismo.
    iniciada = datetime.utcnow()

    if not run_now:
        with tenant_context(None, bypass=True):
            db = fabrica()
            try:
                abierta = en_ventana(_reloj_db(db), ventana)
            finally:
                db.close()
        if not abierta:
            logger.debug("purga %s: fuera de la ventana %s, no corre", run_id, ventana)
            return ResultadoCorrida(
                run_id=run_id, started_at=iniciada, finished_at=datetime.utcnow(),
                dry_run=dry_run, clases=(), filas_no_clasificadas=None,
                cutoff_no_clasificadas=None, revisiones_residuo_fr004=None,
            )

    resultados: List[ResultadoPurga] = []
    for clase in classifier.clases():
        try:
            resultados.append(purgar_clase(clase, session_factory=session_factory,
                                           run_now=run_now, run_id=run_id))
        except Exception:  # noqa: BLE001 — una clase caída no cancela a las demás
            logger.exception("purga %s: la clase %s falló", run_id, clase)
            resultados.append(ResultadoPurga(
                run_id=run_id, clase=clase, started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(), cutoff=None, rows_deleted=0, batches=0,
                window=ventana, result=RESULTADO_ERROR, dry_run=dry_run,
            ))

    residuo: Optional[int] = None
    cutoff_residuo: Optional[datetime] = None
    with tenant_context(None, bypass=True):
        db = fabrica()
        try:
            cutoff_residuo = cutoff_de_residuo(db)
            residuo = contar_no_clasificadas(db, cutoff_residuo)
        except Exception:  # noqa: BLE001 — el contador no tumba la corrida, pero GRITA
            logger.exception("purga %s: no se pudo contar el residuo no clasificado", run_id)
        finally:
            db.close()

    # #215: residuo GEMELO del lado `human_reviews` — misma disciplina (SIEMPRE se cuenta, en
    # real y en simulacro; un fallo del contador GRITA pero no tumba la corrida) y misma sesión
    # descartable propia, independiente de la de arriba porque son dos tablas y dos preguntas
    # distintas (§«Residuo de FR-004» del módulo).
    residuo_fr004: Optional[int] = None
    with tenant_context(None, bypass=True):
        db = fabrica()
        try:
            residuo_fr004 = contar_residuo_fr004(db)
        except Exception:  # noqa: BLE001 — el contador no tumba la corrida, pero GRITA
            logger.exception("purga %s: no se pudo contar el residuo FR-004", run_id)
        finally:
            db.close()

    borradas = sum(r.rows_deleted for r in resultados)
    if residuo:
        logger.warning(
            "purga %s (dry_run=%s): %s filas en %s clases; %s filas vencidas NO clasificadas "
            "siguen en audit_logs (cutoff %s) — el purgador no pudo demostrar que sean tráfico "
            "y no las borra",
            run_id, dry_run, borradas, len(resultados), residuo, cutoff_residuo,
        )
    else:
        logger.info("purga %s (dry_run=%s): %s filas en %s clases; residuo no clasificado: %s",
                    run_id, dry_run, borradas, len(resultados),
                    "0" if residuo == 0 else "SIN CONTAR")

    if residuo_fr004:
        logger.warning(
            "purga %s (dry_run=%s): %s revisiones de human_reviews tienen created_at NULL/no "
            "casteable — su response_text nunca se puede anular por FR-004 (edad indecidible)",
            run_id, dry_run, residuo_fr004,
        )
    else:
        logger.info("purga %s (dry_run=%s): residuo FR-004 (created_at podrido): %s",
                    run_id, dry_run, "0" if residuo_fr004 == 0 else "SIN CONTAR")

    corrida = ResultadoCorrida(
        run_id=run_id, started_at=iniciada, finished_at=datetime.utcnow(), dry_run=dry_run,
        clases=tuple(resultados), filas_no_clasificadas=residuo,
        cutoff_no_clasificadas=cutoff_residuo, revisiones_residuo_fr004=residuo_fr004,
    )

    # FR-005/T010: el rastro auditable, SÓLO en corrida real. El simulacro no escribe (§Simulacro:
    # no toma locks de escritura), y como es el default del producto, un rastro en tabla aparece
    # exactamente cuando de verdad se borró algo.
    if not dry_run:
        _persistir_rastro(fabrica, corrida)

    return corrida


# ── Entrypoint de CLI (FR-001, T008) ──────────────────────────────────────────────────
#
# Hasta acá `python -m src.services.retention.purger --run-now` NO ejecutaba nada: el módulo no
# tenía `__main__` ni argparse. El punto de entrada de una corrida es `run_once`, y el CLI no es
# más que una cáscara sobre él para la operación manual —un DPO que acaba de acortar un plazo y
# quiere el efecto ya, sin esperar a la ventana de las 02:00— y para el quickstart.
#
# Los dos ejes son ORTOGONALES y el CLI respeta esa separación (Contrato 4):
#   * `--run-now` dice CUÁNDO (saltea la ventana). Es lo único que gobierna el CLI.
#   * SI BORRA lo decide `BASA_PURGE_DRY_RUN` (default `true` = simulacro), que `run_once` relee
#     del entorno como el resto de las perillas. El CLI NO lo toca: encender la purga real es
#     `BASA_PURGE_DRY_RUN=false` en el entorno, a mano y a la vista, igual que en el quickstart.


def _main(argv: Optional[List[str]] = None) -> int:
    """Corre UNA pasada del purgador y escribe el `ResultadoCorrida` a stdout.

    Devuelve 0 siempre que la corrida termine (una clase en `error` no es un fallo del proceso:
    es un hecho de esa clase que ya viaja en el resultado y en el log — §«El piso del plazo»).
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m src.services.retention.purger",
        description=(
            "Purgador de retención (spec 018). Corre una pasada por todas las clases. "
            "SIMULACRO por default (BASA_PURGE_DRY_RUN=true): cuenta lo que se iría y no borra. "
            "Para borrar de verdad, exportá BASA_PURGE_DRY_RUN=false."
        ),
    )
    parser.add_argument(
        "--run-now", action="store_true",
        help=("saltea la ventana horaria y corre YA (CUÁNDO, no SI BORRA). Sin este flag, la "
              "corrida sólo trabaja dentro de BASA_PURGE_WINDOW."),
    )
    args = parser.parse_args(argv)

    # El operador que corre esto a mano quiere VER lo que pasó: el log del módulo (incluido el
    # `warning` del residuo) es parte del rastro hasta que exista un scheduler que lo recoja.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    resultado = run_once(run_now=args.run_now)
    print(resultado)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
