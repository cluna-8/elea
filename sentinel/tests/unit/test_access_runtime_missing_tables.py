"""Sin las tablas de acceso (migración sin aplicar) no hay política: nada se corta (069 US2)."""
from sentinel.access import runtime


class _Orig(Exception):
    pass


def test_tablas_ausentes_no_dejan_la_instalacion_sin_modelos(monkeypatch):
    def boom(tenant_id):
        raise RuntimeError('relation "ext_access_profile" does not exist')
    monkeypatch.setattr(runtime.snap, "load", lambda db, t: boom(t))
    monkeypatch.setattr(runtime, "session", lambda t: __import__("contextlib").nullcontext(None))
    s = runtime._load("t1")
    assert s.profiles == {} and s.ceilings == {} and s.assignments == {}


def test_otra_falla_sigue_siendo_fail_closed(monkeypatch):
    import pytest

    def boom(db, t):
        raise RuntimeError("conexión rota")
    monkeypatch.setattr(runtime.snap, "load", boom)
    monkeypatch.setattr(runtime, "session", lambda t: __import__("contextlib").nullcontext(None))
    with pytest.raises(RuntimeError):
        runtime._load("t1")
