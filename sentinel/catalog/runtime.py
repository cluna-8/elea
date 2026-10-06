"""Instancias compartidas del catálogo en el proceso de la pasarela (versión de instantánea)."""
from __future__ import annotations

from typing import Optional

from sentinel.common.snapshot_version import SnapshotVersion

_catalog_version: Optional[SnapshotVersion] = None


def catalog_version() -> SnapshotVersion:
    """Contador `ext:catalog:v:<organización>`; `bump` lo suben las escrituras de la API."""
    global _catalog_version
    if _catalog_version is None:
        _catalog_version = SnapshotVersion("catalog")
    return _catalog_version
