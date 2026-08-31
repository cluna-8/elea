"""Reporte humano comparable del run (spec 035, T026; contract ``run-report.md``
§reporte.md).

Genera ``reporte.md`` con el ORDEN FIJO de secciones del contrato — esa estabilidad es lo
que permite comparar dos runs del mismo ``gate+version`` con un simple ``diff`` (US3):

1. **Veredicto** global + tabla por SLO.
2. **Overhead por superficie** — p50/p95/p99/max (``overhead = medido − programado``);
   TTFT y cortes de stream SOLO en coding.
3. **Por fase** (250/500): tormenta vs sostenido; pico y recuperación.
4. **Instrumento**: evidencia de modelo abierto (dropped_iterations) + headroom del stub.
5. **Fingerprint** (inline — reusa ``Fingerprint.to_json``).
6. **Evidencia**: refs a k6 summary, spool, tarball de logs, export de métricas.

DETERMINISMO: el reporte se arma SOLO del ``Verdict`` + ``Fingerprint`` (timestamps ya
inyectados). Sin reloj, sin red, sin observabilidad (R3).
"""
from __future__ import annotations

from typing import Optional, Union

from .evaluator import PERCENTILES, Verdict
from .fingerprint import Fingerprint

_GLOBAL_BADGE = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "INVALID": "⚠️ INVÁLIDO"}
_SLO_BADGE = {"PASS": "✅", "FAIL": "❌"}


def render_report(verdict: Verdict, fingerprint: Union[Fingerprint, dict, None] = None,
                  *, evidence: Optional[dict] = None) -> str:
    """Arma el ``reporte.md`` completo (string) de un run."""
    lines: list[str] = []
    _section_veredicto(lines, verdict)
    _section_overhead(lines, verdict)
    _section_por_fase(lines, verdict)
    _section_instrumento(lines, verdict)
    _section_fingerprint(lines, fingerprint)
    _section_evidencia(lines, evidence)
    return "\n".join(lines).rstrip() + "\n"


# ── 1. Veredicto ──────────────────────────────────────────────────────────────────────

def _section_veredicto(out: list, v: Verdict) -> None:
    g = v.gate or {}
    badge = _GLOBAL_BADGE.get(v.global_veredicto, v.global_veredicto)
    out.append(f"# Reporte de run — {v.run_id}")
    out.append("")
    out.append(f"- **Gate**: {g.get('n')} · versión {g.get('version')}")
    out.append(f"- **Tipo de run** (kind): {v.kind}")
    out.append(f"- **Estado**: {v.estado}")
    out.append(f"- **Veredicto global**: {badge}")
    out.append(f"- **Timestamp**: {v.timestamp}")
    if v.invalid_reason:
        out.append(f"- **Motivo de invalidez**: {v.invalid_reason}")
        out.append("  > Un run inválido/interrumpido conserva reporte PARCIAL y NO es "
                   "comparable con otros (US3).")
    for nota in v.notas:
        out.append(f"- **Nota**: {nota}")
    out.append("")
    out.append("## Veredicto por SLO")
    out.append("")
    out.append("| SLO | Medido | Veredicto | Detalle |")
    out.append("|---|---|---|---|")
    for s in v.slos:
        badge_s = _SLO_BADGE.get(s.veredicto, s.veredicto)
        out.append(f"| `{s.slo}` | {_fmt(s.medido)} | {badge_s} {s.veredicto} | "
                   f"{_detalle_breve(s.detalle)} |")
    out.append("")


def _detalle_breve(detalle: dict) -> str:
    partes = []
    for k, val in detalle.items():
        if k in ("fuente", "evidencia", "nota"):
            continue
        partes.append(f"{k}={_fmt(val)}")
    nota = detalle.get("nota")
    txt = ", ".join(partes)
    if nota:
        txt = (txt + " — " if txt else "") + str(nota)
    return _escape_cell(txt) or "—"


# ── 2. Overhead por superficie ────────────────────────────────────────────────────────

def _section_overhead(out: list, v: Verdict) -> None:
    out.append("## Overhead por superficie")
    out.append("")
    out.append("Overhead = latencia medida − latencia programada del stub (FR-008). El "
               "examen mide el COSTE que el producto agrega sobre un proveedor de latencia "
               "conocida.")
    out.append("")
    if not v.overhead:
        out.append("_Sin datos de overhead (¿run en seco o k6 no corrió?)._")
        out.append("")
        return
    _overhead_table(out, v.overhead)


def _overhead_table(out: list, overhead: dict) -> None:
    out.append("| Superficie | Programada (ms) | " +
               " | ".join(f"overhead {p} (ms)" for p in PERCENTILES) + " |")
    out.append("|---|---|" + "|".join(["---"] * len(PERCENTILES)) + "|")
    for surface, e in overhead.items():
        ov = e.get("overhead_ms") or {}
        row = [surface, _fmt(e.get("programada_ms"))]
        row += [_fmt(ov.get(p)) for p in PERCENTILES]
        out.append("| " + " | ".join(row) + " |")
    out.append("")
    # Bloque coding: TTFT + cortes de stream (única SSE).
    coding = _first_with_ttft(overhead)
    if coding:
        surface, e = coding
        out.append(f"### Coding (SSE) — TTFT y cortes · superficie `{surface}`")
        out.append("")
        tov = e.get("ttft_overhead_ms") or {}
        out.append("| Métrica | Programada (ms) | " +
                   " | ".join(f"{p} (ms)" for p in PERCENTILES) + " |")
        out.append("|---|---|" + "|".join(["---"] * len(PERCENTILES)) + "|")
        out.append("| TTFT overhead | " + _fmt(e.get("ttft_programada_ms")) + " | " +
                   " | ".join(_fmt(tov.get(p)) for p in PERCENTILES) + " |")
        out.append("")
        out.append(f"- **Cortes de stream** (close/error a mitad): {e.get('stream_cuts', 0)}")
        out.append("")


def _first_with_ttft(overhead: dict):
    for surface, e in overhead.items():
        if "ttft_overhead_ms" in e or "ttft_medida_ms" in e:
            return surface, e
    return None


# ── 3. Por fase ───────────────────────────────────────────────────────────────────────

def _section_por_fase(out: list, v: Verdict) -> None:
    out.append("## Por fase")
    out.append("")
    if not v.por_fase:
        out.append("_Fase única (sin desglose)._")
        out.append("")
        return
    if len(v.por_fase) == 1:
        (phase, block), = v.por_fase.items()
        out.append(f"Fase única `{phase}` "
                   f"(dropped_iterations={block.get('dropped_iterations', 0)}).")
        out.append("")
        return
    for phase, block in v.por_fase.items():
        out.append(f"### Fase `{phase}` "
                   f"(dropped_iterations={block.get('dropped_iterations', 0)})")
        out.append("")
        surfaces = block.get("surfaces") or {}
        if surfaces:
            _overhead_table(out, surfaces)
        else:
            out.append("_Sin datos de superficie en esta fase._")
            out.append("")


# ── 4. Instrumento ────────────────────────────────────────────────────────────────────

def _section_instrumento(out: list, v: Verdict) -> None:
    inst = v.instrumento or {}
    out.append("## Instrumento (modelo abierto + headroom del stub)")
    out.append("")
    valido = inst.get("valido")
    out.append(f"- **Instrumento válido**: {'sí' if valido else 'NO'}")
    out.append(f"- **dropped_iterations**: {inst.get('dropped_iterations')} "
               "(evidencia de modelo abierto: si > 0, k6 no sostuvo la tasa ⇒ run inválido)")
    out.append(f"- **Drift de pacing del stub p99**: {inst.get('stub_drift_p99_ms')} ms "
               "(umbral 5 ms)")
    out.append(f"- **CPU del stub**: {inst.get('stub_cpu_pct')} % (umbral 60%)")
    out.append(f"- **Tráfico no auditable**: {inst.get('trafico_no_auditable')} "
               "(punto ciego del detector de canarios si > 0)")
    for razon in inst.get("razones_invalidez") or []:
        out.append(f"  - ⚠️ {razon}")
    out.append("")


# ── 5. Fingerprint ────────────────────────────────────────────────────────────────────

def _section_fingerprint(out: list, fingerprint: Union[Fingerprint, dict, None]) -> None:
    out.append("## Fingerprint")
    out.append("")
    if fingerprint is None:
        out.append("_Sin fingerprint (run sin huella — no comparable)._")
        out.append("")
        return
    if isinstance(fingerprint, Fingerprint):
        body = fingerprint.to_json()
    else:
        import json
        body = json.dumps(fingerprint, ensure_ascii=False, indent=2, sort_keys=False)
    out.append("Dos runs solo se comparan si comparten fingerprint (el comparador diffea "
               "esto ANTES que las métricas).")
    out.append("")
    out.append("```json")
    out.append(body)
    out.append("```")
    out.append("")


# ── 6. Evidencia ──────────────────────────────────────────────────────────────────────

def _section_evidencia(out: list, evidence: Optional[dict]) -> None:
    out.append("## Evidencia")
    out.append("")
    if not evidence:
        out.append("_Sin refs de evidencia pesada (se persisten en la plataforma R3, "
                   "`/srv/itv-runs/<id>/`)._")
        out.append("")
        return
    for k, ref in evidence.items():
        out.append(f"- **{k}**: `{ref}`")
    out.append("")


# ── helpers de formato ────────────────────────────────────────────────────────────────

def _fmt(v: object) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "sí" if v else "no"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def _escape_cell(txt: str) -> str:
    return txt.replace("|", "\\|").replace("\n", " ")
