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

**Drill de saturación (extensión C1)**: cuando el backend se defiende de la saturación
rechazando con un 503 rápido (``X-Basa-Rejected: saturated``), el examen mide TAMBIÉN esa
defensa. ``saturated_503_rows_durable`` es el espejo de (d) para el rechazo —negar
servicio sin dejar fila durable es tan grave como bloquear sin dejarla— y se evalúa en
todo run que vea rechazos. Los criterios de tiempo (``rejection_time_to_503_p95``,
``admin_latency_budget_p95``) son propios del gate ``kind: drill`` y viven en
``drill.criteria``: NO reemplazan ni relajan los 4 SLO de oro, que siguen siendo
obligatorios. Un run sin rechazos y sin drill produce un verdict IDÉNTICO al de antes de
C1: las filas nuevas no se agregan.

Y un **drill que no saturó** no es un PASS: sus criterios quedan vacuos porque la defensa
nunca se ejercitó, así que el run sale ``invalid`` (examen no tomado, no aprobado). El
dry-run del drill queda afuera de esa regla: corre con datos sintéticos y ya está marcado
NO oficial.
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
        """Serializa el verdict. ``allow_nan=False`` es un CINTURÓN: NaN/Infinity no
        existen en JSON (RFC 8259) y Python los escribiría como los literales inválidos
        ``NaN``/``Infinity``. Un verdict.json que ningún parser estándar lee es peor que
        un fallo ruidoso — si un percentil llegó NaN, revienta acá y el run se marca
        inválido, no se publica evidencia no-parseable."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent,
                          sort_keys=False, allow_nan=False)


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


# ── Extensión C1: rechazo de admisión (503 saturado) ──────────────────────────────────

def eval_saturated_durable(k6_summary: dict, reconciliation: dict) -> SLOResult:
    """Espejo de (d) para el rechazo de admisión: 1 fila durable por cada 503 saturado.

    El guion cuenta un rechazo por cada 503 con ``X-Basa-Rejected: saturated`` (el header
    ES la llave: un 503 sin él es un proxy, no admisión). El producto debe tener esa misma
    cantidad de filas en ``audit_logs`` con el estado literal ``rejected_saturated``,
    escritas ANTES de responder —incluido el camino del queue-timeout—. Negar servicio sin
    rastro auditable es el mismo pecado que bloquear sin rastro.
    """
    rechazos = k6_summary.get("saturated_rejections")
    filas = reconciliation.get("filas_rejected_saturated")
    detalle = {"rechazos_guion": rechazos, "filas_rejected_saturated": filas,
               "fuente": "503 con X-Basa-Rejected: saturated (guion) vs audit_logs con "
                         "estado 'rejected_saturated' (producto)"}
    if not _is_int(rechazos) or rechazos == 0:
        # Vacuamente satisfecho: el producto nunca tuvo que rechazar (100% trivial).
        detalle["nota"] = "no hubo rechazos por saturación en este run (100% trivial)"
        return SLOResult("saturated_503_rows_durable", 1.0, "PASS", detalle)
    if not _is_int(filas):
        detalle["nota"] = ("hubo rechazos pero falta el conteo de filas "
                           "'rejected_saturated' — no se puede afirmar durabilidad → FAIL")
        return SLOResult("saturated_503_rows_durable", None, "FAIL", detalle)
    medido = round(filas / rechazos, 6)
    veredicto = "PASS" if filas == rechazos else "FAIL"
    if veredicto == "FAIL":
        detalle["nota"] = (f"{rechazos - filas} rechazo(s) 503 SIN fila durable: se negó "
                           "servicio sin dejar rastro auditable")
    return SLOResult("saturated_503_rows_durable", medido, veredicto, detalle)


def eval_drill_criteria(k6_summary: dict, criteria: dict) -> tuple[list, list]:
    """Criterios propios del gate ``kind: drill``. Devuelve ``(filas, notas)``.

    Un criterio SIN umbral no se evalúa con un número inventado: no produce fila y deja
    una nota que dice cómo fijarlo. Con umbral fijado es VINCULANTE (entra en el global
    del drill) — para eso se corre el drill.
    """
    filas: list = []
    notas: list = []

    # (1) tiempo hasta el 503: un rechazo SANO tarda ~el queue-timeout. El anti-patrón que
    # este criterio caza son los timeouts largos (el incidente del 30-jul): el cliente
    # esperando minutos por una respuesta que el backend ya sabía que no iba a dar.
    umbral_rej = criteria.get("rejection_p95_max_ms")
    if not _is_num(umbral_rej):
        notas.append("criterio rejection sin umbral: 'drill.criteria.rejection_p95_max_ms' "
                     "no está fijado, no se evalúa el tiempo hasta el 503")
    else:
        rechazos = k6_summary.get("saturated_rejections")
        p95 = (k6_summary.get("rejection_ms") or {}).get("p95")
        detalle = {"umbral_ms": float(umbral_rej), "rechazos": rechazos,
                   "fuente": "k6 rejection_ms.p95 (Trend lat_rejection, aparte de las "
                             "latencias de servicio)"}
        hubo_rechazos = _is_num(rechazos) and rechazos > 0
        if not hubo_rechazos:
            detalle["nota"] = ("el producto no rechazó ninguna request: el criterio no "
                               "aplica (PASS vacuo, no hay p95 que medir)")
            filas.append(SLOResult("rejection_time_to_503_p95", None, "PASS", detalle))
        elif not _is_num(p95):
            # HUBO rechazos y falta el cronómetro: no es lo mismo que no haber rechazado.
            # Espejo de la rama admin — con el criterio fijado, no poder afirmarlo es FAIL.
            detalle["nota"] = (f"hubo {rechazos} rechazos pero falta rejection_ms.p95 — no "
                               "se puede afirmar el tiempo hasta el 503")
            filas.append(SLOResult("rejection_time_to_503_p95", None, "FAIL", detalle))
        else:
            veredicto = "PASS" if p95 <= umbral_rej else "FAIL"
            if veredicto == "FAIL":
                detalle["nota"] = (f"el rechazo tardó demasiado: p95={p95} ms > "
                                   f"{umbral_rej} ms — la defensa existe pero llega tarde")
            filas.append(SLOResult("rejection_time_to_503_p95", p95, veredicto, detalle))

    # (2) presupuesto del panel admin: bajo saturación, el plano de administración no puede
    # irse al pasto (es por donde se diagnostica y se apaga el incendio).
    umbral_admin = criteria.get("admin_p95_budget_ms")
    if not _is_num(umbral_admin):
        notas.append("umbral admin sin fijar: derivarlo del baseline del gate oficial del "
                     "mismo día y pasarlo por --drill-admin-budget-ms")
    else:
        admin = ((k6_summary.get("surfaces") or {}).get("admin") or {}).get("latency_ms") or {}
        p95 = admin.get("p95")
        detalle = {"umbral_ms": float(umbral_admin),
                   "fuente": "k6 surfaces.admin.latency_ms.p95"}
        if not _is_num(p95):
            detalle["nota"] = ("no hay latencia de admin medida en el run: con un "
                               "presupuesto fijado, no poder afirmarlo es FAIL")
            filas.append(SLOResult("admin_latency_budget_p95", None, "FAIL", detalle))
        else:
            veredicto = "PASS" if p95 <= umbral_admin else "FAIL"
            if veredicto == "FAIL":
                detalle["nota"] = (f"el panel admin se salió del presupuesto bajo "
                                   f"saturación: p95={p95} ms > {umbral_admin} ms")
            filas.append(SLOResult("admin_latency_budget_p95", p95, veredicto, detalle))

    return filas, notas


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
             notas: Optional[list] = None,
             drill_overrides: Optional[dict] = None) -> Verdict:
    """Computa el ``Verdict`` de un run a partir de k6 + producto + stub (NUNCA de la
    observabilidad — R3). ``timestamp`` INYECTADO (determinismo).

    ``drill_overrides`` pisa los umbrales de ``drill.criteria`` del gate (el umbral de
    admin se deriva del baseline MEDIDO del gate oficial del mismo día, no se hornea)."""
    gate_meta, gate_obj = _gate_meta(gate)
    programmed = _programmed_from_gate(gate_obj, programmed_latency_ms)

    audit_res, audit_invalid = eval_audit(health_initial, health_final)
    recon_res = eval_reconciliation(reconciliation)
    canary_res = eval_canaries(stub_report)
    blocked_res = eval_blocked_durable(reconciliation)
    slos = [audit_res, recon_res, canary_res, blocked_res]
    # Orden canónico estable (FR-007) para comparabilidad byte a byte del verdict.json.
    slos.sort(key=lambda r: CANONICAL_SLOS.index(r.slo) if r.slo in CANONICAL_SLOS else 99)

    # ── extensión C1 (aditiva, DESPUÉS de las 4 canónicas) ────────────────────────────
    # La durabilidad del rechazo se evalúa si el run es un drill o si el guion vio algún
    # 503 saturado. Sin drill y sin rechazos NO se agrega fila: el verdict de un
    # gate_oficial queda byte a byte igual al de antes de C1 (regla de oro del cambio).
    notas_drill: list = []
    rechazos = k6_summary.get("saturated_rejections")
    kind_drill = (kind == "drill") or (gate_obj is not None
                                       and getattr(gate_obj, "kind", "gate_oficial") == "drill")
    if kind_drill or (_is_int(rechazos) and rechazos > 0):
        slos.append(eval_saturated_durable(k6_summary, reconciliation))
    if kind_drill and gate_obj is not None:
        criteria = dict((getattr(gate_obj, "drill", None) or {}).get("criteria") or {})
        criteria.update(drill_overrides or {})
        filas_drill, notas_drill = eval_drill_criteria(k6_summary, criteria)
        slos.extend(filas_drill)

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
    elif kind_drill and kind != "dry-run" and _sin_saturacion(rechazos):
        # Un drill que NO saturó no midió la defensa C1: sus criterios quedan vacuos y el
        # verdict saldría PASS por no haber ejercitado nada. Eso no es un aprobado, es un
        # examen que no se tomó (el dry-run queda afuera: datos sintéticos, ya NO oficial).
        estado = "invalid"
        invalid_reason = ("el drill no alcanzó saturación: la defensa C1 no llegó a "
                          "ejercitarse (¿stub en modo sede-lenta? ¿SUT sobrado?)")

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
        timestamp=timestamp, kind=kind, notas=list(notas or []) + notas_drill,
    )


def _sin_saturacion(rechazos: object) -> bool:
    """¿El guion NO vio rechazos? Solo ``ausente/None`` y el entero ``0`` cuentan como
    «no saturó». Un conteo presente pero ILEGIBLE (float, string, bool) no se interpreta
    a favor de ninguna hipótesis: no vuelve el examen inválido — lo reprueba la fila
    ``saturated_503_rows_durable``, que ya lo marca FAIL por ilegible."""
    return rechazos is None or (_is_int(rechazos) and rechazos == 0)


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
