"""Guardianes honestos: disponibilidad real y rechazo de activación (spec 031, US3/T012).

Lo que se prueba es el defecto exacto de la spec §6: los guardianes de nube apuntan por
nombre a guardrails que el motor no tiene cargados, el motor **ignora en silencio** los
nombres que no conoce, y la API devolvía 200 al activarlos — un interruptor verde sobre
algo que no toca el tráfico. FR-007 lo convierte en imposible.

La sonda se **mockea** (mismo criterio que ``test_governance_status``): apagar el motor de
verdad haría la suite dependiente del entorno y de los TTL del cliente. Lo que hay que
probar es la decisión ante cada uno de los tres desenlaces de la sonda, y eso es
exactamente lo que reproduce el doble.
"""
import pytest

from migration_harness import require_postgres
from seat_gate_harness import admin_headers, build_app_client

require_postgres()

DB = "sentinel_test_guardians_disponibilidad"

# Los 5 del catálogo incoming (guardrail de nube, ninguno cargado en esta instalación) y
# los que sí ejecuta código nuestro. Son `guardian_type`, identificadores internos de join.
CLOUD = {"openai_moderation", "lakera_prompt_injection", "azure_content_safety",
         "llamaguard_moderations", "bedrock_guardrails"}
REALES = {"pii_masking", "secret_detection", "sensitive_routing"}

# Constitución VII: ni nombres de proveedor ni el `engine_guardrail_name` pueden salir en
# una respuesta o en un error del producto.
PROHIBIDOS = ("litellm", "openai", "azure", "bedrock", "lakera", "llamaguard", "promptguard",
              "presidio", "anthropic", "traceback", "httpx", "http://", "content_filter")


class _Probe:
    """Doble de ``EngineGuardrailProbe``: tres estados, no dos (D4 de la 027)."""

    def __init__(self, confirmed, names=()):
        self.confirmed = confirmed
        self.names = frozenset(names)

    def has(self, name):
        return bool(self.confirmed and name and name in self.names)


MOTOR_ARRIBA_SIN_NUBE = _Probe(True, {"sentinel-guardian"})
MOTOR_CAIDO = _Probe(False)


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


def set_probe(monkeypatch, probe):
    from src.api import guardians

    async def _fake(**_kwargs):
        return probe

    monkeypatch.setattr(guardians.ai_engine_client, "probe_loaded_guardrails", _fake)


def listar(client, headers):
    resp = client.get("/api/v1/guardians", headers=headers)
    assert resp.status_code == 200, resp.text
    return {g["guardian_type"]: g for g in resp.json()}


def payload_de(guardian, **overrides):
    """El cuerpo que manda la pantalla al guardar, con los cambios del caso."""
    cuerpo = {
        "name": guardian["name"],
        "guardian_type": guardian["guardian_type"],
        "is_active": guardian["is_active"],
        "config": guardian["config"],
        "fail_mode": guardian["fail_mode"],
        "apply_on": guardian["apply_on"],
    }
    cuerpo.update(overrides)
    return cuerpo


def poner(client, headers, guardian, **overrides):
    return client.put(f"/api/v1/guardians/{guardian['id']}", headers=headers,
                      json=payload_de(guardian, **overrides))


# ── GET: la disponibilidad viaja, y es la REAL ────────────────────────────────────


def test_get_marca_los_cinco_de_nube_como_no_disponibles(harness, monkeypatch):
    client, _, headers = harness
    set_probe(monkeypatch, MOTOR_ARRIBA_SIN_NUBE)

    guardianes = listar(client, headers)

    assert CLOUD <= set(guardianes), "el seed del catálogo cambió"
    for tipo in CLOUD:
        g = guardianes[tipo]
        assert g["disponible"] is False, tipo
        assert g["motivo_disponibilidad"], tipo
        # Sin plano que los ejecute: la tarjeta no puede prometer alcance.
        assert g["planes_ejecucion"] == [], tipo


def test_get_marca_los_reales_como_disponibles_con_su_plano(harness, monkeypatch):
    client, _, headers = harness
    set_probe(monkeypatch, MOTOR_ARRIBA_SIN_NUBE)

    guardianes = listar(client, headers)

    assert REALES <= set(guardianes)
    for tipo in REALES:
        g = guardianes[tipo]
        assert g["disponible"] is True, tipo
        assert g["motivo_disponibilidad"] is None, tipo
        assert g["planes_ejecucion"], tipo
    # Tabla de consumo real de la spec: el enmascarado es el único que además corre en byok.
    assert guardianes["pii_masking"]["planes_ejecucion"] == ["chat_interno", "api_byok"]
    assert guardianes["secret_detection"]["planes_ejecucion"] == ["chat_interno"]
    assert guardianes["sensitive_routing"]["planes_ejecucion"] == ["chat_interno"]


def test_motor_caido_y_motor_arriba_dan_motivos_DISTINTOS(harness, monkeypatch):
    """'no se pudo confirmar' ≠ 'el motor no lo tiene cargado': dos acciones distintas para
    el admin. Colapsarlos es media mentira, que es lo que esta tarea borra."""
    client, _, headers = harness

    set_probe(monkeypatch, MOTOR_ARRIBA_SIN_NUBE)
    no_cargado = listar(client, headers)["bedrock_guardrails"]["motivo_disponibilidad"]

    set_probe(monkeypatch, MOTOR_CAIDO)
    sin_confirmar = listar(client, headers)["bedrock_guardrails"]["motivo_disponibilidad"]

    assert no_cargado and sin_confirmar and no_cargado != sin_confirmar


def test_el_guardrail_cargado_de_verdad_vuelve_disponible_al_guardian(harness, monkeypatch):
    """La disponibilidad NO es una lista negra hardcodeada: se resuelve contra la sonda, así
    que una instalación que sí cargue el guardrail recupera su interruptor sola."""
    client, _, headers = harness
    set_probe(monkeypatch, _Probe(True, {"sentinel-guardian", "bedrock_guardrails"}))

    guardianes = listar(client, headers)

    assert guardianes["bedrock_guardrails"]["disponible"] is True
    assert guardianes["openai_moderation"]["disponible"] is False


def test_la_respuesta_no_filtra_nombres_de_motor_ni_de_proveedor(harness, monkeypatch):
    client, _, headers = harness
    set_probe(monkeypatch, MOTOR_ARRIBA_SIN_NUBE)

    crudo = client.get("/api/v1/guardians", headers=headers).text.lower()

    # `name` y `config` del seed son copy de producto en español; lo que no puede aparecer
    # es el nombre técnico del guardrail ni el del proveedor que lo publica.
    for g in client.get("/api/v1/guardians", headers=headers).json():
        assert g["engine_guardrail_name"] is None
    for termino in ("litellm_content_filter", "promptguard", "azure/prompt_shield",
                    "azure/text_moderations"):
        assert termino not in crudo


# ── FR-007: activar sin guardrail cargado es imposible ────────────────────────────


def test_activar_un_guardian_de_nube_se_rechaza_con_409(harness, monkeypatch):
    client, factory, headers = harness
    set_probe(monkeypatch, MOTOR_ARRIBA_SIN_NUBE)
    g = listar(client, headers)["lakera_prompt_injection"]
    assert g["is_active"] is False

    resp = poner(client, headers, g, is_active=True)

    assert resp.status_code == 409, resp.text
    detalle = resp.json()["detail"]
    assert "catálogo incoming" in detalle
    assert not any(t in detalle.lower() for t in PROHIBIDOS), detalle

    # El rechazo no dejó la fila a medias: sigue apagada en la base.
    from src.models.guardian import Guardian
    db = factory()
    try:
        fila = db.query(Guardian).filter(Guardian.id == g["id"]).first()
        assert fila.is_active is False
    finally:
        db.close()


def test_el_rechazo_no_muta_NADA_de_la_fila(harness, monkeypatch):
    """El gate corre ANTES de las asignaciones: un 409 no puede dejar el nombre o la config
    del payload persistidos."""
    client, factory, headers = harness
    set_probe(monkeypatch, MOTOR_ARRIBA_SIN_NUBE)
    g = listar(client, headers)["azure_content_safety"]

    resp = poner(client, headers, g, is_active=True, name="RENOMBRADO POR EL ATAQUE",
                 config={"action": "ALLOW"})

    assert resp.status_code == 409
    from src.models.guardian import Guardian
    db = factory()
    try:
        fila = db.query(Guardian).filter(Guardian.id == g["id"]).first()
        assert fila.name == g["name"]
        assert fila.config == g["config"]
        assert fila.is_active is False
    finally:
        db.close()


def test_con_el_motor_caido_tampoco_se_puede_activar(harness, monkeypatch):
    """Fail-closed: 'no se pudo confirmar' no habilita nada. Preferimos negar el interruptor
    durante una caída antes que encender algo que quizás nadie ejecuta."""
    client, _, headers = harness
    set_probe(monkeypatch, MOTOR_CAIDO)
    g = listar(client, headers)["openai_moderation"]

    resp = poner(client, headers, g, is_active=True)

    assert resp.status_code == 409, resp.text


def test_activar_es_posible_cuando_el_guardrail_SI_esta_cargado(harness, monkeypatch):
    client, _, headers = harness
    set_probe(monkeypatch, _Probe(True, {"sentinel-guardian", "litellm_content_filter"}))
    g = listar(client, headers)["openai_moderation"]

    resp = poner(client, headers, g, is_active=True)

    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is True
    assert resp.json()["disponible"] is True
    # Se deja como estaba para no contaminar los tests siguientes del módulo.
    assert poner(client, headers, listar(client, headers)["openai_moderation"],
                 is_active=False).status_code == 200


def test_guardar_config_de_un_guardian_de_catalogo_sigue_funcionando(harness, monkeypatch):
    """El gate es sobre la ACTIVACIÓN, no sobre el guardado: la pantalla persiste los 9
    guardianes en un bucle y un 409 por editar un umbral rompería el botón entero."""
    client, _, headers = harness
    set_probe(monkeypatch, MOTOR_ARRIBA_SIN_NUBE)
    g = listar(client, headers)["lakera_prompt_injection"]

    resp = poner(client, headers, g, is_active=False,
                 config={**g["config"], "threshold": 0.42})

    assert resp.status_code == 200, resp.text
    assert resp.json()["config"]["threshold"] == 0.42
    assert resp.json()["disponible"] is False


def test_los_guardianes_reales_se_activan_aunque_el_motor_este_caido(harness, monkeypatch):
    """Los ejecuta código nuestro en nuestros propios procesos: su carga es estructural y no
    depende de la sonda. Bloquearlos por un motor caído sería la mentira simétrica."""
    client, _, headers = harness
    set_probe(monkeypatch, MOTOR_CAIDO)
    g = listar(client, headers)["sensitive_routing"]

    resp = poner(client, headers, g, is_active=True)

    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is True
    assert resp.json()["disponible"] is True
    assert poner(client, headers, listar(client, headers)["sensitive_routing"],
                 is_active=False).status_code == 200
