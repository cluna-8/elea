"""Semáforo de cumplimiento derivado de la ficha (069 FR-002a, FR-003, FR-003a; T025).

Una sola regla, pública y pura: la usan la API del catálogo, el bloqueo de residencia de proyectos,
los perfiles de acceso y `/internal/model-catalog`. Nunca se almacena ni se escribe: se deriva en
lectura, así un DPA que vence cambia el estado sin que nadie edite nada.

La región contra la que se evalúa es un parámetro (057 FR-030a; research R16): por defecto la UE de siempre, y con la
región del perfil (`region`: las jurisdicciones de «mi región», de `sentinel_redirect_region`) lo que la inferencia, los
registros y el DPA deben cumplir es estar *dentro de esa región*. El valor interno `eu_ok` se conserva (paridad de API
y de tests): la etiqueta que ve el cliente sale de la región («Dentro de <región>»), y el servidor no la arma. Con la
región de una fila (`region_strict`) «dentro» exige también entidad responsable y jurisdicción de control (R25); un dato
sin cargar deja la entrada sin clasificar. Sin región resuelta (`region` vacía) nada está dentro: nunca cae a la UE.

Orden de la regla (FR-003): primero *sin clasificar* —cualquier dato que la regla necesita
desconocido o sin cargar—, después *estándar* —alguna condición incumplida— y, si no, *admisible UE*.
Una ficha a medio llenar no se trata como «clasificada estándar»: sigue sin clasificar (y por eso
la residencia de proyectos cae a su heurística de respaldo, FR-006). Salvo la inferencia **local**,
que por sí sola hace admisible a la entrada y no necesita ningún otro dato.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Mapping, Optional

from sentinel.redirect.residency import satisfies

ESTADOS = ("eu_ok", "standard", "unclassified")
EU_REGION = frozenset({"EU"})
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


def _dentro_o_local(code: Optional[str], region: frozenset) -> Optional[bool]:
    if code is None:
        return None
    return code == "local" or satisfies(code, region)


def semaforo(ficha: Mapping[str, Any], dpa: Optional[Mapping[str, Any]] = None, *,
             es_agregador: bool = False, hoy: Optional[date] = None,
             desactualizada: bool = False, region: Optional[Iterable[str]] = None,
             region_strict: bool = False) -> dict:
    """→ `{"estado": eu_ok|standard|unclassified, "motivos": [...]}`.

    `region`: jurisdicciones de la región contra la que se evalúa (`None` = la UE, como siempre; vacía = región sin
    resolver, nada está dentro). `region_strict`: la región viene de una fila de `sentinel_redirect_region` y «dentro»
    exige también entidad y control (R25). Los motivos conservan sus nombres de siempre (`*_ue`) cuando la región es
    la UE y pasan a `*_region` con cualquier otra.

    `ficha`: campos de `ext_compliance_sheet`. `dpa`: fila del registro de DPAs asociada (o `None`).
    `hoy`: fecha UTC; se inyecta para que la función sea pura y testeable.
    `desactualizada`: la entrada cambió de proveedor o modelo real tras clasificarse; la ficha ya no
    describe lo que se sirve, así que no se emite veredicto (Edge Case de la spec).
    """
    if desactualizada:
        return {"estado": "unclassified", "motivos": ["ficha_desactualizada"]}
    hoy = hoy or datetime.utcnow().date()
    codes = EU_REGION if region is None else frozenset(c for c in (_norm(x) for x in region) if c)
    codes = frozenset(c.upper() for c in codes)
    suf = "ue" if codes == EU_REGION else "region"
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

    exige(None if inf is None else satisfies(inf, codes), f"inferencia_fuera_{suf}", "inference_jurisdiction")

    if region_strict:                       # R25: la entidad responsable y quien la controla también dentro
        for campo, motivo in (("entity_jurisdiction", "entidad_fuera_region"),
                              ("control_jurisdiction", "control_fuera_region")):
            code = _juris(ficha.get(campo))
            exige(None if code is None else satisfies(code, codes), motivo, campo)

    logs = _juris(ficha.get("logs_jurisdiction"))
    exige(None if logs is None else (logs == "none" or bool(_dentro_o_local(logs, codes))),
          f"registros_fuera_{suf}", "logs_jurisdiction")

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
        procesa = _juris(dpa.get("processing_region"))
        if procesa is None or not satisfies(procesa, codes):
            falsos.append(f"dpa_region_no_{suf}")

    return _resultado(falsos, desconocidos)


def _resultado(falsos: list, desconocidos: list) -> dict:
    if desconocidos:
        return {"estado": "unclassified", "motivos": desconocidos}
    if falsos:
        return {"estado": "standard", "motivos": falsos}
    return {"estado": "eu_ok", "motivos": []}
