"""Validación de `limits` y `advanced` de la entrada (069 T126; FR-051, FR-052)."""
import pytest

from sentinel.catalog import validation as v


def test_limits_validos_y_vacio():
    assert v.check_limits({}) == {}
    ok = {"rpm": 60, "tpm": 100000, "max_parallel_requests": 4, "timeout": 30, "num_retries": 0}
    assert v.check_limits(ok) == ok


@pytest.mark.parametrize("bad", [{"foo": 1}, {"rpm": -1}, {"rpm": 1.5}, {"rpm": "10"}, {"timeout": True},
                                 {"num_retries": None}, [], "x"])
def test_limits_invalidos(bad):
    with pytest.raises(ValueError):
        v.check_limits(bad)


def test_advanced_admitido():
    ok = {"max_tokens": 4096, "temperature": 0.2, "stream_timeout": 15,
          "extra_headers": {"X-Equipo": "datos"}}
    assert v.check_advanced(ok) == ok
    assert v.ADVANCED_KEYS == ("extra_headers", "max_tokens", "stream_timeout", "temperature")


@pytest.mark.parametrize("bad", [
    {"top_p": 0.9}, {"organization": "org-1"}, {"max_tokens": 0}, {"temperature": 3}, {"temperature": "x"},
    {"stream_timeout": -1}, {"extra_headers": "x"}, {"extra_headers": {"Authorization": "x"}},
    {"extra_headers": {"x-api-key": "x"}}, {"extra_headers": {"Api-Key": "x"}},
    {"extra_headers": {"X-Tok": "Bearer abc.def"}}, {"extra_headers": {"X-Otro": "sk-abcdefghijklmnop1234"}},
    {"extra_headers": {"X-Secret-Token": "ok"}}, {"extra_headers": {"A": 1}}, [],
])
def test_advanced_rechazado(bad):
    with pytest.raises(ValueError):
        v.check_advanced(bad)


def test_advanced_nunca_repite_el_valor_en_el_error():
    with pytest.raises(ValueError) as e:
        v.check_advanced({"extra_headers": {"X-Otro": "sk-abcdefghijklmnop1234"}})
    assert "sk-abcdefghijklmnop1234" not in str(e.value)


def test_tramos_de_precio():
    ok = [{"up_to_tokens": 200000, "input": 3e-6, "output": 1.5e-5}, {"input": 6e-6, "output": 2.25e-5}]
    assert v.check_tiers(ok) == ok
    assert v.check_tiers(None) is None
    for bad in ([{"input": -1}], [{"foo": 1}], "x", [{"up_to_tokens": 0, "input": 1}], [{"input": "a"}]):
        with pytest.raises(ValueError):
            v.check_tiers(bad)
