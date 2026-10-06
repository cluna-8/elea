"""T094 (057 QA B2, QA v2 N5; research R28): `GET /api/v1/redirect/health` y los tres sitios que resolvían `eu`.

El estado de la región sale sin sesión y sin datos de empresas: 200 con la fila de región, 503 `region_row_missing`
(sin fila, incluida `eu` resuelta sin fila: QA v2 N9) o `region_unresolved` (sin perfil). El plugin, `list_postures`
y la prueba de fidelidad (`run_fidelity`) usan la misma resolución: el panel no muestra `allowlist[EU]` mientras el
tráfico da 403."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redirect_api_fixtures as fx  # noqa: E402
import redirect_fixtures as rf  # noqa: E402

from sentinel.redirect import plugin as redirect_plugin  # noqa: E402
from sentinel.redirect import residency  # noqa: E402


def test_health_200_con_la_fila_de_region(monkeypatch):
    api = fx.make_api(monkeypatch, profile="latam_ar", region="masked_all", jurisdictions=("US", "AR"))
    r = api.call("GET", "/health", None)
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_health_503_sin_fila_de_region(monkeypatch):
    api = fx.make_api(monkeypatch, profile="latam_ar", region=None)
    r = api.call("GET", "/health", None)
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "reason": "region_row_missing"}


def test_health_503_con_eu_resuelta_sin_fila_es_row_missing_no_unresolved(monkeypatch):
    """`compose.prod.yml` inyecta `SENTINEL_ENTITY_REGION=eu`: nunca queda sin resolver (QA v2 N9)."""
    api = fx.make_api(monkeypatch, profile="eu", region=None)
    assert api.call("GET", "/health", None).json()["reason"] == "region_row_missing"


def test_health_503_sin_perfil_es_region_unresolved(monkeypatch):
    api = fx.make_api(monkeypatch, profile=None, region=None)
    r = api.call("GET", "/health", None)
    assert r.status_code == 503 and r.json() == {"status": "degraded", "reason": "region_unresolved"}


def test_health_sin_perfil_aunque_haya_una_fila_sigue_sin_resolver(monkeypatch):
    api = fx.make_api(monkeypatch, profile=None, region="masked_all")
    assert api.call("GET", "/health", None).json()["reason"] == "region_unresolved"


def test_health_no_lleva_datos_de_empresas_ni_pide_sesion(monkeypatch):
    api = fx.make_api(monkeypatch, profile="latam_ar", region=None)
    api.seed(name="Secreto Corp", level="tenant")
    texto = json.dumps(api.call("GET", "/health", None).json())
    assert "Secreto" not in texto and "latam" not in texto.lower() and str(fx.T1) not in texto


def test_health_con_las_tablas_ausentes_degrada_sin_500(monkeypatch):
    api = fx.make_api(monkeypatch, profile="latam_ar", region=None)
    with api.Session() as s:
        s.execute(__import__("sqlalchemy").text("DROP TABLE sentinel_redirect_region"))
        s.commit()
    r = api.call("GET", "/health", None)
    assert r.status_code == 503 and r.json()["reason"] == "region_row_missing"


# ── los tres sitios usan la misma resolución ────────────────────────────────────────────────────────

def test_el_plugin_no_cae_a_eu(monkeypatch):
    monkeypatch.delenv("SENTINEL_ENTITY_REGION", raising=False)
    assert redirect_plugin.tenant_region({"tenant_id": "t"}) is None
    assert redirect_plugin.tenant_region({"tenant_id": "t", "nlp": {"region": "latam_ar"}}) == "latam_ar"
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "us")
    assert redirect_plugin.tenant_region({"tenant_id": "t", "nlp": {}}) == "us"


def test_list_postures_muestra_lo_mismo_que_hace_el_trafico_sin_region(monkeypatch):
    """Sin región resuelta el tráfico redirigido da 403: el panel no puede mostrar `allowlist[EU]`."""
    api = fx.make_api(monkeypatch, profile=None, region=None)
    eff = api.call("GET", "/postures", "tenant_admin").json()["effective_tenant_redirected"]
    assert eff["region_status"] == "region_unresolved" and eff["jurisdictions"] == []
    assert eff["default_applied"] == "code_fallback"
    p = residency.effective_posture([], residency.RequestScope(tenant_id=str(fx.T1)), redirected=True,
                                    tenant_region=redirect_plugin.tenant_region({"tenant_id": str(fx.T1)}))
    assert p.blocked is True


def test_list_postures_sin_fila_muestra_el_respaldo_con_el_alcance_de_la_region(monkeypatch):
    api = fx.make_api(monkeypatch, profile="latam_ar", region=None)
    eff = api.call("GET", "/postures", "tenant_admin").json()["effective_tenant_redirected"]
    assert eff["default_applied"] == "code_fallback" and eff["region_status"] == "region_row_missing"
    assert eff["forced_everywhere"] is True and eff["scope_cap"] == ["AR", "LATAM"]


def test_list_postures_acepta_la_region_por_parametro_y_nunca_cae_a_eu(monkeypatch):
    api = fx.make_api(monkeypatch, profile=None, region="reject_offregion")
    eff = api.call("GET", "/postures", "tenant_admin", params={"region": "eu"}).json()["effective_tenant_redirected"]
    assert eff["region_status"] == "region_row_missing" and eff["scope_cap"] == ["EU"]


def test_resolve_preview_sin_region_no_inventa_eu(monkeypatch):
    api = fx.make_api(monkeypatch, profile=None, region=None)
    posture = None
    dest = api.seed(level="tenant", inference="DE", entity="DE")
    api.call("PUT", "/policy/tenant/*", "tenant_admin", json={"state": "on"})
    pub = api.call("POST", "/published-models", "tenant_admin", json={"face": "openai_generic", "public_id": "pro"})
    api.call("POST", "/rules", "tenant_admin", json={"published_model_id": pub.json()["id"], "targets": [dest["id"]]})
    r = api.call("POST", "/resolve-preview", "tenant_admin", json={"face": "openai_generic", "public_id": "pro"})
    assert r.status_code == 200 and r.json()["result"] == "unavailable" and r.json()["error_class"] == "residency"
    assert posture is None


def test_resolve_preview_con_region_resuelve_y_dice_el_forzado(monkeypatch):
    api = fx.make_api(monkeypatch, profile="eu", region="masked_all", jurisdictions=("EU",))
    dest = api.seed(level="tenant", inference="DE", entity="DE")
    api.call("PUT", "/policy/tenant/*", "tenant_admin", json={"state": "on"})
    pub = api.call("POST", "/published-models", "tenant_admin", json={"face": "openai_generic", "public_id": "pro"})
    api.call("POST", "/rules", "tenant_admin", json={"published_model_id": pub.json()["id"], "targets": [dest["id"]]})
    r = api.call("POST", "/resolve-preview", "tenant_admin", json={"face": "openai_generic", "public_id": "pro"})
    assert r.json()["result"] == "resolved" and r.json()["forced_masking"] is True
    assert r.json()["posture"]["default_applied"] == "masked_all"


def test_run_fidelity_usa_la_misma_resolucion(monkeypatch):
    from sentinel.redirect.api import us5
    import inspect
    src = inspect.getsource(us5.run_fidelity)
    assert "resolve_profile" in src and '"eu"' not in src
