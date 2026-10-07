"""Kits, prueba de fidelidad y comparador de costos por la API (US5; T110–T112).

Misma montura que `test_redirect_admin_api.py`: costura S1 real, guardas de rol reales, SQLite en
memoria; el motor, el emisor de llaves y la fuente de auditoría se inyectan. Corre con el venv
del backend:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest sentinel/tests/contract/test_redirect_us5_api.py
"""
import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
pytest.importorskip("src.auth.rbac", reason="requiere el venv del backend")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.auth.session import get_current_user  # noqa: E402
from src.plugins import mount_plugin_routers  # noqa: E402

from sentinel.catalog import models as cm  # noqa: E402
from sentinel.redirect import fidelity  # noqa: E402
from sentinel.redirect import models as m  # noqa: E402
from sentinel.redirect.api import admin, us5  # noqa: E402

sys.path.insert(0, str(ROOT / "sentinel" / "tests"))
from redirect_fixtures import seed_entry  # noqa: E402
import redirect_fixtures as fx_regions  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
SECRET = "sk-secreto-del-destino-NO-DEBE-VOLVER"
KEY_PLAIN = "gw-llave-nueva-del-kit"
KEY_ID = str(uuid.UUID("99999999-9999-9999-9999-999999999999"))
USER = str(uuid.UUID("44444444-4444-4444-4444-444444444444"))
CONN = str(uuid.UUID("55555555-5555-5555-5555-555555555555"))


def _user(role, tenant=T1):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, role=role, display_label=None)


class _Store:
    def bump(self, tenant=None):
        pass


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    m.RedirectBase.metadata.create_all(engine)
    cm.CatalogBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as _s:
        fx_regions.seed_regions(_s)                      # perfil `eu` con `reject_offregion` (paridad con la 068)
    monkeypatch.setattr(admin, "SESSION_FACTORY", Session)
    monkeypatch.setattr(admin, "STORE", _Store())
    monkeypatch.setattr("sentinel.redirect.api.us5.decrypt_credential",
                        lambda blob: json.loads(blob) if blob else {})      # `seed_entry` guarda el JSON en claro
    issued, sent = [], []

    async def issuer(db, user, *, tool, scope, models):
        issued.append({"tool": tool, "scope": scope, "models": models})
        return KEY_ID, KEY_PLAIN

    def sender_factory(destination, credential, *, face, tenant_id):
        async def send(case, body):
            sent.append((destination["id"], case["name"]))
            return state["outcome"](case)
        return send

    state = {"outcome": lambda case: _good(case)}
    monkeypatch.setattr(us5, "KEY_ISSUER", issuer)
    monkeypatch.setattr(us5, "SENDER_FACTORY", sender_factory)
    monkeypatch.setattr(us5, "PRICE", lambda model, p, c: Decimal(p + c) / Decimal(1_000_000))
    monkeypatch.setenv("REDIRECT_GATEWAY_URL", "https://gw.acme.test/api/v1/gw")
    monkeypatch.setenv("BRAND_NAME", "Acme Pasarela")
    app = FastAPI()
    assert mount_plugin_routers(app, "sentinel.redirect.api") == 1
    who = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = TestClient(app)

    def call(method, path, role=None, tenant=T1, **kw):
        who["user"] = _user(role, tenant) if role else None
        return client.request(method, "/api/v1/redirect" + path, **kw)

    return SimpleNamespace(call=call, Session=Session, issued=issued, sent=sent, state=state)


def _good(case):
    cap = case["capability"]
    base = dict(status=200, text="respuesta", tool_calls=[], events=0, finished=True, error_class=None,
                prompt_tokens=100, completion_tokens=50)
    if cap == "tools":
        base.update(text="", tool_calls=[{"name": "read_file"}])
    if cap == "long_stream":
        base.update(text="x" * 400, events=40)
    if cap == "errors":
        base.update(status=400, text="", error_class="invalid_request")
    if cap == "context":
        base.update(text=case["needle"])
    return fidelity.Outcome(**base)


def _dest(api, **kw):
    """Destino = entrada del catálogo (069 E3): ya no se da de alta por `POST /redirect/destinations`."""
    body = {"name": "Qwen UE", "credential": {"api_key": SECRET}, "context_window": 128000,
            "inference": kw.pop("inference_jurisdiction", "de").upper(),
            "entity": kw.pop("entity_jurisdiction", "DE").upper()}
    body.update(kw)
    with api.Session() as s:
        return seed_entry(s, **body)["id"]


def _publish(api, dest_id, face="claude", public_id="claude-sonnet-4-5", tier="sonnet", **kw):
    body = {"face": face, "public_id": public_id, **({"family_tier": tier, "is_family_default": True} if tier else {})}
    body.update(kw)
    pub = api.call("POST", "/published-models", "tenant_admin", json=body)
    assert pub.status_code == 201, pub.text
    rule = api.call("POST", "/rules", "tenant_admin",
                    json={"published_model_id": pub.json()["id"], "targets": [dest_id]})
    assert rule.status_code == 201, rule.text
    return pub.json()["id"]


def _audits(api, entity=None):
    with api.Session() as s:
        q = s.query(m.RedirectConfigAudit)
        if entity:
            q = q.filter(m.RedirectConfigAudit.entity == entity)
        return list(q)


# ── kits ──────────────────────────────────────────────────────────────────────────────

def test_kits_solo_tenant_admin(api):
    for role in ("client", "compliance_officer"):
        assert api.call("GET", "/kits/claude_code", role).status_code == 403, role
    assert api.call("GET", "/kits/claude_code").status_code == 401


def test_kit_sin_credencial_no_emite_llave_ni_audita(api):
    dest = _dest(api)
    _publish(api, dest)
    r = api.call("GET", "/kits/claude_code", "tenant_admin")
    assert r.status_code == 200, r.text
    body = r.json()
    text = "\n".join(f["content"] for f in body["files"])
    assert "ANTHROPIC_BASE_URL=https://gw.acme.test/api/v1/gw" in text
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-5" in text
    assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW=128000" in text                 # ventana del destino real
    assert body["uses_credential"] is False and body["issued_key_id"] is None
    assert SECRET not in r.text and KEY_PLAIN not in r.text
    assert api.issued == [] and _audits(api, "kit_key") == []
    assert body["scope"] == "tenant:*" and body["catalog_version"]


def test_kit_con_credencial_emite_llave_nueva_del_alcance_y_la_audita(api):
    dest = _dest(api)
    _publish(api, dest)
    _publish(api, dest, face="openai_generic", public_id="pro", tier=None)
    r = api.call("GET", f"/kits/claude_code?scope=user:{USER}&include_credential=true", "tenant_admin")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["issued_key_id"] == KEY_ID and body["uses_credential"] is True
    assert f"ANTHROPIC_AUTH_TOKEN={KEY_PLAIN}" in "\n".join(f["content"] for f in body["files"])
    assert api.issued == [{"tool": "claude_code", "scope": ("user", USER), "models": ["claude-sonnet-4-5"]}]
    assert SECRET not in r.text                                              # nunca credenciales de destino
    [audit] = _audits(api, "kit_key")
    assert audit.action == "issue" and audit.entity_id == KEY_ID and audit.actor_role == "tenant_admin"
    assert audit.after["models"] == ["claude-sonnet-4-5"] and audit.after["scope"] == f"user:{USER}"
    assert KEY_PLAIN not in json.dumps([audit.before, audit.after])          # la llave no queda en la auditoría


def test_kit_de_una_conexion_no_emite_llave(api):
    dest = _dest(api)
    _publish(api, dest)
    r = api.call("GET", f"/kits/claude_code?scope=connection:{CONN}&include_credential=true", "tenant_admin")
    assert r.status_code == 422 and api.issued == []


def test_kit_sin_modelos_en_la_cara_es_404_y_no_emite(api):
    dest = _dest(api)
    _publish(api, dest)                                                       # solo cara Claude
    r = api.call("GET", "/kits/codex?include_credential=true", "tenant_admin")
    assert r.status_code == 404 and api.issued == [] and _audits(api, "kit_key") == []


def test_kit_herramienta_o_alcance_invalidos(api):
    assert api.call("GET", "/kits/vim", "tenant_admin").status_code == 404
    assert api.call("GET", "/kits/codex?scope=planeta:1", "tenant_admin").status_code == 422
    assert api.call("GET", "/kits/codex?scope=user:no-es-uuid", "tenant_admin").status_code == 422


def test_kit_no_ve_el_catalogo_de_otro_tenant(api):
    dest = _dest(api)
    _publish(api, dest)
    assert api.call("GET", "/kits/claude_code", "tenant_admin", tenant=T2).status_code == 404


def test_kit_alcance_usuario_ve_el_id_mas_especifico(api):
    dest = _dest(api)
    _publish(api, dest)
    _publish(api, dest, public_id="claude-sonnet-4-5", scope_type="user", scope_value=USER,
             label="Sonnet del usuario")
    r = api.call("GET", f"/kits/claude_desktop?scope=user:{USER}", "tenant_admin")
    cfg = json.loads(next(f for f in r.json()["files"] if f["path"].endswith(".json"))["content"])
    assert [x["labelOverride"] for x in cfg["inferenceModels"]] == ["Sonnet del usuario"]


def test_kit_resuelve_la_url_de_la_pasarela_del_entorno(api):
    dest = _dest(api)
    _publish(api, dest)
    r = api.call("GET", "/kits/claude_code", "tenant_admin")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gateway_url_resolved"] is True
    assert "https://gw.acme.test/api/v1/gw" in "\n".join(f["content"] for f in body["files"])


def test_kit_con_host_interno_deja_marcador_y_avisa(api, monkeypatch):
    monkeypatch.delenv("REDIRECT_GATEWAY_URL", raising=False)
    dest = _dest(api)
    _publish(api, dest)
    r = api.call("GET", "/kits/claude_code", "tenant_admin", headers={"Host": "backend:8000"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gateway_url_resolved"] is False
    assert us5.kits.URL_PLACEHOLDER in "\n".join(f["content"] for f in body["files"])


# ── fidelidad ─────────────────────────────────────────────────────────────────────────

def _run(api, dest, tool="openai_generic", role="tenant_admin", **kw):
    return api.call("POST", "/fidelity-runs", role, json={"destination_id": dest, "tool": tool, **kw})


def test_fidelidad_solo_tenant_admin_lanza_y_dpo_lee(api):
    dest = _dest(api)
    for role in ("client", "compliance_officer"):
        assert _run(api, dest, role=role).status_code == 403, role
    r = _run(api, dest, tool_version="1.0")
    assert r.status_code == 201, r.text
    assert api.call("GET", f"/fidelity-runs/{r.json()['id']}", "compliance_officer").status_code == 200
    assert api.call("GET", f"/fidelity-runs/{r.json()['id']}", "client").status_code == 403


def test_fidelidad_informe_por_capacidad_persistido_sin_secretos(api):
    dest = _dest(api)
    r = _run(api, dest, tool="claude_code", tool_version="2.1.0")
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["verdict"] == "apto" and rep["face"] == "claude" and rep["tool_version"] == "2.1.0"
    assert {x["capability"] for x in rep["results"]} == set(fidelity.CAPABILITIES)
    assert rep["cost"] > 0 and rep["regressions"] == [] and rep["compared_with"] is None
    assert SECRET not in r.text
    got = api.call("GET", f"/fidelity-runs/{rep['id']}", "tenant_admin").json()
    assert got["results"] == rep["results"] and got["verdict"] == "apto"
    assert len(api.sent) == len(fidelity.CAPABILITIES)
    lst = api.call("GET", f"/fidelity-runs?destination_id={dest}", "compliance_officer").json()["data"]
    assert [x["id"] for x in lst] == [rep["id"]]


def test_fidelidad_regresion_visible_contra_la_corrida_anterior(api):
    dest = _dest(api)
    first = _run(api, dest, tool_version="1.0").json()
    assert first["verdict"] == "apto"

    def broken(case):
        if case["capability"] == "tools":
            return fidelity.Outcome(text="no llamo herramientas", prompt_tokens=10, completion_tokens=5)
        return _good(case)

    api.state["outcome"] = broken
    second = _run(api, dest, tool_version="1.1").json()
    assert second["verdict"] == "no_apto"
    assert [x["capability"] for x in second["regressions"]] == ["tools"]
    assert second["compared_with"]["id"] == first["id"] and second["compared_with"]["tool_version"] == "1.0"


def test_fidelidad_solo_destinos_del_tenant(api):
    dest = _dest(api)
    assert _run(api, dest).status_code == 201
    assert api.call("POST", "/fidelity-runs", "tenant_admin", tenant=T2,
                    json={"destination_id": dest, "tool": "codex"}).status_code == 404       # ajeno: invisible
    assert _run(api, str(uuid.uuid4())).status_code == 404
    n = len(api.sent)
    assert _run(api, str(uuid.uuid4())).status_code == 404 and len(api.sent) == n           # nada salió


def test_fidelidad_respeta_la_postura_de_quien_la_lanza(api):
    us = _dest(api, name="Nativo US", inference_jurisdiction="us", entity_jurisdiction="US")
    r = api.call("POST", "/postures", "compliance_officer",
                 json={"mode": "allowlist", "jurisdictions": ["EU"], "reason": "residencia europea"})
    assert r.status_code == 201, r.text
    denied = _run(api, us)
    assert denied.status_code == 403 and api.sent == []
    eu = _dest(api)
    assert _run(api, eu).status_code == 201


def test_fidelidad_destino_revocado_o_herramienta_desconocida(api):
    dest = _dest(api)
    with api.Session() as s:                                  # se archiva en Modelos
        s.get(cm.CatalogEntry, uuid.UUID(dest)).status = "archived"
        s.commit()
    assert _run(api, dest).status_code == 403
    assert _run(api, _dest(api), tool="vim").status_code == 404
    assert _run(api, _dest(api), tool="codex", face="claude").status_code == 422


def test_fidelidad_presupuesto_agotado_deja_informe_incompleto(api, monkeypatch):
    dest = _dest(api)
    monkeypatch.setenv("REDIRECT_FIDELITY_BUDGET_USD", "0.0001")
    api.state["outcome"] = _expensive
    rep = _run(api, dest).json()
    assert rep["complete"] is False and rep["verdict"] == "incompleto"
    assert any(x["detail_code"] == "budget_exhausted" for x in rep["results"])


def _expensive(case):
    out = _good(case)
    out.prompt_tokens, out.completion_tokens = 60, 60                         # 0,00012 por caso > 0,0001
    return out


# ── costos ────────────────────────────────────────────────────────────────────────────

def _audit_row(public_id, face, dest, *, key=CONN, user=USER, prompt=1000, completion=500, cost=0.0009):
    block = {"public_id": public_id, "face": face, "destination_id": dest, "shadow": False}
    return {"api_key_id": key, "user_id": user, "user_group_id": None, "prompt_tokens": prompt,
            "completion_tokens": completion, "cost_usd": cost,
            "routing_decision": {"extensions": {"redirect": block}}}


def test_costos_real_vs_hipotetico_por_alcance_y_destino(api, monkeypatch):
    dest = _dest(api)
    _publish(api, dest)                                                       # claude-sonnet-4-5 (cara conocida)
    _publish(api, dest, face="openai_generic", public_id="pro", tier=None, reference_model="ref-neutro")
    seen = {}

    def source(db, tenant_id, start, end):
        seen.update(tenant=tenant_id, start=start, end=end)
        return [_audit_row("claude-sonnet-4-5", "claude", dest), _audit_row("pro", "openai_generic", dest, key=None)]

    monkeypatch.setattr(us5, "AUDIT_SOURCE", source)
    monkeypatch.setattr(us5, "PRICE", lambda model, p, c: Decimal("0.02") if model != "qwen" else Decimal("0.001"))
    r = api.call("GET", "/cost-comparison?from=2026-09-01T00:00:00Z&to=2026-10-01T00:00:00Z", "compliance_officer")
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen["tenant"] == T1 and seen["start"].month == 9 and seen["end"].month == 10
    t = body["totals"]
    assert t["requests"] == 2 and t["cost_real"] == 0.0018 and t["cost_hypothetical"] == 0.04
    assert t["without_reference"] == 0
    assert body["by_destination"][0]["destination_name"] == "Qwen UE"
    assert {(s["scope_type"]) for s in body["by_scope"]} == {"connection", "user"}
    assert body["truncated"] is False and body["scope"] == "tenant:*"


def test_costos_filtro_de_alcance_y_validaciones(api, monkeypatch):
    dest = _dest(api)
    _publish(api, dest)
    monkeypatch.setattr(us5, "AUDIT_SOURCE", lambda *a: [_audit_row("claude-sonnet-4-5", "claude", dest),
                                                         _audit_row("claude-sonnet-4-5", "claude", dest, key=str(uuid.uuid4()))])
    r = api.call("GET", f"/cost-comparison?scope=connection:{CONN}", "tenant_admin")
    assert r.status_code == 200 and r.json()["totals"]["requests"] == 1
    assert api.call("GET", "/cost-comparison?scope=nada", "tenant_admin").status_code == 422
    assert api.call("GET", "/cost-comparison?from=ayer", "tenant_admin").status_code == 422
    assert api.call("GET", "/cost-comparison?from=2026-10-02&to=2026-10-01", "tenant_admin").status_code == 422
    assert api.call("GET", "/cost-comparison", "client").status_code == 403
    assert api.call("GET", "/cost-comparison").status_code == 401


def test_costos_usa_budget_service_como_fuente_de_precios(api, monkeypatch):
    """Sin `PRICE` inyectado la ruta usa `BudgetService.calculate_cost` (única fuente, FR-032)."""
    dest = _dest(api)
    _publish(api, dest)
    monkeypatch.setattr(us5, "PRICE", None)
    monkeypatch.setattr(us5, "AUDIT_SOURCE", lambda *a: [_audit_row("claude-sonnet-4-5", "claude", dest, cost=0)])
    calls = []
    from src.services.budget_service import BudgetService

    def spy(model, prompt, completion):
        calls.append(model)
        return Decimal("0.01")

    monkeypatch.setattr(BudgetService, "calculate_cost", staticmethod(spy))
    t = api.call("GET", "/cost-comparison", "tenant_admin").json()["totals"]
    assert set(calls) == {"qwen", "claude-sonnet-4-5"}            # real estimado (cost 0) e hipotético
    assert t["estimated_real"] == 1 and t["cost_hypothetical"] == 0.01
