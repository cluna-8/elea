"""El despliegue de `router-embeddings` sale de ROUTER_EMBEDDINGS_DEPLOYMENT (fix-embeddings-deployment).

Contexto: el nombre de DESPLIEGUE de Azure lo elige quien crea el recurso; el recurso de Elea tiene
`text-embedding-3-large-azure-openai`, no el `text-embedding-3-large` que el catálogo traía fijo. LiteLLM
solo resuelve `os.environ/X` como valor COMPLETO de una clave de `litellm_params` (no interpola dentro de
`azure/...`), y si X no existe devuelve None. Por eso la config lee `ROUTER_EMBEDDINGS_MODEL` y el
arranque del motor (`litellm/entrypoint.sh`) la deriva de ROUTER_EMBEDDINGS_DEPLOYMENT con default.

Sin Docker: se lee el YAML y se corre el script con un `litellm` falso en el PATH.
"""
import os
import stat
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
LITELLM = ROOT / "litellm"
ENTRYPOINT = LITELLM / "entrypoint.sh"
CONFIG = yaml.safe_load((LITELLM / "config.yaml").read_text(encoding="utf-8"))
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
DEFAULT = "text-embedding-3-large"


def _entrada(nombre):
    return next(m for m in CONFIG["model_list"] if m["model_name"] == nombre)


def _arrancar(tmp_path, **env_extra):
    """Corre el entrypoint con un `litellm` falso que imprime sus args y el modelo resuelto."""
    falso = tmp_path / "litellm"
    falso.write_text('#!/bin/sh\necho "ARGS $*"\necho "MODEL ${ROUTER_EMBEDDINGS_MODEL-<sin definir>}"\n')
    falso.chmod(falso.stat().st_mode | stat.S_IXUSR)
    env = {k: v for k, v in os.environ.items() if not k.startswith("ROUTER_EMBEDDINGS")}
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    env.update(env_extra)
    out = subprocess.run(["sh", str(ENTRYPOINT), "--config", "/app/config.yaml"],
                         env=env, capture_output=True, text=True, check=True).stdout
    return dict(linea.split(" ", 1) for linea in out.strip().splitlines())


# ── la config ───────────────────────────────────────────────────────────────────────────────────────

def test_router_embeddings_toma_el_modelo_del_entorno():
    params = _entrada("router-embeddings")["litellm_params"]
    assert params["model"] == "os.environ/ROUTER_EMBEDDINGS_MODEL"
    # lo demás de la entrada no cambia: mismo recurso Azure, embedding gratis para el tenant
    assert params["api_base"] == "os.environ/AZURE_API_BASE"
    assert params["api_key"] == "os.environ/AZURE_API_KEY"
    assert _entrada("router-embeddings")["model_info"]["mode"] == "embedding"


def test_los_modelos_conversables_heredados_no_cambian():
    """Mismo riesgo de nombre de despliegue (anotado en el comentario de config.yaml), pero NO se tocan:
    el alcance de este fix es el de embeddings."""
    modelos = {m["model_name"]: m["litellm_params"]["model"] for m in CONFIG["model_list"]}
    assert modelos["azure-gpt-4o-mini"] == "azure/gpt-4o-mini"
    assert modelos["azure-gpt-5.1-chat"] == "azure/gpt-5.1-chat"
    assert modelos["azure-gpt-5.4-mini"] == "azure/gpt-5.4-mini"


# ── el arranque deriva el modelo, con default retrocompatible ───────────────────────────────────────

def test_sin_variable_el_despliegue_es_el_de_siempre(tmp_path):
    res = _arrancar(tmp_path)
    assert res["MODEL"] == f"azure/{DEFAULT}"
    assert res["ARGS"] == "--config /app/config.yaml"      # los args del motor pasan intactos


def test_variable_vacia_cae_al_default(tmp_path):
    """compose pasa `ROUTER_EMBEDDINGS_DEPLOYMENT=` vacío cuando el .env no la define."""
    assert _arrancar(tmp_path, ROUTER_EMBEDDINGS_DEPLOYMENT="")["MODEL"] == f"azure/{DEFAULT}"


def test_variable_definida_manda(tmp_path):
    res = _arrancar(tmp_path, ROUTER_EMBEDDINGS_DEPLOYMENT="text-embedding-3-large-azure-openai")
    assert res["MODEL"] == "azure/text-embedding-3-large-azure-openai"


# ── el cableado: imagen y desarrollo usan el arranque ───────────────────────────────────────────────

def test_el_script_es_ejecutable_y_sin_secretos():
    assert ENTRYPOINT.stat().st_mode & stat.S_IXUSR, "git debe guardarlo con modo 755"
    texto = ENTRYPOINT.read_text(encoding="utf-8")
    assert "exec litellm" in texto, "tiene que ser exec: litellm queda como PID 1 y recibe las señales"


def test_la_imagen_arranca_por_el_script():
    dockerfile = (LITELLM / "Dockerfile").read_text(encoding="utf-8")
    assert "/app/entrypoint.sh" in dockerfile
    assert 'ENTRYPOINT ["/app/entrypoint.sh", "--config", "/app/config.yaml"]' in dockerfile
    assert "COPY --chmod=755 entrypoint.sh /app/entrypoint.sh" in dockerfile


def test_el_desarrollo_arranca_por_el_script_y_pasa_la_variable():
    engine = COMPOSE["services"]["engine"]
    assert engine["entrypoint"] == ["/app/entrypoint.sh", "--config", "/app/config.yaml"]
    assert "./litellm/entrypoint.sh:/app/entrypoint.sh:ro" in engine["volumes"]
    assert f"ROUTER_EMBEDDINGS_DEPLOYMENT=${{ROUTER_EMBEDDINGS_DEPLOYMENT:-{DEFAULT}}}" in engine["environment"]
