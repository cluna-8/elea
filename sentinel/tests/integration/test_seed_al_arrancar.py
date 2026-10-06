"""T095 (057 QA B2, QA v2 N1, M3; FR-031; research R28, R33): los seeds se cargan al arrancar por la costura S16.

Contra `src.main:app` con su `lifespan` REAL (`TestClient` como gestor de contexto; nunca un `FastAPI()` suelto), con
`PLUGIN_PACKAGES=sentinel.redirect.api,sentinel.catalog.api` y `REDIRECT_SEED_FILES`. Las filas de región y de reglas
de habilitación existen **antes del primer pedido** y `GET /api/v1/redirect/health` da 200 al primer intento; el
arranque es idempotente y seguro ante dos workers; un archivo inválido se registra y rige el respaldo de T094.

Sin Postgres ni Docker (el backend corre con `RUN_ALEMBIC_ON_STARTUP=false`): las tablas las crea el fixture sobre
SQLite con las dos metadatas, no `alembic upgrade heads`. El cerrojo consultivo de Postgres se prueba con un doble de
la sesión; la corrida real con dos workers y las migraciones por `heads` son de la suite 🐳 (T065)."""
import importlib
import logging
import sys
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from sentinel.catalog import models as cm  # noqa: E402
from sentinel.redirect import models as m  # noqa: E402
from sentinel.redirect import seed_on_startup  # noqa: E402
from sentinel.redirect.api import admin  # noqa: E402

SEEDS = ROOT / "deploy" / "redirect-seeds"
REGIONS = SEEDS / "regions.americas.yaml"
HABILITACION = SEEDS / "habilitacion-explicita.yaml"
PAQUETES = "sentinel.redirect.api,sentinel.catalog.api"


@pytest.fixture
def base(monkeypatch, tmp_path):
    """SQLite con las dos metadatas, compartida por el seed, la API y el test."""
    engine = create_engine(f"sqlite:///{tmp_path / 'seed.db'}", connect_args={"check_same_thread": False})
    m.RedirectBase.metadata.create_all(engine)
    cm.CatalogBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(seed_on_startup, "SESSION_FACTORY", Session)
    monkeypatch.setattr(admin, "SESSION_FACTORY", Session)
    monkeypatch.setenv("RUN_ALEMBIC_ON_STARTUP", "false")
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "latam_ar")
    monkeypatch.setenv("PLUGIN_PACKAGES", PAQUETES)
    monkeypatch.delenv("REDIRECT_SEED_FILES", raising=False)
    return Session


@pytest.fixture
def cargar_app(monkeypatch):
    from src import main

    def _cargar():
        return importlib.reload(main).app

    yield _cargar
    monkeypatch.delenv("PLUGIN_PACKAGES", raising=False)
    importlib.reload(main)                         # la app que ven los demás tests vuelve a ser la del core


def _regiones(Session):
    with Session() as s:
        return [(r.name, r.default_posture) for r in s.query(m.RedirectRegion)]


def _reglas(Session):
    with Session() as s:
        return sorted((r.kind, r.value) for r in s.query(cm.EnablementRule))


# ── al arrancar ─────────────────────────────────────────────────────────────────────────────────────

def test_las_filas_existen_antes_del_primer_pedido_y_health_da_200_al_primer_intento(base, cargar_app, monkeypatch):
    monkeypatch.setenv("REDIRECT_SEED_FILES", f"{REGIONS},{HABILITACION}")
    with TestClient(cargar_app()) as client:
        assert _regiones(base) == [("AMERICAS", "masked_all")]          # ya sembrada al entrar, sin pedido alguno
        r = client.get("/api/v1/redirect/health")
        assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_sin_seed_el_arranque_no_hace_nada_y_health_informa_el_respaldo(base, cargar_app):
    with TestClient(cargar_app()) as client:
        assert _regiones(base) == []
        r = client.get("/api/v1/redirect/health")
        assert r.status_code == 503 and r.json() == {"status": "degraded", "reason": "region_row_missing"}


def test_dos_arranques_seguidos_no_duplican_filas(base, cargar_app, monkeypatch):
    monkeypatch.setenv("REDIRECT_SEED_FILES", f"{REGIONS},{HABILITACION}")
    for _ in range(2):
        with TestClient(cargar_app()):
            pass
    assert _regiones(base) == [("AMERICAS", "masked_all")]
    with base() as s:
        assert s.query(m.RedirectConfigAudit).filter_by(entity="region").count() == 1


def test_dos_arranques_simultaneos_tampoco_duplican(base, monkeypatch):
    monkeypatch.setenv("REDIRECT_SEED_FILES", f"{REGIONS},{HABILITACION}")
    errores, listo = [], threading.Barrier(2)

    def arrancar():
        try:
            listo.wait()
            seed_on_startup.on_startup()
        except Exception as exc:  # noqa: BLE001
            errores.append(exc)

    hilos = [threading.Thread(target=arrancar) for _ in range(2)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert errores == [] and _regiones(base) == [("AMERICAS", "masked_all")]


def test_la_siembra_toma_el_cerrojo_consultivo_de_postgres():
    """El doble de una sesión de Postgres: `pg_advisory_xact_lock` antes de cualquier alta (QA v2 M3)."""
    class Dialect:
        name = "postgresql"

    class Bind:
        dialect = Dialect()

    class FakeDb:
        def __init__(self):
            self.sql = []

        def get_bind(self):
            return Bind()

        def execute(self, stmt, params=None):
            self.sql.append((str(stmt), params))

    db = FakeDb()
    seed_on_startup._take_lock(db)
    assert len(db.sql) == 1 and "pg_advisory_xact_lock" in db.sql[0][0] and db.sql[0][1]["k"] == seed_on_startup.ADVISORY_KEY


def test_sin_postgres_no_hay_cerrojo_que_tomar(base):
    with base() as s:
        seed_on_startup._take_lock(s)               # SQLite: no hace nada ni falla


# ── reglas de habilitación ──────────────────────────────────────────────────────────────────────────

def test_las_reglas_de_habilitacion_se_siembran_y_el_seed_de_eleia_las_deja_vacias(base, cargar_app, monkeypatch):
    monkeypatch.setenv("REDIRECT_SEED_FILES", f"{REGIONS},{HABILITACION}")
    with TestClient(cargar_app()):
        assert _reglas(base) == []                  # D1: sin bloqueo por defecto en Eleia


def test_un_seed_de_habilitacion_con_reglas_se_carga_y_re_evalua(base, tmp_path, monkeypatch):
    f = tmp_path / "hab.yaml"
    f.write_text("providers: [deepseek]\napi_hosts: []\njurisdictions: []\n", encoding="utf-8")
    monkeypatch.setenv("REDIRECT_SEED_FILES", str(f))
    seed_on_startup.on_startup()
    seed_on_startup.on_startup()
    assert _reglas(base) == [("provider", "deepseek")]


# ── archivos inválidos ──────────────────────────────────────────────────────────────────────────────

def test_un_archivo_invalido_se_registra_y_rige_el_respaldo(base, cargar_app, monkeypatch, tmp_path, caplog):
    malo = tmp_path / "regiones-malas.yaml"
    malo.write_text("regions:\n  - {name: X, level: installation, default_posture: nunca, jurisdictions: [US]}\n",
                    encoding="utf-8")
    monkeypatch.setenv("REDIRECT_SEED_FILES", str(malo))
    with caplog.at_level(logging.ERROR), TestClient(cargar_app()) as client:
        assert _regiones(base) == []
        r = client.get("/api/v1/redirect/health")
        assert r.status_code == 503 and r.json()["reason"] == "region_row_missing"
    assert "regiones-malas.yaml" in caplog.text and "default_posture" in caplog.text


def test_un_archivo_invalido_no_frena_a_los_demas(base, monkeypatch, tmp_path):
    malo = tmp_path / "malo.yaml"
    malo.write_text("esto: no es un seed\n", encoding="utf-8")
    monkeypatch.setenv("REDIRECT_SEED_FILES", f"{malo},{REGIONS}")
    seed_on_startup.on_startup()
    assert _regiones(base) == [("AMERICAS", "masked_all")]


def test_un_archivo_inexistente_se_registra_y_sigue(base, monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("REDIRECT_SEED_FILES", f"{tmp_path / 'no-existe.yaml'},{REGIONS}")
    with caplog.at_level(logging.ERROR):
        seed_on_startup.on_startup()
    assert _regiones(base) == [("AMERICAS", "masked_all")] and "no-existe.yaml" in caplog.text


# ── el enganche es el del paquete de la extensión ───────────────────────────────────────────────────

def test_sentinel_redirect_api_expone_on_startup_y_el_catalogo_no_lo_necesita():
    import sentinel.catalog.api as catalog_api
    import sentinel.redirect.api as redirect_api
    assert redirect_api.on_startup() == seed_on_startup.on_startup()
    assert getattr(catalog_api, "on_startup", None) is None


def test_los_archivos_se_separan_por_comas_o_saltos_de_linea(monkeypatch):
    monkeypatch.setenv("REDIRECT_SEED_FILES", " a.yaml , b.yaml\nc.yaml,, ")
    assert seed_on_startup.seed_files() == ["a.yaml", "b.yaml", "c.yaml"]
    monkeypatch.setenv("REDIRECT_SEED_FILES", "")
    assert seed_on_startup.seed_files() == []
    monkeypatch.delenv("REDIRECT_SEED_FILES")
    assert seed_on_startup.seed_files() == []
