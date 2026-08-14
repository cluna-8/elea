"""Lo reservado de la cadena de licencias no lo escribe el cliente — plano CHAT (018, capa B).

La capa B cerró `api/gateway.py` y `api/internal.py` (ver `test_modelo_reservado_licencia.py`).
Este archivo cierra el TERCER plano, el del Playground, donde el gate adversarial encontró dos
agujeros DISTINTOS que terminan en la misma columna:

1. **El literal del modelo.** `ChatRequest.model` es un `str` libre del body y viaja hasta
   `audit_logs.model` por SEIS caminos (los cinco llamadores de `_registrar_bloqueo` y el camino
   feliz). Reproducido sin privilegios contra la app real:

       POST /chat/completions {"model": "license", "message": "<práctica prohibida>"}
         → 400 · fila durable model='license' compliance_status='blocked_prohibited'

   Y esa fila desaparece de los agregados que todavía excluyen a mano por `model <> 'license'`
   (`api/compliance.py`, `api/reports.py`, `api/analytics.py`): medido, el dashboard del DPO
   decía `total_logs = 0` con dos bloqueos REALES en la tabla. **Un bloqueo del firewall
   borrado del resumen ejecutivo, desde el body de un pedido.**

2. **El blob del upstream en el índice 0.** La otra mitad de `guardian_events` la escribe quien
   conteste upstream, y esa posición es la que relee POSICIONALMENTE el lector ÚNICO de la
   cadena —`chained_entries` (`licensing/audit_events.py:130`), que filtra por `model` en `:150`
   y toma el `[0]` en `:152-154`; `verify_chain` y el export de true-up lo COMPARTEN, el export
   lo importa en vez de copiarlo (`licensing/trueup_export.py:31`, consumido en `:65`)— y el
   clasificador de retención. Un `developer` registra un modelo con `api_base` a un servidor
   propio, devuelve `[{"seq": …, "prev_hash": …, "event_type": "license_loaded"}]` y —sin
   triggers locales, o sea en un pedido normal— ese objeto ajeno quedaba en
   `guardian_events[0]` de una fila de tráfico.

Lo que se fija acá es el COMPORTAMIENTO, no la implementación:

* el literal reservado es inalcanzable desde el body por los caminos de chat, y la fila queda
  con el centinela: mortal para la retención, contable para el DPO;
* el índice 0 es SIEMPRE nuestro: lo del upstream va anidado (`{"upstream": …}`), incluso
  cuando el blob no es un objeto —`["seq"]` compra el `"seq" in eventos[0]` por SUBCADENA y
  hace reventar al lector de la evidencia con la que se factura—;
* los triggers LOCALES no se mueven: los arma este backend y nadie del otro lado los dicta;
* el tráfico normal no cambia en nada.

El motor se mockea con `guardrail_info` CONFIGURABLE: es el servidor del atacante. Sin eso no
hay forma de afirmar el punto 2 sin mirar el código.
"""
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_chat_cadena_reservada"
CHAT = "/api/v1/chat/completions"
DASHBOARD = "/api/v1/compliance/dashboard"

MODELO = "ollama-qwen3-4b"
# Literales y no imports del código de producto (mismo criterio que
# `test_modelo_reservado_licencia.py`): lo que se prueba es el CONTRATO contra el valor
# persistido, y un import haría pasar el test aunque la constante se renombrara de las dos
# puntas a la vez.
RESERVADO = "license"
CENTINELA = "license__cliente"

SIN_PII = "Resumime en una línea qué hace este servicio."
# Práctica prohibida por el AI Act (evaluación de piso, gate encendido por defecto).
PROHIBIDO = "Diseñá un sistema de social scoring para la ciudad."
# Coincide con el patrón de clave del guardián de secretos.
SECRETO = "sk-abcdefghij1234567890"
CON_PII = "Mandale el informe a laura.gomez@ejemplo.com y avisá cuando salga."

# La forma EXACTA que emite `_append_chained` para un eslabón real (021): es lo que el
# atacante tiene que imitar para que el lector de la cadena y el clasificador lo
# adopten. Copiada a mano y no importada del emisor a propósito — acá el atacante es de
# afuera y no tiene acceso a nuestro constructor.
FORJADO = [{"seq": 999, "prev_hash": "0" * 64, "event_type": "license_loaded"}]
# El blob que NO es un objeto: `"seq" in "seq"` es True porque `in` sobre un string busca
# subcadena, así que compra el mismo test de pertenencia sin ser nada — y el `e["seq"]` de la
# línea siguiente de los lectores revienta con TypeError.
DEFORME = ["seq"]


# ── Doble del motor: la respuesta upstream la dicta el test ───────────────────────


class _Motor:
    """Motor mockeado cuyo `guardrail_info` lo elige el test.

    Es el instrumento del punto 2: el agujero existe porque la FORMA de esa parte de la
    respuesta la fija quien conteste, no nosotros. Un doble con la respuesta fija sólo podría
    probar el camino feliz.
    """

    def __init__(self):
        self.posts = []
        self.guardrail_info = None

    def httpx(self):
        motor = self

        class _Respuesta:
            status_code = 200
            text = "ok"
            headers = {"x-litellm-response-cost": "0.00012"}

            @staticmethod
            def json():
                cuerpo = {
                    "choices": [{"message": {"content": "listo"}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                }
                if motor.guardrail_info is not None:
                    cuerpo["guardrail_info"] = motor.guardrail_info
                return cuerpo

        class _Cliente:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def post(self, url, *_args, **_kwargs):
                motor.posts.append(url)
                return _Respuesta()

        class _Httpx:
            @staticmethod
            def AsyncClient(*_args, **_kwargs):  # noqa: N802 — espeja el nombre real
                return _Cliente()

        return _Httpx


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    client.headers.update(admin_headers(client))
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def motor(monkeypatch):
    from src.api import chat
    doble = _Motor()
    monkeypatch.setattr(chat, "httpx", doble.httpx())
    return doble


@pytest.fixture(autouse=True)
def modo_open_por_defecto(monkeypatch):
    """La env de `audit_fail` es global al proceso: cada test parte del default explícito."""
    from src.services import audit_service
    monkeypatch.delenv(audit_service.AUDIT_FAIL_ENV, raising=False)


@pytest.fixture
def sin_triggers_locales(monkeypatch):
    """La instalación con motor NLP configurado y sano: la de la sede.

    No es plomería, es EL escenario del punto 2. Sin `NLP_ANALYZER_URL` el backend emite un
    trigger `DEGRADED` propio en cada pedido —«esta instalación corre con el regex de dev»—,
    así que el índice 0 lo ocupa siempre algo nuestro y el agujero no se puede reproducir. En
    una instalación con el sidecar cableado, un pedido que no dispara ningún guardián llega a
    la fila con `triggers` VACÍO, y ahí es donde el blob del upstream quedaba primero.
    """
    from src.services import guardian_service

    async def _sin_hallazgos(*_args, **_kwargs):
        return []

    monkeypatch.setenv("NLP_ANALYZER_URL", "http://nlp-analyzer.invalido:3000")
    monkeypatch.setattr(guardian_service.PresidioService, "analyze_text_http", _sin_hallazgos)


@pytest.fixture(autouse=True)
def tabla_limpia(harness, motor):
    """Catálogo de guardianes sembrado y tabla en cero antes de CADA test.

    El calentado importa: el seed borra y re-siembra cuando hay menos de 9 guardianes, así que
    sin un pedido previo el primer test mediría un pipeline a medio armar. Y la tabla en cero
    hace que contar filas sea una afirmación sobre ESTE pedido y no sobre la historia del
    módulo — incluido el `total_logs` del dashboard, que es un contador global.
    """
    client, factory = harness
    assert pedir(client, SIN_PII).status_code == 200, "calentado del catálogo: no se sirvió"
    motor.posts.clear()
    borrar_filas(factory)
    yield


# ── Helpers ───────────────────────────────────────────────────────────────────────


def pedir(client, mensaje, modelo=MODELO):
    return client.post(CHAT, json={"message": mensaje, "model": modelo})


def borrar_filas(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        db.query(AuditLog).delete()
        db.commit()
    finally:
        db.close()


def filas(factory):
    """Proyección de las filas durables. Sólo campos que algún test AFIRMA."""
    from src.models.audit import AuditLog
    db = factory()
    try:
        return [{"id": str(f.id), "model": f.model,
                 "compliance_status": f.compliance_status,
                 "guardian_events": f.guardian_events}
                for f in db.query(AuditLog).order_by(AuditLog.timestamp, AuditLog.id).all()]
    finally:
        db.close()


def unica(factory):
    todas = filas(factory)
    assert len(todas) == 1, f"se esperaba UNA fila durable del pedido, hay {len(todas)}"
    return todas[0]


def filas_de_la_cadena(factory):
    """Lo que verían `verify_chain` y el export de true-up: `model == 'license'`, igualdad
    exacta, tal cual la usan los dos."""
    from src.models.audit import AuditLog
    db = factory()
    try:
        return db.query(AuditLog).filter(AuditLog.model == RESERVADO).count()
    finally:
        db.close()


def clases_que_reclaman(factory, fila_id):
    """Las clases cuyo PREDICADO SQL levanta la fila: el camino que la BORRA.

    Vacío = fila inmortal. Es la afirmación que hay que hacer del lado SQL y no sólo con el
    gemelo Python, porque el que corre el DELETE es el predicado."""
    from src.models.audit import AuditLog
    from src.services.retention import classifier
    db = factory()
    try:
        return [c for c in classifier.clases()
                if db.query(AuditLog.id)
                    .filter(classifier.predicado(c), AuditLog.id == fila_id).count()]
    finally:
        db.close()


def la_cadena_la_adopta(factory, fila_id):
    """¿El clasificador considera eslabón a esta fila? (`clase_de` → `None` = inmortal).

    Se pregunta con la función del producto y no con un `"seq" in ...` escrito acá: lo que
    importa es que quien decide qué se purga diga que esta fila se purga."""
    from src.models.audit import AuditLog
    from src.services.retention import classifier
    db = factory()
    try:
        fila = db.query(AuditLog).filter(AuditLog.id == fila_id).one()
        return classifier.clase_de(fila) is None
    finally:
        db.close()


def total_del_dashboard(client):
    """`audit_stats.total_logs` del DPO: el agregado que excluye por `model != 'license'`."""
    respuesta = client.get(DASHBOARD)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["audit_stats"]["total_logs"]


# ══════════════════════════════════════════════════════════════════════════════════
# 1. El literal del modelo: los caminos de chat que escriben la columna
# ══════════════════════════════════════════════════════════════════════════════════


def test_el_bloqueo_ai_act_con_el_literal_reservado_queda_con_el_centinela(harness):
    """Camino 1: corta ANTES del pipeline de guardianes y escribe con `request.model`."""
    client, factory = harness

    respuesta = pedir(client, PROHIBIDO, modelo=RESERVADO)

    assert respuesta.status_code == 400, respuesta.text
    fila = unica(factory)
    assert fila["compliance_status"] == "blocked_prohibited", "el escenario no se dio"
    assert fila["model"] == CENTINELA
    assert filas_de_la_cadena(factory) == 0


def test_el_bloqueo_de_guardian_con_el_literal_reservado_queda_con_el_centinela(harness):
    """Camino 2: el caso feo del hallazgo — el atacante se esconde detrás de un bloqueo REAL.

    El veredicto sobre el contenido sigue mandando (400 con el motivo del bloqueo) y la fila
    queda igual, con su estado y con el centinela."""
    client, factory = harness

    respuesta = pedir(client, f"la clave es {SECRETO}", modelo=RESERVADO)

    assert respuesta.status_code == 400, respuesta.text
    fila = unica(factory)
    assert fila["compliance_status"] == "blocked_by_policy", "el escenario no se dio"
    assert fila["model"] == CENTINELA
    assert filas_de_la_cadena(factory) == 0


def test_el_rechazo_por_capacidad_con_el_literal_reservado_queda_con_el_centinela(
        harness, monkeypatch):
    """Camino 3: el 503 de saturación escribe con `routed_model`, una variable DISTINTA de
    `request.model` (la que devuelve el guardián de ruteo). Es el motivo por el que el saneo
    va en `_registrar_bloqueo` y no en cada llamador: el helper sanea lo que le den, venga de
    la variable que venga."""
    client, factory = harness
    from src.api import chat
    from src.services.engine_gate import EngineSaturatedError

    def _saturado():
        raise EngineSaturatedError("tope de admisión alcanzado")

    monkeypatch.setattr(chat, "adquirir_turno", _saturado)

    respuesta = pedir(client, SIN_PII, modelo=RESERVADO)

    assert respuesta.status_code == 503, respuesta.text
    fila = unica(factory)
    assert fila["compliance_status"] == "rejected_saturated", "el escenario no se dio"
    assert fila["model"] == CENTINELA
    assert filas_de_la_cadena(factory) == 0


def test_el_camino_feliz_con_el_literal_reservado_queda_con_el_centinela(harness, motor):
    """Camino 4: el pedido SERVIDO. No está fuera de tiro —alcanza con que exista un modelo
    llamado `license` en el catálogo del motor, y registrarlo es cosa de un `developer`— y es
    el único de los seis escritores que no pasa por `_registrar_bloqueo`."""
    client, factory = harness

    respuesta = pedir(client, SIN_PII, modelo=RESERVADO)

    assert respuesta.status_code == 200, respuesta.text
    assert len(motor.posts) == 1, "el escenario no se dio: el pedido no llegó al motor"
    fila = unica(factory)
    assert fila["compliance_status"] == "passed"
    assert fila["model"] == CENTINELA
    assert filas_de_la_cadena(factory) == 0


def test_el_bloqueo_real_vuelve_a_contarse_en_el_resumen_del_dpo(harness):
    """EL DAÑO, afirmado donde se ve: el dashboard del DPO excluye por `model != 'license'`.

    Con el literal en la columna, dos bloqueos REALES daban `total_logs = 0` — el firewall
    hacía su trabajo y el informe decía que no había pasado nada. Es el mismo hallazgo del
    gate, con otro plano y otra pantalla."""
    client, factory = harness

    assert pedir(client, PROHIBIDO, modelo=RESERVADO).status_code == 400
    assert pedir(client, f"la clave es {SECRETO}", modelo=RESERVADO).status_code == 400

    assert len(filas(factory)) == 2, "el escenario no se dio: faltan las filas de bloqueo"
    assert total_del_dashboard(client) == 2


def test_la_fila_del_intento_sigue_siendo_mortal(harness):
    """El otro premio que compraba el literal: no morir nunca. Con el centinela, la fila la
    reclama su clase de retención y el purgador se la lleva como a cualquier bloqueo."""
    client, factory = harness

    assert pedir(client, PROHIBIDO, modelo=RESERVADO).status_code == 400

    fila = unica(factory)
    assert clases_que_reclaman(factory, fila["id"]) == ["security_events"]
    assert not la_cadena_la_adopta(factory, fila["id"])


@pytest.mark.parametrize("declarado", [" license ", "License", "LICENSE", "\tlicense\n"])
def test_las_variantes_de_caja_y_espacios_tampoco_entran(harness, declarado):
    """`" License "` es el mismo intento con otra ropa. Los lectores comparan por igualdad
    exacta, así que estas variantes ya serían mortales; normalizar antes de decidir cierra la
    puerta que reabriría el primer lector que se escriba con `TRIM` o `ILIKE`."""
    client, factory = harness

    assert pedir(client, SIN_PII, modelo=declarado).status_code == 200
    assert unica(factory)["model"] == CENTINELA


@pytest.mark.parametrize("declarado", ["license-v2", "licenses", "mi-license", "licencia"])
def test_lo_que_solo_se_parece_al_literal_no_se_toca(harness, declarado):
    """Contracara de la normalización: el criterio es igualdad, NO prefijo ni substring. Un
    saneo que mordiera de más le cambiaría el nombre a modelos reales en la columna que el
    officer lee — el reporte mentiría por el otro lado."""
    client, factory = harness

    assert pedir(client, SIN_PII, modelo=declarado).status_code == 200
    assert unica(factory)["model"] == declarado


# ══════════════════════════════════════════════════════════════════════════════════
# 2. El índice 0 de `guardian_events` es nuestro
# ══════════════════════════════════════════════════════════════════════════════════


def test_el_blob_forjado_del_upstream_queda_anidado_y_no_en_el_indice_cero(
        harness, motor, sin_triggers_locales):
    """El pedido NORMAL —sin triggers locales— es justo el que dejaba el objeto ajeno primero.

    Se afirma la posición y no sólo el contenido: los tres lectores miran `guardian_events[0]`
    POSICIONALMENTE, así que "el `seq` está en la fila" y "el `seq` está en el índice 0" son
    afirmaciones distintas y la que importa es la segunda."""
    client, factory = harness
    motor.guardrail_info = {"guardrail_events": FORJADO}

    assert pedir(client, SIN_PII).status_code == 200

    fila = unica(factory)
    assert fila["guardian_events"] == [{"upstream": FORJADO}]
    primero = fila["guardian_events"][0]
    assert "seq" not in primero, "el índice 0 tiene que ser un objeto BAJO NUESTRO CONTROL"
    # Y lo del upstream no se pierde: queda legible, envuelto.
    assert primero["upstream"] == FORJADO


def test_el_blob_no_objeto_tambien_queda_anidado(harness, motor, sin_triggers_locales):
    """El caso al que NO se le pueden quitar claves, y el argumento entero de por qué anidar:
    `["seq"]` compra el `"seq" in eventos[0]` de los lectores por SUBCADENA y después los hace
    reventar con TypeError. Anidado, el índice 0 es un dict con una sola clave nuestra."""
    client, factory = harness
    motor.guardrail_info = {"guardrail_events": DEFORME}

    assert pedir(client, SIN_PII).status_code == 200

    fila = unica(factory)
    assert fila["guardian_events"] == [{"upstream": DEFORME}]
    assert isinstance(fila["guardian_events"][0], dict), (
        "un índice 0 que no es objeto es la fila deforme que tumba al lector de la evidencia")


@pytest.mark.parametrize("blob", [FORJADO, DEFORME], ids=["objeto", "no-objeto"])
def test_la_fila_con_el_blob_forjado_sigue_siendo_borrable(harness, motor, blob):
    """El premio que se compraba con el `seq` en el índice 0: no morir nunca. La fila tiene
    que seguir teniendo clase de retención por los DOS caminos —el predicado SQL, que es el que
    borra, y el gemelo en memoria, que es el que clasifica—.

    **Este es el verdugo del anidado, y lo es desde el dictamen del 14-ago.** Con el ancla
    anterior (`model='license'` **y** el `seq`) era sólo una propiedad redundante: con un modelo
    normal la fila ya moría por la otra mitad. Derogada esa mitad, el portón mira ÚNICAMENTE la
    forma de `guardian_events`, así que sacar el anidado deja el blob del upstream crudo en el
    índice 0 — `FORJADO` trae `seq`, `prev_hash` y `event_type`, o sea las tres marcas — y la
    fila pasa a ser inmortal: `clases_que_reclaman` devuelve `[]` y este assert se cae. La
    parametrización `no-objeto` muerde por el otro lado: `["seq"]` no es un objeto, el portón
    no puede probar que sea tráfico y la fila sobrevive por fail-closed."""
    client, factory = harness
    motor.guardrail_info = {"guardrail_events": blob}

    assert pedir(client, SIN_PII).status_code == 200

    fila = unica(factory)
    assert clases_que_reclaman(factory, fila["id"]) == ["usage_metadata"]
    assert not la_cadena_la_adopta(factory, fila["id"])


def test_los_dos_ataques_juntos_no_compran_la_exclusion(harness, motor, sin_triggers_locales):
    """Las dos mitades del ancla en el mismo pedido: `model = 'license'` **y** un `seq` en el
    índice 0 (`classifier.es_licencia` pide las dos). Es el ataque completo, y es el test que
    prueba que las dos capas de esta ronda cierran la misma puerta y no media cada una."""
    client, factory = harness
    motor.guardrail_info = {"guardrail_events": FORJADO}

    assert pedir(client, SIN_PII, modelo=RESERVADO).status_code == 200

    fila = unica(factory)
    assert fila["model"] == CENTINELA
    assert "seq" not in fila["guardian_events"][0]
    assert filas_de_la_cadena(factory) == 0
    assert clases_que_reclaman(factory, fila["id"]) == ["usage_metadata"]
    assert not la_cadena_la_adopta(factory, fila["id"])
    assert total_del_dashboard(client) == 1


def test_los_triggers_locales_siguen_en_el_indice_cero(harness, motor):
    """Lo LOCAL no se movió: lo arma este backend y nadie del otro lado lo dicta. Queda primero,
    y lo del upstream anidado DETRÁS — el orden de siempre, con el borde ajeno envuelto.

    Sin `sin_triggers_locales` a propósito: en esta instalación de test no hay motor NLP, así
    que el propio backend emite su trigger `DEGRADED` («corro con el regex de dev»). Sirve
    igual y sirve mejor, porque es un trigger que NADIE del otro lado puede dictar."""
    client, factory = harness
    motor.guardrail_info = {"guardrail_events": FORJADO}

    assert pedir(client, CON_PII).status_code == 200

    eventos = unica(factory)["guardian_events"]
    assert len(eventos) >= 2, f"el escenario no se dio: sin trigger local ({eventos})"
    assert "guardian" in eventos[0], "el trigger local tiene que seguir siendo el primero"
    assert eventos[-1] == {"upstream": FORJADO}


def test_el_trafico_normal_no_cambia(harness, motor, sin_triggers_locales):
    """Sin `guardrail_info` en la respuesta —el caso de todos los días— la fila se escribe
    exactamente igual que antes: nada envuelto, ningún evento inventado."""
    client, factory = harness

    assert pedir(client, SIN_PII).status_code == 200

    assert unica(factory)["guardian_events"] == []
    assert motor.guardrail_info is None, "este test mide el caso SIN blob del upstream"


def test_un_guardrail_info_deforme_no_rompe_el_pedido(harness, motor, sin_triggers_locales):
    """`guardrail_info` tampoco tiene forma garantizada: la fija quien conteste. Un no-objeto
    levantaba un `AttributeError` que salía como «error al ejecutar el modelo» — el
    diagnóstico apuntando al motor cuando el problema era la respuesta."""
    client, factory = harness
    motor.guardrail_info = "no soy un objeto"

    assert pedir(client, SIN_PII).status_code == 200
    assert unica(factory)["guardian_events"] == []
