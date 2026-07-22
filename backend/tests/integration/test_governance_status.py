"""Integration del estado honesto de gobernanza (spec 027, US1/T011).

Cubre los casos donde el producto **hoy miente** y la US1 obliga a decir la verdad:

- el motor caído no puede producir capas "aplicándose" (fail-closed, D4);
- una capa apagada por decisión no genera un falso "te falta credencial" (§4.1 regla 1);
- una capa delegada al proveedor upstream se explica como delegación, no como carencia
  (FR-013) — y no le pide al admin una credencial que no cambiaría nada;
- una capa que declara un servicio propio sin confirmar jamás llega a "aplicándose"
  (regla 2b);
- el gate de tenant no se apoya en un tier de RBAC que todavía no existe (garantía (g));
- y ninguna respuesta lleva nombres de proveedor ni restos de excepción (Constitución VII,
  garantía (f)).

La sonda se **mockea**: apagar el contenedor del motor haría la suite dependiente del
entorno y de un sleep de 35 s. Lo que hay que probar es el cálculo ante una sonda que no
confirma, y eso es exactamente lo que el doble reproduce.
"""
import hashlib
import uuid

import pytest

from migration_harness import require_postgres
from seat_gate_harness import admin_headers, build_app_client

require_postgres()

DB = "basa_test_governance_status_integration"

# Términos que JAMÁS pueden aparecer en una respuesta del producto (Constitución VII:
# ningún nombre de proveedor externo en API, errores, logs ni UI) más los marcadores
# típicos de un texto de excepción reenviado (garantía (f)).
PROHIBIDOS = ("litellm", "presidio", "anthropic", "openai", "azure", "bedrock", "lakera",
              "llamaguard", "promptguard", "traceback", "httpx", "connecterror",
              "http://", "https://", "content_filter")


class _Probe:
    def __init__(self, confirmed, names=()):
        self.confirmed = confirmed
        self.names = frozenset(names)

    def has(self, name):
        return bool(self.confirmed and name and name in self.names)


MOTOR_ARRIBA = _Probe(True, {"basa-guardian"})
MOTOR_CAIDO = _Probe(False)


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


@pytest.fixture(autouse=True)
def _limpiar(harness):
    yield
    from src.models.governance import GovernanceProfile
    from src.models.guardian import Guardian
    db = factory_de(harness)
    try:
        db.query(Guardian).delete()
        db.query(GovernanceProfile).delete()
        db.commit()
    finally:
        db.close()


def factory_de(harness):
    return harness[1]()


def set_probe(monkeypatch, probe):
    from src.api import governance

    async def _fake(**_kwargs):
        return probe

    monkeypatch.setattr(governance.ai_engine_client, "probe_loaded_guardrails", _fake)


def seed_guardian(harness, guardian_type, *, engine_name=None, con_credencial=False):
    from src.models.guardian import Guardian
    db = factory_de(harness)
    try:
        db.add(Guardian(name=f"instancia-{guardian_type}", guardian_type=guardian_type,
                        is_active=True, config={}, engine_guardrail_name=engine_name,
                        service_api_key_encrypted="cifrada" if con_credencial else None))
        db.commit()
    finally:
        db.close()


def seed_decision(harness, scope_type, scope_value, layer_key, decision):
    from src.models.governance import GovernanceProfile
    db = factory_de(harness)
    try:
        db.add(GovernanceProfile(scope_type=scope_type, scope_value=scope_value,
                                 layer_key=layer_key, decision=decision,
                                 updated_by="test"))
        db.commit()
    finally:
        db.close()


def capas_por_clave(client, headers, **params):
    resp = client.get("/api/v1/governance/status", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return {c["layer_key"]: c for c in resp.json()["layers"]}


# ── Fail-closed: el motor caído nunca produce capas activas ───────────────────────


def test_motor_caido_tumba_a_no_disponible_todas_las_capas_del_plano_motor(harness, monkeypatch):
    client, _, headers = harness
    set_probe(monkeypatch, MOTOR_CAIDO)

    capas = capas_por_clave(client, headers, mode="gateway-models")

    del_motor = [c for c in capas.values() if "engine" in c["planes"]]
    assert del_motor
    for capa in del_motor:
        assert capa["estado_efectivo"] == "no_disponible", capa["layer_key"]
        assert capa["motivo"]
    assert not [c for c in capas.values() if c["estado_efectivo"] == "aplicandose"
                and "engine" in c["planes"]]


def test_motor_caido_y_motor_arriba_dan_motivos_DISTINTOS(harness, monkeypatch):
    """'no pudimos confirmar' ≠ 'el motor no la tiene cargada': son dos acciones distintas
    para el admin, y colapsarlas es la mitad de la mentira que 027 borra."""
    client, _, headers = harness
    seed_guardian(harness, "openai_moderation", engine_name="litellm_content_filter",
                  con_credencial=True)
    seed_decision(harness, "tenant_default", "*", "content_moderation", "on")

    set_probe(monkeypatch, MOTOR_CAIDO)
    caido = capas_por_clave(client, headers, mode="gateway-models")["content_moderation"]
    set_probe(monkeypatch, MOTOR_ARRIBA)
    arriba = capas_por_clave(client, headers, mode="gateway-models")["content_moderation"]

    assert caido["estado_efectivo"] == arriba["estado_efectivo"] == "no_disponible"
    assert caido["motivo"] != arriba["motivo"]


def test_el_piso_sigue_apareciendo_con_el_motor_caido(harness, monkeypatch):
    """Garantía (b): el piso no desaparece del relato porque el motor no conteste — cambia
    su ESTADO, nunca su decisión."""
    client, _, headers = harness
    set_probe(monkeypatch, MOTOR_CAIDO)

    capas = capas_por_clave(client, headers, mode="gateway-models")

    piso = [c for c in capas.values() if c["tier"] == "floor"]
    assert len(piso) == 4
    assert all(c["decision_resuelta"] == "on" and c["origen"] == "floor" for c in piso)


# ── Regla 1: apagada ≠ "te falta credencial" ──────────────────────────────────────


def test_capa_apagada_sin_credencial_es_no_disponible_no_requiere_credencial(harness, monkeypatch):
    client, _, headers = harness
    seed_guardian(harness, "azure_content_safety", engine_name="azure/text_moderations")
    set_probe(monkeypatch, MOTOR_ARRIBA)

    capa = capas_por_clave(client, headers, mode="gateway-models")["content_safety"]

    assert capa["decision_resuelta"] == "off"
    assert capa["estado_efectivo"] == "no_disponible"


def test_capa_encendida_sin_credencial_si_es_requiere_credencial(harness, monkeypatch):
    client, _, headers = harness
    seed_guardian(harness, "azure_content_safety", engine_name="azure/text_moderations")
    seed_decision(harness, "connection_mode", "gateway-models", "content_safety", "on")
    set_probe(monkeypatch, MOTOR_ARRIBA)

    capa = capas_por_clave(client, headers, mode="gateway-models")["content_safety"]

    assert capa["decision_resuelta"] == "on" and capa["origen"] == "connection_mode"
    assert capa["estado_efectivo"] == "requiere_credencial"


# ── Regla 2: delegación (FR-013) ──────────────────────────────────────────────────


def test_capa_delegable_encendida_en_suscripcion_es_delegada_no_requiere_credencial(harness, monkeypatch):
    """La protección la aporta el extremo upstream: pedir credencial ahí sería pedirle al
    admin que cargue algo que no cambiaría nada del tráfico."""
    client, _, headers = harness
    seed_guardian(harness, "openai_moderation", engine_name="litellm_content_filter")
    seed_decision(harness, "tenant_default", "*", "content_moderation", "on")
    set_probe(monkeypatch, MOTOR_ARRIBA)

    capa = capas_por_clave(client, headers, mode="subscription")["content_moderation"]

    assert capa["estado_efectivo"] == "delegada"
    assert capa["motivo"].startswith("En modo suscripción")
    assert "piso" in capa["motivo"], "el copy distingue 'no la aplicamos' de 'desprotegido'"


def test_la_misma_capa_no_es_delegada_hacia_modelos_de_la_pasarela(harness, monkeypatch):
    """La delegación es propiedad del MODO: sin proveedor upstream que modere, no hay a
    quién delegar."""
    client, _, headers = harness
    seed_guardian(harness, "openai_moderation", engine_name="litellm_content_filter")
    seed_decision(harness, "tenant_default", "*", "content_moderation", "on")
    set_probe(monkeypatch, MOTOR_ARRIBA)

    capa = capas_por_clave(client, headers, mode="gateway-models")["content_moderation"]

    assert capa["estado_efectivo"] == "requiere_credencial"


# ── Regla 2b: servicio propio sin confirmar ───────────────────────────────────────


def test_requires_service_sin_confirmar_jamas_es_aplicandose():
    """Regla 2b sobre la función pura: el código puede estar en el proceso y el servicio
    propio caído igual. Se construye una capa sintética porque el catálogo inicial no
    declara ``requires_service`` — la regla existe para cuando la 016 lo declare."""
    from src.services.governance_catalog import ALL_PLANES, GovernanceLayer
    from src.services.governance_status import (ESTADO_DEGRADADA, ESTADO_NO_DISPONIBLE,
                                                StatusInputs, compute_layer_state)

    capa = GovernanceLayer(layer_key="pii_masking", tier="optional", planes=ALL_PLANES,
                           requires_credential=False, delegable_to_upstream=False,
                           default_decision="on", guardian_types=(),
                           requires_service="nlp-sidecar")
    probe = _Probe(True, {"basa-guardian"})
    inputs = StatusInputs(engine_names={"pii_masking": frozenset({"basa-guardian"})})

    estado, motivo = compute_layer_state(capa, desired=True, mode="gateway-models",
                                         probe=probe, inputs=inputs)
    assert estado == ESTADO_NO_DISPONIBLE and motivo

    # Si VENÍA aplicándose y el servicio se cae, el estado honesto es degradada.
    con_evidencia = StatusInputs(engine_names=inputs.engine_names,
                                 evidence=frozenset({"pii_masking"}))
    estado, _ = compute_layer_state(capa, desired=True, mode="gateway-models",
                                    probe=probe, inputs=con_evidencia)
    assert estado == ESTADO_DEGRADADA


# ── Gate de tenant y de rol ───────────────────────────────────────────────────────


def test_tenant_id_en_instalacion_multi_tenant_da_403(harness, monkeypatch):
    """Garantía (g): el tier super-admin es forward-looking; hasta que exista, ninguna
    lectura cross-tenant se apoya en él."""
    from src.models.tenant import Tenant
    client, _, headers = harness
    set_probe(monkeypatch, MOTOR_ARRIBA)
    db = factory_de(harness)
    otro = Tenant(name="Otra Organización", slug=f"otra-{uuid.uuid4().hex[:8]}")
    try:
        db.add(otro)
        db.commit()
        otro_id = str(otro.id)
    finally:
        db.close()

    try:
        resp = client.get("/api/v1/governance/status", headers=headers,
                          params={"tenant_id": otro_id})
        assert resp.status_code == 403
        # …y el propio tenant se sigue consultando sin problema (sin el parámetro).
        assert client.get("/api/v1/governance/status", headers=headers).status_code == 200
    finally:
        db = factory_de(harness)
        try:
            db.query(Tenant).filter(Tenant.id == uuid.UUID(otro_id)).delete()
            db.commit()
        finally:
            db.close()


def test_rol_no_admin_da_403(harness, monkeypatch):
    from src.models.user import User
    client, _, _ = harness
    set_probe(monkeypatch, MOTOR_ARRIBA)
    db = factory_de(harness)
    usuario = f"dev-{uuid.uuid4().hex[:8]}"
    try:
        db.add(User(username=usuario, email=f"{usuario}@basa.com.ar",
                    password_hash=hashlib.sha256(b"secreta").hexdigest(),
                    role="client", display_label="developer", is_active=True))
        db.commit()
    finally:
        db.close()

    login = client.post("/api/v1/users/login",
                        json={"username": usuario, "password": "secreta"})
    assert login.status_code == 200, login.text
    token = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.get("/api/v1/governance/status", headers=token).status_code == 403


# ── White-label (Constitución VII, garantía (f)) ──────────────────────────────────


def test_ninguna_respuesta_lleva_nombres_de_proveedor_ni_restos_de_excepcion(harness, monkeypatch):
    """Test negativo barriendo el JSON completo, en los dos escenarios que más tientan a
    filtrar: el cableado de proveedor sembrado y el motor caído (donde el camino fácil es
    reenviar el mensaje de la excepción)."""
    client, _, headers = harness
    for tipo, nombre in (("openai_moderation", "litellm_content_filter"),
                         ("lakera_prompt_injection", "promptguard"),
                         ("azure_content_safety", "azure/text_moderations"),
                         ("bedrock_guardrails", "bedrock_guardrails"),
                         ("presidio", None)):
        seed_guardian(harness, tipo, engine_name=nombre, con_credencial=True)
    seed_decision(harness, "tenant_default", "*", "content_moderation", "on")
    seed_decision(harness, "tenant_default", "*", "provider_guardrails", "on")

    for probe in (MOTOR_ARRIBA, MOTOR_CAIDO):
        set_probe(monkeypatch, probe)
        for params in ({}, {"mode": "subscription"},
                       {"mode": "gateway-models", "surface": "claude-code"}):
            resp = client.get("/api/v1/governance/status", headers=headers, params=params)
            assert resp.status_code == 200, resp.text
            crudo = resp.text.lower()
            for termino in PROHIBIDOS:
                assert termino not in crudo, f"{termino} filtrado con params={params}"


def test_el_422_nombra_el_valor_recibido_y_nada_mas(harness, monkeypatch):
    """Garantía (e) + (f) juntas: el error nombra el valor que mandó el cliente y los
    valores admitidos — nunca el estado interno del motor ni un texto de excepción."""
    client, _, headers = harness
    set_probe(monkeypatch, MOTOR_CAIDO)

    resp = client.get("/api/v1/governance/status", headers=headers,
                      params={"mode": "modo-inventado"})

    assert resp.status_code == 422
    detalle = resp.json()["detail"]
    assert "modo-inventado" in detalle
    for termino in PROHIBIDOS:
        assert termino not in detalle.lower()
