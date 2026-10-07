"""Recomendación de T-C (handoff-notas-tramo-c.md): un id publicado en la cara Claude tiene que empezar con `claude`.

Claude Code descarta del lado del cliente lo que no reconoce (`unrecognized_model`): un id como `gpt-5.4-mini`
publicado en esa cara nunca lo usaría esa herramienta. La API de administración lo rechaza con 422 y un texto claro."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redirect_api_fixtures as fx  # noqa: E402


@pytest.fixture
def api(monkeypatch):
    return fx.make_api(monkeypatch)


def publicar(api, face, public_id, **kw):
    return api.call("POST", "/published-models", "tenant_admin", json={"face": face, "public_id": public_id, **kw})


@pytest.mark.parametrize("public_id", ["gpt-5.4-mini", "mi-modelo", "qwen3-max", "xclaude-sonnet"])
def test_en_la_cara_claude_un_id_que_no_empieza_con_claude_es_422(api, public_id):
    r = publicar(api, "claude", public_id)
    assert r.status_code == 422
    assert "claude" in r.text.lower() and "Claude Code" in r.text


@pytest.mark.parametrize("public_id", ["claude-sonnet-4-5", "claude-opus-4-1-20250805", "Claude-Haiku", "claude"])
def test_un_id_que_empieza_con_claude_se_acepta(api, public_id):
    assert publicar(api, "claude", public_id).status_code == 201


@pytest.mark.parametrize("face", ["openai_generic", "codex"])
def test_las_otras_caras_no_tienen_esa_restriccion(api, face):
    assert publicar(api, face, "gpt-5.4-mini").status_code == 201


def test_el_rechazo_no_deja_filas_ni_registro(api):
    publicar(api, "claude", "gpt-5.4-mini")
    assert api.call("GET", "/published-models", "tenant_admin").json()["data"] == []
    assert api.audits("published_model") == []
