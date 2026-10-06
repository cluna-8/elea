"""Cableado de la capa de ORIGEN del plano interno (`INTERNAL_ALLOWED_CIDRS`), SIN Docker.

El código (`backend/src/api/internal.py`) lee la variable en cada pedido; que valga algo en un
stack real depende de que los DOS compose se la pasen al servicio `backend` con `auto` por
defecto, y de que `.env.example` la documente (de ahí sale la referencia de configuración).
Se prueba el cableado, no el efecto: el efecto está en `backend/tests/unit/test_internal_origen_cidr.py`.
Vive en `harness/` porque la raíz del repo no existe dentro del contenedor del backend."""
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
_COMPOSES = {"dev": _REPO / "docker-compose.yml",
             "prod": _REPO / "deploy" / "docker" / "compose.prod.yml"}


def _env_backend(ruta: Path) -> dict:
    env = yaml.safe_load(ruta.read_text())["services"]["backend"]["environment"]
    if isinstance(env, dict):
        return {k: str(v) for k, v in env.items()}
    return {i.partition("=")[0]: i.partition("=")[2] for i in env}


def test_los_dos_compose_fijan_auto_en_el_backend():
    for nombre, ruta in _COMPOSES.items():
        valor = _env_backend(ruta).get("INTERNAL_ALLOWED_CIDRS")
        assert valor == "${INTERNAL_ALLOWED_CIDRS-auto}", (nombre, valor)


def test_el_default_es_auto_pero_un_valor_vacio_del_operador_se_respeta():
    """`${V-auto}` (sin dos puntos) solo cae a `auto` si la variable NO está definida: el
    operador que la deja vacía a propósito (desactivar el chequeo) no se pisa en silencio."""
    for ruta in _COMPOSES.values():
        assert "${INTERNAL_ALLOWED_CIDRS:-" not in ruta.read_text()


def test_env_example_la_documenta_con_su_descripcion():
    lineas = (_REPO / ".env.example").read_text().splitlines()
    idx = next(i for i, l in enumerate(lineas) if l.startswith("INTERNAL_ALLOWED_CIDRS="))
    assert lineas[idx] == "INTERNAL_ALLOWED_CIDRS=auto"
    # La referencia de configuración toma la descripción del comentario inmediato de arriba.
    assert lineas[idx - 1].startswith("# ") and "CIDR" in lineas[idx - 1]


def test_el_router_interno_declara_la_capa_y_los_compose_no_publican_el_plano():
    src = (_REPO / "backend" / "src" / "api" / "internal.py").read_text()
    assert 'dependencies=[Depends(_require_internal_origen)]' in src
    assert '"INTERNAL_ALLOWED_CIDRS"' in src
