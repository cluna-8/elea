"""Clientes que hablan directo con el motor sirven del catálogo (069 T033; research D2, spike S1 e).

Hub, tabular y presentaciones piden un **id público** del catálogo (no pasan por la pasarela, así que
no traen autorización firmada). El guard consulta al backend por el canal interno (mismo secreto y
misma red que la identidad), reescribe el pedido a la familia comodín `rdx-<familia>/<modelo real>` y
fija credencial, base y precio de la entrada — el motor no registra el modelo, así que un alta de la
consola se ve en segundos sin reiniciar nada.

Reglas de seguridad:
- **apagado por defecto**: solo actúa si el backend dice `direct: true` (`CATALOG_DIRECT_ENABLED`);
- anti-desvío: se borran credencial/base/precio que mande el cliente;
- **fail-closed** si la entrada existe pero su credencial no se obtiene (503, sin texto del backend);
- catálogo inalcanzable ⇒ no se toca el pedido (lo que ya funcionaba por el archivo de config sigue);
- la credencial no se loguea ni se escribe en la decisión de auditoría.

Importa sus hermanos desde el paquete o copiado plano (S9), como `redirect_guard`.
"""
from __future__ import annotations

import os
import time
from typing import Any, Awaitable, Callable, Mapping, Optional

try:
    from sentinel.engine import redirect_credentials as credentials
    from sentinel.engine import redirect_guard as _guard
except ImportError:
    try:
        from . import redirect_credentials as credentials  # type: ignore[no-redef]
        from . import redirect_guard as _guard  # type: ignore[no-redef]
    except ImportError:
        import redirect_credentials as credentials  # type: ignore[no-redef]
        import redirect_guard as _guard  # type: ignore[no-redef]

Fetch = Callable[[str, Mapping[str, str]], Awaitable[tuple]]
DEFAULT_TTL = 5.0
# Tipo de llamada del motor → tipo de modelo que exige (FR-060, US11). Una llamada que no figura acá
# (o sin `call_type`) se asume de texto: no cambia nada de lo que ya andaba.
CALL_TYPE_ROLE = {
    **dict.fromkeys(("acompletion", "completion", "anthropic_messages", "aresponses", "responses",
                     "atext_completion"), "text"),
    **dict.fromkeys(("aembedding", "embedding"), "embeddings"),
    **dict.fromkeys(("aimage_generation", "image_generation", "aimage_edit"), "image"),
    **dict.fromkeys(("atranscription", "transcription", "aspeech", "speech"), "audio"),
    **dict.fromkeys(("arerank", "rerank"), "rerank"),
}
# De `limits` solo estos dos viajan al motor por pedido; rpm/tpm/max_parallel_requests son informativos
# (no hay deployment registrado sobre el cual el router pueda limitar: los modelos van por comodín).
PER_REQUEST_LIMITS = ("timeout", "num_retries")


def _tenant_of(user_api_key_dict: Any) -> Optional[str]:
    md = getattr(user_api_key_dict, "metadata", None) or {}
    ident = md.get("sentinel") if isinstance(md, Mapping) else None
    tenant = ident.get("tenant_id") if isinstance(ident, Mapping) else None
    return str(tenant) if tenant else None


def _actor_of(user_api_key_dict: Any) -> dict:
    """Parámetros de identidad para el canal de acceso: lo que traiga la identidad del pedido
    (`key_id`/`api_key_id`, `client_id`/`user_id`, `group_id`); lo ausente no se manda."""
    md = getattr(user_api_key_dict, "metadata", None) or {}
    ident = md.get("sentinel") if isinstance(md, Mapping) else None
    ident = ident if isinstance(ident, Mapping) else {}
    out = {"user": ident.get("client_id") or ident.get("user_id"), "group": ident.get("group_id"),
           "key": ident.get("key_id") or ident.get("api_key_id")}
    return {k: str(v) for k, v in out.items() if v}


def _http_fetch(environ: Mapping[str, str]) -> Fetch:
    identity_url = (environ.get("SENTINEL_IDENTITY_URL") or "").strip()
    secret = environ.get("LITELLM_MASTER_KEY", "")
    base = identity_url.rsplit("/internal/", 1)[0] + "/internal" if "/internal/" in identity_url else ""

    async def fetch(path: str, params: Mapping[str, str]) -> tuple:
        if not base:
            raise ConnectionError("sin URL del plano interno")
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:        # corto y sin retry: está en el camino del pedido
            r = await client.get(base + path.removeprefix("/internal"), params=dict(params),
                                 headers={"X-Sentinel-Internal": secret})
        return r.status_code, (r.json() if r.status_code == 200 else None)

    return fetch


class CatalogDirect:
    def __init__(self, fetch: Optional[Fetch] = None, *, environ: Optional[Mapping[str, str]] = None,
                 ttl: float = DEFAULT_TTL, clock: Callable[[], float] = time.monotonic):
        self._environ = os.environ if environ is None else environ
        self._fetch = fetch or _http_fetch(self._environ)
        self._ttl, self._clock = ttl, clock
        self._catalogs: dict = {}                    # tenant → (expira, documento)
        self._access: dict = {}                      # actor → (expira, permitidos | None)

    async def _catalog(self, tenant: str) -> Optional[dict]:
        hit = self._catalogs.get(tenant)
        if hit and hit[0] > self._clock():
            return hit[1]
        try:
            status, doc = await self._fetch("/internal/model-catalog", {"tenant": tenant})
        except Exception:  # noqa: BLE001 — sin catálogo, el pedido sigue por donde iba
            status, doc = 0, None
        if status != 200 or not isinstance(doc, dict):
            self._catalogs[tenant] = (self._clock() + self._ttl, None)     # no reintentar en cada pedido
            return None
        self._catalogs[tenant] = (self._clock() + self._ttl, doc)
        return doc

    async def _check_access(self, tenant: str, model: str, user_api_key_dict: Any) -> None:
        """Acceso por perfil (069 T153): consulta al backend qué ids públicos puede usar este actor.
        Fail-closed: sin respuesta válida no se sirve por omisión."""
        params = {"tenant": tenant, **_actor_of(user_api_key_dict)}
        key = tuple(sorted(params.items()))
        hit = self._access.get(key)
        if hit and hit[0] > self._clock():
            allowed = hit[1]
        else:
            try:
                status, doc = await self._fetch("/internal/model-access", params)
            except Exception:  # noqa: BLE001
                status, doc = 0, None
            if status != 200 or not isinstance(doc, dict) or not isinstance(doc.get("restringe"), bool):
                raise _guard.GuardRejection(503, "access_unavailable", "Modelo no disponible temporalmente.")
            allowed = frozenset(map(str, doc.get("permitidos") or ())) if doc["restringe"] else None
            self._access[key] = (self._clock() + self._ttl, allowed)
        if allowed is not None and model not in allowed:
            raise _guard.GuardRejection(403, "model_not_allowed_for_profile",
                                        "Este modelo no está permitido para tu perfil.")

    async def _credential(self, tenant: str, entry_id: str) -> dict:
        try:
            status, doc = await self._fetch("/internal/model-credential",
                                            {"tenant": tenant, "entry_id": entry_id})
        except Exception:  # noqa: BLE001
            status, doc = 0, None
        if status != 200 or not isinstance(doc, dict) or not isinstance(doc.get("credential"), dict):
            raise _guard.GuardRejection(503, "catalog_credential_unavailable",
                                        "Modelo no disponible temporalmente.")
        return doc["credential"]

    async def apply(self, data: dict, user_api_key_dict: Any, *, call_type: Optional[str] = None) -> bool:
        """Muta `data` y devuelve True si el modelo se resolvió por el catálogo."""
        model = data.get("model")
        if not isinstance(model, str) or _guard.is_redirect_model(model):
            return False
        tenant = _tenant_of(user_api_key_dict)
        if tenant is None:
            return False
        doc = await self._catalog(tenant)
        if not doc or not doc.get("direct"):
            return False
        entry = (doc.get("entries") or {}).get(model)
        if not isinstance(entry, Mapping):
            return False
        await self._check_access(tenant, model, user_api_key_dict)
        provider = entry.get("provider")
        role = entry.get("role") or "text"
        if role != CALL_TYPE_ROLE.get(call_type, "text"):
            raise _guard.GuardRejection(400, "model_role_mismatch",
                                        f"Este modelo es de tipo {role} y no se puede usar en esta operación.")
        cred = await self._credential(tenant, str(entry.get("entry_id")))
        try:
            engine_model = credentials.family_model(provider, entry["real_model"])
            cred = credentials.resolve_env_refs(cred, self._environ)
            params = credentials.to_litellm_params(provider, cred, entry.get("api_base"))
        except (credentials.CredentialError, KeyError):
            raise _guard.GuardRejection(503, "destination_misconfigured",
                                        "Modelo no disponible temporalmente.") from None
        for k in credentials.CLIENT_CREDENTIAL_FIELDS:
            data.pop(k, None)
        for k in ("input_cost_per_token", "output_cost_per_token"):
            data.pop(k, None)                         # el costo lo fija el catálogo, nunca el cliente
        # parámetros que la ficha declara no soportados (069 enmienda): se quitan PRIMERO del pedido del cliente,
        # antes de que el catálogo escriba credencial, costo y límites (H1 del QA del PR #78); se audita solo el nombre
        names = entry.get("unsupported_params")
        dropped = _guard.strip_unsupported(data, names if isinstance(names, (list, tuple)) else ())
        adjusted = _guard.raise_min_output_tokens(data, provider, call_type)       # piso del proveedor (T183), mismo paso que la redirección
        data["model"] = engine_model
        data.update(params)
        price = entry.get("price") or {}
        per_mtok = ({"input_per_mtok": float(price["input"]) * 1e6, "output_per_mtok": float(price["output"]) * 1e6}
                    if price.get("input") is not None and price.get("output") is not None else None)
        pricing, source = credentials.cost_params(per_mtok, provider, entry["real_model"],
                                                  _guard._engine_cost_map())
        data.update(pricing)
        limits = entry.get("limits")
        for k in PER_REQUEST_LIMITS:
            v = limits.get(k) if isinstance(limits, Mapping) else None
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                data[k] = v
        decision = {"source": "catalog", "role": role, "destination_id": entry.get("entry_id"),
                    "public_id": model, "semaforo": (entry.get("semaforo") or {}).get("estado"),
                    "pricing": source}
        _guard._merge_dropped(decision, dropped)
        if adjusted:
            decision[_guard.ADJUSTED_KEY] = ",".join(adjusted)
        _guard._write_decision(data, call_type, decision)
        return True
