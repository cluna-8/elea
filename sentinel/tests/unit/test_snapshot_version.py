"""Versión de instantánea por organización (069 T012; D6, FR-014: cambios visibles ≤ 60 s)."""
from sentinel.common.snapshot_version import SnapshotCache, SnapshotVersion


class FakeRedis:
    def __init__(self):
        self.d = {}

    def incr(self, k):
        self.d[k] = int(self.d.get(k, 0)) + 1

    def mget(self, *ks):
        return [self.d.get(k) for k in ks]


def test_claves_por_clase_y_organizacion():
    v = SnapshotVersion("catalog", redis_factory=lambda: None)
    assert v.key("t1") == "ext:catalog:v:t1"
    assert SnapshotVersion("access", redis_factory=lambda: None).key("t1") == "ext:access:v:t1"
    assert v.key(None) == "ext:catalog:v:*"


def test_bump_cambia_la_version_de_esa_organizacion():
    r = FakeRedis()
    v = SnapshotVersion("catalog", redis_factory=lambda: r)
    antes = v.current("t1")
    v.bump("t1")
    assert v.current("t1") != antes
    assert r.d["ext:catalog:v:t1"] == 1


def test_bump_de_otro_proceso_se_ve_por_redis():
    r = FakeRedis()
    a = SnapshotVersion("catalog", redis_factory=lambda: r)
    b = SnapshotVersion("catalog", redis_factory=lambda: r)
    antes = a.current("t1")
    b.bump("t1")                                   # otro worker
    assert a.current("t1") != antes


def test_bump_global_invalida_a_todas():
    r = FakeRedis()
    v = SnapshotVersion("catalog", redis_factory=lambda: r)
    antes = v.current("t1")
    v.bump(None)                                   # cambio de nivel instalación
    assert v.current("t1") != antes


def test_sin_redis_rige_el_contador_local():
    v = SnapshotVersion("catalog", redis_factory=lambda: None)
    antes = v.current("t1")
    v.bump("t1")
    assert v.current("t1") != antes


def test_redis_caido_no_rompe():
    class Roto:
        def mget(self, *a):
            raise ConnectionError

        def incr(self, *a):
            raise ConnectionError
    v = SnapshotVersion("catalog", redis_factory=lambda: Roto())
    v.bump("t1")
    assert v.current("t1") is not None


def test_cache_sirve_hasta_el_ttl_y_se_invalida_con_bump():
    t = {"now": 0.0}
    cargas = []
    ver = SnapshotVersion("catalog", redis_factory=lambda: None)
    c = SnapshotCache(ver, lambda tid: cargas.append(tid) or {"n": len(cargas)}, ttl=5.0,
                      clock=lambda: t["now"])
    assert c.get("t1") == {"n": 1}
    assert c.get("t1") == {"n": 1} and len(cargas) == 1
    ver.bump("t1")
    assert c.get("t1") == {"n": 2}
    t["now"] = 6.0                                  # vence el TTL
    assert c.get("t1") == {"n": 3}


def test_cache_de_una_organizacion_no_se_mezcla_con_otra():
    ver = SnapshotVersion("catalog", redis_factory=lambda: None)
    c = SnapshotCache(ver, lambda tid: {"t": tid}, ttl=5.0)
    assert c.get("a") == {"t": "a"} and c.get("b") == {"t": "b"}
