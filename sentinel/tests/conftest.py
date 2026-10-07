import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# Las extensiones del motor de la base (`extensions.sentinel_guardian_policy`, costura S7): el
# guard las usa para marcar la decisión de ruteo como confiable, igual que dentro del motor.
_ENGINE = os.path.join(_ROOT, "litellm")
if os.path.isdir(os.path.join(_ENGINE, "extensions")) and _ENGINE not in sys.path:
    sys.path.insert(1, _ENGINE)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _region_de_la_instalacion(monkeypatch):
    """Perfil `eu`, el de los tests heredados de la 068 (057 R28: el código ya no cae a `eu` si falta la variable,
    así que los tests lo fijan; los que prueban «sin región» la borran con `delenv`)."""
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "eu")


@pytest.fixture(autouse=True)
def _puente_de_acceso_apagado():
    """Montar las rutas del catálogo registra el puente de acceso (estado global): ningún test lo hereda."""
    yield
    try:
        from sentinel.access import bridge
        bridge.reset()
    except ImportError:
        pass
    try:                                    # ni el ruteo ni el listado del chat (estado global de la base)
        from src.services import model_route_hook
        model_route_hook.register_model_router(None)
        model_route_hook.register_model_lister(None)
    except ImportError:
        pass
