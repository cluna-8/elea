"""Semáforo de cumplimiento derivado de la ficha (069 FR-002a, FR-003, FR-003a; T025).

Una sola regla, pública y pura: la usan la API del catálogo, el bloqueo de residencia de proyectos,
los perfiles de acceso y `/internal/model-catalog`. Nunca se almacena ni se escribe: se deriva en
lectura, así un DPA que vence cambia el estado sin que nadie edite nada.

Orden de la regla (FR-003): primero *sin clasificar* —cualquier dato que la regla necesita
desconocido o sin cargar—, después *estándar* —alguna condición incumplida— y, si no, *admisible UE*.
Una ficha a medio llenar no se trata como «clasificada estándar»: sigue sin clasificar (y por eso
la residencia de proyectos cae a su heurística de respaldo, FR-006). Salvo la inferencia **local**,
que por sí sola hace admisible a la entrada y no necesita ningún otro dato.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Optional

from sentinel.redirect.residency import satisfies

ESTADOS = ("eu_ok", "standard", "unclassified")
_TRANSFER_OK = {"n/a", "dpf", "scc"}
_DESCONOCIDO = {None, "", "unknown"}


def _norm(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _juris(v: Any) -> Optional[str]:
    s = _norm(v)
    return None if s is None or s.lower() == "unknown" else s.upper() if len(s) <= 3 else s.lower()


def _fecha(v: Any) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _ue_o_local(code: Optional[str]) -> Optional[bool]:
    if code is None:
        return None
    return code == "local" or satisfies(code, {"EU"})


def semaforo(ficha: Mapping[str, Any], dpa: Optional[Mapping[str, Any]] = None, *,
             es_agregador: bool = False, hoy: Optional[date] = None,
             desactualizada: bool = False) -> dict:
    """→ `{"estado": eu_ok|standard|unclassified, "motivos": [...]}`.

    `ficha`: campos de `ext_compliance_sheet`. `dpa`: fila del registro de DPAs asociada (o `None`).
    `hoy`: fecha UTC; se inyecta para que la función sea pura y testeable.
    `desactualizada`: la entrada cambió de proveedor o modelo real tras clasificarse; la ficha ya no
    describe lo que se sirve, así que no se emite veredicto (Edge Case de la spec).
    """
    if desactualizada:
        return {"estado": "unclassified", "motivos": ["ficha_desactualizada"]}
    hoy = hoy or datetime.utcnow().date()
    inf = _juris(ficha.get("inference_jurisdiction"))
    falsos: list[str] = []
    desconocidos: list[str] = []

    def exige(ok: Optional[bool], motivo_falso: str, campo: str) -> None:
        if ok is None:
            desconocidos.append(f"dato_desconocido:{campo}")
        elif not ok:
            falsos.append(motivo_falso)

    # El agregador (FR-002a): la ficha cubre solo su capa; sin región UE contratada y enrutamiento
    # restringido nunca es admisible, ni siquiera si declara inferencia «local».
    if es_agregador:
        reg = ficha.get("eu_region_contracted")
        exige(None if reg is None else bool(reg), "agregador", "eu_region_contracted")

    if inf == "local":
        if not falsos and not desconocidos:
            return {"estado": "eu_ok", "motivos": ["local"]}
        return _resultado(falsos, desconocidos)

    exige(None if inf is None else satisfies(inf, {"EU"}), "inferencia_fuera_ue",
          "inference_jurisdiction")

    logs = _juris(ficha.get("logs_jurisdiction"))
    exige(None if logs is None else (logs == "none" or bool(_ue_o_local(logs))),
          "registros_fuera_ue", "logs_jurisdiction")

    entrena = ficha.get("trains_on_data")
    exige(None if entrena is None else not bool(entrena), "entrena_con_datos", "trains_on_data")

    mecanismo = _norm(ficha.get("transfer_mechanism"))
    mecanismo = mecanismo.lower() if mecanismo else None
    if mecanismo in _DESCONOCIDO:
        desconocidos.append("dato_desconocido:transfer_mechanism")
    elif mecanismo not in _TRANSFER_OK:
        falsos.append("transferencia_sin_mecanismo")

    # DPA: la ausencia no es un dato desconocido sino un hecho (no hay contrato).
    if dpa is None:
        falsos.append("sin_dpa")
    else:
        if not dpa.get("is_active", True):
            falsos.append("dpa_inactivo")
        vence = _fecha(dpa.get("expiration_date"))
        if vence is not None and hoy > vence:           # vigente hasta el final del día, inclusive
            falsos.append("dpa_vencido")
        region = _juris(dpa.get("processing_region"))
        if region is None or not satisfies(region, {"EU"}):
            falsos.append("dpa_region_no_ue")

    return _resultado(falsos, desconocidos)


def _resultado(falsos: list, desconocidos: list) -> dict:
    if desconocidos:
        return {"estado": "unclassified", "motivos": desconocidos}
    if falsos:
        return {"estado": "standard", "motivos": falsos}
    return {"estado": "eu_ok", "motivos": []}
