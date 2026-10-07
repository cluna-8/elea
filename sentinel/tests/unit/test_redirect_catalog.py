"""Guard del motor: clientes que le hablan DIRECTO sirven del catálogo (069 T033, D2; spike S1 e).

Hub, tabular y presentaciones piden un id público del catálogo; el guard lo reescribe a la familia
comodín con la credencial y la base de la entrada, sin tocar el motor. Apagado por defecto (el
backend dice `direct: false`); fail-closed si la entrada existe pero su credencial no se obtiene."""
import json
from types import SimpleNamespace

import pytest

from sentinel.engine import redirect_catalog as rc
from sentinel.engine.redirect_guard import GuardRejection

T1 = "11111111-1111-1111-1111-111111111111"
ENTRY = {"entry_id": "e1", "name": "GLM", "provider": "zai", "real_model": "glm-4.6", "api_base": None,
         "protocol_family": "openai_chat", "level": "tenant",
         "semaforo": {"estado": "standard", "motivos": ["sin_dpa"]}, "jurisdiccion": "unknown",
         "price": {"input": 2e-7, "output": 8e-7, "source": None, "at": None}}


class Backend:
    def __init__(self, direct=True, entries=None, cred=None, down=False, cred_status=200,
                 access=None, access_status=200, access_down=False):
        self.access = {"restringe": False, "permitidos": []} if access is None else access
        self.access_status, self.access_down, self.access_params = access_status, access_down, []
        self.direct, self.entries = direct, {"glm": ENTRY} if entries is None else entries
        self.cred, self.down, self.cred_status = cred if cred is not None else {"api_key": "sk-glm"}, down, cred_status
        self.calls = []

    async def __call__(self, path, params):
        self.calls.append(path)
        if self.down:
            raise ConnectionError("backend caído")
        if path.endswith("model-access"):
            self.access_params.append(dict(params))
            if self.access_down:
                raise ConnectionError("backend caído")
            return self.access_status, (self.access if self.access_status == 200 else None)
        if path.endswith("model-catalog"):
            return 200, {"version": "v1", "direct": self.direct, "entries": self.entries}
        return self.cred_status, {"credential": self.cred}


def user(tenant=T1):
    return SimpleNamespace(metadata={"sentinel": {"tenant_id": tenant}} if tenant else {})


def req(model="glm", **extra):
    return {"model": model, "messages": [{"role": "user", "content": "hola"}], **extra}


async def run(data, backend=None, u=None, environ=None, **kw):
    g = rc.CatalogDirect(fetch=backend or Backend(), environ=environ or {}, **kw)
    ok = await g.apply(data, u or user(), call_type="acompletion")
    return ok, data


async def test_modelo_del_catalogo_se_reescribe_a_la_familia_con_credencial_y_base():
    ok, d = await run(req())
    assert ok and d["model"] == "rdx-zai/glm-4.6" and d["api_key"] == "sk-glm"
    assert d["input_cost_per_token"] == pytest.approx(2e-7) and d["output_cost_per_token"] == pytest.approx(8e-7)


async def test_la_decision_queda_en_la_auditoria_sin_secretos():
    ok, d = await run(req())
    dec = d["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert dec["source"] == "catalog" and dec["destination_id"] == "e1" and dec["public_id"] == "glm"
    assert "sk-glm" not in json.dumps(d["metadata"], default=str)


async def test_anti_desvio_el_cliente_no_elige_credencial_ni_base_ni_precio():
    ok, d = await run(req(api_key="del-cliente", api_base="http://malo", input_cost_per_token=0))
    assert d["api_key"] == "sk-glm" and "api_base" not in d or d["api_base"] != "http://malo"
    assert d["input_cost_per_token"] == pytest.approx(2e-7)


async def test_apagado_por_defecto_no_toca_nada():
    ok, d = await run(req(), Backend(direct=False))
    assert not ok and d["model"] == "glm" and "api_key" not in d


async def test_modelo_fuera_del_catalogo_sigue_su_camino():
    ok, d = await run(req("gpt-4o"))
    assert not ok and d["model"] == "gpt-4o"


async def test_ids_rdx_no_se_resuelven_por_el_catalogo():
    ok, d = await run(req("rdx-zai/glm-4.6"), Backend(entries={"rdx-zai/glm-4.6": ENTRY}))
    assert not ok


async def test_sin_identidad_de_organizacion_no_se_resuelve():
    ok, _ = await run(req(), u=user(None))
    assert not ok


async def test_catalogo_inalcanzable_no_rompe_lo_que_ya_funcionaba():
    ok, d = await run(req(), Backend(down=True))
    assert not ok and d["model"] == "glm"


async def test_credencial_inalcanzable_es_fail_closed_sin_enviar_nada():
    for b in (Backend(down=False, cred_status=503), Backend(cred_status=404)):
        with pytest.raises(GuardRejection) as e:
            await run(req(), b)
        assert e.value.status == 503 and "sk-" not in e.value.message


async def test_referencia_a_variable_del_servidor_se_resuelve_en_el_motor():
    ok, d = await run(req(), Backend(cred={"api_key": "env:REDIRECT_CRED_GLM"}),
                      environ={"REDIRECT_CRED_GLM": "valor-del-entorno"})
    assert d["api_key"] == "valor-del-entorno"
    with pytest.raises(GuardRejection):
        await run(req(), Backend(cred={"api_key": "env:REDIRECT_CRED_GLM"}), environ={})


async def test_proveedor_sin_familia_es_error_de_configuracion():
    bad = {**ENTRY, "provider": "marte"}
    with pytest.raises(GuardRejection) as e:
        await run(req(), Backend(entries={"glm": bad}))
    assert e.value.status == 503


async def test_cache_por_organizacion_y_version():
    b, t = Backend(), {"now": 0.0}
    g = rc.CatalogDirect(fetch=b, environ={}, ttl=5.0, clock=lambda: t["now"])
    await g.apply(req(), user(), call_type=None)
    await g.apply(req(), user(), call_type=None)
    assert b.calls.count("/internal/model-catalog") == 1
    t["now"] = 6.0
    await g.apply(req(), user(), call_type=None)
    assert b.calls.count("/internal/model-catalog") == 2


async def test_el_guard_completo_lo_usa_antes_de_exigir_autorizacion():
    from sentinel.engine.redirect_guard import RedirectGuard
    g = RedirectGuard()
    g._catalog = rc.CatalogDirect(fetch=Backend(), environ={})
    out = await g.async_pre_call_hook(user(), None, req(), "acompletion")
    assert out["model"] == "rdx-zai/glm-4.6"


# ── límites por pedido y tipo de modelo (069 T127; FR-052, FR-060) ───────────────────

async def test_el_guard_aplica_solo_timeout_y_num_retries_por_pedido():
    entry = dict(ENTRY, limits={"timeout": 30, "num_retries": 2, "rpm": 60, "tpm": 1000,
                                "max_parallel_requests": 3})
    ok, d = await run(req(), Backend(entries={"glm": entry}))
    assert ok and d["timeout"] == 30 and d["num_retries"] == 2
    assert not {"rpm", "tpm", "max_parallel_requests"} & set(d)       # informativos: no se aplican


@pytest.mark.parametrize("limits", [{}, {"timeout": 0, "num_retries": 0}, {"timeout": True},
                                    {"timeout": "30", "num_retries": 1.5}, {"timeout": -1}])
async def test_limites_ausentes_cero_o_no_enteros_no_se_aplican(limits):
    ok, d = await run(req(), Backend(entries={"glm": dict(ENTRY, limits=limits)}))
    assert ok and "timeout" not in d and "num_retries" not in d


async def test_sin_la_clave_limits_el_pedido_sigue_como_antes():
    ok, d = await run(req())                                          # ENTRY de la 069 original, sin `limits`
    assert ok and "timeout" not in d and "num_retries" not in d


SERVICIO = [("acompletion", "text"), ("completion", "text"), ("anthropic_messages", "text"),
            ("aresponses", "text"), ("responses", "text"), ("atext_completion", "text"),
            ("aembedding", "embeddings"), ("embedding", "embeddings"),
            ("aimage_generation", "image"), ("image_generation", "image"), ("aimage_edit", "image"),
            ("atranscription", "audio"), ("transcription", "audio"), ("aspeech", "audio"), ("speech", "audio"),
            ("arerank", "rerank"), ("rerank", "rerank")]


async def serve(call_type, role, **extra):
    g = rc.CatalogDirect(fetch=Backend(entries={"glm": dict(ENTRY, **({"role": role} if role else {}), **extra)}),
                         environ={})
    d = req()
    return await g.apply(d, user(), call_type=call_type), d


@pytest.mark.parametrize("call_type,role", SERVICIO)
async def test_cada_tipo_se_sirve_por_su_tipo_de_llamada(call_type, role):
    ok, d = await serve(call_type, role)
    assert ok and d["model"] == "rdx-zai/glm-4.6" and d["api_key"] == "sk-glm"
    home = d.get("metadata") or d["litellm_metadata"]          # según el tipo de llamada
    dec = home["_internal_routing_decision"]["extensions"]["redirect"]
    assert dec["source"] == "catalog" and dec["role"] == role


@pytest.mark.parametrize("call_type,role", SERVICIO)
async def test_un_tipo_que_no_corresponde_a_la_llamada_se_rechaza(call_type, role):
    otro = "image" if role != "image" else "text"
    with pytest.raises(GuardRejection) as e:
        await serve(call_type, otro)
    assert e.value.status == 400
    assert e.value.message == f"Este modelo es de tipo {otro} y no se puede usar en esta operación."


@pytest.mark.parametrize("call_type", [None, "algo_desconocido"])
async def test_llamada_ausente_o_desconocida_se_asume_texto(call_type):
    ok, d = await serve(call_type, "text")
    assert ok and d["model"] == "rdx-zai/glm-4.6"
    with pytest.raises(GuardRejection) as e:
        await serve(call_type, "image")
    assert e.value.status == 400


async def test_entrada_sin_role_se_trata_como_texto():
    ok, _ = await serve("acompletion", None)
    assert ok


async def test_imagen_sin_precio_por_token_no_inventa_precio():
    ok, d = await serve("aimage_generation", "image", price={"input": None, "output": None})
    assert ok and "input_cost_per_token" not in d and "output_cost_per_token" not in d


# --- acceso por perfil para quienes hablan directo con el motor (069 T152/T153; US2) ---

def actor(**ident):
    return SimpleNamespace(metadata={"sentinel": {"tenant_id": T1, **ident}})


async def access_run(backend, u=None, model="glm", **kw):
    g = rc.CatalogDirect(fetch=backend, environ={}, **kw)
    d = req(model)
    return await g.apply(d, u or actor(client_id="u1", group_id="g1", key_id="k1"), call_type="acompletion"), d


async def test_modelo_permitido_para_el_perfil_se_sirve():
    b = Backend(access={"restringe": True, "permitidos": ["glm"]})
    ok, d = await access_run(b)
    assert ok and d["model"] == "rdx-zai/glm-4.6"
    assert b.access_params == [{"tenant": T1, "user": "u1", "group": "g1", "key": "k1"}]


async def test_modelo_no_permitido_para_el_perfil_da_403():
    with pytest.raises(GuardRejection) as e:
        await access_run(Backend(access={"restringe": True, "permitidos": ["otro"]}))
    assert e.value.status == 403 and e.value.message == "Este modelo no está permitido para tu perfil."


async def test_sin_politica_se_sirve():
    ok, _ = await access_run(Backend(access={"restringe": False, "permitidos": []}))
    assert ok


@pytest.mark.parametrize("kw", [{"access_down": True}, {"access_status": 503}, {"access_status": 500},
                                {"access_status": 404}])
async def test_backend_de_acceso_caido_o_con_error_es_503_fail_closed(kw):
    with pytest.raises(GuardRejection) as e:
        await access_run(Backend(**kw))
    assert e.value.status == 503 and e.value.message == "Modelo no disponible temporalmente."


async def test_respuesta_de_acceso_malformada_es_503():
    with pytest.raises(GuardRejection) as e:
        await access_run(Backend(access={"permitidos": ["glm"]}))
    assert e.value.status == 503


async def test_modelo_fuera_del_catalogo_no_se_gobierna_ni_consulta_acceso():
    b = Backend(access={"restringe": True, "permitidos": []}, access_down=True)
    ok, d = await access_run(b, model="gpt-4o")
    assert not ok and d["model"] == "gpt-4o" and b.access_params == []


async def test_con_direct_apagado_no_se_consulta_acceso():
    b = Backend(direct=False, access_down=True)
    ok, _ = await access_run(b)
    assert not ok and b.access_params == []


async def test_el_acceso_se_cachea_por_actor_y_vence_con_el_ttl():
    b, t = Backend(access={"restringe": True, "permitidos": ["glm"]}), {"now": 0.0}
    g = rc.CatalogDirect(fetch=b, environ={}, ttl=5.0, clock=lambda: t["now"])
    for _ in range(2):
        await g.apply(req(), actor(client_id="u1", key_id="k1"), call_type="acompletion")
    assert len(b.access_params) == 1
    await g.apply(req(), actor(client_id="u2", key_id="k2"), call_type="acompletion")
    assert len(b.access_params) == 2                          # otro actor, otra consulta
    t["now"] = 6.0
    await g.apply(req(), actor(client_id="u1", key_id="k1"), call_type="acompletion")
    assert len(b.access_params) == 3


async def test_identidad_sin_usuario_ni_grupo_usa_lo_que_haya():
    b = Backend(access={"restringe": True, "permitidos": ["glm"]})
    ok, _ = await access_run(b, u=actor(key_id="k1"))
    assert ok and b.access_params == [{"tenant": T1, "key": "k1"}]


async def test_acepta_las_claves_user_id_y_api_key_id():
    b = Backend()
    await access_run(b, u=actor(user_id="u9", api_key_id="k9"))
    assert b.access_params == [{"tenant": T1, "user": "u9", "key": "k9"}]


# ── hallazgo en nix (2-oct): dentro del motor `redirect_catalog` y `redirect_guard` se cargan como módulos
# distintos, y la `GuardRejection` del catálogo no es la clase que el hook del guard atrapa ⇒ salía 500.

async def test_una_rechazo_de_otra_instancia_del_modulo_sigue_siendo_un_rechazo_del_guard():
    from fastapi import HTTPException

    from sentinel.engine.redirect_guard import RedirectGuard

    class GuardRejection(Exception):          # misma forma, OTRA clase (como el módulo cargado dos veces)
        def __init__(self, status, code, message):
            super().__init__(code)
            self.status, self.code, self.message = status, code, message

    class Falso:
        async def apply(self, data, user, call_type=None):
            raise GuardRejection(403, "model_not_allowed_for_profile", "Este modelo no está permitido para tu perfil.")

    g = RedirectGuard()
    g._catalog = Falso()
    with pytest.raises(HTTPException) as e:
        await g.async_pre_call_hook(user(), None, req(), "acompletion")
    assert e.value.status_code == 403
    assert e.value.detail["error"] == "Este modelo no está permitido para tu perfil."
    assert e.value.detail["code"] == "model_not_allowed_for_profile"


async def test_una_excepcion_ajena_no_se_convierte_en_rechazo():
    from sentinel.engine.redirect_guard import RedirectGuard

    class Falso:
        async def apply(self, data, user, call_type=None):
            raise RuntimeError("falla inesperada")

    g = RedirectGuard()
    g._catalog = Falso()
    with pytest.raises(RuntimeError):
        await g.async_pre_call_hook(user(), None, req(), "acompletion")


# ── mínimo de tokens de salida del destino (069 T183): mismo punto de paso que la redirección ────

OPENAI_ENTRY = {**ENTRY, "entry_id": "e2", "name": "Luna", "provider": "openai", "real_model": "gpt-6-luna"}


def _decision(data):
    return data["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]


@pytest.mark.parametrize("param", ["max_completion_tokens", "max_output_tokens"])
async def test_la_ruta_directa_sube_al_minimo_de_openai(param):
    be = Backend(entries={"luna": OPENAI_ENTRY}, cred={"api_key": "sk-o"})
    data = req("luna", **{param: 1})
    assert await rc.CatalogDirect(be, environ={}).apply(data, user()) is True
    assert data[param] == 16 and _decision(data)["adjusted_params"] == param


async def test_la_ruta_directa_no_toca_un_limite_normal_ni_ajusta_a_otro_proveedor():
    be = Backend(entries={"luna": OPENAI_ENTRY}, cred={"api_key": "sk-o"})
    data = req("luna", max_completion_tokens=1000)
    await rc.CatalogDirect(be, environ={}).apply(data, user())
    assert data["max_completion_tokens"] == 1000 and "adjusted_params" not in _decision(data)
    data = req("glm", max_tokens=1)                       # zai: sin mínimo propio
    await rc.CatalogDirect(Backend(), environ={}).apply(data, user())
    assert data["max_tokens"] == 1 and "adjusted_params" not in _decision(data)


async def test_la_ruta_directa_renombra_max_tokens_para_openai_y_audita():
    be = Backend(entries={"luna": OPENAI_ENTRY}, cred={"api_key": "sk-o"})
    data = req("luna", max_tokens=4096)                   # T192: gpt-5+ rechaza max_tokens con 400
    await rc.CatalogDirect(be, environ={}).apply(data, user())
    assert data["max_completion_tokens"] == 4096 and "max_tokens" not in data
    assert _decision(data)["adjusted_params"] == "max_tokens->max_completion_tokens"
