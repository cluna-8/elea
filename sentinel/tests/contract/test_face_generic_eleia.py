"""Contrato de la cara OpenAI genérica en Eleia (contracts/cara-generica.md; 057 T046; US5 esc. 1, FR-055).

Pasarela REAL del backend + motor falso. `GET /gw/v1/models` decide la vista por la cabecera `anthropic-version`:
sin ella, solo los alias `openai_generic` del alcance de quien pregunta, con `owned_by` neutro; con ella, la vista
Claude; quien no está en el alcance de un alias no lo ve (y nunca ve un destino ni un id interno).
"""
import time
from pathlib import Path

import pytest

from sentinel.redirect import authz
from sentinel.tests import gw_harness as h
from sentinel.tests import redirect_fixtures as fx

ROOT = Path(__file__).resolve().parents[3]
PROHIBIDOS = [ln.strip().lower() for ln in (ROOT / "deploy/release/checks/prohibited_names.txt").read_text(
    encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
G_CODE, G_OTHER = "55555555-5555-5555-5555-555555555555", "66666666-6666-6666-6666-666666666666"
AUTH = {"Authorization": f"Bearer {h.VK}"}


@pytest.fixture
def env(monkeypatch):
    e = h.gateway_env(monkeypatch)
    yield e
    h.close_env()


def _con_alias(*extra_published, extra_rules=()):
    """El estado de fábrica de los fixtures (alias `pro` y `claude-sonnet-4-5`, de toda la empresa) más lo que se pida."""
    snap = fx.snapshot("on")
    return snap.__class__(**{**snap.__dict__, "published": snap.published + tuple(extra_published),
                             "rules": snap.rules + tuple(extra_rules)})


def _alias_de_grupo(public_id, group, *, face="openai_generic", pid=None):
    pid = pid or f"p-{public_id}"
    pub = {"id": pid, "tenant_id": fx.TENANT, "scope_type": "group", "scope_value": group, "face": face,
           "public_id": public_id}
    rule = {"id": f"r-{public_id}", "tenant_id": fx.TENANT, "scope_type": "group", "scope_value": group,
            "published_model_id": pid, "targets": ["d-chat"]}
    return pub, rule


def _ids(resp):
    return [m["id"] for m in resp.json()["data"]]


# ── sin `anthropic-version`: la vista genérica ─────────────────────────────────

def test_sin_anthropic_version_lista_solo_los_alias_genericos_con_owned_by_neutro(env):
    env.register(fx.snapshot("on"))
    t0 = time.perf_counter()
    r = env.client.get("/gw/v1/models", headers=AUTH)
    assert time.perf_counter() - t0 < 1.0 and r.status_code == 200
    body = r.json()
    assert body["object"] == "list" and [m["id"] for m in body["data"]] == ["pro"]
    (m,) = body["data"]
    assert m["object"] == "model" and m["owned_by"] == "organization" and isinstance(m["created"], int)
    obligatorios = {"id", "object", "created", "owned_by"}
    opcionales = {"context_length", "max_output"}
    assert obligatorios <= set(m), "forma del contrato: faltan campos obligatorios"
    assert set(m) - obligatorios <= opcionales, "forma del contrato, sin campos de la cara Claude"
    assert all(isinstance(m[k], int) for k in set(m) & opcionales), "context_length/max_output son enteros"


def test_la_vista_generica_no_lleva_ids_de_la_cara_claude_ni_destinos_ni_internos(env):
    env.register(fx.snapshot("on"))
    ids = _ids(env.client.get("/gw/v1/models", headers=AUTH))
    assert "claude-sonnet-4-5" not in ids and "modelo-base" not in ids
    assert not any(i.startswith("rdx-") for i in ids)


@pytest.mark.parametrize("grupo,esperados", [(G_CODE, ["alfa", "pro", "zeta"]), (G_OTHER, ["pro"]), (None, ["pro"])],
                         ids=["del-grupo", "otro-grupo", "sin-grupo"])
def test_otro_grupo_no_ve_los_alias_del_grupo(monkeypatch, grupo, esperados):
    pub_a, rule_a = _alias_de_grupo("zeta", G_CODE)
    pub_b, rule_b = _alias_de_grupo("alfa", G_CODE)
    e = h.gateway_env(monkeypatch, ident=fx.ident(group_id=grupo))
    try:
        e.register(_con_alias(pub_a, pub_b, extra_rules=(rule_a, rule_b)))
        r = e.client.get("/gw/v1/models", headers=AUTH)
        assert r.status_code == 200 and _ids(r) == esperados
    finally:
        h.close_env()


def test_un_alias_exclusivo_de_un_grupo_no_se_redirige_para_otro(monkeypatch):
    pub, rule = _alias_de_grupo("solo-codigo", G_CODE)
    e = h.gateway_env(monkeypatch, ident=fx.ident(group_id=G_OTHER))
    try:
        e.register(_con_alias(pub, extra_rules=(rule,)))
        e.client.post("/gw/v1/chat/completions", headers=AUTH,
                      json={"model": "solo-codigo", "messages": [{"role": "user", "content": "hola"}]})
        sent = e.engine.sent[-1]
        # para este grupo no es un id publicado: sale tal cual, sin destino ni autorización interna
        assert sent["body"]["model"] == "solo-codigo" and authz.HEADER not in {k.lower() for k in sent["headers"]}
    finally:
        h.close_env()


# ── con `anthropic-version`: la vista Claude ───────────────────────────────────

def test_con_anthropic_version_es_la_vista_claude_y_sin_los_alias_genericos(env):
    env.register(fx.snapshot("on"))
    r = env.client.get("/gw/v1/models", headers={**AUTH, "anthropic-version": "2023-06-01"})
    body = r.json()
    assert [m["id"] for m in body["data"]] == ["claude-sonnet-4-5"]
    assert body["data"][0]["type"] == "model" and body["has_more"] is False


def test_la_cabecera_se_reconoce_sin_importar_las_mayusculas(env):
    env.register(fx.snapshot("on"))
    r = env.client.get("/gw/v1/models", headers={**AUTH, "Anthropic-Version": "2023-06-01"})
    assert _ids(r) == ["claude-sonnet-4-5"]


# ── política apagada y neutralidad ─────────────────────────────────────────────

def test_con_la_politica_apagada_no_aparece_ningun_alias_y_se_oculta_lo_interno(env):
    env.register(fx.snapshot("off"))
    ids = _ids(env.client.get("/gw/v1/models", headers=AUTH))
    assert ids == ["modelo-base"], "la lista de siempre, sin ids de destino"


def test_el_listado_generico_no_nombra_destinos_ni_internos(env):
    env.register(fx.snapshot("on"))
    texto = env.client.get("/gw/v1/models", headers=AUTH).text.lower()
    assert "qwen" not in texto and "destino" not in texto and "d-chat" not in texto and "rdx-" not in texto
    assert not [n for n in PROHIBIDOS if n in texto], "nombres de componentes internos"


def test_el_listado_claude_no_nombra_ids_internos_ni_componentes_prohibidos(env):
    # la etiqueta de la vista Claude sí dice qué destino sirve (FR-034); lo interno, no
    env.register(fx.snapshot("on"))
    texto = env.client.get("/gw/v1/models", headers={**AUTH, "anthropic-version": "2023-06-01"}).text.lower()
    assert "rdx-" not in texto and "d-chat" not in texto
    assert not [n for n in PROHIBIDOS if n in texto], "nombres de componentes internos"
