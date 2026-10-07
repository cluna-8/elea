"""057 R40 — el default de `label_mode` es `requested`: el cliente ve el id Claude que pidió, nunca el destino.

Con Claude Desktop el selector solo muestra ids de la familia Claude y el administrador cambia el destino de cada tier sin
tocar el cliente. La etiqueta por defecto no debe contar a qué proveedor o modelo real va cada id (ni en `/v1/models` ni
en las respuestas): el nombre del destino es dato interno. `destination` y `custom` siguen existiendo, a elección.
"""
import json

import pytest

from sentinel.engine import redirect_guard  # noqa: F401  (el plugin lo importa por el guard)
from sentinel.redirect import models as m
from sentinel.redirect import stream
from sentinel.redirect.api import admin
from sentinel.redirect.faces import claude as face
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.redirect.store import Snapshot
from sentinel.tests import redirect_fixtures as fx

SECRETO = "Kimi K3 Secreto"
REAL = "moonshotai/kimi-k3"


def test_el_default_de_la_columna_y_del_formulario_de_la_api_es_requested():
    assert m.RedirectPublishedModel.__table__.c.label_mode.default.arg == "requested"
    assert admin.PublishedIn(face="claude", public_id="claude-sonnet-4-6").label_mode == "requested"
    assert "requested" in m.LABEL_MODES and "destination" in m.LABEL_MODES      # los otros modos siguen a elección


def test_una_fila_sin_modo_no_cuenta_el_destino_en_ninguna_de_las_dos_etiquetas():
    row = {"public_id": "claude-sonnet-4-6", "family_tier": "sonnet", "destination_name": SECRETO,
           "context_window": 262144, "without_images": True}
    entry = face.models_view([row], now_iso="2026-10-07T00:00:00Z")["data"][0]
    assert entry["display_name"] == "claude-sonnet-4-6"
    assert SECRETO not in json.dumps(entry) and "sin imágenes" not in json.dumps(entry)


def _snapshot(label_mode):
    dest = {**fx.DEST_CHAT, "id": "d-kimi", "name": SECRETO, "provider": "openrouter", "real_model": REAL,
            "capability_profile": {"images": True}, "api_base": None}
    pub = {"id": "p-cl", "tenant_id": fx.TENANT, "scope_type": "tenant", "scope_value": "*", "face": "claude",
           "public_id": "claude-sonnet-4-6", "family_tier": "sonnet", "is_family_default": True}
    if label_mode is not None:
        pub["label_mode"] = label_mode
    gen = {"id": "p-gen", "tenant_id": fx.TENANT, "scope_type": "tenant", "scope_value": "*", "face": "openai_generic",
           "public_id": "claude-sonnet-4-6"}
    rules = tuple({"id": f"r-{p['id']}", "tenant_id": fx.TENANT, "scope_type": "tenant", "scope_value": "*",
                   "published_model_id": p["id"], "targets": ["d-kimi"]} for p in (pub, gen))
    base = fx.snapshot("on", regions=[fx.ALLOW_EU_REGION, {**fx.US_REGION, "default_posture": "allow"}], offers=())
    return Snapshot(**{**base.__dict__, "published": (pub, gen), "rules": rules,
                       "destinations": {"d-kimi": {**dest, "inference_jurisdiction": "US", "entity_jurisdiction": "US",
                                                   "control_jurisdiction": "US"}},
                       "credentials": {"d-kimi": json.dumps({"api_key": "sk-x"})}})


@pytest.mark.parametrize("headers", [{"anthropic-version": "2023-06-01"}, {}])
@pytest.mark.parametrize("label_mode", [None, "requested"])
async def test_v1_models_no_filtra_el_nombre_ni_el_modelo_real_del_destino(headers, label_mode):
    p = RedirectPlugin(store=fx.store(_snapshot(label_mode)), ping_after=0.05)
    c = fx.ctx(route="/v1/models", model=None, headers=headers)
    assert await p.pre_request(c) is None
    view = p.models_filter(c, {"data": [{"id": "base"}]})
    ids = [x["id"] for x in view["data"]]
    assert ids == ["claude-sonnet-4-6"], "el id Claude que pidió el cliente, sin sufijos"
    plano = json.dumps(view)
    for filtrado in (SECRETO, REAL, "kimi", "openrouter", "Kimi"):
        assert filtrado not in plano, f"/v1/models filtró {filtrado!r}"


async def test_con_destination_el_nombre_sigue_apareciendo_porque_es_una_eleccion_explicita():
    p = RedirectPlugin(store=fx.store(_snapshot("destination")), ping_after=0.05)
    c = fx.ctx(route="/v1/models", model=None, headers={"anthropic-version": "2023-06-01"})
    await p.pre_request(c)
    assert SECRETO in json.dumps(p.models_filter(c, {"data": []}))


async def test_las_respuestas_no_traen_el_modelo_real_del_destino_ni_su_nombre():
    p = RedirectPlugin(store=fx.store(_snapshot(None)), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-6")
    assert await p.pre_request(c) is None
    upstream = {"id": "msg_1", "type": "message", "role": "assistant", "model": REAL,
                "content": [{"type": "text", "text": "hola"}],
                "usage": {"input_tokens": 3, "output_tokens": 1}}
    status, out, _ = p.map_response(c, 200, json.dumps(upstream).encode())
    assert status == 200
    body = out if isinstance(out, (bytes, str)) else json.dumps(out)
    texto = body.decode() if isinstance(body, bytes) else body
    assert json.loads(texto)["model"] == "claude-sonnet-4-6"
    for filtrado in (SECRETO, REAL, "kimi", "openrouter"):
        assert filtrado.lower() not in texto.lower(), f"la respuesta filtró {filtrado!r}"


def test_los_eventos_de_un_stream_tampoco_traen_el_modelo_real():
    frame = ('event: message_start\ndata: {"type":"message_start","message":{"model":"%s","id":"m"}}' % REAL).encode()
    out = stream.rewrite_frame(frame, "claude-sonnet-4-6", "claude")
    assert REAL.encode() not in out and b"claude-sonnet-4-6" in out
