"""Prueba de fidelidad (FR-031; T108): corpus sintético, solo destinos del tenant, postura de
quien la lanza, presupuesto propio y veredicto.

El envío al destino es inyectable (`send`): estos tests no tocan red."""
import re
from decimal import Decimal

import pytest

from sentinel.redirect import fidelity
from sentinel.redirect.residency import Posture
from sentinel.redirect.scopes import RequestScope

T1 = "t1"
SCOPE = RequestScope(tenant_id=T1, user_id="u1")
EU = Posture(mode="allowlist", jurisdictions=frozenset({"EU"}))
OFF = Posture(mode="off")

DEST = {"id": "d1", "level": "tenant", "tenant_id": T1, "name": "Qwen UE", "provider": "openai_compatible",
        "real_model": "qwen", "protocol_family": "openai_chat", "inference_jurisdiction": "DE",
        "entity_jurisdiction": "DE", "status": "active", "has_credential": True,
        "api_base": "http://destino/v1", "context_window": 32000, "max_output": 4096}
US_DEST = dict(DEST, id="d-us", name="Nativo US", inference_jurisdiction="US", entity_jurisdiction="US")
FOREIGN = dict(DEST, id="d-x", tenant_id="otro-tenant")
INST = dict(DEST, id="d-inst", level="installation", tenant_id=None)
DESTS = {d["id"]: d for d in (DEST, US_DEST, FOREIGN, INST)}


def price(model, prompt, completion):
    return Decimal(prompt + completion) / Decimal(1_000_000)


def ok_outcome(case, **kw):
    """Salida «buena» para cada capacidad."""
    cap = case["capability"]
    base = dict(status=200, text="respuesta", tool_calls=[], events=0, finished=True,
                error_class=None, prompt_tokens=10, completion_tokens=5)
    if cap == "tools":
        base.update(text="", tool_calls=[{"name": case["expect"]["tool"]}])
    if cap == "long_stream":
        base.update(text="x" * 400, events=40)
    if cap == "errors":
        base.update(status=400, text="", error_class="invalid_request", finished=True)
    if cap == "context":
        base.update(text=f"el dato es {case['needle']}")
    base.update(kw)
    return fidelity.Outcome(**base)


async def send_ok(case, body):
    return ok_outcome(case)


# --- corpus ------------------------------------------------------------------------

@pytest.mark.parametrize("tool", fidelity.TOOLS)
def test_corpus_covers_every_capability_and_is_synthetic(tool):
    corpus = fidelity.load_corpus(tool)
    assert {c["capability"] for c in corpus.cases} == set(fidelity.CAPABILITIES)
    assert corpus.version and corpus.synthetic is True
    blob = repr(corpus.cases)
    assert not re.search(r"[\w.]+@[\w.]+\.\w+", blob)                    # ni correos
    assert not re.search(r"\b\d{3}[ -]?\d{3}[ -]?\d{3,4}\b", blob)       # ni teléfonos/DNI de aspecto real


def test_corpus_is_in_native_shape_of_the_face():
    assert fidelity.face_for_tool("claude_code") == "claude"
    assert fidelity.face_for_tool("claude_desktop") == "claude"
    assert fidelity.face_for_tool("codex") == "codex"
    assert fidelity.face_for_tool("openai_generic") == "openai_generic"
    with pytest.raises(fidelity.FidelityRefused) as exc:
        fidelity.face_for_tool("vim")
    assert exc.value.code == "unknown_tool"


# --- sin datos reales ---------------------------------------------------------------

async def test_only_corpus_bodies_are_sent():
    sent = []

    async def send(case, body):
        sent.append((case, body))
        return ok_outcome(case)

    corpus = fidelity.load_corpus("openai_generic")
    await fidelity.run(DEST, "openai_generic", "openai_generic", send=send, price=price,
                       budget=fidelity.Budget(Decimal("1")), tenant_id=T1)
    assert len(sent) == len(corpus.cases)
    for case, body in sent:
        # el cuerpo sale del caso grabado, con el modelo y (en contexto) el relleno sintético
        assert body["model"] == "qwen" or body.get("model")
        assert fidelity.ALLOWED_BODY_KEYS >= set(body) - {"model"}


async def test_run_takes_no_user_content():
    import inspect
    params = set(inspect.signature(fidelity.run).parameters)
    assert not params & {"messages", "prompt", "content", "body"}


# --- solo destinos del tenant + postura -----------------------------------------------

def test_destination_must_belong_to_tenant_catalog():
    with pytest.raises(fidelity.FidelityRefused) as exc:
        fidelity.ensure_allowed("d-x", DESTS, offers=[], scope=SCOPE, posture=OFF)
    assert exc.value.code == "not_found"
    with pytest.raises(fidelity.FidelityRefused) as exc:
        fidelity.ensure_allowed("no-existe", DESTS, offers=[], scope=SCOPE, posture=OFF)
    assert exc.value.code == "not_found"


def test_installation_destination_needs_offer():
    with pytest.raises(fidelity.FidelityRefused) as exc:
        fidelity.ensure_allowed("d-inst", DESTS, offers=[], scope=SCOPE, posture=OFF)
    assert exc.value.code == "not_offered"
    offers = [{"destination_id": "d-inst", "tenant_id": "*"}]
    assert fidelity.ensure_allowed("d-inst", DESTS, offers=offers, scope=SCOPE, posture=OFF)["id"] == "d-inst"


def test_respects_residency_posture_of_launcher():
    assert fidelity.ensure_allowed("d1", DESTS, offers=[], scope=SCOPE, posture=EU)["id"] == "d1"
    with pytest.raises(fidelity.FidelityRefused) as exc:
        fidelity.ensure_allowed("d-us", DESTS, offers=[], scope=SCOPE, posture=EU)
    assert exc.value.code == "residency"


def test_inactive_destination_refused():
    dests = {"d1": dict(DEST, status="revoked")}
    with pytest.raises(fidelity.FidelityRefused) as exc:
        fidelity.ensure_allowed("d1", dests, offers=[], scope=SCOPE, posture=OFF)
    assert exc.value.code == "revoked"


# --- informe y veredicto --------------------------------------------------------------

async def test_report_per_capability_and_verdict_apto():
    rep = await fidelity.run(DEST, "openai_generic", "openai_generic", send=send_ok, price=price,
                             budget=fidelity.Budget(Decimal("1")), tenant_id=T1, tool_version="1.2.3",
                             run_by="u1")
    assert rep["verdict"] == "apto" and rep["complete"] is True
    assert rep["destination_id"] == "d1" and rep["face"] == "openai_generic"
    assert rep["tool"] == "openai_generic" and rep["tool_version"] == "1.2.3"
    assert rep["corpus_version"] and rep["tenant_id"] == T1 and rep["run_by"] == "u1"
    assert {r["capability"] for r in rep["results"]} == set(fidelity.CAPABILITIES)
    assert all(r["passed"] and r["detail_code"] == "ok" for r in rep["results"])
    assert rep["pass_rate"] == 1.0
    assert Decimal(str(rep["cost"])) > 0


async def test_failed_capability_is_reported_and_not_apto():
    async def send(case, body):
        if case["capability"] == "tools":
            return ok_outcome(case, tool_calls=[], text="no uso herramientas")
        return ok_outcome(case)

    rep = await fidelity.run(DEST, "openai_generic", "openai_generic", send=send, price=price,
                             budget=fidelity.Budget(Decimal("1")), tenant_id=T1)
    failed = [r for r in rep["results"] if not r["passed"]]
    assert {r["capability"] for r in failed} == {"tools"}
    assert failed[0]["detail_code"] == "no_tool_call"
    assert rep["verdict"] == "no_apto"        # una prueba por capacidad: 4/5 = 80 % < 95 %


async def test_silent_failure_blocks_verdict_even_above_threshold():
    """200 con respuesta vacía = fallo silencioso: peor que un error visible (FR-031)."""
    # corpus con muchos casos: el 95 % se supera igual, pero el silencioso veta
    big = fidelity.Corpus(version="t", synthetic=True, tool="openai_generic",
                          cases=[dict(fidelity.load_corpus("openai_generic").cases[0], name=f"c{i}") for i in range(30)])

    async def send_one_silent(case, body):
        return ok_outcome(case, text="") if case["name"] == "c0" else ok_outcome(case)

    rep = await fidelity.run(DEST, "openai_generic", "openai_generic", send=send_one_silent, price=price,
                             budget=fidelity.Budget(Decimal("1")), tenant_id=T1, corpus=big)
    assert rep["pass_rate"] >= 0.95
    assert any(r["silent"] for r in rep["results"])
    assert rep["verdict"] == "no_apto"


async def test_visible_error_is_not_silent():
    async def send(case, body):
        return ok_outcome(case, status=502, text="", error_class="upstream") if case["capability"] == "conversation" \
            else ok_outcome(case)

    rep = await fidelity.run(DEST, "openai_generic", "openai_generic", send=send, price=price,
                             budget=fidelity.Budget(Decimal("1")), tenant_id=T1)
    conv = next(r for r in rep["results"] if r["capability"] == "conversation")
    assert not conv["passed"] and conv["silent"] is False and conv["detail_code"] == "http_502"


async def test_errors_capability_passes_only_with_clean_classified_error():
    async def send(case, body):
        if case["capability"] == "errors":
            return ok_outcome(case, status=200, text="", error_class=None)   # debió ser un error
        return ok_outcome(case)

    rep = await fidelity.run(DEST, "openai_generic", "openai_generic", send=send, price=price,
                             budget=fidelity.Budget(Decimal("1")), tenant_id=T1)
    err = next(r for r in rep["results"] if r["capability"] == "errors")
    assert not err["passed"] and err["silent"] is True


async def test_sender_exception_is_a_failed_case_not_a_crash():
    async def send(case, body):
        if case["capability"] == "long_stream":
            raise TimeoutError("sin respuesta")
        return ok_outcome(case)

    rep = await fidelity.run(DEST, "openai_generic", "openai_generic", send=send, price=price,
                             budget=fidelity.Budget(Decimal("1")), tenant_id=T1)
    r = next(r for r in rep["results"] if r["capability"] == "long_stream")
    assert not r["passed"] and r["detail_code"] == "send_failed"


async def test_context_case_uses_needle_and_scales_with_window():
    seen = {}

    async def send(case, body):
        if case["capability"] == "context":
            seen["body"], seen["case"] = body, case
        return ok_outcome(case)

    await fidelity.run(DEST, "openai_generic", "openai_generic", send=send, price=price,
                       budget=fidelity.Budget(Decimal("1")), tenant_id=T1)
    text = repr(seen["body"])
    assert seen["case"]["needle"] in text
    assert len(text) < DEST["context_window"] * 4          # nunca excede la ventana del destino


# --- presupuesto propio ---------------------------------------------------------------

async def test_budget_exhaustion_stops_and_marks_incomplete():
    calls = []

    async def send(case, body):
        calls.append(case["name"])
        return ok_outcome(case, prompt_tokens=500_000, completion_tokens=500_000)    # 1 USD por caso

    rep = await fidelity.run(DEST, "openai_generic", "openai_generic", send=send, price=price,
                             budget=fidelity.Budget(Decimal("1.5")), tenant_id=T1)
    assert len(calls) == 2                                  # el segundo agota; no hay tercero
    assert rep["complete"] is False and rep["verdict"] == "incompleto"
    skipped = [r for r in rep["results"] if r["detail_code"] == "budget_exhausted"]
    assert len(skipped) == len(rep["results"]) - 2 and not any(r["passed"] for r in skipped)
    assert Decimal(str(rep["cost"])) == Decimal("2")


def test_budget_is_its_own_object():
    b = fidelity.Budget(Decimal("0.10"))
    assert b.remaining == Decimal("0.10")
    b.charge(Decimal("0.04"))
    assert b.remaining == Decimal("0.06") and not b.exhausted
    b.charge(Decimal("0.06"))
    assert b.exhausted


def test_budget_default_from_environment(monkeypatch):
    monkeypatch.setenv("REDIRECT_FIDELITY_BUDGET_USD", "0.25")
    assert fidelity.Budget.from_env().limit == Decimal("0.25")
    monkeypatch.setenv("REDIRECT_FIDELITY_BUDGET_USD", "basura")
    assert fidelity.Budget.from_env().limit == fidelity.DEFAULT_BUDGET_USD


# --- lectura de respuestas reales (las tres formas de la API) -----------------------------

def _read(events=(), whole=None):
    r = fidelity._Reader()
    for e in events:
        r.event(e)
    if whole is not None:
        r.whole(whole)
    return r.out


def test_reader_messages_stream_with_tool_and_usage():
    out = _read([
        {"type": "message_start", "message": {"usage": {"input_tokens": 12}}},
        {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "read_file"}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hola"}},
        {"type": "message_delta", "usage": {"output_tokens": 7}},
        {"type": "message_stop"}])
    assert out.text == "hola" and out.tool_calls == [{"name": "read_file"}] and out.finished
    assert (out.prompt_tokens, out.completion_tokens, out.events) == (12, 7, 5)


def test_reader_chat_stream_and_whole():
    out = _read([{"choices": [{"delta": {"content": "ho"}}]},
                 {"choices": [{"delta": {"content": "la", "tool_calls": [{"function": {"name": "read_file"}}]},
                               "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}])
    assert out.text == "hola" and out.finished and out.tool_calls == [{"name": "read_file"}]
    whole = _read(whole={"choices": [{"message": {"content": "ok", "tool_calls": [{"function": {"name": "f"}}]}}],
                         "usage": {"prompt_tokens": 4, "completion_tokens": 1}})
    assert whole.text == "ok" and whole.tool_calls == [{"name": "f"}] and whole.completion_tokens == 1


def test_reader_responses_stream():
    out = _read([{"type": "response.output_text.delta", "delta": "ho"},
                 {"type": "response.output_item.added", "item": {"type": "function_call", "name": "read_file"}},
                 {"type": "response.output_item.done", "item": {"type": "function_call", "name": "read_file"}},
                 {"type": "response.completed", "response": {"usage": {"input_tokens": 5, "output_tokens": 2}}}])
    assert out.text == "ho" and out.tool_calls == [{"name": "read_file"}] and out.finished
    assert (out.prompt_tokens, out.completion_tokens) == (5, 2)


def test_missing_usage_is_estimated_not_free():
    out = fidelity.Outcome(text="x" * 300)
    fidelity._estimate(out, {"messages": [{"role": "user", "content": "hola"}]})
    assert out.prompt_tokens > 0 and out.completion_tokens == 100


def test_error_class_for_status():
    assert fidelity.error_class_for(200) is None
    assert fidelity.error_class_for(400) == "invalid_request"
    assert fidelity.error_class_for(429) == "rate_limit"
    assert fidelity.error_class_for(503) == "upstream"


# --- regresiones entre versiones de la herramienta (US5, escenario 4) ---------------------

def test_regressions_only_what_used_to_pass():
    r = lambda name, passed, code="ok": {"capability": name, "name": name, "passed": passed, "detail_code": code}
    before = [r("a", True), r("b", False, "http_500"), r("c", True), r("d", True)]
    after = [r("a", True), r("b", False, "http_500"), r("c", False, "no_tool_call"),
             r("d", False, "budget_exhausted")]
    assert fidelity.regressions(before, after) == [
        {"capability": "c", "name": "c", "detail_code": "no_tool_call"}]
    assert fidelity.regressions([], after) == []
