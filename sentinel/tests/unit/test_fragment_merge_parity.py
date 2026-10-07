"""Helper de fusión de fragmentos (T015): contrato de S11 y paridad con el script de la base."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sentinel.engine import fragment_merge as fm

ROOT = Path(__file__).resolve().parents[3]
FRAGMENT = ROOT / "sentinel" / "engine" / "profile-fragment.yaml"
NIX_TMPL = ROOT / "deploy" / "clients" / "nix" / "config.yaml.tmpl"
BASE_SCRIPT = ROOT / "deploy" / "release" / "fragment_merge.py"   # costura S11 (T020)


def _cfg():
    return {"model_list": [{"model_name": "base-1", "litellm_params": {"model": "openai/x"}}],
            "guardrails": [{"guardrail_name": "sentinel-guardian"}],
            "litellm_settings": {"callbacks": "x"}}


def test_agrega_al_final_y_no_muta():
    cfg = _cfg()
    out = fm.merge(cfg, [("f.yaml", yaml.safe_load(FRAGMENT.read_text()))])
    assert cfg == _cfg()
    assert out["model_list"][0]["model_name"] == "base-1"
    assert all(e["model_name"].startswith("rdx-") for e in out["model_list"][1:])
    assert [g["guardrail_name"] for g in out["guardrails"]] == ["sentinel-guardian", "redirect-guard"]
    assert out["litellm_settings"] == {"callbacks": "x"}


@pytest.mark.parametrize("frag,msg", [
    ({"router_settings": {}}, "claves no permitidas"),
    ({"model_list": {"a": 1}}, "tiene que ser una lista"),
    ({"model_list": [{"litellm_params": {}}]}, "sin 'model_name'"),
    ({"model_list": [{"model_name": "base-1"}]}, "duplicado"),
    ({"guardrails": [{"guardrail_name": "sentinel-guardian"}]}, "duplicado"),
    ({}, "mapping"),
])
def test_errores_del_contrato(frag, msg):
    with pytest.raises(fm.FragmentError, match=msg):
        fm.merge(_cfg(), [("f.yaml", frag)])


def test_duplicado_entre_fragmentos():
    f = {"model_list": [{"model_name": "rdx-x/*"}]}
    with pytest.raises(fm.FragmentError, match="duplicado"):
        fm.merge(_cfg(), [("a.yaml", f), ("b.yaml", f)])


def test_config_sin_guardrails_ni_model_list():
    out = fm.merge({"general_settings": {}}, [("f.yaml", {"guardrails": [{"guardrail_name": "g"}]})])
    assert out == {"general_settings": {}, "guardrails": [{"guardrail_name": "g"}]}


@pytest.mark.skip(reason='Usa el perfil nix de Sentinel (deploy/clients/nix/config.yaml.tmpl), que Eleia no tiene; el fusionador de la base lo prueba deploy/release/checks/test_extension_delivery.sh (T020). 057 T017')
def test_cli_sobre_el_perfil_de_nix(tmp_path):
    """El template real de nix (con placeholders resueltos a mano) + el fragmento de capa 2."""
    txt = NIX_TMPL.read_text()
    import re
    txt = re.sub(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", "x", txt)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(txt)
    before = yaml.safe_load(txt)
    rc = fm.main(["fragment_merge.py", str(cfg), str(FRAGMENT)])
    assert rc == 0
    after = yaml.safe_load(cfg.read_text())
    assert after["model_list"][:len(before["model_list"])] == before["model_list"]
    assert after["guardrails"][-1]["guardrail_name"] == "redirect-guard"
    assert {k: v for k, v in after.items() if k not in fm.KEYS} == \
        {k: v for k, v in before.items() if k not in fm.KEYS}
    # segunda aplicación ⇒ duplicados ⇒ error (el deploy renderiza desde el template cada vez)
    assert fm.main(["fragment_merge.py", str(cfg), str(FRAGMENT)]) == 1


@pytest.mark.skipif(not BASE_SCRIPT.exists(),
                    reason="la costura S11 (deploy/release/fragment_merge.py) no está en este árbol")
def test_paridad_con_el_script_de_la_base(tmp_path):
    cfg = yaml.safe_dump(_cfg(), sort_keys=False)
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text(cfg)
    b.write_text(cfg)
    frags = tmp_path / "frags"
    frags.mkdir()
    shutil.copy(FRAGMENT, frags / "068.yaml")
    subprocess.run([sys.executable, str(BASE_SCRIPT), str(a), str(frags)], check=True,
                   capture_output=True)
    assert fm.main(["x", str(b), str(frags)]) == 0
    assert a.read_text() == b.read_text()
