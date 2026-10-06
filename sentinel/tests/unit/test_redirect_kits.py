"""Kits de cliente (contracts/kits.md; FR-030, FR-035; T107).

Función pura: del catálogo publicado del alcance + la dirección de la pasarela salen los
archivos de cada herramienta. Sin credencial salvo que se pase una llave (la emitida para ese
alcance); jamás credenciales de destino. Marca de instalación NEUTRA DE PRUEBA."""
import json
from pathlib import Path

import pytest

from sentinel.redirect import kits

ROOT = Path(__file__).resolve().parents[3]
GW = "https://gw.acme.test/api/v1/gw"
BRAND = "Acme Pasarela"

CLAUDE = [
    {"face": "claude", "public_id": "claude-opus-4-5", "family_tier": "opus", "is_family_default": True,
     "label": "Opus · servido por GLM"},
    {"face": "claude", "public_id": "claude-sonnet-4-5", "family_tier": "sonnet", "is_family_default": True,
     "label": "Sonnet · servido por DeepSeek"},
    {"face": "claude", "public_id": "claude-haiku-4-5", "family_tier": "haiku", "is_family_default": True,
     "label": None},
]
CODEX = [{"face": "codex", "public_id": "gpt-5-codex", "family_tier": None, "is_family_default": False,
          "label": None}]
GENERIC = [{"face": "openai_generic", "public_id": "pro", "label": None},
           {"face": "openai_generic", "public_id": "rapido", "label": None}]
ALL = CLAUDE + CODEX + GENERIC


def build(tool, published=ALL, **kw):
    return kits.build_kit(tool, gateway_url=GW, brand=BRAND, published=published, **kw)


def text(kit):
    return "\n".join(f["content"] for f in kit["files"])


def file(kit, suffix):
    return next(f for f in kit["files"] if f["path"].endswith(suffix))


def banned_terms():
    lines = (ROOT / "deploy/release/checks/prohibited_names.txt").read_text().splitlines()
    terms = [l.strip().lower() for l in lines if l.strip() and not l.startswith("#")]
    assert terms, "la lista compartida no puede estar vacía"
    return terms + ["sentinel", "guardian", "basa", "evidenze"]      # marca del fabricante del producto


# --- claude_desktop -----------------------------------------------------------------

def test_claude_desktop_json_managed():
    kit = build("claude_desktop")
    cfg = json.loads(file(kit, ".json")["content"])
    assert cfg["inferenceProvider"] == "gateway"
    assert cfg["inferenceGatewayBaseUrl"] == GW
    assert cfg["inferenceGatewayAuthScheme"] == "bearer"
    assert cfg["skipWebFetchPreflight"] is True
    assert cfg["inferenceStreamIdleTimeoutSec"] == 600
    models = {m["name"]: m for m in cfg["inferenceModels"]}
    assert set(models) == {"claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"}   # solo cara Claude
    assert models["claude-sonnet-4-5"]["anthropicFamilyTier"] == "sonnet"
    assert models["claude-sonnet-4-5"]["isFamilyDefault"] is True
    assert models["claude-sonnet-4-5"]["labelOverride"] == "Sonnet · servido por DeepSeek"
    assert models["claude-sonnet-4-5"]["supports1m"] is False
    assert "/etc/claude-desktop/managed-settings.json" in text(kit)    # instrucción de ruta


def test_claude_desktop_unlabeled_model_gets_a_label():
    cfg = json.loads(file(build("claude_desktop"), ".json")["content"])
    haiku = next(m for m in cfg["inferenceModels"] if m["name"] == "claude-haiku-4-5")
    assert haiku["labelOverride"]                      # nunca vacío


# --- claude_code --------------------------------------------------------------------

def test_claude_code_env_with_min_window():
    kit = build("claude_code", context_window=128000)
    body = text(kit)
    assert f"ANTHROPIC_BASE_URL={GW}" in body
    assert "ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-4-5" in body
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-5" in body
    assert "ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-haiku-4-5" in body
    assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW=128000" in body          # ventana mínima de los destinos
    for flag in ("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1", "CLAUDE_CODE_GATEWAY_HINT_HEADERS=1",
                 "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1"):
        assert flag in body
    assert "ANTHROPIC_DEFAULT_FABLE_MODEL" not in body


def test_claude_code_without_window_omits_compact_setting():
    assert "AUTO_COMPACT_WINDOW" not in text(build("claude_code", context_window=None))


def test_claude_code_fable_tier_when_published():
    fable = {"face": "claude", "public_id": "claude-fable-5", "family_tier": "fable",
             "is_family_default": True, "label": None}
    assert "ANTHROPIC_DEFAULT_FABLE_MODEL=claude-fable-5" in text(build("claude_code", CLAUDE + [fable]))


def test_claude_code_isolated_config_dir_note():
    assert "CLAUDE_CONFIG_DIR" in text(build("claude_code")) or build("claude_code")["notes"]


# --- codex --------------------------------------------------------------------------

def test_codex_three_files_with_installation_brand():
    kit = build("codex")
    assert len(kit["files"]) == 3
    cfg = file(kit, "config.toml")["content"]
    assert 'model = "gpt-5-codex"' in cfg
    assert 'model_provider = "acme-pasarela"' in cfg                 # slug de la marca
    assert "[model_providers.acme-pasarela]" in cfg
    assert f'name = "{BRAND}"' in cfg
    assert f'base_url = "{GW}/v1"' in cfg
    assert 'wire_api = "responses"' in cfg and "supports_websockets = false" in cfg
    assert 'forced_login_method = "api"' in cfg
    assert "enabled = false" in cfg                                  # analytics fuera
    models = json.loads(file(kit, "acme-pasarela-models.json")["content"])
    entry = models["models"][0] if isinstance(models, dict) else models[0]
    assert entry["slug"] == "gpt-5-codex"
    assert entry["use_responses_lite"] is False and entry["apply_patch_tool_type"] == "freeform"
    req = file(kit, "requirements.toml")["content"]
    assert 'allowed_login_methods = ["api"]' in req


def test_codex_models_catalog_carries_real_window():
    entry = json.loads(file(build("codex", context_window=200000), "-models.json")["content"])
    entry = entry["models"][0] if isinstance(entry, dict) else entry[0]
    assert entry["context_window"] == 200000


# --- openai_generic -----------------------------------------------------------------

def test_openai_generic_snippet_lists_aliases():
    body = text(build("openai_generic"))
    assert f"OPENAI_BASE_URL={GW}/v1" in body
    assert "OPENAI_API_KEY=" in body
    assert "pro" in body and "rapido" in body
    assert "claude-sonnet-4-5" not in body                           # otra cara: no se mezcla


# --- credencial ---------------------------------------------------------------------

@pytest.mark.parametrize("tool", kits.TOOLS)
def test_no_credential_by_default(tool):
    kit = build(tool)
    assert kit["uses_credential"] is False
    assert "sk-" not in text(kit)


@pytest.mark.parametrize("tool", kits.TOOLS)
def test_credential_only_when_key_given(tool):
    kit = build(tool, api_key="gw-nueva-llave-123")
    assert kit["uses_credential"] is True
    assert "gw-nueva-llave-123" in text(kit)


# --- marca (FR-035) -----------------------------------------------------------------

@pytest.mark.parametrize("tool", kits.TOOLS)
def test_neutral_brand_has_no_engine_or_vendor_terms(tool):
    body = text(build(tool, context_window=128000, api_key="k-test")).lower()
    for term in banned_terms():
        assert term not in body, f"{tool}: el kit nombra «{term}»"


def test_installation_brand_may_appear():
    assert BRAND in text(build("codex"))


# --- alcance y errores --------------------------------------------------------------

def test_tool_without_models_in_scope_is_refused():
    with pytest.raises(kits.KitError) as exc:
        build("codex", published=CLAUDE)
    assert exc.value.code == "no_models"


def test_unknown_tool_is_refused():
    with pytest.raises(kits.KitError) as exc:
        build("vim")
    assert exc.value.code == "unknown_tool"


def test_min_context_window_over_targets_of_scope():
    published = [{"id": "p1", "face": "claude", "public_id": "a"}, {"id": "p2", "face": "claude", "public_id": "b"}]
    rules = [{"published_model_id": "p1", "targets": ["d1", "d2"]}, {"published_model_id": "p2", "targets": ["d3"]}]
    dests = {"d1": {"context_window": 200000}, "d2": {"context_window": 128000},
             "d3": {"context_window": None}, "d4": {"context_window": 8000}}
    assert kits.min_context_window(published, rules, dests) == 128000   # ignora el destino sin dato y el no usado
    assert kits.min_context_window(published, [], dests) is None


def test_brand_slug():
    assert kits.brand_slug("Acme Pasarela") == "acme-pasarela"
    assert kits.brand_slug("  Ñandú  S.A. ") == "nandu-s-a"
    assert kits.brand_slug("") == "gateway"
