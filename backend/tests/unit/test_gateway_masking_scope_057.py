"""S14 en el camino de SUSCRIPCIÓN de la pasarela (057 T097; research R29; contracts/costuras-base.md §S14).

La suscripción no pasa por el guardrail del motor: la propia pasarela enmascara (`evaluate_request_policy`).
Un plugin de pasarela pide el alcance completo con `governance_overrides["masking_scope"] = "full"` (junto con
`pii_masking` y `nlp_fail_mode = block`, como hace `_subscription_posture` de la extensión): entonces se
enmascara TODO lo que sale hacia el proveedor y lo no analizable se BLOQUEA (400 con la forma de Anthropic,
fila `blocked_residency` atribuida a la capa `pii_masking`).

Sin ese override, la pasarela se comporta exactamente como antes (la batería T003 lo sigue fijando).

Reusa el motor/proveedor falso de la batería de T003 (`backend/tests/contract/test_gw_no_regresion_057.py`).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contract"))

import test_gw_no_regresion_057 as t3  # noqa: E402
from test_gw_no_regresion_057 import bateria  # noqa: E402,F401  (fixture)
from src.api import gateway, gateway_plugins as gp  # noqa: E402

# El detector de la pasarela resuelve la región del tenant (sin `ident["nlp"]`: la de la instalación, `eu`):
# se usa un dato que no depende de la región.
DNI = "ana.garcia@example.com"
CUIT = "luis.perez@example.com"


class _PluginForzado:
    """Lo que hace la extensión cuando la postura exige enmascarado forzado en suscripción."""

    def __init__(self, **overrides):
        self.overrides = overrides or {"pii_masking": True, "nlp_fail_mode": "block", "masking_scope": "full"}

    def pre_request(self, ctx):
        ctx.governance_overrides.update(self.overrides)
        return None


@pytest.fixture
def forzado(bateria):                                           # noqa: F811
    gp.register_gateway_plugin(_PluginForzado())
    yield bateria
    gp.clear_gateway_plugins()


def _publicar(b, cuerpo):
    b.upstream.guion = {t3._MENSAJES_PROVEEDOR: t3._Respuesta(200, t3.RESP_OK)}
    b.upstream.llamadas.clear()
    b.auditorias.clear()
    return b.cliente.post("/gw/v1/messages", headers=t3._SUSCRIPCION, json=cuerpo)


def _pedido():
    return {"model": "claude-3-5-sonnet-20241022", "max_tokens": 64,
            "system": f"Atendés al cliente {CUIT}.",
            "messages": [
                {"role": "user", "content": "hola"},
                {"role": "assistant", "content": [{"type": "text", "text": f"Anoto el correo {DNI}"}]},
            ],
            "tools": [{"name": "buscar", "description": f"Busca por correo {DNI}",
                       "input_schema": {"type": "object", "properties": {}}}]}


def test_con_masking_scope_full_se_enmascara_todo_lo_que_sale_hacia_el_proveedor(forzado):
    r = _publicar(forzado, _pedido())
    assert r.status_code == 200
    enviado = forzado.upstream.llamadas[-1]["content"]
    enviado = enviado.decode() if isinstance(enviado, bytes) else enviado
    assert DNI not in enviado and CUIT not in enviado
    cuerpo = json.loads(enviado)
    assert cuerpo["model"] == "claude-3-5-sonnet-20241022" and cuerpo["tools"][0]["name"] == "buscar"
    assert forzado.auditorias[-1]["estado"] != "blocked_residency"


@pytest.mark.parametrize("bloque", [
    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
    {"type": "document", "source": {"type": "url", "url": "https://x.example/a.pdf"}},
    {"type": "tipo_que_no_existe", "x": "y"},
])
def test_lo_no_analizable_se_bloquea_antes_de_llamar_al_proveedor(forzado, bloque):
    cuerpo = _pedido()
    cuerpo["messages"][0]["content"] = [{"type": "text", "text": "mirá"}, bloque]
    r = _publicar(forzado, cuerpo)
    assert r.status_code == 400
    error = r.json()["error"]
    assert error["type"] == "invalid_request_error"
    assert "no pudo protegerse" in error["message"] and "Sentinel Gateway" in error["message"]
    assert forzado.upstream.llamadas == [], "no se llamó al proveedor"
    fila = forzado.auditorias[-1]
    assert fila["estado"] == "blocked_residency" and fila["bloqueada_por"] == "pii_masking"
    assert fila["entidades"] == [], "la fila no lleva contenido ni valores"


def test_un_dato_en_una_posicion_estructural_bloquea(forzado):
    cuerpo = _pedido()
    cuerpo["messages"][1]["content"] = [{"type": "tool_use", "id": DNI, "name": "buscar", "input": {}}]
    r = _publicar(forzado, cuerpo)
    assert r.status_code == 400 and forzado.upstream.llamadas == []


def test_analizador_caido_bloquea_bajo_el_forzado_aunque_la_empresa_diga_degrade(forzado, monkeypatch):
    async def _caido(texto, *a, **k):
        raise gateway.policy.NlpUnavailableError("down")

    monkeypatch.setattr(gateway.policy, "default_analyze", _caido)
    r = _publicar(forzado, _pedido())
    assert r.status_code == 400 and forzado.upstream.llamadas == []


def test_sin_el_override_el_comportamiento_es_el_de_siempre(bateria):
    gp.clear_gateway_plugins()
    r = _publicar(bateria, _pedido())
    assert r.status_code == 200
    enviado = bateria.upstream.llamadas[-1]["content"]
    enviado = enviado.decode() if isinstance(enviado, bytes) else enviado
    assert CUIT in enviado and DNI in enviado, "sin la señal: solo los turnos user, como siempre"


@pytest.mark.parametrize("valor", ["user", "todo", True, None, 1])
def test_un_masking_scope_que_no_es_full_no_cambia_nada(bateria, valor):
    gp.register_gateway_plugin(_PluginForzado(masking_scope=valor))
    try:
        r = _publicar(bateria, _pedido())
    finally:
        gp.clear_gateway_plugins()
    assert r.status_code == 200
    enviado = bateria.upstream.llamadas[-1]["content"]
    enviado = enviado.decode() if isinstance(enviado, bytes) else enviado
    assert CUIT in enviado, "solo `full` activa el alcance completo"
