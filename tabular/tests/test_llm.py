"""Cliente hacia Guardian: cabecera acting-user, códigos de error y reintento sin temperature."""
import httpx
import pytest

from app.llm import EngineClient, EngineError


def _client(handler):
    c = EngineClient("http://engine/v1", "sk-test", "azure-gpt-4o-mini")
    transport = httpx.MockTransport(handler)
    c._post = lambda payload: httpx.Client(transport=transport).post(
        "http://engine/v1/chat/completions", json=payload,
        headers={"X-Guardian-Acting-User": c._acting or ""})
    return c


def test_ok_y_acting_user():
    seen = {}
    def h(req):
        seen["acting"] = req.headers.get("X-Guardian-Acting-User")
        seen["temp"] = req.read() and httpx.Request("POST", "x").read() is not None
        return httpx.Response(200, json={"model": "gpt-4o-mini", "choices": [{"message": {"content": " SELECT 1 "}}]})
    text, model = _client(h).chat([{"role": "user", "content": "x"}], acting_user_id="ana")
    assert (text, model) == ("SELECT 1", "gpt-4o-mini")
    assert seen["acting"] == "ana"


def test_reintento_sin_temperature():
    calls = []
    def h(req):
        body = req.read().decode()
        calls.append("temperature" in body)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"message": "Unsupported value: 'temperature' does not support 0.0"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "SELECT 2"}}]})
    text, _ = _client(h).chat([{"role": "user", "content": "x"}], acting_user_id=None)
    assert text == "SELECT 2" and calls == [True, False]


@pytest.mark.parametrize("status", [400, 401, 402, 500])
def test_errores(status):
    c = _client(lambda req: httpx.Response(status, json={"detail": "x"}))
    with pytest.raises(EngineError) as e:
        c.chat([{"role": "user", "content": "x"}], acting_user_id=None)
    assert e.value.status == status
