"""Tests del evaluador de SLO (spec 035, T025/T028; contract ``run-report.md``).

Con FIXTURES sintéticos — sin stack, sin k6. Cubren los casos del data-model: los tres
estados del contador de auditoría (0/N/null) + el retroceso, la reconciliación, los
canarios, los bloqueos durables, la validez del instrumento (modelo abierto) y el cálculo
de overhead. Frontera de tests (DevFlow §3): pytest prueba el INSTRUMENTO con datos
sintéticos; los runs prueban el producto.
"""
from __future__ import annotations

import copy

import pytest

from basa_harness.reporting import load_gate_by_number, render_report
from basa_harness.reporting.evaluator import eval_audit, evaluate

GATE = load_gate_by_number(125)
TS = "2026-08-12T00:00:00Z"


# ── fixtures sintéticos limpios (un run que PASA) ─────────────────────────────────────

def _health(lost: object) -> dict:
    """Respuesta /health con el bloque audit (tier compliance). ``lost`` = lost_events."""
    return {"status": "healthy", "service": "backend", "version": "1.0.0",
            "audit": {"mode": "block", "lost_events": lost, "last_failure_at": None}}


def _clean_k6_summary() -> dict:
    def lat(p50, p95, p99, mx):
        return {"latency_ms": {"p50": p50, "p95": p95, "p99": p99, "max": mx, "count": 100},
                "dropped_iterations": 0, "requests": 100, "errors": 0}
    surfaces = {
        "chat": lat(812, 830, 845, 900),          # stub chat = 800 → overhead p50 = 12
        "extension": lat(40, 55, 70, 120),         # stub ext = 0 → overhead = latencia
        "admin": lat(15, 22, 30, 60),
    }
    coding = lat(650, 690, 720, 800)
    coding["ttft_ms"] = {"p50": 612, "p95": 640, "p99": 700, "max": 780, "count": 100}
    coding["stream_cuts"] = 0
    surfaces["coding"] = coding
    return {"schema": "basa-harness/k6-summary@1", "gate": 125, "surfaces": surfaces,
            "dropped_iterations_total": 0, "auditable_events": 2250}


def _clean_stub_report() -> dict:
    return {"run_id": "r", "leak_count": 0, "canarios_detectados": [], "canary_set_size": 64,
            "trafico_no_auditable": {"count": 0, "requests": []},
            "pacing_drift_ms": {"p50": 0.2, "p95": 0.8, "p99": 1.2, "max": 2.0, "n": 100},
            "cpu_pct": 24.0, "valido": True}


def _clean_reconciliation() -> dict:
    return {"eventos_guion": 2250, "filas_persistidas": 2250,
            "bloqueos_provocados": 40, "con_fila": 40}


def _evaluate(**over):
    kw = dict(k6_summary=_clean_k6_summary(), health_initial=_health(3),
              health_final=_health(3), stub_report=_clean_stub_report(),
              reconciliation=_clean_reconciliation())
    kw.update(over)
    return evaluate(GATE, run_id="20260812-g125-01", timestamp=TS, **kw)


# ── global PASS limpio ────────────────────────────────────────────────────────────────

def test_run_limpio_global_pass():
    v = _evaluate()
    assert v.estado == "completed"
    assert v.global_veredicto == "PASS"
    assert all(s.veredicto == "PASS" for s in v.slos)
    # los 4 SLO de oro, en orden canónico
    assert [s.slo for s in v.slos] == [
        "audit_lost_events_delta_zero", "reconciliation_rows",
        "zero_raw_canaries", "blocked_rows_durable_100"]
    assert v.to_dict()["global"] == "PASS"


def test_verdict_determinista():
    """Mismos insumos → mismo verdict.json byte a byte (determinismo, timestamp inyectado)."""
    assert _evaluate().to_json() == _evaluate().to_json()


# ── SLO (a): contador 0 / N / null / retroceso ────────────────────────────────────────

def test_audit_delta_cero_pass():
    v = _evaluate(health_initial=_health(3), health_final=_health(3))
    a = _slo(v, "audit_lost_events_delta_zero")
    assert a.medido == 0 and a.veredicto == "PASS"


def test_audit_delta_positivo_fail():
    v = _evaluate(health_initial=_health(3), health_final=_health(5))
    a = _slo(v, "audit_lost_events_delta_zero")
    assert a.medido == 2 and a.veredicto == "FAIL"
    assert v.global_veredicto == "FAIL" and v.estado == "completed"


def test_audit_null_es_fail_no_cero():
    """lost_events=null (Redis ilegible) ⇒ FAIL; JAMÁS se interpreta como 0."""
    v = _evaluate(health_initial=_health(0), health_final=_health(None))
    a = _slo(v, "audit_lost_events_delta_zero")
    assert a.medido is None and a.veredicto == "FAIL"
    # el sistema falló pero el examen es VÁLIDO (no invalid): global FAIL
    assert v.estado == "completed" and v.global_veredicto == "FAIL"


def test_audit_null_inicial_tambien_fail():
    v = _evaluate(health_initial=_health(None), health_final=_health(0))
    assert _slo(v, "audit_lost_events_delta_zero").veredicto == "FAIL"


def test_audit_contador_retrocede_invalid():
    """final < inicial ⇒ reset del almacén ⇒ run INVALID (no hay veredicto)."""
    v = _evaluate(health_initial=_health(5), health_final=_health(2))
    assert v.estado == "invalid"
    assert v.global_veredicto == "INVALID"
    assert "retrocedió" in (v.invalid_reason or "")


def test_audit_bloque_ausente_es_run_invalido_no_fail():
    """Bloque audit AUSENTE = credencial insuficiente del evaluador (bug del harness) ⇒
    run inválido; distinto de null (que es FAIL del sistema)."""
    sin_audit = {"status": "healthy", "service": "backend", "version": "1.0.0"}
    v = _evaluate(health_initial=sin_audit, health_final=sin_audit)
    assert v.estado == "invalid" and v.global_veredicto == "INVALID"
    assert "credencial" in (v.invalid_reason or "")


def test_eval_audit_directo_los_tres_estados():
    # 0/0 → PASS Δ0
    res, inv = eval_audit(_health(0), _health(0))
    assert res.medido == 0 and res.veredicto == "PASS" and inv is None
    # N con delta → FAIL
    res, inv = eval_audit(_health(1), _health(4))
    assert res.medido == 3 and res.veredicto == "FAIL" and inv is None
    # null → FAIL, no invalid
    res, inv = eval_audit(_health(1), _health(None))
    assert res.medido is None and res.veredicto == "FAIL" and inv is None
    # retroceso → invalid
    res, inv = eval_audit(_health(4), _health(1))
    assert inv is not None


# ── SLO (b): reconciliación ───────────────────────────────────────────────────────────

def test_reconciliacion_mismatch_fail():
    recon = _clean_reconciliation()
    recon["filas_persistidas"] = 2238   # faltan 12
    v = _evaluate(reconciliation=recon)
    b = _slo(v, "reconciliation_rows")
    assert b.medido == -12 and b.veredicto == "FAIL"
    assert v.global_veredicto == "FAIL"


def test_reconciliacion_datos_faltantes_fail():
    v = _evaluate(reconciliation={"bloqueos_provocados": 0, "con_fila": 0})
    assert _slo(v, "reconciliation_rows").veredicto == "FAIL"


# ── SLO (c): canarios crudos ──────────────────────────────────────────────────────────

def test_canario_detectado_slo_c_fail():
    rep = _clean_stub_report()
    rep["leak_count"] = 1
    rep["canarios_detectados"] = [{"canary_id": "canary-x", "surface": "/v1/chat/completions",
                                   "request_id": "req-000042"}]
    v = _evaluate(stub_report=rep)
    c = _slo(v, "zero_raw_canaries")
    assert c.medido == 1 and c.veredicto == "FAIL"
    assert v.global_veredicto == "FAIL"


def test_canario_leak_count_derivado_de_evidencia():
    rep = _clean_stub_report()
    del rep["leak_count"]
    rep["canarios_detectados"] = [{"canary_id": "a"}, {"canary_id": "b"}]
    v = _evaluate(stub_report=rep)
    assert _slo(v, "zero_raw_canaries").medido == 2


# ── SLO (d): bloqueos con fila durable ────────────────────────────────────────────────

def test_bloqueo_sin_fila_durable_fail():
    recon = _clean_reconciliation()
    recon["con_fila"] = 38   # 2 bloqueos sin rastro
    v = _evaluate(reconciliation=recon)
    d = _slo(v, "blocked_rows_durable_100")
    assert d.medido == pytest.approx(38 / 40) and d.veredicto == "FAIL"


def test_bloqueos_cero_es_pass_vacuo():
    recon = _clean_reconciliation()
    recon["bloqueos_provocados"] = 0
    recon["con_fila"] = 0
    v = _evaluate(reconciliation=recon)
    d = _slo(v, "blocked_rows_durable_100")
    assert d.medido == 1.0 and d.veredicto == "PASS"


# ── Instrumento (modelo abierto + headroom) ───────────────────────────────────────────

def test_dropped_iterations_invalida_instrumento():
    """dropped_iterations > 0 ⇒ k6 no sostuvo la tasa (modelo cerrado) ⇒ instrumento
    inválido ⇒ run inválido (aunque los 4 SLO pasen)."""
    k6 = _clean_k6_summary()
    k6["dropped_iterations_total"] = 7
    v = _evaluate(k6_summary=k6)
    assert v.instrumento["valido"] is False
    assert v.instrumento["dropped_iterations"] == 7
    assert v.global_veredicto == "INVALID" and v.estado == "invalid"


def test_stub_sin_headroom_invalida_instrumento():
    rep = _clean_stub_report()
    rep["valido"] = False
    rep["pacing_drift_ms"]["p99"] = 8.0   # > 5 ms
    v = _evaluate(stub_report=rep)
    assert v.instrumento["valido"] is False
    assert v.global_veredicto == "INVALID"


def test_trafico_no_auditable_invalida_instrumento():
    rep = _clean_stub_report()
    rep["trafico_no_auditable"] = {"count": 3, "requests": []}
    v = _evaluate(stub_report=rep)
    assert v.instrumento["valido"] is False


def test_harness_errors_invalida_instrumento():
    """A3: una iteración que no consigue autenticar hace `harness_errors.add(1); return`
    ANTES de contar el evento auditable, así que la carga desaparece SIN romper la
    reconciliación (bajan eventos y filas a la vez). Sin esta guarda, un run con el login
    storm fallando en masa certificaría PASS habiendo entregado una fracción de la carga
    programada, con dropped_iterations=0."""
    k6 = _clean_k6_summary()
    k6["harness_errors"] = 412
    v = _evaluate(k6_summary=k6)
    assert v.instrumento["valido"] is False
    assert v.instrumento["harness_errors"] == 412
    assert any("harness_errors" in r for r in v.instrumento["razones_invalidez"])
    assert v.global_veredicto == "INVALID" and v.estado == "invalid"


def test_harness_errors_en_cero_no_molesta():
    k6 = _clean_k6_summary()
    k6["harness_errors"] = 0
    v = _evaluate(k6_summary=k6)
    assert v.instrumento["valido"] is True
    assert v.instrumento["harness_errors"] == 0


def test_summary_sin_harness_errors_no_inventa_la_clave():
    """El summary sintético del dry-run no trae el contador: la clave es CONDICIONAL para
    que el verdict del dry-run oficial siga byte-idéntico."""
    k6 = _clean_k6_summary()
    k6.pop("harness_errors", None)
    v = _evaluate(k6_summary=k6)
    assert v.instrumento["valido"] is True
    assert "harness_errors" not in v.instrumento


# ── Overhead (FR-008) ─────────────────────────────────────────────────────────────────

def test_overhead_medido_menos_programado():
    """overhead = latencia medida − latencia programada del stub (chat = 800 ms)."""
    v = _evaluate()
    chat = v.overhead["chat"]
    assert chat["programada_ms"] == 800.0
    assert chat["overhead_ms"]["p50"] == 12.0    # 812 − 800
    assert chat["overhead_ms"]["p95"] == 30.0    # 830 − 800
    assert chat["overhead_ms"]["p99"] == 45.0    # 845 − 800
    assert chat["overhead_ms"]["max"] == 100.0   # 900 − 800


def test_overhead_ttft_solo_coding():
    v = _evaluate()
    coding = v.overhead["coding"]
    assert coding["ttft_programada_ms"] == 600.0
    assert coding["ttft_overhead_ms"]["p50"] == 12.0   # 612 − 600
    assert coding["stream_cuts"] == 0
    # las superficies no-SSE no tienen TTFT
    assert "ttft_overhead_ms" not in v.overhead["chat"]


def test_por_fase_presente():
    v = _evaluate()
    assert v.por_fase  # al menos la fase sostenida del 125
    (phase, block), = v.por_fase.items()
    assert phase == "sustained"
    assert "chat" in block["surfaces"]


# ── Reporte comparable ────────────────────────────────────────────────────────────────

def test_reporte_secciones_fijas():
    v = _evaluate()
    md = render_report(v, None)
    for encabezado in ("# Reporte de run", "## Veredicto por SLO",
                       "## Overhead por superficie", "## Por fase",
                       "## Instrumento", "## Fingerprint", "## Evidencia"):
        assert encabezado in md
    assert "✅ PASS" in md


def test_reporte_invalid_marca_parcial():
    v = _evaluate(health_initial=_health(5), health_final=_health(2))
    md = render_report(v, None)
    assert "INVÁLIDO" in md and "PARCIAL" in md


# ── helper ────────────────────────────────────────────────────────────────────────────

def _slo(verdict, name):
    return next(s for s in verdict.slos if s.slo == name)
