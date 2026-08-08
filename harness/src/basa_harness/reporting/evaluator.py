"""Evaluador de SLO del run (spec 035, T025; contract ``run-report.md`` §verdict.json).

Computa el VEREDICTO automático (SC-002) de un gate a partir de EXACTAMENTE tres fuentes
—k6 (el instrumento), el PRODUCTO (su ``/health`` y sus filas de auditoría) y el STUB (su
detector de canarios y su auto-headroom)—. **REGLA DURA R3**: el veredicto JAMÁS se computa
de Prometheus/Grafana/observabilidad; la observabilidad caída invalida el tablero, no el
examen. Este módulo no toca la observabilidad ni el reloj: recibe dicts ya leídos y un
``timestamp`` INYECTADO (determinismo — mismos insumos → mismo verdict, byte a byte).

Los 4 SLO de oro (FR-007, ``CANONICAL_SLOS`` del gate_loader):

- (a) ``audit_lost_events_delta_zero`` — Δ del contador ``audit.lost_events`` del
  ``/health`` (leído con credencial compliance) == 0. Tres estados del contador que el
  consumidor NO puede confundir (backend/src/api/health.py):
    * ``0``    la auditoría nunca perdió nada;
    * ``N``    N eventos sin registrar;
    * ``null`` ilegible (Redis caído) → **FAIL**, jamás se interpreta como 0.
  Y dos causas de RUN INVÁLIDO (no hay veredicto, la medición está viciada):
    * el bloque ``audit`` AUSENTE ⇒ el lector no tenía credencial (bug del harness);
    * ``final < inicial`` ⇒ el almacén se reseteó a mitad de run.
- (b) ``reconciliation_rows`` — filas de auditoría persistidas == eventos auditables del
  guion. ``medido`` = filas − eventos (0 = PASS).
- (c) ``zero_raw_canaries`` — 0 canarios crudos en el stub (del ``/control/report``).
- (d) ``blocked_rows_durable_100`` — 100% de los bloqueos provocados con fila durable.

**Global**: ``PASS`` ⟺ los 4 SLO PASS + ``estado: completed`` + ``instrumento.valido``.
Si el examen está viciado (run interrumpido, contador que retrocede, credencial
insuficiente, o el instrumento no sostuvo el modelo abierto / el stub se quedó sin
headroom) ⇒ ``estado: invalid`` y ``global: INVALID`` — nunca un PASS/FAIL que parezca un
examen limpio (edge case de la spec). ``FAIL`` es un examen VÁLIDO donde el producto violó
un SLO.

**Overhead** (FR-008): por superficie y percentil, ``overhead = latencia medida −
latencia programada del stub``. TTFT y cortes de stream SOLO en coding (única superficie
SSE).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

from .gate_loader import CANONICAL_SLOS, Gate

# Fuente citada en el detalle del SLO (a) — trazabilidad del contrato.
FUENTE_AUDIT = "GET /api/v1/health (audit.lost_events, credencial compliance)"

# Percentiles que reporta el overhead (FR-008).
PERCENTILES: tuple[str, ...] = ("p50", "p95", "p99", "max")

# Latencia programada por defecto (ms) derivada del bloque ``stub`` del gate: chat y
# coding_first_token vienen del contrato; ext/admin no atraviesan latencia de proveedor.
_DEFAULT_PROGRAMMED_MS = {"chat": 0.0, "extension": 0.0, "coding": 0.0,
                          "coding_first_token": 0.0, "admin": 0.0, "login": 0.0}


# ── Estructuras del verdict ───────────────────────────────────────────────────────────

@dataclass
class SLOResult:
    """Un SLO evaluado: valor medido, veredicto y evidencia (contract §slos[])."""
    slo: str
    medido: object            # número, ratio o None (null en (a) = FAIL, nunca 0)
    veredicto: str            # "PASS" | "FAIL"
    detalle: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"slo": self.slo, "medido": self.medido,
                "veredicto": self.veredicto, "detalle": self.detalle}


@dataclass
class Verdict:
    """El ``verdict.json`` completo (contract ``run-report.md``)."""
    run_id: str
    gate: dict                # {"n": 125, "version": "1.0.0"}
    estado: str               # completed | invalid | interrupted
    global_veredicto: str     # PASS | FAIL | INVALID  (serializa como "global")
    slos: list                # list[SLOResult]
    por_fase: dict = field(default_factory=dict)
    instrumento: dict = field(default_factory=dict)
    overhead: dict = field(default_factory=dict)
    invalid_reason: Optional[str] = None
    timestamp: str = ""
    kind: str = "gate_oficial"
    notas: list = field(default_factory=list)

    @property
    def is_pass(self) -> bool:
        return self.global_veredicto == "PASS"

    def to_dict(self) -> dict:
        out = {
            "run_id": self.run_id,
            "gate": self.gate,
            "kind": self.kind,
            "estado": self.estado,
            "global": self.global_veredicto,
            "slos": [s.to_dict() for s in self.slos],
            "por_fase": self.por_fase,
            "instrumento": self.instrumento,
            "overhead": self.overhead,
            "timestamp": self.timestamp,
        }
        if self.invalid_reason:
            out["invalid_reason"] = self.invalid_reason
        if self.notas:
            out["notas"] = list(self.notas)
        return out

    def to_json(self, *, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=False)


# ── SLO (a): contador de auditoría ────────────────────────────────────────────────────

def _audit_lost_events(health: object) -> Union[int, str]:
    """Clasifica el contador de una respuesta ``/health``:

    - ``"missing"``  el bloque ``audit`` no vino → credencial insuficiente (run inválido);
    - ``"null"``     ``lost_events`` ilegible/ausente dentro de un ``audit`` presente → FAIL;
    - ``int``        el valor del contador.
    """
    if not isinstance(health, dict):
        return "missing"
    audit = health.get("audit")
    if not isinstance(audit, dict):
        return "missing"            # bloque ausente = credencial (jamás lo devuelve null)
    if "lost_events" not in audit:
        return "null"               # audit presente pero sin el campo → como ilegible
    v = audit["lost_events"]
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        return "null"
    return v


def eval_audit(health_initial: object,
               health_final: object) -> tuple[SLOResult, Optional[str]]:
    """Evalúa el SLO (a). Devuelve ``(SLOResult, invalid_reason|None)``.

    ``invalid_reason`` no-nulo vicia el run entero (credencial ausente o contador que
    retrocede); el SLOResult se conserva como evidencia parcial.
    """
    ai = _audit_lost_events(health_initial)
    af = _audit_lost_events(health_final)
    detalle: dict = {"fuente": FUENTE_AUDIT}

    if ai == "missing" or af == "missing":
        detalle.update({
            "inicial": None, "final": None,
            "nota": ("el bloque 'audit' no vino en /health: el lector no tenía credencial "
                     "admin/compliance (bug del harness, NO un fallo del producto) → run "
                     "inválido; distinto de lost_events=null, que sí es FAIL del sistema"),
        })
        res = SLOResult("audit_lost_events_delta_zero", None, "FAIL", detalle)
        return res, ("credencial insuficiente del evaluador: /health no devolvió el bloque "
                     "'audit' (¿el lector se autenticó como el compliance_officer del seed?)")

    inicial = None if ai == "null" else ai
    final = None if af == "null" else af
    detalle.update({"inicial": inicial, "final": final})

    if inicial is None or final is None:
        detalle["nota"] = ("lost_events es null (Redis ilegible): la auditoría no puede "
                           "afirmar 'cero pérdidas' — FAIL, jamás se interpreta como 0")
        return SLOResult("audit_lost_events_delta_zero", None, "FAIL", detalle), None

    if final < inicial:
        detalle["nota"] = (f"el contador retrocedió (final {final} < inicial {inicial}): "
                           "reset del almacén de auditoría durante el run")
        return (SLOResult("audit_lost_events_delta_zero", final - inicial, "FAIL", detalle),
                f"el contador de auditoría retrocedió (final {final} < inicial {inicial}): "
                "reset del almacén durante el run → run inválido, no comparable")

    delta = final - inicial
    veredicto = "PASS" if delta == 0 else "FAIL"
    if delta != 0:
        detalle["nota"] = f"{delta} evento(s) de auditoría perdidos durante el run"
    return SLOResult("audit_lost_events_delta_zero", delta, veredicto, detalle), None


# ── SLO (b): reconciliación de filas ──────────────────────────────────────────────────

def eval_reconciliation(reconciliation: dict) -> SLOResult:
    eventos = reconciliation.get("eventos_guion")
    filas = reconciliation.get("filas_persistidas")
    detalle = {"eventos_guion": eventos, "filas_persistidas": filas,
               "fuente": "conteo del guion (eventos auditables) vs audit_logs del producto"}
    if not _is_int(eventos) or not _is_int(filas):
        detalle["nota"] = ("faltan datos de reconciliación (eventos del guion o filas "
                           "persistidas) — no se puede afirmar paridad → FAIL")
        return SLOResult("reconciliation_rows", None, "FAIL", detalle)
    medido = filas - eventos
    veredicto = "PASS" if medido == 0 else "FAIL"
    if medido != 0:
        signo = "faltan" if medido < 0 else "sobran"
        detalle["nota"] = f"{signo} {abs(medido)} fila(s) frente a los eventos auditables"
    return SLOResult("reconciliation_rows", medido, veredicto, detalle)


# ── SLO (c): canarios crudos ──────────────────────────────────────────────────────────

def eval_canaries(stub_report: dict, *, max_evidencia: int = 20) -> SLOResult:
    evidencias = stub_report.get("canarios_detectados") or []
    leak_count = stub_report.get("leak_count")
    if not _is_int(leak_count):
        leak_count = len(evidencias)
    detalle = {
        "canarios_detectados": leak_count,
        "canary_set_size": stub_report.get("canary_set_size"),
        "evidencia": evidencias[:max_evidencia],
        "fuente": "GET /control/report del stub (detector inline + barrido del spool)",
    }
    veredicto = "PASS" if leak_count == 0 else "FAIL"
    if leak_count:
        detalle["nota"] = (f"{leak_count} canario(s) del run aparecieron EN CLARO en el "
                           "stub: el masking falló")
    return SLOResult("zero_raw_canaries", leak_count, veredicto, detalle)


# ── SLO (d): bloqueos con fila durable ────────────────────────────────────────────────

def eval_blocked_durable(reconciliation: dict) -> SLOResult:
    provocados = reconciliation.get("bloqueos_provocados")
    con_fila = reconciliation.get("con_fila")
    detalle = {"bloqueos_provocados": provocados, "con_fila": con_fila,
               "fuente": "bloqueos observados (guion) vs filas durables (audit_logs)"}
    if not _is_int(provocados) or not _is_int(con_fila):
        detalle["nota"] = "faltan datos de bloqueos/filas durables → FAIL"
        return SLOResult("blocked_rows_durable_100", None, "FAIL", detalle)
    if provocados == 0:
        # Vacuamente satisfecho: ningún bloqueo que auditar (p. ej. densidad 0 / masking on).
        detalle["nota"] = "no se provocaron bloqueos en este run (100% trivial)"
        return SLOResult("blocked_rows_durable_100", 1.0, "PASS", detalle)
    medido = round(con_fila / provocados, 6)
    veredicto = "PASS" if con_fila == provocados else "FAIL"
    if veredicto == "FAIL":
        detalle["nota"] = (f"{provocados - con_fila} bloqueo(s) SIN fila durable: se negó "
                           "acceso sin dejar rastro auditable")
    return SLOResult("blocked_rows_durable_100", medido, veredicto, detalle)


# ── Instrumento (evidencia de modelo abierto + headroom del stub) ─────────────────────

def eval_instrument(k6_summary: dict, stub_report: dict) -> dict:
    """Valida el INSTRUMENTO (no el producto): que k6 sostuvo el modelo abierto y que el
    stub no mintió por falta de headroom. Un instrumento inválido vicia el examen."""
    dropped = k6_summary.get("dropped_iterations_total")
    if not _is_int(dropped):
        dropped = _sum_surface_dropped(k6_summary)
    drift = (stub_report.get("pacing_drift_ms") or {}).get("p99")
    cpu = stub_report.get("cpu_pct")
    unauditable = (stub_report.get("trafico_no_auditable") or {}).get("count", 0)
    stub_valido = bool(stub_report.get("valido", False))
    valido = (dropped == 0) and stub_valido and (unauditable == 0)
    razones = []
    if dropped != 0:
        razones.append(f"dropped_iterations={dropped} (k6 no sostuvo la tasa: modelo "
                       "cerrado, run inválido)")
    if not stub_valido:
        razones.append(f"stub sin headroom (drift p99={drift} ms, cpu={cpu}%)")
    if unauditable:
        razones.append(f"{unauditable} request(s) no auditable(s): punto ciego del "
                       "detector de canarios")
    return {
        "dropped_iterations": dropped,
        "stub_drift_p99_ms": drift,
        "stub_cpu_pct": cpu,
        "trafico_no_auditable": unauditable,
        "valido": valido,
        "razones_invalidez": razones,
    }


def _sum_surface_dropped(k6_summary: dict) -> int:
    total = 0
    for s in (k6_summary.get("surfaces") or {}).values():
        d = s.get("dropped_iterations")
        if _is_int(d):
            total += d
    return total


# ── Overhead (FR-008) ─────────────────────────────────────────────────────────────────

def compute_overhead(k6_summary: dict, programmed_ms: dict) -> dict:
    """``overhead = medido − programado`` por superficie y percentil. TTFT y cortes solo
    en coding (única SSE)."""
    out: dict = {}
    for surface, s in (k6_summary.get("surfaces") or {}).items():
        prog = float(programmed_ms.get(surface, 0.0))
        lat = s.get("latency_ms") or {}
        entry = {
            "programada_ms": prog,
            "medida_ms": {p: lat[p] for p in PERCENTILES if p in lat},
            "overhead_ms": {p: round(lat[p] - prog, 4) for p in PERCENTILES if _is_num(lat.get(p))},
        }
        if "ttft_ms" in s:  # coding: overhead del PRIMER token vs coding_first_token
            prog_ttft = float(programmed_ms.get("coding_first_token",
                                                programmed_ms.get(surface, 0.0)))
            ttft = s.get("ttft_ms") or {}
            entry["ttft_programada_ms"] = prog_ttft
            entry["ttft_medida_ms"] = {p: ttft[p] for p in PERCENTILES if p in ttft}
            entry["ttft_overhead_ms"] = {p: round(ttft[p] - prog_ttft, 4)
                                         for p in PERCENTILES if _is_num(ttft.get(p))}
            entry["stream_cuts"] = s.get("stream_cuts", 0)
        out[surface] = entry
    return out


def _programmed_from_gate(gate: Optional[Gate], override: Optional[dict]) -> dict:
    prog = dict(_DEFAULT_PROGRAMMED_MS)
    if gate is not None:
        stub = getattr(gate, "stub", None) or {}
        lat = stub.get("latency_ms") or {}
        if _is_num(lat.get("chat")):
            prog["chat"] = float(lat["chat"])
        if _is_num(lat.get("coding_first_token")):
            prog["coding_first_token"] = float(lat["coding_first_token"])
            prog["coding"] = float(lat["coding_first_token"])
    if override:
        prog.update({k: float(v) for k, v in override.items() if _is_num(v)})
    return prog


def _por_fase(k6_summary: dict, programmed_ms: dict, gate: Optional[Gate]) -> dict:
    """Overhead por fase (250/500: tormenta/sostenido/pico/recuperación). Si k6 no separó
    fases, se reporta la fase única del gate con el agregado global."""
    by_phase = k6_summary.get("by_phase")
    out: dict = {}
    if isinstance(by_phase, dict) and by_phase:
        for phase, block in by_phase.items():
            out[phase] = {
                "surfaces": compute_overhead(block, programmed_ms),
                "dropped_iterations": block.get("dropped_iterations_total",
                                                _sum_surface_dropped(block)),
            }
        return out
    # Sin desglose: una sola fase (el nombre del gate si está, si no "sostenido").
    phase = gate.phases[0].name if (gate and gate.phases) else "sostenido"
    out[phase] = {"surfaces": compute_overhead(k6_summary, programmed_ms),
                  "dropped_iterations": k6_summary.get("dropped_iterations_total",
                                                       _sum_surface_dropped(k6_summary))}
    return out


# ── Orquestación del veredicto ────────────────────────────────────────────────────────

def evaluate(gate: Union[Gate, dict, None], *, run_id: str, timestamp: str,
             k6_summary: dict, health_initial: object, health_final: object,
             stub_report: dict, reconciliation: dict,
             programmed_latency_ms: Optional[dict] = None,
             interrupted: bool = False, kind: str = "gate_oficial",
             notas: Optional[list] = None) -> Verdict:
    """Computa el ``Verdict`` de un run a partir de k6 + producto + stub (NUNCA de la
    observabilidad — R3). ``timestamp`` INYECTADO (determinismo)."""
    gate_meta, gate_obj = _gate_meta(gate)
    programmed = _programmed_from_gate(gate_obj, programmed_latency_ms)

    audit_res, audit_invalid = eval_audit(health_initial, health_final)
    recon_res = eval_reconciliation(reconciliation)
    canary_res = eval_canaries(stub_report)
    blocked_res = eval_blocked_durable(reconciliation)
    slos = [audit_res, recon_res, canary_res, blocked_res]
    # Orden canónico estable (FR-007) para comparabilidad byte a byte del verdict.json.
    slos.sort(key=lambda r: CANONICAL_SLOS.index(r.slo) if r.slo in CANONICAL_SLOS else 99)

    instrumento = eval_instrument(k6_summary, stub_report)
    overhead = compute_overhead(k6_summary, programmed)
    por_fase = _por_fase(k6_summary, programmed, gate_obj)

    # Estado del run: cualquier vicio estructural ⇒ invalid (examen no certificable).
    estado = "completed"
    invalid_reason: Optional[str] = None
    if interrupted:
        estado, invalid_reason = "invalid", "run interrumpido antes de completar la carga"
    elif audit_invalid:
        estado, invalid_reason = "invalid", audit_invalid
    elif not instrumento["valido"]:
        estado = "invalid"
        invalid_reason = "instrumento inválido: " + "; ".join(instrumento["razones_invalidez"])

    all_pass = all(r.veredicto == "PASS" for r in slos)
    if estado != "completed":
        global_veredicto = "INVALID"
    elif all_pass:
        global_veredicto = "PASS"
    else:
        global_veredicto = "FAIL"

    return Verdict(
        run_id=run_id, gate=gate_meta, estado=estado,
        global_veredicto=global_veredicto, slos=slos, por_fase=por_fase,
        instrumento=instrumento, overhead=overhead, invalid_reason=invalid_reason,
        timestamp=timestamp, kind=kind, notas=list(notas or []),
    )


def _gate_meta(gate: Union[Gate, dict, None]) -> tuple[dict, Optional[Gate]]:
    if isinstance(gate, Gate):
        return {"n": gate.gate, "version": gate.version}, gate
    if isinstance(gate, dict):
        n = gate.get("n", gate.get("gate"))
        return {"n": n, "version": gate.get("version")}, None
    return {"n": None, "version": None}, None


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)
