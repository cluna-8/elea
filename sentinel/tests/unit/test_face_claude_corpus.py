"""Corpus de pedidos de las herramientas Claude (T031): forma, sin secretos ni nombres internos."""
import json
import re
from pathlib import Path

import pytest

from sentinel.tests import corpus_claude as corpus

PROHIBIDOS = Path(__file__).resolve().parents[3] / "deploy" / "release" / "checks" / "prohibited_names.txt"


@pytest.mark.parametrize("name", corpus.NAMES)
def test_cada_archivo_es_sintetico_y_tiene_su_forma(name):
    doc = corpus.load(name)
    assert doc["synthetic"] is True and doc["tool"] in ("claude_code", "claude_desktop")
    if name == "claude_code_stream_largo":
        assert doc["events"][0]["event"] == "message_start" and doc["events"][-1]["event"] == "message_stop"
    else:
        assert doc["method"] == "POST" and doc["path"].startswith("/v1/messages")
        assert isinstance(doc["body"], dict) and doc["body"].get("model")


def test_el_corpus_cubre_lo_que_pide_t031():
    cc = corpus.load("claude_code_messages_beta")
    assert cc["query"] == {"beta": "true"} and "anthropic-beta" in cc["headers"]
    assert "safeguards" in cc["body"] and cc["body"]["stream"] is True and cc["body"]["tools"]
    assert corpus.load("claude_code_count_tokens")["path"].endswith("/count_tokens")
    assert corpus.load("claude_desktop_sondeo")["body"]["max_tokens"] == 1
    cw = corpus.load("cowork_multiturno")["body"]["messages"]
    assert len([m for m in cw if m["role"] == "user"]) >= 3
    assert any(isinstance(m["content"], list) and any(b.get("type") == "thinking" for b in m["content"])
               for m in cw)


def test_el_stream_largo_se_expande():
    events = corpus.stream_events()
    assert sum(1 for e in events if e["data"].get("delta", {}).get("type") == "text_delta") == 200
    raw = corpus.sse(events)
    assert raw.startswith(b"event: message_start\n") and raw.rstrip().endswith(b'"type": "message_stop"}')


def test_sin_secretos_ni_nombres_prohibidos():
    texto = "\n".join(p.read_text(encoding="utf-8") for p in corpus.CORPUS.glob("*.json")).lower()
    assert not re.search(r"sk-(ant|proj)-|bearer [a-z0-9]{30,}|-----begin", texto)
    for linea in PROHIBIDOS.read_text(encoding="utf-8").splitlines():
        nombre = linea.strip().lower()
        if nombre and not nombre.startswith("#"):
            assert nombre not in texto, nombre
