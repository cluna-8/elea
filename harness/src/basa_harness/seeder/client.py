"""Cliente HTTP del backend para el seeder (spec 035, T020; research R5).

Habla la API REST REAL del producto — el seed ES el primer mini-examen del plano admin
(R5). Superficie verificada en el repo (rama 035-load-harness):

- ``POST /api/v1/users/login``     bootstrap del primer admin (username=admin →
  tenant_admin si la instalación no tiene dueño) o login normal después
  (``backend/src/api/users.py:54``).
- ``GET  /api/v1/health/license``  pre-check de seats: con sesión admin devuelve
  ``max_seats``/``seats_used`` (``backend/src/api/health.py:44``).
- ``POST /api/v1/users``           alta de usuario, admin-only; el seat gate corre en
  alta de rol ``client`` (``backend/src/api/users.py:137`` → ``enforce_seat_gate``).
- ``POST /api/v1/keys``            crea la Connection/APIKey por ``tool_type``; el seat =
  llave activa; 409 si el user ya tiene una activa para esa herramienta
  (``backend/src/api/keys.py:124``).
- ``POST /api/v1/budgets``         presupuesto por user XOR group
  (``backend/src/api/budgets.py:17``).

La lógica de secuencia/idempotencia vive en ``seed.py``; este módulo sólo traduce cada
paso a HTTP y levanta ``BackendError`` con el status para que el orquestador decida qué
es "duplicado esperado → convergé" (400/409) y qué es fallo real. El orquestador está
escrito contra el ``Protocol`` ``SeedClient`` — los tests inyectan un cliente falso, sin
httpx ni backend.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

import httpx

# Prefijo común de la API montada (backend/src/api/__init__.py:21 + main.py:99).
API_PREFIX = "/api/v1"

# Statuses que el orquestador trata como "ya existe → convergé" (no son fallo):
#   400 = username/budget duplicado · 409 = Connection duplicada para ese tool_type.
DUPLICATE_STATUSES: frozenset[int] = frozenset({400, 409})


class BackendError(RuntimeError):
    """Respuesta no-2xx de la API. ``status_code`` y ``detail`` guían la decisión del
    orquestador (convergencia vs fail-fast)."""

    def __init__(self, status_code: int, detail: str, *, method: str = "", url: str = ""):
        self.status_code = status_code
        self.detail = detail
        self.method = method
        self.url = url
        where = f" [{method} {url}]" if url else ""
        super().__init__(f"HTTP {status_code}: {detail}{where}")

    @property
    def is_duplicate(self) -> bool:
        return self.status_code in DUPLICATE_STATUSES


@runtime_checkable
class SeedClient(Protocol):
    """Contrato que el orquestador (``seed.py``) necesita. Lo implementan el
    ``BackendClient`` real y el cliente falso de los tests."""

    def bootstrap_admin(self, username: str, password: str) -> str: ...
    def verify_credential(self, username: str, password: str) -> bool: ...
    def license_health(self) -> dict: ...
    def list_users(self) -> list[dict]: ...
    def list_keys(self) -> list[dict]: ...
    def list_budgets(self) -> list[dict]: ...
    def create_user(self, *, username: str, email: str, password: str, role: str,
                     client_type: Optional[str] = None) -> dict: ...
    def create_key(self, *, name: str, user_id: str, tool_type: str) -> dict: ...
    def create_budget(self, *, user_id: str, max_spend_usd: float, max_tokens: int,
                       reset_period: str) -> dict: ...


class BackendClient:
    """Implementación real sobre ``httpx.Client`` (síncrona: el seed es secuencial y una
    sola vez por despliegue; R5 estima 5-10 min para 500 users)."""

    def __init__(self, base_url: str, *, timeout: float = 30.0,
                 client: Optional[httpx.Client] = None):
        self.base_url = base_url.rstrip("/")
        self._token: Optional[str] = None
        # Se acepta un ``httpx.Client`` inyectado (tests de transporte con MockTransport).
        self._http = client or httpx.Client(timeout=timeout)
        self._owns_http = client is None

    # -- contexto / cierre --------------------------------------------------------------
    def __enter__(self) -> "BackendClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    # -- transporte ---------------------------------------------------------------------
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _request(self, method: str, path: str, *, json: Any = None) -> Any:
        url = f"{self.base_url}{API_PREFIX}{path}"
        resp = self._http.request(method, url, json=json, headers=self._headers())
        if resp.status_code >= 400:
            raise BackendError(resp.status_code, _extract_detail(resp), method=method, url=url)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # -- pasos de la secuencia R5 -------------------------------------------------------
    def bootstrap_admin(self, username: str, password: str) -> str:
        """``POST /users/login``: crea el primer tenant_admin si no hay dueño, o loguea.

        Guarda el bearer para el resto de la secuencia y lo devuelve."""
        body = self._request("POST", "/users/login",
                             json={"username": username, "password": password})
        self._token = body["access_token"]
        return self._token

    def verify_credential(self, username: str, password: str) -> bool:
        """``POST /users/login`` de sólo-comprobación: True si autentica, False si 401.

        NO toca el token de la sesión admin (descarta la respuesta) — se usa para detectar
        que la DB fue sembrada con OTRA semilla antes de emitir un pool que mentiría."""
        url = f"{self.base_url}{API_PREFIX}/users/login"
        resp = self._http.request("POST", url, json={"username": username, "password": password})
        if resp.status_code == 200:
            return True
        if resp.status_code == 401:
            return False
        raise BackendError(resp.status_code, _extract_detail(resp), method="POST", url=url)

    def license_health(self) -> dict:
        """``GET /health/license``: con la sesión admin trae ``max_seats``/``seats_used``."""
        return self._request("GET", "/health/license")

    def list_users(self) -> list[dict]:
        return self._request("GET", "/users") or []

    def list_keys(self) -> list[dict]:
        return self._request("GET", "/keys") or []

    def list_budgets(self) -> list[dict]:
        return self._request("GET", "/budgets") or []

    def create_user(self, *, username: str, email: str, password: str, role: str,
                     client_type: Optional[str] = None) -> dict:
        payload: dict = {"username": username, "email": email, "password": password,
                         "role": role, "is_active": True}
        # client_type viaja best-effort: hoy el schema UserCreate no lo declara y Pydantic
        # lo ignora (queda NULL vía REST), pero enviarlo documenta la intención y es
        # forward-compatible si el borde lo acepta más adelante. Ver README del perfil.
        if client_type is not None:
            payload["client_type"] = client_type
        return self._request("POST", "/users", json=payload)

    def create_key(self, *, name: str, user_id: str, tool_type: str) -> dict:
        return self._request("POST", "/keys",
                             json={"name": name, "user_id": user_id, "tool_type": tool_type})

    def create_budget(self, *, user_id: str, max_spend_usd: float, max_tokens: int,
                       reset_period: str) -> dict:
        return self._request("POST", "/budgets",
                             json={"user_id": user_id, "max_spend_usd": max_spend_usd,
                                   "max_tokens": max_tokens, "reset_period": reset_period})


def _extract_detail(resp: httpx.Response) -> str:
    """El ``detail`` de FastAPI si viene JSON; si no, el texto crudo acotado."""
    try:
        data = resp.json()
    except (ValueError, httpx.DecodingError):
        return resp.text[:300]
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])
    return str(data)[:300]
