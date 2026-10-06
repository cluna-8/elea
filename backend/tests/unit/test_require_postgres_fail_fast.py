"""`require_postgres()` no puede colgar la recolección cuando no hay Postgres.

Caso real (ensayo 2026-10-06, `ENSAYO-SEPARAR-BASES.md` §6.2 del instalador): con
`docker compose run --rm --no-deps backend pytest tests/ -q` y SIN la `db` del compose, la
recolección quedó inmóvil más de 10 minutos. ~100 módulos de integración llaman a
`require_postgres()` al importarse; cada uno pagaba una sonda completa (el `connect_timeout=3`
de libpq no cubre la resolución del nombre `db`, que en un proyecto aislado no existe), y los
costos se SUMABAN. Contrato que se fija acá: UNA sola sonda por sesión, con techo de tiempo
duro, y un skip cuyo motivo dice qué hacer.
"""
import sys
import threading
import time
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import migration_harness  # noqa: E402


@pytest.fixture(autouse=True)
def _estado_limpio(monkeypatch):
    monkeypatch.setattr(migration_harness, "_ESTADO_PG", {})


def _skip_de(llamada):
    with pytest.raises(pytest.skip.Exception) as info:
        llamada()
    return str(info.value)


def test_sonda_colgada_se_corta_y_las_demas_llamadas_no_pagan_otra(monkeypatch):
    llamadas = []
    bloqueo = threading.Event()

    def create_engine_colgado(*args, **kwargs):
        llamadas.append(args)
        bloqueo.wait(30)  # un getaddrinfo que no vuelve
        raise AssertionError("no debería llegar")

    monkeypatch.setattr(migration_harness, "create_engine", create_engine_colgado)
    monkeypatch.setattr(migration_harness, "_TECHO_SONDA_S", 0.3)

    inicio = time.monotonic()
    motivos = [_skip_de(lambda: migration_harness.require_postgres()) for _ in range(20)]
    transcurrido = time.monotonic() - inicio
    bloqueo.set()

    assert transcurrido < 3, f"20 módulos tardaron {transcurrido:.1f}s: la sonda no se comparte"
    assert len(llamadas) == 1, "cada módulo volvió a sondear en vez de reusar el resultado"
    assert len(set(motivos)) == 1


def test_el_motivo_del_skip_dice_donde_y_que_hacer(monkeypatch):
    def create_engine_roto(*args, **kwargs):
        raise OSError("could not translate host name")

    monkeypatch.setattr(migration_harness, "create_engine", create_engine_roto)
    motivo = _skip_de(migration_harness.require_postgres)
    assert f"{migration_harness.PG_HOST}:{migration_harness.PG_PORT}" in motivo
    assert "docker compose up -d db" in motivo
    assert "POSTGRES_HOST" in motivo  # y cómo apuntarla a otra base


def test_postgres_disponible_se_sonda_una_sola_vez(monkeypatch):
    llamadas = []

    class _Cx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _Engine:
        def connect(self):
            return _Cx()

        def dispose(self):
            pass

    def create_engine_ok(*args, **kwargs):
        llamadas.append(args)
        return _Engine()

    monkeypatch.setattr(migration_harness, "create_engine", create_engine_ok)
    for _ in range(5):
        migration_harness.require_postgres()  # no hace skip
    assert len(llamadas) == 1
