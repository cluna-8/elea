"""057 T093 (QA M10; research R18): `MASKING_NONCE_KEY` es una clave del servidor de la que se derivan el sufijo de los
marcadores, la referencia de conversación y el identificador de afinidad de sesión. Una credencial de modelo (de
instalación o adoptada) que la referencie con `env:MASKING_NONCE_KEY` expondría la clave al destino: se rechaza igual que
las de `ENV_DENYLIST`."""
import pytest

from sentinel.catalog import credentials as catalog_credentials
from sentinel.engine import redirect_credentials as rc

NOMBRES = ["MASKING_NONCE_KEY", "OLD_MASKING_NONCE_KEY", "MASKING_NONCE_KEY_2"]


def test_la_clave_esta_en_la_lista_negra_compartida():
    assert "MASKING_NONCE_KEY" in rc.ENV_DENYLIST
    assert catalog_credentials.ENV_DENYLIST is rc.ENV_DENYLIST


@pytest.mark.parametrize("nombre", NOMBRES)
def test_el_nombre_no_se_admite_como_credencial(nombre):
    assert rc.env_name_allowed(nombre) is False


@pytest.mark.parametrize("nombre", NOMBRES)
def test_una_credencial_adoptada_con_esa_referencia_se_rechaza(nombre):
    with pytest.raises(rc.CredentialError):
        catalog_credentials.env_ref_dict(nombre, allow_any_env=True)


def test_una_credencial_de_instalacion_con_esa_referencia_se_rechaza():
    with pytest.raises(rc.CredentialError):
        rc.validate_credential("openai_compatible", {"api_key": "env:MASKING_NONCE_KEY"}, level="installation")


def test_el_guard_no_resuelve_la_referencia_aunque_la_variable_exista():
    with pytest.raises(rc.CredentialError):
        rc.resolve_env_refs({"api_key": "env:MASKING_NONCE_KEY"}, {"MASKING_NONCE_KEY": "x" * 48})


@pytest.mark.parametrize("nombre", ["ANTHROPIC_API_KEY", "REDIRECT_CRED_OR"])
def test_los_nombres_comunes_siguen_admitidos(nombre):
    assert rc.env_name_allowed(nombre) is True
