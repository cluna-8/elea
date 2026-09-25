"""Autodiscovery de routers de plugins (seam de extensión).

Un paquete externo agrega endpoints al gateway SIN editar `main.py`:

    PLUGIN_PACKAGES=mi_plugin,otro.plugin     # módulos importables, separados por coma

Cada módulo expone:

    def get_routers() -> list[tuple[APIRouter, str]]:   # (router, prefix)
        return [(router, "/api/v1/mi-plugin")]

Decisiones:
- Sin la env (o vacía) no se importa nada: rutas y OpenAPI idénticos al core.
- Fail-LOUD: un módulo que no importa, sin `get_routers` o que devuelve otra forma levanta
  `PluginLoadError` y el arranque se cae. Un plugin configurado y ausente es un error de
  despliegue; arrancar sin él serviría una API distinta a la que el operador pidió.
- Todo o nada: se validan TODOS los plugins antes de montar el primero.
- Se montan después de los routers del core, en el orden de la env.
"""
from __future__ import annotations

import importlib
import logging
import os

from fastapi import APIRouter, FastAPI

logger = logging.getLogger("sentinel-secure-gateway.plugins")


class PluginLoadError(RuntimeError):
    """Un plugin declarado en PLUGIN_PACKAGES no cumple el contrato."""


def plugin_packages(raw: str | None = None) -> list[str]:
    """Nombres de módulo declarados (env por default), sin vacíos ni espacios."""
    if raw is None:
        raw = os.getenv("PLUGIN_PACKAGES", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def _routers_de(nombre: str) -> list[tuple[APIRouter, str]]:
    try:
        mod = importlib.import_module(nombre)
    except Exception as e:
        raise PluginLoadError(f"plugin '{nombre}': no se pudo importar: {e}") from e
    get_routers = getattr(mod, "get_routers", None)
    if not callable(get_routers):
        raise PluginLoadError(f"plugin '{nombre}': no expone get_routers()")
    try:
        declarados = get_routers()
    except Exception as e:
        raise PluginLoadError(f"plugin '{nombre}': get_routers() falló: {e}") from e
    if not isinstance(declarados, (list, tuple)):
        raise PluginLoadError(f"plugin '{nombre}': get_routers() debe devolver una lista")
    routers: list[tuple[APIRouter, str]] = []
    for item in declarados:
        if not (
            isinstance(item, tuple) and len(item) == 2
            and isinstance(item[0], APIRouter) and isinstance(item[1], str)
        ):
            raise PluginLoadError(
                f"plugin '{nombre}': cada elemento debe ser (APIRouter, prefix: str), vino {item!r}"
            )
        routers.append(item)
    return routers


def load_plugin_routers(raw: str | None = None) -> list[tuple[APIRouter, str]]:
    """Importa y valida todos los plugins; levanta PluginLoadError al primer fallo."""
    routers: list[tuple[APIRouter, str]] = []
    for nombre in plugin_packages(raw):
        try:
            routers.extend(_routers_de(nombre))
        except PluginLoadError as e:
            logger.error("%s", e)
            raise
    return routers


def mount_plugin_routers(app: FastAPI, raw: str | None = None) -> int:
    """Monta los routers de los plugins declarados. Devuelve cuántos montó."""
    routers = load_plugin_routers(raw)
    for router, prefix in routers:
        app.include_router(router, prefix=prefix)
    if routers:
        logger.info("Plugins montados: %s (%d routers)", ", ".join(plugin_packages(raw)), len(routers))
    return len(routers)
