"""Tests del orquestador del gate (spec 035, T027/T028; quickstart esc. 3 y 7).

Con FIXTURES y hooks inyectados — sin backend, sin stub, sin k6. Cubren:

- **dry-run** (esc. 3 en seco): corre sin stack ni k6 y produce la estructura COMPLETA
  del run (verdict.json + fingerprint.json + reporte.md) con datos sintéticos limpios;
- **run interrumpido** (esc. 7): reporte PARCIAL marcado, nunca un dir a medias;
- **precondición no cumplida**: aborta ANTES de generar carga (k6 no se lanza);
- **pipeline completo con fakes**: health/stub/k6/reconcile inyectados → verdict real.
"""
from __future__ import annotations

import json

import pytest

from basa_harness.orchestrator import Orchestrator

TS = "2026-08-12T00:00:00Z"


# ── fakes de los efectos externos ─────────────────────────────────────────────────────

class FakeStub:
    def __init__(self, report):
        self._report = report
        self.calls = []

    def reset(self):
        self.calls.append("reset")

    def config(self, cfg):
        self.calls.append(("config", cfg))

    def canaries(self, canaries):
        self.calls.append(("canaries", len(canaries)))

    def finalize(self):
        self.calls.append("finalize")

    def report(self):
        return self._report


def _health(lost):
    return {"status": "healthy", "service": "b", "version": "1.0.0",
            "audit": {"mode": "block", "lost_events": lost, "last_failure_at": None}}


def _clean_summary():
    def lat():
        return {"latency_ms": {"p50": 810, "p95": 830, "p99": 845, "max": 900, "count": 10},
                "dropped_iterations": 0, "requests": 10}
    surfaces = {"chat": lat(), "extension": lat(), "admin": lat()}
    coding = lat()
    coding["ttft_ms"] = {"p50": 610, "p95": 640, "p99": 700, "max": 780, "count": 10}
    coding["stream_cuts"] = 0
    surfaces["coding"] = coding
    return {"surfaces": surfaces, "dropped_iterations_total": 0, "auditable_events": 40}


def _clean_stub_report():
    return {"leak_count": 0, "canarios_detectados": [], "canary_set_size": 8,
            "trafico_no_auditable": {"count": 0, "requests": []},
            "pacing_drift_ms": {"p99": 1.0}, "cpu_pct": 20.0, "valido": True}


def _orch(tmp_path, **kw):
    base = dict(gate=125, run_id="20260812-g125-01", runs_dir=tmp_path,
                timestamp=TS, n_canaries=8, n_corpus_docs=8)
    base.update(kw)
    return Orchestrator(**base)


# ── dry-run ───────────────────────────────────────────────────────────────────────────

def test_dry_run_produce_estructura_completa(tmp_path):
    orch = _orch(tmp_path, dry_run=True)
    verdict = orch.run()
    d = orch.run_dir
    for name in ("verdict.json", "fingerprint.json", "reporte.md",
                 "pool.json", "corpus.json", "canaries.json", "k6_config.json",
                 "summary.json"):
        assert (d / name).exists(), f"falta {name}"
    assert verdict.estado == "completed"
    assert verdict.global_veredicto == "PASS"     # datos sintéticos limpios
    assert verdict.kind == "dry-run"
    assert any("sintéticos" in n for n in verdict.notas)
    # k6 NO se lanzó (no hay binario ni stack)
    assert orch.k6_launched is False


def test_dry_run_identidades_offline(tmp_path):
    """El pool se deriva OFFLINE del plan de población (sin backend). 125 + 1 bootstrap."""
    orch = _orch(tmp_path, dry_run=True)
    orch.run()
    pool = json.loads((orch.run_dir / "pool.json").read_text())
    assert len(pool) == 126           # 125 miembros + admin bootstrap
    assert pool[0]["bootstrap"] is True
    # passwords deterministas (cumplen la política del backend)
    assert all(len(p["password"]) >= 12 for p in pool)


def test_dry_run_canarios_unicos_del_run(tmp_path):
    orch = _orch(tmp_path, dry_run=True)
    orch.run()
    canaries = json.loads((orch.run_dir / "canaries.json").read_text())
    assert len(canaries) == 8
    assert all(c["run_id"] == "20260812-g125-01" for c in canaries)
    valores = {c["value"] for c in canaries}
    assert len(valores) == 8          # únicos


def test_dry_run_verdict_json_valido(tmp_path):
    orch = _orch(tmp_path, dry_run=True)
    orch.run()
    data = json.loads((orch.run_dir / "verdict.json").read_text())
    assert data["gate"] == {"n": 125, "version": "1.0.0"}
    assert {s["slo"] for s in data["slos"]} == {
        "audit_lost_events_delta_zero", "reconciliation_rows",
        "zero_raw_canaries", "blocked_rows_durable_100"}


# ── run interrumpido (esc. 7) ─────────────────────────────────────────────────────────

def test_run_interrumpido_reporte_parcial(tmp_path):
    def k6_boom(_cfg):
        raise KeyboardInterrupt()

    orch = _orch(tmp_path, dry_run=False,
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(_clean_stub_report()),
                 k6_runner=k6_boom, reconcile_fn=lambda s: {})
    verdict = orch.run()
    assert verdict.estado == "interrupted"
    assert verdict.global_veredicto == "INVALID"
    assert "interrumpido" in (verdict.invalid_reason or "")
    # el dir tiene reporte PARCIAL, nunca examen a medias
    assert (orch.run_dir / "verdict.json").exists()
    assert (orch.run_dir / "reporte.md").exists()
    md = (orch.run_dir / "reporte.md").read_text()
    assert "PARCIAL" in md


# ── precondición no cumplida → aborta antes de generar carga ──────────────────────────

def test_precondicion_drift_aborta_antes_de_carga(tmp_path):
    """masking observado OFF contra un gate que lo exige ON ⇒ aborta ANTES de k6."""
    observed = {"masking": {"default": "off"}, "nlp_fail_mode": "block"}
    called = {"k6": False}

    def k6_runner(_cfg):
        called["k6"] = True
        return _clean_summary()

    orch = _orch(tmp_path, dry_run=False, observed_stack_config=observed,
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(_clean_stub_report()),
                 k6_runner=k6_runner, reconcile_fn=lambda s: {})
    verdict = orch.run()
    assert verdict.estado == "invalid"
    assert verdict.global_veredicto == "INVALID"
    assert "precondición" in (verdict.invalid_reason or "")
    assert "masking" in (verdict.invalid_reason or "")
    assert called["k6"] is False          # NO se generó carga
    assert orch.k6_launched is False
    assert (orch.run_dir / "verdict.json").exists()


def test_precondicion_masking_on_no_es_drift(tmp_path):
    """masking observado ON (o el True de pyyaml) NO es drift — el gate lo exige ON."""
    observed = {"masking": {"default": True}, "nlp_fail_mode": "block"}
    orch = _orch(tmp_path, dry_run=False, observed_stack_config=observed,
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(_clean_stub_report()),
                 k6_runner=lambda cfg: _clean_summary(),
                 reconcile_fn=lambda s: {"eventos_guion": 40, "filas_persistidas": 40,
                                         "bloqueos_provocados": 0, "con_fila": 0})
    verdict = orch.run()
    assert verdict.estado == "completed"


# ── pipeline completo con fakes (run real simulado) ───────────────────────────────────

def test_pipeline_completo_con_fakes_pass(tmp_path):
    stub = FakeStub(_clean_stub_report())
    recon = {"eventos_guion": 40, "filas_persistidas": 40,
             "bloqueos_provocados": 4, "con_fila": 4}
    orch = _orch(tmp_path, dry_run=False,
                 health_fn=lambda cual: _health(0),
                 stub_client=stub, k6_runner=lambda cfg: _clean_summary(),
                 reconcile_fn=lambda s: recon)
    verdict = orch.run()
    assert verdict.estado == "completed" and verdict.global_veredicto == "PASS"
    assert orch.k6_launched is True
    # el stub se configuró en el orden esperado
    assert stub.calls[0] == "reset"
    assert "finalize" in stub.calls
    # el fingerprint quedó escrito con la config del gate
    fp = json.loads((orch.run_dir / "fingerprint.json").read_text())
    assert fp["gate"] == {"n": 125, "version": "1.0.0"}
    assert fp["versiones_instrumento"]["k6"] == "v1.8.0"


def test_pipeline_canario_detectado_fail(tmp_path):
    rep = _clean_stub_report()
    rep["leak_count"] = 1
    rep["canarios_detectados"] = [{"canary_id": "canary-x"}]
    orch = _orch(tmp_path, dry_run=False,
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(rep), k6_runner=lambda cfg: _clean_summary(),
                 reconcile_fn=lambda s: {"eventos_guion": 40, "filas_persistidas": 40,
                                         "bloqueos_provocados": 0, "con_fila": 0})
    verdict = orch.run()
    assert verdict.global_veredicto == "FAIL"
    assert verdict.estado == "completed"


def test_precondicion_deja_reporte_parcial(tmp_path):
    """Aborto por precondición: dir con reporte parcial coherente, jamás a medias."""
    orch = _orch(tmp_path, dry_run=False, observed_stack_config={"masking": {"default": "off"}},
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(_clean_stub_report()),
                 k6_runner=lambda cfg: _clean_summary(), reconcile_fn=lambda s: {})
    verdict = orch.run()   # aborta por precondición antes de k6
    assert verdict.estado == "invalid"
    assert (orch.run_dir / "verdict.json").exists()


def test_fallo_inesperado_produce_parcial_no_traceback(tmp_path):
    """Un fallo NO controlado del pipeline (no KeyboardInterrupt) → reporte PARCIAL
    invalid, nunca un directorio a medias ni un traceback que escape."""
    def boom(_cfg):
        raise RuntimeError("k6 explotó feo")

    orch = _orch(tmp_path, dry_run=False,
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(_clean_stub_report()),
                 k6_runner=boom, reconcile_fn=lambda s: {})
    verdict = orch.run()   # no re-lanza: captura y degrada
    assert verdict.estado == "invalid"
    assert verdict.global_veredicto == "INVALID"
    assert "fallo inesperado" in (verdict.invalid_reason or "")
    assert "RuntimeError" in (verdict.invalid_reason or "")
    assert (orch.run_dir / "verdict.json").exists()
    assert (orch.run_dir / "reporte.md").exists()
