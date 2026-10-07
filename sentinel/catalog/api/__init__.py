"""Routers del catálogo, montados por la costura S1: `PLUGIN_PACKAGES=sentinel.catalog.api`."""


def _register_residency_resolver():
    """La residencia de proyectos de la base decide con el semáforo del catálogo (069 FR-006). La base
    no importa la extensión: la extensión se registra al montarse."""
    try:
        from src.services import residency_heuristic
    except ImportError:          # fuera del backend (tests de lógica pura)
        return
    from .internal import semaforo_for
    residency_heuristic.register_semaforo_resolver(semaforo_for)


def _register_access_hooks():
    """El chat de la consola decide los modelos permitidos con los perfiles de acceso (069 US2; ADAPT-027).
    La base no importa la extensión: la extensión registra su verificador al montarse."""
    try:
        from sentinel.access import bridge
        bridge.register_hooks()
    except ImportError:          # fuera del backend (tests de lógica pura)
        return


def _register_chat_route():
    """El chat de la consola sirve los modelos del catálogo por la autorización firmada (069 US7; ADAPT-028)."""
    try:
        from sentinel.catalog import chat_route
        chat_route.register_chat_route()
    except ImportError:          # fuera del backend (tests de lógica pura)
        return


def get_routers():
    from .admin import router
    from .internal import router as internal_router
    from .legacy import router as legacy_router
    from .reference import router as reference_router
    from .usage import router as usage_router
    from sentinel.access.api.admin import router as access_router
    _register_residency_resolver()
    _register_access_hooks()
    _register_chat_route()
    return [(router, "/api/v1"), (internal_router, "/api/v1"), (reference_router, "/api/v1"),
            (usage_router, "/api/v1"), (legacy_router, "/api/v1"),
            (access_router, "/api/v1")]
