"""Tests del comparador de runs (US3, T033)."""
from basa_harness.reporting.compare_runs import compare_runs


def _fp(**over):
    """Fingerprint mínimo; over pisa campos para forzar diffs materiales."""
    base = {
        "producto": {"commit": "abc123"},
        "masking_por_scope": {"default": "on"},
        "config_nlp": {"nlp_fail_mode": "block"},
        "workers_procesos": {"backend": 2},
        "limites_recursos": {},
        "gate": {"n": 125, "version": "1.0.0"},
        "corpus": {"version": "1.0.0", "sha256": "deadbeef", "seed": 42},
        "hardware": {"server_type": "ccx33"},
        "licencia": {"lic_id": "lic_itv", "max_seats": 300},
    }
    base.update(over)
    return base


_DEFAULT_OVERHEAD = {"chat": {"p95": 100.0}, "coding_sse": {"p95": 200.0}}


def _run(global_veredicto="PASS", estado="completed", overhead=None, fp_over=None):
    # None = usar el default; {} = explícitamente vacío (no confundir con falsy).
    return {
        "fingerprint": _fp(**(fp_over or {})),
        "verdict": {
            "global": global_veredicto,
            "estado": estado,
            "overhead": _DEFAULT_OVERHEAD if overhead is None else overhead,
        },
    }


def test_dos_runs_identicos_legitima_veredictos_coinciden_dentro_tolerancia():
    r = compare_runs(_run(), _run())
    assert r.comparable and r.legitimate
    assert r.veredictos_coinciden is True
    assert r.overhead_dentro_tolerancia is True


def test_diff_material_de_fingerprint_marca_ilegitima_y_no_compara_metricas():
    a = _run()
    b = _run(fp_over={"workers_procesos": {"backend": 4}})  # cambió los workers
    r = compare_runs(a, b)
    assert r.comparable is True
    assert r.legitimate is False
    assert r.overhead_dentro_tolerancia is None  # no se comparan métricas
    assert r.fingerprint_diffs  # el diff está señalado


def test_nlp_fail_mode_distinto_es_diff_material():
    a = _run()
    b = _run(fp_over={"config_nlp": {"nlp_fail_mode": "degrade"}})
    r = compare_runs(a, b)
    assert r.legitimate is False


def test_run_invalido_no_es_comparable():
    a = _run()
    b = _run(estado="invalid")
    r = compare_runs(a, b)
    assert r.comparable is False
    assert r.overhead_dentro_tolerancia is None


def test_run_interrumpido_no_es_comparable():
    r = compare_runs(_run(), _run(estado="interrupted"))
    assert r.comparable is False


def test_overhead_fuera_de_tolerancia_se_detecta():
    a = _run(overhead={"chat": {"p95": 100.0}})
    b = _run(overhead={"chat": {"p95": 130.0}})  # +30% > ±10%
    r = compare_runs(a, b)
    assert r.comparable and r.legitimate
    assert r.overhead_dentro_tolerancia is False
    assert r.detalle_overhead["chat"]["dentro"] is False


def test_overhead_dentro_de_tolerancia_pasa():
    a = _run(overhead={"chat": {"p95": 100.0}})
    b = _run(overhead={"chat": {"p95": 108.0}})  # +8% ≤ ±10%
    r = compare_runs(a, b)
    assert r.overhead_dentro_tolerancia is True


def test_veredictos_distintos_se_reportan_en_comparacion_legitima():
    r = compare_runs(_run(global_veredicto="PASS"), _run(global_veredicto="FAIL"))
    assert r.legitimate is True
    assert r.veredictos_coinciden is False


def test_sin_overhead_comparable_no_rompe():
    a = _run(overhead={})
    b = _run(overhead={})
    r = compare_runs(a, b)
    assert r.legitimate is True
    assert r.overhead_dentro_tolerancia is None  # nada que medir, no rompe
