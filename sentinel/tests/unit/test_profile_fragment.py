"""Fragmento de perfil: familias estables sin credencial + guard (D14/D15/D21; T015)."""
import os

import yaml

from sentinel.redirect import credentials

PATH = os.path.join(os.path.dirname(__file__), "..", "..", "engine", "profile-fragment.yaml")


def load():
    with open(PATH) as f:
        return yaml.safe_load(f)


def test_families_match_code():
    frag = load()
    entries = {m["model_name"]: m for m in frag["model_list"]}
    assert set(entries) == {f"{fam}/*" for fam in credentials.FAMILIES}
    for fam, prefix in credentials.FAMILIES.items():
        e = entries[f"{fam}/*"]
        assert e["litellm_params"] == {"model": f"{prefix}/*"}      # sin credencial ni base
        assert e["model_info"]["plugin_owner"]


def test_guard_declared_pre_call_default_on():
    (guard,) = load()["guardrails"]
    assert guard["guardrail_name"] == "redirect-guard"
    lp = guard["litellm_params"]
    assert lp == {"guardrail": "extensions.redirect_guard.RedirectGuard", "mode": "pre_call", "default_on": True}


def test_fragment_is_brand_neutral():
    with open(PATH) as f:
        assert "sentinel" not in f.read().lower()
