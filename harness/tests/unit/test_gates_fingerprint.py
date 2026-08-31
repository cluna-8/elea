"""Tests del bloque gates + fingerprint (spec 035, T014).

- Los 3 YAML cargan y validan (SC-008 local); dry-run del gate-500 pasa.
- validate_gate delata mezcla que no suma 100 / sin version / SLO desconocido / cadencia
  con rango inválido.
- Fingerprints idénticos → comparación legítima; un campo distinto → ILEGÍTIMA con el
  diff señalado; run invalid → no comparable; timestamp NO es material.
- La tasa de llegada derivada del gate-125 da los valores de research.md R1.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from sentinel_harness.reporting import (
    CANONICAL_SLOS,
    Fingerprint,
    GateError,
    compare,
    dry_run,
    load_gate,
    surface_arrival_rates,
    surface_populations,
    validate_gate,
)
from sentinel_harness.reporting.gate_loader import GATES_DIR

GATE_FILES = {n: GATES_DIR / f"gate-{n}.yaml" for n in (125, 250, 500)}


# ── Los 3 YAML cargan y validan (SC-008 local) ──────────────────────────────────────

@pytest.mark.parametrize("n", [125, 250, 500])
def test_los_tres_yaml_cargan(n):
    gate = load_gate(GATE_FILES[n])
    assert gate.gate == n
    assert gate.version == "1.1.0"
    assert set(gate.slo) == set(CANONICAL_SLOS)


@pytest.mark.parametrize("n", [125, 250, 500])
def test_los_tres_yaml_validan_sin_errores(n):
    import yaml
    data = yaml.safe_load(GATE_FILES[n].read_text(encoding="utf-8"))
    assert validate_gate(data) == []


@pytest.mark.parametrize("n", [125, 250, 500])
def test_dry_run_pasa(n):
    """La validación en seco de SC-008 pasa para los 3 gates (incluye el 500)."""
    assert dry_run(GATE_FILES[n]) == []


# ── Campos del contrato: gate-125 (ejemplo normativo) ───────────────────────────────

def test_gate_125_campos_del_contrato():
    g = load_gate(GATE_FILES[125])
    assert g.mix == {"chat": 60, "extension": 25, "coding_sse": 10, "admin": 5}
    assert g.cadence_s == {"chat": [60, 180], "extension": [90, 300],
                           "coding_sse": [120, 300], "admin": [180, 600]}
    assert g.pii_densities_per_mille == [0, 1, 5, 20]
    assert g.repeatability_tolerance_pct == 10
    assert g.budget_api_usd == 0
    scr = g.stack_config_required
    assert scr["masking"]["default"] in (True, "on")   # pyyaml: `on` → True
    assert scr["nlp_analyzer"] == "real"
    assert scr["nlp_analyzer_url"] == "configured"
    assert scr["nlp_fail_mode"] == "block"
    assert scr["producto_incluye"] == ["PR #97", "PR #177"]
    assert scr["auto_router"] == "off"
    assert [p.name for p in g.phases] == ["sustained"]
    assert g.phases[0].duration_s == 30 * 60


def test_gate_250_tiene_login_storm():
    g = load_gate(GATE_FILES[250])
    nombres = [p.name for p in g.phases]
    assert nombres == ["login_storm", "sustained"]
    login = g.phases[0]
    assert login.duration_s == 10 * 60
    assert g.phases[1].duration_s == 30 * 60
    # los SLOs son idénticos (no hay SLO por fase distinto en la definición)
    assert set(g.slo) == set(CANONICAL_SLOS)


def test_gate_500_fases_pico_recuperacion_y_knee_search():
    g = load_gate(GATE_FILES[500])
    assert [p.name for p in g.phases] == ["sustained", "peak", "recovery"]
    assert g.phases[0].duration_s == 3600            # sustained 1h
    peak = g.phases[1]
    assert peak.arrival_factor == 2                  # pico ×2
    # knee_search es OPCIONAL e informativa (fuera del pass/fail)
    assert g.knee_search is not None
    assert g.knee_search.get("enabled") is False


# ── validate_gate delata definiciones inválidas ─────────────────────────────────────

def _valid_dict() -> dict:
    import yaml
    return yaml.safe_load(GATE_FILES[125].read_text(encoding="utf-8"))


def test_mezcla_no_suma_100():
    d = _valid_dict()
    d["mix"]["chat"] = 50          # 50+25+10+5 = 90
    errs = validate_gate(d)
    assert any("no suma 100" in e for e in errs)


def test_sin_version():
    d = _valid_dict()
    del d["version"]
    errs = validate_gate(d)
    assert any("version" in e for e in errs)


def test_version_no_semver():
    d = _valid_dict()
    d["version"] = "1.0"           # no es MAJOR.MINOR.PATCH
    errs = validate_gate(d)
    assert any("semver" in e for e in errs)


def test_slo_desconocido():
    d = _valid_dict()
    d["slo"] = ["audit_lost_events_delta_zero", "un_slo_inventado",
                "zero_raw_canaries", "blocked_rows_durable_100"]
    errs = validate_gate(d)
    assert any("SLO desconocido" in e for e in errs)


def test_cadencia_rango_invalido():
    d = _valid_dict()
    d["cadence_s"]["chat"] = [180, 60]   # min > max
    errs = validate_gate(d)
    assert any("cadence_s[chat]" in e and "rango inválido" in e for e in errs)


def test_nlp_fail_mode_desconocido():
    d = _valid_dict()
    d["stack_config_required"]["nlp_fail_mode"] = "panic"
    errs = validate_gate(d)
    assert any("nlp_fail_mode" in e for e in errs)


def test_load_gate_invalido_levanta_gateerror():
    d = _valid_dict()
    del d["version"]
    import yaml
    tmp = GATES_DIR / "_tmp_invalido.yaml"
    tmp.write_text(yaml.safe_dump(d), encoding="utf-8")
    try:
        with pytest.raises(GateError) as exc:
            load_gate(tmp)
        assert exc.value.errors
    finally:
        tmp.unlink()


# ── Tasa de llegada derivada (research.md R1) ───────────────────────────────────────

def test_poblacion_por_superficie_gate_125():
    """Reparto Hamilton de 125 por la mezcla = distribución de R5 (75/31/13/6)."""
    g = load_gate(GATE_FILES[125])
    pops = surface_populations(g)
    assert pops == {"chat": 75, "extension": 31, "coding_sse": 13, "admin": 6}
    assert sum(pops.values()) == 125


def test_tasa_llegada_gate_125_matchea_R1():
    g = load_gate(GATE_FILES[125])
    r = surface_arrival_rates(g)
    # R1: chat 75/120s, ext 31/195s, coding 13/210s  (idénticos)
    assert (r["chat"].sessions, r["chat"].cadence_mean_s) == (75, 120)
    assert (r["extension"].sessions, r["extension"].cadence_mean_s) == (31, 195)
    assert (r["coding_sse"].sessions, r["coding_sse"].cadence_mean_s) == (13, 210)
    # admin: N=6; cadencia media del contrato [180,600] = 390 (R1 documenta 300 — ver
    # reporte: media real del rango del contrato, no 300; el contrato manda).
    assert (r["admin"].sessions, r["admin"].cadence_mean_s) == (6, 390)
    # mapeo k6 (executor de modelo abierto)
    assert r["chat"].k6 == {"executor": "constant-arrival-rate",
                            "rate": 75, "time_unit_s": 120}
    assert r["chat"].rate_per_s == pytest.approx(75 / 120)


def test_reparto_hamilton_250_y_500():
    """El reparto entero suma exacto la población en 250 y 500 (coincide con R5)."""
    assert surface_populations(load_gate(GATE_FILES[250])) == \
        {"chat": 150, "extension": 63, "coding_sse": 25, "admin": 12}
    assert surface_populations(load_gate(GATE_FILES[500])) == \
        {"chat": 300, "extension": 125, "coding_sse": 50, "admin": 25}


# ── Fingerprint: captura y comparación (FR-009 / US3) ───────────────────────────────

def _fp_baseline() -> dict:
    return {
        "producto": {"commit": "abc1234", "digests": {"backend": "sha256:aa", "motor": "sha256:bb"}},
        "masking_por_scope": {"default": "on", "gateway": "on"},
        "config_nlp": {"nlp_analyzer": "real", "nlp_analyzer_url": "configured",
                       "nlp_fail_mode": "block"},
        "workers_procesos": {"backend": 2, "motor": 1, "nlp": 1},
        "limites_recursos": {"cpu": "8", "mem_gb": 32},
        "gate": {"n": 125, "version": "1.0.0"},
        "corpus": {"version": "1.0.0", "sha256": "deadbeef", "seed": 20260808},
        "mix_y_cadencia_usadas": {"chat": 60, "cadence_chat_s": [60, 180]},
        "hardware": {"server_type": "ccx33", "datacenter": "hel1-dc2"},
        "licencia": {"lic_id": "itv-300", "max_seats": 300},
        "seed_estado": "verified",
        "versiones_instrumento": {"k6": "1.8.0", "xk6_sse": "0.1.12",
                                  "stub": "0.1.0", "harness_commit": "cafe123"},
        "timestamp": "2026-08-12T10:00:00Z",
    }


def test_fingerprint_serializa_lista_minima():
    fp = Fingerprint.from_dict(_fp_baseline())
    d = fp.to_dict()
    for campo in ("producto", "config_nlp", "workers_procesos", "gate", "corpus",
                  "hardware", "licencia", "seed_estado", "versiones_instrumento",
                  "timestamp"):
        assert campo in d
    assert Fingerprint.from_dict(d).to_dict() == d  # round-trip


def test_fingerprint_incompleto_falla():
    d = _fp_baseline()
    del d["licencia"]
    with pytest.raises(ValueError):
        Fingerprint.from_dict(d)


def test_fingerprints_identicos_legitima():
    a = Fingerprint.from_dict(_fp_baseline())
    b = Fingerprint.from_dict(_fp_baseline())
    res = compare(a, b)
    assert res.comparable and res.legitimate
    assert bool(res) is True
    assert res.diffs == []


def test_timestamp_no_es_material():
    """Par de repetibilidad: misma config, distinto momento → legítima."""
    a = _fp_baseline()
    b = _fp_baseline()
    b["timestamp"] = "2026-08-19T15:30:00Z"   # otro run, otro día
    res = compare(Fingerprint.from_dict(a), Fingerprint.from_dict(b))
    assert res.legitimate is True


def test_diff_workers_ilegitima_con_detalle():
    a = _fp_baseline()
    b = copy.deepcopy(a)
    b["workers_procesos"]["backend"] = 4      # WEB_CONCURRENCY cambiada
    res = compare(Fingerprint.from_dict(a), Fingerprint.from_dict(b))
    assert res.comparable is True
    assert res.legitimate is False
    assert bool(res) is False
    paths = {d.path for d in res.diffs}
    assert "workers_procesos.backend" in paths
    d = next(d for d in res.diffs if d.path == "workers_procesos.backend")
    assert (d.izquierda, d.derecha) == (2, 4)


def test_diff_nlp_fail_mode_block_vs_degrade_ilegitima():
    a = _fp_baseline()
    b = copy.deepcopy(a)
    b["config_nlp"]["nlp_fail_mode"] = "degrade"   # otro examen (contract regla 4)
    res = compare(Fingerprint.from_dict(a), Fingerprint.from_dict(b))
    assert res.legitimate is False
    assert any(d.path == "config_nlp.nlp_fail_mode" for d in res.diffs)


def test_run_invalid_no_comparable():
    a = Fingerprint.from_dict(_fp_baseline())
    b = Fingerprint.from_dict(_fp_baseline())
    res = compare(a, b, estado_b="invalid")
    assert res.comparable is False
    assert res.legitimate is False
    assert "invalid" in res.motivo


def test_run_sin_fingerprint_no_comparable():
    a = Fingerprint.from_dict(_fp_baseline())
    res = compare(a, None)
    assert res.comparable is False
    assert res.legitimate is False
