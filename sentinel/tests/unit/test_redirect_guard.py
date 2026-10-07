"""Guard del motor (D15/D16/D18; T034/T037/T074) — lógica y enganche con LiteLLM 1.92.0."""
import os
import shutil
import subprocess
import sys

import pytest

from sentinel.engine import redirect_guard as g
from sentinel.redirect import authz

KEY = "k" * 48
NOW = 1_800_000_000.0
MODEL = "rdx-chatcompat/qwen"


def token(**kw):
    args = dict(request_id="req-1", scope="t1/connection:k1", destination_id="d1", model=MODEL,
                provider="openrouter", credential={"api_key": "sk-destino"}, api_base=None,
                provider_options={"providers_allowlist": ["acme-us"]},
                forced_masking=False, decision={"public_id": "pro", "face": "openai_generic",
                                                "rule_id": "r1"}, key=KEY, now=NOW)
    args.update(kw)
    return authz.issue(**args)


def request(tok=None, model=MODEL, **extra):
    hdrs = {"content-type": "application/json"}
    if tok is not None:
        hdrs["X-Redirect-Authz"] = tok
    data = {"model": model, "messages": [{"role": "user", "content": "hola"}],
            "proxy_server_request": {"headers": dict(hdrs)},
            "metadata": {"headers": dict(hdrs)}}
    data.update(extra)
    return data


def apply(data, **kw):
    kw.setdefault("key", KEY)
    kw.setdefault("now", NOW)
    kw.setdefault("environ", {})
    return g.apply_redirect(data, **kw)


def test_non_redirect_untouched():
    data = request(None, model="gpt-4o", api_key="cliente")
    snapshot = repr(data)
    assert apply(data) is data and repr(data) == snapshot


def test_missing_token_rejected():
    with pytest.raises(g.GuardRejection) as e:
        apply(request(None))
    assert e.value.status == 403 and e.value.code == "authz_missing"


def test_valid_token_sets_destination_credentials():
    out = apply(request(token()))
    assert out["api_key"] == "sk-destino"
    assert out["api_base"] == "https://openrouter.ai/api/v1"
    assert out["model"] == MODEL


def test_model_mismatch_rejected():
    with pytest.raises(g.GuardRejection) as e:
        apply(request(token(), model="rdx-chatcompat/otro"))
    assert e.value.code == "authz_model_mismatch"


def test_family_must_match_provider():
    tok = token(model="rdx-openai/qwen")   # firmado, pero proveedor openrouter ≠ familia openai
    with pytest.raises(g.GuardRejection) as e:
        apply(request(tok, model="rdx-openai/qwen"))
    assert e.value.code == "family_mismatch"


def test_expired_and_wrong_key():
    with pytest.raises(g.GuardRejection):
        apply(request(token()), now=NOW + 3600)
    with pytest.raises(g.GuardRejection):
        apply(request(token()), key="z" * 48)


def test_missing_internal_key_is_503():
    with pytest.raises(g.GuardRejection) as e:
        g.apply_redirect(request(token()), key="", now=NOW, environ={})
    assert e.value.status == 503


def test_anti_diversion_client_fields_removed():
    data = request(token(), api_key="cliente", api_base="https://evil", base_url="https://evil",
                   extra_headers={"Authorization": "x"}, aws_secret_access_key="x",
                   headers={"authorization": "Bearer cliente", "anthropic-beta": "b1",
                            "x-redirect-authz": "tok"})
    out = apply(data)
    assert out["api_key"] == "sk-destino" and out["api_base"] == "https://openrouter.ai/api/v1"
    for k in ("base_url", "extra_headers", "aws_secret_access_key"):
        assert k not in out
    assert out["headers"] == {"anthropic-beta": "b1"}


def test_internal_header_scrubbed_from_logs():
    data = apply(request(token()))
    assert all(k.lower() != "x-redirect-authz" for k in data["proxy_server_request"]["headers"])
    assert all(k.lower() != "x-redirect-authz" for k in data["metadata"]["headers"])


def test_env_reference_resolved_engine_side():
    tok = token(credential={"api_key": "env:REDIRECT_CRED_OR"})
    out = apply(request(tok), environ={"REDIRECT_CRED_OR": "sk-del-entorno"})
    assert out["api_key"] == "sk-del-entorno"
    with pytest.raises(g.GuardRejection) as e:
        apply(request(tok), environ={})
    assert e.value.status == 503 and "sk" not in e.value.message


def _decision(out, home="metadata"):
    return out[home]["_internal_routing_decision"]["extensions"]["redirect"]


def test_decision_written_and_client_value_overwritten():
    from extensions import sentinel_guardian_policy as gpol
    data = request(token())
    data["metadata"]["_internal_routing_decision"] = {"destination_id": "falso"}
    out = apply(data)
    raw = out["metadata"]["_internal_routing_decision"]
    assert isinstance(raw, gpol.EngineRoutingDecision)          # confiable para S7
    assert gpol.trusted_routing_decision(out["metadata"]) == raw
    d = _decision(out)
    assert d["destination_id"] == "d1" and d["public_id"] == "pro" and d["request_id"] == "req-1"
    assert d["forced_masking"] is False
    assert set(raw) == {"extensions"}


def test_client_value_in_the_other_home_is_dropped():
    data = request(token())
    data["litellm_metadata"] = {"_internal_routing_decision": {"x": 1}}
    out = apply(data)                   # con litellm_metadata presente, el home es ese
    assert _decision(out, "litellm_metadata")["destination_id"] == "d1"
    assert "_internal_routing_decision" not in out["metadata"]


def test_decision_home_follows_call_type():
    """En anthropic_messages `metadata` viaja al proveedor: la decisión va a litellm_metadata."""
    data = request(token())
    out = apply(data, call_type="anthropic_messages")
    assert _decision(out, "litellm_metadata")["rule_id"] == "r1"
    assert "_internal_routing_decision" not in out["metadata"]


def test_previous_engine_decision_is_kept():
    from extensions import sentinel_guardian_policy as gpol
    data = request(token())
    gpol.mark_routing_decision(data["metadata"], {"route": "auto", "model_selected": "x"})
    out = apply(data)
    raw = out["metadata"]["_internal_routing_decision"]
    assert raw["route"] == "auto" and raw["extensions"]["redirect"]["rule_id"] == "r1"


def test_decision_only_scalars():
    tok = token(decision={"public_id": "p" * 300, "lista": [1], "Mayus": 1, "ok_1": 2.5})
    d = _decision(apply(request(tok)))
    assert d["public_id"] == "p" * 128 and "lista" not in d and "Mayus" not in d and d["ok_1"] == 2.5


def test_decision_created_when_no_metadata():
    data = request(token())
    data.pop("metadata")
    assert _decision(apply(data))["rule_id"] == "r1"


def test_shadow_non_redirect_model_records_decision_only():
    tok = token(model="modelo-base", decision={"public_id": "pro", "shadow_destination_id": "d9"})
    data = request(tok, model="modelo-base")
    out = apply(data)
    d = _decision(out)
    assert d["shadow"] is True and d["shadow_destination_id"] == "d9"
    assert "api_key" not in out and out["model"] == "modelo-base"
    assert "x-redirect-authz" not in {k.lower() for k in out["proxy_server_request"]["headers"]}


def test_shadow_token_for_another_model_is_ignored():
    data = request(token(), model="modelo-base")          # token para MODEL, pedido a otro
    out = apply(data)
    assert "_internal_routing_decision" not in out["metadata"]
    assert "x-redirect-authz" not in {k.lower() for k in out["proxy_server_request"]["headers"]}


GOOD_REPORT = {"completed": True, "degraded": False, "detected": 3, "masked": 3, "unanalyzable": 0, "scope": "full"}


@pytest.mark.parametrize("report,ok", [
    (GOOD_REPORT, True),
    ({**GOOD_REPORT, "degraded": True}, False),
    ({**GOOD_REPORT, "completed": False}, False),
    ({**GOOD_REPORT, "masked": 2}, False),
    ({"completed": True}, False),
    # 057 S14 (QA B3): con el forzado vigente, alcance completo y nada no analizable
    ({**GOOD_REPORT, "unanalyzable": 1}, False),
    ({**GOOD_REPORT, "scope": "user"}, False),
    ({k: v for k, v in GOOD_REPORT.items() if k != "scope"}, False),            # informe viejo, sin `scope`
    ({k: v for k, v in GOOD_REPORT.items() if k != "unanalyzable"}, False),
    ({**GOOD_REPORT, "unanalyzable": "0"}, True),
    ({**GOOD_REPORT, "unanalyzable": None}, False),
    ({**GOOD_REPORT, "unanalyzable": True}, False),
    ({**GOOD_REPORT, "scope": "FULL"}, False),
    (None, False),
    ("sí", False),
])
def test_forced_masking(report, ok):
    data = request(token(forced_masking=True))
    if report is not None:
        data["metadata"]["masking_report"] = report
    if ok:
        out = apply(data)
        assert _decision(out)["masking_verified"] is True
    else:
        with pytest.raises(g.GuardRejection) as e:
            apply(data)
        assert e.value.code == "masking_required"


def test_masking_report_in_litellm_metadata():
    data = request(token(forced_masking=True))
    data["litellm_metadata"] = {"masking_report": GOOD_REPORT}
    apply(data)


def test_masking_report_from_client_metadata_does_not_count():
    """anthropic_messages: el guardrail de la base escribe en litellm_metadata; un informe
    sembrado por el cliente en `metadata` (campo del body) no habilita el destino."""
    data = request(token(forced_masking=True))
    data["metadata"]["masking_report"] = GOOD_REPORT
    with pytest.raises(g.GuardRejection) as e:
        apply(data, call_type="anthropic_messages")
    assert e.value.code == "masking_required"


def test_messages_are_brand_neutral():
    for code_call in (lambda: apply(request(None)),
                      lambda: apply(request(token(forced_masking=True)))):
        with pytest.raises(g.GuardRejection) as e:
            code_call()
        assert "sentinel" not in e.value.message.lower()


# --- enganche LiteLLM ---------------------------------------------------------------

async def test_hook_raises_http_403(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setenv(authz.KEY_ENV, KEY)
    guard = g.RedirectGuard(guardrail_name="redirect-guard", event_hook="pre_call", default_on=True)
    with pytest.raises(HTTPException) as e:
        await guard.async_pre_call_hook(None, None, request(None), "acompletion")
    assert e.value.status_code == 403


async def test_hook_passes_valid(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, KEY)
    guard = g.RedirectGuard(guardrail_name="redirect-guard", event_hook="pre_call", default_on=True)
    tok = authz.issue(request_id="r", scope="s", destination_id="d1", model=MODEL, provider="openrouter",
                      credential={"api_key": "sk-destino"}, provider_options={"providers_allowlist": ["acme-us"]})
    out = await guard.async_pre_call_hook(None, None, request(tok), "acompletion")
    assert out["api_key"] == "sk-destino"


def test_guard_cannot_be_opted_out():
    from litellm.types.guardrails import GuardrailEventHooks
    guard = g.RedirectGuard(guardrail_name="redirect-guard", event_hook="pre_call", default_on=True)
    data = {"metadata": {"user_api_key_metadata": {"disable_global_guardrails": True,
                                                   "opted_out_global_guardrails": ["redirect-guard"]}}}
    assert guard.should_run_guardrail(data, GuardrailEventHooks.pre_call) is True


def test_flat_copy_import(tmp_path):
    """Copiado plano como en S9: `extensions/redirect_guard.py` + hermanos, sin el paquete."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "engine"))
    ext = tmp_path / "extensions"
    ext.mkdir()
    (ext / "__init__.py").write_text("")
    for f in ("redirect_guard.py", "redirect_authz.py", "redirect_credentials.py"):
        shutil.copy(os.path.join(root, f), ext / f)
    code = ("import importlib.util, sys; assert importlib.util.find_spec('sentinel') is None;"
            "import extensions.redirect_guard as m; print(m.authz.__name__, m.credentials.__name__)")
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(tmp_path)})
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["extensions.redirect_authz", "extensions.redirect_credentials"]


# ── mínimo de tokens de salida del destino (069 T183) ─────────────────────────────────────────────

@pytest.mark.parametrize("provider", ["openai", "azure"])
def test_min_output_tokens_sube_lo_que_esta_por_debajo(provider):
    data = {"max_completion_tokens": 5, "max_output_tokens": 1}
    assert g.raise_min_output_tokens(data, provider) == ["max_completion_tokens", "max_output_tokens"]
    assert data == {"max_completion_tokens": 16, "max_output_tokens": 16}


def test_min_output_tokens_no_agrega_ni_toca_lo_valido_ni_otros_proveedores():
    data = {"max_completion_tokens": 1000}
    assert g.raise_min_output_tokens(data, "openai") == [] and data == {"max_completion_tokens": 1000}
    assert g.raise_min_output_tokens(data, "openai") == [] and "max_output_tokens" not in data
    data = {"max_tokens": 1}
    assert g.raise_min_output_tokens(data, "openrouter") == [] and data == {"max_tokens": 1}
    data = {"max_output_tokens": True, "max_completion_tokens": None}
    assert g.raise_min_output_tokens(data, "openai") == [] and data["max_output_tokens"] is True


# ── max_tokens → max_completion_tokens para OpenAI/Azure (069 T192) ───────────────────────────────

@pytest.mark.parametrize("provider", ["openai", "azure"])
def test_max_tokens_se_renombra_a_max_completion_tokens(provider):
    data = {"max_tokens": 4096}
    assert g.raise_min_output_tokens(data, provider) == ["max_tokens->max_completion_tokens"]
    assert data == {"max_completion_tokens": 4096}


@pytest.mark.parametrize("provider", ["openai", "azure"])
def test_con_los_dos_se_quita_max_tokens(provider):
    data = {"max_tokens": 4096, "max_completion_tokens": 2000}
    assert g.raise_min_output_tokens(data, provider) == ["max_tokens"]
    assert data == {"max_completion_tokens": 2000}


def test_max_tokens_otros_proveedores_intacto():
    for provider in ("openrouter", "deepseek", "ollama"):
        data = {"max_tokens": 4096}
        assert g.raise_min_output_tokens(data, provider) == [] and data == {"max_tokens": 4096}


def test_el_piso_sigue_tras_el_renombre():
    data = {"max_tokens": 1}
    assert g.raise_min_output_tokens(data, "openai") == ["max_tokens->max_completion_tokens", "max_completion_tokens"]
    assert data == {"max_completion_tokens": 16}


def test_max_tokens_no_entero_se_renombra_sin_tocar_el_valor():
    data = {"max_tokens": "1"}
    g.raise_min_output_tokens(data, "openai")
    assert data == {"max_completion_tokens": "1"}


@pytest.mark.parametrize("call_type", ["anthropic_messages", "responses", "aresponses"])
def test_max_tokens_de_la_cara_claude_y_responses_no_se_renombra(call_type):
    data = {"max_tokens": 4096}
    assert g.raise_min_output_tokens(data, "openai", call_type) == [] and data == {"max_tokens": 4096}


# ── 069 T193: chat + tools + razonamiento hacia OpenAI/Azure se puentea a Responses ──────

TOOLS = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]


def _puente(provider, model, call_type=None, **extra):
    cred = {"api_key": "sk-x", **({"api_version": "2025-04-01-preview"} if provider == "azure" else {})}
    tok = token(provider=provider, model=model, credential=cred,
                api_base="https://r.openai.azure.com" if provider == "azure" else None)
    return apply(request(tok, model=model, **extra), call_type=call_type)


def _adj(out):
    return str(out.get("adjusted_params") or "") + repr(out.get("metadata")) + repr(out.get("litellm_metadata"))


@pytest.mark.parametrize("provider,fam", [("openai", "rdx-openai"), ("azure", "rdx-azure")])
def test_chat_con_tools_y_razonamiento_va_por_responses(provider, fam):
    out = _puente(provider, f"{fam}/gpt-6-luna", "acompletion", tools=TOOLS, reasoning_effort="high")
    assert out["model"] == f"{fam}/responses/gpt-6-luna"
    assert out["reasoning_effort"] == "high" and out["tools"] == TOOLS
    assert "chat->responses" in _adj(out)


def test_el_puente_tambien_aplica_sin_call_type():
    out = _puente("openai", "rdx-openai/gpt-6-luna", None, tools=TOOLS, reasoning_effort="medium")
    assert out["model"] == "rdx-openai/responses/gpt-6-luna"


@pytest.mark.parametrize("call_type", ["anthropic_messages", "responses", "aresponses"])
def test_el_puente_no_toca_claude_desktop_ni_responses(call_type):
    out = _puente("openai", "rdx-openai/gpt-6-luna", call_type, tools=TOOLS, reasoning_effort="high")
    assert out["model"] == "rdx-openai/gpt-6-luna" and "chat->responses" not in _adj(out)


@pytest.mark.parametrize("extra", [
    {"reasoning_effort": "high"},
    {"tools": [], "reasoning_effort": "high"},
    {"tools": []},
])
def test_el_puente_exige_tools(extra):
    out = _puente("openai", "rdx-openai/gpt-6-luna", "acompletion", **extra)
    assert out["model"] == "rdx-openai/gpt-6-luna" and "chat->responses" not in _adj(out)


@pytest.mark.parametrize("extra", [{}, {"reasoning_effort": "none"}, {"reasoning_effort": None}, {"reasoning_effort": "low"}])
def test_con_tools_puentea_aunque_el_cliente_pida_none_o_no_diga_nada(extra):
    # 6-oct: el Harness manda reasoning_effort='none' y LiteLLM lo descarta (gpt-6 no está en los params soportados)
    out = _puente("openai", "rdx-openai/gpt-6-luna", "acompletion", tools=TOOLS, **extra)
    assert out["model"] == "rdx-openai/responses/gpt-6-luna" and "chat->responses" in _adj(out)
    assert out.get("reasoning_effort") == extra.get("reasoning_effort")      # 'none' se preserva para Responses


@pytest.mark.parametrize("real", ["gpt-5.4", "gpt-6.1-sol", "o4-mini"])
def test_el_puente_cubre_las_familias_de_razonamiento(real):
    assert _puente("openai", f"rdx-openai/{real}", "acompletion", tools=TOOLS)["model"] == f"rdx-openai/responses/{real}"


def test_el_puente_no_toca_modelos_que_no_razonan():
    out = _puente("openai", "rdx-openai/gpt-4.1", "acompletion", tools=TOOLS)
    assert out["model"] == "rdx-openai/gpt-4.1"


def test_la_ficha_con_thinking_puentea_aunque_el_nombre_no_lo_diga():
    d = {"model": "rdx-openai/modelo-raro", "tools": TOOLS}
    assert g.bridge_to_responses(d, "openai", "acompletion", thinking=True) == ["chat->responses"]
    assert d["model"] == "rdx-openai/responses/modelo-raro"
    d = {"model": "rdx-openai/modelo-raro", "tools": TOOLS}
    assert g.bridge_to_responses(d, "openai", "acompletion") == []


def test_el_puente_no_aplica_a_openrouter():
    out = apply(request(token(), tools=TOOLS, reasoning_effort="high"), call_type="acompletion")
    assert out["model"] == MODEL and "chat->responses" not in _adj(out)


def test_el_puente_es_idempotente():
    data = {"model": "rdx-openai/responses/gpt-6-luna", "tools": TOOLS, "reasoning_effort": "high"}
    assert g.bridge_to_responses(data, "openai", "acompletion") == [] and data["model"] == "rdx-openai/responses/gpt-6-luna"


# ── 069 T070: la redirección suma su capa a la atribución confiable ──────────────────────

def _atribucion(out):
    from extensions import sentinel_guardian_policy as gp
    return gp.trusted_attribution(out["metadata"], out.get("litellm_metadata"))


@pytest.mark.skip(reason='Necesita el canal confiable de atribucion de la auditoria tramo 1 de Sentinel (069: trusted_attribution y mark_attribution en sentinel_guardian_policy), que Eleia no trae; el guard ya lo condiciona con hasattr (redirect_guard.py:217). 057 T017')
def test_la_redireccion_suma_su_capa_a_la_atribucion_confiable():
    out = apply(request(token()))
    atribucion = _atribucion(out)
    assert atribucion["extra_layers"] == [
        {"layer_code": "model_redirect", "status": "applied", "decision": "allow"}]


@pytest.mark.skip(reason='Necesita el canal confiable de atribucion de la auditoria tramo 1 de Sentinel (069: trusted_attribution y mark_attribution en sentinel_guardian_policy), que Eleia no trae; el guard ya lo condiciona con hasattr (redirect_guard.py:217). 057 T017')
def test_la_capa_se_suma_sin_pisar_lo_que_marco_el_guardrail():
    from extensions import sentinel_guardian_policy as gp
    data = request(token())
    capas = [{"layer_code": "pii_masking", "status": "applied", "decision": "mask", "count": 2}]
    gp.mark_attribution(data["metadata"], applied_layers=capas, compliance_status="passed")
    atribucion = _atribucion(apply(data))
    assert atribucion["applied_layers"] == capas and atribucion["compliance_status"] == "passed"
    assert atribucion["extra_layers"][0]["layer_code"] == "model_redirect"


@pytest.mark.skip(reason='Necesita el canal confiable de atribucion de la auditoria tramo 1 de Sentinel (069: trusted_attribution y mark_attribution en sentinel_guardian_policy), que Eleia no trae; el guard ya lo condiciona con hasattr (redirect_guard.py:217). 057 T017')
def test_una_decision_en_sombra_no_cuenta_como_capa_aplicada():
    data = request(token(model="gpt-4o"), model="gpt-4o")
    out = apply(data)
    assert _atribucion(out) is None


def test_la_decision_completa_entra_en_el_limite_de_claves_del_saneo():
    """Margen de `extensions` (24 claves, 4 KB; `internal.py`): el guard suma las suyas a las
    del plugin y NINGUNA se pierde en silencio. Si este test falla, hay que subir el tope por
    costura antes de agregar un campo (análisis de auditoría, C.1)."""
    pytest.importorskip("fastapi")
    try:
        from src.api import internal
    except ImportError:
        pytest.skip("backend fuera del path")
    decision = {"public_id": "pro", "face": "openai_generic", "rule_id": "r1",
                "destination_name": "Azure UE", "fidelity": "equivalent", "strategy": "rule",
                "substitution_reason": "residency", "residency_mode": "strict",
                "jurisdiction_served": "EU", "shadow": False, "dropped_params": "top_k,seed",
                "adjusted_params": "max_tokens", "state": "on"}
    out = apply(request(token(decision=decision)))
    guardada = out["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    saneada = internal._extensiones_saneadas({"redirect": guardada})["redirect"]
    assert saneada.keys() == guardada.keys(), "el saneo descartó claves: faltan " + str(
        set(guardada) - set(saneada))
    assert len(guardada) <= 24 - 2, "quedan menos de 2 claves de margen en `extensions`"


def test_sin_forzado_el_informe_viejo_sigue_sin_hacer_falta():
    """La verificación de alcance completo es solo del forzado: un destino sin forzado no pide informe."""
    out = apply(request(token(forced_masking=False)))
    assert "masking_scope" not in _decision(out)


def test_con_forzado_la_decision_lleva_el_alcance_verificado_y_nunca_contenido():
    out = apply(_forced_with(GOOD_REPORT))
    d = _decision(out)
    assert d["masking_scope"] == "full" and d["masking_verified"] is True


def _forced_with(report):
    data = request(token(forced_masking=True))
    data["metadata"]["masking_report"] = report
    return data


def test_el_forzado_por_la_postura_por_defecto_exige_lo_mismo():
    """Da igual de dónde venga el forzado (fila, piso de `default_posture` o respaldo): la autorización lo trae como
    `forced_masking` y el guard verifica igual."""
    with pytest.raises(g.GuardRejection) as e:
        apply(_forced_with({**GOOD_REPORT, "scope": "user"}))
    assert e.value.code == "masking_required"


def test_el_cache_no_se_apoya_en_el_alcance():
    """`_no_masking_map` (caché de respuestas) usa la verificación base: sin `scope` no cambia su decisión."""
    assert g._no_masking_map({"completed": True, "degraded": False, "detected": 0, "masked": 0}) is True


# ── thinking firmado con detecciones (S14, R10; coordinación con E2) ──────────────────────────────────

def _forzado_en(provider, report):
    modelo = g.credentials.PROVIDER_FAMILY[provider] + "/m"
    data = request(token(forced_masking=True, provider=provider, model=modelo,
                         credential={"api_key": "sk-destino"}, api_base=None), model=modelo)
    data["metadata"]["masking_report"] = report
    return data


def test_thinking_firmado_con_detecciones_hacia_un_destino_nativo_se_bloquea():
    informe = {**GOOD_REPORT, g.SIGNED_THINKING_FIELD: 2}
    with pytest.raises(g.GuardRejection) as e:
        apply(_forzado_en("anthropic", informe))
    assert e.value.code == "masking_required"


def test_hacia_un_traducido_no_se_bloquea_porque_la_firma_se_reconstruye():
    informe = {**GOOD_REPORT, g.SIGNED_THINKING_FIELD: 2}
    assert apply(_forzado_en("openrouter", informe))["api_key"] == "sk-destino"


@pytest.mark.parametrize("valor", [0, None, "2", True, 1.5])
def test_un_campo_ausente_cero_o_no_entero_no_bloquea_por_si_solo(valor):
    informe = {**GOOD_REPORT, g.SIGNED_THINKING_FIELD: valor}
    assert apply(_forzado_en("anthropic", informe))["api_key"] == "sk-destino"


# ── exenciones opcionales de S14 en la auditoría (057 T111/T112; research R34) ─────────────────────

def test_las_exenciones_del_informe_quedan_en_la_decision_solo_los_nombres_conocidos():
    informe = {**GOOD_REPORT, "exempt": ["tool_definitions", "system_prompt", "inventada", 7]}
    rd = _decision(apply(_forzado_en("openrouter", informe)))
    assert rd["masking_exempt"] == "system_prompt,tool_definitions"


@pytest.mark.parametrize("exempt", [None, [], "system_prompt", {"a": 1}, ["otra"]])
def test_sin_exenciones_validas_la_decision_no_lleva_el_campo(exempt):
    informe = dict(GOOD_REPORT)
    if exempt is not None:
        informe["exempt"] = exempt
    assert "masking_exempt" not in _decision(apply(_forzado_en("openrouter", informe)))


# ── binarios de una herramienta reemplazados por una nota (S14; 057 R39) ─────────────────────────────

def test_los_binarios_reemplazados_quedan_en_la_decision_solo_conteo_y_nombres_de_tipo():
    informe = {**GOOD_REPORT, "unanalyzable_replaced": 2, "unanalyzable_replaced_kinds": ["image", "pdf_no_text"]}
    out = apply(_forzado_en("openrouter", informe))                  # no bloquea: el binario ya no sale
    rd = _decision(out)
    assert rd["unanalyzable_replaced"] == 2 and rd["unanalyzable_replaced_kinds"] == "image,pdf_no_text"


@pytest.mark.parametrize("n,kinds", [(0, []), (None, None), (True, ["image"]), ("2", ["image"]), (-1, ["image"])])
def test_sin_reemplazos_validos_la_decision_no_lleva_el_campo(n, kinds):
    informe = dict(GOOD_REPORT)
    if n is not None:
        informe.update(unanalyzable_replaced=n, unanalyzable_replaced_kinds=kinds)
    rd = _decision(apply(_forzado_en("openrouter", informe)))
    assert "unanalyzable_replaced" not in rd and "unanalyzable_replaced_kinds" not in rd


def test_los_nombres_de_tipo_del_informe_se_acotan_a_identificadores_cortos():
    informe = {**GOOD_REPORT, "unanalyzable_replaced": 1,
               "unanalyzable_replaced_kinds": ["image", "Juan Pérez 30123456", "x" * 80, 7]}
    assert _decision(apply(_forzado_en("openrouter", informe)))["unanalyzable_replaced_kinds"] == "image"


def test_un_reemplazo_no_tapa_un_no_analizable():
    informe = {**GOOD_REPORT, "unanalyzable": 1, "unanalyzable_replaced": 3, "unanalyzable_replaced_kinds": ["image"]}
    with pytest.raises(g.GuardRejection) as e:
        apply(_forzado_en("openrouter", informe))
    assert e.value.code == "masking_required"


# ── imágenes sin enmascarar bajo el forzado (S14; 057 R43: MASKING_IMAGES=pass) ─────────────────────────────

def test_las_imagenes_sin_enmascarar_no_bloquean_y_quedan_en_la_decision_solo_conteo_y_tipo():
    informe = {**GOOD_REPORT, "images_unmasked": 3, "images_unmasked_kinds": ["image"]}
    assert g.masking_ok(informe, forced=True), "no cuentan como no analizables"
    rd = _decision(apply(_forzado_en("openrouter", informe)))
    assert rd["images_unmasked"] == 3 and rd["images_unmasked_kinds"] == "image"
    assert rd["masking_scope"] == "full" and rd["masking_verified"] is True


@pytest.mark.parametrize("n,kinds", [(0, []), (None, None), (True, ["image"]), ("2", ["image"]), (-1, ["image"])])
def test_sin_imagenes_validas_la_decision_no_lleva_el_campo(n, kinds):
    informe = dict(GOOD_REPORT)
    if n is not None:
        informe.update(images_unmasked=n, images_unmasked_kinds=kinds)
    rd = _decision(apply(_forzado_en("openrouter", informe)))
    assert "images_unmasked" not in rd and "images_unmasked_kinds" not in rd


def test_los_nombres_de_tipo_de_las_imagenes_se_acotan_a_identificadores_cortos():
    informe = {**GOOD_REPORT, "images_unmasked": 1,
               "images_unmasked_kinds": ["image", "Juan Pérez 30123456", "x" * 80, 7]}
    assert _decision(apply(_forzado_en("openrouter", informe)))["images_unmasked_kinds"] == "image"


def test_las_imagenes_sin_enmascarar_no_tapan_un_no_analizable():
    informe = {**GOOD_REPORT, "unanalyzable": 1, "unanalyzable_kinds": ["audio"],
               "images_unmasked": 2, "images_unmasked_kinds": ["image"]}
    with pytest.raises(g.GuardRejection) as e:
        apply(_forzado_en("openrouter", informe))
    assert e.value.code == "masking_required"


# ── alcance del sufijo de los marcadores en la auditoría (S13; 057 T073) ───────────────────────────

@pytest.mark.parametrize("informe,esperado", [
    ({**GOOD_REPORT, "nonce_scope": "conversation"}, "conversation"),
    (dict(GOOD_REPORT), "request"),
    ({**GOOD_REPORT, "nonce_scope": "otro"}, "request"),
    ({**GOOD_REPORT, "nonce_scope": 1}, "request"),
])
def test_la_decision_registra_el_alcance_del_sufijo_solo_el_nombre(informe, esperado):
    assert _decision(apply(_forzado_en("openrouter", informe)))["nonce_scope"] == esperado
