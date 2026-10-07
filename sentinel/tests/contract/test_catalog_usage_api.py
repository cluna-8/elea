"""`GET /api/v1/catalog/usage` (069 T130; FR-054, FR-055; research D29).

La agregación es una función pura (`aggregate`); la ruta se prueba con un `FETCH` inyectado (la
tabla `audit_logs` es de la base y usa tipos de Postgres). Corre con el venv del backend.
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
pytest.importorskip("src.auth.rbac", reason="requiere el venv del backend")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.auth.session import get_current_user  # noqa: E402
from src.plugins import mount_plugin_routers  # noqa: E402

from sentinel.catalog import models as cm  # noqa: E402
from sentinel.catalog.api import admin, usage  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")


def row(model="glm", p=100, c=50, cost=0.01, lat=100, dest=None, purpose=None, **kw):
    rd = None
    if dest:
        rd = {"extensions": {"redirect": {"destination_id": dest[0], "destination_name": dest[1]}}}
    return {"model": model, "prompt_tokens": p, "completion_tokens": c, "cost_usd": cost,
            "latency_ms": lat, "routing_decision": rd, "processing_purpose": purpose, **kw}


# ── agregación pura ───────────────────────────────────────────────────────────

def test_agrupa_por_modelo_con_tokens_de_salida_y_latencia():
    out = usage.aggregate([row(lat=100), row(lat=300, p=10, c=5, cost=0.02), row(model="otro")], "model")
    glm = next(g for g in out["data"] if g["key"] == "glm")
    assert (glm["requests"], glm["prompt_tokens"], glm["completion_tokens"]) == (2, 110, 55)
    assert glm["cost_usd"] == pytest.approx(0.03)
    assert glm["latency_avg_ms"] == 200 and glm["latency_p95_ms"] == 300
    assert glm["billing"] == "measured"
    assert out["totals"]["requests"] == 3


def test_p95_nearest_rank():
    assert usage.p95([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == 10
    assert usage.p95(list(range(1, 101))) == 95
    assert usage.p95([7]) == 7 and usage.p95([]) == 0


def test_destino_real_por_routing_decision_y_cae_a_modelo():
    rows = [row(model="alias", dest=("d1", "GLM UE")), row(model="alias", dest=("d1", "GLM UE")),
            row(model="alias")]
    out = usage.aggregate(rows, "destination")
    by = {g["key"]: g for g in out["data"]}
    assert by["d1"]["name"] == "GLM UE" and by["d1"]["requests"] == 2
    assert by["alias"]["requests"] == 1
    # agrupado por modelo ignora el destino
    assert [g["key"] for g in usage.aggregate(rows, "model")["data"]] == ["alias"]


def test_suscripcion_es_tarifa_plana_y_no_suma_costo_medido():
    rows = [row(model="claude", cost=0.0, purpose="coding-assistant", p=1000, c=500),
            row(model="claude", cost=0.05)]
    out = usage.aggregate(rows, "model")
    flat = next(g for g in out["data"] if g["billing"] == "flat")
    meas = next(g for g in out["data"] if g["billing"] == "measured")
    assert flat["requests"] == 1 and flat["cost_usd"] == 0 and flat["completion_tokens"] == 500
    assert meas["cost_usd"] == pytest.approx(0.05)
    assert out["totals"]["cost_usd"] == pytest.approx(0.05)
    assert out["totals"]["flat_requests"] == 1


def test_routing_decision_malformado_no_rompe():
    r = row()
    r["routing_decision"] = {"extensions": "x"}
    assert usage.aggregate([r], "destination")["data"][0]["key"] == "glm"


def test_la_salida_no_lleva_contenido():
    out = usage.aggregate([row(prompt="secreto", messages=["hola"])], "model")
    assert "secreto" not in str(out) and "hola" not in str(out)


def test_consulta_por_defecto_filtra_tenant_tipo_y_rango():
    sql = str(usage._default_query(T1, datetime(2026, 9, 1), datetime(2026, 10, 1))
              .compile(compile_kwargs={"literal_binds": False}))
    assert "audit_logs.tenant_id" in sql and "audit_logs.event_type" in sql
    assert "audit_logs.timestamp >=" in sql and "audit_logs.timestamp <=" in sql


# ── ruta ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    cm.CatalogBase.metadata.create_all(engine)
    rm.RedirectBase.metadata.create_all(engine)
    monkeypatch.setattr(admin, "SESSION_FACTORY", sessionmaker(bind=engine))
    calls = []
    data = {T1: [row(model="a", cost=1.0), row(model="a", cost=1.0, dest=("d", "Dest"))],
            T2: [row(model="b", cost=99.0)]}

    def fetch(db, tenant, start, end):
        calls.append((tenant, start, end))
        return data[tenant]
    monkeypatch.setattr(usage, "FETCH", fetch)
    monkeypatch.setattr(usage, "NOW", lambda: datetime(2026, 10, 1, tzinfo=timezone.utc))
    app = FastAPI()
    assert mount_plugin_routers(app, "sentinel.catalog.api") == 6
    who = {}
    app.dependency_overrides[get_current_user] = lambda: who["u"]
    client = TestClient(app)

    def call(role, tenant=T1, qs=""):
        who["u"] = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, role=role, display_label=None) \
            if role else None
        return client.get("/api/v1/catalog/usage" + qs)
    return SimpleNamespace(call=call, calls=calls)


def test_roles(api):
    assert api.call(None).status_code == 401
    assert api.call("client").status_code == 403
    for r in ("tenant_admin", "compliance_officer", "lectura"):
        assert api.call(r).status_code == 200


def test_filtra_por_tenant_de_la_sesion(api):
    d = api.call("tenant_admin", T1).json()
    assert {g["key"] for g in d["data"]} == {"a"} and d["totals"]["cost_usd"] == pytest.approx(2.0)
    d2 = api.call("tenant_admin", T2).json()
    assert {g["key"] for g in d2["data"]} == {"b"}
    assert [c[0] for c in api.calls] == [T1, T2]


def test_rango_por_defecto_30_dias_y_parametros(api):
    d = api.call("lectura").json()
    assert d["group"] == "model" and d["to"].startswith("2026-10-01") and d["from"].startswith("2026-09-01")
    d = api.call("lectura", qs="?from=2026-09-10&to=2026-09-20&group=destination").json()
    assert d["from"].startswith("2026-09-10") and d["group"] == "destination"
    assert {g["key"] for g in d["data"]} == {"a", "d"}


def test_parametros_invalidos(api):
    assert api.call("lectura", qs="?group=otro").status_code == 422
    assert api.call("lectura", qs="?from=ayer").status_code == 422
    assert api.call("lectura", qs="?from=2026-10-02&to=2026-10-01").status_code == 422
