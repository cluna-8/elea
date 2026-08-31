"""El entrypoint de CLI del purgador (spec 018, FR-001/T008).

Antes de este PR `python -m src.services.retention.purger --run-now` NO ejecutaba nada: el módulo
no tenía `__main__` ni `argparse`. Ahora corre una pasada. Lo que se muerde acá es el CONTRATO del
CLI, no la corrida (eso lo cubren los tests de integración contra Postgres):

* `--run-now` invoca `run_once(run_now=True)` — CUÁNDO;
* sin el flag, `run_now=False` — respeta la ventana;
* el CLI NO decide SI BORRA: no toca `SENTINEL_PURGE_DRY_RUN`. Los dos ejes son ortogonales
  (Contrato 4), y encender la purga real sigue siendo una variable de entorno a la vista.

Se monkeypatchea `run_once` para no necesitar DB: lo que se afirma es el cableado del CLI.
"""
import os

from src.services.retention import purger


def test_run_now_invoca_run_once_con_run_now_true(monkeypatch, capsys):
    llamadas = {}

    def fake_run_once(*, run_now=False):
        llamadas["run_now"] = run_now
        return "RESULTADO-FALSO"

    monkeypatch.setattr(purger, "run_once", fake_run_once)

    rc = purger._main(["--run-now"])

    assert rc == 0
    assert llamadas["run_now"] is True, "--run-now dice CUÁNDO: saltea la ventana"
    assert "RESULTADO-FALSO" in capsys.readouterr().out, "el CLI escribe el resultado a stdout"


def test_sin_run_now_respeta_la_ventana(monkeypatch):
    llamadas = {}

    def fake_run_once(*, run_now=False):
        llamadas["run_now"] = run_now
        return None

    monkeypatch.setattr(purger, "run_once", fake_run_once)

    purger._main([])

    assert llamadas["run_now"] is False, "sin el flag, la corrida sólo trabaja dentro de la ventana"


def test_el_cli_no_decide_si_borra(monkeypatch):
    """CUÁNDO y SI BORRA son ortogonales: el CLI no toca la perilla del simulacro."""
    monkeypatch.setattr(purger, "run_once", lambda *, run_now=False: None)
    monkeypatch.delenv("SENTINEL_PURGE_DRY_RUN", raising=False)

    purger._main(["--run-now"])

    assert os.getenv("SENTINEL_PURGE_DRY_RUN") is None, "el CLI no setea SENTINEL_PURGE_DRY_RUN"
