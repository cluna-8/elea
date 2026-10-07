"""El deploy de nix no borra los modelos dados de alta desde la consola.

Incidente 2026-09-25: `deploy.sh` copiaba el config renderizado del template sobre el volumen
del motor y se perdía todo modelo cargado por la consola (p. ej. `claude-sonnet-4-5`). El helper
`conservar_modelos_consola.py` rescata esas entradas del config vivo y las suma al nuevo.
"""
import importlib.util
import re
from pathlib import Path

import pytest

import yaml

ROOT = Path(__file__).resolve().parents[3]
HOST = ROOT / "deploy/clients/nix/host"

if not (ROOT / "deploy/clients/nix").exists():
    pytest.skip("Despliegue nix de Sentinel (deploy/clients/nix/**): no existe en Eleia, que entrega la extension por S9/S11 (T020, test_extension_delivery.sh) y las variantes -ext (T091, test_ext_images.sh). 057 T017",
                allow_module_level=True)
_spec = importlib.util.spec_from_file_location("conservar", HOST / "conservar_modelos_consola.py")
conservar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conservar)


def _m(name, model="openai/x", **info):
    e = {"model_name": name, "litellm_params": {"model": model}}
    if info:
        e["model_info"] = info
    return e


def _cfg(models, fallbacks=None, **extra):
    c = {"model_list": models, **extra}
    if fallbacks is not None:
        c["router_settings"] = {"fallbacks": fallbacks}
    return c


def _names(c):
    return [e["model_name"] for e in c.get("model_list") or []]


def test_conserva_los_modelos_de_consola_al_final():
    nuevo = _cfg([_m("nix-us-fast")])
    actual = _cfg([_m("nix-us-fast"), _m("claude", "anthropic/claude-sonnet-4-5")])
    out, rescatados = conservar.fusionar(nuevo, actual)
    assert _names(out) == ["nix-us-fast", "claude"]
    assert rescatados == ["claude"]


def test_el_template_manda_sobre_el_mismo_nombre():
    nuevo = _cfg([_m("nix-us-fast", "openai/gpt-5.4-mini")])
    actual = _cfg([_m("nix-us-fast", "openai/modelo-viejo")])
    out, rescatados = conservar.fusionar(nuevo, actual)
    assert out["model_list"] == [_m("nix-us-fast", "openai/gpt-5.4-mini")]
    assert rescatados == []


def test_nunca_rescata_entradas_internas_de_plugins():
    nuevo = _cfg([_m("nix-us-fast")])
    actual = _cfg([_m("rdx-openai/*", "openai/*", plugin_owner="redirect"),
                   _m("rdx-viejo/*", "openai/*"),
                   _m("otra-interna", plugin_owner="x")])
    out, rescatados = conservar.fusionar(nuevo, actual)
    assert _names(out) == ["nix-us-fast"] and rescatados == []


def test_conserva_los_fallbacks_de_los_modelos_rescatados_con_destinos_existentes():
    nuevo = _cfg([_m("nix-us-fast"), _m("router-embeddings")], fallbacks=[])
    actual = _cfg([_m("claude"), _m("borrado")],
                  fallbacks=[{"claude": ["nix-us-fast", "no-existe"]}, {"borrado": ["nix-us-fast"]},
                             {"nix-us-fast": ["claude"]}])
    out, _ = conservar.fusionar(nuevo, actual)
    fb = out["router_settings"]["fallbacks"]
    assert {"claude": ["nix-us-fast"]} in fb                  # destino inexistente descartado
    assert all("nix-us-fast" not in f for f in fb)            # fallbacks del template no se tocan


def test_descarta_fallbacks_hacia_modelos_de_embeddings():
    # incidente 2026-09-27: la consola dejó `claude → router-embeddings` (un modelo de embeddings)
    nuevo = _cfg([_m("router-embeddings", "ollama/qwen3-embedding:0.6b"),
                  _m("nix-us-embed", "openai/text-embedding-3-small"),
                  _m("marcado", "openai/x", mode="embedding"), _m("nix-us-fast")], fallbacks=[])
    actual = _cfg([_m("claude", "anthropic/claude-sonnet-4-5")],
                  fallbacks=[{"claude": ["router-embeddings", "nix-us-embed", "marcado", "nix-us-fast"]}])
    out, _ = conservar.fusionar(nuevo, actual)
    assert out["router_settings"]["fallbacks"] == [{"claude": ["nix-us-fast"]}]


def test_si_solo_quedaban_embeddings_el_fallback_desaparece():
    nuevo = _cfg([_m("router-embeddings", "ollama/qwen3-embedding:0.6b")], fallbacks=[])
    actual = _cfg([_m("claude")], fallbacks=[{"claude": ["router-embeddings"]}])
    out, _ = conservar.fusionar(nuevo, actual)
    assert out["router_settings"]["fallbacks"] == []


def test_el_template_manda_en_los_fallbacks_del_mismo_modelo():
    nuevo = _cfg([_m("a"), _m("b")], fallbacks=[{"a": ["b"]}])
    actual = _cfg([_m("a"), _m("b"), _m("c")], fallbacks=[{"a": ["c"]}, {"c": ["a"]}])
    out, _ = conservar.fusionar(nuevo, actual)
    assert out["router_settings"]["fallbacks"] == [{"a": ["b"]}, {"c": ["a"]}]


def test_sin_config_vivo_no_cambia_nada():
    nuevo = _cfg([_m("nix-us-fast")])
    out, rescatados = conservar.fusionar(nuevo, None)
    assert out == nuevo and rescatados == []


def test_config_vivo_ilegible_no_rompe_el_deploy(tmp_path):
    nuevo = tmp_path / "nuevo.yaml"
    nuevo.write_text(yaml.safe_dump(_cfg([_m("nix-us-fast")])))
    antes = nuevo.read_text()
    vivo = tmp_path / "vivo.yaml"
    vivo.write_text(":::no es yaml [")
    assert conservar.main([str(nuevo), str(vivo)]) == 0
    assert nuevo.read_text() == antes


def test_main_reescribe_el_nuevo_y_no_imprime_secretos(tmp_path, capsys):
    nuevo = tmp_path / "nuevo.yaml"
    nuevo.write_text(yaml.safe_dump(_cfg([_m("nix-us-fast")])))
    vivo = tmp_path / "vivo.yaml"
    secreto = _m("claude", "anthropic/claude-sonnet-4-5")
    secreto["litellm_params"]["api_key"] = "sk-ant-SECRETO"
    vivo.write_text(yaml.safe_dump(_cfg([_m("nix-us-fast"), secreto])))
    assert conservar.main([str(nuevo), str(vivo)]) == 0
    assert _names(yaml.safe_load(nuevo.read_text())) == ["nix-us-fast", "claude"]
    salida = capsys.readouterr()
    assert "SECRETO" not in salida.out + salida.err and "claude" in salida.out + salida.err


def test_deploy_sh_aplica_el_helper_antes_de_copiar_al_volumen():
    deploy = (HOST / "deploy.sh").read_text()
    assert "conservar_modelos_consola.py" in deploy
    i_helper = deploy.index("conservar_modelos_consola.py")
    i_cp = deploy.index("cp /state/config.yaml.$VERSION /vol/config.yaml")
    assert i_helper < i_cp
    # lee el config vivo del snapshot que el propio deploy ya toma del volumen
    assert re.search(r"litellm_config-antes-de-\$VERSION\.tgz", deploy[:i_helper])
