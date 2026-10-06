"""Routers de la extensión, montados por la costura S1: `PLUGIN_PACKAGES=sentinel.redirect.api`.

Un solo router montado: `us5` (kits, fidelidad, costos) se incluye dentro del de administración,
que es el que ya conocen la costura y sus tests."""
_combined = False


def get_routers():
    global _combined
    from .admin import router
    if not _combined:
        from .us5 import router as us5_router
        router.include_router(us5_router)
        _combined = True
    return [(router, "/api/v1")]
