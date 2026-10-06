"""Invalidación ≤ 60 s sin reemitir llaves (069 T045; FR-014): la versión cambia con cada escritura y un
segundo proceso (otro `SnapshotVersion` sobre el mismo Redis) ve el cambio."""
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
pytest.importorskip("src.database", reason="requiere el venv del backend")
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from sentinel.access import models as am  # noqa: E402
from sentinel.access import runtime as rt  # noqa: E402
from sentinel.access import snapshot as snap  # noqa: E402
from sentinel.access.resolver import PermitidosNoResueltos  # noqa: E402
from sentinel.common.snapshot_version import SnapshotCache, SnapshotVersion  # noqa: E402

T1 = str(uuid.UUID("11111111-1111-1111-1111-111111111111"))


class FakeRedis:
    def __init__(self):
        self.d = {}

    def incr(self, k):
        self.d[k] = int(self.d.get(k, 0)) + 1

    def mget(self, *ks):
        return [self.d.get(k) for k in ks]


def E(pid, estado):
    return {"id": f"id-{pid}", "public_id": pid, "name": pid, "provider": "x", "capability": "standard",
            "semaforo": {"estado": estado}, "jurisdiccion": "EU"}


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    am.AccessBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    redis = FakeRedis()
    v_a = SnapshotVersion("access", redis_factory=lambda: redis)
    v_b = SnapshotVersion("access", redis_factory=lambda: redis)        # «otro proceso»
    monkeypatch.setattr(rt, "SESSION_FACTORY", Session)
    monkeypatch.setattr(rt, "VERSION", v_a)
    monkeypatch.setattr(rt, "ENTRIES", lambda tenant: [E("a", "eu_ok"), E("b", "standard")])
    return Session, v_a, v_b


def _assign_ue(Session):
    with Session() as db:
        snap.ensure_seed(db, T1)
        ue = db.query(am.AccessProfile).filter_by(name="Solo admisibles UE").one()
        db.add(am.AccessAssignment(tenant_id=uuid.UUID(T1), profile_id=ue.id, subject_type="tenant",
                                   subject_id=uuid.UUID(T1)))
        db.commit()


def test_cada_escritura_cambia_la_version_y_otro_proceso_la_ve(env):
    Session, v_a, v_b = env
    antes = v_b.current(T1)
    rt.bump(T1)
    assert v_b.current(T1) != antes
    mas = v_b.current(T1)
    rt.bump(T1)
    assert v_b.current(T1) != mas


def test_la_cache_de_otro_proceso_se_invalida_sin_esperar_el_ttl(env):
    Session, v_a, v_b = env
    loads = []
    cache_b = SnapshotCache(v_b, lambda t: loads.append(1) or snap.load(Session(), t), ttl=3600)
    assert cache_b.get(T1).assignments == {} and len(loads) == 1
    cache_b.get(T1)
    assert len(loads) == 1                                  # sirvió de caché
    _assign_ue(Session)
    rt.bump(T1)                                             # el proceso A escribió
    assert ("tenant", T1) in cache_b.get(T1).assignments and len(loads) == 2


def test_la_fachada_ve_la_politica_nueva_despues_del_bump(env):
    Session, *_ = env
    assert rt.allowed_public_ids(T1, user_risk="minimal") is None            # sin política
    _assign_ue(Session)
    assert rt.allowed_public_ids(T1, user_risk="minimal") is None            # aún cacheado (TTL corto)
    rt.bump(T1)
    assert rt.allowed_public_ids(T1, user_risk="minimal") == frozenset({"a"})


def test_la_fachada_levanta_si_falla_la_base_o_el_catalogo(env, monkeypatch):
    def boom(tenant):
        raise RuntimeError("catálogo caído")
    monkeypatch.setattr(rt, "ENTRIES", boom)
    with pytest.raises(PermitidosNoResueltos):
        rt.allowed_public_ids(T1)


def test_la_fachada_levanta_si_la_instantanea_no_carga(env, monkeypatch):
    Session, *_ = env
    monkeypatch.setattr(rt, "SESSION_FACTORY", lambda: (_ for _ in ()).throw(RuntimeError("sin base")))
    rt.bump("otra-org-sin-cache")
    with pytest.raises(PermitidosNoResueltos):
        rt.allowed_public_ids(str(uuid.uuid4()))


def test_perfiles_sembrados_idempotentes_y_no_se_asignan(env):
    Session, *_ = env
    with Session() as db:
        assert snap.ensure_seed(db, T1) is True
        assert snap.ensure_seed(db, T1) is False
        db.commit()
        assert {p.name for p in db.query(am.AccessProfile)} == {"Todos salvo bloqueados", "Solo admisibles UE"}
        assert db.query(am.AccessAssignment).count() == 0
        assert snap.load(db, T1).assignments == {}
