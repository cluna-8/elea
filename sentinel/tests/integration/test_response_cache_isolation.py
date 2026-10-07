"""057 T071 (FR-048; research R20; T127 de Sentinel): la caché de RESPUESTAS del motor (Redis, `litellm/config.yaml`) no
devuelve una respuesta generada por otro destino ni con los marcadores de otra conversación.

Se usa la caché real de `litellm` (en memoria) con lo que el guard fija en cada pedido (`cache`): el `namespace` liga alcance,
destino, modelo, proveedor y base; un pedido con mapa de enmascarado se salta la caché (lectura y escritura). Con la costura
S13 los marcadores de dos conversaciones son distintos, así que ni siquiera comparten la clave. Es independiente de la caché
del PROVEEDOR (la del prefijo de entrada), que el guard no toca."""
import json

import pytest

from sentinel.engine import redirect_guard as g
from sentinel.redirect import authz

litellm_caching = pytest.importorskip("litellm.caching.caching")

KEY = "k" * 48
MENSAJES = [{"role": "user", "content": "¿Cuánto es 2+2?"}]
SIN_MAPA = {"completed": True, "degraded": False, "detected": 0, "masked": 0, "unanalyzable": 0, "scope": "user"}
CON_MAPA = {**SIN_MAPA, "detected": 2, "masked": 2}


def _grant(destino="d1", provider="openai_compatible", scope="t1/connection:k1", api_base="http://d.local/v1"):
    family = g.credentials.PROVIDER_FAMILY[provider]
    model = family + "/qwen"
    tok = authz.issue(request_id="r", scope=scope, destination_id=destino, model=model, provider=provider,
                      credential={"api_key": "sk-d"}, api_base=api_base, decision={"public_id": "pro"}, key=KEY)
    return authz.verify(tok, key=KEY)


def _cache_de(grant, report):
    return g.cache_control(grant, report)


def _clave(cache, grant, mensajes):
    c = litellm_caching.Cache(type="local")
    return c.get_cache_key(model=grant.model, messages=mensajes, cache=cache), c


def test_un_destino_distinto_no_comparte_la_respuesta_aunque_el_pedido_sea_identico():
    a, b = _grant("d1"), _grant("d2")
    ka, cache = _clave(_cache_de(a, SIN_MAPA), a, MENSAJES)
    kb, _ = _clave(_cache_de(b, SIN_MAPA), b, MENSAJES)
    assert ka != kb
    cache.cache.set_cache(ka, "respuesta del destino 1")
    assert cache.cache.get_cache(kb) is None and cache.cache.get_cache(ka) == "respuesta del destino 1"


@pytest.mark.parametrize("cambio", [{"provider": "openrouter"}, {"api_base": "http://otro.local/v1"},
                                    {"scope": "t2/connection:k1"}, {"scope": "t1/connection:k2"}])
def test_otro_alcance_proveedor_o_base_tampoco_la_comparte(cambio):
    a = _grant()
    b = _grant(**cambio)
    if "provider" in cambio:
        b = _grant(provider="openrouter")
    assert _cache_de(a, SIN_MAPA)["namespace"] != _cache_de(b, SIN_MAPA)["namespace"]


def test_un_pedido_con_mapa_de_enmascarado_se_salta_la_cache_en_lectura_y_escritura():
    cache = _cache_de(_grant(), CON_MAPA)
    assert cache == {"no-cache": True, "no-store": True}


@pytest.mark.parametrize("informe", [None, "x", {}, {**SIN_MAPA, "completed": False}, {**SIN_MAPA, "degraded": True},
                                     {**SIN_MAPA, "detected": 1, "masked": 0}])
def test_ante_la_duda_sobre_el_mapa_no_se_cachea(informe):
    assert _cache_de(_grant(), informe) == {"no-cache": True, "no-store": True}


def test_dos_conversaciones_con_marcadores_derivados_no_comparten_clave_ni_respuesta():
    """S13: el mismo dato en dos conversaciones sale con otro sufijo; la clave de caché (que incluye el cuerpo enmascarado)
    es otra, y de todos modos el pedido con mapa se salta la caché."""
    from extensions import sentinel_guardian_policy as policy
    a = policy.PlaceholderMap.for_conversation("k" * 48, tenant="t1", key_id="k1", ref="conv-a")
    b = policy.PlaceholderMap.for_conversation("k" * 48, tenant="t1", key_id="k1", ref="conv-b")
    ma = [{"role": "user", "content": f"Mi DNI es {a.placeholder_for('30.123.456', 'DNI')}"}]
    mb = [{"role": "user", "content": f"Mi DNI es {b.placeholder_for('30.123.456', 'DNI')}"}]
    grant = _grant()
    ka, _ = _clave({"namespace": "rdx:x"}, grant, ma)
    kb, _ = _clave({"namespace": "rdx:x"}, grant, mb)
    assert ka != kb
    assert _cache_de(grant, CON_MAPA) == {"no-cache": True, "no-store": True}


def test_lo_que_manda_el_cliente_en_cache_se_reemplaza_entero():
    grant = _grant()
    tok = authz.issue(request_id="r", scope=grant.scope, destination_id="d1", model=grant.model, provider=grant.provider,
                      credential={"api_key": "sk-d"}, api_base=grant.api_base, decision={"public_id": "pro"}, key=KEY)
    data = {"model": grant.model, "messages": MENSAJES, "cache": {"namespace": "del-cliente", "ttl": 99999, "use-cache": True},
            "proxy_server_request": {"headers": {authz.HEADER: tok}}, "metadata": {"masking_report": SIN_MAPA}}
    out = g.apply_redirect(data, key=KEY, call_type="completion", environ={})
    assert out["cache"]["namespace"].startswith("rdx:") and "ttl" not in out["cache"]
    assert "del-cliente" not in json.dumps(out["cache"])
