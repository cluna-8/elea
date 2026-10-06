"""Comparador de costos del tráfico redirigido (FR-032; T112).

Función pura sobre filas de `audit_logs` ya cargadas por la ruta. Cada pedido servido por la
política (`routing_decision.extensions.redirect` con destino real, sin sombra) aporta:

- costo **real**: lo que registró el motor (`cost_usd`, con el precio del destino). Si quedó en 0
  con tokens — destino sin precio, hallazgo del spike de la 069 — se estima con el modelo REAL del
  destino y la fila se cuenta en `estimated_real`;
- costo **hipotético**: lo mismo con el modelo de referencia — el id pedido en las caras conocidas
  (Claude, Codex); el `reference_model` que eligió el administrador en los alias neutros. Sin
  referencia no se inventa: la fila cuenta en `without_reference` y queda fuera de la comparación.

`price(model, prompt_tokens, completion_tokens) -> Decimal` es la ÚNICA fuente de precios; en
producción `BudgetService.calculate_cost`, la misma que descuenta los presupuestos.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping, Optional

KNOWN_FACES = ("claude", "codex")
_Q = Decimal("0.00000001")


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _f(value: Optional[Decimal]) -> Optional[float]:
    return None if value is None else float(value.quantize(_Q))


def _redirect_block(row: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    decision = row.get("routing_decision")
    if not isinstance(decision, Mapping):
        return None
    block = (decision.get("extensions") or {}).get("redirect")
    return block if isinstance(block, Mapping) else None


def _scope_of(row: Mapping[str, Any]) -> tuple:
    if row.get("api_key_id"):
        return ("connection", str(row["api_key_id"]))
    if row.get("user_id"):
        return ("user", str(row["user_id"]))
    return ("tenant", "*")


def _in_scope(row: Mapping[str, Any], scope: Optional[tuple]) -> bool:
    if scope is None or scope[0] == "tenant":
        return True
    column = {"connection": "api_key_id", "user": "user_id", "group": "user_group_id"}.get(scope[0])
    return column is not None and str(row.get(column) or "") == str(scope[1])


def reference_model(published: Iterable[Mapping[str, Any]], face: str, public_id: str) -> Optional[str]:
    if face in KNOWN_FACES:
        return public_id
    for p in published:
        if p.get("face") == face and p.get("public_id") == public_id and p.get("reference_model"):
            return p["reference_model"]
    return None


class _Acc:
    def __init__(self):
        self.requests = 0
        self.real = Decimal(0)
        self.real_comparable = Decimal(0)
        self.hypothetical = Decimal(0)
        self.comparable = 0
        self.estimated = 0

    def add(self, real: Decimal, hypothetical: Optional[Decimal], estimated: bool):
        self.requests += 1
        self.real += real
        self.estimated += int(estimated)
        if hypothetical is not None:
            self.comparable += 1
            self.hypothetical += hypothetical
            self.real_comparable += real

    def out(self) -> dict:
        hyp = self.hypothetical if self.comparable else None
        return {"requests": self.requests, "cost_real": _f(self.real),
                "cost_real_comparable": _f(self.real_comparable), "cost_hypothetical": _f(hyp),
                "savings": _f(hyp - self.real_comparable) if hyp is not None else None,
                "without_reference": self.requests - self.comparable,
                "estimated_real": self.estimated}


def compare(rows: Iterable[Mapping[str, Any]], *, published: Iterable[Mapping[str, Any]],
            destinations: Mapping[str, Mapping[str, Any]],
            price: Callable[[str, int, int], Decimal],
            scope: Optional[tuple] = None) -> dict:
    published = list(published)
    totals, by_dest, by_scope = _Acc(), {}, {}
    shadow = 0
    for row in rows:
        block = _redirect_block(row)
        if block is None or not _in_scope(row, scope):
            continue
        if block.get("shadow"):
            shadow += 1
            continue
        dest_id = block.get("destination_id")
        if not dest_id:
            continue                                     # no se sirvió con ningún destino
        prompt, completion = int(row.get("prompt_tokens") or 0), int(row.get("completion_tokens") or 0)
        dest = destinations.get(str(dest_id))
        real, estimated = _d(row.get("cost_usd")), False
        if real == 0 and (prompt or completion) and dest and dest.get("real_model"):
            real, estimated = price(dest["real_model"], prompt, completion), True
        ref = reference_model(published, str(block.get("face")), str(block.get("public_id")))
        hypothetical = price(ref, prompt, completion) if ref else None
        totals.add(real, hypothetical, estimated)
        by_dest.setdefault(str(dest_id), _Acc()).add(real, hypothetical, estimated)
        by_scope.setdefault(_scope_of(row), _Acc()).add(real, hypothetical, estimated)
    return {
        "totals": totals.out(),
        "by_destination": [dict(destination_id=d, destination_name=(destinations.get(d) or {}).get("name"),
                                **acc.out()) for d, acc in sorted(by_dest.items())],
        "by_scope": [dict(scope_type=k[0], scope_value=k[1], **acc.out())
                     for k, acc in sorted(by_scope.items())],
        "shadow_requests": shadow,
    }
