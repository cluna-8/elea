"""Una fila deforme no puede tumbar la evidencia comercial (gate adversarial 018, HALLAZGO 2).

Los dos lectores de la hash-chain de licencias —`verify_chain` (`licensing/audit_events.py`) y
el export de true-up (`licensing/trueup_export.py`)— releen TODAS las filas `model='license'` y
hasta esta ronda decidían qué fila era un eslabón con `"seq" in r.guardian_events[0]`, sin mirar
de qué tipo era ese primer evento. Sobre un string, `in` busca SUBCADENA: `["seq"]` pasaba el
filtro —y `["consequence"]` también, sin nombrar la clave— y el `e["seq"]` siguiente levantaba
`TypeError: string indices must be integers`.

O sea: UNA fila deforme en `audit_logs` y el cliente se queda sin poder verificar su cadena y
sin poder generar el true-up con el que renueva. No es una verificación que da rojo —eso sería
un veredicto— es una que no da nada: un 500. Un lector de evidencia que se cae con una excepción
sin capturar en vez de reportar el problema es la mitad del incidente que FR-003 vino a evitar.

## Por qué esto entra a un PR con el alcance cerrado

La capa B (`gateway.sanear_modelo_declarado`, `api/internal.py`) sacó el literal reservado del
codominio de lo auditable en los dos escritores, así que DESDE AHORA ninguna fila nueva puede
declararse `license`. Lo que la capa B no puede hacer es sanear hacia atrás: en la base de un
cliente ya instalado puede haber filas viejas, y una sola alcanza. El saneo protege el futuro;
esta guarda es la que hace que el pasado no tumbe la verificación.

## Qué se afirma acá, y qué NO

Se siembran filas deformes junto a una cadena LEGÍTIMA de varios eslabones —emitida por el
emisor real de la 021, no por dicts a mano— y se exige que los dos lectores **sobrevivan y
sigan verificando la cadena buena**: `verify_chain` verde con `checked` EXACTO, y un true-up
firmado que el verificador lado-Sentinel acepta con los `seq` exactos que emitió el emisor.

`checked` exacto y no «al menos» porque el error simétrico también existe: adoptar la fila
ajena. Un `[{"seq": 1}]` adoptado hace que el export se lleve una fila que no es de la cadena, y
entonces el lado-Sentinel rechaza el true-up del cliente por «cadena interna inválida».

Lo que NO se prueba acá es que la guarda vuelva indulgente al verificador: por eso está el test
del final, que rompe un eslabón LEGÍTIMO deformándolo y exige que la cadena se ponga ROJA. Una
guarda que saltea filas puede convertirse en un lavadero de manipulaciones, y esa es exactamente
la línea que separa «saltear lo que no es un eslabón» de «no mirar».

## Forma que a propósito NO se siembra

`[{"seq": 1, "prev_hash": "0"*64}]` —un objeto BIEN formado con datos inventados— no está en la
lista. No es un problema de forma: por forma es indistinguible de un eslabón, y el que decide si
miente es el hash. Con esa fila viva la cadena acusa manipulación, y eso es el verificador
haciendo su trabajo, no el bug de este archivo. Hoy además no es alcanzable: `guardian_events`
no lo escribe el cliente en ninguno de los tres productores — lo clava, en
`test_retencion_dataset_abusivo.py`, el test
`test_ningun_escritor_deja_que_el_cliente_le_ponga_el_seq_a_su_propia_fila`.

## Que este archivo muerde está MEDIDO

Con la guarda revertida a mano (`"seq" in eventos[0]` sin `isinstance`), cada forma de `DEFORMES`
tumba a los dos lectores con la excepción que dice su tercera columna: de los 27 tests del
archivo se ponen rojos 26, y no con un assert sino con `TypeError`/`KeyError` — que es
exactamente el punto, porque una excepción sin capturar en un lector de evidencia no es un
veredicto, es un 500. El único que queda en pie es el que no depende de ninguna fila deforme
(`test_la_cadena_legitima_vuelve_a_estar_sana`). Un test que no se cae con la mutación es
decoración.
"""
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client  # noqa: E402

require_postgres()

DB = "sentinel_test_cadena_filas_deformes"

RESERVADO = "license"

# Tres y no uno: con un solo eslabón, un `verify_chain` que dejara de mirar la contigüidad
# seguiría verde y el test no distinguiría «verifica la cadena» de «no verifica nada».
ESLABONES = 3

HASH_FALSO = "0" * 64

# (marca, guardian_events, con qué reventaba antes de la guarda).
#
# La marca es la identidad de la fila dentro del test: sin ella, un fallo diría «TypeError» y no
# CUÁL de las siete formas se coló. La tercera columna no la lee ningún assert — es la evidencia
# medida, para que quien revierta la guarda sepa qué tiene que ver.
DEFORMES = [
    # La del informe del gate: `"seq" in "seq"` es True por subcadena. El disfraz más barato.
    ("string_igual_a_la_clave", ["seq"],
     "TypeError: string indices must be integers, not 'str'"),
    # La misma puerta sin ni siquiera escribir la clave: `"seq" in "consequence"` también es
    # True. Es la que muestra que el filtro viejo no filtraba nada.
    ("string_que_la_contiene", ["consequence"],
     "TypeError: string indices must be integers, not 'str'"),
    # `"seq" in 7` ni siquiera llega al filtro: revienta ANTES, en el `in`.
    ("entero", [7], "TypeError: argument of type 'int' is not iterable"),
    ("nulo", [None], "TypeError: argument of type 'NoneType' is not iterable"),
    # `in` sobre una lista es pertenencia de verdad, así que pasa el filtro y muere en el índice.
    ("lista_anidada", [["seq"]],
     "TypeError: list indices must be integers or slices, not str"),
    # Objeto legítimo a medias: pasa el filtro viejo y `verify_chain` muere en el `prev_hash`.
    # Es además la forma que el clasificador de retención considera eslabón, o sea la que el
    # export ADOPTABA — el daño acá no es sólo la excepción: el true-up sale contaminado y el
    # lado-Sentinel lo rechaza con «cadena interna inválida: falta seq 2», medido.
    ("objeto_sin_prev_hash", [{"seq": 1}],
     "KeyError: 'prev_hash' en verify_chain / TrueUpError en el export"),
    # El `seq` con el tipo equivocado: pasa las dos guardas de pertenencia y revienta en el
    # `sorted`, comparando `str` con `int`, antes de que nadie mire un hash. Es la puerta que
    # una guarda que sólo pidiera `isinstance(evento, dict)` dejaría abierta.
    ("objeto_con_seq_string", [{"seq": "1", "prev_hash": HASH_FALSO}],
     "TypeError: '<' not supported between instances of 'str' and 'int'"),
    # `guardian_events` que no es lista: el `[0]` no indexa, busca la clave 0 del objeto.
    ("guardian_events_no_es_lista", {"seq": 1, "prev_hash": HASH_FALSO}, "KeyError: 0"),
]

MARCAS = [marca for marca, _eventos, _sintoma in DEFORMES]


# ── Semilla ───────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    cadena = sembrar_cadena_legitima(factory)
    yield factory, cadena
    cleanup()


def sembrar_cadena_legitima(factory):
    """`ESLABONES` eslabones por el emisor REAL de la 021, sobre una tabla en cero.

    Por el emisor y no por dicts a mano: lo que hay que proteger es la cadena que el producto
    emite, con la forma que el producto le da — un `{"seq": n}` escrito acá probaría que sigue
    legible un eslabón que nadie emite.

    La tabla arranca vacía —incluida `license_runtime_state`, que el arranque de la app ya
    tocó— para que `checked` y `counter` sean números EXACTOS y no «al menos». Un «al menos»
    pasaría igual con una fila ajena adentro, que es justo lo que se mide.

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


def sembrar_deforme(factory, eventos):
    """UNA fila `model='license'` con el jsonb deforme. Devuelve su id.

    Por DB directa porque lo que se mide son los LECTORES sobre la tabla, no por qué puerta
    entró la fila: hoy ningún escritor la produce —ése es el punto de la capa B— y el escenario
    que este archivo cubre es justamente la fila que ya está en la base del cliente.
    """
    from src.models.audit import AuditLog
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        fila = AuditLog(
            tenant_id=DEFAULT_TENANT_ID, model=RESERVADO,
            prompt_tokens=0, completion_tokens=0, cost_usd=0,
            pii_detected=False, compliance_status="blocked_secret", latency_ms=7,
            guardian_events=eventos,
        )
        db.add(fila)
        db.commit()
        return fila.id
    finally:
        db.close()


def borrar(factory, fila_id):
    from src.models.audit import AuditLog
    db = factory()
    try:
        db.query(AuditLog).filter(AuditLog.id == fila_id).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def deforme(harness, request):
    """Siembra UNA forma deforme y la saca al terminar: cada test corre con un solo intruso en
    la tabla, así el assert que falla nombra a la forma que se coló."""
    factory, _cadena = harness
    fila_id = sembrar_deforme(factory, request.param)
    yield
    borrar(factory, fila_id)


# ── Helpers ───────────────────────────────────────────────────────────────────────────


def reporte_de_la_cadena(factory):
    from src.licensing.audit_events import verify_chain
    db = factory()
    try:
        return verify_chain(db)
    finally:
        db.close()


def export_firmado(factory, monkeypatch, tmp_path):
    """El true-up REAL: firmado con una deployment key efímera y verificado por el mismo
    verificador que corre del lado Sentinel."""
    from src.licensing import deployment_key, trueup_export
    monkeypatch.setenv(deployment_key.DEPLOYMENT_KEY_ENV, str(tmp_path / "deployment_key.pem"))
    deployment_key.ensure_deployment_key()
    doc = trueup_export.generate_signed_export(session_factory=factory)
    # No levanta ⇒ firma válida, cadena interna contigua y head coherente con el historial.
    trueup_export.verify_export(doc, deployment_key.public_key_pem())
    return doc


def seqs_legitimos(cadena):
    return [entry["seq"] for _id, entry in cadena]


# ── 1. `verify_chain` sobrevive y sigue verificando ───────────────────────────────────


@pytest.mark.parametrize("deforme", [d[1] for d in DEFORMES], ids=MARCAS, indirect=True)
def test_verify_chain_sobrevive_a_la_fila_deforme_y_sigue_verde(harness, deforme):
    """El bug medido, forma por forma: antes de la guarda esto no era un assert que fallaba,
    era una excepción sin capturar. Y el veredicto tiene que ser VERDE: la fila deforme no es
    un eslabón, así que su presencia no es evidencia de manipulación de la cadena."""
    factory, _cadena = harness

    reporte = reporte_de_la_cadena(factory)

    assert reporte["issues"] == []
    assert reporte["ok"] is True


@pytest.mark.parametrize("deforme", [d[1] for d in DEFORMES], ids=MARCAS, indirect=True)
def test_la_fila_deforme_no_se_cuenta_como_eslabon(harness, deforme):
    """El error simétrico del que revienta: adoptarla. `checked` EXACTO — si subiera, la cadena
    habría adoptado una fila que el emisor de la 021 nunca escribió, y a partir de ahí cualquier
    purga de esa fila (que es mortal, justamente) dejaría un hueco que el verificador leería
    como tamper: el deployment acusándose solo."""
    factory, _cadena = harness

    assert reporte_de_la_cadena(factory)["checked"] == ESLABONES


# ── 2. El export de true-up sobrevive y sale limpio ───────────────────────────────────


@pytest.mark.parametrize("deforme", [d[1] for d in DEFORMES], ids=MARCAS, indirect=True)
def test_el_trueup_sobrevive_a_la_fila_deforme_y_no_se_la_lleva(
        harness, deforme, monkeypatch, tmp_path):
    """El lector que le cuesta plata al cliente. Se exige el payload EXACTO —los mismos `seq`
    que emitió el emisor— y que el documento firmado verifique de punta a punta: `verify_export`
    recorre la cadena interna eslabón por eslabón, así que es el assert que de verdad detecta al
    intruso. Un export con una fila ajena adentro lo rechaza el lado-Sentinel por «cadena interna
    inválida», y el cliente se queda sin poder demostrar su historial."""
    factory, cadena = harness

    doc = export_firmado(factory, monkeypatch, tmp_path)

    assert [e["seq"] for e in doc["events"]] == seqs_legitimos(cadena)
    assert doc["counter"] == ESLABONES
    assert doc["range"] == {"from_seq": 1, "to_seq": ESLABONES}


# ── 3. Todas juntas ───────────────────────────────────────────────────────────────────


def test_los_dos_lectores_sobreviven_a_todas_las_formas_a_la_vez(harness, monkeypatch, tmp_path):
    """De a una se prueba que ninguna forma tumba a los lectores; juntas se prueba que la
    defensa no depende del orden en que salen de la query. Es además el escenario realista: una
    base vieja no tiene una fila rara, tiene las que se hayan acumulado."""
    factory, cadena = harness
    ids = [sembrar_deforme(factory, eventos) for _marca, eventos, _sintoma in DEFORMES]
    try:
        reporte = reporte_de_la_cadena(factory)
        doc = export_firmado(factory, monkeypatch, tmp_path)
    finally:
        for fila_id in ids:
            borrar(factory, fila_id)

    assert reporte == {"ok": True, "issues": [], "checked": ESLABONES}
    assert [e["seq"] for e in doc["events"]] == seqs_legitimos(cadena)
    assert doc["counter"] == ESLABONES


# ── 4. La guarda no es un lavadero ────────────────────────────────────────────────────


def test_deformar_un_eslabon_legitimo_sigue_rompiendo_la_cadena(harness):
    """La contracara obligatoria: saltear lo que no se puede leer NO puede volverse «no mirar».

    Si el jsonb roto es el de un eslabón de VERDAD, saltearlo deja un hueco de `seq` y el
    verificador tiene que reportarlo igual que un borrado. Sin este test, una guarda que
    devolviera `False` para todo pasaría los tres bloques de arriba con `checked == 0`… salvo
    por el `checked` exacto, y esa sola línea es demasiado poco para sostener el invariante.

    Se elige el eslabón INTERMEDIO a propósito: el último sería truncado de cola, que la
    verificación local no puede detectar por contrato (T039).
    """
    from sqlalchemy.orm.attributes import flag_modified

    from src.models.audit import AuditLog
    factory, cadena = harness
    victima_id, entry_original = cadena[-2]

    db = factory()
    try:
        fila = db.query(AuditLog).filter(AuditLog.id == victima_id).one()
        fila.guardian_events = ["seq"]  # el eslabón real, deformado por DB directa
        flag_modified(fila, "guardian_events")
        db.commit()
    finally:
        db.close()
    try:
        reporte = reporte_de_la_cadena(factory)
    finally:
        db = factory()
        try:  # restaurar: el resto del módulo comparte esta cadena
            fila = db.query(AuditLog).filter(AuditLog.id == victima_id).one()
            fila.guardian_events = [entry_original]
            flag_modified(fila, "guardian_events")
            db.commit()
        finally:
            db.close()

    assert reporte["ok"] is False, (
        "deformar un eslabón legítimo salió gratis: la guarda dejó de distinguir «esta fila no "
        "es un eslabón» de «este eslabón desapareció»")
    assert reporte["checked"] == ESLABONES - 1
    assert any("eslabón" in issue or "hash" in issue for issue in reporte["issues"]), reporte


def test_la_cadena_legitima_vuelve_a_estar_sana(harness):
    """Cierre del archivo: después de sembrar, borrar y deformar, la cadena real quedó como
    estaba. Si esto se pone rojo, algún test de arriba dejó basura y los demás están midiendo
    otra tabla que la que dicen medir."""
    factory, _cadena = harness

    assert reporte_de_la_cadena(factory) == {"ok": True, "issues": [], "checked": ESLABONES}
