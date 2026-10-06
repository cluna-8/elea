"""Credenciales por proveedor, referencias env: y parámetros del motor (data-model §2; D14; T042)."""
import pytest

from sentinel.redirect import credentials as c


@pytest.mark.parametrize("provider,family,prefix", [
    ("openai", "rdx-openai", "openai"),
    ("azure", "rdx-azure", "azure"),
    ("azure_ai", "rdx-azure-ai", "azure_ai"),
    ("anthropic", "rdx-anthropic", "anthropic"),
    ("bedrock", "rdx-bedrock", "bedrock"),
    ("vertex_ai", "rdx-vertex", "vertex_ai"),
    ("deepseek", "rdx-deepseek", "deepseek"),
    ("gemini", "rdx-gemini", "gemini"),
    ("groq", "rdx-groq", "groq"),
    ("openrouter", "rdx-chatcompat", "hosted_vllm"),
    ("ollama", "rdx-chatcompat", "hosted_vllm"),
    ("openai_compatible", "rdx-chatcompat", "hosted_vllm"),
])
def test_family_mapping(provider, family, prefix):
    assert c.family_for(provider) == family
    assert c.FAMILIES[family] == prefix
    assert c.family_model(provider, "m/x") == f"{family}/m/x"
    assert c.engine_model_for(f"{family}/m/x") == f"{prefix}/m/x"


def test_unknown_provider():
    with pytest.raises(c.CredentialError):
        c.family_for("acme")
    assert c.engine_model_for("gpt-4o") is None
    assert c.engine_model_for("rdx-nope/x") is None


def test_split_family_model():
    assert c.split_family_model("rdx-openai/gpt-5") == ("rdx-openai", "gpt-5")
    assert c.split_family_model("gpt-5") is None


# --- validación de forma ---------------------------------------------------------

@pytest.mark.parametrize("provider,cred", [
    ("openai", {"api_key": "sk"}),
    ("anthropic", {"api_key": "sk"}),
    ("azure", {"api_key": "k", "api_version": "2025-01-01"}),
    ("bedrock", {"aws_access_key_id": "a", "aws_secret_access_key": "b", "aws_region_name": "eu-west-1"}),
    ("bedrock", {"aws_access_key_id": "a", "aws_secret_access_key": "b", "aws_region_name": "eu-west-1",
                 "aws_session_token": "t"}),
    ("vertex_ai", {"vertex_credentials": {"type": "service_account"}, "vertex_project": "p",
                   "vertex_location": "europe-west4"}),
    ("ollama", {}),
])
def test_valid_shapes(provider, cred):
    c.validate_credential(provider, cred, level="tenant")


@pytest.mark.parametrize("provider,cred", [
    ("openai", {}),
    ("openai", {"api_key": ""}),
    ("openai", {"api_key": "sk", "api_base": "https://evil"}),   # la base nunca va en la credencial
    ("azure", {"api_key": "k"}),
    ("bedrock", {"aws_access_key_id": "a"}),
    ("openai", "sk-suelta"),
])
def test_invalid_shapes(provider, cred):
    with pytest.raises(c.CredentialError):
        c.validate_credential(provider, cred, level="installation")


def test_env_refs_only_installation_level():
    c.validate_credential("openai", {"api_key": "env:REDIRECT_CRED_OPENAI"}, level="installation")
    with pytest.raises(c.CredentialError):
        c.validate_credential("openai", {"api_key": "env:REDIRECT_CRED_OPENAI"}, level="tenant")


@pytest.mark.parametrize("ref", ["env:LITELLM_MASTER_KEY", "env:redirect_cred_x", "env:", "env:REDIRECT_CRED_"])
def test_env_ref_name_restricted(ref):
    with pytest.raises(c.CredentialError):
        c.validate_credential("openai", {"api_key": ref}, level="installation")


def test_resolve_env_refs():
    env = {"REDIRECT_CRED_OR": "sk-real", "LITELLM_MASTER_KEY": "master"}
    assert c.resolve_env_refs({"api_key": "env:REDIRECT_CRED_OR"}, env) == {"api_key": "sk-real"}
    with pytest.raises(c.CredentialError):
        c.resolve_env_refs({"api_key": "env:REDIRECT_CRED_MISSING"}, env)
    with pytest.raises(c.CredentialError):
        c.resolve_env_refs({"api_key": "env:LITELLM_MASTER_KEY"}, env)   # defensa en profundidad
    assert c.resolve_env_refs({"api_key": "literal"}, env) == {"api_key": "literal"}


def test_requires_secret_and_base():
    assert not c.requires_secret("ollama")
    assert c.requires_secret("openrouter")
    assert c.requires_api_base("azure") and c.requires_api_base("ollama")
    assert not c.requires_api_base("anthropic")


# --- parámetros del motor ---------------------------------------------------------

def test_params_api_key():
    assert c.to_litellm_params("anthropic", {"api_key": "sk"}, None) == {"api_key": "sk"}
    assert c.to_litellm_params("openrouter", {"api_key": "sk"}, None) == {
        "api_key": "sk", "api_base": "https://openrouter.ai/api/v1"}


def test_params_azure():
    p = c.to_litellm_params("azure", {"api_key": "k", "api_version": "v"}, "https://x.openai.azure.com")
    assert p == {"api_key": "k", "api_version": "v", "api_base": "https://x.openai.azure.com"}
    with pytest.raises(c.CredentialError):
        c.to_litellm_params("azure", {"api_key": "k", "api_version": "v"}, None)


def test_params_bedrock_vertex_ollama():
    b = c.to_litellm_params("bedrock", {"aws_access_key_id": "a", "aws_secret_access_key": "b",
                                        "aws_region_name": "eu-west-1"}, None)
    assert b == {"aws_access_key_id": "a", "aws_secret_access_key": "b", "aws_region_name": "eu-west-1"}
    v = c.to_litellm_params("vertex_ai", {"vertex_credentials": {"type": "sa"}, "vertex_project": "p",
                                          "vertex_location": "l"}, None)
    assert v["vertex_credentials"] == '{"type": "sa"}' and v["vertex_project"] == "p"
    o = c.to_litellm_params("ollama", {}, "http://h:11434/v1")
    assert o["api_base"] == "http://h:11434/v1" and o["api_key"]  # placeholder: nunca cae a env del motor


def test_params_refuse_unresolved_env_ref():
    with pytest.raises(c.CredentialError):
        c.to_litellm_params("openai", {"api_key": "env:REDIRECT_CRED_X"}, None)


def test_redacted():
    r = c.redacted({"api_key": "sk-123", "aws_region_name": "eu-west-1"})
    assert r == {"api_key": "***", "aws_region_name": "***"}
    assert "sk-123" not in repr(r)


def test_strip_client_credentials():
    body = {"model": "x", "api_key": "a", "api_base": "b", "base_url": "c", "extra_headers": {},
            "aws_secret_access_key": "d", "vertex_credentials": "e", "messages": []}
    out, removed = c.strip_client_credentials(body)
    assert out == {"model": "x", "messages": []}
    assert set(removed) == {"api_key", "api_base", "base_url", "extra_headers", "aws_secret_access_key",
                            "vertex_credentials"}


# --- env: de credenciales adoptadas (069 T141/T142; lista negra compartida) -------------

NEVER = ["LITELLM_MASTER_KEY", "SENTINEL_ENGINE_MASTER_KEY", "FERNET_SECRET_KEY", "FERNET_PREVIOUS_KEYS",
         "JWT_SECRET_KEY", "DATABASE_URL", "POSTGRES_PASSWORD", "POSTGRES_USER", "REDIRECT_INTERNAL_KEY",
         "MY_MASTER_KEY_2", "DB_PASSWORD_X", "PG_DATABASE"]
BAD_FORMAT = ["minusculas", "1_EMPIEZA", "CON-GUION", "", "A", "TERMINA_"]


@pytest.mark.parametrize("name", ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "REDIRECT_CRED_OR", "GLM_KEY"])
def test_env_name_allowed_acepta_comunes(name):
    assert c.env_name_allowed(name)


@pytest.mark.parametrize("name", NEVER + BAD_FORMAT)
def test_env_name_allowed_rechaza_lista_negra_y_formato(name):
    assert not c.env_name_allowed(name)


@pytest.mark.parametrize("name", NEVER)
def test_el_motor_nunca_resuelve_la_lista_negra(name):
    env = {name: "secreto"}
    with pytest.raises(c.CredentialError):
        c.resolve_env_refs({"api_key": f"env:{name}"}, env)
    with pytest.raises(c.CredentialError):
        c.validate_credential("openai", {"api_key": f"env:{name}"}, level="installation", allow_any_env=True)


def test_el_motor_resuelve_env_adoptado_y_los_redirect_cred_siguen_valiendo():
    env = {"ANTHROPIC_API_KEY": "sk-a", "REDIRECT_CRED_OR": "sk-r"}
    assert c.resolve_env_refs({"api_key": "env:ANTHROPIC_API_KEY"}, env) == {"api_key": "sk-a"}
    assert c.resolve_env_refs({"api_key": "env:REDIRECT_CRED_OR"}, env) == {"api_key": "sk-r"}
    with pytest.raises(c.CredentialError):
        c.resolve_env_refs({"api_key": "env:ANTHROPIC_API_KEY"}, {})          # sin valor


def test_validate_credential_env_ajeno_solo_con_allow_any_env_y_solo_instalacion():
    ref = {"api_key": "env:ANTHROPIC_API_KEY"}
    with pytest.raises(c.CredentialError):                                    # por defecto sigue estricto
        c.validate_credential("anthropic", ref, level="installation")
    c.validate_credential("anthropic", ref, level="installation", allow_any_env=True)
    with pytest.raises(c.CredentialError):                                    # la regla de nivel no cambia
        c.validate_credential("anthropic", ref, level="tenant", allow_any_env=True)


def test_paridad_lista_negra_catalogo_y_motor():
    from sentinel.catalog import credentials as cat
    nombres = NEVER + BAD_FORMAT + ["ANTHROPIC_API_KEY", "REDIRECT_CRED_OR", "FOO"]
    for n in nombres:
        try:
            cat.env_ref_dict(n, allow_any_env=True)
            catalogo = True
        except c.CredentialError:
            catalogo = False
        assert catalogo == c.env_name_allowed(n), n
    assert cat.ENV_DENYLIST is c.ENV_DENYLIST and cat.ENV_DENY_FRAGMENTS is c.ENV_DENY_FRAGMENTS
