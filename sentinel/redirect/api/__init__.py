"""Routers de la extensión, montados por la costura S1: `PLUGIN_PACKAGES=sentinel.redirect.api`.

Un solo router montado: `us5` (kits, fidelidad, costos) se incluye dentro del de administración,
que es el que ya conocen la costura y sus tests. `on_startup()` lo llama S16 al arrancar (siembra de seeds)."""
_combined = False


def on_startup():
    """Enganche de arranque de la costura S16 de la base (`src.plugins.run_plugin_startup`): carga al arrancar, antes
    de servir, las regiones y reglas de habilitación de `REDIRECT_SEED_FILES`. Sin la variable no hace nada."""
    from .. import seed_on_startup
    return seed_on_startup.on_startup()


def get_routers():
    global _combined
    from .admin import router
    if not _combined:
        from .us5 import router as us5_router
        router.include_router(us5_router)
        _combined = True
    return [(router, "/api/v1")]
