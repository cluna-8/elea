"""Lector del corpus de pedidos de las herramientas Claude (T031).

`load(nombre)` devuelve una copia profunda del archivo `fixtures/harness_corpus/claude/<nombre>.json`;
`stream_events(nombre)` expande `repeat` y `sse(events)` arma los bytes SSE de un destino.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

CORPUS = Path(__file__).resolve().parent / "fixtures" / "harness_corpus" / "claude"
NAMES = ("claude_code_messages_beta", "claude_code_count_tokens", "claude_desktop_sondeo",
         "cowork_multiturno", "claude_code_stream_largo")


def load(name: str) -> dict:
    return copy.deepcopy(json.loads((CORPUS / f"{name}.json").read_text(encoding="utf-8")))


def stream_events(name: str = "claude_code_stream_largo") -> list:
    doc = load(name)
    events = doc["events"]
    rep = doc.get("repeat")
    if rep:
        events = events[:rep["index"] + 1] + [copy.deepcopy(events[rep["index"]])
                                              for _ in range(rep["times"] - 1)] + events[rep["index"] + 1:]
    return events


def sse(events) -> bytes:
    return b"".join(f"event: {e['event']}\ndata: {json.dumps(e['data'], ensure_ascii=False)}\n\n".encode()
                    for e in events)


def headers_of(doc: dict) -> dict:
    return dict(doc.get("headers") or {})
