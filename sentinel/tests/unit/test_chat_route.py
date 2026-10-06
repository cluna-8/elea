"""El chat de la consola sirve los modelos del catálogo (069 T143/T144; FR-040, FR-041, D2/D26).

El enrutador reescribe a `rdx-<familia>/<modelo>` y firma la autorización interna con la credencial
cifrada y el precio de la entrada; un modelo que el catálogo no conoce no se toca; fallar no cae en
silencio al camino viejo."""
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
pytest.importorskip("src.services.model_route_hook", reason="requiere el venv del backend")

from src.services import model_route_hook as mh  # noqa: E402

from sentinel.catalog import chat_route as cr  # noqa: E402
from sentinel.redirect import authz  # noqa: E402

KEY = "clave-interna-de-prueba-0123456789abcdef"
T1 = str(uuid.uuid4())
EID = str(uuid.uuid4())
ENTRY = {"entry_id": EID, "name": "GPT", "provider": "openai", "real_model": "gpt-5", "api_base": None,
         "role": "text", "level": "tenant", "semaforo": {"estado": "eu_ok", "motivos": []},
         "price": {"input": 2e-6, "output": 1e-5}, "limits": {}}
USER = SimpleNamespace(id=uuid.uuid4(), group_id=None, tenant_id=T1)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, KEY)
    monkeypatch.setattr(cr, "CATALOG", lambda tenant: {"mi-gpt": ENTRY, "viejo": dict(ENTRY, entry_id=str(uuid.uuid4()))})
    monkeypatch.setattr(cr, "CREDENTIAL", lambda tenant, entry_id: {"api_key": "sk-secreta"})
    yield
    mh.register_model_router(None)
    mh.register_model_lister(None)


def test_modelo_del_catalogo_se_reescribe_y_la_firma_verifica():
    r = cr.route(T1, USER, "mi-gpt")
    assert r.engine_model == "rdx-openai/gpt-5"
    token = r.headers[authz.HEADER]
    g = authz.verify(token, expected_model=r.engine_model, key=KEY)
    assert g.provider == "openai" and g.destination_id == EID and g.forced_masking is False
    assert g.credential == {"api_key": "sk-secreta"}
    assert g.scope.startswith(T1)
    assert g.decision["source"] == "catalog_chat" and g.decision["public_id"] == "mi-gpt"
    assert g.price == {"input_per_mtok": pytest.approx(2.0), "output_per_mtok": pytest.approx(10.0)}


def test_la_credencial_no_viaja_en_claro():
    token = cr.route(T1, USER, "mi-gpt").headers[authz.HEADER]
    assert "sk-secreta" not in token
    import base64
    body = token.split(".")[1]
    assert "sk-secreta" not in base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()


def test_la_firma_no_vale_para_otro_modelo():
    r = cr.route(T1, USER, "mi-gpt")
    with pytest.raises(authz.AuthzModelMismatch):
        authz.verify(r.headers[authz.HEADER], expected_model="rdx-openai/otro", key=KEY)


def test_desconocido_devuelve_none(monkeypatch):
    assert cr.route(T1, USER, "del-archivo-de-config") is None
    assert cr.route(T1, USER, "rdx-openai/gpt-5") is None          # un id interno nunca se acepta del cliente


def test_sin_tenant_devuelve_none():
    assert cr.route(None, USER, "mi-gpt") is None


def test_catalogo_que_no_sirve_la_entrada_devuelve_none(monkeypatch):
    # `build` omite lo inactivo/archivado o sin credencial vigente: ausente ⇒ camino de siempre
    monkeypatch.setattr(cr, "CATALOG", lambda tenant: {})
    assert cr.route(T1, USER, "mi-gpt") is None


def test_rol_que_no_es_texto_devuelve_none(monkeypatch):
    monkeypatch.setattr(cr, "CATALOG", lambda tenant: {"emb": dict(ENTRY, role="image")})
    assert cr.route(T1, USER, "emb") is None


def test_env_ref_viaja_como_referencia(monkeypatch):
    monkeypatch.setattr(cr, "CREDENTIAL", lambda tenant, entry_id: {"api_key": "env:ANTHROPIC_API_KEY"})
    monkeypatch.setattr(cr, "CATALOG", lambda t: {"c": dict(ENTRY, provider="anthropic", real_model="claude-x")})
    r = cr.route(T1, USER, "c")
    assert r.engine_model == "rdx-anthropic/claude-x"
    assert authz.verify(r.headers[authz.HEADER], expected_model=r.engine_model, key=KEY).credential == \
        {"api_key": "env:ANTHROPIC_API_KEY"}


def test_sin_precio_no_firma_precio(monkeypatch):
    monkeypatch.setattr(cr, "CATALOG", lambda t: {"m": dict(ENTRY, price=None)})
    r = cr.route(T1, USER, "m")
    assert authz.verify(r.headers[authz.HEADER], expected_model=r.engine_model, key=KEY).price is None


def test_api_base_viaja_firmada(monkeypatch):
    monkeypatch.setattr(cr, "CATALOG", lambda t: {"l": dict(ENTRY, provider="ollama", real_model="qwen",
                                                           api_base="http://ollama:11434")})
    r = cr.route(T1, USER, "l")
    assert r.engine_model == "rdx-chatcompat/qwen"
    assert authz.verify(r.headers[authz.HEADER], expected_model=r.engine_model, key=KEY).api_base == "http://ollama:11434"


def test_falla_la_firma_es_fail_closed(monkeypatch):
    monkeypatch.delenv(authz.KEY_ENV)
    with pytest.raises(mh.ModelRouteUnavailable):
        cr.route(T1, USER, "mi-gpt")


def test_falla_la_credencial_es_fail_closed(monkeypatch):
    def boom(tenant, entry_id):
        raise RuntimeError("descifrado")
    monkeypatch.setattr(cr, "CREDENTIAL", boom)
    with pytest.raises(mh.ModelRouteUnavailable) as e:
        cr.route(T1, USER, "mi-gpt")
    assert "descifrado" not in str(e.value)


def test_proveedor_sin_familia_es_fail_closed(monkeypatch):
    monkeypatch.setattr(cr, "CATALOG", lambda t: {"x": dict(ENTRY, provider="acme")})
    with pytest.raises(mh.ModelRouteUnavailable):
        cr.route(T1, USER, "x")


def test_catalogo_inalcanzable_es_fail_closed_solo_si_el_modelo_podria_ser_suyo(monkeypatch):
    # sin poder leer el catálogo no se sabe si es suyo: se sigue por el camino de siempre
    def boom(t):
        raise RuntimeError("db")
    monkeypatch.setattr(cr, "CATALOG", boom)
    assert cr.route(T1, USER, "mi-gpt") is None


def test_register_chat_route_conecta_la_costura():
    cr.register_chat_route()
    assert mh.is_active()
    r = mh.route_model(T1, USER, "mi-gpt")
    assert r.engine_model == "rdx-openai/gpt-5"
    assert mh.route_model(T1, USER, "otro") is None
    nombres = {m["model_name"]: m for m in mh.catalog_models(T1)}
    assert set(nombres) == {"mi-gpt", "viejo"}
    m = nombres["mi-gpt"]
    assert (m["provider"], m["model_id"], m["is_configured"], m["is_eu_compliant"]) == ("openai", "gpt-5", True, True)


def test_listado_marca_ue_segun_el_semaforo_y_omite_lo_que_no_es_texto(monkeypatch):
    monkeypatch.setattr(cr, "CATALOG", lambda t: {
        "a": dict(ENTRY, semaforo={"estado": "standard", "motivos": []}),
        "b": dict(ENTRY, role="image"),
        "c": dict(ENTRY, semaforo={"estado": "unclassified", "motivos": []})})
    out = {m["model_name"]: m["is_eu_compliant"] for m in cr.list_models(T1)}
    assert out == {"a": False, "c": False}
