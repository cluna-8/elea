"""Fingerprint del run: captura y comparación (spec 035, T013; FR-009 / data-model /
contract ``run-report.md``).

El fingerprint es la HUELLA de las condiciones bajo las que corrió un examen. Su razón
de ser (US3): dos runs solo son comparables si corrieron el MISMO examen. Por eso el
comparador **diffea los fingerprints ANTES que las métricas** y marca ILEGÍTIMA
cualquier comparación con diferencia material (contract: «marca ilegítima cualquier
comparación con diff»).

Lista mínima de FR-009 (data-model):
    producto (commit + digests) · masking_por_scope · config_nlp (incl. nlp_fail_mode,
    nlp_analyzer_url) · workers_procesos (backend/motor/nlp) · limites_recursos ·
    gate (n + version + kind) · examen (programa del stub + fases) · corpus (version +
    sha256 + seed) · mix_y_cadencia_usadas · hardware (server_type/datacenter — outputs de
    OpenTofu) · licencia (lic_id/max_seats) · seed_estado · versiones_instrumento
    (k6+xk6-sse, stub, harness commit) · timestamp.

``gate.kind`` y ``examen`` son la extensión C1: el drill de saturación y el gate 125
oficial comparten número, versión, mezcla y cadencia — sin esos campos sus fingerprints
solo diferían en el ``timestamp`` (no material) y el comparador declaraba «LEGÍTIMA» la
comparación de dos exámenes distintos.

DETERMINISMO (restricción del entorno de ejecución): la lógica pura NO lee el reloj ni
genera uuid/random. El ``timestamp`` se INYECTA como parámetro de ``capture`` — así los
tests son reproducibles. El comparador excluye ``timestamp`` del diff material: dos runs
de repetibilidad (misma config, distinto momento) DEBEN salir legítimos.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Union

# Orden canónico de la lista mínima de FR-009 (estable para serializar/diffar).
FINGERPRINT_FIELDS: tuple[str, ...] = (
    "producto",
    "masking_por_scope",
    "config_nlp",
    "workers_procesos",
    "limites_recursos",
    "gate",
    "examen",
    "corpus",
    "mix_y_cadencia_usadas",
    "hardware",
    "licencia",
    "seed_estado",
    "versiones_instrumento",
    "timestamp",
)

# Campos NO materiales para la comparación: se espera que difieran entre runs y no
# invalidan la comparación (el timestamp SIEMPRE cambia — si contara, ningún par de
# repetibilidad sería legítimo).
NON_MATERIAL: frozenset[str] = frozenset({"timestamp"})

# Campos ADITIVOS (post-C1) con default: un fingerprint escrito a mano o previo puede no
# traerlos y se lee igual. ``capture`` (la única vía real) SIEMPRE los completa.
_OPTIONAL_FIELDS: frozenset[str] = frozenset({"examen"})

# Estados de run que NO son comparables (data-model Run: interrupted/invalid NUNCA).
_COMPARABLE_STATES = frozenset({"completed"})


@dataclass(frozen=True)
class Fingerprint:
    """Huella inmutable de un run. Construir con ``capture`` (timestamp inyectado)."""
    producto: dict
    masking_por_scope: dict
    config_nlp: dict
    workers_procesos: dict
    limites_recursos: dict
    gate: dict
    corpus: dict
    mix_y_cadencia_usadas: dict
    hardware: dict
    licencia: dict
    seed_estado: str
    versiones_instrumento: dict
    timestamp: str
    # ``examen``: QUÉ examen se corrió, no solo con qué config. El programa del stub
    # (latencias, token_rate, duración de stream, error_rate) y las fases (nombre,
    # duración, arrival_factor) son MATERIALES: el drill de saturación y el gate 125
    # oficial comparten gate/mix/cadencia y sin esto sus fingerprints salían idénticos —
    # el comparador declaraba «LEGÍTIMA» la comparación de dos exámenes distintos.
    # Va al final por la regla de dataclasses (campo con default), no por importancia:
    # su lugar canónico en el JSON lo fija FINGERPRINT_FIELDS (justo después de `gate`).
    examen: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Dict JSON-serializable en el orden canónico de FR-009 (para fingerprint.json)."""
        return {k: getattr(self, k) for k in FINGERPRINT_FIELDS}

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Fingerprint":
        faltan = [k for k in FINGERPRINT_FIELDS
                  if k not in data and k not in _OPTIONAL_FIELDS]
        if faltan:
            raise ValueError(f"fingerprint incompleto (FR-009): faltan {faltan}")
        return cls(**{k: data[k] for k in FINGERPRINT_FIELDS if k in data})


def capture(*, producto: dict, masking_por_scope: dict, config_nlp: dict,
            workers_procesos: dict, limites_recursos: dict, gate: dict, corpus: dict,
            mix_y_cadencia_usadas: dict, hardware: dict, licencia: dict,
            seed_estado: str, versiones_instrumento: dict, timestamp: str,
            examen: Union[dict, None] = None) -> Fingerprint:
    """Captura un fingerprint. ``timestamp`` se INYECTA (nunca se lee del reloj acá).

    ``gate`` lleva ``{n, version, kind}``: el KIND del run es material — un drill y un
    gate oficial del mismo número NO son el mismo examen. ``examen`` lleva el programa
    del stub y las fases (ver el docstring del campo).
    """
    return Fingerprint(
        producto=producto, masking_por_scope=masking_por_scope, config_nlp=config_nlp,
        workers_procesos=workers_procesos, limites_recursos=limites_recursos, gate=gate,
        corpus=corpus, mix_y_cadencia_usadas=mix_y_cadencia_usadas, hardware=hardware,
        licencia=licencia, seed_estado=seed_estado,
        versiones_instrumento=versiones_instrumento, timestamp=timestamp,
        examen=dict(examen or {}),
    )


# ── Comparación ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FieldDiff:
    """Una diferencia material entre dos fingerprints, con ruta legible."""
    path: str
    izquierda: object
    derecha: object

    def __str__(self) -> str:
        return f"{self.path}: {self.izquierda!r} != {self.derecha!r}"


@dataclass
class ComparisonResult:
    """Resultado de comparar dos fingerprints.

    - ``comparable``: hay base para comparar (ambos runs ``completed`` con fingerprint).
      Un run interrumpido/invalid → ``comparable = False``.
    - ``legitimate``: comparable Y sin diferencia material → las métricas SÍ se comparan.
      Con cualquier diff material → ``legitimate = False`` (comparación ilegítima).
    - ``diffs``: el detalle del diff (lo que hace la ilegitimidad accionable).
    - ``motivo``: explicación humana.
    """
    comparable: bool
    legitimate: bool
    diffs: list = field(default_factory=list)
    motivo: str = ""

    def __bool__(self) -> bool:
        return self.legitimate

    @property
    def resumen(self) -> str:
        if not self.comparable:
            return f"NO COMPARABLE — {self.motivo}"
        if self.legitimate:
            return "LEGÍTIMA — fingerprints idénticos, las métricas son comparables"
        detalle = "; ".join(str(d) for d in self.diffs)
        return f"ILEGÍTIMA — diff material ANTES de métricas: {detalle}"


def _as_dict(fp: Union[Fingerprint, dict]) -> dict:
    if isinstance(fp, Fingerprint):
        return fp.to_dict()
    if isinstance(fp, dict):
        return dict(fp)
    raise TypeError(f"se esperaba Fingerprint o dict, no {type(fp).__name__}")


def _diff(a: object, b: object, path: str, out: list) -> None:
    """Diff recursivo; acumula FieldDiff en las hojas donde a != b."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            child = f"{path}.{k}" if path else str(k)
            if k not in a:
                out.append(FieldDiff(child, None, b[k]))
            elif k not in b:
                out.append(FieldDiff(child, a[k], None))
            else:
                _diff(a[k], b[k], child, out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(FieldDiff(path, a, b))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                _diff(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append(FieldDiff(path, a, b))


def compare(fp_a: Union[Fingerprint, dict, None], fp_b: Union[Fingerprint, dict, None],
            *, estado_a: str = "completed", estado_b: str = "completed",
            ignorar: frozenset = NON_MATERIAL) -> ComparisonResult:
    """Compara dos fingerprints. Diff material ANTES de cualquier métrica.

    Args:
        fp_a, fp_b: fingerprints (``Fingerprint`` o dict). ``None`` = run sin
            fingerprint (interrumpido/invalid) → no comparable.
        estado_a, estado_b: estado de cada Run; solo ``completed`` es comparable
            (data-model: interrupted/invalid NUNCA comparables).
        ignorar: campos top-level no materiales (por defecto ``timestamp``).

    Returns:
        ``ComparisonResult``. ``bool(result)`` es ``True`` solo si la comparación es
        legítima (comparable + sin diff material).
    """
    if fp_a is None or fp_b is None:
        cuales = [n for n, fp in (("a", fp_a), ("b", fp_b)) if fp is None]
        return ComparisonResult(comparable=False, legitimate=False,
                                motivo=f"run(s) sin fingerprint (interrumpido/invalid): {cuales}")
    if estado_a not in _COMPARABLE_STATES or estado_b not in _COMPARABLE_STATES:
        malos = {"a": estado_a, "b": estado_b}
        return ComparisonResult(comparable=False, legitimate=False,
                                motivo=f"run no 'completed' (interrupted/invalid): {malos}")

    da, db = _as_dict(fp_a), _as_dict(fp_b)
    diffs: list = []
    keys = (set(da) | set(db)) - set(ignorar)
    for k in sorted(keys):
        if k not in da:
            diffs.append(FieldDiff(k, None, db[k]))
        elif k not in db:
            diffs.append(FieldDiff(k, da[k], None))
        else:
            _diff(da[k], db[k], k, diffs)

    if diffs:
        return ComparisonResult(comparable=True, legitimate=False, diffs=diffs,
                                motivo="fingerprints con diferencia material")
    return ComparisonResult(comparable=True, legitimate=True,
                            motivo="fingerprints idénticos")
