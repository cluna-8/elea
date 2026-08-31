"""Filtro «Bloqueados» del listado de auditoría (spec 031, T007-API — FR-006).

Antes de la 031, aislar los intentos IMPEDIDOS exigía que el officer supiera de memoria los
valores de `compliance_status` (`blocked_prohibited`, `blocked_secret`, …) y los filtrara de
a uno, o que los dedujera de «0/0 tokens». Con la convención D1 (prefijo `blocked_`) el
filtro canónico es uno solo: `LIKE 'blocked%'`.

Los invariantes que se fijan acá:

1. **`estado=bloqueados` devuelve TODOS los bloqueos y sólo bloqueos**, sin importar el
   motivo — el officer no tiene que conocer el vocabulario interno para encontrar lo que
   busca (SC-001/SC-005).
2. **Los eslabones de la hash-chain de licencias quedan fuera** (FR-010). No es un detalle:
   varias transiciones de licencia se persisten con `compliance_status='blocked_by_policy'`
   (`licensing/audit_events.py:271`) y caen de lleno en `LIKE 'blocked%'`. Sin la exclusión
   por `model='license'`, la pantalla mezclaría «se venció la licencia del deployment» con
   «alguien intentó pegar el padrón de socios» — justo la confusión que el filtro existe
   para eliminar. La cadena no se toca: sólo se la deja fuera de un filtro de TRÁFICO.

   La exclusión es por el LITERAL pelado (`classifier.dice_licencia()`), como en `main`.
   Durante la 018 se probó pedirle DOS cosas —el literal **y** el `seq` del eslabón
   (`es_licencia()`)— y el dictamen del manager del 14-ago (punto b) lo revirtió: con el
   `seq` en la exclusión, una fila de licencia LEGÍTIMA anterior a la US5 de la 021 —trae
   `event_type` y NO trae `seq`— se le muestra al officer entre los bloqueos, mezclada con
   los intentos de fuga. La regla que quedó: la purga excluye por FORMA (irreversible) y esta
   pantalla por LITERAL (reversible, y el literal ya es nuestro gracias a la Capa B). El
   argumento entero está en el docstring de `api/audit.py::_build_query`.

   Consecuencia para este archivo: hay que sembrar las DOS formas de licencia que existen —la
   vigente por su emisor real y la histórica a mano, que ningún emisor de hoy puede producir—
   y exigir que las dos queden fuera de los dos baldes. Ver `sembrar`.
3. **Los rechazos por capacidad quedan fuera de los DOS baldes** (gate #135 H4, decisión JF
   12-ago). `rejected_saturated` (`services/engine_gate.py`) no empieza con `blocked` a
   propósito —capacidad no es política—, así que sin exclusión explícita caería en el `else`
   y se contaría como PERMITIDO: un pedido que nunca se sirvió, por causa nuestra, informado
   al cliente como servido. Su balde propio («Rechazados») llega en el ciclo 2; hasta
   entonces, fuera de ambos pero VISIBLE sin filtro `estado` (es auditoría durable).
"""
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

DB = "sentinel_test_audit_filtro_estado"
LOGS = "/api/v1/audit-logs"
EXPORT = "/api/v1/audit-logs/export"

# `compliance_status` del rechazo por capacidad. Literal y no import de `engine_gate`: lo que
# este archivo prueba es el CONTRATO de la pantalla contra el valor que se persiste, y un
# import haría pasar el test aunque la constante cambiara de las dos puntas a la vez.
SATURADO = "rejected_saturated"

# Un `rejected_*` que hoy NO existe en el código: clava que el contrato de exclusión es de
# PREFIJO, no de valor exacto. Si el criterio se degradara al literal (`PREFIJO_RECHAZADO` del
# clasificador; hasta la 018 era `RECHAZADO_LIKE` de `api/audit.py`), el próximo rechazo con
# nombre propio caería callado en «permitidos» — exactamente la mentira que H4 vino a cerrar,
# reabierta para el status siguiente (mutante sobreviviente del re-check).
RECHAZO_FUTURO = "rejected_timeout"

# (modelo, compliance_status, capa que bloqueó). Cubre los dos motivos de bloqueo que ya
# escribía el passthrough, uno nuevo del plano chat, tráfico permitido, un rechazo por
# capacidad (que no es ni una cosa ni la otra) y un segundo rechazo hipotético que clava el
# prefijo. TODO lo de acá es TRÁFICO: el eslabón de licencia —el caso feo, el que también
# empieza con `blocked`— ya no se arma a mano (ver `ESLABONES_DE_LICENCIA` y `sembrar`).
SEMILLA = [
    ("claude-3-5-sonnet-20241022", "blocked_secret", "secret_detection"),
    ("claude-3-5-sonnet-20241022", "blocked_prohibited", "ai_act_evaluation"),
    ("ollama-qwen3-4b", "blocked_guardian", "pii_masking"),
    ("claude-3-5-sonnet-20241022", "passed", None),
    ("ollama-qwen3-4b", "flagged_high_risk", None),
    ("ollama-qwen3-4b", SATURADO, None),
    ("claude-3-5-sonnet-20241022", RECHAZO_FUTURO, None),
]

# El eslabón de licencia sale del EMISOR REAL de la 021 (`emit_license_event`), no de un dict
# escrito acá. Es el hallazgo del gate del 13-ago: mientras esta semilla lo armó a mano
# —`model='license'` con `guardian_events=[]`— sembró una forma que el producto NUNCA emitió, y
# bajo la regla enmendada del clasificador esa fila es indistinguible de un spoof. Con razón:
# una fila de licencia REAL siempre trae su eslabón. O sea que el test venía pasando por una
# forma que sólo existía en el test; emitida por el emisor, la forma no puede divergir de
# producción sin que este archivo se entere el mismo día.
#
# El evento es `license_seat_limit_exceeded` porque NO figura en `_COMPLIANCE_BY_EVENT`
# (`audit_events.py:204-209`) y cae en el default `blocked_by_policy` — que es exactamente el
# caso feo que este archivo tiene que excluir: un eslabón que matchea `LIKE 'blocked%'`.
EVENTO_DE_LICENCIA = "license_seat_limit_exceeded"
ESTADO_DEL_ESLABON = "blocked_by_policy"
ESLABONES_DE_LICENCIA = 1

# ── La OTRA forma legítima de la cadena: la anterior a la US5 de la 021 ────────────────
#
# `(marca, event_type, compliance_status con el que el emisor de aquel momento la persistía)`.
#
# Ésta SÍ va a mano, y es la ÚNICA excepción a la regla del depto de «no inventar fixtures».
# El motivo, escrito para que no haya que adivinarlo: esta forma no la puede volver a producir
# ningún emisor de hoy. `_append_chained` escribe `prev_hash` y `seq` desde la US5 (9cd7b99,
# 20-jul) y no hay perilla para que no los escriba. Lo que se siembra acá es evidencia
# HISTÓRICA: filas escritas entre el 16 y el 20 de julio que están en la base de una
# instalación viva y que no se van a mover nunca. Sembrarlas llamando al emisor es imposible;
# la única fuente honesta es el fuente de aquel momento (8e8f705), de donde está copiada la
# forma —las MISMAS seis claves y ninguna más—, y de donde salen también los dos estados de
# abajo (`_COMPLIANCE_BY_EVENT` de entonces: `license_loaded` → `passed`, y todo lo que no
# figuraba en el mapa → el default `blocked_by_policy`).
#
# Van DOS y no una porque el invariante tiene dos mitades y una sola fila sólo ejercita una:
# la de `blocked_by_policy` es la que se cuela en «bloqueados» —el caso medido del dictamen,
# `total=1` donde `main` da `0`— y la de `passed` es la que se cuela en «permitidos». Con una
# sola, media afirmación del test pasaría por no tener candidato.
LICENCIAS_PRE_US5 = [
    ("pre_us5_bloqueada", "license_seat_limit_exceeded", "blocked_by_policy"),
    ("pre_us5_pasada", "license_loaded", "passed"),
]


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    client.headers.update(admin_headers(client))
    historicas = sembrar(factory)
    yield client, factory, historicas
    cleanup()


def sembrar(factory):
    """Tráfico por base directa; la cadena VIGENTE por su emisor; la HISTÓRICA a mano.

    Los tres criterios parecen inconsistentes y no lo son.

    El tráfico va por base directa porque lo que se prueba es la QUERY del listado, y hacer
    que cada plano emita su bloqueo convertiría este test en uno de integración de otros tres
    módulos.

    El eslabón VIGENTE va por `emit_license_event` por el motivo contrario: la forma de esa
    fila no es plomería, es evidencia de qué escribe el producto. Una forma escrita a mano en
    el test es una forma que nadie garantiza que exista — y es justo lo que pasó: la semilla
    anterior escribía `guardian_events=[]` en una fila de licencia, que ningún emisor de la 021
    produjo jamás. Emitida por el emisor real, no puede divergir de producción sin que este
    archivo se entere el mismo día.

    Las PRE-US5 van a mano porque no hay emisor que las pueda escribir hoy: el motivo entero
    está arriba, en `LICENCIAS_PRE_US5`, y es la única excepción declarada a la regla de no
    inventar fixtures.

    Devuelve marca → id (como string) de las filas históricas, que es lo único que los asserts
    necesitan nombrar por fuera de la semilla.
    """
    from src.licensing.audit_events import emit_license_event
    from src.models.audit import AuditLog
    from src.models.license_state import LicenseRuntimeState
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        db.query(AuditLog).delete()
        # La cadena arranca en cero para que el emisor escriba EXACTAMENTE
        # `ESLABONES_DE_LICENCIA` filas. Si la fila singleton ya existiera con génesis
        # 'unlicensed', el primer `license_id` con firma dispararía ADEMÁS el evento de
        # anclaje diferido (`audit_events.py:229-236`) y el listado tendría una fila de más
        # que nadie declaró.
        db.query(LicenseRuntimeState).delete()
        base = datetime.utcnow() - timedelta(minutes=len(SEMILLA))
        for i, (modelo, estado, capa) in enumerate(SEMILLA):
            db.add(AuditLog(
                id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID,
                timestamp=base + timedelta(minutes=i), model=modelo,
                prompt_tokens=0, completion_tokens=0, cost_usd=0,
                pii_detected=False, compliance_status=estado, latency_ms=7,
                blocked_by_layer=capa, guardian_events=[],
            ))
        db.commit()

        emit_license_event(db, EVENTO_DE_LICENCIA, license_id="lic_filtro_estado",
                           seats_used=26, max_seats=25,
                           reason="seats en uso por encima del máximo licenciado")

        # La semilla se verifica a sí misma. Sin esto, el día que el emisor cambie de estados
        # o de forma este archivo seguiría verde probando otro universo — que es exactamente
        # el modo de falla del que viene: una semilla que se creía realista y no lo era.
        filas = db.query(AuditLog).filter(AuditLog.model == "license").all()
        assert len(filas) == ESLABONES_DE_LICENCIA, (
            f"el emisor de la 021 escribió {len(filas)} filas y la semilla declara "
            f"{ESLABONES_DE_LICENCIA}")
        eslabon = filas[0].guardian_events[0]
        assert filas[0].compliance_status == ESTADO_DEL_ESLABON, (
            f"«{EVENTO_DE_LICENCIA}» dejó de persistirse como {ESTADO_DEL_ESLABON!r}: la "
            "semilla ya no cubre el caso feo (un eslabón que matchea LIKE 'blocked%')")
        assert "seq" in eslabon, (
            "el eslabón que emite la 021 dejó de traer `seq`: la fila pre-US5 de abajo ya no "
            "es un caso DISTINTO del vigente y este archivo dejó de cubrir los dos")

        return sembrar_pre_us5(db, DEFAULT_TENANT_ID)
    finally:
        db.close()


def sembrar_pre_us5(db, tenant_id):
    """Las filas de licencia LEGÍTIMAS del 16→20-jul, copiadas del fuente de 8e8f705.

    Las seis claves del `entry` de aquel emisor y ninguna más: sin `prev_hash` y sin `seq`,
    que llegaron con la US5 (9cd7b99). Es la forma que el dictamen del 14-ago midió colándose
    en el balde «bloqueados» cuando la vitrina exigía el `seq`, y la que este archivo tiene que
    ver excluida.

    El resto de las columnas van como las escribía aquel emisor (cero tokens, cero coste, cero
    latencia, sin PII, `model='license'`): así lo único que separa estas filas de un eslabón de
    hoy es la ausencia de las dos claves de la cadena, que es exactamente la variable medida.
    """
    from src.models.audit import AuditLog

    base = datetime.utcnow() - timedelta(hours=1)
    historicas = {}
    for i, (marca, evento, estado) in enumerate(LICENCIAS_PRE_US5):
        fila_id = uuid.uuid4()
        db.add(AuditLog(
            id=fila_id, tenant_id=tenant_id,
            timestamp=base + timedelta(seconds=i), model="license",
            prompt_tokens=0, completion_tokens=0, cost_usd=0,
            pii_detected=False, compliance_status=estado, latency_ms=0,
            blocked_by_layer=None,
            guardian_events=[{
                "event_type": evento,
                "license_id": "lic_filtro_estado",
                "seats_used": 26,
                "max_seats": 25,
                "reason": "seats en uso por encima del máximo licenciado",
                "ts": (base + timedelta(seconds=i)).isoformat(),
            }],
        ))
        historicas[marca] = str(fila_id)
    db.commit()

    # La semilla se verifica a sí misma, igual que la vigente: lo que hace ÚTIL a estas filas
    # es que NO traigan `seq`. Si alguien las «arreglara» copiándoles un eslabón entero, el
    # archivo seguiría verde sin cubrir el caso que el dictamen vino a cerrar.
    for marca, fila_id in historicas.items():
        fila = db.query(AuditLog).filter(AuditLog.id == uuid.UUID(fila_id)).one()
        evento = fila.guardian_events[0]
        assert "event_type" in evento and "seq" not in evento and "prev_hash" not in evento, (
            f"«{marca}» dejó de tener la forma pre-US5 (event_type sin seq ni prev_hash): "
            "este archivo ya no cubre la regresión del dictamen del 14-ago")
    return historicas


def estados(payload):
    return sorted(fila["compliance_status"] for fila in payload["logs"])


def test_sin_filtro_el_listado_no_cambia(harness):
    """Retrocompatibilidad: quien no manda `estado` sigue viendo todo (incluidos los
    eslabones de licencia —de las DOS formas—, que siempre estuvieron en esta pantalla)."""
    client, _, _ = harness
    payload = client.get(LOGS).json()
    assert payload["total"] == (len(SEMILLA) + ESLABONES_DE_LICENCIA
                                + len(LICENCIAS_PRE_US5))


def test_bloqueados_devuelve_todos_los_bloqueos_sin_conocer_el_vocabulario(harness):
    client, _, _ = harness
    payload = client.get(LOGS, params={"estado": "bloqueados"}).json()
    assert estados(payload) == ["blocked_guardian", "blocked_prohibited", "blocked_secret"]
    assert payload["total"] == 3


def test_bloqueados_no_arrastra_los_eslabones_de_licencia(harness):
    """FR-010: la hash-chain de la 021 no es tráfico bloqueado. Si esta afirmación se cae,
    el officer ve un «bloqueo» que ningún usuario provocó."""
    client, _, _ = harness
    payload = client.get(LOGS, params={"estado": "bloqueados"}).json()
    assert all(fila["model"] != "license" for fila in payload["logs"])
    assert "blocked_by_policy" not in estados(payload)


def test_la_licencia_pre_us5_tampoco_entra_en_ninguno_de_los_dos_baldes(harness):
    """La regresión que se nos escapó, y el motivo del dictamen del 14-ago (punto b).

    Una fila de licencia LEGÍTIMA anterior a la US5 de la 021 trae `event_type` y NO trae
    `seq`. Mientras la vitrina excluyó con `~es_licencia()` —literal **y** `seq`— esa fila
    dejaba de ser «de licencia» para la pantalla y caía en un balde por su
    `compliance_status`: la de `blocked_by_policy` aparecía entre los bloqueos, mezclada con
    los intentos de fuga de los usuarios (medido: `total=1` donde `main` da `0`), y la de
    `passed` entre los permitidos. Ninguna de las dos es tráfico: son transiciones del ciclo
    de vida del deployment.

    Con la exclusión por LITERAL las dos vuelven a quedar fuera, exactamente como en `main`.
    Se afirma por id y no por `compliance_status` porque los dos estados se repiten en el
    tráfico de la semilla: contar estados escondería justamente la fila que importa.

    Y la contracara, en el mismo test: quedan fuera del FILTRO, no de la pantalla. El listado
    sin `estado` las sigue mostrando — son auditoría durable y el officer las tiene que poder
    ver para explicar qué pasó con la licencia.
    """
    client, _, historicas = harness
    for balde in ("bloqueados", "permitidos"):
        vistos = {fila["id"] for fila in client.get(
            LOGS, params={"estado": balde}).json()["logs"]}
        for marca, fila_id in historicas.items():
            assert fila_id not in vistos, (
                f"«{marca}» —una licencia legítima pre-US5— apareció en el balde «{balde}». "
                "La exclusión de la vitrina volvió a pedir el `seq` del eslabón: el officer "
                "está viendo una transición de licencia mezclada con tráfico")

    todo = {fila["id"] for fila in client.get(LOGS).json()["logs"]}
    assert set(historicas.values()) <= todo, (
        "las licencias pre-US5 desaparecieron del listado sin filtro: la exclusión dejó de "
        "ser de un filtro de tráfico y pasó a esconder auditoría durable")


def test_la_fila_bloqueada_dice_que_capa_la_bloqueo(harness):
    """SC-005: quién/qué/cuándo/**qué capa**, sin abrir otra vista."""
    client, _, _ = harness
    payload = client.get(LOGS, params={"estado": "bloqueados"}).json()
    capas = {fila["compliance_status"]: fila["blocked_by_layer"] for fila in payload["logs"]}
    assert capas["blocked_secret"] == "secret_detection"
    assert capas["blocked_prohibited"] == "ai_act_evaluation"


def test_permitidos_es_el_complemento_y_tampoco_trae_licencias(harness):
    client, _, _ = harness
    payload = client.get(LOGS, params={"estado": "permitidos"}).json()
    assert estados(payload) == ["flagged_high_risk", "passed"]
    assert all(fila["model"] != "license" for fila in payload["logs"])


def test_el_rechazo_por_capacidad_no_se_cuenta_como_permitido(harness):
    """H4 del gate de #135. `rejected_saturated` no matchea `LIKE 'blocked%'` (capacidad ≠
    política), así que sin exclusión explícita caería en el `else` y se informaría como
    PERMITIDO. Ese pedido nunca se sirvió, y el motivo fue nuestro: contarlo entre los
    permitidos le miente al cliente justo en el número que más mira."""
    client, _, _ = harness
    payload = client.get(LOGS, params={"estado": "permitidos"}).json()
    assert SATURADO not in estados(payload)
    assert RECHAZO_FUTURO not in estados(payload)
    assert payload["total"] == 2


def test_el_rechazo_por_capacidad_tampoco_es_un_bloqueo(harness):
    """La otra mitad del mismo invariante: tampoco se lo infla como bloqueo. No lo impidió
    ninguna capa, no hubo dato personal ni secreto ni práctica prohibida. Su balde propio
    («Rechazados») llega en el ciclo 2; hasta entonces, fuera de los dos."""
    client, _, _ = harness
    payload = client.get(LOGS, params={"estado": "bloqueados"}).json()
    assert SATURADO not in estados(payload)
    assert RECHAZO_FUTURO not in estados(payload)
    assert payload["total"] == 3


def test_sin_filtro_el_rechazo_por_capacidad_sigue_visible(harness):
    """Dejarlo fuera del filtro binario no es esconderlo: la fila es auditoría durable y el
    officer tiene que poder verla para explicar por qué ese pedido no salió."""
    client, _, _ = harness
    payload = client.get(LOGS).json()
    assert SATURADO in estados(payload)
    assert RECHAZO_FUTURO in estados(payload)


def test_el_export_tampoco_vende_el_rechazo_como_permitido(harness):
    """El CSV sale del MISMO constructor de query: si la exclusión viviera sólo en el listado,
    el reporte que se manda por mail seguiría mintiendo."""
    client, _, _ = harness
    cuerpo = client.get(EXPORT, params={"estado": "permitidos"}).text
    assert SATURADO not in cuerpo
    assert RECHAZO_FUTURO not in cuerpo
    assert "passed" in cuerpo and "flagged_high_risk" in cuerpo


def test_un_estado_desconocido_falla_fuerte_en_vez_de_ignorarse(harness):
    """Un filtro que se ignora en silencio es peor que un error: el officer creería estar
    viendo SÓLO los bloqueos mientras mira la tabla entera."""
    client, _, _ = harness
    assert client.get(LOGS, params={"estado": "bloqueadas"}).status_code == 422


def test_el_filtro_convive_con_los_filtros_previos(harness):
    """`estado` se compone con el resto (AND), no los reemplaza."""
    client, _, _ = harness
    payload = client.get(LOGS, params={"estado": "bloqueados",
                                       "compliance_status": "blocked_secret"}).json()
    assert estados(payload) == ["blocked_secret"]


def test_el_export_honra_el_mismo_filtro(harness):
    """Un CSV que ignora el filtro visible es una trampa silenciosa: el officer exporta lo
    que ve."""
    client, _, _ = harness
    respuesta = client.get(EXPORT, params={"estado": "bloqueados"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.text
    assert "blocked_secret" in cuerpo and "blocked_prohibited" in cuerpo
    assert "blocked_by_policy" not in cuerpo   # el eslabón de licencia no es tráfico
    assert "passed" not in cuerpo
