"""El chat de la consola sirve los modelos del catálogo (069 T144; FR-040, FR-041; research D2, D26).

La base (`backend/src/services/model_route_hook.py`) consulta a esta extensión justo antes de armar el
pedido al motor. Si el `public_id` es del catálogo servido de la organización, el chat habla con la
familia comodín `rdx-<familia>/<modelo real>` y firma la autorización interna con la credencial
(descifrada acá y re-cifrada dentro de la firma; las referencias `env:` viajan como referencia), la
base y el precio de la entrada: el mismo contrato que usa la pasarela (`RedirectPlugin.pre_engine`).

Reglas:
- lo que el catálogo no conoce (los modelos del archivo de config del motor), lo inactivo/archivado y
  lo que no tiene credencial vigente **no se toca**: `route` devuelve `None` y el chat sigue por el
  camino de siempre. El catálogo servido (`internal.build`) ya omite lo inactivo y lo sin credencial;
- si el modelo ES del catálogo y no se puede firmar o descifrar su credencial: **fail-closed**
  (`ModelRouteUnavailable` ⇒ el chat responde 503), nunca se cae en silencio al camino viejo;
- el acceso por perfil y la residencia ya se aplicaron antes (`access_hook`, `residency_heuristic`).

`register_chat_route()` lo invoca el montaje de rutas de la extensión. Inyectables para tests:
`CATALOG` (`fn(tenant) -> {public_id: entrada}`) y `CREDENTIAL` (`fn(tenant, entry_id) -> dict`).
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from sentinel.redirect import authz
from sentinel.redirect import credentials as rc

logger = logging.getLogger("sentinel.catalog.chat_route")

CATALOG = None        # fn(tenant) -> {public_id: entrada servida}
CREDENTIAL = None     # fn(tenant, entry_id) -> dict de credencial descifrada (o `env:`)
CHAT_ROLE = "text"    # el chat de la consola conversa; el resto de los tipos no se ofrece acá
NOT_AVAILABLE = "Modelo no disponible temporalmente."


def _entries(tenant: str) -> dict:
    if CATALOG is not None:
        return CATALOG(tenant)
    from sentinel.catalog.api import internal
    return internal.build(tenant).get("entries") or {}


def _credential(tenant: str, entry_id: str) -> dict:
    if CREDENTIAL is not None:
        return CREDENTIAL(tenant, entry_id)
    # misma resolución, mismo filtro de servido y misma clave de cifrado que el canal interno del guard
    from fastapi import Response
    from sentinel.catalog.api import internal
    return internal.model_credential(Response(), tenant=uuid.UUID(tenant), entry_id=uuid.UUID(entry_id))["credential"]


def _per_mtok(price) -> Optional[dict]:
    return rc.price_per_mtok(price)                # una única fuente de precios (FR-049)


def _tenant_of(tenant_id) -> Optional[str]:
    return str(tenant_id) if tenant_id else None


def route(tenant_id, user, model: str):
    """`RoutedModel` si `model` es un `public_id` servido del catálogo de la organización; si no, `None`."""
    from src.services.model_route_hook import ModelRouteUnavailable, RoutedModel
    tenant = _tenant_of(tenant_id)
    if tenant is None or not isinstance(model, str) or not model:
        return None
    try:
        entry = _entries(tenant).get(model)
    except Exception:  # noqa: BLE001 — sin catálogo no se sabe si es suyo: camino de siempre
        logger.warning("chat: catálogo no disponible; el modelo sigue por el archivo de config")
        return None
    if not isinstance(entry, dict) or entry.get("role", CHAT_ROLE) != CHAT_ROLE:
        return None
    try:
        provider, real = entry["provider"], entry["real_model"]
        engine_model = rc.family_model(provider, real)
        cred = _credential(tenant, str(entry["entry_id"]))
        user_id = getattr(user, "id", None)
        scope = f"{tenant}/user:{user_id}" if user_id else f"{tenant}/tenant:*"
        token = authz.issue(
            request_id=str(uuid.uuid4()), scope=scope, destination_id=str(entry["entry_id"]),
            model=engine_model, provider=provider, credential=cred, api_base=entry.get("api_base"),
            forced_masking=False,
            decision={"source": "catalog_chat", "public_id": model, "face": "chat_ui",
                      "semaforo": (entry.get("semaforo") or {}).get("estado") or "unclassified"},
            price=_per_mtok(entry.get("price")),
            # la consola fija `temperature` en el pedido (base): el guard quita lo que la ficha no soporta
            drop_params=entry.get("unsupported_params") or None)
    except Exception as exc:  # noqa: BLE001 — fail-closed, sin texto que pueda traer secretos
        logger.error("chat: no se pudo preparar el modelo del catálogo %s (%s)", model, type(exc).__name__)
        raise ModelRouteUnavailable(NOT_AVAILABLE) from None
    return RoutedModel(engine_model=engine_model, headers={authz.HEADER: token},
                       unsupported_params=tuple(entry.get("unsupported_params") or ()))


def list_models(tenant_id) -> list:
    """Modelos del catálogo conversables en la organización, con la forma de `/chat/models`."""
    tenant = _tenant_of(tenant_id)
    if tenant is None:
        return []
    out = []
    for public_id, e in sorted(_entries(tenant).items()):
        if e.get("role", CHAT_ROLE) != CHAT_ROLE:
            continue
        out.append({"model_name": public_id, "provider": e.get("provider"), "model_id": e.get("real_model"),
                    "api_base": e.get("api_base"), "is_configured": True,
                    "is_eu_compliant": (e.get("semaforo") or {}).get("estado") == "eu_ok"})
    return out


def register_chat_route() -> None:
    """Conecta la extensión a la costura de la base. Idempotente."""
    from src.services import model_route_hook
    model_route_hook.register_model_router(route)
    model_route_hook.register_model_lister(list_models)
