"""Guard offline: `rdx-*` sin autorización y orden de los guardrails (057 T092; QA A3; FR-014, FR-027).

1. Un `rdx-*` sin autorización firmada se rechaza con 403 en **todo** `call_type`: texto, embeddings, imágenes,
   transcripción y cualquiera que no sea de texto (incluso uno que hoy no existe). Sin autorización nunca hay credencial
   de entorno del motor detrás de una familia `rdx-*`.
2. En el `config.yaml` fusionado, `redirect-guard` corre **después** de `sentinel-guardian` (el de la base,
   `litellm/config.yaml`): ve su `masking_report` y no uno sembrado por el cliente.
3. Un pedido que trae `metadata.masking_report`, `guardrails`, `disable_global_guardrails` u otros del cliente no relaja
   el forzado: el guard solo lee el informe del lugar donde lo escribe el guardrail de la base
   (`sentinel/engine/redirect_guard.py::_masking_report`).
"""
import asyncio
import copy
import importlib.util
from pathlib import Path

import pytest
import yaml

from sentinel.engine import fragment_merge as fm
from sentinel.engine import redirect_guard as g
from sentinel.redirect import authz

ROOT = Path(__file__).resolve().parents[3]
BASE_CONFIG = ROOT / "litellm" / "config.yaml"
FRAGMENT = ROOT / "sentinel" / "engine" / "profile-fragment.yaml"
DEPLOY_MERGE = ROOT / "deploy" / "release" / "fragment_merge.py"          # S9/S11 de la base (T020)
KEY = "k" * 48
NOW = 1_800_000_000.0
MODEL = "rdx-chatcompat/qwen"
REPORTE_OK = {"completed": True, "degraded": False, "detected": 2, "masked": 2, "unanalyzable": 0, "scope": "full"}      # con S14 el forzado exige alcance completo (057 QA B3)

TEXTUALES = ["completion", "acompletion", "atext_completion", "anthropic_messages"]
NO_TEXTUALES = ["embedding", "aembedding", "image_generation", "aimage_generation", "transcription", "atranscription",
                "aspeech", "speech", "arerank", "rerank", "amoderation", "aresponses", "responses", "avideo_generation",
                "aretrieve_batch", "acreate_file", "un_call_type_que_no_existe_todavia", "", None]


def _token(**kw):
    args = dict(request_id="req-1", scope="t1/connection:k1", destination_id="d1", model=MODEL, provider="openrouter",
                credential={"api_key": "valor-inventado-del-destino"}, api_base=None, forced_masking=False,
                provider_options={"providers_allowlist": ["acme-us"]},
                decision={"public_id": "pro", "face": "openai_generic", "rule_id": "r1"}, key=KEY, now=NOW)
    args.update(kw)
    return authz.issue(**args)


def _pedido(tok=None, model=MODEL, **extra):
    hdrs = {"content-type": "application/json"}
    if tok is not None:
        hdrs["X-Redirect-Authz"] = tok
    data = {"model": model, "messages": [{"role": "user", "content": "hola"}],
            "proxy_server_request": {"headers": dict(hdrs)}, "metadata": {"headers": dict(hdrs)}}
    data.update(extra)
    return data


def _hook(data, call_type):
    """El enganche real del motor (`async_pre_call_hook`), con la clave interna del entorno del test."""
    guard = g.RedirectGuard()
    return asyncio.run(guard.async_pre_call_hook({}, None, data, call_type))


@pytest.fixture(autouse=True)
def _clave_interna(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, KEY)


# ── 1. rdx-* sin autorización ⇒ 403 en todo call_type ─────────────────────────────────────────────

@pytest.mark.parametrize("call_type", TEXTUALES + NO_TEXTUALES)
def test_rdx_sin_autorizacion_se_rechaza_con_403_en_la_logica_pura(call_type):
    with pytest.raises(g.GuardRejection) as e:
        g.apply_redirect(_pedido(None), key=KEY, now=NOW, environ={}, call_type=call_type)
    assert e.value.status == 403 and e.value.code == "authz_missing"


@pytest.mark.parametrize("call_type", TEXTUALES + NO_TEXTUALES)
def test_rdx_sin_autorizacion_se_rechaza_con_403_por_el_enganche_del_motor(call_type):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        _hook(_pedido(None), call_type)
    assert e.value.status_code == 403 and e.value.detail["code"] == "authz_missing"


@pytest.mark.parametrize("call_type", ["acompletion", "aembedding", "aimage_generation", "atranscription"])
def test_rdx_sin_autorizacion_no_deja_credenciales_del_motor_en_el_pedido(call_type):
    data = _pedido(None)
    with pytest.raises(g.GuardRejection):
        g.apply_redirect(data, key=KEY, now=NOW, environ={"REDIRECT_CRED_X": "no-debe-salir"}, call_type=call_type)
    assert "api_key" not in data and "api_base" not in data and "no-debe-salir" not in repr(data)


@pytest.mark.parametrize("call_type", ["acompletion", "aembedding", "aimage_generation", "atranscription"])
def test_rdx_con_autorizacion_invalida_tambien_se_rechaza(call_type):
    for token in ("basura", _token(key="z" * 48), _token(model="rdx-chatcompat/otro")):
        with pytest.raises(g.GuardRejection) as e:
            g.apply_redirect(_pedido(token), key=KEY, now=NOW, environ={}, call_type=call_type)
        assert e.value.status == 403


def test_rdx_rechazado_nunca_llega_a_la_busqueda_en_el_catalogo():
    """El camino de clientes directos (`redirect_catalog`) es solo para modelos que NO son `rdx-*`."""
    class _Explota:
        async def apply(self, *a, **k):
            raise AssertionError("un rdx-* no se resuelve por catálogo")

    guard = g.RedirectGuard()
    guard._catalog = _Explota()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        asyncio.run(guard.async_pre_call_hook({}, None, _pedido(None), "aembedding"))
    assert e.value.status_code == 403


# ── 2. orden de los guardrails en el config fusionado ─────────────────────────────────────────────

def _fusionadores():
    """Los dos fusionadores con el mismo contrato: el de la extensión y, cuando exista, el de la base."""
    out = [("sentinel/engine/fragment_merge.py", fm.merge)]
    if DEPLOY_MERGE.exists():
        spec = importlib.util.spec_from_file_location("deploy_fragment_merge", DEPLOY_MERGE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out.append(("deploy/release/fragment_merge.py", mod.merge))
    return out


@pytest.mark.parametrize("nombre,merge", _fusionadores(), ids=lambda v: v if isinstance(v, str) else "")
def test_redirect_guard_corre_despues_de_sentinel_guardian(nombre, merge):
    base = yaml.safe_load(BASE_CONFIG.read_text())
    assert base["guardrails"][0]["guardrail_name"] == "sentinel-guardian"      # litellm/config.yaml:12
    fusionado = merge(base, [(FRAGMENT.name, yaml.safe_load(FRAGMENT.read_text()))])
    orden = [x["guardrail_name"] for x in fusionado["guardrails"]]
    assert orden.index("sentinel-guardian") < orden.index("redirect-guard"), orden
    assert orden[-1] == "redirect-guard"                                       # el fragmento va AL FINAL
    guard = next(x for x in fusionado["guardrails"] if x["guardrail_name"] == "redirect-guard")
    assert guard["litellm_params"]["default_on"] is True and guard["litellm_params"]["mode"] == "pre_call"
    # el fusionador no muta el config de la base
    assert [x["guardrail_name"] for x in base["guardrails"]] == ["sentinel-guardian"]


def test_el_guardrail_de_la_base_escribe_el_informe_donde_lo_lee_el_guard():
    """Mismo nombre de clave y mismo lugar (`metadata`, o `litellm_metadata` en la ruta anthropic)."""
    from extensions import sentinel_guardrail as base
    assert g.MASKING_REPORT_KEY == "masking_report"
    for call_type in ("acompletion", "anthropic_messages"):
        data = {"model": MODEL}
        home = base._metadata_home(data, call_type)
        home["masking_report"] = dict(REPORTE_OK)
        assert g._masking_report(data, call_type) == REPORTE_OK, call_type


# ── 3. lo que manda el cliente no relaja el forzado ───────────────────────────────────────────────

def _forzado():
    return _token(forced_masking=True)


@pytest.mark.parametrize("call_type", ["acompletion", "anthropic_messages"])
def test_forzado_sin_informe_del_guardrail_se_bloquea(call_type):
    with pytest.raises(g.GuardRejection) as e:
        g.apply_redirect(_pedido(_forzado()), key=KEY, now=NOW, environ={}, call_type=call_type)
    assert e.value.code == "masking_required"


@pytest.mark.parametrize("call_type", ["acompletion", "anthropic_messages"])
def test_forzado_con_informe_del_guardrail_pasa(call_type):
    data = _pedido(_forzado())
    from extensions import sentinel_guardrail as base
    base._metadata_home(data, call_type)["masking_report"] = dict(REPORTE_OK)
    assert g.apply_redirect(data, key=KEY, now=NOW, environ={}, call_type=call_type)["api_key"] == "valor-inventado-del-destino"


SEMBRADOS = [
    ("metadata", {"masking_report": REPORTE_OK}),
    ("litellm_metadata", {"masking_report": REPORTE_OK}),
    ("masking_report", REPORTE_OK),                                           # suelto en el cuerpo
    ("guardrails", ["redirect-guard"]),
    ("guardrails", {"redirect-guard": False}),
    ("disable_global_guardrails", True),
    ("opted_out_global_guardrails", ["redirect-guard", "sentinel-guardian"]),
    ("metadata", {"disable_global_guardrails": True, "guardrails": []}),
    ("metadata", {"opted_out_global_guardrails": ["redirect-guard"]}),
]


@pytest.mark.parametrize("campo,valor", SEMBRADOS, ids=[f"{c}:{str(v)[:28]}" for c, v in SEMBRADOS])
@pytest.mark.parametrize("call_type", ["acompletion", "anthropic_messages"])
def test_un_campo_del_cliente_no_reemplaza_el_informe_del_guardrail_de_la_base(campo, valor, call_type):
    """El guardrail de la base corre ANTES (por el orden del config) y escribe SIEMPRE su informe, en el mismo lugar que
    lee el guard (`_metadata_home`): lo que el cliente haya sembrado se pisa. Acá el analizador falló (informe
    incompleto): ningún campo del cliente —informe «bueno» sembrado, `guardrails`, `disable_global_guardrails`…— lo
    convierte en un pedido verificado."""
    from extensions import sentinel_guardrail as base
    data = _pedido(_forzado())
    if campo in ("metadata", "litellm_metadata"):
        data.setdefault(campo, {}).update(copy.deepcopy(valor))
    else:
        data[campo] = copy.deepcopy(valor)
    base._metadata_home(data, call_type)["masking_report"] = {            # lo que escribe la base al fallar
        "completed": False, "degraded": True, "detected": 3, "masked": 0}
    with pytest.raises(g.GuardRejection) as e:
        g.apply_redirect(data, key=KEY, now=NOW, environ={}, call_type=call_type)
    assert e.value.code == "masking_required"


def test_el_informe_sembrado_en_el_otro_lugar_no_cuenta():
    """`litellm_metadata` del cuerpo en la ruta anthropic ES el lugar del informe; el `metadata` suelto, no."""
    data = _pedido(_forzado())
    data["metadata"]["masking_report"] = dict(REPORTE_OK)                      # sembrado en `metadata`…
    with pytest.raises(g.GuardRejection) as e:
        g.apply_redirect(data, key=KEY, now=NOW, environ={}, call_type="anthropic_messages")   # …y se lee `litellm_metadata`
    assert e.value.code == "masking_required"


@pytest.mark.parametrize("sembrado", [
    {"disable_global_guardrails": True}, {"opted_out_global_guardrails": ["redirect-guard"]},
    {"guardrails": []}, {"metadata": {"disable_global_guardrails": True}},
])
def test_ni_el_cliente_ni_la_llave_apagan_el_guard_en_pre_call(sembrado):
    guard = g.RedirectGuard()
    assert guard.should_run_guardrail(dict(_pedido(None), **sembrado), "pre_call") is True
    assert guard.should_run_guardrail(dict(_pedido(None), **sembrado), type("E", (), {"value": "pre_call"})()) is True


def test_el_informe_con_conteos_que_no_cierran_o_degradado_bloquea():
    for reporte in ({"completed": True, "degraded": True, "detected": 1, "masked": 1},
                    {"completed": True, "degraded": False, "detected": 2, "masked": 1},
                    {"completed": False, "degraded": False, "detected": 0, "masked": 0}, "ok", None, {}):
        data = _pedido(_forzado())
        data["metadata"]["masking_report"] = reporte
        with pytest.raises(g.GuardRejection):
            g.apply_redirect(data, key=KEY, now=NOW, environ={}, call_type="acompletion")
