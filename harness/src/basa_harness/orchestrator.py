"""Orquestador del gate — UN comando corre un examen (spec 035, T027; SC-006; quickstart
esc. 3 y 7).

    precondiciones/fingerprint → exportar identidades → configurar stub → k6 →
    recolectar (k6 summary + health inicial/final + stub report) → evaluar → escribir
    verdict.json + fingerprint.json + reporte.md en ``runs/<run-id>/``.

Frontera R3: el veredicto se computa SOLO de k6 + producto + stub — NUNCA de la
observabilidad. El orquestador tampoco la consulta.

**Degradación en seco (``--dry-run``)**: corre SIN stack ni k6 y produce la estructura
completa de un run (los tres artefactos) con datos SINTÉTICOS deterministas — para
ensayar el cableado del harness en local sin la caja de examen. Las identidades se derivan
OFFLINE del plan de población (``plan_members`` + ``derive_password`` — sin red), el corpus
y los canarios del generador determinista, y health/stub/k6 se sustituyen por sondas
sintéticas limpias. Un dry-run se marca ``kind='dry-run'`` y NUNCA es oficial.

**Run interrumpido / precondición no cumplida** (edge case de la spec): jamás un directorio
a medias que parezca examen completo. Ante ``KeyboardInterrupt``, un fallo de precondición
(config del stack drifteada) o cualquier excepción del pipeline, se escribe un reporte
PARCIAL marcado ``invalid``/``interrupted`` y se ABORTA antes de generar carga si la
precondición falla (``k6`` no se lanza).

DETERMINISMO: ``run_id`` y ``timestamp`` son inyectables; toda la data sintética deriva de
la semilla. Sin ese pin, se usan reloj/fecha reales (una corrida real).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Union

from .corpus import GENERATOR_VERSION, generate, generate_canaries
from .reporting.evaluator import Verdict, evaluate
from .reporting.fingerprint import Fingerprint, capture
from .reporting.gate_loader import (Gate, load_gate, load_gate_by_number,
                                    surface_arrival_rates, surface_populations)
from .reporting.report import render_report
from .seeder.population import (Population, derive_password, load_population_by_gate,
                                plan_members)
from .seeder.seed import DEFAULT_SEED

# Versiones PINEADAS del instrumento (research R1; van al fingerprint).
K6_VERSION = "v1.8.0"
XK6_SSE_VERSION = "v0.1.12"
STUB_VERSION = "0.1.0"

# Superficies de carga y su función k6 (para el k6_config.json).
SURFACE_EXEC = {"chat": "chat", "extension": "extension", "coding_sse": "coding",
                "admin": "admin"}


class OrchestratorError(RuntimeError):
    """Fallo accionable del orquestador (precondición, entorno). No es un veredicto FAIL:
    impide correr o certificar el examen."""


@dataclass
class RunOutputs:
    """Rutas de los tres artefactos + evidencia de un run."""
    run_dir: Path
    verdict_path: Path
    fingerprint_path: Path
    report_path: Path


class Orchestrator:
    """Corre un gate de punta a punta. Los efectos externos (health, stub, k6,
    reconciliación) son HOOKS inyectables — los tests pasan fakes; en real, se arman
    clientes HTTP/subprocess. En ``dry_run`` los hooks no se invocan: sondas sintéticas."""

    def __init__(self, gate: Union[Gate, int], *, run_id: Optional[str] = None,
                 backend_url: str = "http://localhost:8000",
                 stub_url: str = "http://localhost:9900",
                 runs_dir: Optional[Union[str, Path]] = None,
                 seed: Union[int, str] = DEFAULT_SEED, kind: str = "gate_oficial",
                 dry_run: bool = False, drill_admin_budget_ms: Optional[float] = None,
                 n_canaries: int = 64, n_corpus_docs: int = 200,
                 timestamp: Optional[str] = None, now: Optional[Callable[[], datetime]] = None,
                 health_fn: Optional[Callable[[str], dict]] = None,
                 stub_client: Optional[object] = None,
                 k6_runner: Optional[Callable[[dict], dict]] = None,
                 reconcile_fn: Optional[Callable[[dict], dict]] = None,
                 observed_stack_config: Optional[dict] = None,
                 population: Optional[Population] = None,
                 hardware: Optional[dict] = None, licencia: Optional[dict] = None,
                 producto: Optional[dict] = None, harness_commit: Optional[str] = None):
        self.gate = gate if isinstance(gate, Gate) else load_gate_by_number(gate)
        self.backend_url = backend_url.rstrip("/")
        self.stub_url = stub_url.rstrip("/")
        self.seed = seed
        # kind efectivo: si el YAML declara un kind propio (p. ej. ``drill``), MANDA el
        # YAML — un drill no puede correrse por accidente como gate oficial. ``--kind``
        # explícito sigue sirviendo para runs ad-hoc sobre los gates oficiales.
        gate_kind = getattr(self.gate, "kind", "gate_oficial")
        self.kind = "dry-run" if dry_run else (gate_kind if gate_kind != "gate_oficial"
                                               else kind)
        self.dry_run = dry_run
        self.drill_admin_budget_ms = drill_admin_budget_ms
        self.n_canaries = n_canaries
        self.n_corpus_docs = n_corpus_docs
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.timestamp = timestamp or self._now().isoformat()
        self.run_id = run_id or self._default_run_id()
        base = Path(runs_dir) if runs_dir else (Path(__file__).resolve().parent.parent.parent
                                                / "runs")
        self.run_dir = base / self.run_id
        # hooks
        self._health_fn = health_fn
        self._stub_client = stub_client
        self._k6_runner = k6_runner
        self._reconcile_fn = reconcile_fn
        self.observed_stack_config = observed_stack_config
        # metadata para el fingerprint
        self._population = population
        self._hardware = hardware
        self._licencia = licencia
        self._producto = producto
        self._harness_commit = harness_commit
        # estado interno / trazas para tests
        self.k6_launched = False
        self.stub_configured = False

    # ── ciclo de vida ──────────────────────────────────────────────────────────────────

    def run(self) -> Verdict:
        """Corre el gate. Devuelve el ``Verdict`` (parcial si se interrumpe/aborta)."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._check_preconditions()          # ABORTA antes de generar carga si drift
            pool = self._export_identities()
            corpus = self._export_corpus()
            self._write_k6_config(pool, corpus)
            self._configure_stub(corpus)
            health_initial = self._probe_health("inicial")
            k6_summary = self._run_k6()
            self._finalize_stub()
            stub_report = self._collect_stub_report()
            health_final = self._probe_health("final")
            reconciliation = self._reconcile(k6_summary)
            verdict = evaluate(
                self.gate, run_id=self.run_id, timestamp=self.timestamp,
                k6_summary=k6_summary, health_initial=health_initial,
                health_final=health_final, stub_report=stub_report,
                reconciliation=reconciliation, kind=self.kind,
                notas=(["run en seco: datos sintéticos, NO oficial"] if self.dry_run else None),
                drill_overrides=_drill_overrides(self.drill_admin_budget_ms),
            )
            fingerprint = self._build_fingerprint(corpus, k6_summary)
            self._write_outputs(verdict, fingerprint, evidence=self._evidence_refs())
            return verdict
        except KeyboardInterrupt:
            return self._abort("run interrumpido (KeyboardInterrupt) antes de completar",
                               estado="interrupted")
        except OrchestratorError as exc:
            return self._abort(str(exc), estado="invalid")
        except Exception as exc:  # noqa: BLE001 — cualquier fallo → reporte PARCIAL, jamás
            # un directorio a medias que parezca examen completo (edge case de la spec).
            return self._abort(f"fallo inesperado del orquestador ({type(exc).__name__}): "
                               f"{exc}", estado="invalid")

    # ── precondiciones ─────────────────────────────────────────────────────────────────

    def _check_preconditions(self) -> None:
        """Precondición del fingerprint (contract gate-definition regla 2): el stack cumple
        ``stack_config_required``. Un drift ABORTA antes de generar carga (el run no puede
        marcarse oficial). Si no hay config observada (dry-run sin stack) se omite el chequeo
        vivo, pero el gate ya se validó al cargarse."""
        observed = self.observed_stack_config
        if observed is None:
            return
        drifts = _stack_config_drift(self.gate.stack_config_required, observed)
        if drifts:
            raise OrchestratorError(
                "precondición de config no cumplida (stack_config_required drifteado): "
                + "; ".join(drifts) + ". El run no puede marcarse gate_oficial; se aborta "
                "ANTES de generar carga.")
        # Bloque nlp del health, si aplica (post-#97): sano antes de un run oficial.
        nlp = observed.get("nlp")
        if isinstance(nlp, dict) and nlp.get("status") not in (None, "healthy", "ok", "up"):
            raise OrchestratorError(
                f"precondición nlp: el bloque nlp del health no está sano ({nlp.get('status')!r}); "
                "un gate en 'degrade' no es el mismo examen que uno en 'block'.")

    # ── exportaciones deterministas (offline) ──────────────────────────────────────────

    def _population_obj(self) -> Population:
        if self._population is None:
            self._population = load_population_by_gate(self.gate.gate)
        return self._population

    def _export_identities(self) -> list[dict]:
        """Pool de identidades para el ``SharedArray`` de k6, DERIVADO OFFLINE del plan de
        población (usernames + passwords deterministas — sin tocar el backend). El material
        de llave (``basa_key``) para las superficies extensión/coding NO se puede derivar
        offline: si la corrida es real, se completa desde el emit del seeder; acá se deja el
        campo en null y se documenta."""
        pop = self._population_obj()
        members = plan_members(pop, self.seed)
        admin_pwd = derive_password(self.seed, pop.admin_username)
        pool = [{"username": pop.admin_username, "password": admin_pwd,
                 "role": "tenant_admin", "client_type": None, "tool_type": None,
                 "bootstrap": True, "basa_key": None}]
        for m in members:
            pool.append({"username": m.username, "password": m.password, "role": m.role,
                         "client_type": m.client_type, "tool_type": m.tool_type,
                         "basa_key": None})
        self._write_json("pool.json", pool)
        return pool

    def _export_corpus(self) -> dict:
        """Canarios únicos del run + documentos PII deterministas (para que k6 los siembre
        y el stub detecte fugas). Runtime-only: ``runs/`` es scratch gitignored."""
        canaries = generate_canaries(self.run_id, self.n_canaries)
        densities = {d: 1 for d in (self.gate.pii_densities_per_mille or [0])}
        seed_int = self.seed if isinstance(self.seed, int) else abs(hash(self.seed)) % (2**31)
        docs = generate(seed_int, self.n_corpus_docs, densities, region="eu")
        corpus = {
            "run_id": self.run_id,
            "corpus_version": GENERATOR_VERSION,
            "seed": seed_int,
            "canaries": [{"canary_id": c["canary_id"], "value": c["value"],
                          "entity_type": c["entity_type"]} for c in canaries],
            "docs": [{"text": d["text"],
                      "entities": [e.get("entity_type") for e in d.get("entities", [])]}
                     for d in docs],
            "densities_per_mille": list(self.gate.pii_densities_per_mille or [0]),
        }
        self._write_json("corpus.json", corpus)
        self._write_json("canaries.json", canaries)  # set COMPLETO (para /control/canaries)
        self._canaries_full = canaries
        return corpus

    def _write_k6_config(self, pool: list, corpus: dict) -> dict:
        """Traduce el gate a la config que k6 consume: por cada (superficie, fase) un
        scenario ``constant-arrival-rate`` con ``rate=N_s`` sobre ``timeUnit=cadencia_media``
        (research R1). El math del gate vive en Python (surface_arrival_rates); k6 solo lo
        ejecuta."""
        rates = surface_arrival_rates(self.gate)
        scenarios = []
        for phase in self.gate.phases:
            for surface, ar in rates.items():
                exec_name = SURFACE_EXEC.get(surface)
                if exec_name is None:
                    continue
                rate = max(1, round(ar.sessions * phase.arrival_factor))
                scenarios.append({
                    "surface": surface, "exec": exec_name, "phase": phase.name,
                    "executor": "constant-arrival-rate",
                    "rate": rate, "timeUnit": f"{ar.cadence_mean_s:g}s",
                    "duration": phase.duration,
                    "preAllocatedVUs": max(10, rate * 2), "maxVUs": max(20, rate * 6),
                })
            # login_storm / peak llevan su propio scenario si el gate lo declara.
            if phase.name == "login_storm":
                # `enters` puede ser un centinela (p. ej. "all_population"): toda la
                # población entra en la ventana. Solo un entero explícito lo overridea.
                raw = phase.extra.get("enters", self.gate.total_population)
                enters = raw if (isinstance(raw, int) and not isinstance(raw, bool)) \
                    else self.gate.total_population
                scenarios.append({
                    "surface": "login", "exec": "login", "phase": phase.name,
                    "executor": "constant-arrival-rate",
                    "rate": enters, "timeUnit": phase.duration, "duration": phase.duration,
                    "preAllocatedVUs": 50, "maxVUs": max(100, enters), "startTime": "0s"})
        cfg = {
            "gate": self.gate.gate, "version": self.gate.version,
            "base_url": self.backend_url, "stub_url": self.stub_url,
            "pool_file": "pool.json", "corpus_file": "corpus.json",
            "summary_file": "summary.json",
            "densities_per_mille": list(self.gate.pii_densities_per_mille or [0]),
            "scenarios": scenarios,
        }
        self._write_json("k6_config.json", cfg)
        return cfg

    # ── efectos externos (hooks) ───────────────────────────────────────────────────────

    def _configure_stub(self, corpus: dict) -> None:
        """Programa el stub con las latencias del gate y carga el set de canarios del run."""
        client = self._stub()
        if client is None:
            return
        stub = self.gate.stub or {}
        lat = stub.get("latency_ms") or {}
        stream_rng = stub.get("stream_duration_s") or [1, 1]
        stream_mid = (float(stream_rng[0]) + float(stream_rng[-1])) / 2.0
        cfg = {
            "run_id": self.run_id,
            "seed": self.seed if isinstance(self.seed, int) else 0,
            "masking_config": self.gate.stack_config_required.get("masking", {}),
            "defaults": {"token_rate": float(stub.get("token_rate_tps", 40)),
                         "stream_duration_s": stream_mid,
                         "error_rate": float(stub.get("error_rate", 0.0))},
            "aliases": {
                "chat": {"latency_ms": float(lat.get("chat", 0)),
                         "token_rate": float(stub.get("token_rate_tps", 40)),
                         "stream_duration_s": stream_mid},
                "coding": {"latency_ms": float(lat.get("coding_first_token", 0)),
                           "token_rate": float(stub.get("token_rate_tps", 40)),
                           "stream_duration_s": stream_mid},
            },
        }
        client.reset()
        client.config(cfg)
        client.canaries(self._canaries_full)
        self.stub_configured = True

    def _probe_health(self, cual: str) -> dict:
        """Lee ``GET /api/v1/health`` con credencial compliance. En dry-run, sonda
        sintética limpia (lost_events=0)."""
        if self.dry_run:
            return {"status": "healthy", "service": "stub-dry-run", "version": "1.0.0",
                    "audit": {"mode": "open", "lost_events": 0, "last_failure_at": None}}
        fn = self._health_fn or self._default_health_fn
        return fn(cual)

    def _run_k6(self) -> dict:
        """Lanza k6 (o el runner inyectado) y devuelve el summary. En dry-run / sin binario,
        degrada a un summary sintético limpio (dropped_iterations=0)."""
        if self.dry_run:
            return self._synthetic_summary()
        if self._k6_runner is None:
            self._k6_runner = self._default_k6_runner
        cfg = self._read_json("k6_config.json")
        self.k6_launched = True
        summary = self._k6_runner(cfg)
        # persistir por si el runner devolvió el dict sin escribirlo
        if isinstance(summary, dict):
            self._write_json("summary.json", summary)
        return summary

    def _finalize_stub(self) -> None:
        client = self._stub()
        if client is not None:
            client.finalize()

    def _collect_stub_report(self) -> dict:
        if self.dry_run:
            return self._synthetic_stub_report()
        client = self._stub()
        if client is None:
            return self._synthetic_stub_report()
        return client.report()

    def _reconcile(self, k6_summary: dict) -> dict:
        """Reconciliación de auditoría (filas persistidas vs eventos del guion) + bloqueos
        durables. En dry-run: paridad sintética perfecta (eventos==filas, 0 bloqueos).

        En un **drill de saturación**, ``reconcile_fn`` debe devolver ADEMÁS
        ``filas_rejected_saturated``: el conteo de filas de ``audit_logs`` con el estado
        LITERAL ``'rejected_saturated'`` (el rechazo de admisión C1 — deliberadamente NO es
        un bloqueo de política, así que no se mezcla con ``bloqueos_provocados``)."""
        if self.dry_run:
            eventos = int(k6_summary.get("auditable_events", 0))
            recon = {"eventos_guion": eventos, "filas_persistidas": eventos,
                     "bloqueos_provocados": 0, "con_fila": 0}
            if getattr(self.gate, "kind", "gate_oficial") == "drill":
                # solo en drills: el dry-run del gate oficial no cambia ni un byte.
                recon["filas_rejected_saturated"] = 0
            return recon
        if self._reconcile_fn is None:
            raise OrchestratorError(
                "reconciliación no configurada: pasá --reconcile_fn o corré con --dry-run. "
                "El SLO de reconciliación necesita el conteo de audit_logs del producto.")
        return self._reconcile_fn(k6_summary)

    # ── fingerprint ────────────────────────────────────────────────────────────────────

    def _build_fingerprint(self, corpus: dict, k6_summary: dict) -> Fingerprint:
        pop = self._population_obj()
        rates = {s: ar.k6 for s, ar in surface_arrival_rates(self.gate).items()}
        scr = self.gate.stack_config_required
        return capture(
            producto=self._producto or {"commit": "unknown", "digests": {},
                                        "dry_run": self.dry_run},
            masking_por_scope=scr.get("masking", {}),
            config_nlp={"nlp_analyzer": scr.get("nlp_analyzer"),
                        "nlp_analyzer_url": scr.get("nlp_analyzer_url"),
                        "nlp_fail_mode": scr.get("nlp_fail_mode")},
            workers_procesos=(self._producto or {}).get("workers_procesos", {}),
            limites_recursos=(self._producto or {}).get("limites_recursos", {}),
            gate={"n": self.gate.gate, "version": self.gate.version},
            corpus={"version": corpus.get("corpus_version"), "seed": corpus.get("seed"),
                    "n_canaries": len(corpus.get("canaries", [])),
                    "densities_per_mille": corpus.get("densities_per_mille")},
            mix_y_cadencia_usadas={"mix": self.gate.mix, "cadence_s": self.gate.cadence_s,
                                   "surface_populations": surface_populations(self.gate),
                                   "arrival_rates": rates},
            hardware=self._hardware or {"provider": "n/a (sin infra)" if self.dry_run
                                        else "unknown"},
            licencia=self._licencia or {"lic_id": None,
                                        "max_seats": pop.expected_max_seats},
            seed_estado=("dry-run" if self.dry_run else "unknown"),
            versiones_instrumento={"k6": K6_VERSION, "xk6_sse": XK6_SSE_VERSION,
                                   "stub": STUB_VERSION,
                                   "harness_commit": self._harness_commit or "unknown"},
            timestamp=self.timestamp,
        )

    # ── escritura de artefactos ────────────────────────────────────────────────────────

    def _write_outputs(self, verdict: Verdict, fingerprint: Optional[Fingerprint],
                       *, evidence: Optional[dict] = None) -> RunOutputs:
        vpath = self._write_text("verdict.json", verdict.to_json())
        if fingerprint is not None:
            fpath = self._write_text("fingerprint.json", fingerprint.to_json())
        else:
            fpath = self.run_dir / "fingerprint.json"
        rpath = self._write_text("reporte.md", render_report(verdict, fingerprint,
                                                              evidence=evidence))
        return RunOutputs(self.run_dir, vpath, fpath, rpath)

    def _abort(self, reason: str, *, estado: str) -> Verdict:
        """Escribe un reporte PARCIAL marcado invalid/interrupted — nunca un dir a medias."""
        verdict = Verdict(run_id=self.run_id,
                          gate={"n": self.gate.gate, "version": self.gate.version},
                          estado=estado, global_veredicto="INVALID", slos=[],
                          invalid_reason=reason, timestamp=self.timestamp, kind=self.kind,
                          notas=["reporte PARCIAL: el run no llegó a completarse; NO comparable"])
        fingerprint = None
        try:
            fingerprint = self._build_fingerprint({"corpus_version": GENERATOR_VERSION,
                                                   "seed": None, "canaries": [],
                                                   "densities_per_mille": []}, {})
        except Exception:  # noqa: BLE001 — un fingerprint parcial no debe tapar el abort
            fingerprint = None
        self._write_outputs(verdict, fingerprint, evidence=self._evidence_refs())
        return verdict

    def _evidence_refs(self) -> dict:
        return {
            "k6_summary": str(self.run_dir / "summary.json"),
            "pool": str(self.run_dir / "pool.json"),
            "corpus": str(self.run_dir / "corpus.json"),
            "k6_config": str(self.run_dir / "k6_config.json"),
            "plataforma_r3": f"/srv/itv-runs/{self.run_id}/",
        }

    # ── sondas sintéticas (dry-run) ────────────────────────────────────────────────────

    def _synthetic_summary(self) -> dict:
        surfaces = {}
        for surface in SURFACE_EXEC:
            key = "coding" if surface == "coding_sse" else surface
            entry = {"requests": 0, "dropped_iterations": 0, "errors": 0,
                     "latency_ms": {"p50": 0, "p95": 0, "p99": 0, "max": 0, "count": 0}}
            if surface == "coding_sse":
                entry["ttft_ms"] = {"p50": 0, "p95": 0, "p99": 0, "max": 0, "count": 0}
                entry["stream_cuts"] = 0
            surfaces[key] = entry
        summary = {"schema": "basa-harness/k6-summary@1", "gate": self.gate.gate,
                   "dry_run": True, "surfaces": surfaces,
                   "dropped_iterations_total": 0, "auditable_events": 0,
                   "provoked_blocks": 0, "observed_blocks": 0}
        self._write_json("summary.json", summary)
        return summary

    def _synthetic_stub_report(self) -> dict:
        return {"run_id": self.run_id, "leak_count": 0, "canarios_detectados": [],
                "canary_set_size": self.n_canaries,
                "trafico_no_auditable": {"count": 0, "requests": []},
                "pacing_drift_ms": {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "n": 0},
                "cpu_pct": 0.0, "valido": True}

    # ── clientes reales (solo corrida real) ────────────────────────────────────────────

    def _stub(self):
        """Devuelve el cliente de control del stub (inyectado o HTTP), o None en dry-run."""
        if self.dry_run:
            return None
        if self._stub_client is None:
            self._stub_client = _HttpStubClient(self.stub_url)
        return self._stub_client

    def _default_health_fn(self, _cual: str) -> dict:  # pragma: no cover — camino real
        import httpx
        pop = self._population_obj()
        # el lector de SLO usa el primer compliance_officer del seed
        cmp_user = f"{pop.seed_prefix}-g{pop.gate}-cmp-0000"
        pwd = derive_password(self.seed, cmp_user)
        with httpx.Client(timeout=30.0) as c:
            tok = c.post(f"{self.backend_url}/api/v1/users/login",
                         json={"username": cmp_user, "password": pwd}).json()["access_token"]
            return c.get(f"{self.backend_url}/api/v1/health",
                         headers={"Authorization": f"Bearer {tok}"}).json()

    def _default_k6_runner(self, cfg: dict) -> dict:  # pragma: no cover — camino real
        import subprocess
        bin_path = str(Path(__file__).resolve().parent.parent.parent / "bin" / "k6")
        gate_js = str(Path(__file__).resolve().parent.parent.parent / "scenarios" / "gate.js")
        summary_path = self.run_dir / "summary.json"
        env_json = json.dumps(cfg)
        subprocess.run(
            [bin_path, "run", "--env", f"GATE_CONFIG={env_json}",
             "--env", f"POOL_FILE={self.run_dir / 'pool.json'}",
             "--env", f"CORPUS_FILE={self.run_dir / 'corpus.json'}",
             "--env", f"SUMMARY_FILE={summary_path}", gate_js],
            check=True, cwd=str(self.run_dir))
        return self._read_json("summary.json")

    # ── util ───────────────────────────────────────────────────────────────────────────

    def _default_run_id(self) -> str:
        fecha = self._now().strftime("%Y%m%d")
        return f"{fecha}-g{self.gate.gate}-01"

    def _write_json(self, name: str, data: object) -> Path:
        return self._write_text(name, json.dumps(data, ensure_ascii=False, indent=2))

    def _write_text(self, name: str, text: str) -> Path:
        path = self.run_dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def _read_json(self, name: str) -> dict:
        return json.loads((self.run_dir / name).read_text(encoding="utf-8"))


# ── overrides de criterios del drill ──────────────────────────────────────────────────

def _drill_overrides(admin_budget_ms: Optional[float]) -> Optional[dict]:
    """Umbrales del drill que llegan por CLI en vez de por YAML.

    El presupuesto de admin NO se hornea en la definición: se DERIVA del baseline medido
    del gate oficial del mismo día (mismo hardware, misma imagen) y se pasa por
    ``--drill-admin-budget-ms``. Sin el flag no hay override y el criterio queda sin
    umbral (nota informativa, sin fila)."""
    if admin_budget_ms is None:
        return None
    return {"admin_p95_budget_ms": float(admin_budget_ms)}


# ── drift de stack_config_required ────────────────────────────────────────────────────

def _stack_config_drift(required: dict, observed: dict) -> list[str]:
    """Diff material required→observed. Solo señala claves que el stack observado
    CONTRADICE (una clave ausente en observed no se puede verificar → no es drift duro)."""
    drifts: list[str] = []
    for key, req in required.items():
        if key not in observed:
            continue
        obs = observed[key]
        if key == "masking":
            req_def = req.get("default") if isinstance(req, dict) else req
            obs_def = obs.get("default") if isinstance(obs, dict) else obs
            if _norm(req_def) != _norm(obs_def):
                drifts.append(f"masking.default requerido={req_def!r} observado={obs_def!r}")
        elif isinstance(req, (str, int, float, bool)):
            if _norm(req) != _norm(obs):
                drifts.append(f"{key} requerido={req!r} observado={obs!r}")
    return drifts


def _norm(v: object) -> object:
    """Normaliza el ON de YAML: pyyaml parsea ``on`` como True; ``'on'`` y ``True`` iguales."""
    if v in (True, "on", "ON", "On"):
        return True
    if v in (False, "off", "OFF", "Off"):
        return False
    return v


# ── cliente HTTP del stub (control por run) ────────────────────────────────────────────

class _HttpStubClient:  # pragma: no cover — camino real (los tests inyectan un fake)
    def __init__(self, base_url: str):
        import httpx
        self._base = base_url.rstrip("/")
        self._http = httpx.Client(timeout=30.0)

    def reset(self) -> None:
        self._http.post(f"{self._base}/control/reset")

    def config(self, cfg: dict) -> None:
        self._http.post(f"{self._base}/control/config", json=cfg)

    def canaries(self, canaries: list) -> None:
        self._http.post(f"{self._base}/control/canaries", json={"canaries": canaries})

    def finalize(self) -> None:
        self._http.post(f"{self._base}/control/finalize")

    def report(self) -> dict:
        return self._http.get(f"{self._base}/control/report").json()


# ── CLI ────────────────────────────────────────────────────────────────────────────────

def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m basa_harness.orchestrator",
        description="Corre un gate del harness ITV con UN comando (SC-006).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--gate", type=int, choices=(125, 250, 500),
                     help="carga harness/gates/gate-<N>.yaml")
    src.add_argument("--gate-file", type=Path, help="ruta a un YAML de gate")
    p.add_argument("--backend-url", default="http://localhost:8000")
    p.add_argument("--stub-url", default="http://localhost:9900")
    p.add_argument("--runs-dir", type=Path, default=None,
                   help="directorio de salida (default: harness/runs/)")
    p.add_argument("--run-id", default=None, help="id del run (default: <fecha>-g<N>-01)")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--kind", default="gate_oficial",
                   choices=("gate_oficial", "diagnostico", "smoke", "fault_injection"))
    p.add_argument("--dry-run", action="store_true",
                   help="corre SIN stack ni k6: estructura completa con datos sintéticos")
    p.add_argument("--drill-admin-budget-ms", type=float, default=None,
                   help="drill de saturación: presupuesto p95 del panel admin (ms), "
                        "derivado del baseline del gate oficial del MISMO día")
    args = p.parse_args(argv)

    gate = load_gate(args.gate_file) if args.gate_file else load_gate_by_number(args.gate)
    orch = Orchestrator(gate, run_id=args.run_id, backend_url=args.backend_url,
                        stub_url=args.stub_url, runs_dir=args.runs_dir, seed=args.seed,
                        kind=args.kind, dry_run=args.dry_run,
                        drill_admin_budget_ms=args.drill_admin_budget_ms)
    verdict = orch.run()
    print(f"run {verdict.run_id}: estado={verdict.estado} global={verdict.global_veredicto}")
    print(f"  artefactos → {orch.run_dir}")
    if verdict.invalid_reason:
        print(f"  motivo: {verdict.invalid_reason}", file=sys.stderr)
    return 0 if verdict.global_veredicto == "PASS" else (2 if verdict.estado != "completed" else 1)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
