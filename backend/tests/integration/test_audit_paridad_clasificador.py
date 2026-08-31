"""Paridad EXACTA de la vitrina de auditoría antes y después del refactor (spec 018, T005).

La 018 mueve el criterio de «qué fila es un bloqueo / un eslabón de licencia / un rechazo
nuestro» desde las constantes locales de `api/audit.py` al clasificador de retención
(`services/retention/classifier.py`, FR-002), para que la pantalla que MIRA y el purgador que
BORRA no puedan discrepar sobre la misma tabla.

Mover ese criterio es tocar superficie viva del cliente: la vitrina de compliance es la
pantalla donde el officer lee «cuántos intentos bloqueó el firewall». Un número distinto
después de un refactor que no venía a cambiar ningún número no es un detalle, es un incidente
— y de los peores, porque no rompe nada visiblemente: simplemente el informe del mes que viene
no cuadra con el del mes pasado y nadie sabe cuál de los dos era el bueno.

Por eso este archivo NO afirma «la vitrina hace lo correcto» (eso ya lo fija
`test_audit_filtro_estado.py`, spec 031). Afirma otra cosa: **hace exactamente lo mismo que
hacía**. Con dos redes que se cubren entre sí:

1. **Oráculo congelado** (`_vitrina_pre_refactor`): la query PRE-refactor reescrita acá con
   sus literales a mano (`model != 'license'`, `LIKE 'blocked%'`, `LIKE 'rejected%'`), sin
   importar nada de `api/audit.py` ni del clasificador. Cada vista de la pantalla se compara
   fila por fila (por id, no por conteo) contra lo que devuelve la API real. Si el refactor
   corrió una sola fila de balde, acá se ve cuál.
2. **Números de oro** (`ESPERADO`): las mismas expectativas escritas a mano. El oráculo por sí
   solo tiene un agujero conocido — el día que alguien vea este test en rojo puede «arreglar»
   el oráculo en vez del código y quedarse tranquilo. Los literales de `ESPERADO` no se pueden
   arreglar sin escribir explícitamente «sí, decido que esta fila cambia de balde».

Y un tercer grupo que no es de paridad sino de la razón de ser del refactor
(`test_la_vitrina_sigue_al_clasificador_*`): mueven el criterio EN EL CLASIFICADOR y exigen
que la pantalla se mueva con él. Si mañana alguien vuelve a escribir un `LIKE 'blocked%'`
dentro de `api/audit.py`, los tests de paridad seguirían verdes (el criterio inlineado daría
el mismo resultado) y estos se ponen rojos. Son los que impiden que la vitrina recupere
criterio propio en silencio, que es justo lo que FR-002 vino a prohibir. Hay uno por primitiva
CONSUMIDA (`es_bloqueo`, `es_rechazo`, `dice_licencia`) y un cuarto por la negativa: clava que
la vitrina NO mira la forma del eslabón, que es la mitad que el dictamen del 14-ago le sacó.
"""
import csv
import io
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "sentinel_test_audit_paridad_clasificador"
LOGS = "/api/v1/audit-logs"
EXPORT = "/api/v1/audit-logs/export"

# (marca, model, compliance_status). La marca es la identidad de la fila DENTRO del test: los
# `compliance_status` se repiten entre planos (un `blocked_by_policy` de tráfico y otro de la
# cadena de licencias son filas distintas con el mismo estado), así que comparar por estado
# escondería justamente el caso que más importa. Se compara por id, y la marca es cómo se lee
# ese id cuando el assert falla.
#
# La semilla cubre, a propósito, más de lo que el producto emite hoy: los 13 literales vivos
# del inventario del clasificador (`EMISORES_VIGENTES`), un `rejected_*` que todavía no existe,
# un literal que nadie inventarió y un `blocked` sin guion bajo. Los tres últimos son los que
# clavan que el criterio es de PREFIJO y que el `else` de la pantalla es un cajón de sastre: si
# el refactor cambiara cualquiera de esas dos cosas, sólo una fila rara lo delata — con la
# semilla feliz (`passed` + `blocked_secret`) el cambio pasaría inadvertido.
#
# Acá va sólo TRÁFICO. La cadena de licencias se siembra aparte y con su emisor real (`CADENA`).
SEMILLA = [
    # Bloqueos: una capa dictaminó y el pedido no pasó.
    ("bloq_prohibited", "claude-3-5-sonnet-20241022", "blocked_prohibited"),
    ("bloq_by_policy", "ollama-qwen3-4b", "blocked_by_policy"),
    ("bloq_residency", "claude-3-5-sonnet-20241022", "blocked_residency"),
    ("bloq_secret", "gpt-4o", "blocked_secret"),
    ("bloq_nlp_unavailable", "ollama-qwen3-4b", "blocked_nlp_unavailable"),
    # Legado: `api/monitor.py:78` avisa que hoy no lo emite ningún productor, pero la pantalla
    # lo sigue conociendo y la 031 lo siembra. Si alguna vez volviera, tiene que seguir siendo
    # un bloqueo.
    ("bloq_guardian", "ollama-qwen3-4b", "blocked_guardian"),
    # Sin guion bajo: el prefijo canónico es `blocked`, no `blocked_`. Clava que el criterio no
    # se degradó a una lista de valores exactos.
    ("bloq_sin_guion", "gpt-4o", "blockedXraro"),
    # El prefijo PELADO, sin nada detrás. Parece un caso de laboratorio y es el único que
    # separa `LIKE 'blocked%'` de `LIKE 'blocked_%'`: en LIKE el `_` es comodín de UN carácter,
    # así que `blocked_%` también matchea `blockedXraro` y las dos formas se ven idénticas
    # sobre cualquier semilla realista. Sin esta fila, un refactor que reescriba el criterio
    # con guion bajo pasa la paridad entera. Es el mismo motivo por el que el clasificador usa
    # `startswith(..., autoescape=True)` y no `like()` crudo.
    ("bloq_pelado", "gpt-4o", "blocked"),
    # Tráfico que el firewall resolvió sin impedirlo.
    ("perm_passed", "claude-3-5-sonnet-20241022", "passed"),
    ("perm_flagged", "ollama-qwen3-4b", "flagged_high_risk"),
    ("perm_allowed", "gpt-4o", "allowed"),
    ("perm_upstream_error", "claude-3-5-sonnet-20241022", "upstream_error"),
    ("perm_degradado", "ollama-qwen3-4b", "degraded_nlp_regex"),
    # Literal que nadie inventarió: hoy cae en el `else` y se informa como PERMITIDO. Es el
    # comportamiento vigente y el refactor no lo cambia (ver HALLAZGO al pie del archivo).
    ("perm_inedito", "gpt-4o", "estado_que_nadie_inventario"),
    # Cambio de configuración auditado: tampoco es tráfico, y sin embargo hoy cuenta como
    # permitido. Va en la semilla para que el refactor no lo mueva de balde sin querer.
    ("cfg_nlp_fail_mode", "claude-3-5-sonnet-20241022", "config_change_nlp_fail_mode"),
    # Rechazos NUESTROS: fuera de los DOS baldes (gate #135 H4 · #157), visibles sin filtro.
    ("rech_saturado", "ollama-qwen3-4b", "rejected_saturated"),
    ("rech_budget", "claude-3-5-sonnet-20241022", "rejected_budget"),
    ("rech_futuro", "gpt-4o", "rejected_timeout"),
]

# ── La cadena de licencias (021): NO se arma a mano, la emite el emisor real ───────────
#
# `(marca, event_type, compliance_status que el emisor le pone)`.
#
# Por qué el emisor y no tres dicts acá: es el hallazgo del gate del 13-ago. Esta semilla
# escribía `model='license'` con `guardian_events=[]`, una forma que el emisor de la 021 NUNCA
# produjo —ni antes ni después de la US5—, y bajo la regla enmendada del clasificador una fila
# así es indistinguible de un spoof. Con razón: una fila de licencia REAL siempre trae su
# eslabón. O sea que la paridad venía pasando gracias a una forma que sólo existía en el test.
# Emitidas por `emit_license_event`, la forma no puede divergir de producción sin que este
# archivo se entere el mismo día.
#
# Los tres estados de acá son los TRES —y los únicos— con los que la cadena se persiste de
# verdad (`_COMPLIANCE_BY_EVENT`, `audit_events.py:204-209`): `passed`, `flagged_high_risk` y
# el default `blocked_by_policy`. La ronda anterior sembraba en su lugar un
# `model='license'` + `rejected_saturated` que ningún evento de licencia escribe, y que además
# quedaba excluido por DOS puertas a la vez (la del modelo y la del prefijo `rejected`) — o
# sea que no medía ninguna. `flagged_high_risk` (el evento de gracia) lo reemplaza porque es
# real y porque sale SÓLO por la puerta de la cadena.
#
# Los estados van escritos acá para poder AFIRMARLOS después de emitir (ver `sembrar_cadena`):
# una semilla que se sigue creyendo realista mientras el emisor cambió de estados no prueba
# nada, y es exactamente el modo de falla del que viene este archivo.
CADENA = [
    ("lic_pasada", "license_loaded", "passed"),
    ("lic_gracia", "license_grace", "flagged_high_risk"),
    # El feo: el eslabón que cae de lleno en `LIKE 'blocked%'` y que sólo la exclusión de la
    # cadena saca de los baldes.
    ("lic_bloqueada", "license_seat_limit_exceeded", "blocked_by_policy"),
]

# ── La forma HISTÓRICA de la cadena (16→20-jul), que es la que rompe la paridad ────────
#
# `(marca, event_type, compliance_status)`. Ésta va a mano y es la ÚNICA excepción declarada a
# la regla de no inventar fixtures: ningún emisor de HOY la puede producir, porque
# `_append_chained` escribe `prev_hash` y `seq` desde la US5 (9cd7b99, 20-jul) y no hay perilla
# para que no los escriba. Es evidencia histórica que está en la base de instalaciones vivas;
# la forma está copiada del fuente de aquel momento (8e8f705): las mismas seis claves y
# ninguna más.
#
# Por qué esta fila vive en el archivo de PARIDAD y no sólo en el de comportamiento: es la
# única de la semilla sobre la que el oráculo congelado (`model != 'license'`, o sea `main`) y
# la exclusión que la 018 probó el 13-ago (`literal` **y** `seq`) contestan DISTINTO. Sin ella
# la paridad quedaría verde con las dos exclusiones y el archivo no mediría el punto b del
# dictamen del 14-ago — que es, textualmente, «la paridad con main se restaura EXACTA».
#
# El estado es el feo a propósito: `blocked_by_policy` es el que la mete en «bloqueados» junto
# a los intentos de fuga (el `total=1` donde `main` da `0` que midió el dictamen). La mitad
# `passed` —la que se colaría en «permitidos»— la cubre `test_audit_filtro_estado.py`, que es
# el archivo de comportamiento.
CADENA_PRE_US5 = [
    ("lic_pre_us5", "license_seat_limit_exceeded", "blocked_by_policy"),
]

# Índice de la fila a partir de la cual corta `from_date` en la vista con rango de fechas.
# Cae en medio de los bloqueos a propósito: un rango que dejara los tres baldes intactos no
# probaría que `estado` y las fechas se componen con AND.
_CORTE = 4

# Los números de oro, por marca. Escritos a mano leyendo la semilla, NO derivados del oráculo
# ni de la API: son la segunda red, y una red que se calcula sola no es una red.
ESPERADO = {
    "bloqueados": [
        "bloq_prohibited", "bloq_by_policy", "bloq_residency", "bloq_secret",
        "bloq_nlp_unavailable", "bloq_guardian", "bloq_sin_guion", "bloq_pelado",
    ],
    "permitidos": [
        "perm_passed", "perm_flagged", "perm_allowed", "perm_upstream_error",
        "perm_degradado", "perm_inedito", "cfg_nlp_fail_mode",
    ],
}


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    client.headers.update(admin_headers(client))
    marcas = sembrar(factory)
    yield client, factory, marcas
    cleanup()


def sembrar(factory):
    """Tráfico por base directa; la cadena VIGENTE por su emisor; la HISTÓRICA a mano.

    Los tres criterios parecen inconsistentes y no lo son. El TRÁFICO va por base directa
    porque lo que se prueba es la QUERY de la pantalla: hacer que cada plano emita su propio
    estado convertiría esto en un test de integración de otros seis módulos y taparía el único
    invariante que interesa acá.

    La CADENA VIGENTE va por su emisor por el motivo contrario: la forma de esa fila no es
    plomería, es evidencia de qué escribe el producto. Una forma escrita a mano acá es una
    forma que nadie garantiza que exista — y es justo lo que había: `guardian_events=[]` en una
    fila de licencia, que ningún emisor de la 021 produjo nunca.

    La cadena HISTÓRICA (pre-US5) va a mano porque no hay emisor que la pueda escribir hoy: el
    motivo entero está en `CADENA_PRE_US5`, y es la única excepción declarada a la regla de no
    inventar fixtures.

    Devuelve marca → (id como string, timestamp), que es con lo que se leen los asserts.
    """
    from src.models.audit import AuditLog
    from src.models.license_state import LicenseRuntimeState
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        db.query(AuditLog).delete()
        # La cadena arranca en cero para que el emisor escriba EXACTAMENTE `len(CADENA)` filas.
        # Si la fila singleton ya existiera con génesis 'unlicensed', el primer `license_id`
        # dispararía ADEMÁS el evento de anclaje diferido (`audit_events.py:229-236`) y el
        # listado tendría una fila `model='license'` que ninguna marca nombra — o sea, un
        # `nombres()` con un UUID pelado adentro y un total que no cuadra con nada.
        db.query(LicenseRuntimeState).delete()
        base = datetime.utcnow() - timedelta(minutes=len(SEMILLA))
        marcas = {}
        for i, (marca, modelo, estado) in enumerate(SEMILLA):
            fila_id = uuid.uuid4()
            ts = base + timedelta(minutes=i)
            db.add(AuditLog(
                id=fila_id, tenant_id=DEFAULT_TENANT_ID,
                timestamp=ts, model=modelo,
                prompt_tokens=0, completion_tokens=0, cost_usd=0,
                pii_detected=False, compliance_status=estado, latency_ms=7,
                blocked_by_layer=None, guardian_events=[],
            ))
            marcas[marca] = (str(fila_id), ts)
        db.commit()
        marcas.update(sembrar_cadena(db))
        marcas.update(sembrar_cadena_pre_us5(db, DEFAULT_TENANT_ID))
        return marcas
    finally:
        db.close()


def sembrar_cadena(db):
    """Los eslabones de `CADENA`, EMITIDOS por `licensing.audit_events.emit_license_event`.

    El timestamp de estas filas lo pone el emisor (reloj real), no la grilla por minutos de la
    semilla de tráfico. No importa y conviene que se sepa por qué: las filas de la cadena están
    excluidas de las DOS vistas que filtran por fecha, así que su posición en el tiempo no
    puede mover ningún resultado. Si algún día una vista con `from_date` las incluyera, este
    comentario es la advertencia de que quedan al final de la línea de tiempo.

    Devuelve marca → (id como string, timestamp), con la misma forma que el resto de la semilla.
    """
    from src.licensing.audit_events import emit_license_event
    from src.models.audit import AuditLog

    for _, evento, _ in CADENA:
        emit_license_event(db, evento, license_id="lic_paridad_018",
                           seats_used=26, max_seats=25,
                           reason="semilla de paridad de la vitrina")

    # Por `seq` y no por `timestamp`: el emisor escribe los tres eslabones dentro del mismo
    # segundo y el orden de la cadena es el del contador, no el del reloj.
    filas = sorted(db.query(AuditLog).filter(AuditLog.model == "license").all(),
                   key=lambda fila: fila.guardian_events[0]["seq"])
    assert len(filas) == len(CADENA), (
        f"el emisor de la 021 escribió {len(filas)} filas de licencia y `CADENA` declara "
        f"{len(CADENA)}: la semilla dejó de describir lo que siembra")

    # La semilla se verifica a sí misma contra el emisor. Sin esto, el día que la 021 cambie
    # de estados o de forma este archivo seguiría verde midiendo otro universo — que es el modo
    # de falla del que viene: una semilla que se creía realista y no lo era.
    marcas = {}
    for (marca, evento, estado), fila in zip(CADENA, filas):
        assert fila.compliance_status == estado, (
            f"«{evento}» dejó de persistirse como {estado!r} (hoy: "
            f"{fila.compliance_status!r}): `CADENA` ya no describe la cadena real")
        assert "seq" in fila.guardian_events[0], (
            f"el eslabón de «{evento}» no trae `seq`: la exclusión de la vitrina pide las DOS "
            "mitades y esta fila dejó de ejercitar la del modelo")
        marcas[marca] = (str(fila.id), fila.timestamp)
    return marcas


def sembrar_cadena_pre_us5(db, tenant_id):
    """Las filas de `CADENA_PRE_US5`, copiadas del fuente de 8e8f705 (16→20-jul-2026).

    Corre DESPUÉS de `sembrar_cadena` a propósito: esa función cuenta las filas
    `model='license'` de la base y las compara contra `len(CADENA)`. Sembrar las históricas
    antes le agregaría filas que ese assert no espera y el archivo moriría en el fixture, lejos
    del test que corresponde.

    Las seis claves del `entry` de aquel emisor y ninguna más: sin `prev_hash` y sin `seq`, que
    llegaron con la US5 (9cd7b99). El resto de las columnas van como las escribía aquel emisor
    (cero tokens, cero coste, cero latencia, sin PII), así lo único que separa esta fila de un
    eslabón de hoy es la ausencia de las dos claves de la cadena — que es la variable medida.

    Devuelve marca → (id como string, timestamp), con la misma forma que el resto de la semilla.
    """
    from src.models.audit import AuditLog

    base = datetime.utcnow() - timedelta(hours=1)
    marcas = {}
    for i, (marca, evento, estado) in enumerate(CADENA_PRE_US5):
        fila_id = uuid.uuid4()
        ts = base + timedelta(seconds=i)
        db.add(AuditLog(
            id=fila_id, tenant_id=tenant_id,
            timestamp=ts, model="license",
            prompt_tokens=0, completion_tokens=0, cost_usd=0,
            pii_detected=False, compliance_status=estado, latency_ms=0,
            blocked_by_layer=None,
            guardian_events=[{
                "event_type": evento,
                "license_id": "lic_paridad_018",
                "seats_used": 26,
                "max_seats": 25,
                "reason": "semilla de paridad de la vitrina (forma pre-US5)",
                "ts": ts.isoformat(),
            }],
        ))
        marcas[marca] = (str(fila_id), ts)
    db.commit()

    # La semilla se verifica a sí misma, igual que la vigente: lo que hace ÚTIL a estas filas es
    # que NO traigan `seq`. Si alguien las «arreglara» copiándoles un eslabón entero, el archivo
    # seguiría verde midiendo el mismo caso dos veces.
    for marca, (fila_id, _) in marcas.items():
        evento = db.query(AuditLog).filter(
            AuditLog.id == uuid.UUID(fila_id)).one().guardian_events[0]
        assert "event_type" in evento and "seq" not in evento and "prev_hash" not in evento, (
            f"«{marca}» dejó de tener la forma pre-US5 (event_type sin seq ni prev_hash): la "
            "semilla ya no distingue el criterio de `main` del que se probó el 13-ago")
    return marcas


# ── El oráculo congelado ──────────────────────────────────────────────────────────────
#
# Copia LITERAL de `api/audit.py::_build_query` tal como estaba antes del refactor de la 018,
# con sus constantes en crudo. No importa nada de `src.api.audit` ni del clasificador A
# PROPÓSITO: un oráculo que llame al código bajo prueba se pone de acuerdo consigo mismo y no
# prueba nada. Esto es la foto del comportamiento que el cliente ya tiene instalado.
#
# NO SE ACTUALIZA. Si un cambio futuro de la vitrina lo pone en rojo, la pregunta correcta no
# es «¿cómo arreglo el oráculo?» sino «¿el officer va a ver otro número, y eso está decidido?».
# Recién con esa decisión tomada (y anotada) se toca este bloque.
#
# ── La pregunta se contestó dos veces, y la respuesta VIGENTE es la segunda ──
#
# **13-AGO-2026 — se aceptó mover el número.** La 018 había enmendado la exclusión de la
# cadena: `es_licencia()` dejó de conformarse con `model='license'` y pasó a pedir TAMBIÉN el
# `seq` del eslabón, o sea que una fila `model='license'` sin eslabón era tráfico y aparecía en
# los baldes. El argumento era que `model` lo escribe el inspeccionado
# (`api/gateway.py:1455`), así que una exclusión que se conforme con el literal es una que el
# inspeccionado se pide a sí mismo.
#
# **14-AGO-2026 — REVERTIDA por el manager (dictamen, punto b), y por eso la paridad con
# `main` vuelve a ser EXACTA.** Lo que el cambio anterior no había medido es que la forma
# «`license` sin `seq`» no es sólo el spoof: es también la forma LEGÍTIMA que el emisor de la
# 021 persistió entre el 16 y el 20 de julio, antes de que la US5 (9cd7b99) inventara la
# hash-chain. Con el `seq` en la exclusión, esa fila histórica se le muestra al officer entre
# los bloqueos, mezclada con intentos de fuga — medido: `total=1` donde `main` da `0`. Y el
# literal no necesitaba esa defensa: la Capa B (`gateway.sanear_modelo_declarado`) ya impide
# que el inspeccionado escriba `license` en la columna. La regla que quedó, textual:
#
#     purga = por forma (irreversible → no confía en nadie); vitrina = por literal
#     (reversible → y el literal ya es nuestro gracias a la Capa B)
#
# O sea que este oráculo NO se tocó nunca —ni en la ronda del 13 ni en la del 14— y hoy
# describe otra vez, literalmente, lo que la pantalla hace. Quien vuelva a verlo en rojo: la
# pregunta de arriba ya tiene dueño y respuesta; lo que hay que contestar es la siguiente.
#
# (La ronda del 13-ago sí arregló la SEMILLA, que armaba filas de licencia con
# `guardian_events=[]` —una forma que el emisor de la 021 nunca escribió, ver `sembrar_cadena`—.
# Ese arreglo se queda: es correcto con cualquiera de las dos exclusiones.)
def _vitrina_pre_refactor(db, estado=None, compliance_status=None, pii_detected=None,
                          from_date=None, to_date=None):
    from src.models.audit import AuditLog
    query = db.query(AuditLog)
    if pii_detected is not None:
        query = query.filter(AuditLog.pii_detected == pii_detected)
    if compliance_status is not None:
        query = query.filter(AuditLog.compliance_status == compliance_status)
    if estado is not None:
        query = query.filter(AuditLog.model != "license")
        query = query.filter(~AuditLog.compliance_status.like("rejected%"))
        if estado == "bloqueados":
            query = query.filter(AuditLog.compliance_status.like("blocked%"))
        else:
            query = query.filter(~AuditLog.compliance_status.like("blocked%"))
    if from_date:
        query = query.filter(AuditLog.timestamp >= datetime.fromisoformat(from_date))
    if to_date:
        query = query.filter(AuditLog.timestamp <= datetime.fromisoformat(to_date))
    return query


def vistas(marcas):
    """Las combinaciones de filtros que la pantalla ofrece de verdad.

    No es una matriz exhaustiva: es el recorrido del officer (los dos baldes, el listado sin
    filtro con el que compara, la composición con los filtros previos y el rango de fechas del
    informe mensual). Cada una viaja a la API y al oráculo con los MISMOS parámetros.
    """
    corte = marcas[SEMILLA[_CORTE][0]][1].isoformat()
    return [
        ("sin filtro", {}),
        ("bloqueados", {"estado": "bloqueados"}),
        ("permitidos", {"estado": "permitidos"}),
        ("bloqueados + estado exacto", {"estado": "bloqueados",
                                        "compliance_status": "blocked_secret"}),
        # El eslabón de licencia pedido por su estado exacto: el filtro `estado` tiene que
        # seguir sacándolo aunque el officer escriba el literal a mano.
        ("bloqueados + estado de la cadena", {"estado": "bloqueados",
                                              "compliance_status": "blocked_by_policy"}),
        ("permitidos + sin PII", {"estado": "permitidos", "pii_detected": False}),
        ("bloqueados desde el corte", {"estado": "bloqueados", "from_date": corte}),
        ("permitidos hasta el corte", {"estado": "permitidos", "to_date": corte}),
    ]


def ids_api(client, params):
    payload = client.get(LOGS, params={**params, "limit": 100}).json()
    return payload["total"], {fila["id"] for fila in payload["logs"]}


def ids_oraculo(db, params):
    filas = _vitrina_pre_refactor(db, **params).all()
    return len(filas), {str(fila.id) for fila in filas}


def nombres(marcas, ids):
    """ids → marcas, para que el assert que falla diga «bloq_secret» y no un UUID."""
    inverso = {fila_id: marca for marca, (fila_id, _) in marcas.items()}
    return sorted(inverso.get(fila_id, fila_id) for fila_id in ids)


# ── Red 1: paridad contra el oráculo congelado ────────────────────────────────────────


# Los nombres van sueltos porque `parametrize` se evalúa al importar el módulo, cuando todavía
# no hay fixture ni semilla. `test_no_quedo_ninguna_vista_sin_comparar` los ata a `vistas()`:
# agregar una vista y olvidarse de parametrizarla —o sea, refactorizar una parte de la pantalla
# que nadie compara— pone el archivo en rojo.
VISTAS_COMPARADAS = (
    "sin filtro",
    "bloqueados",
    "permitidos",
    "bloqueados + estado exacto",
    "bloqueados + estado de la cadena",
    "permitidos + sin PII",
    "bloqueados desde el corte",
    "permitidos hasta el corte",
)


def test_no_quedo_ninguna_vista_sin_comparar(harness):
    _, _, marcas = harness
    assert [nombre for nombre, _ in vistas(marcas)] == list(VISTAS_COMPARADAS)


@pytest.mark.parametrize("nombre", VISTAS_COMPARADAS)
def test_cada_vista_devuelve_exactamente_las_mismas_filas_que_antes(harness, nombre):
    """Fila por fila, no conteo por conteo.

    Dos baldes pueden tener el mismo total con filas distintas adentro —basta con que una fila
    entre y otra salga— y el officer que audita un caso concreto lo descubriría antes que
    nosotros. Comparar por id cierra esa puerta.
    """
    client, factory, marcas = harness
    params = dict(vistas(marcas))[nombre]
    db = factory()
    try:
        total_esperado, ids_esperados = ids_oraculo(db, params)
    finally:
        db.close()
    total, ids = ids_api(client, params)
    assert nombres(marcas, ids) == nombres(marcas, ids_esperados), (
        f"la vista «{nombre}» cambió de filas con el refactor"
    )
    assert total == total_esperado


def test_el_export_arrastra_las_mismas_filas_que_el_listado(harness):
    """El CSV sale del MISMO `_build_query`, así que el refactor lo toca igual. Si la paridad
    se rompiera sólo acá, el informe que el officer manda por mail diría una cosa y la pantalla
    otra — y el que queda escrito en el expediente es el CSV."""
    client, factory, marcas = harness
    for estado in ("bloqueados", "permitidos"):
        db = factory()
        try:
            _, ids_esperados = ids_oraculo(db, {"estado": estado})
        finally:
            db.close()
        cuerpo = client.get(EXPORT, params={"estado": estado}).text
        filas = list(csv.reader(io.StringIO(cuerpo)))
        ids_csv = {fila[0] for fila in filas[1:] if fila}
        assert nombres(marcas, ids_csv) == nombres(marcas, ids_esperados), (
            f"el export de «{estado}» dejó de coincidir con el listado"
        )


# ── Red 2: los números de oro ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("estado", ["bloqueados", "permitidos"])
def test_los_dos_baldes_tienen_las_filas_que_alguien_decidio(harness, estado):
    """Expectativas escritas a mano, no derivadas del oráculo.

    Es la red que queda si alguien, viendo el test 1 en rojo, decide «arreglar» el oráculo. Un
    literal de `ESPERADO` no se puede tocar sin escribir con todas las letras que esa fila
    cambia de balde — que es exactamente la conversación que este test existe para forzar.
    """
    client, _, marcas = harness
    total, ids = ids_api(client, {"estado": estado})
    assert nombres(marcas, ids) == sorted(ESPERADO[estado])
    assert total == len(ESPERADO[estado])


def test_los_baldes_particionan_el_trafico_sin_huecos_ni_solapes(harness):
    """`bloqueados` + `permitidos` = todo el universo del filtro, y ni una fila en los dos.

    Es la propiedad que hace que la pantalla se pueda leer: si una fila cayera en ambos, el
    officer sumaría dos baldes y le daría más que el total; si no cayera en ninguno sin ser
    licencia ni rechazo, habría tráfico invisible en la vista filtrada.
    """
    client, _, marcas = harness
    _, bloqueados = ids_api(client, {"estado": "bloqueados"})
    _, permitidos = ids_api(client, {"estado": "permitidos"})
    assert bloqueados & permitidos == set()

    fuera = {marca for marca in marcas if marca.startswith(("rech_", "lic_"))}
    universo = {marcas[marca][0] for marca in marcas if marca not in fuera}
    assert bloqueados | permitidos == universo


def test_la_cadena_de_licencias_no_entra_en_ninguno_de_los_dos_baldes(harness):
    """FR-010 + regla 2 del contrato del clasificador, sobre los TRES estados con los que la
    cadena se persiste de verdad y sobre sus DOS formas. El feo es `lic_bloqueada`: matchea
    `LIKE 'blocked%'` y sólo la exclusión de la cadena lo saca. Sin ella, «se venció la licencia
    del deployment» aparecería junto a «alguien intentó pegar el padrón de socios».

    Las tres primeras las emitió `emit_license_event`, así que lo que se afirma sobre ellas es
    que la pantalla excluye la cadena que el producto ESCRIBE hoy — no una forma de
    laboratorio. `lic_pre_us5` cubre la otra forma legítima, la del 16→20-jul, que ningún
    emisor de hoy puede producir y que es la que el dictamen del 14-ago midió colándose en
    «bloqueados» cuando la exclusión pedía el `seq`."""
    client, _, marcas = harness
    _, bloqueados = ids_api(client, {"estado": "bloqueados"})
    _, permitidos = ids_api(client, {"estado": "permitidos"})
    de_la_cadena = [marca for marca, _, _ in CADENA + CADENA_PRE_US5]
    for marca in de_la_cadena:
        fila_id = marcas[marca][0]
        assert fila_id not in bloqueados and fila_id not in permitidos, marca

    # Y siguen VISIBLES sin filtro: la exclusión es de un filtro de tráfico, no un borrado de
    # la pantalla. La cadena es auditoría durable y el officer tiene que poder verla.
    _, todo = ids_api(client, {})
    assert {marcas[marca][0] for marca in de_la_cadena} <= todo


def test_los_rechazos_nuestros_siguen_fuera_de_los_dos_y_visibles_sin_filtro(harness):
    """Gate #135 (H4) e issue #157. Capacidad y presupuesto no son política: no se cuentan
    como bloqueo. Y el pedido nunca se sirvió: tampoco como permitido. `rech_futuro` clava que
    la exclusión sigue siendo de prefijo — si degenerara en una lista de dos literales, el
    próximo rechazo con nombre propio caería callado en «permitidos»."""
    client, _, marcas = harness
    _, bloqueados = ids_api(client, {"estado": "bloqueados"})
    _, permitidos = ids_api(client, {"estado": "permitidos"})
    _, todo = ids_api(client, {})
    for marca in ("rech_saturado", "rech_budget", "rech_futuro"):
        fila_id = marcas[marca][0]
        assert fila_id not in bloqueados, marca
        assert fila_id not in permitidos, marca
        assert fila_id in todo, marca


# ── Red 3: la vitrina no tiene criterio propio ────────────────────────────────────────
#
# Estos cuatro son la razón de ser del refactor, y los únicos que se caen si alguien vuelve a
# inlinear un `LIKE 'blocked%'` en `api/audit.py`: con el criterio copiado, la paridad seguiría
# verde (mismo resultado) y la fuente única sería mentira.
#
# El mecanismo: se mueve el literal EN EL CLASIFICADOR y se exige que la pantalla se mueva con
# él. Funciona porque `api/audit.py` importa las primitivas (`es_bloqueo`…) y no los literales,
# y cada primitiva lee su constante de módulo en el momento de construir el predicado.
#
# Son CUATRO y no tres porque el cuarto no prueba que la vitrina SIGA algo, sino que NO mira
# algo: la forma del eslabón. La 018 había llegado a exigirla (`es_licencia()` = literal **y**
# `seq`) y el dictamen del 14-ago (punto b) lo revirtió, así que la ausencia de esa condición
# pasó a ser una decisión con motivo escrito — y una decisión sin test se deshace sola en el
# próximo refactor. Ver `test_la_vitrina_no_mira_la_forma_del_eslabon`.


def test_la_vitrina_sigue_al_clasificador_en_que_es_un_bloqueo(harness, monkeypatch):
    client, _, marcas = harness
    monkeypatch.setattr("src.services.retention.classifier.PREFIJO_BLOQUEADO", "flagged")
    _, ids = ids_api(client, {"estado": "bloqueados"})
    assert nombres(marcas, ids) == ["perm_flagged"], (
        "la pantalla no siguió al clasificador: tiene criterio propio de bloqueo"
    )


def test_la_vitrina_sigue_al_clasificador_en_que_es_un_rechazo(harness, monkeypatch):
    client, _, marcas = harness
    monkeypatch.setattr("src.services.retention.classifier.PREFIJO_RECHAZADO", "passed")
    _, ids = ids_api(client, {"estado": "permitidos"})
    assert "perm_passed" not in nombres(marcas, ids), (
        "la pantalla no siguió al clasificador: tiene criterio propio de rechazo"
    )
    assert "rech_saturado" in nombres(marcas, ids)


def test_la_vitrina_sigue_al_clasificador_en_el_modelo_que_marca_la_cadena(harness, monkeypatch):
    """El literal del modelo, que desde el dictamen del 14-ago es la exclusión ENTERA.

    Se le dice al clasificador que la cadena ya no se llama `license` y se exige que la
    pantalla suelte las filas que venía excluyendo. Que `lic_bloqueada` —un eslabón REAL,
    emitido por la 021, con `blocked_by_policy`— reaparezca en el balde es la prueba de que la
    exclusión la decide el clasificador y no una copia del literal en `api/audit.py`.

    La segunda mitad del test volvió a la semántica de `main` en la ronda del 14-ago, y el
    motivo se escribe acá porque es lo contrario de lo que decía: mientras la vitrina exigió
    ADEMÁS el `seq` (`es_licencia()`), mover el literal a `gpt-4o` NO sacaba a las filas
    `gpt-4o` del balde —son tráfico y no traen eslabón—, y este test lo afirmaba. Con la
    exclusión por literal pelado sí se van, porque el literal es todo lo que se mira. Afirmarlo
    no es cosmética: es lo que distingue «la pantalla lee el literal DEL CLASIFICADOR» de «la
    pantalla tiene su propio `!= 'license'` escrito al lado» — con una copia local, mover la
    constante no movería ninguna de estas filas.
    """
    client, _, marcas = harness
    monkeypatch.setattr("src.services.retention.classifier.MODELO_LICENCIA", "gpt-4o")
    marcas_vistas = nombres(marcas, ids_api(client, {"estado": "bloqueados"})[1])
    assert "lic_bloqueada" in marcas_vistas, (
        "la pantalla no siguió al clasificador: tiene criterio propio de exclusión por modelo"
    )
    for marca in ("bloq_secret", "bloq_sin_guion", "bloq_pelado"):
        assert marca not in marcas_vistas, (
            f"«{marca}» dice `gpt-4o`, que es lo que el clasificador llama ahora «el modelo de "
            "la cadena», y siguió en el balde: la vitrina no está leyendo ese literal del "
            "clasificador"
        )


def test_la_vitrina_no_mira_la_forma_del_eslabon(harness, monkeypatch):
    """El cuarto, por la negativa: la exclusión de la vitrina NO depende del `seq`.

    **Este test decía lo contrario hasta el 14-ago, y esto es por qué se dio vuelta.** Se
    llamaba `..._sigue_al_clasificador_en_la_forma_del_eslabon` y exigía que, cambiándole al
    clasificador la clave con la que reconoce un eslabón, las filas de la cadena CAYERAN en los
    baldes: era la mitad 2 de `es_licencia()` (literal **y** `seq`), la exclusión que la 018
    probó. El dictamen del manager del 14-ago (punto b) la revirtió y la vitrina volvió al
    literal pelado de `main`, porque con el `seq` en la exclusión una fila de licencia LEGÍTIMA
    pre-US5 —`event_type`, sin `seq`— se le muestra al officer entre los bloqueos. La regla que
    quedó:

        purga = por forma (irreversible → no confía en nadie); vitrina = por literal
        (reversible → y el literal ya es nuestro gracias a la Capa B)

    O sea que la afirmación correcta hoy es la simétrica: se mueve la clave y NO se mueve NADA.
    Las cuatro filas de la cadena —las tres emitidas y la histórica, que ni siquiera trae `seq`
    para empezar— siguen fuera de los dos baldes.

    Y muerde igual que el anterior, por el otro lado: si alguien vuelve a meter la condición del
    `seq` en `api/audit.py` (o revierte la vitrina a `~es_licencia()`), patchear esta constante
    empieza a mover filas y el test se pone rojo EN EL ACTO — que es lo que le faltó a la
    decisión de la ronda anterior, tomada sin test que la sostuviera.

    `CLAVE_SEQ_CADENA` y no `MARCAS_DE_LA_CADENA`: la tupla se arma al importar el módulo y
    patchear la constante no la reescribe. Es la constante que lee `_trae_seq_de_cadena()`, o
    sea la puerta por la que la vitrina llegaría si volviera a `es_licencia()`; conviene saberlo
    antes de copiar este patrón para el portón de la purga, que sí usa la tupla.
    """
    client, _, marcas = harness
    de_la_cadena = [marca for marca, _, _ in CADENA + CADENA_PRE_US5]
    antes = {estado: ids_api(client, {"estado": estado})[1]
             for estado in ("bloqueados", "permitidos")}

    monkeypatch.setattr("src.services.retention.classifier.CLAVE_SEQ_CADENA",
                        "clave_que_ningun_eslabon_trae")

    for estado, ids_previos in antes.items():
        _, ids = ids_api(client, {"estado": estado})
        assert nombres(marcas, ids) == nombres(marcas, ids_previos), (
            f"el balde «{estado}» cambió al mover la clave del eslabón: la vitrina volvió a "
            "mirar la FORMA de `guardian_events`, y con eso una licencia legítima pre-US5 se "
            "le muestra al officer entre los bloqueos (dictamen 14-ago, punto b)"
        )
        for marca in de_la_cadena:
            assert marcas[marca][0] not in ids, marca


# HALLAZGO anotado acá para que no se pierda (NO se arregla en T005, cuyo criterio es paridad
# exacta): el balde «permitidos» de la vitrina incluye hoy `cfg_nlp_fail_mode` —un cambio de
# configuración auditado— y `perm_inedito` —un literal que nadie inventarió—. Ninguno de los
# dos es tráfico que el firewall haya permitido: el primero es un evento de configuración
# (clase `config_audit`, 730 d en el clasificador) y el segundo es, por definición, algo de lo
# que no se sabe nada. Es el mismo modo de falla que la exclusión de licencias vino a cerrar,
# con otro literal. Cambiarlo mueve un número que el officer ya viene mirando, así que es
# decisión de producto, no del refactor.
