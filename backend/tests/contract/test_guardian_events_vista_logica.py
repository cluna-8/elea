"""`guardian_events`: lo que se GUARDA cambió, lo que la API EXPONE no (spec 018).

El plano de escritura (`api/chat.py`) mete los eventos que devuelve el motor dentro de un
sobre nuestro: una fila de tráfico pasa de guardar `[ev1, ev2, …]` a guardar
`[{"upstream": [ev1, ev2, …]}]`. El motivo es de ALMACENAMIENTO y está escrito largo en
`api/audit.py`: la posición 0 de esa columna decide si el clasificador de retención trata la
fila como eslabón de la hash-chain de licencias (`guardian_events[0]` con clave `seq`), y
mientras el blob viajara pelado esa posición la elegía el upstream — o sea alguien de afuera.

Este archivo fija la OTRA mitad del trato: **el sobre es invisible desde la API**. Una fila
con el blob anidado sale con la misma forma y el mismo conteo que una fila equivalente sin
anidar, en las tres superficies que exponen el campo:

1. el listado de auditoría (`GET /audit-logs`),
2. la columna `guardian_events_count` del export CSV,
3. el contexto de las revisiones pendientes (`GET /compliance/review/pending`).

Por qué muerde de verdad y no es un test de tautología: las dos pantallas que consumen esto
NO leen la base. `AuditPage.tsx:218` llama `api.getAuditLogs()` y `CompliancePage.tsx:112-118`
llama `api.getPendingReviews()`; ambas cuentan `guardian_events.length` para decirle al
officer cuántos guardianes se activaron en ese pedido. Sin la desenvoltura en esta frontera,
el número es 1 en TODA fila con sobre —pase lo que pase— y el detalle dibuja un objeto
`{upstream: […]}` donde iban los eventos. No revienta nada: simplemente el informe de este mes
cuenta otra cosa que el del mes pasado, con la misma etiqueta. Si alguien saca la
desenvoltura, los tests de pares de acá abajo se ponen rojos.

La semilla se escribe por base directa y no haciendo pasar un pedido por `/chat`: lo que se
prueba es el contrato de LECTURA contra las dos formas del dato —la vieja, que sigue viva en
todas las filas ya escritas, y la nueva—, y ninguna corrida de `/chat` puede producir las dos.
"""
import csv
import io
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Los harness de DB viven en `tests/` y `tests/integration/` (pytest solo agrega al path el
# directorio del módulo que colecta, así que desde `tests/contract/` no se ven).
_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_guardian_events_vista_logica"
LOGS = "/api/v1/audit-logs"
EXPORT = "/api/v1/audit-logs/export"
PENDIENTES = "/api/v1/compliance/review/pending"

# Eventos del MOTOR: son los que viajan dentro del sobre.
EV_PII = {"guardian": "Presidio", "action": "MASK", "detail": "PERSON x2"}
EV_TOXICO = {"guardian": "Lakera", "action": "FLAG", "detail": "toxicity 0.71"}

# Disparo NUESTRO (`guardian_service.py:225` y siguientes). Va delante de los del motor en la
# misma columna: `chat.py:1659` concatena los dos orígenes.
DISPARO_PROPIO = {"guardian": "Secret Detector", "action": "REDACT", "detail": "Redactada clave"}

# Eslabón de la hash-chain de licencias (021), con la forma que persiste `_append_chained`.
# Es un objeto en la posición 0 y NO es un sobre: tiene que salir intacto.
ESLABON = {"event_type": "license_loaded", "seq": 1, "hash": "deadbeef"}

# Clave del sobre escrita a mano, sin importar `api.audit`: si el lector y el test sacaran el
# literal de la misma constante, renombrarla de las dos puntas a la vez pasaría el test con la
# desenvoltura rota para todas las filas ya escritas en la base del cliente.
CLAVE = "upstream"


def sobre(eventos):
    return {CLAVE: eventos}


# (marca, model, lo que se GUARDA, la vista LÓGICA que la API debe devolver).
#
# La marca es la identidad de la fila dentro del test: es lo que se lee cuando un assert falla,
# en vez de un UUID.
SEMILLA = [
    # El par que define el contrato: mismo contenido lógico, las dos formas de guardarlo.
    ("plano", "claude-3-5-sonnet-20241022", [EV_PII, EV_TOXICO], [EV_PII, EV_TOXICO]),
    ("anidado", "claude-3-5-sonnet-20241022", [sobre([EV_PII, EV_TOXICO])], [EV_PII, EV_TOXICO]),
    # El mismo par pero con un disparo NUESTRO delante, que es la fila realista cuando además
    # actuó un guardián de piso. Sin este caso, una desenvoltura que sólo contemple la lista de
    # un único sobre pasaría el test y dejaría el sobre a la vista justo en las filas
    # interesantes.
    ("mixto_plano", "ollama-qwen3-4b", [DISPARO_PROPIO, EV_PII, EV_TOXICO],
     [DISPARO_PROPIO, EV_PII, EV_TOXICO]),
    ("mixto_anidado", "ollama-qwen3-4b", [DISPARO_PROPIO, sobre([EV_PII, EV_TOXICO])],
     [DISPARO_PROPIO, EV_PII, EV_TOXICO]),
    # Pedido sin ningún evento. El sobre vacío no lo emite el plano de escritura de hoy (sólo
    # envuelve si hubo eventos del motor), y por eso mismo está acá: es la forma que nadie
    # mira. Si mañana el envoltorio se vuelve incondicional, «cero guardianes» no puede
    # empezar a contar como «1» sin que nadie lo note.
    ("vacio", "gpt-4o", [], []),
    ("vacio_anidado", "gpt-4o", [sobre([])], []),
    # Columna nullable: `null` es «no hay dato», distinto de «lista vacía», y la API lo viene
    # devolviendo así. La desenvoltura no normaliza — normalizar sería cambiar la forma que se
    # promete no cambiar.
    ("nulo", "gpt-4o", None, None),
    # Eslabón de licencia: la vitrina lo muestra y la desenvoltura no lo puede tocar.
    ("cadena", "license", [ESLABON], [ESLABON]),
    # Un objeto que TIENE la clave del sobre pero también otras: es un evento del motor que
    # casualmente habla de un upstream, no un sobre nuestro. Sale entero. Clava que el
    # reconocimiento del sobre es por forma exacta y no por «tiene una clave que se llama así»
    # — que además es la puerta por la que el de afuera desarmaría el lector a pedido.
    ("impostor", "gpt-4o", [{CLAVE: [EV_PII], "seq": 3}], [{CLAVE: [EV_PII], "seq": 3}]),
]

# Los pares equivalentes: (forma vieja, forma nueva). Son el corazón del archivo — cada uno
# afirma que las dos filas son indistinguibles desde afuera.
PARES = [
    ("plano", "anidado"),
    ("mixto_plano", "mixto_anidado"),
    ("vacio", "vacio_anidado"),
]


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    client.headers.update(admin_headers(client))
    marcas = sembrar(factory)
    yield client, factory, marcas
    cleanup()


def sembrar(factory):
    """Una fila de auditoría por marca + una revisión pendiente colgada de cada una.

    La revisión es lo que hace visible la fila en `/compliance/review/pending`, que es la
    tercera superficie. Devuelve {marca: str(id)}.
    """
    from src.models.audit import AuditLog
    from src.models.compliance import HumanReview
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    marcas = {}
    try:
        db.query(HumanReview).delete()
        db.query(AuditLog).delete()
        base = datetime.utcnow() - timedelta(minutes=len(SEMILLA))
        for i, (marca, modelo, guardado, _esperado) in enumerate(SEMILLA):
            fila = AuditLog(
                id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID,
                timestamp=base + timedelta(minutes=i), model=modelo,
                prompt_tokens=11, completion_tokens=7, cost_usd=0,
                pii_detected=False, compliance_status="passed", latency_ms=9,
                guardian_events=guardado,
            )
            db.add(fila)
            db.add(HumanReview(
                id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, audit_log_id=fila.id,
                review_token=uuid.uuid4(), response_text=f"respuesta {marca}",
            ))
            marcas[marca] = str(fila.id)
        db.commit()
        return marcas
    finally:
        db.close()


ESPERADO = {marca: esperado for marca, _m, _g, esperado in SEMILLA}


def listado(client, marcas):
    """{marca: guardian_events} tal como sale del listado."""
    payload = client.get(LOGS, params={"limit": 100}).json()
    por_id = {fila["id"]: fila["guardian_events"] for fila in payload["logs"]}
    assert len(por_id) == len(SEMILLA), "la semilla no llegó entera al listado"
    return {marca: por_id[fila_id] for marca, fila_id in marcas.items()}


def conteos_csv(client, marcas):
    """{marca: guardian_events_count} tal como sale del export."""
    filas = list(csv.reader(io.StringIO(client.get(EXPORT).text)))
    cabecera, cuerpo = filas[0], [f for f in filas[1:] if f]
    columna = cabecera.index("guardian_events_count")
    por_id = {f[0]: int(f[columna]) for f in cuerpo}
    assert len(por_id) == len(SEMILLA), "la semilla no llegó entera al export"
    return {marca: por_id[fila_id] for marca, fila_id in marcas.items()}


def revisiones(client, marcas):
    """{marca: context.guardian_events} tal como sale de las revisiones pendientes."""
    por_id = {r["audit_log_id"]: r["context"]["guardian_events"] for r in client.get(PENDIENTES).json()}
    assert len(por_id) == len(SEMILLA), "la semilla no llegó entera a las revisiones pendientes"
    return {marca: por_id[fila_id] for marca, fila_id in marcas.items()}


# ── El contrato: la fila anidada es indistinguible de la plana ────────────────────────


@pytest.mark.parametrize("viejo,nuevo", PARES)
def test_el_listado_devuelve_la_misma_forma_para_las_dos(harness, viejo, nuevo):
    client, _, marcas = harness
    vistas = listado(client, marcas)
    assert vistas[nuevo] == vistas[viejo], (
        f"«{nuevo}» (blob anidado) sale distinto de «{viejo}» (mismo contenido sin anidar): "
        f"el sobre de almacenamiento se está filtrando al listado que lee AuditPage"
    )


@pytest.mark.parametrize("viejo,nuevo", PARES)
def test_el_csv_cuenta_lo_mismo_para_las_dos(harness, viejo, nuevo):
    """`guardian_events_count` significa «cuántos guardianes se activaron», no «cuántos
    elementos tiene el jsonb». Contando lo guardado, toda fila con sobre da 1 y la columna
    cambia de significado sin cambiar de nombre, en un export que el officer archiva."""
    client, _, marcas = harness
    conteos = conteos_csv(client, marcas)
    assert conteos[nuevo] == conteos[viejo], (
        f"el export cuenta {conteos[nuevo]} eventos en «{nuevo}» y {conteos[viejo]} en "
        f"«{viejo}», que tienen los mismos eventos guardados de otra forma"
    )


@pytest.mark.parametrize("viejo,nuevo", PARES)
def test_la_revision_pendiente_desenvuelve_igual(harness, viejo, nuevo):
    client, _, marcas = harness
    contextos = revisiones(client, marcas)
    assert contextos[nuevo] == contextos[viejo], (
        f"el contexto de revisión de «{nuevo}» sale distinto del de «{viejo}»: el revisor "
        f"vería otra cantidad de guardianes según cómo se guardó la fila"
    )


# ── Los valores de oro: qué es exactamente la vista lógica ────────────────────────────
#
# Los tres tests de pares afirman «las dos filas dan lo mismo», y eso solo lo cumpliría también
# una desenvoltura que rompiera las DOS por igual. Estos dos clavan el contenido a mano.


@pytest.mark.parametrize("marca", [m for m, *_ in SEMILLA])
def test_cada_fila_sale_con_sus_eventos_logicos(harness, marca):
    client, _, marcas = harness
    assert listado(client, marcas)[marca] == ESPERADO[marca]


@pytest.mark.parametrize("marca", [m for m, *_ in SEMILLA])
def test_el_csv_cuenta_los_eventos_logicos(harness, marca):
    client, _, marcas = harness
    assert conteos_csv(client, marcas)[marca] == len(ESPERADO[marca] or [])


@pytest.mark.parametrize("marca", [m for m, *_ in SEMILLA])
def test_la_revision_pendiente_trae_los_eventos_logicos(harness, marca):
    client, _, marcas = harness
    assert revisiones(client, marcas)[marca] == ESPERADO[marca]


# ── Las dos guardas de la defensa ─────────────────────────────────────────────────────


def test_la_desenvoltura_es_UNA(harness):
    """Los tres consumidores llaman a la misma función, no a tres copias sincronizadas a mano.

    Tres desarmados paralelos son tres oportunidades de que uno quede viejo el día que el sobre
    cambie, y el que quedara viejo no rompería nada visible: devolvería un número plausible y
    distinto del de los otros dos. Se afirma por identidad del objeto función, así que mudar el
    helper a un módulo compartido sigue pasando; lo único que pone esto en rojo es que aparezca
    una SEGUNDA implementación.
    """
    from src.api import audit, compliance
    assert compliance.desenvolver_eventos_guardian is audit.desenvolver_eventos_guardian


def test_este_lector_entiende_el_sobre_que_el_escritor_produce_hoy():
    """El único punto donde las dos puntas se miran, y a propósito no es la desenvoltura.

    La desenvoltura NO importa la clave del plano de escritura: tiene que saber desarmar las
    filas ya escritas, que no cambian de forma porque `chat.py` cambie de opinión (el porqué,
    en `api/audit.py`). Pero entre «el lector entiende el pasado» y «el lector entiende lo que
    se está escribiendo AHORA» hay un hueco: si el escritor estrenara otro sobre, la vitrina
    dejaría de desenvolver las filas nuevas y los tests de arriba —que siembran la forma a
    mano— seguirían verdes. Esto es la alarma de ese hueco, y se lee al revés de como se
    escribió: sea cual sea el sobre, desenvolverlo tiene que devolver la concatenación llana
    que la fila tenía antes de que el sobre existiera.

    Si un día esto falla por `ImportError`, no se borra: se mira qué produce el escritor ahora
    y se decide si la vitrina tiene que aprender esa forma NUEVA además de la vieja.
    """
    from src.api.audit import desenvolver_eventos_guardian
    from src.api.chat import _eventos_de_la_fila
    casos = [
        ([], [EV_PII, EV_TOXICO]),                    # sólo el motor: el caso normal
        ([DISPARO_PROPIO], [EV_PII, EV_TOXICO]),      # los dos orígenes
        ([DISPARO_PROPIO], []),                       # sólo nosotros
        ([], []),                                     # pedido limpio
    ]
    for triggers, upstream in casos:
        assert desenvolver_eventos_guardian(_eventos_de_la_fila(triggers, upstream)) == \
            triggers + upstream, (
                f"la vitrina no desenvuelve lo que `chat.py` escribe para "
                f"triggers={triggers!r} upstream={upstream!r}"
            )


def test_leer_la_vitrina_no_desarma_el_sobre_en_la_base(harness):
    """La desenvoltura es de PRESENTACIÓN: el blob guardado no se toca.

    Lo que protege la posición 0 de esa columna del upstream es el sobre EN DISCO — de ahí lo
    leen el clasificador de retención y `verify_chain`. Si la vitrina desenvolviera sobre la
    instancia ORM, SQLAlchemy podría flushear el blob desarmado de vuelta a la base y una
    pantalla de sólo lectura estaría desactivando una defensa de almacenamiento.
    """
    from src.models.audit import AuditLog
    client, factory, marcas = harness
    listado(client, marcas)
    conteos_csv(client, marcas)
    revisiones(client, marcas)
    db = factory()
    try:
        guardado = {
            str(fila.id): fila.guardian_events
            for fila in db.query(AuditLog).all()
        }
    finally:
        db.close()
    for marca, _modelo, esperado_en_disco, _vista in SEMILLA:
        assert guardado[marcas[marca]] == esperado_en_disco, (
            f"la fila «{marca}» cambió en la base después de leerla por la API"
        )
