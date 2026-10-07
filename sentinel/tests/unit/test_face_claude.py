"""Cara Claude: /v1/models, errores y normalizador (contracts/cara-claude.md; D5/D6; T081/T083)."""
import json

import pytest

from sentinel.redirect.faces import claude as face

ROWS = [
    {"public_id": "claude-sonnet-4-5", "family_tier": "sonnet", "is_family_default": True,
     "label_mode": "destination", "destination_name": "Nube Propia", "context_window": 128000,
     "created_at": "2026-09-25T00:00:00Z"},
    {"public_id": "claude-opus-4-1", "family_tier": "opus", "is_family_default": True,
     "label_mode": "custom", "label": "Opus corporativo", "destination_name": "Secreto",
     "context_window": 1_000_000},
    {"public_id": "claude-haiku-4-5", "family_tier": "haiku", "label_mode": "requested",
     "destination_name": "Otro", "context_window": 64000},
]


def test_models_view_shape():
    v = face.models_view(ROWS, now_iso="2026-09-25T00:00:00Z")
    ids = [m["id"] for m in v["data"]]
    assert ids == ["claude-haiku-4-5", "claude-opus-4-1", "claude-sonnet-4-5"]
    assert v["has_more"] is False and v["first_id"] == ids[0] and v["last_id"] == ids[-1]
    sonnet = v["data"][2]
    assert sonnet == {
        "type": "model", "id": "claude-sonnet-4-5", "display_name": "Sonnet · servido por Nube Propia",
        "description": "Destino: Nube Propia. Ventana: 128000.", "created_at": "2026-09-25T00:00:00Z",
        "anthropic_family_tier": "sonnet", "is_family_default": True, "max_input_tokens": 128000,
        "supports_1m": False}


def test_label_modes_hide_destination():
    v = {m["id"]: m for m in face.models_view(ROWS, now_iso="2026-09-25T00:00:00Z")["data"]}
    assert v["claude-opus-4-1"]["display_name"] == "Opus corporativo"
    assert "Secreto" not in v["claude-opus-4-1"]["description"]
    assert v["claude-opus-4-1"]["supports_1m"] is True
    assert v["claude-haiku-4-5"]["display_name"] == "claude-haiku-4-5"
    assert "Otro" not in v["claude-haiku-4-5"]["description"]


def test_models_pagination():
    v = face.models_view(ROWS, limit=1, now_iso="x")
    assert [m["id"] for m in v["data"]] == ["claude-haiku-4-5"] and v["has_more"] is True
    v2 = face.models_view(ROWS, limit=1, after_id="claude-haiku-4-5", now_iso="x")
    assert [m["id"] for m in v2["data"]] == ["claude-opus-4-1"]
    v3 = face.models_view(ROWS, before_id="claude-sonnet-4-5", now_iso="x")
    assert [m["id"] for m in v3["data"]] == ["claude-haiku-4-5", "claude-opus-4-1"]
    empty = face.models_view([], now_iso="x")
    assert empty == {"data": [], "has_more": False, "first_id": None, "last_id": None}


# --- errores -----------------------------------------------------------------------

@pytest.mark.parametrize("kind,status,etype", [
    ("not_available", 404, "not_found_error"),
    ("region", 403, "permission_error"),
    ("capability", 400, "invalid_request_error"),
    ("overloaded", 529, "overloaded_error"),
    ("rate_limit", 429, "rate_limit_error"),
    ("policy_unavailable", 503, "api_error"),
    ("auth", 401, "authentication_error"),
])
def test_error_table(kind, status, etype):
    st, headers, body = face.error_response(kind, capability="documents_pdf")
    assert st == status and body["type"] == "error" and body["error"]["type"] == etype
    assert "sentinel" not in body["error"]["message"].lower()
    if kind == "capability":
        assert body["error"]["message"].startswith("capability_rejected: documents_pdf")
    if kind in ("overloaded", "policy_unavailable"):
        assert headers["x-should-retry"] == "true"
    if kind == "rate_limit":
        assert headers["retry-after"] == "10"


def test_region_message_does_not_name_destination():
    _, _, body = face.error_response("region")
    assert body["error"]["message"] == "Modelo no disponible para tu región."
    _, _, body = face.error_response("not_available")
    assert body["error"]["message"] == "Modelo no disponible para tu organización."


@pytest.mark.parametrize("given,want", [(None, "10"), (0, "1"), (3.2, "4"), (500, "60"), ("7", "7"), ("x", "10")])
def test_retry_after_clamped(given, want):
    _, headers, _ = face.error_response("rate_limit", retry_after=given)
    assert headers["retry-after"] == want


@pytest.mark.parametrize("upstream,kind", [(429, "rate_limit"), (500, "overloaded"), (502, "overloaded"),
                                           (503, "overloaded"), (529, "overloaded"), (400, "invalid_request"),
                                           (404, "not_available"), (401, "upstream_auth"), (403, "upstream_auth")])
def test_map_upstream(upstream, kind):
    assert face.map_upstream_status(upstream) == kind


def test_upstream_auth_is_neutral_api_error():
    st, _, body = face.error_response("upstream_auth")
    assert st == 502 and body["error"]["type"] == "api_error"


def test_error_sse_event():
    ev = face.error_event("overloaded")
    assert ev.startswith(b"event: error\ndata: ") and ev.endswith(b"\n\n")
    assert b"overloaded_error" in ev


# --- normalizador ----------------------------------------------------------------------

PROFILE_MIN = {"thinking": False, "cache_control": False, "mid_system_messages": False,
               "documents_pdf": False, "images": True}
PROFILE_FULL = {"thinking": True, "cache_control": True, "mid_system_messages": True,
                "documents_pdf": True, "images": True}


def body(**kw):
    b = {"model": "claude-sonnet-4-5", "max_tokens": 64000,
         "system": [{"type": "text", "text": "S0", "cache_control": {"type": "ephemeral"}}],
         "messages": [
             {"role": "user", "content": [{"type": "text", "text": "hola", "cache_control": {"type": "ephemeral"}}]},
             {"role": "system", "content": "S1 intermedio"},
             {"role": "assistant", "content": "ok"},
         ],
         "tools": [{"name": "t", "input_schema": {"type": "object"}, "cache_control": {"type": "ephemeral"}}],
         "thinking": {"type": "adaptive"}, "output_config": {"effort": "high"},
         "context_management": {"edits": []}, "api_key": "cliente", "base_url": "https://evil"}
    b.update(kw)
    return b


def test_normalize_minimal_profile():
    out, removed = face.normalize_for_translated(body(), PROFILE_MIN, max_output=8192)
    assert "thinking" not in out and "output_config" not in out and "reasoning_effort" not in out
    assert "context_management" not in out
    assert "api_key" not in out and "base_url" not in out
    assert out["max_tokens"] == 8192
    assert "cache_control" not in repr(out)
    assert [m["role"] for m in out["messages"]] == ["user", "assistant"]
    assert out["system"][-1]["text"] == "S1 intermedio" and out["system"][0]["text"] == "S0"
    assert {"thinking", "output_config", "context_management", "cache_control", "mid_system_messages",
            "max_tokens", "client_credentials"} <= set(removed)


def test_normalize_full_profile_translates_effort():
    out, _ = face.normalize_for_translated(body(), PROFILE_FULL, max_output=100000)
    assert "thinking" not in out and out["reasoning_effort"] == "high"
    assert out["max_tokens"] == 64000
    assert "cache_control" in repr(out)
    assert any(m["role"] == "system" for m in out["messages"])


@pytest.mark.parametrize("effort,want", [("low", "low"), ("medium", "medium"), ("high", "high"),
                                         ("max", "high"), ("xhigh", "high")])
def test_effort_mapping(effort, want):
    out, _ = face.normalize_for_translated(body(output_config={"effort": effort}), PROFILE_FULL, max_output=10)
    assert out["reasoning_effort"] == want


def test_adaptive_without_effort_defaults_medium():
    b = body()
    b.pop("output_config")
    out, _ = face.normalize_for_translated(b, PROFILE_FULL, max_output=10)
    assert out["reasoning_effort"] == "medium"


def test_enabled_thinking_kept_only_if_supported():
    b = body(thinking={"type": "enabled", "budget_tokens": 2048})
    b.pop("output_config")
    out, _ = face.normalize_for_translated(b, PROFILE_FULL, max_output=10)
    assert out["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    out2, _ = face.normalize_for_translated(b, PROFILE_MIN, max_output=10)
    assert "thinking" not in out2


def test_system_string_merge():
    b = body(system="S0")
    out, _ = face.normalize_for_translated(b, PROFILE_MIN, max_output=10)
    assert [blk["text"] for blk in out["system"]] == ["S0", "S1 intermedio"]
    b2 = body()
    b2.pop("system")
    out2, _ = face.normalize_for_translated(b2, PROFILE_MIN, max_output=10)
    assert [blk["text"] for blk in out2["system"]] == ["S1 intermedio"]


def test_pdf_rejected_when_unsupported():
    b = body(messages=[{"role": "user", "content": [{"type": "document", "source": {"type": "base64"}}]}])
    with pytest.raises(face.CapabilityRejected) as e:
        face.normalize_for_translated(b, PROFILE_MIN, max_output=10)
    assert e.value.capability == "documents_pdf"
    st, _, err = face.error_response("capability", capability=e.value.capability)
    assert st == 400 and err["error"]["message"].startswith("capability_rejected: documents_pdf")


def test_images_rejected_when_unsupported():
    b = body(messages=[{"role": "user", "content": [{"type": "image", "source": {}}]}])
    with pytest.raises(face.CapabilityRejected):
        face.normalize_for_translated(b, {**PROFILE_MIN, "images": False}, max_output=10)


def test_input_not_mutated():
    b = body()
    snapshot = repr(b)
    face.normalize_for_translated(b, PROFILE_MIN, max_output=10)
    assert repr(b) == snapshot


def test_ventana_sin_declarar_no_se_publica_como_cero():
    """Un destino sin ventana no anuncia `max_input_tokens: 0` (el cliente compactaría ya):
    se omite y el cliente usa su default para el id (verificación en vivo, 27-sep)."""
    row = {**ROWS[0], "context_window": None}
    m = face.models_view([row], now_iso="2026-09-25T00:00:00Z")["data"][0]
    assert "max_input_tokens" not in m and m["supports_1m"] is False
    assert m["description"] == "Destino: Nube Propia. Ventana: sin declarar."


# ── imágenes y documentos en la historia (demo del 28-sep, 069 FR-008e) ─────────────

NO_IMG = {**PROFILE_MIN, "images": False}
IMG = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBOR"}}


def test_imagen_en_turno_anterior_se_omite_y_el_chat_sigue():
    """Tras adjuntar una imagen, «hola» y todo lo siguiente daban capability_rejected: la
    historia viaja entera en cada pedido. La imagen vieja se reemplaza por una nota."""
    b = body(messages=[
        {"role": "user", "content": [IMG, {"type": "text", "text": "haceme ocr"}]},
        {"role": "assistant", "content": "No puedo ver imágenes."},
        {"role": "user", "content": "hola"}])
    out, removed = face.normalize_for_translated(b, NO_IMG, max_output=10)
    viejo = out["messages"][0]["content"]
    assert all(blk.get("type") == "text" for blk in viejo)
    assert any(blk["text"] == "[imagen omitida: este modelo no acepta imágenes]" for blk in viejo)
    assert out["messages"][2]["content"] == "hola"
    assert "images_in_history:1" in removed


def test_historia_se_audita_por_tipo_y_con_conteo():
    """El ajuste dice qué tipo y cuántos bloques de turnos anteriores se reemplazaron (solo
    cantidades, nunca contenido); un PDF de la historia no se cuenta como imagen."""
    doc = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBER"}}
    b = body(messages=[
        {"role": "user", "content": [IMG, IMG, doc, {"type": "text", "text": "mirá"}]},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": [IMG]},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "hola"}])
    out, removed = face.normalize_for_translated(b, {**NO_IMG, "documents_pdf": False}, max_output=10)
    assert [r for r in removed if "_in_history" in r] == ["images_in_history:3", "documents_in_history:1"]
    textos = [blk["text"] for m in out["messages"][:3] if isinstance(m["content"], list) for blk in m["content"]]
    assert "[documento omitido: este modelo no acepta documentos]" in textos
    assert '"type": "image"' not in json.dumps(out) and '"type": "document"' not in json.dumps(out)


def test_historia_solo_audita_lo_que_el_destino_no_acepta():
    doc = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBER"}}
    b = body(messages=[{"role": "user", "content": [IMG, doc]},
                       {"role": "assistant", "content": "ok"},
                       {"role": "user", "content": "hola"}])
    out, removed = face.normalize_for_translated(b, {**PROFILE_MIN, "images": True, "documents_pdf": False},
                                                 max_output=10)
    assert "documents_in_history:1" in removed and not any(r.startswith("images_in_history") for r in removed)
    assert out["messages"][0]["content"][0] == IMG


def test_imagen_en_el_turno_actual_se_rechaza():
    b = body(messages=[{"role": "user", "content": "hola"},
                       {"role": "assistant", "content": "¡Hola!"},
                       {"role": "user", "content": [IMG, {"type": "text", "text": "haceme ocr"}]}])
    with pytest.raises(face.CapabilityRejected) as e:
        face.normalize_for_translated(b, NO_IMG, max_output=10)
    assert e.value.capability == "images"


def test_documento_en_tool_result_anterior_se_omite():
    doc = {"type": "document", "source": {"type": "base64"}}
    b = body(messages=[
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [doc]}]},
        {"role": "assistant", "content": "listo"},
        {"role": "user", "content": "seguí"}])
    out, _ = face.normalize_for_translated(b, PROFILE_MIN, max_output=10)
    nested = out["messages"][0]["content"][0]["content"]
    assert nested[0]["type"] == "text" and "documento omitido" in nested[0]["text"]


def test_rechazo_de_imagen_trae_mensaje_en_castellano_y_el_marcador():
    st, headers, err = face.error_response("capability", capability="images")
    msg = err["error"]["message"]
    assert st == 400 and msg.startswith("capability_rejected: images")
    assert "no acepta imágenes" in msg and "x-should-retry" not in {k.lower() for k in headers}


# ── capturas del propio agente en el turno actual (F5 del 29-sep) ────────────────────
# Una imagen suelta en el turno actual la adjuntó la persona → se rechaza. Una imagen dentro de
# un `tool_result` la devolvió una herramienta que pidió el modelo (la captura con la que Cowork
# revisa su resultado, o leer un PNG) → se reemplaza por una nota y la tarea sigue.

def _tool_result(*blocks, tid="t1"):
    return {"type": "tool_result", "tool_use_id": tid, "content": list(blocks)}


def _agente(ultimo):
    return body(messages=[
        {"role": "user", "content": "creame un pdf sobre el café"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "screenshot", "input": {}}]},
        {"role": "user", "content": ultimo}])


def test_captura_en_tool_result_del_turno_actual_se_omite_y_la_tarea_sigue():
    b = _agente([_tool_result({"type": "text", "text": "pdf creado"}, IMG)])
    out, removed = face.normalize_for_translated(b, NO_IMG, max_output=10)
    nested = out["messages"][2]["content"][0]["content"]
    assert nested[0] == {"type": "text", "text": "pdf creado"}
    assert nested[1]["type"] == "text" and "imagen omitida" in nested[1]["text"]
    assert "images_in_tool_result" in removed and "images_in_history" not in removed


def test_captura_unica_del_tool_result_deja_la_nota_nunca_contenido_vacio():
    b = _agente([_tool_result(IMG)])
    out, _ = face.normalize_for_translated(b, NO_IMG, max_output=10)
    nested = out["messages"][2]["content"][0]["content"]
    assert nested and len(nested) == 1
    assert nested[0]["type"] == "text" and nested[0]["text"].strip()


def test_la_nota_de_la_captura_le_dice_al_agente_que_no_insista():
    b = _agente([_tool_result(IMG)])
    out, _ = face.normalize_for_translated(b, NO_IMG, max_output=10)
    nota = out["messages"][2]["content"][0]["content"][0]["text"]
    assert "no acepta imágenes" in nota and "no vuelvas a pedir" in nota.lower()


def test_imagen_adjuntada_junto_a_un_tool_result_se_rechaza():
    """La persona interviene a mitad de la tarea y adjunta una imagen: esa imagen es suya."""
    b = _agente([_tool_result({"type": "text", "text": "ok"}), IMG,
                 {"type": "text", "text": "mirá esto"}])
    with pytest.raises(face.CapabilityRejected) as e:
        face.normalize_for_translated(b, NO_IMG, max_output=10)
    assert e.value.capability == "images"


def test_documento_en_tool_result_del_turno_actual_se_omite():
    doc = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBE"}}
    b = _agente([_tool_result(doc)])
    out, removed = face.normalize_for_translated(b, PROFILE_MIN, max_output=10)
    nested = out["messages"][2]["content"][0]["content"]
    assert nested[0]["type"] == "text" and "documento omitido" in nested[0]["text"]
    assert "documents_in_tool_result" in removed


def test_documento_adjuntado_en_el_turno_actual_se_rechaza():
    doc = {"type": "document", "source": {"type": "base64"}}
    b = body(messages=[{"role": "user", "content": [doc, {"type": "text", "text": "resumilo"}]}])
    with pytest.raises(face.CapabilityRejected) as e:
        face.normalize_for_translated(b, PROFILE_MIN, max_output=10)
    assert e.value.capability == "documents_pdf"


def test_destino_con_vision_deja_pasar_la_captura_intacta():
    b = _agente([_tool_result(IMG)])
    out, removed = face.normalize_for_translated(b, PROFILE_MIN, max_output=10)   # images: True
    assert out["messages"][2]["content"][0]["content"][0] == IMG
    assert "images_in_tool_result" not in removed


# ── la capacidad del destino se respeta con cualquier ajuste de imágenes (S14, R43) ──────────────
# `MASKING_IMAGES=pass` deja salir la imagen del enmascarado, pero NO se la manda a un destino que no declara `images`: la cara
# resuelve por capacidad, antes del motor, y no lee el ajuste.

@pytest.mark.parametrize("ajuste", ["pass", "filter"])
def test_la_capacidad_del_destino_se_respeta_con_cualquier_ajuste_de_imagenes(monkeypatch, ajuste):
    monkeypatch.setenv("MASKING_IMAGES", ajuste)
    adjunta = body(messages=[{"role": "user", "content": [IMG, {"type": "text", "text": "mirá"}]}])
    with pytest.raises(face.CapabilityRejected) as e:
        face.normalize_for_translated(adjunta, NO_IMG, max_output=10)
    assert e.value.capability == "images"
    st, _, err = face.error_response("capability", capability="images")
    assert st == 400 and err["error"]["message"].startswith("capability_rejected: images")

    captura = _agente([_tool_result(IMG)])
    out, removed = face.normalize_for_translated(captura, NO_IMG, max_output=10)
    nota = out["messages"][2]["content"][0]["content"][0]["text"]
    assert "no acepta imágenes" in nota and "images_in_tool_result" in removed


@pytest.mark.parametrize("ajuste", ["pass", "filter"])
def test_con_un_destino_que_declara_imagenes_la_cara_no_las_toca(monkeypatch, ajuste):
    monkeypatch.setenv("MASKING_IMAGES", ajuste)
    captura = _agente([_tool_result(IMG)])
    out, removed = face.normalize_for_translated(captura, PROFILE_MIN | {"images": True}, max_output=10)
    assert out["messages"][2]["content"][0]["content"] == [IMG]
    assert "images_in_tool_result" not in removed
