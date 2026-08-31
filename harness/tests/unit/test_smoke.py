"""Smoke test del scaffold: el paquete del harness importa y la estructura existe.

Los tests reales del instrumento (evaluador de SLO, detector de canarios, generador
de corpus, comparador) llegan con sus bloques respectivos. Este archivo solo asegura
que el job `harness-tests` de CI tenga algo verde que correr desde el scaffold.
"""
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[2]


def test_paquete_importa():
    import sentinel_harness  # noqa: F401 — el paquete raíz se instala vía pyproject


def test_estructura_del_modulo_existe():
    # Solo se verifican los directorios con contenido trackeado desde el scaffold. Los
    # demás (gates/, scenarios/, infra/…) se pueblan en bloques posteriores y git no
    # trackea directorios vacíos — asertarlos acá rompería la CI de las ramas intermedias.
    for sub in ("src", "tests"):
        assert (HARNESS_ROOT / sub).is_dir(), f"falta harness/{sub}"
    assert (HARNESS_ROOT / "pyproject.toml").is_file(), "falta harness/pyproject.toml"
