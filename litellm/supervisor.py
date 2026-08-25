"""Supervisor del motor (spec 033, FR-001).

Es el entrypoint del container del motor: vigila `config.yaml` y el sentinel
`apply.trigger`, coalesce las ráfagas, **valida el YAML antes de tocar el proceso
viejo** y recién ahí relanza litellm con drenaje.

Vigila DOS cosas, no una: los disparadores de recarga y **que el hijo siga vivo**.
Al pasar a ser el entrypoint, este proceso es PID 1 y litellm es su hijo, así que
un crash del motor ya no hace salir al contenedor y `restart: unless-stopped` deja
de recuperarlo. Ver `check_liveness`.

Invariante duro de la spec: la validación corre SIEMPRE antes de matar. Un YAML
roto jamás puede dejar el motor caído — el proceso viejo sigue sirviendo y el
error se publica en `status.json`. Si un test puede pasar con el orden invertido,
el test está mal (tasks.md:97-98).

Cero deps nuevas: PyYAML ya viaja con LiteLLM. El supervisor NUNCA escribe en el
volumen `litellm_config` (su lado es `:ro`); sólo escribe `status.json` en
`engine_status`.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

IDLE, APPLYING, ERROR = "idle", "applying", "error"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _log(msg: str) -> None:
    """El log del supervisor ES el log del contenedor. stderr sin buffer para que
    `docker logs` lo muestre en el momento y no cuando se llene el buffer."""
    print(f"[supervisor] {msg}", file=sys.stderr, flush=True)


class Supervisor:
    """Loop de recarga supervisada. Todo lo inyectable es para poder testear el
    ORDEN de las operaciones con un proceso hijo falso."""

    def __init__(
        self,
        config_path: Path,
        sentinel_path: Path,
        status_dir: Path,
        launch,
        *,
        debounce: float = 5.0,
        drain: float = 30.0,
        autoreload: bool = True,
        relaunch_min: float = 5.0,
        sleep=time.sleep,
        now=time.time,
    ) -> None:
        self.config_path = Path(config_path)
        self.sentinel_path = Path(sentinel_path)
        self.status_dir = Path(status_dir)
        self._launch = launch
        self.debounce = debounce
        self.drain = drain
        self.autoreload = autoreload
        self.relaunch_min = relaunch_min
        self._sleep = sleep
        self._now = now
        self.child = None
        self._last_launch = None
        self._muerte_publicada = False
        self._seen = self._stamps()

    # ── estado observable ────────────────────────────────────────────────────
    def _write_status(self, state: str, last_error=None, config_hash=None) -> None:
        self.status_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "state": state,
            "ts": self._now(),
            "last_error": last_error,
            "config_hash": config_hash,
        }
        tmp = self.status_dir / "status.json.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.status_dir / "status.json")

    # ── disparadores ─────────────────────────────────────────────────────────
    def _stamps(self) -> tuple:
        def mtime(p: Path):
            try:
                return p.stat().st_mtime
            except OSError:
                return None

        # con AUTORELOAD=off el mtime del config deja de ser disparador: sólo el botón.
        return (mtime(self.config_path) if self.autoreload else None, mtime(self.sentinel_path))

    # ── validación (SIEMPRE antes de matar) ──────────────────────────────────
    def _validate(self):
        """→ (ok, error, hash). Nunca levanta: un config ilegible es `error`, no un crash."""
        try:
            raw = self.config_path.read_bytes()
        except OSError as exc:
            return False, f"no se pudo leer el config: {exc}", None
        try:
            yaml.safe_load(raw.decode("utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError) as exc:
            return False, f"YAML inválido: {exc}", None
        return True, None, hashlib.sha256(raw).hexdigest()

    def _spawn(self):
        """Único lugar donde nace el hijo: deja registrado CUÁNDO nació, que es lo que
        acota el ritmo de relanzamiento ante un motor que crashea al arrancar."""
        self.child = self._launch()
        self._last_launch = self._now()
        self._muerte_publicada = False  # el hijo nuevo tiene su propia muerte que publicar
        return self.child

    def _restart_child(self) -> None:
        """SIGTERM + ventana de drenaje; SIGKILL sólo si no se fue solo."""
        if self.child is not None and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=self.drain)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()
        self._spawn()

    def apply_changes(self) -> bool:
        """Un ciclo de aplicación. True si relanzó."""
        ok, err, digest = self._validate()
        if not ok:
            # El proceso viejo NO se toca: sigue sirviendo con el config anterior.
            self._write_status(ERROR, last_error=err)
            return False
        self._write_status(APPLYING, config_hash=digest)
        self._restart_child()
        self._write_status(IDLE, config_hash=digest)
        return True

    # ── liveness del hijo ────────────────────────────────────────────────────
    def check_liveness(self) -> bool:
        """Relanza el motor si murió SOLO (crash, OOM, segfault). True si relanzó.

        **Por qué existe (P1 del gate de #301).** Con el supervisor de entrypoint, litellm
        dejó de ser PID 1. Antes de la 033 un crash del motor mataba PID 1, el contenedor
        SALÍA y `restart: unless-stopped` (`compose.prod.yml:171`) lo levantaba. Con el
        supervisor arriba, el hijo se muere y el padre sigue vivo: el contenedor sigue `Up`
        y esa política **nunca dispara** — el motor quedaría caído hasta el próximo cambio
        de config. Cambió el entrypoint, que es la regla; hay que barrer a su lector. La
        recuperación vive acá o no existe.

        **No es un healthcheck**: en compose plano un healthcheck marca `unhealthy`, no
        reinicia nada. Y `/analytics/engine-status` sólo observa la muerte.

        El estado queda en `error` con el código de salida hasta el próximo `apply_changes`
        exitoso: un motor que crashea en loop tiene que ser VISIBLE. Antes lo delataba el
        contenedor reiniciándose en `docker ps`; ahora el contenedor se queda `Up` y el
        único testigo es `status.json`.
        """
        if self.child is None:
            return False
        code = self.child.poll()
        if code is None:
            return False
        # La muerte se publica APENAS se ve, antes de la cota (P2-a del re-gate de #301). Si se
        # publicara después, el primer crash tras un arranque sano dejaría `status.json` en
        # `idle` durante toda la ventana de la cota — y `status.json` es justo el único testigo
        # que queda ahora que el contenedor se queda `Up`. El flag evita reescribirlo una vez
        # por vuelta mientras dure la ventana; `_spawn` lo resetea, así que la muerte del hijo
        # NUEVO también se publica.
        if not self._muerte_publicada:
            _log(f"el motor terminó solo (código {code})")
            self._write_status(ERROR, last_error=f"el motor terminó solo (código {code})")
            self._muerte_publicada = True
        # Cota de ritmo: sin esto, un motor que no arranca (credencial mala, puerto tomado)
        # produce un fork por vuelta del loop. `restart: unless-stopped` traía el backoff del
        # daemon; al mudar la recuperación acá adentro, la cota se muda con ella.
        #
        # El delta va con clamp inferior (P2-b del re-gate de #301). `_now` es reloj de PARED y
        # no puede dejar de serlo: `_write_status` lo usa para el `ts` que el backend lee como
        # epoch. Un salto hacia atrás (step de NTP, resume de VM, restore de snapshot) da delta
        # negativo, y sin el `0 <=` la comparación quedaría True hasta que el reloj vuelva a
        # alcanzar `_last_launch`: trabaría la recuperación justo cuando hace falta. Fuera de
        # [0, relaunch_min) el reloj no es fuente confiable de «hace cuánto» y se relanza.
        if self._last_launch is not None and 0 <= self._now() - self._last_launch < self.relaunch_min:
            return False
        _log(f"relanzando el motor (código de salida anterior {code})")
        self._spawn()
        return True

    # ── loop ─────────────────────────────────────────────────────────────────
    def poll_once(self) -> bool:
        """Mira los disparadores una vez. Coalesce: espera la ventana de debounce y
        vuelve a leer, así una ráfaga de N cambios produce UN solo relanzamiento."""
        stamps = self._stamps()
        if stamps == self._seen:
            return False
        self._sleep(self.debounce)
        self._seen = self._stamps()  # se queda con el ÚLTIMO estado de la ráfaga
        return self.apply_changes()

    def run(self, interval: float = 1.0, iterations=None) -> None:
        if self.child is None:
            self._spawn()
            ok, err, digest = self._validate()
            self._write_status(IDLE if ok else ERROR, last_error=err, config_hash=digest)
        n = 0
        while iterations is None or n < iterations:
            # El loop vigila DOS cosas, no una: que el hijo siga vivo y que el config
            # haya cambiado. Vigilar sólo mtimes deja el motor muerto sin que nadie mire.
            self.check_liveness()
            self.poll_once()
            self._sleep(interval)
            n += 1


def build_default() -> Supervisor:
    config = Path(os.getenv("BASA_ENGINE_CONFIG_PATH", "/app/config/config.yaml"))
    argv = ["litellm", "--config", str(config)]
    return Supervisor(
        config_path=config,
        sentinel_path=Path(os.getenv("BASA_ENGINE_SENTINEL_PATH", "/app/config/apply.trigger")),
        status_dir=Path(os.getenv("BASA_ENGINE_STATUS_DIR", "/app/status")),
        launch=lambda: subprocess.Popen(argv),
        debounce=_env_float("BASA_ENGINE_APPLY_DEBOUNCE_SECONDS", 5.0),
        drain=_env_float("BASA_ENGINE_DRAIN_SECONDS", 30.0),
        autoreload=os.getenv("BASA_ENGINE_AUTORELOAD", "on").strip().lower() != "off",
    )


if __name__ == "__main__":  # pragma: no cover
    build_default().run()
