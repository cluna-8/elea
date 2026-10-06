"""Cara OpenAI genérica (contracts/cara-generica.md; T040/T057)."""
import pytest

from sentinel.redirect.faces import generic as face


def test_models_view():
    rows = [{"public_id": "pro"}, {"public_id": "flash", "created": 5}]
    v = face.models_view(rows, created=1758758400)
    assert v == {"object": "list", "data": [
        {"id": "flash", "object": "model", "created": 5, "owned_by": "organization"},
        {"id": "pro", "object": "model", "created": 1758758400, "owned_by": "organization"}]}


def test_view_selection_by_headers():
    assert face.select_models_view({"anthropic-version": "2023-06-01"}) == "claude"
    assert face.select_models_view({"Anthropic-Version": "2023-06-01"}) == "claude"
    assert face.select_models_view({"authorization": "Bearer x"}) == "openai_generic"


@pytest.mark.parametrize("kind,status,code,etype", [
    ("not_available", 404, "model_not_found", "invalid_request_error"),
    ("region", 403, "region_not_allowed", "permission_error"),
    ("rate_limit", 429, None, "rate_limit_error"),
    ("overloaded", 503, None, "api_error"),
    ("capability", 400, "capability_rejected", "invalid_request_error"),
    ("policy_unavailable", 503, None, "api_error"),
])
def test_errors(kind, status, code, etype):
    st, headers, body = face.error_response(kind, capability="images")
    assert st == status
    assert body == {"error": {"message": body["error"]["message"], "type": etype, "param": None, "code": code}}
    assert "sentinel" not in body["error"]["message"].lower()
    if kind == "rate_limit":
        assert headers["retry-after"] == "10"


def test_rewrite_response_model():
    body = {"id": "x", "object": "chat.completion", "model": "hosted_vllm/qwen", "choices": []}
    assert face.rewrite_response_model(body, "pro")["model"] == "pro"
    assert body["model"] == "hosted_vllm/qwen"   # no muta


def test_prepare_request():
    body = {"model": "pro", "messages": [], "api_key": "x", "api_base": "https://evil",
            "max_tokens": 99999, "max_completion_tokens": 99999}
    out, removed = face.prepare_request(body, engine_model="rdx-chatcompat/qwen", max_output=4096)
    assert out["model"] == "rdx-chatcompat/qwen"
    assert "api_key" not in out and "api_base" not in out
    assert out["max_tokens"] == 4096 and out["max_completion_tokens"] == 4096
    assert "client_credentials" in removed


def test_models_view_trae_context_length_y_max_output_si_existen():
    """T194: Hermes toma la ventana de `context_length`; sin el campo cae a 256K."""
    rows = [{"public_id": "a", "context_window": 128000, "max_output": 32000},
            {"public_id": "b", "context_window": None}]
    data = {m["id"]: m for m in face.models_view(rows, created=1)["data"]}
    assert data["a"]["context_length"] == 128000 and data["a"]["max_output"] == 32000
    assert "context_length" not in data["b"] and "max_output" not in data["b"]
