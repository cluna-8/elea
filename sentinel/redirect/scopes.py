"""Alcances y precedencia (data-model §0).

Un «row» es cualquier dict con `scope_type`/`scope_value` (y opcionalmente `tenant_id`).
Precedencia: conexión > usuario > grupo > tenant. Entre grupos (un usuario puede estar en
varios) el desempate es determinista: gana el `group_id` menor en orden lexicográfico, así
todos los planos (pasarela, vista previa, sombra) resuelven igual sin depender del orden en
que llegaron los grupos.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

SCOPE_TYPES = ("connection", "user", "group", "tenant")
_RANK = {name: i for i, name in enumerate(SCOPE_TYPES)}


@dataclass(frozen=True)
class RequestScope:
    tenant_id: str
    connection_id: Optional[str] = None
    user_id: Optional[str] = None
    group_ids: tuple = ()

    def label(self) -> str:
        """Etiqueta estable del alcance del pedido (va firmada en la autorización interna)."""
        if self.connection_id:
            return f"{self.tenant_id}/connection:{self.connection_id}"
        if self.user_id:
            return f"{self.tenant_id}/user:{self.user_id}"
        return f"{self.tenant_id}/tenant:*"


def scope_key(row: Mapping[str, Any], scope: RequestScope) -> Optional[tuple]:
    """Clave de orden (menor = más específico) si la fila aplica al pedido; si no, None."""
    tenant = row.get("tenant_id", scope.tenant_id)
    if tenant is not None and tenant != scope.tenant_id:
        return None
    st, sv = row.get("scope_type"), row.get("scope_value")
    if st == "connection":
        ok = scope.connection_id is not None and sv == scope.connection_id
    elif st == "user":
        ok = scope.user_id is not None and sv == scope.user_id
    elif st == "group":
        ok = sv in scope.group_ids
    elif st == "tenant":
        ok = sv in ("*", None, scope.tenant_id)
    else:
        return None
    if not ok:
        return None
    tiebreak = str(sv) if st == "group" else ""
    return (_RANK[st], tiebreak)


def applicable(rows: Iterable[Mapping[str, Any]], scope: RequestScope) -> list:
    """Filas que aplican, ordenadas de más a menos específica (orden estable)."""
    keyed = []
    for i, r in enumerate(rows):
        k = scope_key(r, scope)
        if k is not None:
            keyed.append((k, i, r))
    keyed.sort(key=lambda t: (t[0], t[1]))
    return [r for _, _, r in keyed]


def most_specific(rows: Iterable[Mapping[str, Any]], scope: RequestScope):
    found = applicable(rows, scope)
    return found[0] if found else None
