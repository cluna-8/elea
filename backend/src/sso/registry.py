"""Registro de proveedores SSO (spec 017 US2, `contracts/proveedor-sso.md`).

Contrato CONGELADO (Jeff, 017-auth-rbac-sso): nombres y firmas son ley — hay código en
paralelo (`sso/api.py`, `sso/jit.py`, ambos de Jeff) que importa este módulo tal cual. Alta
de un proveedor nuevo (Google, C3; research D2) = implementar `SsoProvider` + `register(...)`;
el flujo común (rutas, JIT, emisión de sesión, flag de licencia) no se toca.

``Identity`` es lo MÍNIMO que un proveedor devuelve tras `exchange_code`: cualquier claim
extra que el IdP mande (roles, groups, tenant propio, lo que sea) se DESCARTA acá — el mapeo
IdP→rol es un consumidor futuro NO comprometido en esta spec (research D11).
"""
from typing import Protocol, TypedDict


class Identity(TypedDict):
    email: str
    subject: str
    display_name: str


class SsoProvider(Protocol):
    provider_type: str

    def authorize_url(
        self, config: dict, state: str, *, nonce: str, redirect_uri: str
    ) -> str:
        """Arma la URL de inicio del flujo (redirect al IdP). Incluye `state` y `nonce` TAL
        CUAL se los pasaron, `response_type=code` y el `redirect_uri` recibido — regla dura
        6 del contrato."""
        ...

    def exchange_code(
        self, config: dict, code: str, *, nonce: str, redirect_uri: str
    ) -> Identity:
        """Callback: intercambia el `code` por tokens contra el IdP y devuelve la identidad
        YA verificada (firma, `iss`, `aud`, `nonce`, expiración). Nunca acepta un id_token sin
        verificar."""
        ...


_REGISTRY: dict[str, SsoProvider] = {}
_BUILTINS_CARGADOS = False


def _cargar_builtins() -> None:
    """Registra los proveedores built-in la primera vez que alguien pide uno.

    El registro se AUTO-ABASTECE: ningún consumidor externo necesita `from . import entra`
    sólo por el efecto de lado del import (frágil — cualquier linter que ordene/pode imports
    lo puede borrar por "no usado", y acopla `sso/api.py` a este archivo sin necesidad; enmienda
    de Jeff sobre el brief original de T014). El import de `entra` va DENTRO de la función y no
    a nivel de módulo: `entra.py` importa `register`/`SsoProvider`/`Identity` de ACÁ, así que un
    import a nivel de módulo en este archivo crearía un ciclo.
    """
    global _BUILTINS_CARGADOS
    if _BUILTINS_CARGADOS:
        return
    from . import entra  # noqa: F401 — el import ejecuta `register(EntraProvider())`
    _BUILTINS_CARGADOS = True


def register(provider: SsoProvider) -> None:
    """Alta (o reemplazo) de un proveedor en el registro. Última alta gana — permite que los
    tests registren un doble sin reiniciar el proceso."""
    _REGISTRY[provider.provider_type] = provider


def get_provider(provider_type: str) -> SsoProvider:
    """Devuelve el proveedor registrado. Levanta `KeyError` si `provider_type` no existe —
    ni siquiera tras cargar los built-ins. El 404/400 hacia el cliente lo arma el consumidor
    (`sso/api.py`), no este módulo."""
    _cargar_builtins()
    return _REGISTRY[provider_type]


def known_types() -> set[str]:
    """Tipos de proveedor disponibles. Carga los built-ins primero: sin eso, en un proceso
    donde nadie llamó `get_provider` todavía, mentiría que `entra` no existe."""
    _cargar_builtins()
    return set(_REGISTRY.keys())
