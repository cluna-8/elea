"""Punto de extensión de la pasarela ``/gw``: plugins con hooks opcionales.

Por qué existe: los despliegues que construyen SOBRE esta base necesitan decidir cosas
dentro del camino de ``/gw`` —cortar un pedido por una regla propia, reescribir el body que
va al destino, filtrar el catálogo de ``/v1/models``, traducir un error del upstream— y la
única forma que tenían era parchear ``gateway.py``, o sea un fork que diverge en cada merge.
Este módulo es la costura: un registro de objetos con hooks, llamados en orden de registro.

**Contrato de identidad (la propiedad que más importa):** sin ningún plugin registrado el
comportamiento de la pasarela es byte a byte el de siempre — mismos pedidos al motor y al
upstream, mismas respuestas, mismos headers, misma fila de auditoría. Cada call-site de
``gateway.py`` pregunta ``active()`` y, si es ``False``, ni construye el ``GatewayContext``.

Hooks (todos opcionales; un plugin implementa sólo los que necesita, sync o async):

* ``pre_request(ctx) -> None | Response``: el primero que devuelve una ``Response`` gana.
* ``pre_engine(ctx, body, headers) -> (body, headers)``: antes de mandar al destino.
* ``wrap_stream(ctx, iterator) -> iterator``: envuelve los bytes del streaming.
* ``models_filter(ctx, listing) -> listing``: sobre la respuesta de ``/v1/models``.
* ``map_error(ctx, status, body) -> (status, body, headers) | None``: el primero no-None gana.
* ``map_response(ctx, status, content) -> (status, content, headers) | None``: igual que
  ``map_error`` pero para la respuesta NO-stream exitosa (< 400) de ``/v1/messages``.
* ``forward_headers_allowlist(ctx) -> set[str]``: headers extra a reenviar en byok.
* ``post_mask(ctx, report) -> None | Response``: después del enmascarado del gateway.

Carga: ``register_gateway_plugin(obj)`` desde código, o ``GATEWAY_PLUGINS`` con una lista
de módulos importables separada por comas; cada módulo expone ``gateway_plugin``.
"""
import importlib
import inspect
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

# El nombre se lee con el literal en `_load_from_env` (el gate de deriva doc↔código solo ve
# literales); esta constante es la que usan los tests.
PLUGINS_ENV = "GATEWAY_PLUGINS"
# Estado con el que se audita un corte decidido por un plugin. Es un literal YA inventariado
# en el clasificador de retención (seguridad, bloqueo por política): inventar uno nuevo acá
# dejaría filas sin plazo decidido.
STATUS_PLUGIN_BLOCK = "blocked_by_policy"

_registry: list = []
_env_loaded = {"hecho": False}


@dataclass
class GatewayContext:
    """Lo que un plugin ve de ESTE pedido. ``state`` es del plugin (para pasar datos entre
    sus propios hooks); ``governance_overrides`` y ``routing_decision`` son las dos ranuras
    que la pasarela LEE de vuelta (ver ``gateway.py``)."""
    route: str
    mode: str  # "byok" | "subscription"
    request_headers: Mapping[str, str]
    ident: dict = field(default_factory=dict)
    model: Optional[str] = None
    state: dict = field(default_factory=dict)
    governance_overrides: dict = field(default_factory=dict)
    routing_decision: Optional[dict] = None


def register_gateway_plugin(plugin: Any) -> None:
    """Registra un plugin (idempotente por identidad: registrarlo dos veces no duplica hooks)."""
    if plugin not in _registry:
        _registry.append(plugin)


def clear_gateway_plugins() -> None:
    """Vacía el registro y re-habilita la carga desde env (tests y recarga en caliente)."""
    _registry.clear()
    _env_loaded["hecho"] = False


def _load_from_env() -> None:
    """Importa los módulos de ``GATEWAY_PLUGINS`` una vez. Un módulo que no importa o no
    expone ``gateway_plugin`` LEVANTA, y se reintenta en el pedido siguiente: si el operador
    configuró un plugin, servir sin él sería saltarse en silencio una regla que pidió —
    mejor un 500 ruidoso que un pedido que pasa sin la política que se creía activa."""
    if _env_loaded["hecho"]:
        return
    for nombre in filter(None, (m.strip() for m in os.getenv("GATEWAY_PLUGINS", "").split(","))):
        register_gateway_plugin(importlib.import_module(nombre).gateway_plugin)
    _env_loaded["hecho"] = True


def plugins() -> tuple:
    _load_from_env()
    return tuple(_registry)


def active() -> bool:
    return bool(plugins())


async def _call(fn, *args):
    out = fn(*args)
    return await out if inspect.isawaitable(out) else out


def _hooks(nombre: str):
    return [h for h in (getattr(p, nombre, None) for p in plugins()) if callable(h)]


async def run_pre_request(ctx: GatewayContext):
    for hook in _hooks("pre_request"):
        resp = await _call(hook, ctx)
        if resp is not None:
            return resp
    return None


async def run_pre_engine(ctx: GatewayContext, body: dict, headers: dict):
    for hook in _hooks("pre_engine"):
        body, headers = await _call(hook, ctx, body, headers)
    return body, headers


async def run_post_mask(ctx: GatewayContext, report: dict):
    for hook in _hooks("post_mask"):
        resp = await _call(hook, ctx, report)
        if resp is not None:
            return resp
    return None


async def run_models_filter(ctx: GatewayContext, listing: dict) -> dict:
    for hook in _hooks("models_filter"):
        listing = await _call(hook, ctx, listing)
    return listing


async def run_map_error(ctx: GatewayContext, status: int, body: bytes):
    for hook in _hooks("map_error"):
        mapped = await _call(hook, ctx, status, body)
        if mapped is not None:
            return mapped
    return None


async def run_map_response(ctx: GatewayContext, status: int, content: bytes):
    for hook in _hooks("map_response"):
        mapped = await _call(hook, ctx, status, content)
        if mapped is not None:
            return mapped
    return None


def wrap_stream(ctx: GatewayContext, iterator):
    for hook in _hooks("wrap_stream"):
        iterator = hook(ctx, iterator)
    return iterator


def forward_headers_allowlist(ctx: GatewayContext) -> set:
    """Unión en minúsculas. Los headers de control de la pasarela y los hop-by-hop los
    filtra el caller igual: un plugin puede AGREGAR headers al reenvío, no reabrir esos."""
    out: set = set()
    for hook in _hooks("forward_headers_allowlist"):
        out |= {h.lower() for h in (hook(ctx) or ())}
    return out


def routing_of(ctx: Optional[GatewayContext]) -> Optional[dict]:
    """``routing_decision`` para ``_audit``; ``None`` sin contexto (sin plugins)."""
    return ctx.routing_decision if ctx is not None else None
