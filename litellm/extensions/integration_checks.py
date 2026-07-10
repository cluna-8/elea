"""Integration checks del BasaGuardrail (spec 014 US1) — corren DENTRO de la imagen.

Ejercitan los 3 hooks del guardrail directamente (sin LLM real, que no está
disponible en este entorno): mask en pre_call + metadata poblada, unmask en
post_call no-streaming, y el reensamblado de bytes SSE con placeholder partido en el
streaming hook. Complementan los unit tests de la policy (backend) verificando el
CABLEADO del guardrail con los tipos reales del motor.

    docker compose exec -T litellm python /app/extensions/integration_checks.py
"""
import asyncio
import json
import sys
from types import SimpleNamespace

sys.path.insert(0, "/app")
from extensions.basa_guardrail import BasaGuardrail  # noqa: E402
from extensions.basa_audit_logger import _scrub  # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    print(f"[{'OK ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail and not condition else ''}")
    if not condition:
        FAILURES.append(name)


def _identity(redact=True):
    return SimpleNamespace(metadata={"basa": {"redact_enabled": redact, "tool_type": "claude-code"}})


async def _byte_stream(frames):
    for f in frames:
        yield f.encode("utf-8") if isinstance(f, str) else f


async def main():
    g = BasaGuardrail()

    # ── 1) pre_call enmascara el turno user y puebla litellm_metadata.pii_tokens ──
    body = {
        "model": "claude-3-5-sonnet",
        "messages": [{"role": "user", "content": "Soy el paciente Juan Pérez, mi mail juan@acme.com"}],
    }
    out = await g.async_pre_call_hook(_identity(), None, body, "anthropic_messages")
    masked_text = out["messages"][0]["content"]
    tokens = out.get("litellm_metadata", {}).get("pii_tokens", {})
    check("pre_call: upstream NO ve el nombre", "Juan Pérez" not in masked_text)
    check("pre_call: upstream NO ve el mail", "juan@acme.com" not in masked_text)
    check("pre_call: placeholders inyectados", "[PERSON_" in masked_text and "[EMAIL_ADDRESS_" in masked_text)
    check("pre_call: mapa reversible en litellm_metadata", len(tokens) == 2)
    check("pre_call: masked_entities registradas",
          bool(out["litellm_metadata"].get("basa_masked_entities")))

    # ── 2) toggle redact_enabled=False NO enmascara ──────────────────────────────
    body2 = {"messages": [{"role": "user", "content": "paciente Juan Pérez"}]}
    out2 = await g.async_pre_call_hook(_identity(redact=False), None, body2, "anthropic_messages")
    check("pre_call: redact_enabled=False no enmascara",
          "Juan Pérez" in out2["messages"][0]["content"]
          and "pii_tokens" not in out2.get("litellm_metadata", {}))

    # ── 3) post_call no-streaming des-enmascara (AnthropicMessagesResponse-like) ──
    data = {"litellm_metadata": {"pii_tokens": tokens}}
    ph_person = next(p for p in tokens if p.startswith("[PERSON_"))
    response = SimpleNamespace(content=[
        {"type": "text", "text": f"Hola {ph_person}, te ayudo."},
        {"type": "tool_use", "input": {"nombre": ph_person}},
    ])
    await g.async_post_call_success_hook(data, _identity(), response)
    check("post_call: texto des-enmascarado", "Juan Pérez" in response.content[0]["text"])
    check("post_call: tool_use.input des-enmascarado", response.content[1]["input"]["nombre"] == "Juan Pérez")

    # ── 4) streaming hook: placeholder partido entre frames SSE de bytes ─────────
    frames = [
        'event: content_block_start\ndata: {"type": "content_block_start", "index": 0}\n\n',
        'event: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, '
        f'"delta": {{"type": "text_delta", "text": "Hola {ph_person[:8]}"}}}}\n\n',
        'event: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, '
        f'"delta": {{"type": "text_delta", "text": "{ph_person[8:]}!"}}}}\n\n',
        'event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}\n\n',
    ]
    request_data = {"litellm_metadata": {"pii_tokens": tokens}}
    collected = b""
    async for chunk in g.async_post_call_streaming_iterator_hook(_identity(), _byte_stream(frames), request_data):
        collected += chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
    text = collected.decode("utf-8")
    emitted = "".join(
        json.loads(line[5:])["delta"]["text"]
        for line in text.split("\n")
        if line.startswith("data:") and '"content_block_delta"' in line
    )
    check("streaming: placeholder partido reensamblado y des-enmascarado", emitted == "Hola Juan Pérez!")
    check("streaming: 0 placeholders crudos en la salida", ph_person not in text)

    # ── 5) sin pii_tokens el streaming es passthrough transparente ───────────────
    passthrough = b""
    async for chunk in g.async_post_call_streaming_iterator_hook(_identity(), _byte_stream(["event: ping\ndata: {}\n\n"]), {}):
        passthrough += chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
    check("streaming: passthrough sin PII intacto", b"ping" in passthrough)

    # ── 6) audit scrub elimina el mapa reversible (C1) ───────────────────────────
    scrubbed = _scrub({"pii_tokens": tokens, "basa_masked_entities": [{"type": "PERSON", "count": 1}]})
    check("audit: scrub elimina pii_tokens", "pii_tokens" not in scrubbed)
    check("audit: scrub conserva metadata no sensible", "basa_masked_entities" in scrubbed)

    print(f"\n{'INTEGRACIÓN ROTA: ' + str(FAILURES) if FAILURES else 'Guardrail wiring OK end-to-end.'}")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    asyncio.run(main())
