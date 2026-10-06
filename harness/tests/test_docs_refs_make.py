"""`make -C deploy docs-refs` no puede dejar `openapi.json` sucio ni a medias, SIN Docker.

Caso real (ensayo 2026-10-06, `ENSAYO-SEPARAR-BASES.md` §6.3 del instalador): con la imagen del
backend sin construir, `docker compose run` la construía por su cuenta y el progreso de
BuildKit salía por **stdout**; el `2>/dev/null` del target no lo captura, así que el
`openapi.json` quedó con 46 líneas de log al principio y nadie lo notó hasta el `git diff`.
Contrato que se fija: (1) la imagen se construye ANTES y su progreso nunca viaja por el stdout
que se vuelve JSON; (2) lo que sale del export se valida como JSON antes de reemplazar el
archivo; (3) cualquier fallo sale con un mensaje que dice qué hacer y deja el archivo intacto.

Se usa un `docker` de mentira (un script en el PATH que registra cómo lo llamaron) y un repo
de juguete: se prueba el cableado del Makefile, no que Docker construya. Vive en `harness/`
porque la raíz del repo no existe dentro del contenedor del backend.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_MAKEFILE_DIR = _REPO / "deploy"
_ORIGINAL = '{"original": true}\n'

_DOCKER_FALSO = """#!/bin/sh
echo "$@" >> "$FAKE_DOCKER_LOG"
case "$1 $2" in
  "compose build")
    # El progreso de BuildKit sale por stderr (y, si algo se filtra, por stdout).
    echo "#1 [internal] load build definition" >&2
    [ "$FAKE_DOCKER_MODE" = "build_falla" ] && { echo "build roto" >&2; exit 1; }
    exit 0 ;;
  "compose run")
    [ "$FAKE_DOCKER_MODE" = "run_falla" ] && { echo "boom" >&2; exit 1; }
    [ "$FAKE_DOCKER_MODE" = "stdout_sucio" ] && echo "#1 [internal] load build definition"
    echo '{"openapi": "3.1.0"}'
    exit 0 ;;
esac
exit 0
"""


@pytest.fixture
def repo_de_juguete(tmp_path):
    refs = tmp_path / "docs" / "docs" / "api-reference"
    refs.mkdir(parents=True)
    (refs / "openapi.json").write_text(_ORIGINAL)
    (tmp_path / "docs" / "gen_config_reference.py").write_text(
        "open('gen_corrio','w').write('si')\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(_DOCKER_FALSO)
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    return tmp_path


def _correr(repo, modo):
    env = dict(os.environ, PATH=f"{repo / 'bin'}:{os.environ['PATH']}",
               FAKE_DOCKER_MODE=modo, FAKE_DOCKER_LOG=str(repo / "docker.log"))
    return subprocess.run(["make", "-C", str(_MAKEFILE_DIR), f"REPO_ROOT={repo}", "docs-refs"],
                          env=env, capture_output=True, text=True, timeout=60)


def _openapi(repo):
    return (repo / "docs" / "docs" / "api-reference" / "openapi.json").read_text()


def _llamadas(repo):
    return (repo / "docker.log").read_text().splitlines()


@pytest.mark.skipif(shutil.which("make") is None, reason="make no está instalado")
class TestDocsRefs:
    def test_camino_feliz_escribe_el_json_y_regenera_la_config(self, repo_de_juguete):
        r = _correr(repo_de_juguete, "ok")
        assert r.returncode == 0, r.stderr
        assert _openapi(repo_de_juguete) == '{"openapi": "3.1.0"}\n'
        assert (repo_de_juguete / "gen_corrio").exists()
        assert not (repo_de_juguete / "docs/docs/api-reference/openapi.json.tmp").exists()

    def test_la_imagen_se_construye_antes_de_exportar(self, repo_de_juguete):
        _correr(repo_de_juguete, "ok")
        llamadas = _llamadas(repo_de_juguete)
        assert llamadas[0].startswith("compose build") and "backend" in llamadas[0]
        assert llamadas[1].startswith("compose run")

    def test_el_progreso_del_build_nunca_llega_al_json(self, repo_de_juguete):
        _correr(repo_de_juguete, "ok")
        assert "load build definition" not in _openapi(repo_de_juguete)

    def test_stdout_con_basura_no_reemplaza_el_archivo(self, repo_de_juguete):
        """Red de seguridad: aunque algo vuelva a colarse por stdout, no se compromete."""
        r = _correr(repo_de_juguete, "stdout_sucio")
        assert r.returncode != 0
        assert _openapi(repo_de_juguete) == _ORIGINAL
        assert "JSON" in r.stderr
        assert not (repo_de_juguete / "docs/docs/api-reference/openapi.json.tmp").exists()
        assert not (repo_de_juguete / "gen_corrio").exists(), \
            "no se regenera la config sobre un export fallido"

    def test_build_roto_falla_con_instrucciones_y_deja_el_archivo(self, repo_de_juguete):
        r = _correr(repo_de_juguete, "build_falla")
        assert r.returncode != 0
        assert _openapi(repo_de_juguete) == _ORIGINAL
        assert "docker compose build backend" in r.stderr
        assert all(not l.startswith("compose run") for l in _llamadas(repo_de_juguete))

    def test_export_roto_falla_con_instrucciones_y_deja_el_archivo(self, repo_de_juguete):
        r = _correr(repo_de_juguete, "run_falla")
        assert r.returncode != 0
        assert _openapi(repo_de_juguete) == _ORIGINAL
        assert "openapi.json" in r.stderr
        assert not (repo_de_juguete / "docs/docs/api-reference/openapi.json.tmp").exists()
