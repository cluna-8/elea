"""Los servicios internos toman el modelo del catálogo (069, T185–T190): nunca un alias fijo.

Incidente 5-oct-2026: AnythingLLM, Presenton y tabular tenían `nix-us-*` de la config estática de
septiembre; con el catálogo único esos nombres no existen y los tres dejaron de andar.
"""
import re
from pathlib import Path

import pytest

import yaml

ROOT = Path(__file__).resolve().parents[3]

if not (ROOT / "deploy/clients/nix").exists():
    pytest.skip("Despliegue nix de Sentinel (deploy/clients/nix/**): no existe en Eleia, que entrega la extension por S9/S11 (T020, test_extension_delivery.sh) y las variantes -ext (T091, test_ext_images.sh). 057 T017",
                allow_module_level=True)
COMPOSE = yaml.safe_load((ROOT / "deploy/docker/compose.prod.yml").read_text())["services"]
DEPLOY = (ROOT / "deploy/clients/nix/host/deploy.sh").read_text()
GW = "http://backend:8000/api/v1/gw/v1"


def _env(servicio):
    return COMPOSE[servicio]["environment"]


def test_chat_de_los_tres_servicios_pide_auto_por_el_gateway():
    assert _env("anythingllm")["GENERIC_OPEN_AI_MODEL_PREF"].endswith(":-auto}")
    assert _env("tabular")["TABULAR_MODEL"].endswith(":-auto}")
    assert _env("presenton")["CUSTOM_MODEL"].endswith(":-auto}")
    for url in (_env("anythingllm")["GENERIC_OPEN_AI_BASE_PATH"], _env("tabular")["TABULAR_ENGINE_URL"],
                _env("presenton")["CUSTOM_LLM_URL"]):
        assert GW in url and "engine:4000" not in url


def test_el_backend_alcanza_las_redes_internas_de_los_motores():
    redes = COMPOSE["backend"]["networks"]
    assert {"default", "tabular-net", "presentations-net"} <= set(redes)


def test_embeddings_de_anythingllm_son_ollama_local():
    env = _env("anythingllm")
    assert env["EMBEDDING_ENGINE"] == "ollama"
    assert "embeddings:11434" in env["EMBEDDING_BASE_PATH"]
    assert "qwen3-embedding:0.6b" in env["EMBEDDING_MODEL_PREF"]


def test_ningun_alias_fijo_en_el_compose():
    assert "nix-us-" not in (ROOT / "deploy/docker/compose.prod.yml").read_text()


def test_deploy_escribe_siempre_los_modelos_de_servicio_en_instance_env():
    # Lección del #80: lo que el deploy no escribe, un instance.env viejo lo conserva.
    for var in ("ANYTHINGLLM_MODEL", "TABULAR_MODEL", "PRESENTON_MODEL"):
        assert re.search(rf'for\s+\w+\s+in[^\n]*\b{var}\b', DEPLOY), var
    assert re.search(r"=auto\b", DEPLOY)
