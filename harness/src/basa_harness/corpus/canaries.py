"""Canarios de carga — PII sintética única por run (spec 035, T008, FR-004).

Un canario es un valor PII que se siembra en el tráfico de un run: si aparece EN CLARO
en el proveedor simulado, el masking falló (SLO (c) FAIL). Cada canario lleva un NONCE
único por ``run_id`` embebido, de modo que:

- dos ``run_id`` distintos producen conjuntos DISJUNTOS (imposible confundir una fuga
  de este run con residuos de otro — data-model «Set de un run ∩ set de otro = ∅»);
- el mismo ``run_id`` es reproducible (nonce derivado por hash del run_id, sin
  ``uuid``/``time`` — encaja con el determinismo del harness);
- el valor sigue siendo PII DETECTABLE por los reconocedores reales (checksums válidos,
  teléfono nacional) — si no, el masking «acertaría» por no ver PII y el canario no
  probaría nada.

**Disjunción por construcción vs. techo de formato (FIX-C3)**: el nonce se EMBEBE
LITERAL donde el formato lo permite → disjunción GARANTIZADA:
  - ``EMAIL_ADDRESS``: el nonce (12 hex) viaja tal cual en el local-part.
  - ``IBAN_CODE``: el nonce decimal (15 dígitos) ocupa el BBAN (banco+sucursal+cuenta),
    18 dígitos de espacio → inyectivo sobre el nonce.
  - ``CREDIT_CARD``: 12 dígitos de nonce en el cuerpo (14 libres) → colisión ~5e-5 a
    10 000 runs; efectivamente disjunto.
Los tipos de IDENTIFICADOR ESPAÑOL tienen un espacio de valores acotado por su PROPIO
formato y NO admiten el nonce completo — su disjunción es probabilística, no garantizada:
  - ``ES_NIF``: 8 dígitos = 10^8 valores válidos (techo del formato).
  - ``PHONE_NUMBER``: 9 dígitos, primero 6-9 = ~3.6·10^8.
Es una propiedad del formato (birthday bound), no de la implementación: no existe un NIF
español válido que codifique 48 bits de nonce. Se maximiza la entropía (los 8/9 dígitos
derivan del nonce) y se documenta el techo. Ver ``generate_canaries`` y los tests.

Estos NO se commitean como dataset (son runtime-only, capa aparte del corpus etiquetado
— corpus-format.md, cabecera). Este módulo SOLO los genera.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from . import oracle

# Tipos que se siembran como canarios y cómo se construye cada valor a partir del run.
_CANARY_TYPES = ["EMAIL_ADDRESS", "PHONE_NUMBER", "ES_NIF", "IBAN_CODE", "CREDIT_CARD"]

# Tipos cuya disjunción es GARANTIZADA por construcción (nonce embebido literal).
GUARANTEED_DISJOINT_TYPES = frozenset({"EMAIL_ADDRESS", "IBAN_CODE"})
# Tipos acotados por el espacio de su propio formato (disjunción probabilística).
FORMAT_BOUNDED_TYPES = frozenset({"ES_NIF", "PHONE_NUMBER", "CREDIT_CARD"})


def _nonce_for(run_id: str) -> str:
    """Nonce hex de 12 chars derivado del run_id (determinista, disjunto entre runs)."""
    return hashlib.sha256(f"basa-itv-canary::{run_id}".encode("utf-8")).hexdigest()[:12]


def _nonce_decimal(nonce: str, width: int) -> str:
    """El nonce completo como ``width`` dígitos decimales (inyectivo si width>=15)."""
    return f"{int(nonce, 16):0{width}d}"[-width:] if width < 15 else f"{int(nonce, 16):015d}"


def _digits_from(nonce: str, salt: str, length: int) -> str:
    """Cadena de ``length`` dígitos derivada de (nonce, salt) — determinista.

    Para los tipos acotados por formato (NIF/teléfono) usa TODO el ancho disponible
    del hash de (nonce, salt): entropía máxima dentro del techo del formato.
    """
    h = hashlib.sha256(f"{nonce}:{salt}".encode("utf-8")).hexdigest()
    return (str(int(h, 16)))[:length].rjust(length, "0")


def _canary_value(entity_type: str, nonce: str, i: int) -> str:
    salt = f"{entity_type}:{i}"
    if entity_type == "EMAIL_ADDRESS":
        # Nonce LITERAL en el local-part → disjunción garantizada por construcción.
        return f"itv-canary-{nonce}-{i}@canario.basa-itv.invalid"
    if entity_type == "IBAN_CODE":
        # Nonce decimal completo (15 díg) en banco+sucursal+cuenta → inyectivo sobre
        # el nonce; el índice i ocupa los 3 dígitos bajos de la cuenta (distinto por
        # canario dentro del run). 18 díg de BBAN alcanzan de sobra.
        nd = _nonce_decimal(nonce, 15)
        bank = nd[0:4]
        branch = nd[4:8]
        account = nd[8:15] + f"{i % 1000:03d}"  # 7 + 3 = 10 dígitos
        return oracle.build_iban_es(bank, branch, account)
    if entity_type == "CREDIT_CARD":
        # 12 díg de nonce + 2 de índice en el cuerpo (14 libres tras el BIN "4");
        # colisión ~5e-5 a 10 000 runs (efectivamente disjunto).
        cuerpo = "4" + _nonce_decimal(nonce, 12) + f"{i % 100:02d}"  # 1+12+2 = 15
        return cuerpo + str(oracle.luhn_check_digit(cuerpo))
    if entity_type == "ES_NIF":
        # 8 díg = techo del formato (10^8). Se deriva del nonce+i (máxima entropía).
        numero = _digits_from(nonce, salt, 8)
        return numero + oracle.nif_control_letter(numero)
    if entity_type == "PHONE_NUMBER":
        # 9 díg, primero 6-9 = techo ~3.6·10^8. Derivado del nonce+i.
        d = _digits_from(nonce, salt, 8)
        primero = "6789"[int(d[0]) % 4]
        numero = primero + d
        return f"{numero[0:3]} {numero[3:6]} {numero[6:9]}"
    raise ValueError(f"tipo de canario no soportado: {entity_type!r}")


def generate_canaries(run_id: str, n: int, *,
                      types: Optional[list[str]] = None) -> list[dict]:
    """Genera ``n`` canarios únicos para ``run_id``.

    Cada canario es un dict ``{canary_id, run_id, nonce, entity_type, value}``.
    ``value`` es el string exacto a sembrar en el tráfico (PII detectable de ese
    ``entity_type``). Dos ``run_id`` distintos → conjuntos de ``value`` disjuntos
    (GARANTIZADO para ``GUARANTEED_DISJOINT_TYPES``; probabilístico y acotado por el
    formato para ``FORMAT_BOUNDED_TYPES`` — ver el docstring del módulo).

    Args:
        run_id: identificador del run (define el nonce).
        n: cuántos canarios generar.
        types: tipos a rotar (por defecto los 5 con checksum/regex verificable).
    """
    if n < 0:
        raise ValueError("n no puede ser negativo")
    if not run_id:
        raise ValueError("run_id es obligatorio")
    menu = types or _CANARY_TYPES
    nonce = _nonce_for(run_id)
    canaries: list[dict] = []
    for i in range(n):
        etype = menu[i % len(menu)]
        canaries.append({
            "canary_id": f"canary-{nonce}-{i:04d}",
            "run_id": run_id,
            "nonce": nonce,
            "entity_type": etype,
            "value": _canary_value(etype, nonce, i),
        })
    return canaries
