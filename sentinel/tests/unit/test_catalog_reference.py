"""Cliente de las listas de referencia del motor (069 T122/T124; D27): httpx simulado, sin red."""
import pytest

from sentinel.catalog import models as cm
from sentinel.catalog import reference as ref

PROVIDERS = ["openai", "anthropic", "z_ai", "bedrock", "cohere", "ollama"]
FIELDS = [
    {"provider": "openai", "provider_display_name": "OpenAI", "litellm_provider": "openai",
     "credential_fields": [{"key": "api_key", "label": "Llave de API", "required": True, "field_type": "password"},
                           {"key": "api_base", "label": "Base", "required": False, "field_type": "text"}],
     "default_model_placeholder": "gpt-4o"},
    {"provider": "bedrock", "provider_display_name": "AWS Bedrock", "litellm_provider": "bedrock",
     "credential_fields": [{"key": "aws_access_key_id", "label": "Access key", "required": True,
                            "field_type": "password"},
                           {"key": "aws_region_name", "label": "Región", "required": False, "field_type": "text"},
                           {"key": "extra_thing", "label": "Otro", "required": True, "field_type": "text"}],
     "default_model_placeholder": "anthropic.claude-3"},
    {"provider": "cohere", "provider_display_name": "Cohere", "litellm_provider": "cohere",
     "credential_fields": [], "default_model_placeholder": "command-r"},
]
COST = {
    "sample_spec": {"mode": "chat"},
    "gpt-4o": {"litellm_provider": "openai", "mode": "chat", "input_cost_per_token": 2.5e-6,
               "output_cost_per_token": 1e-5, "cache_read_input_token_cost": 1.25e-6,
               "max_input_tokens": 128000, "max_output_tokens": 16384, "supports_vision": True,
               "supports_function_calling": True, "supports_pdf_input": True,
               "supports_prompt_caching": True, "supports_reasoning": False},
    "text-embedding-3-small": {"litellm_provider": "openai", "mode": "embedding",
                               "input_cost_per_token": 2e-8, "max_input_tokens": 8191},
    "dall-e-3": {"litellm_provider": "openai", "mode": "image_generation"},
    "whisper-1": {"litellm_provider": "openai", "mode": "audio_transcription"},
    "omni-moderation": {"litellm_provider": "openai", "mode": "moderation"},
    "z_ai/glm-4.6": {"litellm_provider": "z_ai", "mode": "chat", "input_cost_per_token": 6e-7,
                     "output_cost_per_token": 2.2e-6, "max_tokens": 200000},
    "openrouter/z-ai/glm-4.6": {"litellm_provider": "openrouter", "mode": "chat",
                                "input_cost_per_token": 5e-7, "output_cost_per_token": 2e-6},
    "cohere/command-r": {"litellm_provider": "cohere", "mode": "chat"},
    "anthropic.claude-3": {"litellm_provider": "bedrock", "mode": "chat",
                           "input_cost_per_token": 3e-6, "output_cost_per_token": 1.5e-5},
}
DOCS = {"/public/providers": PROVIDERS, "/public/providers/fields": FIELDS,
        "/public/litellm_model_cost_map": COST}


class Fake:
    def __init__(self, docs=DOCS):
        self.docs, self.calls, self.down = docs, [], False

    def __call__(self, path):
        self.calls.append(path)
        if self.down:
            raise ConnectionError("motor caído")
        return self.docs[path]


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def env():
    f, c = Fake(), Clock()
    return f, c, ref.Reference(fetch=f, clock=c)


def by(data, provider):
    return next(p for p in data if p["provider"] == provider)


def test_proveedores_soportados_y_no_soportados(env):
    _, _, r = env
    out = r.providers()
    assert out["available"] is True and out["fetched_at"]
    d = out["data"]
    assert by(d, "openai")["supported"] is True and by(d, "openai")["display_name"] == "OpenAI"
    assert by(d, "openai")["example_model"] == "gpt-4o"
    cohere = by(d, "cohere")
    assert cohere["supported"] is False and cohere["reason"] == "Todavía no se puede servir desde Sentinel"
    assert by(d, "zai")["supported"] is True                      # z_ai del motor → zai del catálogo
    assert all(p["provider"] in cm.PROVIDERS for p in d if p["supported"])


def test_tabla_explicita_apunta_solo_a_proveedores_del_catalogo():
    assert set(ref.ENGINE_TO_CATALOG.values()) <= set(cm.PROVIDERS)


def test_campos_de_credencial_se_mapean_a_las_formas_del_catalogo(env):
    _, _, r = env
    d = r.providers()["data"]
    keys = [f["key"] for f in by(d, "openai")["credential_fields"]]
    assert keys == ["api_key"]                                    # api_base no es campo de credencial
    f = by(d, "openai")["credential_fields"][0]
    assert f["label"] == "Llave de API" and f["required"] is True
    bed = by(d, "bedrock")["credential_fields"]
    assert {x["key"] for x in bed} == {"aws_access_key_id", "aws_secret_access_key", "aws_region_name",
                                       "aws_session_token"}
    assert next(x for x in bed if x["key"] == "aws_region_name")["required"] is True   # manda SHAPES
    assert next(x for x in bed if x["key"] == "aws_session_token")["required"] is False
    assert by(d, "azure")["requires_api_base"] is True


def test_cache_24h_y_recarga_manual(env):
    f, c, r = env
    r.providers(); r.providers()
    assert len(f.calls) == 3
    c.t += 23 * 3600
    r.providers()
    assert len(f.calls) == 3
    c.t += 2 * 3600
    r.providers()
    assert len(f.calls) == 6
    assert r.refresh() is True and len(f.calls) == 9


def test_motor_caido_es_available_false_sin_excepcion():
    f = Fake(); f.down = True
    r = ref.Reference(fetch=f, clock=Clock())
    out = r.providers()
    assert out["available"] is False and out["fetched_at"] is None
    assert out["data"] and all(p["supported"] for p in out["data"])     # alta manual (SC-014)
    assert r.models("openai")["available"] is False and r.models("openai")["data"] == []
    assert r.refresh() is False
    assert r.model("openai", "gpt-4o") is None


def test_motor_caido_no_reintenta_en_cada_pedido():
    f = Fake(); f.down = True
    c = Clock()
    r = ref.Reference(fetch=f, clock=c)
    r.providers(); r.providers()
    assert len(f.calls) == 1
    c.t += ref.RETRY_AFTER + 1
    f.down = False
    assert r.providers()["available"] is True


def test_si_cae_despues_de_cargar_sirve_lo_ultimo_conocido(env):
    f, c, r = env
    r.providers()
    f.down = True
    c.t += 48 * 3600
    out = r.providers()
    assert out["available"] is True and out["stale"] is True


def test_modelos_del_proveedor_con_precio_contexto_y_features(env):
    _, _, r = env
    out = r.models("openai")
    names = [m["real_model"] for m in out["data"]]
    assert names == ["dall-e-3", "gpt-4o", "text-embedding-3-small", "whisper-1"]   # sin moderación
    m = next(m for m in out["data"] if m["real_model"] == "gpt-4o")
    assert m["role"] == "text" and m["context_window"] == 128000 and m["max_output"] == 16384
    assert m["price"] == {"input": 2.5e-6, "output": 1e-5, "cache_read": 1.25e-6, "cache_write": None}
    assert m["features"] == {"images": True, "documents_pdf": True, "tools": True, "cache_control": True}
    roles = {m["real_model"]: m["role"] for m in out["data"]}
    assert roles["text-embedding-3-small"] == "embeddings" and roles["dall-e-3"] == "image"
    assert roles["whisper-1"] == "audio"


def test_nombre_real_sin_prefijo_del_proveedor_y_contexto_por_max_tokens(env):
    _, _, r = env
    assert [m["real_model"] for m in r.models("zai")["data"]] == ["glm-4.6"]
    assert r.models("zai")["data"][0]["context_window"] == 200000
    assert [m["real_model"] for m in r.models("openrouter")["data"]] == ["z-ai/glm-4.6"]


def test_busqueda_y_paginado(env):
    _, _, r = env
    out = r.models("openai", q="TEXT-emb")
    assert out["total"] == 1 and out["data"][0]["real_model"] == "text-embedding-3-small"
    page = r.models("openai", limit=2, offset=1)
    assert page["total"] == 4 and [m["real_model"] for m in page["data"]] == ["gpt-4o", "text-embedding-3-small"]


def test_proveedor_no_soportado_o_desconocido_sin_modelos(env):
    _, _, r = env
    assert r.models("cohere")["data"] == [] and r.models("nada")["data"] == []


def test_modelo_puntual_para_sugerencias(env):
    _, _, r = env
    assert r.model("openai", "gpt-4o")["context_window"] == 128000
    assert r.model("openai", "no-existe") is None
    assert r.model("bedrock", "anthropic.claude-3")["price"]["output"] == 1.5e-5


def test_mode_a_rol():
    assert {m: ref.role_of_mode(m) for m in ("chat", "completion", "responses", "embedding", "image_generation",
                                             "audio_speech", "rerank", "moderation")} == {
        "chat": "text", "completion": "text", "responses": "text", "embedding": "embeddings",
        "image_generation": "image", "audio_speech": "audio", "rerank": "rerank", "moderation": None}


def test_base_del_motor_por_entorno(monkeypatch):
    monkeypatch.delenv("SENTINEL_ENGINE_API_BASE", raising=False)
    assert ref.engine_base() == "http://engine:4000"
    monkeypatch.setenv("SENTINEL_ENGINE_API_BASE", "http://x:1/")
    assert ref.engine_base() == "http://x:1"
