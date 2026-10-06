"""E3 de la 069, plano de datos: un destino de una regla ES una entrada del catálogo (T180).

Instantánea real (`load_from_session` sobre SQLite con las dos metadatas) → resolver → plugin de la pasarela →
autorización firmada → guard del motor. El pedido sale con el modelo real, la dirección base, la credencial, el
precio y la lista de parámetros no soportados DE LA ENTRADA; archivar o cambiar de tipo la entrada la saca de
servicio sin 500; la fila vieja de la tabla de la 068 no se sirve si no tiene entrada.

    backend/.venv/bin/python -m pytest sentinel/tests/unit/test_redirect_plano_de_datos_catalogo.py
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from sentinel.catalog import models as cm  # noqa: E402
from sentinel.engine import redirect_guard as g  # noqa: E402
from sentinel.redirect import authz, credentials  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402
from sentinel.redirect.plugin import RedirectPlugin  # noqa: E402
from sentinel.redirect.store import RedirectStore, decrypt_credential, load_from_session  # noqa: E402
from sentinel.tests import redirect_fixtures as fx  # noqa: E402

KEY = fx.INTERNAL_KEY
T = uuid.UUID(fx.TENANT)
AZURE_KEY = "sk-azure-de-la-entrada-sol"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, KEY)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    rm.RedirectBase.metadata.create_all(engine)
    cm.CatalogBase.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    fx.seed_regions(s)
    yield s
    s.close()


def _sol(db, **kw):
    base = dict(name="GPT 6.1 Sol", provider="azure", real_model="gpt-6.1-sol",
                protocol_family="openai_chat", api_base="https://recurso.openai.azure.com",
                credential={"api_key": AZURE_KEY, "api_version": "2024-10-21"},
                unsupported=["temperature"], context_window=400000, max_output=32000,
                price={"input_per_mtok": 2.5, "output_per_mtok": 10.0}, inference="DE", entity="DE")
    base.update(kw)
    return fx.seed_entry(db, **base)


def _politica(db, destinos, *, public_id="claude-opus-5-5", tier="opus"):
    pub = rm.RedirectPublishedModel(id=uuid.uuid4(), tenant_id=T, scope_type="tenant", scope_value="*",
                                    face="claude", public_id=public_id, family_tier=tier)
    db.add(pub)
    db.add(rm.RedirectPolicy(id=uuid.uuid4(), tenant_id=T, scope_type="tenant", scope_value="*", state="on"))
    db.add(rm.RedirectRule(id=uuid.uuid4(), tenant_id=T, published_model_id=pub.id, scope_type="tenant",
                           scope_value="*", targets=list(destinos), strategy="order"))
    db.commit()


def _decrypt(blob):
    """Como `decrypt_credential` de producción, con el cifrado reemplazado por JSON en claro."""
    if blob and blob.startswith("env_ref:"):
        return decrypt_credential(blob)
    return json.loads(blob) if blob else {}


def _plugin(db):
    store = RedirectStore(loader=lambda t: load_from_session(db, t), ttl=0, key_models=lambda k: None,
                          redis_factory=lambda: None, decrypt=_decrypt)
    return RedirectPlugin(store=store, ping_after=0.05)


def _pedido(**extra):
    body = {"model": "claude-opus-5-5", "max_tokens": 200, "temperature": 0.3, "top_p": 0.9,
            "messages": [{"role": "user", "content": "hola"}]}
    body.update(extra)
    return body


async def _por_la_cara_claude(plugin, **extra):
    c = fx.ctx(route="/v1/messages", model="claude-opus-5-5")
    rejected = await plugin.pre_request(c)
    return c, rejected, (None if rejected else plugin.pre_engine(c, _pedido(**extra), {}))


def _al_motor(out, headers, environ=None):
    """Lo que ve el motor: el guard verifica la autorización firmada y reescribe el pedido."""
    data = dict(out)
    hdrs = {authz.HEADER: headers[authz.HEADER]}
    data.update({"proxy_server_request": {"headers": dict(hdrs)}, "metadata": {"headers": dict(hdrs)}})
    return g.apply_redirect(data, key=KEY, environ=environ or {})


# ── (c) un pedido por la cara Claude llega al motor con lo de la entrada ──────────────────────────

async def test_la_cara_claude_sirve_la_entrada_con_su_modelo_credencial_y_parametros(db):
    sol = _sol(db)
    _politica(db, [sol["id"]])
    c, rejected, (out, headers) = await _por_la_cara_claude(_plugin(db))
    assert rejected is None
    assert c.routing_decision["extensions"]["redirect"]["dropped_params"] == "temperature"
    assert "temperature" not in out and out["top_p"] == 0.9
    data = _al_motor(out, headers)
    assert data["model"] == credentials.family_model("azure", "gpt-6.1-sol")
    assert data["api_key"] == AZURE_KEY and data["api_version"] == "2024-10-21"
    assert data["api_base"] == "https://recurso.openai.azure.com"
    assert "temperature" not in data and data["top_p"] == 0.9
    assert data["input_cost_per_token"] == pytest.approx(2.5e-6)
    assert data["output_cost_per_token"] == pytest.approx(1e-5)
    # la decisión de auditoría lleva el id de la ENTRADA y solo el nombre de lo descartado
    redirect = data["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert redirect["destination_id"] == sol["id"] and redirect["dropped_params"] == "temperature"
    assert AZURE_KEY not in json.dumps(data["metadata"])


async def test_el_motor_aunque_el_cliente_cuele_temperature_la_quita_por_la_lista_firmada(db):
    sol = _sol(db)
    _politica(db, [sol["id"]])
    _, _, (out, headers) = await _por_la_cara_claude(_plugin(db))
    out["temperature"] = 0.9                      # algo que se coló entre la pasarela y el motor
    assert "temperature" not in _al_motor(out, headers)


async def test_una_entrada_sin_lista_conserva_temperature(db):
    sol = _sol(db, unsupported=[])
    _politica(db, [sol["id"]])
    _, _, (out, headers) = await _por_la_cara_claude(_plugin(db))
    assert _al_motor(out, headers)["temperature"] == 0.3


async def test_el_fallback_pasa_a_la_siguiente_entrada_del_catalogo(db):
    archivada = _sol(db, name="Sol vieja", status="archived")
    luna = _sol(db, name="GPT 6 Luna", real_model="gpt-6-luna", unsupported=[])
    _politica(db, [archivada["id"], luna["id"]])
    _, _, (out, headers) = await _por_la_cara_claude(_plugin(db))
    data = _al_motor(out, headers)
    assert data["model"] == credentials.family_model("azure", "gpt-6-luna") and data["temperature"] == 0.3


async def test_una_entrada_de_instalacion_ofrecida_se_sirve_con_su_referencia_de_entorno(db):
    inst = fx.seed_entry(db, name="Sol de la instalación", level="installation", offered_to=["*"],
                         provider="openai_compatible", real_model="sol", api_base="http://sol/v1",
                         credential_kind="env_ref", env_name="REDIRECT_CRED_SOL")
    _politica(db, [inst["id"]])
    _, _, (out, headers) = await _por_la_cara_claude(_plugin(db))
    data = _al_motor(out, headers, {"REDIRECT_CRED_SOL": "sk-del-entorno"})
    assert data["api_key"] == "sk-del-entorno" and data["api_base"] == "http://sol/v1"


# ── (5) lo que ya no está en el catálogo no se sirve y no rompe ───────────────────────────────────

@pytest.mark.parametrize("cambio", [{"status": "archived"}, {"status": "inactive"}])
async def test_una_entrada_archivada_o_inactiva_deja_de_servir_sin_500(db, cambio):
    sol = _sol(db)
    _politica(db, [sol["id"]])
    db.get(cm.CatalogEntry, uuid.UUID(sol["id"])).status = cambio["status"]
    db.commit()
    c, rejected, _ = await _por_la_cara_claude(_plugin(db))
    assert rejected is not None and rejected.status_code == 404


async def test_una_entrada_que_no_es_de_texto_no_sirve_a_una_regla(db):
    emb = _sol(db, name="Embeddings", role="embeddings")
    _politica(db, [emb["id"]])
    _, rejected, _ = await _por_la_cara_claude(_plugin(db))
    assert rejected is not None and rejected.status_code == 404


async def test_la_fila_vieja_sin_entrada_no_se_sirve(db):
    vieja = uuid.uuid4()
    db.add(rm.RedirectDestination(
        id=vieja, level="tenant", tenant_id=T, name="Vieja", provider="openai_compatible", real_model="viejo",
        protocol_family="openai_chat", api_base="http://viejo/v1", credential_encrypted=json.dumps({"api_key": "sk-v"}),
        provider_options={}, capability_profile={}, status="active"))
    _sol(db)                                         # el catálogo existe y no tiene la fila vieja
    _politica(db, [str(vieja)])
    snap = load_from_session(db, fx.TENANT)
    assert str(vieja) not in snap.destinations and str(vieja) not in snap.credentials
    _, rejected, _ = await _por_la_cara_claude(_plugin(db))
    assert rejected is not None and rejected.status_code == 404


async def test_la_fila_vieja_con_el_mismo_id_que_su_entrada_manda_el_catalogo(db):
    sol = _sol(db)
    db.add(rm.RedirectDestination(
        id=uuid.UUID(sol["id"]), level="tenant", tenant_id=T, name="GPT 6.1 Sol", provider="openai_compatible",
        real_model="otro-modelo", protocol_family="openai_chat", api_base="http://viejo/v1",
        credential_encrypted=json.dumps({"api_key": "sk-viejo"}), provider_options={}, capability_profile={},
        status="active"))
    db.commit()
    _politica(db, [sol["id"]])
    _, _, (out, headers) = await _por_la_cara_claude(_plugin(db))
    data = _al_motor(out, headers)
    assert data["model"] == credentials.family_model("azure", "gpt-6.1-sol") and data["api_key"] == AZURE_KEY


def test_sin_las_tablas_del_catalogo_la_instantanea_usa_la_tabla_de_la_068():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    rm.RedirectBase.metadata.create_all(engine)               # catálogo sin migrar
    s = sessionmaker(bind=engine)()
    did = uuid.uuid4()
    s.add(rm.RedirectDestination(
        id=did, level="tenant", tenant_id=T, name="Vieja", provider="openai_compatible", real_model="viejo",
        protocol_family="openai_chat", api_base="http://viejo/v1", credential_encrypted="blob",
        provider_options={}, capability_profile={}, status="active"))
    s.add(rm.RedirectPolicy(id=uuid.uuid4(), tenant_id=T, scope_type="tenant", scope_value="*", state="on"))
    s.commit()
    snap = load_from_session(s, fx.TENANT)
    assert list(snap.destinations) == [str(did)] and snap.credentials == {str(did): "blob"}


# ── mínimo de tokens de salida del destino (T183) ────────────────────────────────────────────────
# Claude Desktop sondea con `max_tokens: 1`; OpenAI (Responses) rechaza `max_output_tokens < 16`.

def _openai(db, **kw):
    base = dict(name="GPT 6 Luna", provider="openai", real_model="gpt-6-luna", protocol_family="openai_responses",
                api_base=None, credential={"api_key": "sk-openai-de-la-entrada"}, unsupported=[],  # secret-scanner: allow (valor inventado de un fixture de test, no es una credencial)
                context_window=400000, max_output=32000, price={"input_per_mtok": 1.0, "output_per_mtok": 4.0})
    base.update(kw)
    return fx.seed_entry(db, **base)


async def _sale(db, entry, **extra):
    _politica(db, [entry["id"]])
    _, rejected, (out, headers) = await _por_la_cara_claude(_plugin(db), **extra)
    assert rejected is None
    data = _al_motor(out, headers)
    return data, data["metadata"]["_internal_routing_decision"]["extensions"]["redirect"]


async def test_el_sondeo_de_un_token_sale_a_openai_con_el_minimo_y_queda_auditado(db):
    data, redirect = await _sale(db, _openai(db), max_tokens=1)
    assert data["max_completion_tokens"] == 16 and "max_tokens" not in data     # T192: OpenAI chat solo acepta este
    assert redirect["adjusted_params"] == "max_tokens->max_completion_tokens,max_completion_tokens"


async def test_un_limite_normal_a_openai_no_se_toca(db):
    data, redirect = await _sale(db, _openai(db), max_tokens=1000)
    assert data["max_completion_tokens"] == 1000 and redirect["adjusted_params"] == "max_tokens->max_completion_tokens"


async def test_un_destino_openrouter_no_se_ajusta(db):
    glm = fx.seed_entry(db, name="GLM 5.2", provider="openrouter", real_model="z-ai/glm-5.2",
                        protocol_family="openai_chat", credential={"api_key": "sk-or"}, unsupported=[],
                        context_window=200000, max_output=32000, price={"input_per_mtok": 1.0, "output_per_mtok": 2.0})
    data, redirect = await _sale(db, glm, max_tokens=1)
    assert data["max_tokens"] == 1 and "adjusted_params" not in redirect


async def test_azure_tambien_sube_al_minimo(db):
    data, redirect = await _sale(db, _sol(db), max_tokens=1)
    assert data["max_completion_tokens"] == 16 and "max_tokens" in redirect["adjusted_params"]
