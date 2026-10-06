"""Versión de instantánea por organización y caché corta (069 T012; research D6, FR-014).

Mismo patrón que `RedirectStore` de la 068, generalizado para que catálogo y acceso lo compartan:
cada escritura sube un contador (`ext:<clase>:v:<organización>`, o `*` para cambios de nivel
instalación) en Redis y en memoria; los lectores comparan la versión en cada lectura y sueltan su
caché si cambió. Sin Redis, o con Redis caído, rige el TTL corto: el cambio sigue siendo visible
muy por debajo de los 60 s del requisito.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("sentinel.common.snapshot_version")

_GLOBAL = "*"


def _default_redis():
    try:
        from src.services.redis_client import get_redis
        return get_redis()
    except Exception:  # noqa: BLE001
        return None


class SnapshotVersion:
    def __init__(self, kind: str, redis_factory: Optional[Callable[[], Any]] = None):
        self.kind = kind
        self._redis_factory = redis_factory if redis_factory is not None else _default_redis
        self._local = 0
        self._lock = threading.Lock()

    def key(self, tenant_id: Optional[str]) -> str:
        return f"ext:{self.kind}:v:{_GLOBAL if tenant_id is None else tenant_id}"

    def current(self, tenant_id: str):
        r = self._redis_factory()
        if r is None:
            return self._local
        try:
            return (self._local, tuple(r.mget(self.key(tenant_id), self.key(None))))
        except Exception:  # noqa: BLE001 — sin Redis rige el TTL
            return self._local

    def bump(self, tenant_id: Optional[str] = None) -> None:
        with self._lock:
            self._local += 1
        r = self._redis_factory()
        if r is not None:
            try:
                r.incr(self.key(tenant_id))
            except Exception:  # noqa: BLE001
                logger.warning("%s: no se pudo publicar la versión en Redis; rige el TTL", self.kind)


class SnapshotCache:
    """Caché por organización con TTL + versión; `loader(tenant_id)` produce la instantánea."""

    def __init__(self, version: SnapshotVersion, loader: Callable[[str], Any], *, ttl: float = 5.0,
                 clock: Callable[[], float] = time.monotonic):
        self.version = version
        self._loader = loader
        self.ttl = ttl
        self._clock = clock
        self._cache: dict = {}
        self._lock = threading.Lock()

    def get(self, tenant_id: str):
        tenant_id = str(tenant_id)
        now = self._clock()
        ver = self.version.current(tenant_id)
        hit = self._cache.get(tenant_id)
        if hit and hit[0] > now and hit[1] == ver:
            return hit[2]
        snap = self._loader(tenant_id)
        with self._lock:
            self._cache[tenant_id] = (now + self.ttl, ver, snap)
        return snap
