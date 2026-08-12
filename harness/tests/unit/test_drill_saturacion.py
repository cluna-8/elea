"""Tests del drill de saturación C1 (spec 035; contracts ``gate-definition.md`` y
``run-report.md``).

El fix de admisión del core rechaza con un 503 rápido cuando el motor está saturado
(``X-Basa-Rejected: saturated`` + fila durable ``estado='rejected_saturated'`` escrita
ANTES de responder). Acá se prueba el INSTRUMENTO que lo mide, con datos sintéticos:

- el YAML del drill carga, valida y expone ``kind``/``drill.criteria``; un ``kind``
  inventado o un criterio mal escrito son errores ACCIONABLES (un typo que se leyera como
  «sin umbral» dejaría pasar un drill que no midió nada);
- el evaluador agrega ``saturated_503_rows_durable`` + los criterios del drill, y los
  criterios con umbral fijado son VINCULANTES;
- **REGLA DE ORO**: un ``gate_oficial`` sin rechazos produce un verdict byte a byte
  idéntico al de antes de C1 — se compara contra un golden congelado.
"""
from __future__ import annotations

import copy
import json

import pytest
import yaml

from basa_harness.orchestrator import (Orchestrator, OrchestratorError, _drill_overrides,
                                       main)
from basa_harness.reporting.evaluator import (SLOResult, Verdict, evaluate,
                                              eval_drill_criteria, eval_saturated_durable)
from basa_harness.reporting.fingerprint import compare
from basa_harness.reporting.gate_loader import (GATES_DIR, GateError, dry_run, load_gate,
                                                validate_gate)

DRILL_FILE = GATES_DIR / "drill-saturacion-125.yaml"
GATE_FILE = GATES_DIR / "gate-125.yaml"
TS = "2026-08-12T00:00:00Z"


# ── fixtures sintéticos (idénticos a los del evaluador, más los campos de C1) ──────────

def _health(lost: object) -> dict:
    return {"status": "healthy", "service": "backend", "version": "1.0.0",
            "audit": {"mode": "block", "lost_events": lost, "last_failure_at": None}}


def _clean_k6_summary() -> dict:
    def lat(p50, p95, p99, mx):
        return {"latency_ms": {"p50": p50, "p95": p95, "p99": p99, "max": mx, "count": 100},
                "dropped_iterations": 0, "requests": 100, "errors": 0}
    surfaces = {
        "chat": lat(812, 830, 845, 900),
        "extension": lat(40, 55, 70, 120),
        "admin": lat(15, 22, 30, 60),
    }
    coding = lat(650, 690, 720, 800)
    coding["ttft_ms"] = {"p50": 612, "p95": 640, "p99": 700, "max": 780, "count": 100}
    coding["stream_cuts"] = 0
    surfaces["coding"] = coding
    return {"schema": "basa-harness/k6-summary@1", "gate": 125, "surfaces": surfaces,
            "dropped_iterations_total": 0, "auditable_events": 2250}


def _saturated_summary(rechazos: int = 120, p95: float = 5200.0) -> dict:
    """Summary de un drill: el guion vio ``rechazos`` 503 saturados, cronometrados en su
    propia Trend (lat_rejection) — NO en la latencia de chat."""
    k6 = _clean_k6_summary()
    k6["saturated_rejections"] = rechazos
    k6["rejection_ms"] = {"p50": 4800.0, "p95": p95, "p99": 5600.0, "max": 5900.0,
                          "count": rechazos}
    return k6


def _clean_stub_report() -> dict:
    return {"run_id": "r", "leak_count": 0, "canarios_detectados": [], "canary_set_size": 64,
            "trafico_no_auditable": {"count": 0, "requests": []},
            "pacing_drift_ms": {"p50": 0.2, "p95": 0.8, "p99": 1.2, "max": 2.0, "n": 100},
            "cpu_pct": 24.0, "valido": True}


def _clean_reconciliation() -> dict:
    return {"eventos_guion": 2250, "filas_persistidas": 2250,
            "bloqueos_provocados": 40, "con_fila": 40}


def _evaluate(gate=None, **over):
    kw = dict(k6_summary=_clean_k6_summary(), health_initial=_health(3),
              health_final=_health(3), stub_report=_clean_stub_report(),
              reconciliation=_clean_reconciliation())
    kw.update(over)
    gate_obj = load_gate(GATE_FILE) if gate is None else gate
    return evaluate(gate_obj, run_id="20260812-g125-01", timestamp=TS, **kw)


def _slo(verdict, name):
    return next(s for s in verdict.slos if s.slo == name)


def _slo_opt(verdict, name):
    return next((s for s in verdict.slos if s.slo == name), None)


# ── (a) gate_loader: el YAML del drill ────────────────────────────────────────────────

def test_drill_yaml_carga_y_valida():
    g = load_gate(DRILL_FILE)
    assert g.kind == "drill"
    assert g.gate == 125
    assert g.drill == {"criteria": {"rejection_p95_max_ms": 6000,
                                    "admin_p95_budget_ms": None}}
    # los 4 SLO de oro siguen ahí: un drill NO reemplaza el examen
    assert set(g.slo) == {"audit_lost_events_delta_zero", "reconciliation_rows",
                          "zero_raw_canaries", "blocked_rows_durable_100"}


def test_drill_yaml_dry_run_sin_errores():
    """Validación en seco (SC-008): el drill es aprovisionable igual que un gate."""
    assert dry_run(DRILL_FILE) == []


def test_drill_fases_sostenido_y_rafaga():
    g = load_gate(DRILL_FILE)
    assert [p.name for p in g.phases] == ["sustained", "burst"]
    assert g.phases[0].duration_s == 10 * 60
    assert g.phases[1].duration_s == 5 * 60
    assert g.phases[1].arrival_factor == 3      # la ráfaga que encuentra la cola llena


def test_drill_stub_es_sede_lenta():
    """El estrés del drill viene del stub: streams largos y goteo lento ocupan el tope de
    concurrencia al motor. El 503 debe salir de la admisión, no de un error_rate."""
    g = load_gate(DRILL_FILE)
    assert g.stub["token_rate_tps"] == 5
    assert g.stub["stream_duration_s"] == [60, 120]
    assert g.stub["error_rate"] == 0.0


def test_gates_oficiales_kind_por_defecto():
    """Sin `kind` en el YAML, un gate sigue siendo oficial y sin criterios de drill."""
    g = load_gate(GATE_FILE)
    assert g.kind == "gate_oficial"
    assert g.drill is None


def _drill_dict() -> dict:
    return yaml.safe_load(DRILL_FILE.read_text(encoding="utf-8"))


def test_kind_invalido_error_accionable():
    d = _drill_dict()
    d["kind"] = "ensayito"
    errs = validate_gate(d)
    assert any("'kind' desconocido" in e and "ensayito" in e for e in errs)
    assert any("gate_oficial" in e and "drill" in e for e in errs)   # dice los válidos


def test_criterio_de_drill_desconocido_error_accionable():
    """Un criterio mal escrito NO se ignora: se leería como «sin umbral» y el drill
    pasaría por no medir nada."""
    d = _drill_dict()
    d["drill"]["criteria"]["rejection_p95_max_msec"] = 6000
    errs = validate_gate(d)
    assert any("criterio(s) de drill desconocido(s)" in e for e in errs)
    assert any("rejection_p95_max_msec" in e for e in errs)


def test_clave_desconocida_en_drill_error_accionable():
    d = _drill_dict()
    d["drill"]["umbrales"] = {"algo": 1}
    errs = validate_gate(d)
    assert any("desconocida(s) en 'drill'" in e and "umbrales" in e for e in errs)


def test_criteria_debe_ser_mapeo():
    d = _drill_dict()
    d["drill"] = {"criteria": [6000]}
    errs = validate_gate(d)
    assert any("'drill.criteria' debe ser un mapeo" in e for e in errs)


def test_umbral_no_positivo_error():
    d = _drill_dict()
    d["drill"]["criteria"]["rejection_p95_max_ms"] = 0
    errs = validate_gate(d)
    assert any("rejection_p95_max_ms" in e and "> 0 o null" in e for e in errs)


def test_umbral_null_es_valido():
    """null = umbral sin fijar a propósito (se deriva del baseline del mismo día)."""
    d = _drill_dict()
    d["drill"]["criteria"]["rejection_p95_max_ms"] = None
    assert validate_gate(d) == []


def test_bloque_drill_sin_kind_drill_error_accionable():
    """Cross-check (a): con el bloque `drill` pero sin `kind: drill`, el evaluador NUNCA
    miraría los criterios — el examen parecería medir sin medir."""
    d = _drill_dict()
    del d["kind"]
    errs = validate_gate(d)
    assert any("bloque 'drill' en una definición gate_oficial" in e for e in errs)
    assert any("falta 'kind: drill'" in e and "sobra el bloque" in e for e in errs)


def test_bloque_drill_con_kind_gate_oficial_explicito_error_accionable():
    """Mismo cross-check con el kind escrito a mano (no solo ausente)."""
    d = _drill_dict()
    d["kind"] = "gate_oficial"
    errs = validate_gate(d)
    assert any("bloque 'drill' en una definición gate_oficial" in e for e in errs)


def test_kind_drill_sin_bloque_drill_error_accionable():
    """Cross-check (b): un drill sin criterios propios «pasaría» por no medir nada."""
    d = _drill_dict()
    del d["drill"]
    errs = validate_gate(d)
    assert any("'kind: drill' sin bloque 'drill'" in e and "criteria" in e for e in errs)


def test_kind_drill_con_criteria_en_null_sigue_valido():
    """Los VALORES pueden ser null (umbral sin fijar); la CLAVE no."""
    d = _drill_dict()
    d["drill"]["criteria"] = {"rejection_p95_max_ms": None, "admin_p95_budget_ms": None}
    assert validate_gate(d) == []


@pytest.mark.parametrize("literal", [".inf", "-.inf", ".nan"])
def test_umbral_no_finito_error_accionable(literal):
    """`.inf` volvería el criterio decorativo (nada lo supera) y `.nan` aleatorio: ninguna
    comparación los delata (`nan <= 0` es False, `.inf > 0` es True)."""
    texto = DRILL_FILE.read_text(encoding="utf-8").replace(
        "rejection_p95_max_ms: 6000", f"rejection_p95_max_ms: {literal}")
    d = yaml.safe_load(texto)
    # el YAML REALMENTE los parsea como float (por eso hace falta la guarda explícita)
    assert isinstance(d["drill"]["criteria"]["rejection_p95_max_ms"], float)
    errs = validate_gate(d)
    assert any("rejection_p95_max_ms" in e and "FINITO" in e for e in errs)


@pytest.mark.parametrize("valor", ["nan", "inf", "-inf", "-5", "0"])
def test_cli_budget_no_finito_o_no_positivo_error_accionable(valor, tmp_path, capsys):
    """argparse acepta 'nan'/'inf' como float: la guarda es del harness, y corre ANTES de
    construir el orquestador (no se empieza un examen con un criterio roto)."""
    with pytest.raises(SystemExit) as exc:
        # forma `--flag=valor`: los negativos con espacio los leería argparse como opción
        main(["--gate-file", str(DRILL_FILE), "--dry-run", "--runs-dir", str(tmp_path),
              "--run-id", "cli-budget", f"--drill-admin-budget-ms={valor}"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--drill-admin-budget-ms" in err and "FINITO > 0" in err
    assert not (tmp_path / "cli-budget").exists()      # no se tocó disco


def test_verdict_con_nan_revienta_en_vez_de_escribir_json_invalido():
    """Cinturón: NaN/Infinity no existen en JSON (RFC 8259). Mejor un fallo ruidoso que un
    verdict.json que ningún parser estándar lee."""
    v = Verdict(run_id="x", gate={"n": 125, "version": "1.0.0"}, estado="completed",
                global_veredicto="FAIL",
                slos=[SLOResult("rejection_time_to_503_p95", float("nan"), "FAIL", {})],
                timestamp=TS)
    with pytest.raises(ValueError):
        v.to_json()


def test_load_gate_drill_invalido_levanta_gateerror(tmp_path):
    d = _drill_dict()
    d["kind"] = "no_existe"
    tmp = tmp_path / "drill-roto.yaml"
    tmp.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    with pytest.raises(GateError) as exc:
        load_gate(tmp)
    assert any("'kind' desconocido" in e for e in exc.value.errors)


# ── (b) evaluador: durabilidad del rechazo + criterios del drill ──────────────────────

def test_drill_con_rechazos_pares_tres_filas_nuevas_pass():
    """Drill sano: 120 rechazos, 120 filas durables, p95 bajo el umbral, presupuesto de
    admin pasado por override → las 3 filas nuevas PASS y global PASS."""
    recon = _clean_reconciliation()
    recon["filas_rejected_saturated"] = 120
    v = _evaluate(gate=load_gate(DRILL_FILE), k6_summary=_saturated_summary(),
                  reconciliation=recon, drill_overrides={"admin_p95_budget_ms": 250.0})
    # las 4 canónicas primero, las del drill DESPUÉS y en orden fijo
    assert [s.slo for s in v.slos] == [
        "audit_lost_events_delta_zero", "reconciliation_rows", "zero_raw_canaries",
        "blocked_rows_durable_100", "saturated_503_rows_durable",
        "rejection_time_to_503_p95", "admin_latency_budget_p95"]
    assert _slo(v, "saturated_503_rows_durable").medido == 1.0
    assert _slo(v, "rejection_time_to_503_p95").medido == 5200.0
    assert _slo(v, "admin_latency_budget_p95").medido == 22       # admin p95 del summary
    assert all(s.veredicto == "PASS" for s in v.slos)
    assert v.estado == "completed" and v.global_veredicto == "PASS"


def test_drill_filas_impares_saturated_fail_y_global_fail():
    """Rechazar sin dejar fila durable = negar servicio sin rastro auditable."""
    recon = _clean_reconciliation()
    recon["filas_rejected_saturated"] = 117          # faltan 3
    v = _evaluate(gate=load_gate(DRILL_FILE), k6_summary=_saturated_summary(),
                  reconciliation=recon)
    s = _slo(v, "saturated_503_rows_durable")
    assert s.medido == pytest.approx(117 / 120) and s.veredicto == "FAIL"
    assert "SIN fila durable" in s.detalle["nota"]
    assert v.global_veredicto == "FAIL" and v.estado == "completed"


def test_drill_rejection_p95_sobre_umbral_fail():
    """El umbral (6000 ms = queue-timeout 5 s + 1 s) caza el anti-patrón del timeout
    largo: la defensa existe pero llega tarde."""
    recon = _clean_reconciliation()
    recon["filas_rejected_saturated"] = 120
    v = _evaluate(gate=load_gate(DRILL_FILE),
                  k6_summary=_saturated_summary(p95=150_000.0), reconciliation=recon)
    r = _slo(v, "rejection_time_to_503_p95")
    assert r.medido == 150_000.0 and r.veredicto == "FAIL"
    assert r.detalle["umbral_ms"] == 6000.0
    # criterio con umbral fijado = VINCULANTE para el veredicto del drill
    assert v.global_veredicto == "FAIL"


def test_drill_admin_budget_null_deja_nota_y_no_fila():
    """Sin umbral no se inventa un número: nota accionable y NINGUNA fila."""
    recon = _clean_reconciliation()
    recon["filas_rejected_saturated"] = 120
    v = _evaluate(gate=load_gate(DRILL_FILE), k6_summary=_saturated_summary(),
                  reconciliation=recon)
    assert _slo_opt(v, "admin_latency_budget_p95") is None
    assert any("--drill-admin-budget-ms" in n for n in v.notas)
    assert v.global_veredicto == "PASS"      # un criterio sin umbral no reprueba


def test_drill_admin_budget_excedido_fail():
    recon = _clean_reconciliation()
    recon["filas_rejected_saturated"] = 120
    v = _evaluate(gate=load_gate(DRILL_FILE), k6_summary=_saturated_summary(),
                  reconciliation=recon, drill_overrides={"admin_p95_budget_ms": 10.0})
    a = _slo(v, "admin_latency_budget_p95")
    assert a.medido == 22 and a.veredicto == "FAIL"
    assert v.global_veredicto == "FAIL"


def test_drill_sin_saturacion_es_examen_invalido_no_pass():
    """Un drill que NO saturó no midió la defensa C1: sus criterios quedan vacuos y el
    verdict saldría PASS por no haber ejercitado nada. Eso no es un aprobado — es un examen
    que no se tomó. Las filas se conservan como EVIDENCIA de por qué es inválido."""
    v = _evaluate(gate=load_gate(DRILL_FILE), reconciliation=_clean_reconciliation())
    s = _slo(v, "saturated_503_rows_durable")
    assert s.medido == 1.0 and s.veredicto == "PASS"
    assert "no hubo rechazos" in s.detalle["nota"]
    r = _slo(v, "rejection_time_to_503_p95")
    assert r.medido is None and r.veredicto == "PASS"
    assert "no aplica" in r.detalle["nota"]
    assert v.estado == "invalid"
    assert v.global_veredicto == "INVALID"
    assert "no alcanzó saturación" in (v.invalid_reason or "")
    assert "sede-lenta" in (v.invalid_reason or "")


def test_drill_con_rechazos_en_cero_explicito_tambien_es_invalido():
    """`saturated_rejections: 0` es lo mismo que no haber rechazado."""
    k6 = _saturated_summary(rechazos=0)
    v = _evaluate(gate=load_gate(DRILL_FILE), k6_summary=k6,
                  reconciliation=_clean_reconciliation())
    assert v.estado == "invalid" and v.global_veredicto == "INVALID"


def test_dry_run_del_drill_sin_saturacion_sigue_completed():
    """El dry-run corre con datos sintéticos y ya está marcado NO oficial: exigirle
    saturación invalidaría todo ensayo en seco del cableado."""
    v = _evaluate(gate=load_gate(DRILL_FILE), reconciliation=_clean_reconciliation(),
                  kind="dry-run")
    assert v.estado == "completed"
    assert v.global_veredicto == "PASS"


def test_gate_oficial_sin_rechazos_no_se_invalida():
    """La regla es del drill: un gate oficial no tiene por qué saturar."""
    v = _evaluate()
    assert v.estado == "completed" and v.global_veredicto == "PASS"


def test_drill_con_rechazos_y_sin_p95_es_fail_medido_null():
    """M3: hubo rechazos pero falta el cronómetro. No es lo mismo que no haber rechazado
    (PASS vacuo): con el criterio fijado, no poder afirmarlo es FAIL — espejo de admin."""
    k6 = _saturated_summary()
    del k6["rejection_ms"]
    recon = _clean_reconciliation()
    recon["filas_rejected_saturated"] = 120
    v = _evaluate(gate=load_gate(DRILL_FILE), k6_summary=k6, reconciliation=recon)
    r = _slo(v, "rejection_time_to_503_p95")
    assert r.medido is None and r.veredicto == "FAIL"
    assert "hubo 120 rechazos" in r.detalle["nota"]
    assert "falta rejection_ms.p95" in r.detalle["nota"]
    assert v.estado == "completed" and v.global_veredicto == "FAIL"


def test_drill_rechazos_sin_conteo_de_filas_fail():
    """Hubo rechazos pero el reconcile no trajo filas_rejected_saturated: no se puede
    afirmar durabilidad ⇒ FAIL (jamás se asume que estaban)."""
    v = _evaluate(gate=load_gate(DRILL_FILE), k6_summary=_saturated_summary(),
                  reconciliation=_clean_reconciliation())
    s = _slo(v, "saturated_503_rows_durable")
    assert s.medido is None and s.veredicto == "FAIL"
    assert v.global_veredicto == "FAIL"


def test_eval_saturated_durable_directo():
    # 0 rechazos → vacuo
    assert eval_saturated_durable({}, {}).medido == 1.0
    # paridad
    r = eval_saturated_durable({"saturated_rejections": 10},
                               {"filas_rejected_saturated": 10})
    assert r.medido == 1.0 and r.veredicto == "PASS"
    # faltante
    r = eval_saturated_durable({"saturated_rejections": 10}, {})
    assert r.medido is None and r.veredicto == "FAIL"


def test_saturated_durable_filas_de_sobra_es_fail_con_nota_propia():
    """B2: la paridad es ESTRICTA en los dos sentidos, pero el diagnóstico no es el mismo:
    faltar filas es negar servicio sin rastro; sobrar filas es contabilidad que no cuadra."""
    r = eval_saturated_durable({"saturated_rejections": 100},
                               {"filas_rejected_saturated": 103})
    assert r.veredicto == "FAIL" and r.medido == 1.03
    assert "sobran 3 fila(s) rejected_saturated" in r.detalle["nota"]
    assert "filas fantasma o rechazos no vistos" in r.detalle["nota"]
    # y la nota del faltante NO cambió
    r = eval_saturated_durable({"saturated_rejections": 100},
                               {"filas_rejected_saturated": 97})
    assert "SIN fila durable" in r.detalle["nota"]


@pytest.mark.parametrize("valor", [120.0, "120", True])
def test_conteo_de_rechazos_ilegible_es_fail_visible(valor):
    """B3: un conteo presente pero no-entero JAMÁS se interpreta a favor. Y la fila se
    AGREGA aunque el run no sea drill, para que el FAIL se vea en el verdict."""
    k6 = _clean_k6_summary()
    k6["saturated_rejections"] = valor
    recon = _clean_reconciliation()
    recon["filas_rejected_saturated"] = 120
    directo = eval_saturated_durable(k6, recon)
    assert directo.medido is None and directo.veredicto == "FAIL"
    assert "conteo de rechazos ilegible" in directo.detalle["nota"]
    v = _evaluate(k6_summary=k6, reconciliation=recon)      # gate OFICIAL, no drill
    assert _slo(v, "saturated_503_rows_durable").veredicto == "FAIL"
    assert v.global_veredicto == "FAIL" and v.estado == "completed"


def test_conteo_de_rechazos_ausente_en_oficial_no_agrega_fila():
    """El otro lado de B3: clave ausente = el golden de los gates oficiales, intacto."""
    v = _evaluate()
    assert "saturated_rejections" not in _clean_k6_summary()
    assert _slo_opt(v, "saturated_503_rows_durable") is None


def test_eval_drill_criteria_sin_umbrales_solo_notas():
    filas, notas = eval_drill_criteria(_saturated_summary(), {})
    assert filas == []
    assert any("criterio rejection sin umbral" in n for n in notas)
    assert any("umbral admin sin fijar" in n for n in notas)


# ── (b bis) REGLA DE ORO: el gate oficial no se mueve ni un byte ──────────────────────

# Snapshot CONGELADO del verdict de un run gate_oficial limpio, tomado ANTES de la
# extensión C1 (mismos fixtures sintéticos que test_evaluator). Si esto cambia, cambió el
# contrato de los gates oficiales: es un bump de versión, no un detalle de implementación.
GOLDEN_PRE_C1 = json.loads(r"""
{
  "run_id": "20260812-g125-01",
  "gate": {"n": 125, "version": "1.1.0"},
  "kind": "gate_oficial",
  "estado": "completed",
  "global": "PASS",
  "slos": [
    {"slo": "audit_lost_events_delta_zero", "medido": 0, "veredicto": "PASS",
     "detalle": {"fuente": "GET /api/v1/health (audit.lost_events, credencial compliance)",
                 "inicial": 3, "final": 3}},
    {"slo": "reconciliation_rows", "medido": 0, "veredicto": "PASS",
     "detalle": {"eventos_guion": 2250, "filas_persistidas": 2250,
                 "fuente": "conteo del guion (eventos auditables) vs audit_logs del producto"}},
    {"slo": "zero_raw_canaries", "medido": 0, "veredicto": "PASS",
     "detalle": {"canarios_detectados": 0, "canary_set_size": 64, "evidencia": [],
                 "fuente": "GET /control/report del stub (detector inline + barrido del spool)"}},
    {"slo": "blocked_rows_durable_100", "medido": 1.0, "veredicto": "PASS",
     "detalle": {"bloqueos_provocados": 40, "con_fila": 40,
                 "fuente": "bloqueos observados (guion) vs filas durables (audit_logs)"}}
  ],
  "por_fase": {
    "sustained": {
      "surfaces": {
        "chat": {"programada_ms": 800.0,
                 "medida_ms": {"p50": 812, "p95": 830, "p99": 845, "max": 900},
                 "overhead_ms": {"p50": 12.0, "p95": 30.0, "p99": 45.0, "max": 100.0}},
        "extension": {"programada_ms": 0.0,
                      "medida_ms": {"p50": 40, "p95": 55, "p99": 70, "max": 120},
                      "overhead_ms": {"p50": 40.0, "p95": 55.0, "p99": 70.0, "max": 120.0}},
        "admin": {"programada_ms": 0.0,
                  "medida_ms": {"p50": 15, "p95": 22, "p99": 30, "max": 60},
                  "overhead_ms": {"p50": 15.0, "p95": 22.0, "p99": 30.0, "max": 60.0}},
        "coding": {"programada_ms": 600.0,
                   "medida_ms": {"p50": 650, "p95": 690, "p99": 720, "max": 800},
                   "overhead_ms": {"p50": 50.0, "p95": 90.0, "p99": 120.0, "max": 200.0},
                   "ttft_programada_ms": 600.0,
                   "ttft_medida_ms": {"p50": 612, "p95": 640, "p99": 700, "max": 780},
                   "ttft_overhead_ms": {"p50": 12.0, "p95": 40.0, "p99": 100.0, "max": 180.0},
                   "stream_cuts": 0}
      },
      "dropped_iterations": 0
    }
  },
  "instrumento": {"dropped_iterations": 0, "stub_drift_p99_ms": 1.2, "stub_cpu_pct": 24.0,
                  "trafico_no_auditable": 0, "valido": true, "razones_invalidez": []},
  "overhead": {
    "chat": {"programada_ms": 800.0,
             "medida_ms": {"p50": 812, "p95": 830, "p99": 845, "max": 900},
             "overhead_ms": {"p50": 12.0, "p95": 30.0, "p99": 45.0, "max": 100.0}},
    "extension": {"programada_ms": 0.0,
                  "medida_ms": {"p50": 40, "p95": 55, "p99": 70, "max": 120},
                  "overhead_ms": {"p50": 40.0, "p95": 55.0, "p99": 70.0, "max": 120.0}},
    "admin": {"programada_ms": 0.0,
              "medida_ms": {"p50": 15, "p95": 22, "p99": 30, "max": 60},
              "overhead_ms": {"p50": 15.0, "p95": 22.0, "p99": 30.0, "max": 60.0}},
    "coding": {"programada_ms": 600.0,
               "medida_ms": {"p50": 650, "p95": 690, "p99": 720, "max": 800},
               "overhead_ms": {"p50": 50.0, "p95": 90.0, "p99": 120.0, "max": 200.0},
               "ttft_programada_ms": 600.0,
               "ttft_medida_ms": {"p50": 612, "p95": 640, "p99": 700, "max": 780},
               "ttft_overhead_ms": {"p50": 12.0, "p95": 40.0, "p99": 100.0, "max": 180.0},
               "stream_cuts": 0}
  },
  "timestamp": "2026-08-12T00:00:00Z"
}
""")


def test_gate_oficial_sin_rechazos_es_byte_identico_al_golden():
    """REGLA DE ORO: sin rechazos de saturación, el verdict de un gate oficial es
    EXACTAMENTE el de antes de C1 — misma estructura, mismas claves, mismo orden."""
    d = _evaluate().to_dict()
    assert d == GOLDEN_PRE_C1
    # mismo orden de claves y de filas (no solo igualdad de dicts)
    assert json.dumps(d, ensure_ascii=False) == json.dumps(GOLDEN_PRE_C1, ensure_ascii=False)
    assert "notas" not in d          # sin notas de drill que ensucien el artefacto


def test_gate_oficial_sin_rechazos_no_agrega_fila():
    v = _evaluate()
    assert _slo_opt(v, "saturated_503_rows_durable") is None
    assert len(v.slos) == 4


def test_gate_oficial_con_rechazos_si_agrega_fila():
    """Un gate OFICIAL que ve rechazos también los audita: el producto no puede negar
    servicio sin rastro solo porque el run no era un drill."""
    recon = _clean_reconciliation()
    recon["filas_rejected_saturated"] = 5
    v = _evaluate(k6_summary=_saturated_summary(rechazos=5), reconciliation=recon)
    s = _slo(v, "saturated_503_rows_durable")
    assert s.veredicto == "PASS" and s.medido == 1.0
    assert len(v.slos) == 5
    # los criterios de TIEMPO son del drill: un gate oficial no los evalúa
    assert _slo_opt(v, "rejection_time_to_503_p95") is None
    assert _slo_opt(v, "admin_latency_budget_p95") is None


def test_filas_saturadas_sin_rechazos_observados_fail():
    """Gate ciego del core (#139 hallazgo 1): el producto tiene filas rejected_saturated
    pero el guion no vio NINGÚN 503 saturado — un proxy que come el header dejaría al
    detector ciego. Eso jamás puede ser un PASS trivial."""
    recon = _clean_reconciliation()
    recon["filas_rejected_saturated"] = 120
    # (1) el guion declaró explícitamente 0 rechazos
    k6 = _clean_k6_summary()
    k6["saturated_rejections"] = 0
    v = _evaluate(k6_summary=k6, reconciliation=recon)
    s = _slo(v, "saturated_503_rows_durable")
    assert s.veredicto == "FAIL" and s.medido is None
    assert "proxy" in s.detalle["nota"]
    assert v.global_veredicto == "FAIL"
    # (2) el guion ni declaró el contador (summary pre-C1): la asimetría igual se VE
    v2 = _evaluate(reconciliation=recon)
    s2 = _slo(v2, "saturated_503_rows_durable")
    assert s2.veredicto == "FAIL" and v2.global_veredicto == "FAIL"
    # (3) filas=0 con 0 rechazos sigue siendo vacuo (dry-run del drill intacto)
    recon0 = _clean_reconciliation()
    recon0["filas_rejected_saturated"] = 0
    k60 = _clean_k6_summary()
    k60["saturated_rejections"] = 0
    v3 = _evaluate(gate=load_gate(DRILL_FILE), k6_summary=k60, reconciliation=recon0)
    assert _slo(v3, "saturated_503_rows_durable").veredicto == "PASS"


def test_verdict_del_drill_es_determinista():
    recon = _clean_reconciliation()
    recon["filas_rejected_saturated"] = 120
    kw = dict(gate=load_gate(DRILL_FILE), k6_summary=_saturated_summary(),
              reconciliation=recon, drill_overrides={"admin_p95_budget_ms": 250.0})
    assert _evaluate(**copy.deepcopy(kw)).to_json() == _evaluate(**copy.deepcopy(kw)).to_json()


# ── (c) orquestador: kind efectivo y overrides ────────────────────────────────────────

def test_kind_efectivo_drill_sale_del_yaml(tmp_path):
    """El YAML manda: un drill no se corre por accidente como gate oficial."""
    orch = Orchestrator(load_gate(DRILL_FILE), run_id="d1", runs_dir=tmp_path, timestamp=TS)
    assert orch.kind == "drill"


def test_kind_explicito_solo_manda_en_gates_oficiales(tmp_path):
    orch = Orchestrator(load_gate(GATE_FILE), run_id="g1", runs_dir=tmp_path, timestamp=TS,
                        kind="diagnostico")
    assert orch.kind == "diagnostico"
    # y --kind NO puede degradar un drill a otra cosa
    orch = Orchestrator(load_gate(DRILL_FILE), run_id="d2", runs_dir=tmp_path, timestamp=TS,
                        kind="diagnostico")
    assert orch.kind == "drill"


def test_dry_run_gana_sobre_el_kind_del_yaml(tmp_path):
    orch = Orchestrator(load_gate(DRILL_FILE), run_id="d3", runs_dir=tmp_path, timestamp=TS,
                        dry_run=True)
    assert orch.kind == "dry-run"


def test_fases_del_drill_son_secuenciales_en_k6(tmp_path):
    """A2: sin `startTime` k6 corre TODOS los scenarios desde t=0 — la ráfaga caería sobre
    una cola FRÍA, no sobre la que llenó el sostenido. El burst arranca a los 10 min."""
    orch = Orchestrator(load_gate(DRILL_FILE), run_id="k1", runs_dir=tmp_path, timestamp=TS,
                        dry_run=True, n_canaries=4, n_corpus_docs=4)
    orch.run_dir.mkdir(parents=True, exist_ok=True)
    cfg = orch._write_k6_config([], {})
    starts = {(s["surface"], s["phase"]): s["startTime"] for s in cfg["scenarios"]}
    assert {v for (surf, ph), v in starts.items() if ph == "sustained"} == {"0s"}
    assert {v for (surf, ph), v in starts.items() if ph == "burst"} == {"600s"}
    # todas las superficies de una misma fase comparten arranque
    assert len([s for s in cfg["scenarios"] if s["phase"] == "burst"]) == 4


def test_gate_de_una_fase_arranca_en_cero(tmp_path):
    orch = Orchestrator(load_gate(GATE_FILE), run_id="k2", runs_dir=tmp_path, timestamp=TS,
                        dry_run=True, n_canaries=4, n_corpus_docs=4)
    orch.run_dir.mkdir(parents=True, exist_ok=True)
    cfg = orch._write_k6_config([], {})
    assert {s["startTime"] for s in cfg["scenarios"]} == {"0s"}


def test_default_run_id_del_drill_no_choca_con_el_del_oficial(tmp_path):
    """A3: mismo día, mismo gate 125 → el id por defecto tiene que distinguir el examen."""
    from datetime import datetime, timezone
    ahora = lambda: datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)  # noqa: E731
    drill = Orchestrator(load_gate(DRILL_FILE), runs_dir=tmp_path, timestamp=TS, now=ahora)
    oficial = Orchestrator(load_gate(GATE_FILE), runs_dir=tmp_path, timestamp=TS, now=ahora)
    assert drill.run_id == "20260810-g125-drill-01"
    assert oficial.run_id == "20260810-g125-01"
    assert drill.run_id != oficial.run_id
    seco = Orchestrator(load_gate(DRILL_FILE), runs_dir=tmp_path, timestamp=TS, now=ahora,
                        dry_run=True)
    assert seco.run_id == "20260810-g125-dry-run-01"


def test_segundo_run_al_mismo_run_dir_no_pisa_la_evidencia(tmp_path):
    """La evidencia de un run NO se sobrescribe: el error SALE (dentro del try se
    escribiría un verdict parcial encima del run que se quiere proteger)."""
    def _orch():
        return Orchestrator(load_gate(DRILL_FILE), run_id="d7", runs_dir=tmp_path,
                            timestamp=TS, dry_run=True, n_canaries=4, n_corpus_docs=4)

    primero = _orch()
    primero.run()
    original = (primero.run_dir / "verdict.json").read_text(encoding="utf-8")
    with pytest.raises(OrchestratorError) as exc:
        _orch().run()
    assert "ya contiene un verdict.json" in str(exc.value)
    assert "--run-id" in str(exc.value)
    assert (primero.run_dir / "verdict.json").read_text(encoding="utf-8") == original


def test_cli_segundo_run_mismo_run_id_error_accionable(tmp_path, capsys):
    argv = ["--gate-file", str(DRILL_FILE), "--dry-run", "--runs-dir", str(tmp_path),
            "--run-id", "t1"]
    assert main(argv) in (0, 1, 2)          # el primero corre y reporta
    assert main(argv) == 2                  # el segundo NO pisa: error accionable
    assert "ya contiene un verdict.json" in capsys.readouterr().err


def _fingerprint_de(gate_file, tmp_path, run_id):
    orch = Orchestrator(load_gate(gate_file), run_id=run_id, runs_dir=tmp_path,
                        timestamp=TS, n_canaries=4, n_corpus_docs=4)
    return orch._build_fingerprint({"corpus_version": "1.0.0", "seed": 1, "canaries": [],
                                    "densities_per_mille": [0]}, {})


def test_fingerprint_del_drill_no_es_comparable_con_el_del_125_oficial(tmp_path):
    """A4: mismo gate, misma versión, misma mezcla y cadencia — antes los dos fingerprints
    solo diferían en el timestamp (NO material) y el comparador decía «LEGÍTIMA»: se podían
    contrastar las métricas de dos exámenes distintos como si fueran el mismo."""
    drill = _fingerprint_de(DRILL_FILE, tmp_path, "fp-drill")
    oficial = _fingerprint_de(GATE_FILE, tmp_path, "fp-oficial")
    res = compare(drill, oficial)
    assert res.comparable is True
    assert res.legitimate is False
    paths = {d.path for d in res.diffs}
    assert "gate.kind" in paths                                  # drill vs gate_oficial
    assert any(p.startswith("examen.stub") for p in paths)       # sede-lenta vs normal
    assert any(p.startswith("examen.phases") for p in paths)     # sustained+burst vs solo
    # y el par de repetibilidad del propio drill SIGUE siendo legítimo
    assert compare(drill, _fingerprint_de(DRILL_FILE, tmp_path, "fp-drill-2")).legitimate


def test_fingerprint_del_drill_declara_el_programa_del_examen(tmp_path):
    fp = _fingerprint_de(DRILL_FILE, tmp_path, "fp-drill-3").to_dict()
    assert fp["gate"] == {"n": 125, "version": "1.1.0", "kind": "drill"}
    assert fp["examen"]["stub"] == {"latency_ms": {"chat": 800, "coding_first_token": 600},
                                    "token_rate_tps": 5, "stream_duration_s": [60, 120],
                                    "error_rate": 0.0}
    assert fp["examen"]["phases"] == [
        {"name": "sustained", "duration": "10m", "arrival_factor": 1.0},
        {"name": "burst", "duration": "5m", "arrival_factor": 3.0}]
    # orden canónico: `examen` va inmediatamente después de `gate`
    claves = list(fp)
    assert claves[claves.index("gate") + 1] == "examen"


def test_cli_budget_sobre_gate_no_drill_error_accionable(tmp_path, capsys):
    """B1: sobre un gate oficial el flag no haría NADA (el evaluador solo mira
    drill.criteria en un run drill) y el operador creería haber fijado un umbral."""
    with pytest.raises(SystemExit) as exc:
        main(["--gate", "125", "--dry-run", "--runs-dir", str(tmp_path),
              "--run-id", "b1", "--drill-admin-budget-ms=33"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--drill-admin-budget-ms solo aplica a un gate kind: drill" in err
    assert not (tmp_path / "b1").exists()


def test_cli_budget_sobre_el_drill_en_seco_si_aplica(tmp_path):
    """La guarda mira el kind del GATE: un --dry-run del drill sigue siendo un drill."""
    assert main(["--gate-file", str(DRILL_FILE), "--dry-run", "--runs-dir", str(tmp_path),
                 "--run-id", "b1-ok", "--drill-admin-budget-ms=33"]) == 0
    data = json.loads((tmp_path / "b1-ok" / "verdict.json").read_text(encoding="utf-8"))
    fila = next(s for s in data["slos"] if s["slo"] == "admin_latency_budget_p95")
    assert fila["detalle"]["umbral_ms"] == 33.0


def test_drill_overrides_desde_la_cli():
    assert _drill_overrides(None) is None
    assert _drill_overrides(250) == {"admin_p95_budget_ms": 250.0}


def test_drill_admin_budget_llega_al_evaluador(tmp_path):
    """El flag --drill-admin-budget-ms termina produciendo la fila del presupuesto."""
    orch = Orchestrator(load_gate(DRILL_FILE), run_id="d4", runs_dir=tmp_path, timestamp=TS,
                        dry_run=True, n_canaries=4, n_corpus_docs=4,
                        drill_admin_budget_ms=250.0)
    verdict = orch.run()
    assert _slo_opt(verdict, "admin_latency_budget_p95") is not None
    assert _slo(verdict, "admin_latency_budget_p95").detalle["umbral_ms"] == 250.0


def test_dry_run_del_drill_trae_filas_rejected_saturated(tmp_path):
    """En seco, el reconcile del drill declara el campo (0) — el del gate oficial NO se
    toca: su dict sigue siendo el de siempre."""
    drill = Orchestrator(load_gate(DRILL_FILE), run_id="d5", runs_dir=tmp_path, timestamp=TS,
                         dry_run=True, n_canaries=4, n_corpus_docs=4)
    assert "filas_rejected_saturated" in drill._reconcile({"auditable_events": 10})
    oficial = Orchestrator(load_gate(GATE_FILE), run_id="g5", runs_dir=tmp_path,
                           timestamp=TS, dry_run=True, n_canaries=4, n_corpus_docs=4)
    assert oficial._reconcile({"auditable_events": 10}) == {
        "eventos_guion": 10, "filas_persistidas": 10,
        "bloqueos_provocados": 0, "con_fila": 0}


def test_dry_run_completo_del_drill(tmp_path):
    """El drill corre en seco de punta a punta y marca el run como drill."""
    orch = Orchestrator(load_gate(DRILL_FILE), run_id="d6", runs_dir=tmp_path, timestamp=TS,
                        dry_run=True, n_canaries=4, n_corpus_docs=4)
    verdict = orch.run()
    assert verdict.estado == "completed"
    data = json.loads((orch.run_dir / "verdict.json").read_text(encoding="utf-8"))
    assert data["kind"] == "dry-run"
    assert "saturated_503_rows_durable" in {s["slo"] for s in data["slos"]}


def test_el_graceful_stop_cubre_el_stream_mas_largo(tmp_path):
    """Artefacto medido en 20260812-g125-drill-01 (+15 filas): con el gracefulStop por
    defecto de k6 (30 s), un stream de 60-120 s del modo sede-lenta queda cortado al
    terminar la fase; el guion no cuenta su evento y el producto ya escribió la fila, así
    que la reconciliación reporta «sobran filas» sin que se haya perdido nada."""
    orch = Orchestrator(load_gate(DRILL_FILE), run_id="gs", runs_dir=tmp_path, timestamp=TS,
                        dry_run=True, n_canaries=4, n_corpus_docs=4)
    orch.run()
    cfg = json.loads((orch.run_dir / "k6_config.json").read_text())
    # el drill sirve streams de hasta 120 s → margen de 135 s en TODOS los scenarios
    assert cfg["scenarios"], "el gate no produjo scenarios"
    assert all(s["gracefulStop"] == "135s" for s in cfg["scenarios"]), \
        [s.get("gracefulStop") for s in cfg["scenarios"]]


def test_el_gate_oficial_tiene_su_propio_margen(tmp_path):
    """El margen sale del gate, no de una constante: el 125 sirve streams de hasta 60 s."""
    orch = Orchestrator(125, run_id="gs2", runs_dir=tmp_path, timestamp=TS,
                        dry_run=True, n_canaries=4, n_corpus_docs=4)
    orch.run()
    cfg = json.loads((orch.run_dir / "k6_config.json").read_text())
    assert all(s["gracefulStop"] == "75s" for s in cfg["scenarios"])
