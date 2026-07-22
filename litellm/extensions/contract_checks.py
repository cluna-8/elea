"""Contract checks de la spec 014 (US5) — corren DENTRO de la imagen pinneada.

Verifican las firmas de los 4 puntos de extensión contra la versión REAL del motor
(no contra la doc ni contra un pip local que puede divergir del build de la imagen):

    docker compose exec -T litellm python /app/extensions/contract_checks.py

Salida no-cero = el contrato se rompió (p.ej. tras un bump del pin). Proceso de bump:
cambiar el digest en docker-compose.yml → correr esto + la suite → commitear.
"""
import inspect
import sys

FAILURES = []


def check(name, condition, detail=""):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {name}{(' — ' + detail) if detail and not condition else ''}")
    if not condition:
        FAILURES.append(name)


def main():
    import litellm
    from importlib.metadata import version
    print(f"litellm image version: {version('litellm')}\n")

    # ── Firmas de CustomGuardrail/CustomLogger (base) ──────────────────────────
    from litellm.integrations.custom_guardrail import CustomGuardrail
    from litellm.integrations.custom_logger import CustomLogger

    pre = inspect.signature(CustomLogger.async_pre_call_hook)
    check("async_pre_call_hook(user_api_key_dict, cache, data, call_type)",
          [p for p in pre.parameters] == ["self", "user_api_key_dict", "cache", "data", "call_type"],
          str(pre))

    post = inspect.signature(CustomLogger.async_post_call_success_hook)
    check("async_post_call_success_hook(data, user_api_key_dict, response)",
          [p for p in post.parameters] == ["self", "data", "user_api_key_dict", "response"],
          str(post))

    stream = inspect.signature(CustomLogger.async_post_call_streaming_iterator_hook)
    check("async_post_call_streaming_iterator_hook(user_api_key_dict, response, request_data)",
          [p for p in stream.parameters] == ["self", "user_api_key_dict", "response", "request_data"],
          str(stream))

    log = inspect.signature(CustomLogger.async_log_success_event)
    check("async_log_success_event(kwargs, response_obj, start_time, end_time)",
          [p for p in log.parameters] == ["self", "kwargs", "response_obj", "start_time", "end_time"],
          str(log))

    # ── UserAPIKeyAuth: los campos que la identidad Basa usa ──────────────────
    from litellm.proxy._types import UserAPIKeyAuth
    fields = set(UserAPIKeyAuth.model_fields)
    for field in ("user_id", "team_id", "metadata", "models", "rpm_limit", "tpm_limit", "key_alias"):
        check(f"UserAPIKeyAuth.{field} existe", field in fields)

    # ── call_type de la ruta titular /v1/messages ─────────────────────────────
    from litellm.types.utils import CallTypes
    check("CallTypes.anthropic_messages existe",
          getattr(CallTypes, "anthropic_messages", None) is not None)

    # ── Nuestras extensiones cargan y respetan los gotchas de la research ─────
    sys.path.insert(0, "/app")
    from extensions.basa_guardrail import BasaGuardrail
    from extensions import custom_auth
    from extensions.basa_audit_logger import basa_audit_logger_instance

    check("BasaGuardrail hereda CustomGuardrail", issubclass(BasaGuardrail, CustomGuardrail))
    check("BasaGuardrail NO define apply_guardrail (gotcha unified_guardrail)",
          "apply_guardrail" not in BasaGuardrail.__dict__)
    check("streaming hook overrideado en la clase HOJA (gotcha de detección)",
          "async_post_call_streaming_iterator_hook" in BasaGuardrail.__dict__)
    check("pre_call hook overrideado", "async_pre_call_hook" in BasaGuardrail.__dict__)
    check("post_call_success hook overrideado",
          "async_post_call_success_hook" in BasaGuardrail.__dict__)

    auth_sig = inspect.signature(custom_auth.user_api_key_auth)
    check("custom_auth.user_api_key_auth(request, api_key) async",
          [p for p in auth_sig.parameters] == ["request", "api_key"]
          and inspect.iscoroutinefunction(custom_auth.user_api_key_auth))

    check("BasaAuditLogger es CustomLogger",
          isinstance(basa_audit_logger_instance, CustomLogger))

    # ── Round-trip básico de la policy dentro del container ───────────────────
    from extensions import basa_guardian_policy as bp
    ph = {"[PERSON_0_ab12]": "Juan Pérez"}
    blocks, carry, field, _, _ = bp.rewrite_sse_block(
        'event: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, '
        '"delta": {"type": "text_delta", "text": "Hola [PERSON_0_ab12]!"}}',
        "", None, ph)
    check("policy round-trip dentro del container", "Juan Pérez" in blocks[0])

    # ── spec 016: detección NLP real, región eu, enforcement MASK/BLOCK ────────
    check("resolve_entity_action default MASK",
          bp.resolve_entity_action("PASSPORT", {}) == "MASK")
    check("resolve_entity_action respeta BLOCK",
          bp.resolve_entity_action("CREDIT_CARD", {"CREDIT_CARD": "BLOCK"}) == "BLOCK")
    _overlap_result = bp.resolve_overlaps([
        {"start": 0, "end": 6, "entity_type": "PHONE_NUMBER", "score": 0.9},
        {"start": 4, "end": 12, "entity_type": "DNI", "score": 0.85},
    ])
    check("resolve_overlaps deja rangos disjuntos",
          len(_overlap_result) == 1 or all(
              a["end"] <= b["start"] for a, b in zip(_overlap_result, _overlap_result[1:])))
    check("build_ad_hoc_recognizers región eu no incluye DNI/CUIL (Argentina)",
          {rec["supported_entity"] for rec in bp.build_ad_hoc_recognizers([])} == {"PASSPORT"})

    import os as _os
    presidio_url = _os.environ.get("NLP_ANALYZER_URL")
    if presidio_url:
        import asyncio

        async def _check_presidio():
            try:
                entities = await bp.presidio_analyze(
                    "Mi NIF es 12345678Z y mi pasaporte PAB123456", presidio_url, [])
                return True, entities
            except bp.NlpUnavailableError as e:
                return False, str(e)

        ok, detail = asyncio.run(_check_presidio())
        check(f"Presidio Analyzer responde ({presidio_url})", ok, str(detail))

        async def _check_failclosed():
            try:
                await bp.presidio_analyze("hola", "http://nlp-analyzer:9999", [])
                return False
            except bp.NlpUnavailableError:
                return True

        check("presidio_analyze fail-closed ante URL inválida", asyncio.run(_check_failclosed()))
    else:
        check("NLP_ANALYZER_URL configurada", False,
              "sin esta env var el guardrail degrada a regex de dev — no válido para este check")

    print(f"\n{'CONTRATO ROTO: ' + str(FAILURES) if FAILURES else 'Contrato OK contra la imagen pinneada.'}")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
