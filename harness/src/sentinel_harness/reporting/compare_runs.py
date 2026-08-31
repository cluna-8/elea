"""Comparador de RUNS (US3) — capa encima de ``fingerprint.compare``.

Un número suelto sirve una vez; dos números comparables convierten el harness en el
instrumento con el que el departamento decide (¿el fix del pool alcanzó? ¿cuánto ganamos
con N workers?). La comparación es legítima SOLO si los fingerprints no difieren en nada
material (misma versión de producto, misma config, mismo gate+version, mismo hardware) —
esa parte la resuelve ``fingerprint.compare``. Encima de eso, este módulo compara los
VEREDICTOS y el overhead p95 dentro de la tolerancia de repetibilidad del gate (SC-005,
±10% vinculante en el ciclo 1).

Regla dura (data-model): un run ``interrupted``/``invalid`` NO es comparable — un examen
a medias no es un punto de referencia.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .fingerprint import compare as compare_fingerprints


@dataclass
class RunComparison:
    """Resultado de comparar dos runs completos.

    - ``comparable``: ambos runs ``completed`` con fingerprint (hereda de la comparación
      de fingerprints).
    - ``legitimate``: comparable Y fingerprints sin diff material → las métricas se
      comparan de verdad.
    - ``veredictos_coinciden``: los ``global`` de ambos verdicts son iguales.
    - ``overhead_dentro_tolerancia``: |Δ overhead p95| ≤ tolerancia del gate, por
      superficie. ``None`` si no se pudo evaluar (falta el dato o comparación ilegítima).
    - ``fingerprint_diffs``: el detalle del diff que hace ilegítima la comparación.
    - ``detalle_overhead``: por superficie, {a, b, delta_pct, dentro}.
    - ``motivo``: explicación humana accionable.
    """

    comparable: bool
    legitimate: bool
    veredictos_coinciden: Optional[bool]
    overhead_dentro_tolerancia: Optional[bool]
    fingerprint_diffs: list = field(default_factory=list)
    detalle_overhead: dict = field(default_factory=dict)
    motivo: str = ""

    def to_dict(self) -> dict:
        return {
            "comparable": self.comparable,
            "legitimate": self.legitimate,
            "veredictos_coinciden": self.veredictos_coinciden,
            "overhead_dentro_tolerancia": self.overhead_dentro_tolerancia,
            "fingerprint_diffs": self.fingerprint_diffs,
            "detalle_overhead": self.detalle_overhead,
            "motivo": self.motivo,
        }


def _overhead_p95_por_superficie(verdict: dict) -> dict:
    """Extrae {superficie: overhead_p95} del verdict (tolerante a formatos).

    Busca en ``verdict['overhead']`` un mapa superficie→percentiles con ``p95``; si no
    está, devuelve {} (la comparación de métricas se marcará no-evaluable, no rota).
    """
    overhead = verdict.get("overhead") or {}
    out: dict = {}
    if isinstance(overhead, dict):
        for superficie, datos in overhead.items():
            if isinstance(datos, dict) and datos.get("p95") is not None:
                try:
                    out[superficie] = float(datos["p95"])
                except (TypeError, ValueError):
                    continue
    return out


def compare_runs(
    run_a: dict,
    run_b: dict,
    *,
    tolerancia_pct: float = 10.0,
) -> RunComparison:
    """Compara dos runs. Cada run es un dict con al menos ``fingerprint`` y ``verdict``.

    ``tolerancia_pct`` es el ±% vinculante de overhead p95 del gate (SC-005). Recalibrarla
    es un cambio versionado de la definición del gate, no una decisión de este comparador.
    """
    fp_a, fp_b = run_a.get("fingerprint"), run_b.get("fingerprint")
    vr_a, vr_b = run_a.get("verdict") or {}, run_b.get("verdict") or {}
    estado_a = str(vr_a.get("estado", "completed"))
    estado_b = str(vr_b.get("estado", "completed"))

    fp_cmp = compare_fingerprints(fp_a, fp_b, estado_a=estado_a, estado_b=estado_b)

    # Un run no-completed no es comparable (data-model): corta acá.
    if not fp_cmp.comparable:
        return RunComparison(
            comparable=False,
            legitimate=False,
            veredictos_coinciden=None,
            overhead_dentro_tolerancia=None,
            fingerprint_diffs=fp_cmp.diffs,
            motivo=fp_cmp.motivo or "un run interrumpido/inválido no es un punto de referencia",
        )

    veredictos_coinciden = vr_a.get("global") == vr_b.get("global")

    # Si la comparación es ilegítima (diff material de fingerprint), NO comparamos métricas:
    # serían dos exámenes de cosas distintas.
    if not fp_cmp.legitimate:
        return RunComparison(
            comparable=True,
            legitimate=False,
            veredictos_coinciden=veredictos_coinciden,
            overhead_dentro_tolerancia=None,
            fingerprint_diffs=fp_cmp.diffs,
            motivo="fingerprints difieren en campos materiales: las métricas no se comparan "
                   "(compararías dos exámenes de cosas distintas)",
        )

    # Comparación legítima: overhead p95 por superficie dentro de la tolerancia.
    oa = _overhead_p95_por_superficie(vr_a)
    ob = _overhead_p95_por_superficie(vr_b)
    detalle: dict = {}
    todas_dentro = True
    evaluables = 0
    for superficie in sorted(set(oa) & set(ob)):
        a, b = oa[superficie], ob[superficie]
        base = max(abs(a), 1e-9)
        delta_pct = abs(b - a) / base * 100.0
        dentro = delta_pct <= tolerancia_pct
        detalle[superficie] = {"a": a, "b": b, "delta_pct": round(delta_pct, 2), "dentro": dentro}
        todas_dentro = todas_dentro and dentro
        evaluables += 1

    overhead_dentro = todas_dentro if evaluables else None
    if evaluables == 0:
        motivo = "comparación legítima; sin overhead p95 comparable en el verdict (nada que medir)"
    elif overhead_dentro:
        motivo = f"comparación legítima; overhead p95 dentro de ±{tolerancia_pct:g}% en {evaluables} superficie(s)"
    else:
        fuera = [s for s, d in detalle.items() if not d["dentro"]]
        motivo = f"comparación legítima; overhead p95 FUERA de ±{tolerancia_pct:g}% en: {', '.join(fuera)}"

    return RunComparison(
        comparable=True,
        legitimate=True,
        veredictos_coinciden=veredictos_coinciden,
        overhead_dentro_tolerancia=overhead_dentro,
        fingerprint_diffs=[],
        detalle_overhead=detalle,
        motivo=motivo,
    )
