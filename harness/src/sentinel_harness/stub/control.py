"""Estado del run + API de control del stub (spec 035, T017; contract ``stub-wire.md``
§API de control).

Consumidor: el orquestador del harness. Endpoints por run:

- ``POST /control/config``   — comportamiento programable por alias (latencia, ritmo,
  duración de stream, tasa de error y palancas de error) + semilla, dimensión de
  embeddings, ``run_id`` (namespacia el spool), ``spool_dir`` y el snapshot de masking
  vigente que se estampa en cada ``LeakEvidence``.
- ``POST /control/canaries`` — carga el set de canarios del run (lista explícita o
  ``{run_id, n}`` generado por el corpus).
- ``POST /control/reset``    — limpia contadores, set de canarios y baseline de headroom.
- ``POST /control/finalize`` — cierra el frame zstd del spool (marcador de fin) para que
  el barrido post-run lo lea completo (hallazgo A1). Se llama antes de ``sweep_spool``.
- ``GET  /control/report``   — canarios detectados con evidencia, requests por alias y
  endpoint, tráfico NO auditable, drift de pacing p50/p95/p99 y CPU propia (el
  AUTO-HEADROOM del instrumento) + coste del spool.

**Auto-headroom** (base de la INVALIDEZ del run, juzgada por el orquestador): el stub se
auto-mide para no mentir. ``drift`` = cuánto se atrasa cada emisión de token respecto del
cronograma de modelo abierto (si el event loop se satura, crece). ``cpu_pct`` = CPU propia
promedio desde el reset (vía ``resource``, stdlib — sin ``psutil``). Umbrales del contrato:
drift p99 > 5 ms o CPU > 60% ⇒ run inválido. El stub EXPONE el veredicto informativo
(``valido``); la decisión vinculante la toma el orquestador leyendo este report.

Nota CPU (B4): ``cpu_pct`` asume 1 proceso / 1 event loop (el diseño del stub). Con varios
hilos ``ru_utime+ru_stime`` es la suma de todos → podría superar 100%; a 1 loop se mantiene
en [0, ~100]. El coste del spool se mide aparte (``spool_seconds``) y NO entra en el drift
de pacing: el spool ocurre en ``_ingest``, antes de que arranque el cronómetro del stream.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .canary_sentinel import CanarySentinel, LeakEvidence

try:  # ``resource`` es stdlib en Unix (Linux/macOS — donde corre el generador).
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]

# Umbrales de invalidez del run (contract §API de control).
DRIFT_P99_THRESHOLD_MS = 5.0
CPU_THRESHOLD_PCT = 60.0


def _cpu_seconds() -> float:
    """CPU propia acumulada (user+sys) en segundos. 0 si ``resource`` no está."""
    if resource is None:  # pragma: no cover
        return 0.0
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Percentil por rango-más-cercano sobre una lista YA ordenada (0 si vacía)."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = max(0, min(len(sorted_vals) - 1,
                      int(round((pct / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[rank]


@dataclass
class AliasBehavior:
    """Comportamiento programado de un alias (contract §Comportamiento programable)."""
    latency_ms: float = 0.0        # tiempo al primer byte/token
    token_rate: float = 50.0       # tokens por segundo (ritmo de emisión)
    stream_duration_s: float = 1.0 # duración objetivo del stream SSE
    error_rate: float = 0.0        # tasa determinista por semilla [0, 1]
    error_terminal: bool = False   # palanca (B3): error NO reintentable (5xx/400) al fallar
    error_mid_stream: bool = False # palanca (B3): romper el stream A MITAD, no pre-stream

    @classmethod
    def from_dict(cls, data: dict) -> "AliasBehavior":
        base = cls()
        return cls(
            latency_ms=float(data.get("latency_ms", base.latency_ms)),
            token_rate=float(data.get("token_rate", base.token_rate)),
            stream_duration_s=float(data.get("stream_duration_s", base.stream_duration_s)),
            error_rate=float(data.get("error_rate", base.error_rate)),
            error_terminal=bool(data.get("error_terminal", base.error_terminal)),
            error_mid_stream=bool(data.get("error_mid_stream", base.error_mid_stream)),
        )

    def to_dict(self) -> dict:
        return {
            "latency_ms": self.latency_ms,
            "token_rate": self.token_rate,
            "stream_duration_s": self.stream_duration_s,
            "error_rate": self.error_rate,
            "error_terminal": self.error_terminal,
            "error_mid_stream": self.error_mid_stream,
        }


def _default_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StubState:
    """Estado mutable de un run del stub. Un solo proceso, un solo run a la vez.

    ``clock``/``sleep`` son inyectables (por defecto ``time.monotonic``/``asyncio.sleep``):
    un reloj falso determinista permite verificar la grilla de pacing sin asserts frágiles
    de tiempo real (hallazgo A5).
    """

    def __init__(self, sentinel: Optional[CanarySentinel] = None, *,
                 spool_dir: Optional[object] = None,
                 now_iso: Callable[[], str] = _default_now_iso,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.sentinel = (sentinel if sentinel is not None
                         else CanarySentinel(spool_dir=spool_dir))
        self.now_iso = now_iso
        self.clock = clock
        self.sleep = sleep
        # config del run
        self.run_id: Optional[str] = None
        self.seed: int = 0
        self.embedding_dim: int = 1536
        self.defaults = AliasBehavior()
        self.aliases: dict[str, AliasBehavior] = {}
        self.masking_config: dict = {}
        # contadores / registro
        self._req_counter = 0
        self.requests_por_alias: Counter = Counter()
        self.requests_por_endpoint: Counter = Counter()
        self.not_found = 0
        self.errors_inyectados = 0
        self.unauditable: list[dict] = []      # tráfico que no pudimos mirar (A4)
        self._error_index: Counter = Counter()
        self.leaks: list[LeakEvidence] = []
        self.programmed: list[dict] = []       # latencia programada de CADA request
        self.drift_samples_ms: list[float] = []
        # baseline de auto-headroom
        self._wall0 = time.monotonic()
        self._cpu0 = _cpu_seconds()

    # ── configuración ─────────────────────────────────────────────────────────────────

    def apply_config(self, data: dict) -> None:
        """Aplica ``POST /control/config``. Acepta ``aliases`` (mapa) y/o los campos de
        alias en el nivel superior (compat con ``{alias → {...}}`` de data-model)."""
        if "spool_dir" in data:
            self.sentinel.set_spool_dir(data["spool_dir"])
        if "run_id" in data:
            self.run_id = data["run_id"]
            self.sentinel.configure_run(self.run_id)
        if "seed" in data:
            self.seed = int(data["seed"])
        if "embedding_dim" in data:
            self.embedding_dim = int(data["embedding_dim"])
        if "defaults" in data and isinstance(data["defaults"], dict):
            self.defaults = AliasBehavior.from_dict(data["defaults"])
        if "masking_config" in data and isinstance(data["masking_config"], dict):
            self.masking_config = dict(data["masking_config"])
        aliases = data.get("aliases")
        if aliases is None and "latency_ms" not in data:
            # forma data-model: el propio body ES el mapa {alias → {...}}
            aliases = {k: v for k, v in data.items()
                       if isinstance(v, dict) and "latency_ms" in v}
        if isinstance(aliases, dict):
            for alias, cfg in aliases.items():
                if isinstance(cfg, dict):
                    self.aliases[alias] = AliasBehavior.from_dict(cfg)

    def behavior_for(self, alias: str) -> AliasBehavior:
        return self.aliases.get(alias, self.defaults)

    # ── registro de requests ───────────────────────────────────────────────────────────

    def next_request_id(self) -> str:
        """ID determinista por contador (sin uuid): ``req-000001`` … Reinicia en reset."""
        self._req_counter += 1
        return f"req-{self._req_counter:06d}"

    def record_request(self, *, endpoint: str, request_id: str, latency_ms: float,
                       alias: Optional[str] = None) -> None:
        if alias is not None:
            self.requests_por_alias[alias] += 1
        self.requests_por_endpoint[endpoint] += 1
        # la latencia PROGRAMADA de cada request queda registrada (referencia FR-008)
        self.programmed.append({"request_id": request_id, "alias": alias,
                                "endpoint": endpoint, "latency_ms": latency_ms})

    def record_unauditable(self, request_id: str, endpoint: str, encoding: str) -> None:
        """Registra tráfico que NO pudimos inspeccionar (encoding no soportado o corrupto).
        Nunca un 0 en silencio: se expone ruidosamente en el report (hallazgo A4)."""
        self.unauditable.append({"request_id": request_id, "endpoint": endpoint,
                                 "content_encoding": encoding})

    def should_error(self, alias: str) -> bool:
        """Decisión de error DETERMINISTA por (semilla, alias, índice de la secuencia).

        Reproducible: misma semilla + misma SECUENCIA de requests por alias ⇒ mismo patrón
        (no depende del reloj ni de random global). Bajo concurrencia solo la TASA es
        determinista, no QUÉ request puntual falla (el orden de llegada puede variar)."""
        beh = self.behavior_for(alias)
        if beh.error_rate <= 0.0:
            return False
        if beh.error_rate >= 1.0:
            self._error_index[alias] += 1
            return True
        idx = self._error_index[alias]
        self._error_index[alias] += 1
        digest = hashlib.sha256(f"{self.seed}:{alias}:{idx}".encode("utf-8")).hexdigest()
        frac = int(digest[:16], 16) / float(1 << 64)
        return frac < beh.error_rate

    def record_drift(self, ms: float) -> None:
        self.drift_samples_ms.append(ms)

    def record_leaks(self, evidences: list[LeakEvidence]) -> None:
        if evidences:
            self.leaks.extend(evidences)

    # ── reset ──────────────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Limpia contadores, set de canarios y baseline de headroom (contract §reset)."""
        self.sentinel.reset()
        self._req_counter = 0
        self.requests_por_alias = Counter()
        self.requests_por_endpoint = Counter()
        self.not_found = 0
        self.errors_inyectados = 0
        self.unauditable = []
        self._error_index = Counter()
        self.leaks = []
        self.programmed = []
        self.drift_samples_ms = []
        self.sentinel.spool_seconds = 0.0
        self._wall0 = time.monotonic()
        self._cpu0 = _cpu_seconds()

    # ── auto-headroom ───────────────────────────────────────────────────────────────────

    def cpu_pct(self) -> float:
        """CPU propia promedio (%) desde el último reset. 0 si no transcurrió tiempo."""
        wall = time.monotonic() - self._wall0
        if wall <= 0:
            return 0.0
        return round((_cpu_seconds() - self._cpu0) / wall * 100.0, 2)

    def drift_percentiles(self) -> dict:
        s = sorted(self.drift_samples_ms)
        return {
            "p50": round(_percentile(s, 50), 4),
            "p95": round(_percentile(s, 95), 4),
            "p99": round(_percentile(s, 99), 4),
            "max": round(s[-1], 4) if s else 0.0,
            "n": len(s),
        }

    def programmed_by_alias(self) -> dict:
        """Latencia programada de referencia por alias (constante por config)."""
        out: dict[str, dict] = {}
        for rec in self.programmed:
            a = rec["alias"] if rec["alias"] is not None else "(sin-alias)"
            slot = out.setdefault(a, {"count": 0, "latency_ms": rec["latency_ms"]})
            slot["count"] += 1
            slot["latency_ms"] = rec["latency_ms"]
        return out

    def report(self) -> dict:
        drift = self.drift_percentiles()
        cpu = self.cpu_pct()
        valido = drift["p99"] <= DRIFT_P99_THRESHOLD_MS and cpu <= CPU_THRESHOLD_PCT
        contratados = sum(self.requests_por_endpoint.values())
        spool_path = self.sentinel.current_spool_path
        return {
            "run_id": self.run_id,
            # honesto: TODO lo que recibió el stub = endpoints contratados + 404s (A6)
            "requests_total": contratados + self.not_found,
            "requests_contratados": contratados,
            "requests_por_alias": dict(self.requests_por_alias),
            "requests_por_endpoint": dict(self.requests_por_endpoint),
            "not_found": self.not_found,
            "errors_inyectados": self.errors_inyectados,
            "trafico_no_auditable": {"count": len(self.unauditable),
                                     "requests": self.unauditable},
            "canarios_detectados": [e.to_dict() for e in self.leaks],
            "leak_count": len(self.leaks),
            "canary_set_size": self.sentinel.canary_count,
            "programmed_latency_ms_por_alias": self.programmed_by_alias(),
            "pacing_drift_ms": drift,
            "cpu_pct": cpu,
            "spool_seconds": round(self.sentinel.spool_seconds, 6),
            "spool_path": str(spool_path) if spool_path else None,
            "umbral": {"drift_p99_ms": DRIFT_P99_THRESHOLD_MS, "cpu_pct": CPU_THRESHOLD_PCT},
            "valido": valido,
        }


def register_control_routes(app: FastAPI, state: StubState) -> None:
    """Registra los endpoints ``/control/*`` sobre ``app``, cerrando sobre ``state``."""

    @app.post("/control/config")
    async def _config(request: Request):  # noqa: ANN202
        data = await request.json()
        state.apply_config(data)
        return {
            "ok": True,
            "run_id": state.run_id,
            "seed": state.seed,
            "embedding_dim": state.embedding_dim,
            "defaults": state.defaults.to_dict(),
            "aliases": {a: b.to_dict() for a, b in state.aliases.items()},
            "spool_path": (str(state.sentinel.current_spool_path)
                           if state.sentinel.current_spool_path else None),
        }

    @app.post("/control/canaries")
    async def _canaries(request: Request):  # noqa: ANN202
        data = await request.json()
        canaries = data.get("canaries")
        if canaries is None and data.get("run_id") and data.get("n") is not None:
            # generación on-demand vía el corpus (runtime-only, jamás commiteado)
            from ..corpus import generate_canaries
            canaries = generate_canaries(data["run_id"], int(data["n"]))
        canaries = canaries or []
        state.sentinel.load_canaries(canaries)
        return {"ok": True, "canary_set_size": state.sentinel.canary_count}

    @app.post("/control/reset")
    async def _reset():  # noqa: ANN202
        state.reset()
        return {"ok": True}

    @app.post("/control/finalize")
    async def _finalize():  # noqa: ANN202
        """Cierra el frame zstd del spool (marcador de fin) — llamar antes de barrer."""
        state.sentinel.close()
        return {"ok": True, "spool_path": (str(state.sentinel.current_spool_path)
                                           if state.sentinel.current_spool_path else None)}

    @app.get("/control/report")
    async def _report():  # noqa: ANN202
        return JSONResponse(content=state.report())
