"""057 T077 (FR-046): aprovechamiento de la caché por destino en el comparador de costos.

Cada fila redirigida puede llevar `cache_read_tokens` / `cache_write_tokens` en `routing_decision.extensions.redirect` (los pone
el plugin con el `usage` del destino). Por destino se suman, junto con la entrada total, y el aprovechamiento es la parte de la
entrada que salió de la caché. La entrada total depende del formato en que informó el destino: la cara Claude usa el formato de
Anthropic (`input_tokens` NO incluye la caché: total = entrada + lectura + escritura); el resto usa el de OpenAI
(`prompt_tokens` YA incluye la caché). Solo cuentan las filas donde el destino informó la caché."""
import pytest

from sentinel.redirect import costs
from sentinel.tests.unit.test_redirect_costs import DESTS, PUBLISHED, price, row


def _con_cache(read, write=None, **kw):
    r = row(**kw)
    block = r["routing_decision"]["extensions"]["redirect"]
    if read is not None:
        block["cache_read_tokens"] = read
    if write is not None:
        block["cache_write_tokens"] = write
    return r


def _dest(rows, dest="d1"):
    out = costs.compare(rows, published=PUBLISHED, destinations=DESTS, price=price)
    return next(d for d in out["by_destination"] if d["destination_id"] == dest)


def test_formato_anthropic_la_entrada_total_suma_la_cache():
    d = _dest([_con_cache(600, 100, face="claude", prompt=300)])         # total = 300 + 600 + 100 = 1000
    assert (d["input_tokens"], d["cache_read_tokens"], d["cache_write_tokens"]) == (1000, 600, 100)
    assert d["cache_hit_rate"] == pytest.approx(0.6)


def test_formato_openai_el_prompt_ya_incluye_la_cache():
    d = _dest([_con_cache(600, None, face="openai_generic", public_id="pro", prompt=1000)])
    assert d["input_tokens"] == 1000 and d["cache_hit_rate"] == pytest.approx(0.6)


def test_se_suman_los_pedidos_del_destino_y_solo_cuentan_los_que_informaron_cache():
    d = _dest([_con_cache(800, 0, face="claude", prompt=200), _con_cache(0, 500, face="claude", prompt=500),
               _con_cache(None, None, face="claude", prompt=99999)])
    assert d["cache_requests"] == 2 and d["input_tokens"] == 2000
    assert d["cache_read_tokens"] == 800 and d["cache_hit_rate"] == pytest.approx(0.4)


def test_sin_filas_con_cache_informada_no_hay_tasa():
    d = _dest([_con_cache(None, None)])
    assert d["cache_requests"] == 0 and d["cache_hit_rate"] is None and d["cache_read_tokens"] == 0


@pytest.mark.parametrize("valor", ["x", -5, True, 1.5])
def test_valores_invalidos_se_ignoran(valor):
    d = _dest([_con_cache(valor, None, face="claude", prompt=100)])
    assert d["cache_requests"] == 0 and d["cache_hit_rate"] is None


def test_es_por_destino_y_los_totales_no_cambian():
    rows = [_con_cache(600, 100, face="claude", prompt=300), _con_cache(10, None, face="claude", prompt=90, dest="d2")]
    out = costs.compare(rows, published=PUBLISHED, destinations=DESTS, price=price)
    assert {d["destination_id"]: d["cache_read_tokens"] for d in out["by_destination"]} == {"d1": 600, "d2": 10}
    assert "cache_read_tokens" not in out["totals"]
