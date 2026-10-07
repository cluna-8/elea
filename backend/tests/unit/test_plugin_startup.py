"""Costura S16 — arranque de extensiones (spec 057 T104; research R33; contracts/costuras-base.md S16).

`PLUGIN_PACKAGES` + un `on_startup()` opcional en el paquete: `run_plugin_startup()` lo llama desde el
`_lifespan` de `src.main` antes del `yield`, una vez por proceso y antes de servir el primer pedido.

Los tests corren contra `src.main:app` con su `lifespan` REAL (`TestClient` como gestor de contexto,
`RUN_ALEMBIC_ON_STARTUP=false`), nunca contra un `FastAPI()` suelto: uno sin `lifespan` pasaría aunque el
enganche no corriera en la app real. `PLUGIN_PACKAGES` se lee al importar `src.main` (S1), así que cada caso la
fija ANTES de recargarlo. Los paquetes de prueba son archivos reales en un directorio temporal en `sys.path`.
"""
import importlib
import logging
import sys
import textwrap

import pytest
from fastapi.testclient import TestClient

LOG_MODULE = "s16_probe_log"


def _write(base, name, body):
    pkg = base / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text(textwrap.dedent(body))
    return name


ROUTERS = """
from fastapi import APIRouter
def get_routers():
    return []
"""


@pytest.fixture
def eventos(tmp_path, monkeypatch):
    """Registro compartido entre el test y los paquetes de prueba (`s16_probe_log.EVENTS`)."""
    (tmp_path / f"{LOG_MODULE}.py").write_text("EVENTS = []\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("RUN_ALEMBIC_ON_STARTUP", "false")
    log = importlib.import_module(LOG_MODULE)
    yield log.EVENTS
    for name in [m for m in sys.modules if m == LOG_MODULE or m.startswith("s16_pkg_")]:
        sys.modules.pop(name, None)


@pytest.fixture
def cargar_app(monkeypatch, eventos):
    """Fija `PLUGIN_PACKAGES`, recarga `src.main` (S1 la lee al importar) y devuelve su `app`."""
    from src import main

    def _cargar(paquetes: str = ""):
        if paquetes:
            monkeypatch.setenv("PLUGIN_PACKAGES", paquetes)
        else:
            monkeypatch.delenv("PLUGIN_PACKAGES", raising=False)
        # los schedulers del lifespan dejan huella en el registro (orden respecto del enganche)
        monkeypatch.setattr(main.license_reconcile, "start_scheduler", lambda: eventos.append("sched:start"))
        monkeypatch.setattr(main.license_reconcile, "stop_scheduler", lambda: eventos.append("sched:stop"))
        monkeypatch.setattr(main.retention_scheduler, "start_scheduler", lambda: eventos.append("ret:start"))
        monkeypatch.setattr(main.retention_scheduler, "stop_scheduler", lambda: eventos.append("ret:stop"))
        return importlib.reload(main).app

    yield _cargar
    monkeypatch.delenv("PLUGIN_PACKAGES", raising=False)
    importlib.reload(main)            # la app que ven los demás tests vuelve a ser la del core


def _paquete(tmp_path, nombre, on_startup=""):
    return _write(tmp_path, nombre, ROUTERS + textwrap.dedent(on_startup))


def test_on_startup_sincrono_corre_una_vez_y_antes_del_primer_pedido(tmp_path, eventos, cargar_app):
    pkg = _paquete(tmp_path, "s16_pkg_a", f"""
        import {LOG_MODULE}
        def on_startup():
            {LOG_MODULE}.EVENTS.append("a:startup")
    """)
    app = cargar_app(pkg)
    with TestClient(app) as client:
        assert "a:startup" in eventos                      # corrió al entrar, antes de cualquier pedido
        n_antes = list(eventos)
        assert client.get("/health").status_code == 200
        client.get("/health")
        assert eventos == n_antes                          # y no se repite por pedido
    assert eventos.count("a:startup") == 1


def test_on_startup_corrutina_se_espera(tmp_path, eventos, cargar_app):
    pkg = _paquete(tmp_path, "s16_pkg_async", f"""
        import asyncio, {LOG_MODULE}
        async def on_startup():
            await asyncio.sleep(0)
            {LOG_MODULE}.EVENTS.append("async:startup")
    """)
    with TestClient(cargar_app(pkg)):
        assert eventos.count("async:startup") == 1


def test_corre_despues_de_arrancar_los_schedulers_y_antes_de_servir(tmp_path, eventos, cargar_app):
    pkg = _paquete(tmp_path, "s16_pkg_orden", f"""
        import {LOG_MODULE}
        def on_startup():
            {LOG_MODULE}.EVENTS.append("plugin")
    """)
    with TestClient(cargar_app(pkg)):
        assert eventos[:3] == ["sched:start", "ret:start", "plugin"]
    assert eventos[-2:] == ["sched:stop", "ret:stop"]       # el cierre sigue siendo el de siempre


def test_sin_plugin_packages_no_se_llama_nada_y_los_schedulers_andan_como_hoy(eventos, cargar_app):
    with TestClient(cargar_app("")) as client:
        assert eventos == ["sched:start", "ret:start"]
        assert client.get("/health").status_code == 200
    assert eventos == ["sched:start", "ret:start", "sched:stop", "ret:stop"]


def test_paquete_sin_on_startup_no_llama_nada(tmp_path, eventos, cargar_app):
    pkg = _paquete(tmp_path, "s16_pkg_sin")
    with TestClient(cargar_app(pkg)) as client:
        assert client.get("/health").status_code == 200
    assert eventos == ["sched:start", "ret:start", "sched:stop", "ret:stop"]


def test_un_on_startup_que_levanta_se_registra_con_el_nombre_y_la_app_sirve(tmp_path, eventos, cargar_app, caplog):
    pkg = _paquete(tmp_path, "s16_pkg_roto", """
        def on_startup():
            raise RuntimeError("siembra rota")
    """)
    app = cargar_app(pkg)
    with caplog.at_level(logging.ERROR):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
    registro = [r for r in caplog.records if "s16_pkg_roto" in r.getMessage()]
    assert registro and registro[0].levelno == logging.ERROR
    assert "siembra rota" in registro[0].getMessage()


def test_un_fallo_no_impide_que_corran_los_demas_paquetes(tmp_path, eventos, cargar_app):
    roto = _paquete(tmp_path, "s16_pkg_rotox", """
        def on_startup():
            raise RuntimeError("x")
    """)
    sano = _paquete(tmp_path, "s16_pkg_sano", f"""
        import {LOG_MODULE}
        def on_startup():
            {LOG_MODULE}.EVENTS.append("sano")
    """)
    with TestClient(cargar_app(f"{roto},{sano}")):
        assert eventos.count("sano") == 1


def test_dos_paquetes_corren_en_el_orden_de_la_variable(tmp_path, eventos, cargar_app):
    cuerpo = """
        import {log}
        def on_startup():
            {log}.EVENTS.append("{name}")
    """
    a = _paquete(tmp_path, "s16_pkg_uno", cuerpo.format(log=LOG_MODULE, name="uno"))
    b = _paquete(tmp_path, "s16_pkg_dos", cuerpo.format(log=LOG_MODULE, name="dos"))
    with TestClient(cargar_app(f"{b}, {a}")):
        assert [e for e in eventos if e in ("uno", "dos")] == ["dos", "uno"]


def test_canario_el_on_startup_de_un_router_incluido_no_corre_bajo_lifespan(tmp_path, eventos, cargar_app):
    """Por qué existe S16: con la FastAPI fijada (`backend/requirements.txt:1`, 0.111.0) un
    `APIRouter(on_startup=[…])` montado por S1 NO corre cuando la app tiene `lifespan`. Si una actualización de
    FastAPI hace fallar este caso (en 0.135 sí corre, research R28), se revisa el caso, no la costura: S16 no
    depende de ese comportamiento."""
    pkg = _write(tmp_path, "s16_pkg_canario", f"""
        import {LOG_MODULE}
        from fastapi import APIRouter
        def get_routers():
            r = APIRouter(on_startup=[lambda: {LOG_MODULE}.EVENTS.append("router:on_startup")])
            return [(r, "/api/v1/s16-canario")]
    """)
    with TestClient(cargar_app(pkg)):
        assert "router:on_startup" not in eventos
