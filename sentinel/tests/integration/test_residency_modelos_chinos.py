"""T057 (057 FR-028a, FR-029–FR-031a; decisiones D1, D2, D5, D12 del owner; requisito del owner sobre modelos chinos y
económicos): residencia de modelos chinos y económicos con el seed REAL de Eleia.

Región `AMERICAS` con `masked_all` (`deploy/redirect-seeds/regions.americas.yaml`) y reglas de habilitación vacías
(`habilitacion-explicita.yaml`), cargadas con los cargadores de verdad sobre SQLite con las dos metadatas; los destinos
se dan de alta por la API del catálogo; la instantánea sale de `load_from_session` y la resolución de la pasarela real.

- un destino de API oficial china se da de alta **sin** bloqueo y sale enmascarado, y se bloquea con el analizador
  caído;
- los mismos modelos alojados en América (`azure_ai` con inferencia, entidad y control `US`; `openrouter` con lista de
  proveedores de EE. UU.) salen **enmascarados por defecto** y sin forzado solo con una relajación por destino con
  retención cero;
- una entrada con inferencia `US` y control fuera de `AMERICAS` no pierde el forzado con una relajación por región;
- los cuatro valores de `default_posture` se comportan como en T053."""
import json
import sys
import uuid
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from sentinel.catalog import habilitacion  # noqa: E402
from sentinel.catalog import models as cm  # noqa: E402
from sentinel.engine import redirect_guard as guard  # noqa: E402
from sentinel.redirect import authz, regions_seed  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402
from sentinel.redirect.plugin import RedirectPlugin  # noqa: E402
from sentinel.redirect.store import RedirectStore, load_from_session  # noqa: E402
from sentinel.tests import redirect_fixtures as fx  # noqa: E402
from sentinel.tests.catalog_fixtures import T1, create_entry, make_api  # noqa: E402

SEEDS = ROOT / "deploy" / "redirect-seeds"
REPORTE_OK = {"completed": True, "degraded": False, "detected": 1, "masked": 1, "unanalyzable": 0, "scope": "full"}
SECRETO = "sk-del-destino-de-prueba"      # secret-scanner: allow (valor inventado de un fixture de test)


@pytest.fixture
def mundo(monkeypatch):
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "latam_ar")
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)
    api = make_api(monkeypatch)
    from sentinel.access import bridge                         # sin perfiles de acceso: no hay base real
    monkeypatch.setattr(bridge, "RESOLVER", lambda tenant, **kw: None)
    monkeypatch.setattr(bridge, "RISK", lambda ident: (None, None))
    with api.Session() as s:                                  # los seeds de Eleia, con los cargadores reales
        regions_seed.seed_regions(s, regions_seed.load_seed_file(SEEDS / "regions.americas.yaml"))
        habilitacion.seed_rules(s, habilitacion.load_seed_file(SEEDS / "habilitacion-explicita.yaml"))
        s.commit()

    def sheet(entry_id, *, inference, entity, control, zdr=None):
        with api.Session() as s:
            ficha = s.get(cm.ComplianceSheet, uuid.UUID(entry_id))
            ficha.inference_jurisdiction, ficha.entity_jurisdiction = inference, entity
            ficha.control_jurisdiction, ficha.zero_data_retention = control, zdr
            s.commit()

    def alta(name, provider, real, *, jur, zdr=None, **kw):
        body = dict(name=name, provider=provider, real_model=real, protocol_family="openai_chat",
                    credential={"new": {"name": f"c-{name}", "value": SECRETO}}, **kw)
        e = create_entry(api, "tenant_admin", T1, **body)
        sheet(e["id"], inference=jur[0], entity=jur[1], control=jur[2], zdr=zdr)
        return e

    def relajar(entry_id):
        with api.Session() as s:
            s.add(rm.RedirectMaskingRelaxation(level="tenant", tenant_id=T1, entry_id=uuid.UUID(entry_id),
                                               reason="alojador nombrado con retención cero",
                                               created_by_role="compliance_officer"))
            s.commit()

    def default(valor):
        with api.Session() as s:
            s.query(rm.RedirectRegion).one().default_posture = valor
            s.commit()

    async def pedir(entry, *, nombres=None):
        """Regla → pasarela → (autorización) → verifica el guard con un informe; devuelve (decisión, grant | rechazo)."""
        with api.Session() as s:
            for tabla in (rm.RedirectRule, rm.RedirectPublishedModel, rm.RedirectPolicy):   # una regla por pedido
                s.query(tabla).delete()
            s.add_all([
                rm.RedirectPolicy(tenant_id=T1, scope_type="tenant", scope_value="*", state="on"),
            ])
            pub = rm.RedirectPublishedModel(tenant_id=T1, face="claude", public_id="claude-sonnet-4-5", family_tier="sonnet",
                                            is_family_default=True, label_mode="destination", scope_type="tenant",
                                            scope_value="*")
            s.add(pub)
            s.flush()
            s.add(rm.RedirectRule(tenant_id=T1, published_model_id=pub.id, scope_type="tenant", scope_value="*",
                                  targets=[entry["id"]], strategy="order"))
            s.commit()
        db = api.Session()
        store = RedirectStore(loader=lambda t: load_from_session(db, t, always=True), ttl=0, key_models=lambda k: None,
                              redis_factory=lambda: None,
                              decrypt=lambda blob: json.loads(blob[len("cifrado:"):][::-1]) if blob else {})
        p = RedirectPlugin(store=store, ping_after=0.05)
        c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", nlp={"region": "latam_ar"})
        resp = await p.pre_request(c)
        if resp is not None:
            return resp.status_code, None, None
        _, headers = p.pre_engine(c, {"model": "claude-sonnet-4-5", "max_tokens": 8,
                                      "messages": [{"role": "user", "content": "hola"}]}, {})
        return 200, c.routing_decision["extensions"]["redirect"], headers[authz.HEADER]

    from types import SimpleNamespace
    return SimpleNamespace(api=api, alta=alta, relajar=relajar, default=default, pedir=pedir)


def al_guard(token, report=None):
    data = {"model": authz.verify(token, key=fx.INTERNAL_KEY).model, "messages": [{"role": "user", "content": "hola"}],
            "proxy_server_request": {"headers": {authz.HEADER: token}}, "metadata": {}}
    if report is not None:
        data["metadata"]["masking_report"] = report
    return guard.apply_redirect(data, key=fx.INTERNAL_KEY, call_type="acompletion", environ={})


CHINA = ("CN", "CN", "CN")
AMERICA = ("US", "US", "US")


# ── el seed de Eleia ────────────────────────────────────────────────────────────────────────────────

def test_el_seed_deja_masked_all_y_ninguna_regla_de_habilitacion(mundo):
    with mundo.api.Session() as s:
        [region] = s.query(rm.RedirectRegion).all()
        assert (region.name, region.default_posture) == ("AMERICAS", "masked_all")
        assert s.query(cm.EnablementRule).count() == 0


# ── API oficial china ───────────────────────────────────────────────────────────────────────────────

async def test_la_api_oficial_china_se_da_de_alta_sin_bloqueo_y_sale_enmascarada(mundo):
    e = mundo.alta("DeepSeek oficial", "deepseek", "deepseek-chat", jur=CHINA)
    assert e["blocked_by_default"] is False                    # D1: ninguna regla por defecto
    status, red, token = await mundo.pedir(e)
    assert status == 200 and red["forced_masking"] is True and red["in_region"] is False
    assert red["default_posture_applied"] == "masked_all"
    assert authz.verify(token, key=fx.INTERNAL_KEY).forced_masking is True
    assert "masking_verified" not in red


async def test_la_api_oficial_china_se_bloquea_con_el_analizador_caido(mundo):
    e = mundo.alta("Qwen oficial", "openai_compatible", "qwen3-max", jur=CHINA, api_base="https://api.ejemplo.com/v1")
    _, _, token = await mundo.pedir(e)
    caido = {"completed": False, "degraded": True, "detected": 0, "masked": 0, "unanalyzable": 0, "scope": "full"}
    for informe in (caido, None):
        with pytest.raises(guard.GuardRejection) as err:
            al_guard(token, informe)
        assert err.value.code == "masking_required"
    assert al_guard(token, REPORTE_OK)["api_key"] == SECRETO


# ── los mismos modelos alojados en América ──────────────────────────────────────────────────────────

async def test_azure_ai_en_america_sale_enmascarado_por_defecto_y_sin_forzado_solo_con_relajacion(mundo):
    e = mundo.alta("Kimi en Azure", "azure_ai", "kimi-k2", jur=AMERICA, zdr=True, api_base="https://recurso.example.com")
    status, red, _ = await mundo.pedir(e)
    assert red["forced_masking"] is True and red["in_region"] is True
    mundo.relajar(e["id"])
    _, red, token = await mundo.pedir(e)
    assert red["forced_masking"] is False and red["masking_relaxation"] == "destination"
    assert authz.verify(token, key=fx.INTERNAL_KEY).forced_masking is False
    assert al_guard(token)["api_key"] == SECRETO                      # sin forzado, el guard no pide informe


async def test_openrouter_con_lista_de_proveedores_de_eeuu_sale_enmascarado_y_sin_forzado_solo_con_relajacion(mundo):
    e = mundo.alta("GLM por OpenRouter", "openrouter", "z-ai/glm-4.6", jur=AMERICA, zdr=True,
                   provider_options={"providers_allowlist": ["acme-us"]})
    _, red, _ = await mundo.pedir(e)
    assert red["forced_masking"] is True
    mundo.relajar(e["id"])
    _, red, token = await mundo.pedir(e)
    assert red["forced_masking"] is False
    grant = authz.verify(token, key=fx.INTERNAL_KEY)
    assert grant.provider_options == {"providers_allowlist": ["acme-us"]}
    assert al_guard(token)["extra_body"]["provider"]["zdr"] is True        # FR-032: también sin forzado


async def test_la_relajacion_no_tiene_efecto_si_la_ficha_ya_no_cumple(mundo):
    e = mundo.alta("Kimi en Azure", "azure_ai", "kimi-k2", jur=AMERICA, zdr=True, api_base="https://recurso.example.com")
    mundo.relajar(e["id"])
    assert (await mundo.pedir(e))[1]["forced_masking"] is False
    with mundo.api.Session() as s:
        s.get(cm.ComplianceSheet, uuid.UUID(e["id"])).zero_data_retention = False       # la ficha cambió por otra vía
        s.commit()
    assert (await mundo.pedir(e))[1]["forced_masking"] is True


# ── control fuera de la región ──────────────────────────────────────────────────────────────────────

async def test_inferencia_us_con_control_fuera_de_americas_no_pierde_el_forzado_con_la_relajacion_por_region(mundo):
    e = mundo.alta("Qwen en EE. UU.", "azure_ai", "qwen3", jur=("US", "US", "CN"), zdr=True,
                   api_base="https://recurso.example.com")
    mundo.default("masked_offregion")                                  # la relajación por región
    status, red, _ = await mundo.pedir(e)
    assert status == 200 and red["forced_masking"] is True and red["in_region"] is False
    mundo.default("masked_all")
    assert (await mundo.pedir(e))[1]["forced_masking"] is True


async def test_con_la_relajacion_por_region_un_destino_en_region_sale_sin_forzado(mundo):
    e = mundo.alta("Kimi en Azure", "azure_ai", "kimi-k2", jur=AMERICA, zdr=True, api_base="https://recurso.example.com")
    mundo.default("masked_offregion")
    _, red, _ = await mundo.pedir(e)
    assert red["forced_masking"] is False and red["masking_relaxation"] == "region"


# ── los cuatro valores de default_posture, como en T053 ─────────────────────────────────────────────

@pytest.mark.parametrize("valor,china,america", [
    ("reject_offregion", "403", (False, None)),
    ("masked_offregion", (True, None), (False, "region")),
    ("masked_all", (True, None), (True, None)),
    ("allow", (False, None), (False, None)),
])
async def test_los_cuatro_valores_de_default_posture(mundo, valor, china, america):
    mundo.default(valor)
    cn = mundo.alta("Oficial", "deepseek", "deepseek-chat", jur=CHINA)
    us = mundo.alta("Alojado", "azure_ai", "kimi-k2", jur=AMERICA, api_base="https://recurso.example.com")
    for entrada, esperado in ((cn, china), (us, america)):
        status, red, _ = await mundo.pedir(entrada)
        if esperado == "403":
            assert status == 403
        else:
            assert status == 200 and (red["forced_masking"], red.get("masking_relaxation")) == esperado
