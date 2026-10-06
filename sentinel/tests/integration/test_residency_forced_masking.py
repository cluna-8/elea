"""T056 (057 FR-027, SC-006; US3 esc. 3–5; research R23, R29; T070 de Sentinel): el enmascarado forzado de punta a punta.

Región `AMERICAS` de Eleia (`masked_all`) y un destino **dentro** de la región. Lo que prueba este archivo, de la
pasarela al guard del motor:

1. la resolución dice forzado (por la postura por defecto, sin fila alguna) y lo deja en la autorización firmada y en la
   auditoría (`forced_masking`, `default_posture_applied`, `in_region`), solo metadatos;
2. el forzado enciende el enmascarado y `nlp_fail_mode = block` (aunque la empresa tenga `redact_enabled = false` o
   `nlp_fail_mode = degrade`); ningún override del cliente, de la conexión, de las cabeceras ni del cuerpo lo relaja;
3. el guard del motor bloquea con `masking_required` si el informe no es completo, no degradado, con todo lo detectado
   enmascarado, `unanalyzable = 0` y `scope = "full"` (un informe sin `scope` no pasa), y deja pasar el que sí.

Lo que corre **en el guardrail del motor** —la batería de formatos del perfil `latam_ar` (DNI con y sin puntos,
CUIT/CUIL con y sin guiones, CBU de 22 dígitos), `system`, herramientas, adjuntos, no analizable— es la costura S14
(T096/T097, otro worker): su estado se vigila en `test_el_guardrail_del_motor_lee_la_senal_de_s14` (queda en `xfail`
hasta que se integre; la señal en `pre_engine` y el contrato son de esa tarea). Mientras tanto un pedido forzado con
un guardrail anterior a S14 **se bloquea** (informe sin `scope`): falla cerrado, nunca abierto."""
import json
from pathlib import Path

import pytest

from sentinel.engine import redirect_guard as guard
from sentinel.redirect import authz
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.tests import redirect_fixtures as fx
from sentinel.tests import residency_fixtures as rf

ROOT = Path(__file__).resolve().parents[3]
DNI = "30.123.456"
REPORTE_OK = {"completed": True, "degraded": False, "detected": 2, "masked": 2, "unanalyzable": 0, "scope": "full"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "latam_ar")


def snapshot(default="masked_all", *, destino=None, postures=(), relaxations=()):
    dest = {**fx.DEST_ANTHROPIC, "id": "d-us", "level": "tenant", "tenant_id": fx.TENANT,
            "inference_jurisdiction": "US", "entity_jurisdiction": "US", "control_jurisdiction": "US", **(destino or {})}
    snap = fx.snapshot("on", regions=[rf.region_row(default)], targets=("d-us",), claude_targets=("d-us",), offers=(),
                       postures=postures, relaxations=relaxations)
    return snap.__class__(**{**snap.__dict__, "destinations": {**snap.destinations, "d-us": dest},
                             "credentials": {**snap.credentials, "d-us": json.dumps({"api_key": "sk-destino-us"})}})


async def resolver(snap, **ident):
    p = RedirectPlugin(store=fx.store(snap), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", nlp={"region": "latam_ar", **ident.pop("nlp", {})}, **ident)
    assert await p.pre_request(c) is None
    return p, c


def firmada(p, c):
    _, headers = p.pre_engine(c, {"model": "claude-sonnet-4-5", "max_tokens": 8,
                                  "messages": [{"role": "user", "content": "hola"}]}, {})
    return headers[authz.HEADER], authz.verify(headers[authz.HEADER], key=fx.INTERNAL_KEY)


# ── 1. la resolución ────────────────────────────────────────────────────────────────────────────────

async def test_masked_all_fuerza_el_destino_dentro_de_la_region_sin_ninguna_fila():
    p, c = await resolver(snapshot("masked_all"))
    red = c.routing_decision["extensions"]["redirect"]
    assert red["forced_masking"] is True and red["in_region"] is True
    assert red["default_posture_applied"] == "masked_all"
    _, grant = firmada(p, c)
    assert grant.forced_masking is True


async def test_masked_offregion_no_fuerza_dentro_de_la_region_y_no_hay_nada_que_verificar():
    p, c = await resolver(snapshot("masked_offregion"))
    assert "forced_masking" in c.routing_decision["extensions"]["redirect"]
    _, grant = firmada(p, c)
    assert grant.forced_masking is False
    assert c.routing_decision["extensions"]["redirect"]["masking_relaxation"] == "region"


async def test_la_auditoria_lleva_metadatos_nunca_texto_ni_valores():
    _, c = await resolver(snapshot("masked_all"))
    texto = json.dumps(c.routing_decision)
    assert DNI not in texto and "sk-destino-us" not in texto and "hola" not in texto


# ── 2. el forzado enciende el enmascarado y nada lo relaja ──────────────────────────────────────────

async def test_el_forzado_enciende_el_enmascarado_y_el_modo_bloqueo():
    _, c = await resolver(snapshot("masked_all"))
    assert c.governance_overrides == {"pii_masking": True, "nlp_fail_mode": "block", "masking_scope": "full"}
    assert c.routing_decision["extensions"]["redirect"]["masking_scope"] == "full"


async def test_sin_forzado_la_pasarela_no_toca_la_configuracion_de_la_empresa():
    _, c = await resolver(snapshot("masked_offregion"))
    assert "pii_masking" not in c.governance_overrides


async def test_con_nlp_fail_mode_degrade_de_la_empresa_el_forzado_sigue_en_bloqueo():
    _, c = await resolver(snapshot("masked_all"), nlp={"nlp_fail_mode": "degrade"})
    assert c.governance_overrides["nlp_fail_mode"] == "block"


async def test_un_override_del_cliente_no_relaja_el_forzado():
    p = RedirectPlugin(store=fx.store(snapshot("masked_all")), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", nlp={"region": "latam_ar"},
               headers={"x-sentinel-redact": "off", "x-sentinel-masking": "off", "x-redirect-forced": "0"})
    c.body = {"governance_overrides": {"pii_masking": False}, "forced_masking": False}
    assert await p.pre_request(c) is None
    assert c.governance_overrides["pii_masking"] is True
    _, grant = firmada(p, c)
    assert grant.forced_masking is True


async def test_un_destino_con_inferencia_sin_cargar_se_rechaza_aunque_haya_una_fila_off_y_una_relajacion():
    snap = snapshot("masked_all", destino={"inference_jurisdiction": None},
                    postures=[{**rf.row("off"), "tenant_id": fx.TENANT, "id": "x"}],
                    relaxations=[rf.relaxation("d-us")])
    p = RedirectPlugin(store=fx.store(snap), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", nlp={"region": "latam_ar"})
    resp = await p.pre_request(c)
    assert resp is not None and resp.status_code == 403


# ── 3. el guard del motor verifica el informe ───────────────────────────────────────────────────────

def al_guard(token, report=None, *, call_type="anthropic_messages"):
    data = {"model": "rdx-anthropic/claude-real", "max_tokens": 8, "messages": [{"role": "user", "content": "hola"}],
            "proxy_server_request": {"headers": {authz.HEADER: token}}, "metadata": {}, "litellm_metadata": {}}
    if report is not None:
        data["litellm_metadata"]["masking_report"] = report
    return guard.apply_redirect(data, key=fx.INTERNAL_KEY, call_type=call_type, environ={"REDIRECT_CRED_ANT": "k"})


async def test_el_guard_deja_pasar_un_informe_completo_con_alcance_completo():
    p, c = await resolver(snapshot("masked_all"))
    token, _ = firmada(p, c)
    out = al_guard(token, REPORTE_OK)
    rd = out["litellm_metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert rd["masking_verified"] is True and rd["masking_scope"] == "full"


@pytest.mark.parametrize("informe", [
    None,
    {k: v for k, v in REPORTE_OK.items() if k != "scope"},                 # guardrail anterior a S14: no prueba el alcance
    {**REPORTE_OK, "scope": "user"},
    {**REPORTE_OK, "unanalyzable": 1},
    {**REPORTE_OK, "degraded": True},                                       # analizador degradado
    {**REPORTE_OK, "completed": False},                                     # analizador caído
    {**REPORTE_OK, "masked": 1},                                            # lo detectado no se enmascaró
])
async def test_el_guard_bloquea_con_masking_required(informe):
    p, c = await resolver(snapshot("masked_all"))
    token, _ = firmada(p, c)
    with pytest.raises(guard.GuardRejection) as e:
        al_guard(token, informe)
    assert e.value.code == "masking_required"
    assert "30.123" not in str(e.value.message)


async def test_la_respuesta_de_bloqueo_no_nombra_destinos_ni_valores():
    p, c = await resolver(snapshot("masked_all"))
    token, _ = firmada(p, c)
    with pytest.raises(guard.GuardRejection) as e:
        al_guard(token, None)
    assert "d-us" not in e.value.message and "AMERICAS" not in e.value.message


async def test_el_forzado_por_la_postura_por_defecto_exige_lo_mismo_que_el_de_una_fila():
    con_fila = snapshot("allow", postures=[{**rf.row("offregion_masked", ["AR"]), "tenant_id": fx.TENANT, "id": "f"}])
    for snap in (snapshot("masked_all"), con_fila):
        p, c = await resolver(snap)
        token, grant = firmada(p, c)
        assert grant.forced_masking is True
        with pytest.raises(guard.GuardRejection):
            al_guard(token, {**REPORTE_OK, "scope": "user"})


# ── lo que es del guardrail del motor (S14, T096/T097) ──────────────────────────────────────────────

@pytest.mark.xfail(strict=False, reason="S14 (T096/T097, otro worker): el guardrail lee `sentinel_forced_masking` y su alcance completo")
def test_el_guardrail_del_motor_lee_la_senal_de_s14():
    texto = (ROOT / "litellm" / "extensions" / "sentinel_guardrail.py").read_text(encoding="utf-8")
    assert "sentinel_forced_masking" in texto and "unanalyzable" in texto


@pytest.mark.xfail(strict=False, reason="T097 (otro worker): patrón de CUIT/CUIL sin guiones del perfil latam_ar (hoy solo con guiones)")
def test_el_patron_de_cuit_sin_guiones_existe_en_el_perfil_latam_ar():
    from extensions import sentinel_guardian_policy as policy
    detectado = policy.detect_entities("mi cuit es 20301234567", region="latam_ar") if hasattr(policy, "detect_entities") else []
    assert detectado
