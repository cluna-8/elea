"""Tests del orquestador del gate (spec 035, T027/T028; quickstart esc. 3 y 7).

Con FIXTURES y hooks inyectados — sin backend, sin stub, sin k6. Cubren:

- **dry-run** (esc. 3 en seco): corre sin stack ni k6 y produce la estructura COMPLETA
  del run (verdict.json + fingerprint.json + reporte.md) con datos sintéticos limpios;
- **run interrumpido** (esc. 7): reporte PARCIAL marcado, nunca un dir a medias;
- **precondición no cumplida**: aborta ANTES de generar carga (k6 no se lanza);
- **pipeline completo con fakes**: health/stub/k6/reconcile inyectados → verdict real;
- **corrida real (T031)**: ventana del run alrededor de k6, material de llave del pool del
  seeder y evidencia del conteo de auditoría.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from basa_harness.orchestrator import Orchestrator, main

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
    # el fingerprint quedó escrito con la config del gate (el kind del run es MATERIAL:
    # un drill y un gate oficial del mismo número no son el mismo examen)
    fp = json.loads((orch.run_dir / "fingerprint.json").read_text())
    assert fp["gate"] == {"n": 125, "version": "1.0.0", "kind": "gate_oficial"}
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


# ── corrida real: ventana, pool del seeder, evidencia del conteo (T031) ───────────────

class FakeReconcile:
    """Hook de reconciliación con ventana, como el ``HttpReconcile`` real."""

    def __init__(self, recon):
        self._recon = recon
        self.window = None
        self.llamado_con = None

    def set_window(self, desde, hasta):
        self.window = (desde, hasta)

    def __call__(self, summary):
        self.llamado_con = summary
        return dict(self._recon)


def _recon_limpia():
    return {"eventos_guion": 40, "filas_persistidas": 40,
            "bloqueos_provocados": 0, "con_fila": 0}


def _reloj_falso():
    """Reloj monotónico inyectable: un tick por llamada (t0 y t1 no pueden coincidir)."""
    base = datetime(2026, 8, 11, 9, 0, 0, tzinfo=timezone.utc)
    estado = {"n": 0}

    def ahora():
        estado["n"] += 1
        return base + timedelta(minutes=estado["n"])
    return ahora


def test_ventana_del_run_se_captura_alrededor_de_k6(tmp_path):
    """t0 ANTES de la carga y t1 DESPUÉS: es el rango sobre el que se cuentan las filas."""
    recon = FakeReconcile(_recon_limpia())
    marcas = {}

    def k6(cfg):
        marcas["durante"] = True
        return _clean_summary()

    orch = _orch(tmp_path, dry_run=False, now=_reloj_falso(),
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(_clean_stub_report()),
                 k6_runner=k6, reconcile_fn=recon)
    verdict = orch.run()

    assert verdict.global_veredicto == "PASS"
    assert marcas["durante"] is True
    assert recon.window == (orch.window_t0, orch.window_t1)
    assert orch.window_t0 < orch.window_t1
    # el timestamp del verdict sigue siendo el INYECTADO (el evaluador no mira relojes)
    assert verdict.timestamp == TS


def test_hook_sin_ventana_sigue_funcionando(tmp_path):
    """Un reconcile_fn simple (los fakes de siempre) no tiene set_window: no debe romper."""
    orch = _orch(tmp_path, dry_run=False,
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(_clean_stub_report()),
                 k6_runner=lambda cfg: _clean_summary(),
                 reconcile_fn=lambda s: _recon_limpia())
    assert orch.run().global_veredicto == "PASS"


def test_conteo_de_auditoria_queda_como_evidencia(tmp_path):
    recon = FakeReconcile(dict(_recon_limpia(), filas_rejected_saturated=0,
                               fuente="GET /api/v1/audit-logs"))
    orch = _orch(tmp_path, dry_run=False, now=_reloj_falso(),
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(_clean_stub_report()),
                 k6_runner=lambda cfg: _clean_summary(), reconcile_fn=recon)
    orch.run()

    data = json.loads((orch.run_dir / "reconciliation.json").read_text())
    assert data["filas_persistidas"] == 40
    assert data["ventana"]["desde"] == orch.window_t0.isoformat()
    assert data["ventana"]["hasta"] == orch.window_t1.isoformat()
    # y el reporte lo lista como evidencia del run
    assert "reconciliation.json" in (orch.run_dir / "reporte.md").read_text()


def _pool_del_seeder(tmp_path, *, con_keys=True):
    """Pool como el que emite `seeder.seed --emit-credentials` para el gate 125."""
    from basa_harness.seeder.population import (derive_password, load_population_by_gate,
                                                plan_members)
    from basa_harness.seeder.seed import DEFAULT_SEED
    pop = load_population_by_gate(125)
    creds = [{"username": pop.admin_username,
              "password": derive_password(DEFAULT_SEED, pop.admin_username),
              "role": "tenant_admin", "client_type": None, "tool_type": None,
              "bootstrap": True, "basa_key": None}]
    for m in plan_members(pop, DEFAULT_SEED):
        key = None
        if con_keys and m.client_type in ("desktop", "base_url"):
            key = f"sk-{m.username}"
        creds.append({"username": m.username, "password": m.password, "role": m.role,
                      "client_type": m.client_type, "tool_type": m.tool_type,
                      "basa_key": key})
    path = tmp_path / "pool-seeder.json"
    path.write_text(json.dumps(creds), encoding="utf-8")
    return path


def test_pool_file_injerta_la_basa_key_en_el_pool_de_k6(tmp_path):
    pool_file = _pool_del_seeder(tmp_path)
    orch = _orch(tmp_path, dry_run=False, pool_file=pool_file,
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(_clean_stub_report()),
                 k6_runner=lambda cfg: _clean_summary(),
                 reconcile_fn=lambda s: _recon_limpia())
    assert orch.run().global_veredicto == "PASS"

    pool = json.loads((orch.run_dir / "pool.json").read_text())
    porsuperficie = {"desktop": [], "base_url": [], "chat_ui": []}
    for entry in pool:
        if entry["client_type"] in porsuperficie:
            porsuperficie[entry["client_type"]].append(entry)
    # extensión y coding autentican con X-Basa-Key: TODAS tienen material…
    assert porsuperficie["desktop"] and all(e["basa_key"] for e in porsuperficie["desktop"])
    assert porsuperficie["base_url"] and all(e["basa_key"] for e in porsuperficie["base_url"])
    # …y el resto conserva el shape que espera common.js (password para el JWT).
    assert all(e["password"] for e in porsuperficie["chat_ui"])


def test_pool_sin_material_aborta_antes_de_generar_carga(tmp_path):
    pool_file = _pool_del_seeder(tmp_path, con_keys=False)
    lanzado = {"k6": False}

    def k6(cfg):
        lanzado["k6"] = True
        return _clean_summary()

    orch = _orch(tmp_path, dry_run=False, pool_file=pool_file,
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(_clean_stub_report()),
                 k6_runner=k6, reconcile_fn=lambda s: _recon_limpia())
    verdict = orch.run()
    assert verdict.estado == "invalid"
    assert "basa_key" in (verdict.invalid_reason or "")
    assert lanzado["k6"] is False          # no se quemó una ventana de examen
    assert orch.k6_launched is False


def test_pool_file_ilegible_es_accionable(tmp_path):
    malo = tmp_path / "pool.json"
    malo.write_text("{no json", encoding="utf-8")
    orch = _orch(tmp_path, dry_run=False, pool_file=malo,
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(_clean_stub_report()),
                 k6_runner=lambda cfg: _clean_summary(),
                 reconcile_fn=lambda s: _recon_limpia())
    verdict = orch.run()
    assert verdict.estado == "invalid"
    assert "pool de credenciales ilegible" in (verdict.invalid_reason or "")


def test_dry_run_no_necesita_pool_ni_reconcile(tmp_path):
    """El dry-run no cambia: sin pool (basa_key null) y con reconciliación sintética."""
    orch = _orch(tmp_path, dry_run=True)
    assert orch.run().global_veredicto == "PASS"
    pool = json.loads((orch.run_dir / "pool.json").read_text())
    assert all(e["basa_key"] is None for e in pool)
    data = json.loads((orch.run_dir / "reconciliation.json").read_text())
    assert data["filas_persistidas"] == data["eventos_guion"]


# ── CLI de la corrida real ────────────────────────────────────────────────────────────

def test_cli_reconcile_http_sin_pool_es_error_accionable(tmp_path, capsys):
    with pytest.raises(SystemExit) as ei:
        main(["--gate", "125", "--reconcile", "http", "--runs-dir", str(tmp_path)])
    assert ei.value.code == 2
    assert "--pool-file" in capsys.readouterr().err


def test_cli_reconcile_http_no_aplica_a_dry_run(tmp_path, capsys):
    with pytest.raises(SystemExit) as ei:
        main(["--gate", "125", "--reconcile", "http", "--dry-run",
              "--runs-dir", str(tmp_path)])
    assert ei.value.code == 2
    assert "dry-run" in capsys.readouterr().err


def test_cli_reconcile_http_sin_lector_en_el_pool_es_error(tmp_path, capsys):
    pool = tmp_path / "pool.json"
    pool.write_text(json.dumps([{"username": "cli", "password": "x", "role": "client"}]),
                    encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        main(["--gate", "125", "--reconcile", "http", "--pool-file", str(pool),
              "--runs-dir", str(tmp_path)])
    assert ei.value.code == 2
    assert "admin-only" in capsys.readouterr().err


def test_cli_dry_run_sigue_verde_y_sin_reconcile(tmp_path, capsys):
    rc = main(["--gate", "125", "--dry-run", "--runs-dir", str(tmp_path),
               "--run-id", "cli-dry-01"])
    assert rc == 0
    assert "global=PASS" in capsys.readouterr().out
    assert (tmp_path / "cli-dry-01" / "verdict.json").exists()


def test_cli_real_sin_reconcile_avisa(tmp_path, capsys, monkeypatch):
    """Un run real sin --reconcile http no puede computar (b) ni (d): tiene que avisarlo
    ANTES, no descubrirse al final del examen."""
    import basa_harness.orchestrator as orchmod

    class OrchFalso:
        run_dir = tmp_path

        def __init__(self, *a, **kw):
            pass

        def run(self):
            from basa_harness.reporting.evaluator import Verdict
            return Verdict(run_id="x", gate={"n": 125, "version": "1.0.0"},
                           estado="completed", global_veredicto="PASS", slos=[])

    monkeypatch.setattr(orchmod, "Orchestrator", OrchFalso)
    main(["--gate", "125", "--runs-dir", str(tmp_path)])
    assert "reconciliation_rows" in capsys.readouterr().err


def test_pool_del_run_no_es_world_readable(tmp_path):
    """El pool del run lleva passwords en claro y las keys de las Connections: 0600."""
    import stat
    orch = _orch(tmp_path, dry_run=True)
    orch.run()
    modo = stat.S_IMODE((orch.run_dir / "pool.json").stat().st_mode)
    assert modo == 0o600, f"pool.json quedó {oct(modo)}"


# ── Metadata del fingerprint en una corrida REAL (M2 del gate) ────────────────────────

def test_el_fingerprint_toma_hardware_y_producto_del_cli(tmp_path):
    """Sin estos flags, un gate oficial se firmaba con producto/hardware 'unknown' y su
    evidencia no era contrastable: nadie podía demostrar QUÉ build se midió (ni descartar
    el doble conteo pre-#135 a posteriori)."""
    hw = tmp_path / "hw.json"
    hw.write_text(json.dumps({"provider": "hetzner", "location": "hel1",
                              "sut_server_type": "ccx33", "gen_server_type": "cpx42"}),
                  encoding="utf-8")
    prod = tmp_path / "prod.json"
    prod.write_text(json.dumps({"commit": "52e694b", "digests": {"backend": "sha256:ab"}}),
                    encoding="utf-8")

    assert main(["--gate", "125", "--dry-run", "--runs-dir", str(tmp_path),
                 "--run-id", "fp-real", "--hardware-file", str(hw),
                 "--producto-file", str(prod), "--harness-commit", "cafe123"]) in (0, 1)

    fp = json.loads((tmp_path / "fp-real" / "fingerprint.json").read_text())
    assert fp["hardware"]["sut_server_type"] == "ccx33"
    assert fp["producto"]["commit"] == "52e694b"
    assert fp["versiones_instrumento"]["harness_commit"] == "cafe123"


def test_metadata_ilegible_es_error_del_cli_no_un_unknown_silencioso(tmp_path):
    roto = tmp_path / "roto.json"
    roto.write_text("{no es json", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--gate", "125", "--dry-run", "--runs-dir", str(tmp_path),
              "--run-id", "fp-roto", "--hardware-file", str(roto)])


def test_metadata_que_no_es_objeto_tampoco_pasa(tmp_path):
    lista = tmp_path / "lista.json"
    lista.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--gate", "125", "--dry-run", "--runs-dir", str(tmp_path),
              "--run-id", "fp-lista", "--producto-file", str(lista)])


# ── Skew de reloj orquestador↔SUT (M1 del gate) ───────────────────────────────────────

def _run_real_con_reloj(tmp_path, probe):
    """Run real mínimo con hooks falsos + la sonda de reloj bajo prueba."""
    return _orch(tmp_path, run_id="skew",
                 health_fn=lambda cual: _health(0),
                 stub_client=FakeStub(_clean_stub_report()),
                 k6_runner=lambda cfg: _clean_summary(),
                 reconcile_fn=lambda s: {},
                 clock_probe_fn=probe)


def test_skew_grande_invalida_el_run_antes_de_cargar(tmp_path):
    """M1: con el SUT adelantado, tráfico escrito ANTES de t0 cae dentro de la ventana y
    puede tapar filas perdidas reales — la promesa «se cuenta de menos, nunca de más»
    deja de valer. Se aborta antes de generar carga."""
    adelantado = lambda: datetime.fromisoformat(TS) + timedelta(seconds=30)
    orch = _run_real_con_reloj(tmp_path, adelantado)
    orch._now = lambda: datetime.fromisoformat(TS)
    verdict = orch.run()
    assert verdict.estado == "invalid"
    assert "skew" in (verdict.invalid_reason or "")
    assert orch.k6_launched is False                      # nunca se pagó la carga
    skew = json.loads((orch.run_dir / "clock_skew.json").read_text())
    assert skew["skew_s"] == 30.0


def test_skew_chico_no_molesta_y_queda_en_la_evidencia(tmp_path):
    casi = lambda: datetime.fromisoformat(TS) + timedelta(seconds=1)
    orch = _run_real_con_reloj(tmp_path, casi)
    orch._now = lambda: datetime.fromisoformat(TS)
    verdict = orch.run()
    assert verdict.estado != "invalid" or "skew" not in (verdict.invalid_reason or "")
    assert json.loads((orch.run_dir / "clock_skew.json").read_text())["skew_s"] == 1.0


def test_sonda_de_reloj_muda_aborta(tmp_path):
    orch = _run_real_con_reloj(tmp_path, lambda: None)
    orch._now = lambda: datetime.fromisoformat(TS)
    verdict = orch.run()
    assert verdict.estado == "invalid"
    assert "Date" in (verdict.invalid_reason or "")
