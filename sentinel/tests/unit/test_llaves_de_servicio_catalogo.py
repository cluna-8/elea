"""Las llaves de servicio (svc.*) no llevan allowlist propia: el catálogo y el acceso por perfil
mandan (069, T186). Un allowed_models fijo de septiembre las dejaba sin modelo."""
from sentinel.redirect import store


def test_servicio_ignora_allowed_models_fijos():
    assert store.models_de_la_llave("servicio", ["nix-us-fast"]) is None


def test_otras_llaves_conservan_su_allowlist():
    assert store.models_de_la_llave("claude-code", ["a", "b"]) == ["a", "b"]
    assert store.models_de_la_llave("claude-code", None) is None
    assert store.models_de_la_llave(None, "no-lista") is None
