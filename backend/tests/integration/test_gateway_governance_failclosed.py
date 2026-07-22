"""Fail-closed del plano gateway al resolver la postura (spec 027 US2, hallazgos de la
verificación adversarial).

Tres invariantes, uno por hallazgo, sin DB ni HTTP (las piezas son puras: la postura ya
llega leída en ``ident``):

1. **De qué tenant se aplica la postura no lo elige el cliente.** ``/gw/v1/messages`` se
   autentica con el OAuth de suscripción; ``X-Basa-Key`` es OPCIONAL y hasta la 027 solo
   decidía a nombre de quién se auditaba ([D-014]). Al pasar a decidir también las
   ``governance_decisions``, omitir el header equivalía a elegirse la postura del tenant por
   defecto — potencialmente más laxa que la del admin propio. Sin tenant atribuible las
   relajaciones se descartan y sobreviven solo las decisiones que AGREGAN.
2. **Ausencia de atribución = ``null``, jamás lista vacía** (contrato evento §8): ``[]``
   afirmaría "no corrió ninguna capa", que es mentira porque el piso corre siempre.
3. **El ``X-Basa-Redact: off`` ignorado deja rastro**: contador consultable, para que la
   degradación no dependa de que alguien estuviera mirando los logs.
"""
import uuid

import pytest

from src.api import gateway

TENANT = "00000000-0000-0000-0000-000000000001"


def _row(layer_key: str, decision: str, scope_type: str = "tenant_default",
         scope_value: str = "*") -> dict:
    """Fila de decisión tal como sale de la query (el resolutor acepta Mappings)."""
    return {"tenant_id": TENANT, "scope_type": scope_type, "scope_value": scope_value,
            "layer_key": layer_key, "decision": decision}


def _ident(*, api_key_id=None, decisions=()) -> dict:
    return {"tenant_id": TENANT, "api_key_id": api_key_id, "tool_type": None,
            "redact_enabled": None, "governance_decisions": tuple(decisions)}


# ── 1) La postura no se elige omitiendo un header ────────────────────────────────

def test_sin_atribucion_la_relajacion_del_tenant_no_aplica():
    # Escenario del hallazgo: el tenant por defecto tiene el enmascarado apagado y el
    # cliente simplemente NO manda X-Basa-Key. Antes se resolvía con esa postura laxa.
    profile = gateway._resolve_governance_profile(
        _ident(decisions=[_row("pii_masking", "off")]), "Claude Code", None)
    assert profile.is_on("pii_masking"), "sin tenant atribuible no puede relajarse el piso móvil"


def test_con_connection_resuelta_la_relajacion_si_aplica():
    # Contracara: la relajación es legítima cuando el pedido trae el dato provisionado por
    # el admin (una Connection). Si no, el fix habría roto el caso insignia de D8.
    profile = gateway._resolve_governance_profile(
        _ident(api_key_id=str(uuid.uuid4()), decisions=[_row("pii_masking", "off")]),
        "Claude Code", None)
    assert not profile.is_on("pii_masking")


def test_sin_atribucion_las_decisiones_que_agregan_sobreviven():
    # Fail-closed no es "ignorar al admin": una capa que el admin ENCENDIÓ sigue encendida.
    # El criterio es el máximo de {postura del tenant, defaults de producto}.
    profile = gateway._resolve_governance_profile(
        _ident(decisions=[_row("sensitive_routing", "on")]), None, None)
    assert profile.is_on("sensitive_routing")


def test_sin_atribucion_el_piso_sigue_completo():
    profile = gateway._resolve_governance_profile(_ident(), None, None)
    for layer_key in ("interception_audit", "pii_detection", "secret_detection",
                      "ai_act_evaluation"):
        assert profile.is_on(layer_key)


# ── 2) Shape del evento sin atribución ───────────────────────────────────────────

class _FakePipe:
    def __init__(self, sink):
        self.sink = sink

    def lpush(self, key, payload):
        self.sink.append(payload)

    def ltrim(self, *a):
        pass

    def expire(self, *a):
        pass

    def execute(self):
        pass


class _FakeRedis:
    def __init__(self):
        self.publicado = []

    def pipeline(self):
        return _FakePipe(self.publicado)


def test_evento_sin_atribucion_lleva_null_no_lista_vacia(monkeypatch):
    import json

    fake = _FakeRedis()
    monkeypatch.setattr(gateway, "get_redis", lambda: fake)
    gateway._publish_monitor(_ident(), "claude-code", "modelo", "passed", [], "prev")
    event = json.loads(fake.publicado[0])
    assert event["applied_layers"] is None      # "sin registro" ≠ "ninguna capa corrió"
    assert event["blocked_by_layer"] is None


# ── 3) Telemetría del header ignorado ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _contador_limpio():
    gateway.reset_redact_off_ignored()
    yield
    gateway.reset_redact_off_ignored()


def test_redact_off_se_ignora_y_queda_contado():
    assert gateway._redact_header_override("0") is None
    assert gateway._redact_header_override("false") is None
    assert gateway.redact_off_ignored_count() == 2


def test_redact_on_fuerza_y_no_cuenta():
    assert gateway._redact_header_override("1") == "on"
    assert gateway.redact_off_ignored_count() == 0
