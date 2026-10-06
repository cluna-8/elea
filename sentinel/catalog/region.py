"""Región efectiva del perfil para el catálogo (057 FR-021, FR-028a; data-model §1, §4).

Qué jurisdicciones son «mi región» para una empresa: la fila de `sentinel_redirect_region` (empresa > instalación) cuyos
`region_profiles` contienen el perfil de país resuelto; sin fila, el respaldo fijo de `residency.region_codes` (el
comportamiento de Sentinel). Perfil sin resolver ⇒ ninguna jurisdicción: nada cuenta como «en región».

La regla «en región» del catálogo (`in_region`) exige que inferencia, entidad **y control** de la ficha estén en el
conjunto; un dato sin cargar (`NULL`, vacío o `unknown`) no cuenta. Ningún código nombra un país.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from sentinel.redirect import models as rm
from sentinel.redirect.residency import region_codes, satisfies

PROFILE_ENV = "SENTINEL_ENTITY_REGION"


def installation_profile() -> Optional[str]:
    """Perfil de país de la instalación (`SENTINEL_ENTITY_REGION`); vacío ⇒ sin resolver."""
    return (os.environ.get(PROFILE_ENV) or "").strip().lower() or None


def effective_codes(db, tenant_id, profile: Optional[str] = ...) -> frozenset:
    """Jurisdicciones de «mi región» para `tenant_id` y `profile` (por defecto, el de la instalación)."""
    profile = installation_profile() if profile is ... else (profile or "").strip().lower() or None
    if profile is None:
        return frozenset()
    memo = db.info.setdefault("region_codes", {})            # una consulta por sesión y empresa (las listas la repiten)
    if (tenant_id, profile) in memo:
        return memo[(tenant_id, profile)]
    memo[(tenant_id, profile)] = codes = _codes(db, tenant_id, profile)
    return codes


def _codes(db, tenant_id, profile: str) -> frozenset:
    rows = [r for r in db.query(rm.RedirectRegion)
            if profile in {str(p).strip().lower() for p in (r.region_profiles or ())}
            and (r.tenant_id is None or r.tenant_id == tenant_id)]
    rows.sort(key=lambda r: r.tenant_id is None)               # la de la empresa gana sobre la de instalación
    if rows:
        return frozenset(str(j).strip().upper() for j in (rows[0].jurisdictions or ()) if str(j).strip())
    return region_codes(profile)


def in_region(sheet: Any, codes) -> bool:
    """¿Inferencia, entidad y control de la ficha están todos en `codes`? Faltante o `unknown` ⇒ no."""
    if sheet is None or not codes:
        return False
    return all(_loaded(getattr(sheet, f, None)) and satisfies(getattr(sheet, f), codes)
               for f in ("inference_jurisdiction", "entity_jurisdiction", "control_jurisdiction"))


def _loaded(code: Optional[str]) -> bool:
    return bool(code and str(code).strip() and str(code).strip().lower() != "unknown")
