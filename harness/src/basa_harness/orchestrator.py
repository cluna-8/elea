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

**Corrida real** (T031): además del stack, pide dos insumos que no se pueden derivar
offline. (1) ``--pool-file``: el pool 0600 que emitió el seeder, del que salen las
``basa_key`` de las Connections —sin ellas las superficies extensión/coding no autentican
(``scenarios/common.js`` ``authHeaders``)— y la credencial compliance del lector de
auditoría. (2) ``--reconcile http``: el conteo de ``audit_logs`` del producto, acotado a
la VENTANA del run (``t0`` antes de lanzar k6, ``t1`` al cerrarlo). El reloj de la ventana
vive acá, en el orquestador; el ``timestamp`` del veredicto sigue INYECTADO — el evaluador
no mira ningún reloj.

DETERMINISMO: ``run_id`` y ``timestamp`` son inyectables; toda la data sintética deriva de
la semilla. Sin ese pin, se usan reloj/fecha reales (una corrida real).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Union

from .corpus import GENERATOR_VERSION, generate, generate_canaries
from .reconcile import ReconcileError, build_http_reconcile, credential_from_pool
from .reporting.evaluator import Verdict, evaluate
from .reporting.fingerprint import Fingerprint, capture
from .reporting.gate_loader import (Gate, load_gate, load_gate_by_number,
                                    surface_arrival_rates, surface_populations)
from .reporting.report import render_report
from .seeder.population import (Population, derive_password, load_population_by_gate,
                                plan_members)
from .seeder.seed import DEFAULT_SEED, KEY_SURFACE_CLIENT_TYPES

# Versiones PINEADAS del instrumento (research R1; van al fingerprint).
K6_VERSION = "v1.8.0"
XK6_SSE_VERSION = "v0.1.12"
STUB_VERSION = "0.1.0"

# Tolerancia de skew de reloj orquestador↔SUT (M1): el header Date tiene resolución de
# 1 s y la sonda paga medio RTT; por encima de esto la ventana de reconciliación puede
# contar tráfico ajeno al run (la dirección peligrosa: tapar filas perdidas).
CLOCK_SKEW_MAX_S = 2.0

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
                 model_chat: str = "chat", model_coding: str = "coding",
                 n_canaries: int = 64, n_corpus_docs: int = 200,
                 timestamp: Optional[str] = None, now: Optional[Callable[[], datetime]] = None,
                 health_fn: Optional[Callable[[str], dict]] = None,
                 stub_client: Optional[object] = None,
                 k6_runner: Optional[Callable[[dict], dict]] = None,
                 reconcile_fn: Optional[Callable[[dict], dict]] = None,
                 clock_probe_fn: Optional[Callable[[], Optional[datetime]]] = None,
                 smoke_fn: Optional[Callable[[list], list]] = None,
                 observed_stack_config: Optional[dict] = None,
                 pool_file: Optional[Union[str, Path]] = None,
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
        self.model_chat = model_chat
        self.model_coding = model_coding
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
        self._clock_probe_fn = clock_probe_fn
        self._smoke_fn = smoke_fn
        self.clock_skew_s: Optional[float] = None
        self.observed_stack_config = observed_stack_config
        self.pool_file = Path(pool_file) if pool_file else None
        self._pool_cache: Optional[list] = None
        # Ventana del run (UTC): t0 ANTES de lanzar k6, t1 al cerrarlo. Es el rango sobre
        # el que se cuentan las filas de auditoría del producto.
        self.window_t0: Optional[datetime] = None
        self.window_t1: Optional[datetime] = None
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
        self._guard_evidencia_existente()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._check_preconditions()          # ABORTA antes de generar carga si drift
            pool = self._export_identities()
            corpus = self._export_corpus()
            self._write_k6_config(pool, corpus)
            self._configure_stub(corpus)
            health_initial = self._probe_health("inicial")
            self._assert_stack_ready(health_initial, pool)
            self._assert_clock_skew()
            # Ventana del run: se abre ANTES de la primera request de carga y se cierra
            # con la última. Sin margen a propósito — una fila de auditoría escrita fuera
            # de la ventana se cuenta de menos (FAIL), nunca de más (que sería el camino
            # por el que un run con filas perdidas podría cuadrar)… siempre que los
            # relojes coincidan, que es lo que la guarda de arriba acaba de comprobar.
            self.window_t0 = self._now()
            k6_summary = self._run_k6()
            self.window_t1 = self._now()
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

    def _guard_evidencia_existente(self) -> None:
        """La evidencia de un run NO se sobrescribe. Se levanta ANTES del ``try`` a
        propósito: dentro, el manejo de errores escribiría un verdict PARCIAL encima del
        run que se quiere proteger. Por eso este error SALE del orquestador."""
        vpath = self.run_dir / "verdict.json"
        if vpath.exists():
            raise OrchestratorError(
                f"el run_dir ya contiene un verdict.json ({vpath}): elegí otro --run-id — "
                "no se sobrescribe evidencia")

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
        # El alias de chat se verifica contra el catálogo REAL del motor, pero no acá: esta
        # ruta depende de una config observada que sólo existe si el llamador la inyecta.
        # La comprobación viva vive en `_assert_stack_ready` (GET /chat/models, la misma
        # fuente que consume la UI de Modelos) — ver la nota de H2 en ese método.
        catalogo = observed.get("model_catalog") or observed.get("modelos")
        if isinstance(catalogo, (list, tuple, set)) and catalogo:
            if self.model_chat not in catalogo:
                raise OrchestratorError(
                    f"precondición de catálogo: el alias de chat {self.model_chat!r} no está "
                    f"en el catálogo del motor ({sorted(catalogo)!r}). El backend lo "
                    "rechazaría con 400 sin auditar y el 60% del gate no mediría nada. "
                    "Pasá --model-chat con un alias del `model_list` del perfil desplegado.")

    # ── exportaciones deterministas (offline) ──────────────────────────────────────────

    def _population_obj(self) -> Population:
        if self._population is None:
            self._population = load_population_by_gate(self.gate.gate)
        return self._population

    def _export_identities(self) -> list[dict]:
        """Pool de identidades para el ``SharedArray`` de k6, DERIVADO OFFLINE del plan de
        población (usernames + passwords deterministas — sin tocar el backend).

        El material de llave (``basa_key``) NO se puede derivar offline: la key en claro la
        devuelve el backend UNA vez, al crear la Connection. En una corrida real llega por
        ``--pool-file`` (el pool 0600 del seeder) y se INJERTA por username; sin ese
        archivo el campo queda en null, que es lo que corresponde a un dry-run."""
        pop = self._population_obj()
        members = plan_members(pop, self.seed)
        admin_pwd = derive_password(self.seed, pop.admin_username)
        material = self._key_material()
        pool = [{"username": pop.admin_username, "password": admin_pwd,
                 "role": "tenant_admin", "client_type": None, "tool_type": None,
                 "bootstrap": True, "basa_key": None}]
        for m in members:
            pool.append({"username": m.username, "password": m.password, "role": m.role,
                         "client_type": m.client_type, "tool_type": m.tool_type,
                         "basa_key": material.get(m.username)})
        if self.pool_file is not None:
            self._assert_key_material(members, material)
        # 0600: el pool lleva passwords EN CLARO y —desde la corrida real— las keys de las
        # Connections. Es material de RUN, no evidencia publicable (mismo criterio que
        # ``seeder.seed._write_credentials``).
        self._write_secret_json("pool.json", pool)
        return pool

    def _read_pool_file(self) -> list:
        """Lee el pool emitido por el seeder (``--emit-credentials``). Ilegible = abortar:
        de ahí salen el material de llave y la credencial del lector de auditoría."""
        if self._pool_cache is not None:
            return self._pool_cache
        assert self.pool_file is not None
        try:
            data = json.loads(self.pool_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise OrchestratorError(
                f"pool de credenciales ilegible ({self.pool_file}): {exc}. Es el archivo "
                "que emite `seeder.seed --emit-credentials`.") from exc
        if not isinstance(data, list):
            raise OrchestratorError(
                f"el pool {self.pool_file} no es una lista de credenciales.")
        self._pool_cache = data
        return data

    def _key_material(self) -> dict:
        """``username → basa_key`` del pool del seeder (vacío si no hay ``--pool-file``)."""
        if self.pool_file is None:
            return {}
        out = {}
        for entry in self._read_pool_file():
            if isinstance(entry, dict) and isinstance(entry.get("basa_key"), str) \
                    and entry["basa_key"]:
                out[entry.get("username")] = entry["basa_key"]
        return out

    def _assert_key_material(self, members: list, material: dict) -> None:
        """Con pool en mano, toda identidad de extensión/coding tiene que traer su key.

        ``authHeaders`` (common.js) devuelve null sin ella y la iteración se contabiliza
        como ``harness_errors``: el run mediría 2 de 4 superficies y su veredicto NO sería
        el del gate. Se aborta ANTES de generar carga."""
        faltan = [m.username for m in members
                  if m.client_type in KEY_SURFACE_CLIENT_TYPES
                  and not material.get(m.username)]
        if faltan:
            raise OrchestratorError(
                f"{len(faltan)} identidad(es) de extensión/coding sin basa_key en "
                f"{self.pool_file} (p. ej. {', '.join(faltan[:5])}): k6 no puede autenticar "
                "esas superficies y el examen mediría 2 de 4. Re-seedeá contra un stack "
                "fresco (`down -v`) y volvé a emitir el pool.")

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
        ejecuta.

        **Las fases son SECUENCIALES** (``startTime`` acumulado por orden de declaración):
        sin él k6 arranca TODOS los scenarios en t=0 y los corre en paralelo — la ráfaga
        del drill caería sobre una cola FRÍA en vez de sobre la que llenó el sostenido, y
        «tormenta → pico → recuperación» de los gates 250/500 dejaría de ser una secuencia.
        Todas las superficies de una misma fase comparten ``startTime``; la fase i arranca
        en la suma de las duraciones de las fases 0..i-1.
        """
        rates = surface_arrival_rates(self.gate)
        # Ver la nota del `gracefulStop` más abajo: el margen sale del stream MÁS LARGO que
        # el stub puede servir en este gate, más holgura para el cierre.
        stub_cfg = self.gate.stub or {}
        stream_rng = stub_cfg.get("stream_duration_s") or [1, 1]
        graceful_stop_s = float(stream_rng[-1]) + 15.0
        scenarios = []
        offset_s = 0.0
        for phase in self.gate.phases:
            start_time = f"{offset_s:g}s"
            for surface, ar in rates.items():
                exec_name = SURFACE_EXEC.get(surface)
                if exec_name is None:
                    continue
                rate = max(1, round(ar.sessions * phase.arrival_factor))
                scenarios.append({
                    "surface": surface, "exec": exec_name, "phase": phase.name,
                    "executor": "constant-arrival-rate",
                    "rate": rate, "timeUnit": f"{ar.cadence_mean_s:g}s",
                    "duration": phase.duration, "startTime": start_time,
                    "preAllocatedVUs": max(10, rate * 2), "maxVUs": max(20, rate * 6),
                    # El `gracefulStop` por defecto de k6 son 30 s: un stream del stub que
                    # dura más queda CORTADO al terminar la fase, el guion nunca ejecuta el
                    # cierre de su iteración (no cuenta el evento) y el producto ya escribió
                    # su fila → la reconciliación reporta «sobran filas» sin que se haya
                    # perdido nada. Medido en 20260812-g125-drill-01: +15 filas con streams
                    # de 60-120 s del modo sede-lenta. Se le da margen para que las
                    # iteraciones en vuelo terminen y los dos lados cuenten lo mismo.
                    "gracefulStop": f"{graceful_stop_s:g}s",
                })
            # login_storm / peak llevan su propio scenario si el gate lo declara.
            if phase.name == "login_storm":
                # `enters` puede ser un centinela (p. ej. "all_population"): toda la
                # población entra en la ventana. Solo un entero explícito lo overridea.
                raw = phase.extra.get("enters", self.gate.total_population)
                enters = raw if (isinstance(raw, int) and not isinstance(raw, bool)) \
                    else self.gate.total_population
                # La tormenta arranca en t=0 por DISEÑO (es la primera fase del 250: toda
                # la población entrando junta), no por omisión del escalonado.
                scenarios.append({
                    "surface": "login", "exec": "login", "phase": phase.name,
                    "executor": "constant-arrival-rate",
                    "rate": enters, "timeUnit": phase.duration, "duration": phase.duration,
                    "preAllocatedVUs": 50, "maxVUs": max(100, enters), "startTime": "0s"})
            offset_s += phase.duration_s
        cfg = {
            "gate": self.gate.gate, "version": self.gate.version,
            "base_url": self.backend_url, "stub_url": self.stub_url,
            "pool_file": "pool.json", "corpus_file": "corpus.json",
            "summary_file": "summary.json",
            "densities_per_mille": list(self.gate.pii_densities_per_mille or [0]),
            "scenarios": scenarios,
            # Alias de modelo del DESPLIEGUE (no del gate): el backend valida `model`
            # contra el `model_list` del motor y un alias desconocido devuelve 400 sin
            # auditar. Viaja acá para que el guion no lo adivine.
            "model_chat": self.model_chat,
            "model_coding": self.model_coding,
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
        # El stub programa la latencia POR ALIAS, y el alias que ve es el del DESPLIEGUE
        # (el `model` que le reenvía el motor), no la clave genérica del gate. En el examen
        # del 12-ago el gate declaraba `chat: 800` pero el motor mandaba `local`, así que el
        # stub aplicó 0 ms a las 1107 peticiones de chat y el overhead de esa superficie
        # salió en -649 ms: restaba una latencia que nunca se aplicó.
        # La latencia de chat va en `defaults`, que es lo que el stub usa para cualquier
        # alias no listado (`self.aliases.get(alias, self.defaults)`): así el nombre que
        # elija el despliegue deja de importar. `coding` sigue explícito porque su latencia
        # es distinta (primer token) y su alias SÍ es estable — viaja por /gw, donde la
        # Connection resuelve el destino.
        cfg = {
            "run_id": self.run_id,
            "seed": self.seed if isinstance(self.seed, int) else 0,
            "masking_config": self.gate.stack_config_required.get("masking", {}),
            "defaults": {"token_rate": float(stub.get("token_rate_tps", 40)),
                         "stream_duration_s": stream_mid,
                         "latency_ms": float(lat.get("chat", 0)),
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

    def _assert_stack_ready(self, health: dict, pool: list) -> None:
        """Prueba de HUMO antes de abrir la ventana: una petición REAL por superficie.

        Es la respuesta de fondo al 12-ago, donde el examen corrió 30 minutos completos
        con el 60% de la carga rebotando en 422 y nadie se enteró hasta que un humano miró
        la pantalla de auditoría del producto. Las precondiciones declarativas no alcanzan:
        el health no publica ni el catálogo de modelos ni la config de enmascarado, así que
        la única forma honesta de saber si una superficie ejercita el producto es
        **ejercitarla una vez**. Cuatro peticiones, un segundo, antes de gastar media hora.

        Cubre de una sola vez toda la familia: cuerpo desalineado con el wire, alias de
        modelo inexistente, material de llave inválido, ruta cambiada. Y deja el terreno
        firme para clasificar lo que venga después: con el wire probado en t0, un 400 en
        régimen sobre ``/gw`` es un rechazo del gateway (con su fila durable), no un
        pedido mal armado por nosotros.

        Además vuelve VIVA la precondición del modo NLP: el ``fail_mode_efectivo`` del
        health se compara contra el que el gate exige. Hasta hoy esa comprobación existía
        pero nunca corría en una corrida real (``observed_stack_config`` no se pasaba
        nunca por CLI) — o sea que ningún run oficial verificó jamás sus precondiciones.
        """
        if self.dry_run:
            return
        # (1) modo NLP efectivo: el gate 125/250/500 exige `block`; un stack en `degrade`
        # sirve con regex de dev y NO es el mismo examen. FAIL-CLOSED: si el gate exige un
        # modo y la fuente observable no lo publica, el run NO arranca — «no pude
        # comparar» jamás puede leerse como «coincide» (semántica sellada con el core).
        exigido = (self.gate.stack_config_required or {}).get("nlp_fail_mode")
        if exigido:
            efectivo = (health.get("nlp") or {}).get("fail_mode_efectivo")
            if not efectivo:
                raise OrchestratorError(
                    f"precondición nlp_fail_mode: el gate exige {exigido!r} pero el health "
                    "no publica `nlp.fail_mode_efectivo`, así que no hay con qué "
                    "compararlo. Un examen que no puede verificar sus propias "
                    "precondiciones no se corre.")
            if exigido != efectivo:
                raise OrchestratorError(
                    f"precondición nlp_fail_mode: el gate exige {exigido!r} y el stack corre "
                    f"{efectivo!r}. Un run en 'degrade' enmascara con el regex de dev: no es "
                    "el mismo examen y no puede marcarse oficial.")
        # (2) humo por superficie. La sonda es un HOOK que ``main()`` cablea SIEMPRE en un
        # run real (mismo patrón que la del reloj): el orquestador no la inventa, así que
        # un llamador programático con hooks falsos no sale a la red sin pedirlo.
        if self._smoke_fn is None:
            return
        fallos = self._smoke_fn(pool)
        if fallos:
            detalle = "; ".join(f"{s}: {d}" for s, d in fallos)
            raise OrchestratorError(
                f"prueba de humo fallida ANTES de generar carga — {detalle}. Una superficie "
                "que no se sirve en seco no va a medir nada en 30 minutos de examen: se "
                "aborta acá en vez de producir un veredicto sobre una fracción de la carga.")

    def _assert_clock_skew(self) -> None:
        """M1: la ventana la fija el reloj del ORQUESTADOR, pero los ``timestamp`` de
        ``audit_logs`` los pone el ``utcnow()`` del BACKEND. Con el SUT adelantado,
        tráfico escrito antes de t0 cae dentro de la ventana y puede TAPAR filas perdidas
        reales (la promesa «se cuenta de menos, nunca de más» deja de valer). Se compara
        el header ``Date`` del backend con el reloj propio; tolerancia ±2 s = resolución
        de 1 s del header + margen de RTT. La sonda es un hook (``clock_probe_fn``) que
        ``main()`` cablea SIEMPRE en un run real; en seco no hay backend que sondear."""
        if self.dry_run or self._clock_probe_fn is None:
            return
        remoto = self._clock_probe_fn()
        if remoto is None:
            raise OrchestratorError(
                "no se pudo leer el reloj del backend (header Date): sin esa comprobación "
                "la ventana de la reconciliación no es confiable y el examen no arranca.")
        if remoto.tzinfo is None:
            remoto = remoto.replace(tzinfo=timezone.utc)
        skew = (remoto - self._now()).total_seconds()
        self.clock_skew_s = skew
        self._write_json("clock_skew.json", {
            "skew_s": round(skew, 3), "tolerancia_s": CLOCK_SKEW_MAX_S,
            "fuente": "header Date del backend vs reloj del orquestador (t0)"})
        if abs(skew) > CLOCK_SKEW_MAX_S:
            raise OrchestratorError(
                f"skew de reloj orquestador↔SUT de {skew:+.1f} s (tolerancia "
                f"±{CLOCK_SKEW_MAX_S} s): la ventana de reconciliación contaría tráfico "
                "fuera del run (o perdería filas del run). Sincronizá NTP en las dos "
                "cajas y reintentá.")

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

        En CUALQUIER run que vea rechazos —no solo en un drill— ``reconcile_fn`` debe
        devolver ADEMÁS ``filas_rejected_saturated``: el conteo de filas de ``audit_logs``
        con el estado LITERAL ``'rejected_saturated'`` (el rechazo de admisión C1 —
        deliberadamente NO es un bloqueo de política, así que no se mezcla con
        ``bloqueos_provocados``), o ``0`` si no hubo ninguna. Sin ese campo, el evaluador
        no puede afirmar durabilidad y la fila sale FAIL. La fuente de verdad del contrato
        es ``contracts/run-report.md``, no este docstring.

        La VENTANA del run se le pasa al hook si lo admite (``set_window``): el reloj es
        del orquestador, no del evaluador ni del contador. OJO (B3): la guarda «sin
        ventana no se cuenta» solo aplica a hooks que exponen ``set_window`` — el real
        (``HttpReconcile``) siempre lo tiene; un fake simple de los tests corre sin
        ventana y sin error, a sabiendas."""
        if self.dry_run:
            eventos = int(k6_summary.get("auditable_events", 0))
            recon = {"eventos_guion": eventos, "filas_persistidas": eventos,
                     "bloqueos_provocados": 0, "con_fila": 0}
            if getattr(self.gate, "kind", "gate_oficial") == "drill":
                # solo en drills: el dry-run del gate oficial no cambia ni un byte.
                recon["filas_rejected_saturated"] = 0
            self._persist_reconciliation(recon)
            return recon
        if self._reconcile_fn is None:
            raise OrchestratorError(
                "reconciliación no configurada: pasá --reconcile http (con --pool-file) o "
                "corré con --dry-run. El SLO de reconciliación necesita el conteo de "
                "audit_logs del producto.")
        set_window = getattr(self._reconcile_fn, "set_window", None)
        if callable(set_window):
            if self.window_t0 is None or self.window_t1 is None:
                raise OrchestratorError(
                    "la ventana del run no se capturó (t0/t1): sin ella el conteo de "
                    "audit_logs mezclaría el tráfico del seed con el del examen.")
            set_window(self.window_t0, self.window_t1)
        recon = self._reconcile_fn(k6_summary)
        self._persist_reconciliation(recon)
        return recon

    def _persist_reconciliation(self, recon: dict) -> None:
        """Guarda el conteo como EVIDENCIA del run (el verdict sólo publica el delta).

        Con esto, la cifra que decidió los SLO (b) y (d) queda auditable después: qué
        ventana se consultó, cuántas filas de cada clase y de qué fuente."""
        if not isinstance(recon, dict):
            return
        data = dict(recon)
        data.setdefault("ventana", {
            "desde": self.window_t0.isoformat() if self.window_t0 else None,
            "hasta": self.window_t1.isoformat() if self.window_t1 else None,
        })
        # La evidencia puede persistirse desde un _reconcile suelto (tests lo hacen) sin
        # que run() haya creado el directorio todavía; mkdir exist_ok no pisa nada — la
        # guarda anti-sobrescritura es sobre verdict.json, al arrancar run().
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._write_json("reconciliation.json", data)

    # ── fingerprint ────────────────────────────────────────────────────────────────────

    def _build_fingerprint(self, corpus: dict, k6_summary: dict) -> Fingerprint:
        """Huella del run. Incluye QUÉ examen fue, no solo con qué config corrió: el
        ``kind`` en el bloque ``gate`` y el bloque ``examen`` (programa del stub + fases).
        Sin ellos, el drill de saturación y el gate 125 oficial —mismo número, misma
        versión, misma mezcla y cadencia— producían fingerprints que solo diferían en el
        timestamp (no material) y el comparador los daba por LEGÍTIMAMENTE comparables."""
        pop = self._population_obj()
        rates = {s: ar.k6 for s, ar in surface_arrival_rates(self.gate).items()}
        scr = self.gate.stack_config_required
        stub = self.gate.stub or {}
        return capture(
            producto=self._producto or {"commit": "unknown", "digests": {},
                                        "dry_run": self.dry_run},
            masking_por_scope=scr.get("masking", {}),
            config_nlp={"nlp_analyzer": scr.get("nlp_analyzer"),
                        "nlp_analyzer_url": scr.get("nlp_analyzer_url"),
                        "nlp_fail_mode": scr.get("nlp_fail_mode")},
            workers_procesos=(self._producto or {}).get("workers_procesos", {}),
            limites_recursos=(self._producto or {}).get("limites_recursos", {}),
            gate={"n": self.gate.gate, "version": self.gate.version, "kind": self.kind},
            examen={"stub": {"latency_ms": stub.get("latency_ms"),
                             "token_rate_tps": stub.get("token_rate_tps"),
                             "stream_duration_s": stub.get("stream_duration_s"),
                             "error_rate": stub.get("error_rate")},
                    "phases": [{"name": p.name, "duration": p.duration,
                                "arrival_factor": p.arrival_factor}
                               for p in self.gate.phases]},
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
        refs = {
            "k6_summary": str(self.run_dir / "summary.json"),
            "pool": str(self.run_dir / "pool.json"),
            "corpus": str(self.run_dir / "corpus.json"),
            "k6_config": str(self.run_dir / "k6_config.json"),
        }
        # Sólo si se llegó a contar: un run abortado no debe listar evidencia que no existe.
        recon = self.run_dir / "reconciliation.json"
        if recon.exists():
            refs["reconciliacion"] = str(recon)
        refs["plataforma_r3"] = f"/srv/itv-runs/{self.run_id}/"
        return refs

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
        """Id por defecto del run. Incluye el KIND efectivo cuando no es ``gate_oficial``
        (``20260810-g125-drill-01``, ``…-dry-run-01``): sin eso, el drill de saturación y
        el gate 125 oficial del mismo día proponen el MISMO id y el segundo run pisaría la
        evidencia del primero — dos exámenes distintos con la misma identidad."""
        fecha = self._now().strftime("%Y%m%d")
        if self.kind != "gate_oficial":
            return f"{fecha}-g{self.gate.gate}-{self.kind}-01"
        return f"{fecha}-g{self.gate.gate}-01"

    def _write_json(self, name: str, data: object) -> Path:
        return self._write_text(name, json.dumps(data, ensure_ascii=False, indent=2))

    def _write_secret_json(self, name: str, data: object) -> Path:
        """Escribe con permisos 0600 desde el fd (nunca una ventana world-readable, ni
        siquiera al sobrescribir un archivo previo de un run anterior)."""
        path = self.run_dir / name
        blob = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, blob)
        finally:
            os.close(fd)
        return path

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

def _default_smoke(backend_url: str, model_chat: str,
                   model_coding: str = "coding") -> Callable[[list], list]:
    """Sonda real de las 4 superficies. Devuelve la lista de ``(superficie, motivo)`` que
    NO se sirvieron; vacía = todo el wire probado.

    El texto de prueba es deliberadamente INOCUO (sin PII ni canarios): se comprueba que
    la superficie responde, no la política. Un bloqueo acá sería un falso negativo."""
    TEXTO = "Consulta administrativa de rutina sobre el horario de atención."

    def smoke(pool: list) -> list:  # pragma: no cover — camino real (los tests inyectan)
        import httpx
        fallos = []
        base = f"{backend_url}/api/v1"

        def _cred(role):
            for c in pool or []:
                if isinstance(c, dict) and c.get("role") == role and c.get("password"):
                    return c
            return None

        def _key(client_type):
            for c in pool or []:
                if isinstance(c, dict) and c.get("client_type") == client_type \
                        and c.get("basa_key"):
                    return c["basa_key"]
            return None

        with httpx.Client(timeout=60.0) as http:
            cli = _cred("client")
            if cli is None:
                fallos.append(("chat", "el pool no trae ninguna credencial de rol client"))
            else:
                r = http.post(f"{base}/users/login",
                              json={"username": cli["username"], "password": cli["password"]})
                if r.status_code != 200:
                    fallos.append(("chat", f"login {r.status_code}"))
                else:
                    tok = r.json().get("access_token")
                    auth = {"Authorization": f"Bearer {tok}"}
                    # Catálogo REAL del motor: `GET /chat/models` es lo que consume la UI
                    # de Modelos y basta credencial autenticada. Fail-closed: si no se
                    # puede leer, no se corre (no se asume que el alias existe).
                    r = http.get(f"{base}/chat/models", headers=auth)
                    if r.status_code != 200:
                        fallos.append(("catálogo", f"GET /chat/models → HTTP "
                                                   f"{r.status_code}: sin catálogo no se "
                                                   "puede verificar el alias de chat"))
                    else:
                        nombres = {m.get("model_name") for m in (r.json() or [])
                                   if isinstance(m, dict)}
                        if model_chat not in nombres:
                            fallos.append(("catálogo", f"el alias {model_chat!r} no está en "
                                                       f"el catálogo del motor "
                                                       f"({sorted(n for n in nombres if n)!r})"))
                    r = http.post(f"{base}/chat/completions",
                                  json={"model": model_chat, "message": TEXTO},
                                  headers=auth)
                    if r.status_code != 200:
                        fallos.append(("chat", f"HTTP {r.status_code} con model="
                                               f"{model_chat!r} → {r.text[:160]}"))

            k_ext = _key("desktop")
            if k_ext is None:
                fallos.append(("extension", "el pool no trae basa_key de client_type=desktop"))
            else:
                r = http.post(f"{base}/gw/inspect", json={"text": TEXTO, "tool": "chatgpt"},
                              headers={"X-Basa-Key": k_ext})
                if r.status_code != 200:
                    fallos.append(("extension", f"HTTP {r.status_code} → {r.text[:160]}"))

            k_cod = _key("base_url")
            if k_cod is None:
                fallos.append(("coding", "el pool no trae basa_key de client_type=base_url"))
            else:
                # Con `stream: True` y el alias REAL: el guion de coding es SSE, y probar
                # la rama no-streaming dejaría pasar un desalineado del wire en streaming
                # justo en la superficie cuyo 400 leemos como bloqueo apoyándonos en este
                # humo. Se verifica que abra y entregue el primer byte, no todo el stream.
                try:
                    with http.stream("POST", f"{base}/gw/v1/messages",
                                     json={"model": model_coding, "max_tokens": 16,
                                           "stream": True,
                                           "messages": [{"role": "user", "content": TEXTO}]},
                                     headers={"X-Basa-Key": k_cod,
                                              "Accept": "text/event-stream"}) as r:
                        if r.status_code != 200:
                            r.read()
                            fallos.append(("coding", f"HTTP {r.status_code} (stream) → "
                                                     f"{r.text[:160]}"))
                        else:
                            primero = next(r.iter_bytes(), b"")
                            if not primero:
                                fallos.append(("coding", "el stream abrió con 200 pero no "
                                                         "entregó un solo byte"))
                except Exception as exc:  # noqa: BLE001 — transporte/stream roto
                    fallos.append(("coding", f"{type(exc).__name__}: {exc}"))

            cmp_ = _cred("compliance_officer") or _cred("tenant_admin")
            if cmp_ is None:
                fallos.append(("admin", "el pool no trae credencial compliance/admin"))
            else:
                r = http.post(f"{base}/users/login",
                              json={"username": cmp_["username"], "password": cmp_["password"]})
                if r.status_code != 200:
                    fallos.append(("admin", f"login {r.status_code}"))
                else:
                    tok = r.json().get("access_token")
                    r = http.get(f"{base}/audit-logs", params={"limit": 1},
                                 headers={"Authorization": f"Bearer {tok}"})
                    if r.status_code != 200:
                        fallos.append(("admin", f"HTTP {r.status_code} → {r.text[:160]}"))
        return fallos

    return smoke


def _default_clock_probe(backend_url: str) -> Callable[[], Optional[datetime]]:
    """Sonda real del reloj del backend para la guarda de skew (M1): CUALQUIER respuesta
    HTTP/1.1 trae ``Date`` (no hace falta un 200 ni credenciales)."""
    def probe() -> Optional[datetime]:  # pragma: no cover — camino real
        import httpx
        from email.utils import parsedate_to_datetime
        resp = httpx.get(f"{backend_url}/api/v1/health", timeout=10, follow_redirects=True)
        date = resp.headers.get("date")
        return parsedate_to_datetime(date) if date else None
    return probe


def _git_commit() -> str:
    """Sha del harness que corre el examen, para el fingerprint. Si el árbol no es un repo
    (el caso de la caja de examen, que recibe el código por tar), devuelve ``unknown`` en
    vez de fallar: el operador puede fijarlo con ``--harness-commit``."""
    import subprocess  # local: el import global no se paga en cada run
    raiz = Path(__file__).resolve().parent.parent.parent.parent
    try:
        out = subprocess.run(["git", "-C", str(raiz), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else "unknown"

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
    p.add_argument("--pool-file", type=Path, default=None,
                   help="pool 0600 emitido por `seeder.seed --emit-credentials`: aporta "
                        "las basa_key de las Connections (extensión/coding) y la "
                        "credencial compliance del reconcile")
    p.add_argument("--reconcile", choices=("none", "http"), default="none",
                   help="'http' cuenta las filas de audit_logs del producto en la ventana "
                        "del run (obligatorio en un gate oficial); 'none' = sin conteo")
    p.add_argument("--model-chat", default=None,
                   help="alias de modelo de la superficie chat: DEBE existir en el "
                        "`model_list` del motor desplegado (p. ej. itv-examen-local). "
                        "OBLIGATORIO en una corrida real — no hay default plausible: el "
                        "alias es del despliegue, y uno inventado devuelve 400 sin auditar "
                        "(60%% del gate sin medir, el fallo del 12-ago)")
    p.add_argument("--model-coding", default="coding",
                   help="alias nominal de la superficie coding (viaja por /gw, donde la "
                        "Connection resuelve el destino)")
    p.add_argument("--hardware-file", type=Path, default=None,
                   help="JSON del output `fingerprint_hardware` de OpenTofu (provider, "
                        "location, datacenter, tipos de caja). Sin él, un gate oficial se "
                        "firma con hardware 'unknown' y su evidencia no es contrastable")
    p.add_argument("--producto-file", type=Path, default=None,
                   help="JSON del build del SUT: {commit, digests{servicio: sha256}} y, "
                        "opcional, workers_procesos/limites_recursos. Es QUÉ se midió")
    p.add_argument("--licencia-file", type=Path, default=None,
                   help="JSON de la licencia del SUT: {lic_id, max_seats, seats_used}")
    p.add_argument("--harness-commit", default=None,
                   help="sha del harness que corre el examen (default: git rev-parse HEAD "
                        "del repo; 'unknown' si no hay git)")
    args = p.parse_args(argv)

    # El presupuesto de admin es un UMBRAL vinculante: un valor no finito o <= 0 lo
    # volvería decorativo (nada lo supera) o aleatorio (NaN). Se valida ANTES de construir
    # el orquestador — no se empieza un examen con un criterio roto.
    budget = args.drill_admin_budget_ms
    if budget is not None and (not math.isfinite(budget) or budget <= 0):
        p.error(f"--drill-admin-budget-ms debe ser un número FINITO > 0 (ms), es {budget!r}; "
                "derivalo del p95 de admin del gate oficial del mismo día")

    # El alias de chat no tiene default que sirva: es del DESPLIEGUE. En seco da igual
    # (no se llama al producto); en una corrida real, inventarlo es exactamente el fallo
    # que dejó el 60% del gate sin medir el 12-ago, así que se exige explícito.
    if args.model_chat is None:
        if not args.dry_run:
            p.error("falta --model-chat: el alias de la superficie chat tiene que existir "
                    "en el `model_list` del motor desplegado (mirá el config.yaml del "
                    "perfil; p. ej. itv-examen-local). Un alias inventado devuelve 400 sin "
                    "auditar y el 60% de la carga del gate no mide nada.")
        args.model_chat = "chat"

    gate = load_gate(args.gate_file) if args.gate_file else load_gate_by_number(args.gate)

    # El presupuesto de admin es un criterio del drill: sobre otro gate el flag no haría
    # NADA (el evaluador solo mira drill.criteria en un run drill) y el operador creería
    # haber fijado un umbral. Se avisa en vez de tragárselo. Ojo: el kind acá es el del
    # GATE — un --dry-run del drill sigue siendo un drill para esta guarda.
    kind_efectivo = gate.kind if gate.kind != "gate_oficial" else args.kind
    if args.drill_admin_budget_ms is not None and kind_efectivo != "drill":
        p.error(f"--drill-admin-budget-ms solo aplica a un gate kind: drill; este gate es "
                f"{kind_efectivo!r} (¿querías --gate-file gates/drill-saturacion-125.yaml?)")

    # La credencial del reconcile viaja SIEMPRE por el pool (archivo 0600), nunca por
    # argv: un `ps` en la caja del examen no debe mostrar la password del lector de
    # auditoría. Es además el mismo archivo que la semilla ya verificó contra la DB, así
    # que no hay una segunda fuente de verdad que pueda divergir.
    reconcile_fn = None
    if args.reconcile == "http":
        if args.dry_run:
            p.error("--reconcile http no aplica a --dry-run: un run en seco no consulta el "
                    "producto (sus datos son sintéticos y NUNCA oficiales)")
        if args.pool_file is None:
            p.error("--reconcile http necesita --pool-file: la credencial que lee "
                    "/api/v1/audit-logs sale del pool 0600 del seeder (nunca por argv, "
                    "que es visible en `ps`)")
        try:
            pool = json.loads(Path(args.pool_file).read_text(encoding="utf-8"))
            usuario, clave = credential_from_pool(pool)
            reconcile_fn = build_http_reconcile(args.backend_url, usuario, clave)
        except (OSError, ValueError) as exc:
            p.error(f"no se pudo leer el pool {args.pool_file}: {exc}")
        except ReconcileError as exc:
            p.error(str(exc))
    elif not args.dry_run:
        print("⚠ sin --reconcile http: los SLO (b) reconciliation_rows y (d) "
              "blocked_rows_durable_100 no se pueden computar y el run abortará al "
              "reconciliar. Un gate OFICIAL se corre con --reconcile http.", file=sys.stderr)

    # Metadata del fingerprint: QUÉ se midió y sobre qué caja. Un JSON ilegible es error
    # del CLI, no un `unknown` silencioso — el fingerprint es lo único que hace la
    # evidencia contrastable después (y lo que separa un run legítimo de uno que no lo es).
    def _leer_json(ruta, cual):
        if ruta is None:
            return None
        try:
            data = json.loads(Path(ruta).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            p.error(f"no se pudo leer {cual} {ruta}: {exc}")
        if not isinstance(data, dict):
            p.error(f"{cual} {ruta} debe ser un objeto JSON, no {type(data).__name__}")
        return data

    hardware = _leer_json(args.hardware_file, "--hardware-file")
    producto = _leer_json(args.producto_file, "--producto-file")
    licencia = _leer_json(args.licencia_file, "--licencia-file")
    if not args.dry_run and (hardware is None or producto is None):
        print("⚠ sin --hardware-file/--producto-file: el fingerprint se firma con "
              "'unknown' y el run NO será contrastable contra otro (ni comparable por el "
              "comparador de runs). Un gate OFICIAL los pasa.", file=sys.stderr)

    orch = Orchestrator(gate, run_id=args.run_id, backend_url=args.backend_url,
                        stub_url=args.stub_url, runs_dir=args.runs_dir, seed=args.seed,
                        kind=args.kind, dry_run=args.dry_run,
                        drill_admin_budget_ms=args.drill_admin_budget_ms,
                        model_chat=args.model_chat, model_coding=args.model_coding,
                        pool_file=args.pool_file, reconcile_fn=reconcile_fn,
                        hardware=hardware, producto=producto, licencia=licencia,
                        harness_commit=args.harness_commit or _git_commit(),
                        clock_probe_fn=(None if args.dry_run else
                                        _default_clock_probe(args.backend_url.rstrip("/"))),
                        smoke_fn=(None if args.dry_run else
                                  _default_smoke(args.backend_url.rstrip("/"),
                                                 args.model_chat, args.model_coding)))
    try:
        verdict = orch.run()
    except OrchestratorError as exc:
        # Precondición del run (p. ej. run_dir con evidencia): mensaje accionable, no
        # traceback — y sin tocar el directorio existente.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"run {verdict.run_id}: estado={verdict.estado} global={verdict.global_veredicto}")
    print(f"  artefactos → {orch.run_dir}")
    if verdict.invalid_reason:
        print(f"  motivo: {verdict.invalid_reason}", file=sys.stderr)
    return 0 if verdict.global_veredicto == "PASS" else (2 if verdict.estado != "completed" else 1)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
