"""Centinela de canarios del stub (spec 035, T016; FR-003/FR-007c; contract
``stub-wire.md`` §Detección de canarios).

Es la pieza MÁS crítica del harness: su detección ES el SLO de fuga de PII (c). Si un
canario del run aparece EN CLARO en un request que el SUT le manda al proveedor
simulado, el masking falló y ``zero_raw_canaries`` va a FAIL. El run NO se aborta por un
hit (se mide el tamaño de la fuga); el veredicto lo dicta el evaluador leyendo la
evidencia.

Dos caminos, por diseño redundantes (el segundo VERIFICA al primero — SC-004):

1. **INLINE**: sobre los bytes de cada request, ANTES de que el handler lo use. La
   detección es de DOBLE RED para no fallar en silencio (hallazgo A3):
   - literal crudo (``value in body``) — el caso común, rapidísimo;
   - forma JSON-escapada del valor (``json.dumps(value)`` con y sin ``ensure_ascii``) —
     un canario con comilla, backslash o tilde viaja escapado dentro del JSON;
   - strings DECODIFICADOS del body cuando parsea como JSON — si el SUT re-serializa el
     payload, el valor reaparece al decodificar.
   Alcanza de sobra a la escala del gate (research R2: ~151 µs p50 con 100 canarios) y no
   suma dependencias. Hit → ``LeakEvidence``.
2. **SPOOL**: cada payload se persiste en un JSONL comprimido con zstd, un archivo POR
   RUN (``spool-<run_id>.jsonl.zst`` — hallazgo A2: un run nunca pisa la evidencia de
   otro). El barrido POST-run independiente (``sweep_spool``) re-escanea TODO con la
   misma doble red y DEBE coincidir con la detección inline. El corpus es 100% sintético,
   así que persistir crudo es válido (metadata-only no aplica: no hay PII real).

**Buffer POR REQUEST, no por chunk** (regla dura del contrato): un canario partido entre
chunks de un request troceado debe detectarse igual. La garantía se cumple escaneando el
CUERPO ACUMULADO (``scan_body`` recibe el body completo); escanear chunks aislados
perdería el canario que cruza la frontera.

**Cierre del spool (hallazgo A1)**: el frame zstd DEBE finalizarse antes del barrido, o
``sweep_spool`` lee un frame truncado y perdería evidencia EN SILENCIO. Por eso ``close``
escribe un marcador ``__spool_eof__`` y finaliza el frame; ``sweep_spool`` EXIGE ese
marcador como última línea y levanta ``SpoolTruncatedError`` si falta (nunca menos
registros callado). El orquestador invoca ``POST /control/finalize`` (→ ``close``) antes
de barrer.

**Tamaño del spool (B4)**: se spolea TODO el tráfico (no solo los hits) A PROPÓSITO — el
barrido SC-004 existe para cazar lo que el detector inline se PERDIÓ; con solo-hits sería
ciego a los falsos negativos. Costo estimado: ~20-40 MB comprimidos por gate 500
(research R2). Si algún perfil futuro lo hiciera prohibitivo, la palanca sería un muestreo
de limpios + todos los hits, documentada acá.

DETERMINISMO: la lógica de detección es pura (bytes → bool). El único no-determinista es
el ``timestamp`` de la evidencia, que se INYECTA (no se lee el reloj acá).
"""
from __future__ import annotations

import base64
import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import zstandard as zstd

# Clave del marcador de fin de spool (última línea que escribe ``close``).
_EOF_KEY = "__spool_eof__"


class SpoolTruncatedError(RuntimeError):
    """El spool no termina en el marcador ``__spool_eof__``: frame truncado / no
    finalizado. Barrer así perdería evidencia en silencio (hallazgo A1)."""


@dataclass(frozen=True)
class LeakEvidence:
    """Una fuga confirmada: un canario del run aparecido en claro en el stub.

    Campos de data-model («LeakEvidence {canario, request_id, superficie, timestamp,
    config_masking_vigente}»), más ``entity_type`` para el forense por tipo de PII.
    """
    canary_id: str
    canary_value: str
    entity_type: str
    request_id: str
    surface: str
    timestamp: str
    config_masking_vigente: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "canary_id": self.canary_id,
            "canary_value": self.canary_value,
            "entity_type": self.entity_type,
            "request_id": self.request_id,
            "surface": self.surface,
            "timestamp": self.timestamp,
            "config_masking_vigente": self.config_masking_vigente,
        }


def _json_string_leaves(body: bytes) -> list[str]:
    """Todos los strings hoja del body si parsea como JSON (para cazar canarios que el
    SUT re-serializó / escapó). Body no-JSON → lista vacía."""
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return []
    out: list[str] = []
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            out.append(cur)
        elif isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return out


class _Entry:
    """Un canario precompilado: su valor y las agujas (needles) a buscar en el body."""

    __slots__ = ("meta", "value", "needles")

    def __init__(self, meta: dict) -> None:
        self.meta = meta
        self.value = meta.get("value", "")
        needles: set[bytes] = {self.value.encode("utf-8")}
        # forma JSON-escapada (con y sin ensure_ascii): cubre comilla/backslash/tilde
        needles.add(json.dumps(self.value, ensure_ascii=True)[1:-1].encode("utf-8"))
        needles.add(json.dumps(self.value, ensure_ascii=False)[1:-1].encode("utf-8"))
        self.needles = [n for n in needles if n]


class _Matcher:
    """Detector de doble red sobre un set de canarios. ``scan`` devuelve los metadatos de
    los canarios encontrados en un body (cada uno a lo sumo una vez)."""

    def __init__(self, canaries: Iterable[dict]) -> None:
        self.entries = [_Entry(c) for c in canaries if c.get("value")]

    def __len__(self) -> int:
        return len(self.entries)

    def scan(self, body: bytes) -> list[dict]:
        hits: list[dict] = []
        leaves: Optional[list[str]] = None  # se decodifica una sola vez, si hace falta
        for e in self.entries:
            found = any(n in body for n in e.needles)
            if not found:
                if leaves is None:
                    leaves = _json_string_leaves(body)
                if leaves and any(e.value in s for s in leaves):
                    found = True
            if found:
                hits.append(e.meta)
        return hits


class CanarySentinel:
    """Centinela inline + spool de un run. NO es thread-safe: pensado para el bucle
    asyncio de un solo proceso (los handlers llaman ``scan_body`` sin ``await`` en medio,
    así el escaneo+spool es atómico frente al event loop).

    Ciclo de vida del spool (orquestado por la API de control):
        ``configure_run(run_id)`` → tráfico (``scan_body``) → ``close()`` → ``sweep_spool``.
    Un ``run_id`` distinto abre OTRO archivo (nunca pisa el anterior). ``reset`` se llama
    al ARRANQUE del run (antes de tráfico): abandona el stream y limpia contadores.
    """

    def __init__(self, spool_dir: Optional[Path] = None) -> None:
        self._spool_dir = Path(spool_dir) if spool_dir else None
        self._run_id: Optional[str] = None
        self._matcher = _Matcher([])
        self._fh = None
        self._zw = None
        self._record_count = 0
        self._finalized = False
        self.spool_seconds = 0.0  # coste acumulado de compresión/escritura (B5)

    # ── carga y ciclo de vida ────────────────────────────────────────────────────────

    def load_canaries(self, canaries: Iterable[dict]) -> None:
        """Carga el set de canarios del run (reemplaza el anterior)."""
        self._matcher = _Matcher(list(canaries))

    @property
    def canary_count(self) -> int:
        return len(self._matcher)

    def set_spool_dir(self, spool_dir: Optional[Path]) -> None:
        """Fija el directorio de spool (idealmente antes del tráfico del run)."""
        self._teardown_stream()
        self._spool_dir = Path(spool_dir) if spool_dir else None

    def configure_run(self, run_id: Optional[str]) -> None:
        """Cambia el run activo → nuevo archivo de spool. No pisa el archivo del run
        anterior (nombre distinto por ``run_id``)."""
        if run_id == self._run_id:
            return
        self._teardown_stream()
        self._run_id = run_id
        self._record_count = 0
        self._finalized = False

    @property
    def current_spool_path(self) -> Optional[Path]:
        if self._spool_dir is None:
            return None
        run = self._run_id or "default"
        return self._spool_dir / f"spool-{run}.jsonl.zst"

    def reset(self) -> None:
        """Limpia el set de canarios y abandona el stream actual (se llama al arranque
        del run, antes del tráfico)."""
        self._teardown_stream()
        self._matcher = _Matcher([])
        self._record_count = 0
        self._finalized = False

    def close(self) -> None:
        """Finaliza el spool: escribe el marcador ``__spool_eof__`` y cierra el frame zstd
        para que el barrido lo lea completo (hallazgo A1). Idempotente."""
        if self._spool_dir is None or self._finalized:
            return
        self._ensure_spool()  # crea un archivo aunque el run no tuviera tráfico
        if self._zw is not None:
            eof = {_EOF_KEY: True, "records": self._record_count}
            self._zw.write((json.dumps(eof) + "\n").encode("utf-8"))
            self._teardown_stream()
        self._finalized = True

    def _teardown_stream(self) -> None:
        if self._zw is not None:
            self._zw.close()
            self._zw = None
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def _ensure_spool(self) -> None:
        if self._spool_dir is None or self._zw is not None:
            return
        path = self.current_spool_path
        path.parent.mkdir(parents=True, exist_ok=True)
        # 'ab': el nombre por run garantiza que nunca truncamos otro run; append permite
        # frames concatenados (zstd los lee transparente en el barrido).
        self._fh = open(path, "ab")
        self._zw = zstd.ZstdCompressor(level=3).stream_writer(self._fh)

    # ── detección ────────────────────────────────────────────────────────────────────

    def scan_body(self, *, request_id: str, endpoint: str, body: bytes,
                  also_scan: Optional[list[bytes]] = None,
                  content_encoding: str = "", unauditable: bool = False,
                  config_masking: Optional[dict] = None,
                  timestamp: str = "") -> list[LeakEvidence]:
        """Escanea el CUERPO ACUMULADO contra el set del run (doble red) y lo spoolea.

        ``also_scan`` son representaciones EXTRA a escanear (p. ej. el crudo comprimido
        además del descomprimido — A4): la unión de hits se deduplica por ``canary_id``.
        El escaneo es SIEMPRE best-effort, incluso sobre tráfico ``unauditable`` (que no
        pudimos decodificar del todo): el flag es ortogonal, nunca un motivo para no mirar.

        Devuelve una ``LeakEvidence`` por canario encontrado. Spoolea SIEMPRE el payload
        primario (con o sin hit) — el barrido post-run re-escanea todo para verificar al
        detector, no solo lo que el inline marcó.
        """
        seen: set[str] = set()
        hits: list[dict] = []
        for chunk in [body, *(also_scan or [])]:
            for meta in self._matcher.scan(chunk):
                cid = meta.get("canary_id", "")
                if cid in seen:
                    continue
                seen.add(cid)
                hits.append(meta)
        cfg = dict(config_masking or {})
        evidences = [
            LeakEvidence(
                canary_id=meta.get("canary_id", ""),
                canary_value=meta.get("value", ""),
                entity_type=meta.get("entity_type", ""),
                request_id=request_id,
                surface=endpoint,
                timestamp=timestamp,
                config_masking_vigente=cfg,
            )
            for meta in hits
        ]
        self._spool_write(request_id, endpoint, body, [e.canary_id for e in evidences],
                          timestamp, content_encoding, unauditable, cfg)
        return evidences

    def _spool_write(self, request_id: str, endpoint: str, body: bytes,
                     hit_ids: list[str], timestamp: str, content_encoding: str,
                     unauditable: bool, masking: dict) -> None:
        if self._spool_dir is None:
            return
        t0 = time.perf_counter()
        self._ensure_spool()
        record = {
            "request_id": request_id,
            "endpoint": endpoint,
            "ts": timestamp,
            "body_b64": base64.b64encode(body).decode("ascii"),
            "inline_hits": hit_ids,
            "content_encoding": content_encoding,
            "unauditable": unauditable,
            "masking": masking,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        self._zw.write(line.encode("utf-8"))
        self._record_count += 1
        self.spool_seconds += time.perf_counter() - t0


def sweep_spool(spool_path: Path, canaries: Iterable[dict], *,
                require_eof: bool = True) -> list[LeakEvidence]:
    """Barrido POST-run: re-escanea el spool zstd-JSONL con la MISMA doble red que el
    inline (SC-004), independiente del detector en vivo. Debe reproducir exactamente los
    hits inline.

    Falla RUIDOSAMENTE (``SpoolTruncatedError``) si el frame está truncado o le falta el
    marcador ``__spool_eof__`` — jamás devuelve menos registros en silencio (hallazgo A1).
    """
    matcher = _Matcher(list(canaries))
    out: list[LeakEvidence] = []
    saw_eof = False
    dctx = zstd.ZstdDecompressor()
    try:
        with open(spool_path, "rb") as fh:
            with dctx.stream_reader(fh) as reader:
                text = io.TextIOWrapper(reader, encoding="utf-8")
                for line in text:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if record.get(_EOF_KEY):
                        saw_eof = True
                        continue
                    if saw_eof:
                        # registros DESPUÉS del marcador: spool inconsistente (append tras
                        # finalize) → ruidoso, no silencio.
                        raise SpoolTruncatedError(
                            f"registros tras el marcador de fin en {spool_path}")
                    body = base64.b64decode(record["body_b64"])
                    # se escanea también lo ``unauditable`` (best-effort, igual que inline):
                    # mantiene la paridad inline==sweep; el flag ya se reportó en vivo.
                    for meta in matcher.scan(body):
                        out.append(LeakEvidence(
                            canary_id=meta.get("canary_id", ""),
                            canary_value=meta.get("value", ""),
                            entity_type=meta.get("entity_type", ""),
                            request_id=record["request_id"],
                            surface=record["endpoint"],
                            timestamp=record.get("ts", ""),
                            config_masking_vigente=record.get("masking", {}),
                        ))
    except zstd.ZstdError as exc:  # frame incompleto: nunca callar
        raise SpoolTruncatedError(f"frame zstd truncado en {spool_path}: {exc}") from exc
    if require_eof and not saw_eof:
        raise SpoolTruncatedError(
            f"spool sin marcador de fin (¿se llamó a /control/finalize?): {spool_path}")
    return out
