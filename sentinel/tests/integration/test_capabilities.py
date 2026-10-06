"""Capacidades por destino: salto al siguiente que las tiene y rechazo claro y auditado (069 T103;
FR-008a/b/c/d). Corre el plugin con una instantánea de dos destinos traducidos."""
import json

import pytest

from sentinel.redirect import authz
from sentinel.redirect.plugin import RedirectPlugin, STATE_KEY
from sentinel.tests import redirect_fixtures as fx

SIN_IMAGENES = {**fx.DEST_CHAT, "id": "d-sin", "name": "Texto UE", "real_model": "qwen-texto",
                "capability_profile": {"images": False}}
CON_IMAGENES = {**fx.DEST_CHAT, "id": "d-con", "name": "Visión UE", "real_model": "qwen-vision",
                "capability_profile": {"images": True, "documents_pdf": False}}
IMG = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)


def snap(targets):
    s = fx.snapshot("on", claude_targets=tuple(targets))
    dests = {**s.destinations, "d-sin": SIN_IMAGENES, "d-con": CON_IMAGENES}
    creds = {**s.credentials, "d-sin": json.dumps({"api_key": "k1"}), "d-con": json.dumps({"api_key": "k2"})}
    from dataclasses import replace
    return replace(s, destinations=dests, credentials=creds)


def body(*content, history=()):
    return {"model": "claude-sonnet-4-5", "max_tokens": 10,
            "messages": [*history, {"role": "user", "content": list(content)}]}


async def run(targets, b):
    p = RedirectPlugin(store=fx.store(snap(targets)), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5")
    assert await p.pre_request(c) is None
    out, headers = p.pre_engine(c, b, {})
    return p, c, out, headers


async def test_sin_necesidades_se_sirve_el_primer_destino():
    _, c, out, headers = await run(["d-sin", "d-con"], body({"type": "text", "text": "hola"}))
    assert out["model"] == "rdx-chatcompat/qwen-texto"
    assert authz.verify(headers[authz.HEADER]).credential == {"api_key": "k1"}


async def test_imagen_salta_al_siguiente_destino_que_la_acepta():
    _, c, out, headers = await run(["d-sin", "d-con"], body(IMG, {"type": "text", "text": "¿qué ves?"}))
    assert out["model"] == "rdx-chatcompat/qwen-vision"
    claims = authz.verify(headers[authz.HEADER])
    assert claims.credential == {"api_key": "k2"}              # la credencial del destino elegido
    dec = c.routing_decision["extensions"]["redirect"]
    assert dec["destination_id"] == "d-con" and dec["substitution_reason"] == "capability"


async def test_imagen_sin_ningun_destino_capaz_es_rechazo_claro_con_marcador():
    p, c, out, headers = await run(["d-sin"], body(IMG))
    assert out["model"].startswith("rdx-rejected") and authz.HEADER not in headers
    st, raw, _ = p.map_error(c, 403, b"{}")
    err = json.loads(raw)["error"]
    assert st == 400 and err["message"].startswith("capability_rejected: images")
    assert "imagen" in err["message"]
    assert c.state[STATE_KEY].decision["rejected"] == "images"          # lo que audita map_error (FR-008c)


async def test_pdf_sigue_la_misma_regla():
    doc = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "AA"}}
    p, c, out, _ = await run(["d-con"], body(doc))
    assert out["model"].startswith("rdx-rejected")
    assert c.state[STATE_KEY].decision["rejected"] == "documents_pdf"


async def test_destino_nativo_acepta_todo_sin_perfil():
    snap_nativo = fx.snapshot("on", claude_targets=("d-ant",))
    p = RedirectPlugin(store=fx.store(snap_nativo), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", nlp={"region": "us"})
    await p.pre_request(c)
    out, _ = p.pre_engine(c, body(IMG), {})
    assert out["model"] == "rdx-anthropic/claude-real"


# ── cara genérica: solo se niega lo declarado explícitamente falso (FR-039) ───────────────

def gbody(*parts, history=()):
    return {"model": "pro", "messages": [*history, {"role": "user", "content": list(parts)}]}


GIMG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}


async def grun(dest, b):
    from dataclasses import replace
    s = fx.snapshot("on", targets=("d-x",))
    s = replace(s, destinations={**s.destinations, "d-x": dest}, credentials={**s.credentials, "d-x": json.dumps({"api_key": "k"})})
    p = RedirectPlugin(store=fx.store(s), ping_after=0.05)
    c = fx.ctx()
    await p.pre_request(c)
    out, h = p.pre_engine(c, b, {})
    return c, out


async def test_generica_destino_sin_perfil_recibe_la_imagen_como_siempre():
    c, out = await grun({**fx.DEST_CHAT, "id": "d-x", "capability_profile": {}}, gbody(GIMG))
    assert out["messages"][0]["content"][0] == GIMG


async def test_generica_destino_que_declara_sin_imagenes_la_rechaza():
    c, out = await grun({**fx.DEST_CHAT, "id": "d-x", "capability_profile": {"images": False}}, gbody(GIMG))
    assert out["model"].startswith("rdx-rejected")
    assert c.state[STATE_KEY].decision["rejected"] == "images"


async def test_el_selector_avisa_cuando_el_destino_no_acepta_imagenes():
    p = RedirectPlugin(store=fx.store(snap(["d-sin"])), ping_after=0.05)
    c = fx.ctx(route="/v1/models", model=None, headers={"anthropic-version": "2023-06-01"})
    await p.pre_request(c)
    names = [m["display_name"] for m in c.state[STATE_KEY + ".models_view"]["data"]]
    assert names and all(n.endswith("· sin imágenes") for n in names)
    p2 = RedirectPlugin(store=fx.store(snap(["d-con"])), ping_after=0.05)
    c2 = fx.ctx(route="/v1/models", model=None, headers={"anthropic-version": "2023-06-01"})
    await p2.pre_request(c2)
    assert not any("sin imágenes" in m["display_name"] for m in c2.state[STATE_KEY + ".models_view"]["data"])
