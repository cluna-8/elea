"""Piso de `api_version` de Azure solo para la llamada a Responses (057, Azure OpenAI).

Cuando el puente (T193) pasa un pedido a Responses hacia Azure, la `api_version` de la credencial puede ser
anterior a la que documenta Responses con razonamiento (2025-04-01-preview; Responses nace en 2025-03-01-preview).
El guard usa el piso SOLO para esa llamada: chat/completions conserva la versión de la credencial. Se audita solo
el NOMBRE del campo ajustado, jamás un valor.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from sentinel.engine import redirect_catalog as rcat  # noqa: E402
from sentinel.engine import redirect_guard as g  # noqa: E402
from sentinel.redirect import authz  # noqa: E402

KEY = "k" * 48
NOW = 1_800_000_000.0
FLOOR = "2025-04-01-preview"
TOOLS = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]
SECRET = "sk-azure-solo-de-prueba"      # secret-scanner: allow (valor inventado de un fixture de test)


def _token(api_version, model="rdx-azure/gpt-6-luna"):
    return authz.issue(
        request_id="req-1", scope="t1/connection:k1", destination_id="d1", model=model, provider="azure",
        credential={"api_key": SECRET, "api_version": api_version}, api_base="https://r.openai.azure.com",
        provider_options={}, forced_masking=False,
        decision={"public_id": "pro", "face": "openai_generic", "rule_id": "r1"}, key=KEY, now=NOW)


def _apply(api_version, call_type="acompletion", model="rdx-azure/gpt-6-luna", **extra):
    hdrs = {"X-Redirect-Authz": _token(api_version, model)}
    data = {"model": model, "messages": [{"role": "user", "content": "hola"}],
            "proxy_server_request": {"headers": dict(hdrs)}, "metadata": {"headers": dict(hdrs)}, **extra}
    return g.apply_redirect(data, key=KEY, now=NOW, environ={}, call_type=call_type)


def _adjusted(out):
    home = out.get("litellm_metadata") if "litellm_metadata" in out else out["metadata"]
    return ((home.get("_internal_routing_decision") or {}).get("extensions", {}).get("redirect", {})
            .get("adjusted_params", ""))


@pytest.mark.parametrize("old", ["2024-10-21", "2024-12-01-preview", "2025-03-01-preview", "2023-05-15"])
def test_el_puente_a_responses_sube_una_version_vieja_al_piso(old):
    out = _apply(old, tools=TOOLS, reasoning_effort="high")
    assert out["model"] == "rdx-azure/responses/gpt-6-luna"
    assert out["api_version"] == FLOOR
    assert "api_version" in _adjusted(out).split(",") and "chat->responses" in _adjusted(out)


@pytest.mark.parametrize("ok", [FLOOR, "2025-06-01-preview", "2025-04-01", "2026-01-01-preview"])
def test_una_version_igual_o_posterior_al_piso_no_se_toca(ok):
    out = _apply(ok, tools=TOOLS, reasoning_effort="high")
    assert out["model"] == "rdx-azure/responses/gpt-6-luna" and out["api_version"] == ok
    assert "api_version" not in _adjusted(out).split(",")


@pytest.mark.parametrize("opaque", ["v1", "latest", "preview", ""])
def test_una_version_que_no_es_una_fecha_no_se_toca(opaque):
    out = _apply(opaque, tools=TOOLS, reasoning_effort="high")
    assert out["api_version"] == opaque


def test_chat_completions_conserva_la_version_de_la_credencial():
    out = _apply("2024-10-21")                               # sin tools: no hay puente, sigue por chat
    assert out["model"] == "rdx-azure/gpt-6-luna" and out["api_version"] == "2024-10-21"
    assert "api_version" not in _adjusted(out).split(",")


def test_un_modelo_que_no_razona_conserva_la_version_aunque_traiga_tools():
    out = _apply("2024-10-21", model="rdx-azure/gpt-4.1", tools=TOOLS)
    assert out["model"] == "rdx-azure/gpt-4.1" and out["api_version"] == "2024-10-21"


def test_la_llamada_nativa_a_responses_tambien_usa_el_piso():
    out = _apply("2024-10-21", call_type="aresponses")
    assert out["api_version"] == FLOOR


def test_la_auditoria_no_lleva_valores_ni_secretos():
    out = _apply("2024-10-21", tools=TOOLS)
    assert "2024-10-21" not in repr(out.get("metadata")) and SECRET not in repr(out.get("metadata"))


def test_otro_proveedor_no_se_ajusta():
    d = {"model": "rdx-openai/responses/gpt-6-luna", "api_version": "2024-10-21"}
    assert g.raise_responses_api_version(d, "openai") == [] and d["api_version"] == "2024-10-21"


def test_el_helper_es_idempotente_y_no_inventa_el_campo():
    d = {"model": "rdx-azure/responses/gpt-6-luna", "api_version": "2024-10-21"}
    assert g.raise_responses_api_version(d, "azure") == ["api_version"] and d["api_version"] == FLOOR
    assert g.raise_responses_api_version(d, "azure") == []
    d = {"model": "rdx-azure/responses/gpt-6-luna"}
    assert g.raise_responses_api_version(d, "azure") == [] and "api_version" not in d


# --- ruta directa del catálogo (misma regla) --------------------------------------------------------------------

T1 = "11111111-1111-1111-1111-111111111111"
ENTRY = {"entry_id": "e1", "name": "GPT 6 luna", "provider": "azure", "real_model": "gpt-6-luna",
         "api_base": "https://r.openai.azure.com", "protocol_family": "openai_chat", "level": "tenant",
         "semaforo": {"estado": "standard", "motivos": []}, "jurisdiccion": "unknown",
         "price": {"input": None, "output": None}}


def _backend(api_version):
    async def fetch(path, params):
        if path.endswith("model-access"):
            return 200, {"restringe": False, "permitidos": []}
        if path.endswith("model-catalog"):
            return 200, {"version": "v1", "direct": True, "entries": {"gpt-6-luna": ENTRY}}
        return 200, {"credential": {"api_key": SECRET, "api_version": api_version}}
    return fetch


async def _direct(api_version, **extra):
    data = {"model": "gpt-6-luna", "messages": [{"role": "user", "content": "hola"}], **extra}
    user = SimpleNamespace(metadata={"sentinel": {"tenant_id": T1}})
    assert await rcat.CatalogDirect(fetch=_backend(api_version), environ={}).apply(data, user, call_type="acompletion")
    return data


async def test_directo_con_puente_sube_la_version_vieja_al_piso():
    d = await _direct("2024-10-21", tools=TOOLS, reasoning_effort="high")
    assert d["model"].endswith("/responses/gpt-6-luna") and d["api_version"] == FLOOR
    assert "api_version" in d["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]["adjusted_params"].split(",")


async def test_directo_por_chat_conserva_la_version():
    d = await _direct("2024-10-21")
    assert not d["model"].endswith("/responses/gpt-6-luna") and d["api_version"] == "2024-10-21"
