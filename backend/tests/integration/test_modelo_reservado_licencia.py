"""El literal `license` es de la auditoría, no del cliente (spec 018, capa B).

Hallazgo del gate adversarial de la 018 (CRÍTICA): `audit_logs.model` lo escribe el CLIENTE
—`body["model"]` en `/gw`, `entry.model` en `/internal/audit`— y `license` es la marca de los
eslabones de la hash-chain de licencias (021). Cualquiera con una API key mandaba
`{"model": "license"}` y su fila de tráfico —incluido un bloqueo real— quedaba:

1. **inmortal**: los predicados de retención excluyen la cadena, así que no la alcanzaba
   ninguna clase y no moría nunca (Art. 5.1.e al revés, justo lo que la 018 cierra);
2. **invisible**: la vitrina y los agregados de cobertura excluyen por la misma columna, así
   que no aparecía ni entre los bloqueados ni entre los permitidos;
3. **veneno**: `verify_chain` y el export de true-up releen TODAS las filas `model='license'`,
   y una fila ajena sin `seq` puede hacer que la verificación acuse TAMPER y que el true-up
   del cliente falle.

Es el MISMO bug que ya se cazó y se cerró para el campo `tool` en `api/inspect.py` (ver
`test_gw_inspect_superficie.py`), y se cierra con la misma doctrina: **saneo con vocabulario
cerrado, no rechazo**. Lo que estos tests fijan es el comportamiento, no la implementación:

* el literal reservado es INALCANZABLE desde input de cliente en los dos escritores;
* el orden **sanear → auditar → rechazar** — la fila durable existe ANTES del 422, porque un
  rechazo en el parseo dejaría al atacante irse sin rastro, que es peor que la fila inmortal
  (FR-001);
* `/internal/audit` sanea y **nunca** rechaza: esa fila llega del motor después del hecho y
  tirarla sería tirar auditoría durable ya generada;
* el tráfico legítimo no se toca, ni siquiera el que se le PARECE (`license-v2`).
"""
import json
import os
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

DB = "basa_test_modelo_reservado_licencia"
GW = "/api/v1/gw/v1/messages"
AUDIT = "/api/v1/internal/audit"

SECRETO_INTERNO = "secreto-interno-de-la-suite-018"
CABECERA_INTERNA = {"X-Basa-Internal": SECRETO_INTERNO}

RESERVADO = "license"
CENTINELA = "license__cliente"
LEGITIMO = "claude-3-5-sonnet-20241022"

# Dispara `SECRET_PATTERNS["OpenAI API Key"]` ⇒ bloqueo `blocked_secret` por regex pura de la
# librería compartida, sin depender del analizador NLP (mismo insumo que la suite de la 031).
SECRETO = "sk-ABCdefghij0123456789"


def cuerpo(model, texto="resumime esto en una línea"):
    return {"model": model, "messages": [{"role": "user", "content": texto}]}


# ── Dobles ────────────────────────────────────────────────────────────────────────


class _RespuestaFalsa:
    status_code = 200
    headers = {"content-type": "application/json"}
    content = json.dumps({"content": [{"type": "text", "text": "ok"}],
                          "usage": {"input_tokens": 3, "output_tokens": 2}}).encode()

    def json(self):
        return json.loads(self.content)


class _ClienteFalso:
    def __init__(self, registro):
        self._registro = registro

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url, **_kwargs):
        self._registro.append(url)
        return _RespuestaFalsa()


class _HttpxEspia:
    """Doble del `httpx` que usa el gateway: cuenta a quién se llamó.

    Es el instrumento del invariante caro del 422: el rechazo tiene que ocurrir SIN haberle
    mandado el pedido al proveedor, y eso sólo se afirma contando salidas."""

    def __init__(self):
        self.llamadas = []

    def AsyncClient(self, *_args, **_kwargs):  # noqa: N802 — espeja el nombre real
        return _ClienteFalso(self.llamadas)


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    previo = os.environ.get("BASA_ENGINE_MASTER_KEY")
    os.environ["BASA_ENGINE_MASTER_KEY"] = SECRETO_INTERNO
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()
    if previo is None:
        os.environ.pop("BASA_ENGINE_MASTER_KEY", None)
    else:
        os.environ["BASA_ENGINE_MASTER_KEY"] = previo


@pytest.fixture(autouse=True)
def sesion_del_gateway(harness, monkeypatch):
    """`gateway` abre sus PROPIAS sesiones (este plano se autentica con el OAuth del cliente,
    no con la sesión del request). Sin este patch los tests escribirían en la base del
    compose."""
    _, factory = harness
    from src.api import gateway
    monkeypatch.setattr(gateway, "SessionLocal", factory)


@pytest.fixture(autouse=True)
def proveedor(monkeypatch):
    from src.api import gateway
    espia = _HttpxEspia()
    monkeypatch.setattr(gateway, "httpx", espia)
    return espia


@pytest.fixture(autouse=True)
def limpiar_filas(harness):
    """Cada test cuenta filas propias: el módulo comparte base. Y arranca de cero también para
    que `filas_de_la_cadena()` no herede eslabones legítimos de otro test."""
    _, factory = harness
    from src.models.audit import AuditLog
    db = factory()
    try:
        db.query(AuditLog).delete()
        db.commit()
    finally:
        db.close()
    yield


# ── Helpers ───────────────────────────────────────────────────────────────────────


def filas(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return [{"model": f.model, "compliance_status": f.compliance_status,
                 "prompt_tokens": f.prompt_tokens, "completion_tokens": f.completion_tokens}
                for f in db.query(AuditLog).all()]
    finally:
        db.close()


def filas_de_la_cadena(factory):
    """Lo que verían `verify_chain` y el export de true-up: `model == 'license'`, igualdad
    exacta. Los dos ven lo MISMO porque comparten UN solo lector —`chained_entries`, y la
    igualdad vive ahí, en `licensing/audit_events.py:150`—: el export lo importa en vez de
    copiarlo (`licensing/trueup_export.py:31`) y ya no tiene filtro propio por `model`."""
    from src.models.audit import AuditLog
    db = factory()
    try:
        return db.query(AuditLog).filter(AuditLog.model == RESERVADO).count()
    finally:
        db.close()


def mensaje(respuesta):
    return respuesta.json()["error"]["message"]


# ── /gw: sanear → auditar → rechazar ──────────────────────────────────────────────


def test_el_pedido_con_modelo_reservado_queda_auditado_con_centinela_y_se_rechaza(
        harness, proveedor):
    """El orden entero en un solo test: la fila durable existe (con el centinela y con el
    veredicto real de las capas), el cliente se lleva un 422 que explica por qué, y el
    proveedor no vio nunca el pedido."""
    client, factory = harness

    respuesta = client.post(GW, json=cuerpo(RESERVADO))

    assert respuesta.status_code == 422, respuesta.text
    assert "literal reservado" in mensaje(respuesta)
    assert RESERVADO in mensaje(respuesta), "el error tiene que nombrar el literal"

    assert filas(factory) == [{"model": CENTINELA, "compliance_status": "passed",
                               "prompt_tokens": 0, "completion_tokens": 0}]
    assert proveedor.llamadas == [], "el rechazo es ANTES del proveedor"


def test_la_cadena_de_licencias_no_gana_eslabones_ajenos(harness):
    """El daño nº3 del hallazgo: `verify_chain` y el true-up releen TODAS las filas
    `model='license'`. Una fila de tráfico ahí adentro —sin `seq` ni hash— puede hacer que la
    verificación acuse TAMPER y que el true-up del cliente falle. O sea: el cliente podía
    romperle al operador la evidencia con la que le factura, desde el body de un pedido."""
    client, factory = harness
    client.post(GW, json=cuerpo(RESERVADO))
    assert filas_de_la_cadena(factory) == 0


def test_la_fila_no_es_inmortal_ni_invisible(harness):
    """Los daños nº1 y nº2, afirmados como los ven los lectores: TODOS excluyen la cadena por
    igualdad exacta sobre `model`, así que basta con que la fila no sea el literal para que la
    retención la alcance y la vitrina la cuente. El centinela recupera las dos propiedades sin
    disfrazar la fila de tráfico normal."""
    client, factory = harness
    client.post(GW, json=cuerpo(RESERVADO))

    guardada = filas(factory)[0]["model"]
    assert guardada != RESERVADO
    assert guardada == CENTINELA, "el centinela es explícito, no un genérico anónimo"


@pytest.mark.parametrize("declarado", [" license ", "License", "LICENSE", "\tlicense\n"])
def test_las_variantes_de_caja_y_espacios_tampoco_entran(harness, declarado):
    """`" License "` es el mismo intento con otra ropa y no tiene un solo uso legítimo. Hoy los
    lectores comparan el literal exacto —así que estas variantes ya serían mortales y
    visibles—, pero normalizar antes de decidir cierra la puerta que reabriría el primer lector
    que se escriba con `TRIM` o `ILIKE`."""
    client, factory = harness
    assert client.post(GW, json=cuerpo(declarado)).status_code == 422
    assert [f["model"] for f in filas(factory)] == [CENTINELA]


def test_un_bloqueo_real_con_modelo_reservado_sigue_siendo_bloqueo_y_no_pierde_la_fila(
        harness, proveedor):
    """El caso feo del hallazgo: el atacante se escondía con un bloqueo REAL. El veredicto
    sobre el contenido sigue mandando —400 con el motivo del bloqueo, no el 422 por el
    nombre— y la fila queda igual, con su estado de bloqueo y con el centinela."""
    client, factory = harness

    respuesta = client.post(GW, json=cuerpo(RESERVADO, f"la clave es {SECRETO}"))

    assert respuesta.status_code == 400, respuesta.text
    assert "material secreto" in mensaje(respuesta)
    assert filas(factory) == [{"model": CENTINELA, "compliance_status": "blocked_secret",
                               "prompt_tokens": 0, "completion_tokens": 0}]
    assert filas_de_la_cadena(factory) == 0
    assert proveedor.llamadas == []


# ── /gw: el tráfico legítimo no se toca ───────────────────────────────────────────


def test_el_trafico_legitimo_pasa_y_se_audita_con_su_nombre(harness, proveedor):
    client, factory = harness

    respuesta = client.post(GW, json=cuerpo(LEGITIMO))

    assert respuesta.status_code == 200, respuesta.text
    assert [f["model"] for f in filas(factory)] == [LEGITIMO]
    assert len(proveedor.llamadas) == 1


@pytest.mark.parametrize("declarado", ["license-v2", "licenses", "mi-license", "licencia"])
def test_lo_que_solo_se_parece_al_literal_no_se_toca(harness, declarado):
    """Contracara de la normalización: el criterio es igualdad, NO prefijo ni substring. Un
    saneo que mordiera de más le cambiaría el nombre a modelos reales en la columna que el
    officer lee — el reporte mentiría por el otro lado."""
    client, factory = harness
    assert client.post(GW, json=cuerpo(declarado)).status_code == 200
    assert [f["model"] for f in filas(factory)] == [declarado]


# ── /internal/audit: sanear y NADA más ────────────────────────────────────────────


def test_internal_audit_persiste_el_centinela_y_responde_ok(harness):
    """La fila del motor llega DESPUÉS del hecho: se sanea el nombre y se registra igual."""
    client, factory = harness

    respuesta = client.post(AUDIT, headers=CABECERA_INTERNA, json={
        "model": RESERVADO, "compliance_status": "passed",
        "prompt_tokens": 10, "completion_tokens": 5, "latency_ms": 42,
    })

    assert respuesta.status_code == 200, respuesta.text
    assert [f["model"] for f in filas(factory)] == [CENTINELA]
    assert filas_de_la_cadena(factory) == 0


def test_internal_audit_nunca_rechaza_la_fila_del_motor(harness):
    """El invariante que separa este escritor del otro: acá NO se rechaza ni siquiera cuando el
    nombre es el literal reservado. El pedido ya se sirvió o ya se bloqueó; un 4xx no impide
    nada y sí tira auditoría durable ya generada — el agujero que la 031 cerró en este mismo
    endpoint y el que la 018 viene a proteger."""
    client, factory = harness

    respuesta = client.post(AUDIT, headers=CABECERA_INTERNA, json={
        "model": RESERVADO, "compliance_status": "blocked_secret",
        "blocked_by_layer": "secret_detection", "latency_ms": 7,
    })

    assert respuesta.status_code == 200, respuesta.text
    assert filas(factory) == [{"model": CENTINELA, "compliance_status": "blocked_secret",
                               "prompt_tokens": 0, "completion_tokens": 0}]


def test_internal_audit_no_le_cambia_el_nombre_al_trafico_legitimo(harness):
    client, factory = harness

    respuesta = client.post(AUDIT, headers=CABECERA_INTERNA, json={
        "model": LEGITIMO, "compliance_status": "passed", "latency_ms": 30,
    })

    assert respuesta.status_code == 200, respuesta.text
    assert [f["model"] for f in filas(factory)] == [LEGITIMO]


# ── Los dos escritores, la misma regla ────────────────────────────────────────────


def test_ningun_escritor_deja_alcanzable_el_literal_reservado(harness):
    """El punto entero de la capa B: el literal reservado no depende de por qué puerta entró el
    pedido. Se ejercitan los DOS escritores en la misma base y la cadena sigue vacía."""
    client, factory = harness

    client.post(GW, json=cuerpo(RESERVADO))
    client.post(AUDIT, headers=CABECERA_INTERNA,
                json={"model": RESERVADO, "compliance_status": "passed", "latency_ms": 1})

    modelos = sorted(f["model"] for f in filas(factory))
    assert modelos == [CENTINELA, CENTINELA]
    assert filas_de_la_cadena(factory) == 0
