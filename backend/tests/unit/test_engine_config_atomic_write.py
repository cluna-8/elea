"""Escritura ATÓMICA del `config.yaml` del motor (issue #50).

El bug: los cuatro endpoints que editan el catálogo escribían con `open(path, "w")`,
que TRUNCA el fichero antes de volcar el contenido nuevo. Un proceso que muriera —o
un reinicio— en esa ventana dejaba al motor arrancando con un YAML cortado: catálogo
vacío en la instalación del cliente.

Todos PUROS: sin Postgres ni motor. Los endpoints se llaman como corrutinas normales
(el RBAC vive en `dependencies=[...]` del decorador, o sea en el router, no en la
firma), así que lo único que se ejercita es el camino de lectura → mutación → guardado.
"""
import asyncio
import os
import stat
from pathlib import Path

import pytest
import yaml

from src.api import chat
from src.services.atomic_file import escribir_atomico

# Catálogo de partida: un modelo local del cliente y uno de nube, que es la forma
# mínima donde el alta automática de respaldo (030 US3) tiene algo que hacer.
_CATALOGO = {
    "model_list": [
        {"model_name": "local-qwen", "litellm_params": {"model": "ollama/qwen3:4b"}},
        {"model_name": "nube-gpt", "litellm_params": {"model": "openai/gpt-4o"}},
    ],
    "router_settings": {"disable_cooldowns": True},
}


@pytest.fixture
def catalogo(tmp_path, monkeypatch):
    """`config.yaml` de mentira + el plano chat apuntando ahí.

    Sin esto los tests reescribirían el `litellm/config.yaml` del repo, que en dev
    está montado dentro del contenedor del motor.
    """
    destino = tmp_path / "config.yaml"
    destino.write_text(yaml.safe_dump(_CATALOGO, default_flow_style=False), encoding="utf-8")
    os.chmod(destino, 0o664)  # los permisos que deja el install en el volumen
    monkeypatch.setattr(chat, "_get_config_path", lambda: str(destino))
    return destino


def _volcado_que_muere(datos, f, **kwargs):
    """Volcado que escribe a medias y revienta: el fallo que el bug no sobrevivía."""
    f.write("model_list:\n- model_name: a-medio-escri")
    raise RuntimeError("el proceso murió a mitad del volcado")


# Los CUATRO escritores del catálogo. Se listan como llamadas para que agregar un
# endpoint nuevo que escriba el config sin pasar por el helper rompa acá.
_ESCRITORES = [
    ("alta", lambda: chat.register_model(chat.ModelCreateSchema(
        model_name="nube-nueva", provider="openai", model_id="gpt-4o-mini"))),
    ("baja", lambda: chat.delete_model("nube-gpt")),
    ("credenciales", lambda: chat.update_model_credential(
        "nube-gpt", chat.ModelCredentialSchema(litellm_params={"api_key": "sk-nueva"}))),
    ("respaldo", lambda: chat.set_fallback(
        "nube-gpt", chat.FallbackBody(fallback_model="local-qwen"))),
]


# --------------------------------------------------------------------------- #
# El helper compartido (`atomic_file.escribir_atomico`)
# --------------------------------------------------------------------------- #

def test_el_guardado_pasa_por_un_temporal_del_mismo_dir_y_un_replace(tmp_path, monkeypatch):
    destino = tmp_path / "config.yaml"
    destino.write_text("viejo: 1\n", encoding="utf-8")
    visto = []
    replace_real = os.replace

    def espia(src, dst):
        # En el instante del `replace` el destino TODAVÍA tiene el contenido viejo
        # (el nuevo vive en el temporal): eso es exactamente la atomicidad. Y el
        # temporal está en el MISMO directorio, sin lo cual `replace` no es atómico.
        visto.append((Path(src).parent == Path(dst).parent, Path(dst).read_text()))
        return replace_real(src, dst)

    monkeypatch.setattr(os, "replace", espia)
    escribir_atomico(str(destino), lambda f: f.write("nuevo: 2\n"))

    assert visto == [(True, "viejo: 1\n")]
    assert destino.read_text() == "nuevo: 2\n"
    assert [p.name for p in tmp_path.iterdir()] == ["config.yaml"]


def test_un_fallo_a_mitad_deja_el_fichero_anterior_intacto(tmp_path):
    destino = tmp_path / "config.yaml"
    destino.write_text("viejo: 1\n", encoding="utf-8")

    def volcar(f):
        f.write("nuevo a med")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        escribir_atomico(str(destino), volcar)

    assert destino.read_text() == "viejo: 1\n"
    # Y sin temporales huérfanos: se acumularían en el mismo volumen que lee el motor.
    assert [p.name for p in tmp_path.iterdir()] == ["config.yaml"]


def test_conserva_los_permisos_del_fichero_que_ya_existia(tmp_path):
    destino = tmp_path / "config.yaml"
    destino.write_text("viejo: 1\n", encoding="utf-8")
    os.chmod(destino, 0o664)

    escribir_atomico(str(destino), lambda f: f.write("nuevo: 2\n"))

    # 664 es lo que el install deja en el volumen para que el motor —otro UID— lea.
    # `mkstemp` crea 0600: sin conservar el modo, el motor quedaría sin catálogo igual.
    assert stat.S_IMODE(destino.stat().st_mode) == 0o664


def test_al_crearlo_lo_deja_legible_para_el_motor(tmp_path):
    destino = tmp_path / "sub" / "config.yaml"

    escribir_atomico(str(destino), lambda f: f.write("a: 1\n"))

    assert stat.S_IMODE(destino.stat().st_mode) == 0o664


# --------------------------------------------------------------------------- #
# Los cuatro escritores del catálogo del motor
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("nombre,llamada", _ESCRITORES, ids=[n for n, _ in _ESCRITORES])
def test_cada_escritor_deja_un_yaml_completo(catalogo, nombre, llamada):
    asyncio.run(llamada())

    guardado = yaml.safe_load(catalogo.read_text(encoding="utf-8"))
    assert guardado.get("model_list"), "el catálogo no puede quedar vacío"
    assert stat.S_IMODE(catalogo.stat().st_mode) == 0o664
    assert [p.name for p in catalogo.parent.iterdir()] == ["config.yaml"]


@pytest.mark.parametrize("nombre,llamada", _ESCRITORES, ids=[n for n, _ in _ESCRITORES])
def test_si_el_guardado_muere_a_mitad_el_catalogo_sobrevive(catalogo, monkeypatch,
                                                            nombre, llamada):
    monkeypatch.setattr(chat.yaml, "safe_dump", _volcado_que_muere)

    with pytest.raises(chat.HTTPException) as exc:
        asyncio.run(llamada())
    assert exc.value.status_code == 500

    # Lo que se vende: el motor reinicia y encuentra el catálogo de antes, entero.
    monkeypatch.undo()
    assert yaml.safe_load(catalogo.read_text(encoding="utf-8")) == _CATALOGO
    assert [p.name for p in catalogo.parent.iterdir()] == ["config.yaml"]
