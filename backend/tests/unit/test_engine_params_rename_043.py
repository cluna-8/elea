"""`ModelCredentialSchema` — `engine_params` reemplaza a `litellm_params` como campo
público (spec 043 US6, T060, contrato 6): `engine_params` funciona como entrada nueva;
`litellm_params` se sigue aceptando por compatibilidad (al menos una versión) pero queda
marcado `deprecated` en el schema; si llegan los dos, gana `engine_params`."""
import warnings

from src.api.chat import ModelCredentialSchema


def test_engine_params_es_el_camino_nuevo():
    body = ModelCredentialSchema(engine_params={"api_key": "sk-nueva"})
    assert body.resolved_engine_params() == {"api_key": "sk-nueva"}


def test_litellm_params_sigue_funcionando_por_compatibilidad():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        body = ModelCredentialSchema(litellm_params={"api_key": "sk-vieja"})
    assert body.resolved_engine_params() == {"api_key": "sk-vieja"}


def test_si_llegan_los_dos_gana_engine_params():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        body = ModelCredentialSchema(engine_params={"api_key": "nuevo"},
                                     litellm_params={"api_key": "viejo"})
    assert body.resolved_engine_params() == {"api_key": "nuevo"}


def test_litellm_params_esta_marcado_deprecated_en_el_schema():
    schema = ModelCredentialSchema.model_json_schema()
    assert schema["properties"]["litellm_params"].get("deprecated") is True
    assert "deprecated" not in schema["properties"]["engine_params"]
