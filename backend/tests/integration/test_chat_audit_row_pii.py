"""Coherencia interna de la FILA DURABLE del plano chat (spec 027, US2).

Hallazgo de la ronda adversarial: con `pii_masking=off` y un texto con datos personales, la
misma fila de `audit_logs` afirmaba dos cosas opuestas —`applied_layers` decía
`{"layer_code":"pii_detection","status":"applied","decision":"flag","count":N}` y las
columnas legadas de esa MISMA fila quedaban `pii_detected=false` / `masked_entities=null`.
La causa era que `pii_detected` se derivaba de las entidades ENMASCARADAS, que solo existen
cuando el enmascarado corrió.

Por qué es la peor combinación posible: los lectores de cumplimiento —el export Art.30, el
panel, cualquier query histórica— leen las columnas legadas, no el JSONB nuevo. O sea que
justo en los pedidos donde SÍ hubo datos personales **y encima salieron sin enmascarar**, el
informe decía "no hubo datos personales".

Lo que se fija acá es la semántica elegida, no la implementación:

- `pii_detected` refleja la DETECCIÓN (el piso). Responde "¿este pedido llevaba PII?", no
  "¿la enmascaramos?".
- `masked_entities` es el desglose `[{type, count}]` de lo DETECTADO — formato intacto para
  no romper a sus lectores, y metadata-only (C1: jamás el valor detectado).
- El matiz que las columnas legadas no pueden expresar —"detectado pero no enmascarado"— lo
  lleva `applied_layers` de la misma fila (`pii_masking: skipped`). Las columnas afirman el
  piso; el registro nuevo dice si se neutralizó.

El invariante que ordena todo: **`count` de `pii_detection` y `masked_entities` salen de la
misma medición**, así que no pueden divergir dentro de una fila.

El motor se mockea a nivel del namespace de `chat`: lo que se verifica es qué quedó escrito,
y atarlo a que haya un modelo levantado convertiría un test de contrato en uno de entorno.
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

DB = "basa_test_chat_audit_row_pii"

CHAT = "/api/v1/chat/completions"
MODELO = "ollama-qwen3-4b"

# Dato personal detectable por el detector local (EMAIL_ADDRESS), evitando a propósito los
# `custom_names` del seed para que el hallazgo venga del detector y no de una lista del demo.
CON_PII = "Mandale el informe a laura.gomez@ejemplo.com y avisá cuando salga."
SIN_PII = "Resumime en una línea qué hace este servicio."


# ── Doble del motor ───────────────────────────────────────────────────────────────


class _FakeResponse:
    status_code = 200
    text = "ok"
    headers = {"x-litellm-response-cost": "0.00012"}

    @staticmethod
    def json():
        return {
            "choices": [{"message": {"content": "listo"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }


class _FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, *_args, **_kwargs):
        return _FakeResponse()


class _FakeHttpx:
    @staticmethod
    def AsyncClient(*_args, **_kwargs):  # noqa: N802 — espeja el nombre real
        return _FakeClient()


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    # El chat es fail-closed: sin credencial es 401. La sesión va en el cliente y no en cada
    # llamada porque lo que se mide acá es la fila de auditoría, no la autenticación. El
    # usuario es el mismo 'admin' del tenant default al que antes se caía el fallback anónimo.
    client.headers.update(admin_headers(client))
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def motor_mockeado(monkeypatch):
    from src.api import chat
    monkeypatch.setattr(chat, "httpx", _FakeHttpx)


@pytest.fixture(autouse=True)
def limpiar(harness):
    """Cada test arranca sin filas de decisión (la postura es una cascada: una fila huérfana
    la cambia sin que se note) y con el catálogo de guardianes intacto."""
    yield
    _, factory = harness
    from src.models.governance import GovernanceProfile
    from src.models.guardian import Guardian
    db = factory()
    try:
        db.query(GovernanceProfile).delete()
        for guardian in db.query(Guardian).all():
            if guardian.guardian_type in ("pii_masking", "secret_detection"):
                guardian.is_active = True
        db.commit()
    finally:
        db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────────


def pedir(client, mensaje, **extra):
    return client.post(CHAT, json={"message": mensaje, "model": MODELO, **extra})


def calentar_catalogo(client):
    """Primer pedido: deja el catálogo de 9 guardianes sembrado. El seed BORRA la tabla y
    re-siembra cuando hay menos de 9 filas, así que sin esto un cambio de postura previo
    quedaría destruido por el propio seed."""
    respuesta = pedir(client, SIN_PII)
    assert respuesta.status_code == 200, respuesta.text


def apagar_enmascarado(factory):
    from src.models.governance import GovernanceProfile
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        db.add(GovernanceProfile(tenant_id=DEFAULT_TENANT_ID, scope_type="tenant_default",
                                 scope_value="*", layer_key="pii_masking",
                                 decision="off", updated_by="suite-027"))
        db.commit()
    finally:
        db.close()


def ultima_fila(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        fila = db.query(AuditLog).order_by(AuditLog.timestamp.desc(),
                                           AuditLog.id.desc()).first()
        assert fila is not None, "el pedido no dejó fila de auditoría"
        # Se leen los atributos antes de cerrar la sesión (objeto desprendido después).
        return {
            "pii_detected": fila.pii_detected,
            "masked_entities": fila.masked_entities,
            "applied_layers": fila.applied_layers,
        }
    finally:
        db.close()


def capa(fila, layer_code):
    for entrada in fila["applied_layers"] or []:
        if entrada.get("layer_code") == layer_code:
            return entrada
    raise AssertionError(f"`applied_layers` no trae {layer_code}: {fila['applied_layers']}")


def total(masked_entities):
    return sum(int(e.get("count", 1) or 1) for e in masked_entities or [])


# ── El hallazgo ───────────────────────────────────────────────────────────────────


def test_enmascarado_apagado_la_fila_registra_la_pii_detectada(harness):
    """`pii_masking=off` + texto con PII ⇒ `pii_detected=true` y `masked_entities` coherente.

    Antes esta fila decía `pii_detection: flag [N]` en `applied_layers` y `pii_detected=false`
    / `masked_entities=null` en las columnas legadas: el informe de cumplimiento afirmaba "no
    hubo datos personales" en el pedido donde los hubo Y salieron sin enmascarar.
    """
    client, factory = harness
    calentar_catalogo(client)
    apagar_enmascarado(factory)

    assert pedir(client, CON_PII).status_code == 200
    fila = ultima_fila(factory)

    deteccion = capa(fila, "pii_detection")
    assert deteccion["status"] == "applied", "la detección es PISO: corre con el masking off"
    assert deteccion["decision"] == "flag"
    assert deteccion["count"] >= 1

    # El arreglo: las columnas legadas afirman lo mismo que el registro nuevo.
    assert fila["pii_detected"] is True, \
        "la fila no puede decir 'no hubo datos personales' cuando su propia atribución los cuenta"
    assert fila["masked_entities"], "sin desglose, el export Art.30 no tiene qué reportar"
    assert total(fila["masked_entities"]) == deteccion["count"], \
        "columna legada y `applied_layers` salen de la misma medición: no pueden divergir"

    # El matiz que las columnas legadas no expresan lo lleva `applied_layers`: la fila dice
    # "hubo PII" (piso) y por separado "el enmascarado estaba apagado por decisión".
    assert capa(fila, "pii_masking")["status"] == "skipped"

    # C1: metadata-only. La columna lleva tipo y contador, jamás el valor detectado.
    for entrada in fila["masked_entities"]:
        assert set(entrada) == {"type", "count"}, entrada
        assert "laura" not in str(entrada).lower()


def test_enmascarado_encendido_la_fila_sigue_registrando_la_pii(harness):
    """La postura por defecto no se rompe: enmascarado ON ⇒ misma coherencia."""
    client, factory = harness
    calentar_catalogo(client)

    assert pedir(client, CON_PII).status_code == 200
    fila = ultima_fila(factory)

    assert fila["pii_detected"] is True
    assert total(fila["masked_entities"]) == capa(fila, "pii_detection")["count"]
    assert capa(fila, "pii_masking")["status"] == "applied"
    assert capa(fila, "pii_masking")["decision"] == "mask"


@pytest.mark.parametrize("apagar", [True, False])
def test_texto_limpio_no_inventa_pii_en_ninguna_postura(harness, apagar):
    """El arreglo no puede volverse un falso positivo: sin datos personales la fila dice que
    no los hubo, con el enmascarado encendido o apagado."""
    client, factory = harness
    calentar_catalogo(client)
    if apagar:
        apagar_enmascarado(factory)

    assert pedir(client, SIN_PII).status_code == 200
    fila = ultima_fila(factory)

    assert fila["pii_detected"] is False
    assert not fila["masked_entities"]
    assert capa(fila, "pii_detection")["decision"] == "allow"
