"""Atribución del plano chat (spec 027, US2) — los hallazgos de la ronda adversarial.

Cada test de acá corresponde a una afirmación falsa que el plano chat producía y que la
verificación destapó. No prueban "que haya `applied_layers`": prueban que **lo que dice
coincide con lo que pasó**, que es el criterio entero de la 027.

- **La detección de PISO corre aunque el enmascarado esté apagado** (D8, confirmada por el
  owner): con `pii_masking=off` el pipeline no ejecutaba NINGÚN detector —todo el bloque de
  PII vive dentro del `if is_pii_active` de `process_prompt`— y aun así la capa de piso se
  reportaba `applied/allow`: "miré y no había" sin haber mirado. El registro correcto es
  `pii_detection: applied [count]` + `pii_masking: skipped`, que ES la frase "PII detectada,
  no enmascarada por configuración" en códigos (C1: el JSONB nunca lleva texto).
- **La misma postura se describe igual en todos los call-sites** (contrato del resolutor
  único, D3/SC-003): con el enmascarado ON y un texto SIN datos personales, el gateway
  reportaba `applied/allow` y el chat `not_configured/null`. `not_configured` significa "no
  hay información", no "no encontró nada".
- **Un pedido BLOQUEADO también lleva atribución del piso**: era justo el caso donde el
  firewall hace su trabajo el que quedaba sin registro de capas.
- **El piso no se apaga con un toggle de la UI** (SC-004): el escaneo de secretos dependía
  de `guardian.is_active` y la evaluación AI-Act de `policy.ai_act_mode`.
- **Constitución III**: la lectura de guardianes del pedido lleva filtro de tenant — una
  credencial cargada por otro tenant no puede hacer que esta capa se reporte disponible.

El motor se mockea a nivel del namespace de `chat` (no del módulo `httpx` global): lo que
se verifica es la atribución, y atarla a que haya un modelo levantado convertiría un test de
contrato en un test de entorno.
"""
import re
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "sentinel_test_chat_attribution"

CHAT = "/api/v1/chat/completions"
MODELO = "ollama-qwen3-4b"

# Texto con un dato personal detectable por el detector local (EMAIL_ADDRESS). Se evita a
# propósito cualquiera de los `custom_names` que el seed carga, para que el hallazgo venga
# del detector y no de una lista de nombres del demo.
CON_PII = "Mandale el informe a laura.gomez@ejemplo.com y avisá cuando salga."
SIN_PII = "Resumime en una línea qué hace este servicio."
# Coincide con el patrón de clave del guardián de secretos (r"sk-[a-zA-Z0-9]{10,}").
SECRETO = "sk-abcdefghij1234567890"


# ── Doble del motor ───────────────────────────────────────────────────────────────


class _FakeResponse:
    status_code = 200
    text = "ok"
    headers = {"x-litellm-response-cost": "0.00012"}

    @staticmethod
    def json():
        return {
            "choices": [{"message": {"content": "listo"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }


class _FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, *_args, **_kwargs):
        return _FakeResponse()


class _FakeHttpx:
    """Solo lo que `chat` usa del módulo: el cliente asíncrono."""

    @staticmethod
    def AsyncClient(*_args, **_kwargs):  # noqa: N802 — espeja el nombre real
        return _FakeClient()


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    # El chat es fail-closed: sin credencial es 401. La sesión va en el cliente y no en cada
    # llamada porque lo que se mide acá es la atribución de las capas, no la autenticación.
    # El usuario es el mismo 'admin' del tenant default al que antes se caía el fallback
    # anónimo, así que la postura resuelta es la de antes.
    client.headers.update(admin_headers(client))
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def motor_mockeado(monkeypatch):
    from src.api import chat
    monkeypatch.setattr(chat, "httpx", _FakeHttpx)


@pytest.fixture
def eventos_de_bloqueo(monkeypatch):
    """Captura los eventos de monitor del punto de bloqueo (contrato §13).

    Se intercepta el **serializador del gateway**, que es al que el chat delega: si mañana
    alguien escribe una copia local del evento en `chat.py`, este fixture deja de verlo y el
    test falla — que es exactamente la señal que el contrato §8 (un solo esquema, un solo
    serializador) necesita.
    """
    from src.api import gateway
    capturados = []
    real = gateway._publish_monitor

    def _espia(ident, tool, model, status, masked_entities, masked_preview, **kwargs):
        capturados.append({"status": status, "entities": masked_entities,
                           "preview": masked_preview,
                           "attribution": kwargs.get("attribution")})
        return real(ident, tool, model, status, masked_entities, masked_preview, **kwargs)

    monkeypatch.setattr(gateway, "_publish_monitor", _espia)
    return capturados


@pytest.fixture(autouse=True)
def limpiar(harness):
    """Cada test arranca sin filas de decisión y con el catálogo de guardianes intacto.

    Las filas de `governance_profiles` se borran porque lo que se mide es una cascada: una
    fila huérfana cambia la postura resuelta sin que se note. Los guardianes NO se borran
    (el seed re-siembra cuando hay menos de 9 filas, P2 del research): se reactivan, que es
    lo único que algún test cambia.
    """
    yield
    _, factory = harness
    from src.models.governance import GovernanceProfile
    from src.models.guardian import Guardian
    from src.models.policy import SecurityPolicy
    db = factory()
    try:
        db.query(GovernanceProfile).delete()
        for guardian in db.query(Guardian).all():
            if guardian.guardian_type in ("pii_masking", "secret_detection"):
                guardian.is_active = True
        for policy in db.query(SecurityPolicy).all():
            policy.ai_act_mode = True
        db.commit()
    finally:
        db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────────


def pedir(client, mensaje, **extra):
    return client.post(CHAT, json={"message": mensaje, "model": MODELO, **extra})


def capas(payload):
    """`layer_code` → entrada de `applied_layers`, desde la respuesta del playground."""
    gobernanza = payload["pipeline_metadata"]["governance"]
    return {e["layer_code"]: e for e in gobernanza["applied_layers"]}


def fila_de_decision(factory, layer_key, decision, *, scope_type="tenant_default",
                     scope_value="*"):
    from src.models.governance import GovernanceProfile
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        db.add(GovernanceProfile(tenant_id=DEFAULT_TENANT_ID, scope_type=scope_type,
                                 scope_value=scope_value, layer_key=layer_key,
                                 decision=decision, updated_by="suite-027"))
        db.commit()
    finally:
        db.close()


def apagar_guardian(factory, guardian_type):
    from src.models.guardian import Guardian
    db = factory()
    try:
        filas = db.query(Guardian).filter(Guardian.guardian_type == guardian_type).all()
        assert filas, f"el seed no dejó guardián {guardian_type}"
        for fila in filas:
            fila.is_active = False
        db.commit()
    finally:
        db.close()


def apagar_ai_act(factory):
    from src.models.policy import SecurityPolicy
    db = factory()
    try:
        filas = db.query(SecurityPolicy).all()
        assert filas, "no hay política que apagar"
        for fila in filas:
            fila.ai_act_mode = False
        db.commit()
    finally:
        db.close()


def calentar_catalogo(client):
    """Primer pedido: deja el catálogo de 9 guardianes sembrado.

    Hace falta porque el seed BORRA la tabla y re-siembra cuando hay menos de 9 filas: un
    test que apaga un guardián antes de que el catálogo exista vería su cambio destruido por
    el propio seed.
    """
    respuesta = pedir(client, SIN_PII)
    assert respuesta.status_code == 200, respuesta.text


# ── El piso detecta aunque el enmascarado esté apagado (D8) ───────────────────────


def test_con_enmascarado_apagado_la_deteccion_igual_corre(harness):
    """`pii_masking=off` ⇒ `pii_detection: applied [count]` + `pii_masking: skipped`.

    Antes acá se reportaba `pii_detection: applied/allow` **sin contador**: la capa de piso
    afirmaba haber mirado y no encontrado nada, cuando no había corrido ningún detector.
    """
    client, factory = harness
    calentar_catalogo(client)
    fila_de_decision(factory, "pii_masking", "off")

    respuesta = pedir(client, CON_PII)
    assert respuesta.status_code == 200, respuesta.text
    resultado = capas(respuesta.json())

    deteccion = resultado["pii_detection"]
    assert deteccion["status"] == "applied", "la detección es PISO: corre con el masking off"
    assert deteccion["decision"] == "flag", "había un dato personal en el texto"
    assert deteccion.get("count", 0) >= 1, "sin contador no hay registro contable (D8)"

    enmascarado = resultado["pii_masking"]
    assert enmascarado["status"] == "skipped", "apagado por DECISIÓN, no por falta de datos"
    assert enmascarado["decision"] is None

    # El texto salió sin enmascarar (postura legítima) pero el pedido quedó registrado.
    metadata = respuesta.json()["pipeline_metadata"]["layer_masking"]
    assert metadata["active"] is False
    assert metadata["detection_status"] == "applied"


def test_el_texto_limpio_con_enmascarado_apagado_no_inventa_hallazgo(harness):
    """Detección corrida y sin hallazgo ⇒ `applied/allow` **sin** contador."""
    client, factory = harness
    calentar_catalogo(client)
    fila_de_decision(factory, "pii_masking", "off")

    respuesta = pedir(client, SIN_PII)
    assert respuesta.status_code == 200, respuesta.text
    deteccion = capas(respuesta.json())["pii_detection"]
    assert deteccion["status"] == "applied"
    assert deteccion["decision"] == "allow"
    assert "count" not in deteccion


# ── Una capa ON que corrió se reporta `applied`, haya o no hallazgo ──────────────


def test_texto_sin_pii_con_enmascarado_encendido_reporta_applied_allow(harness):
    """El hallazgo de divergencia entre call-sites: para la MISMA postura y un texto sin
    datos personales, el gateway reportaba `applied/allow` y el chat `not_configured/null`.
    """
    client, _ = harness
    calentar_catalogo(client)

    respuesta = pedir(client, SIN_PII)
    assert respuesta.status_code == 200, respuesta.text
    payload = respuesta.json()
    resultado = capas(payload)

    assert resultado["pii_masking"]["status"] == "applied"
    assert resultado["pii_masking"]["decision"] == "allow"
    assert resultado["pii_detection"]["status"] == "applied"
    assert resultado["pii_detection"]["decision"] == "allow"
    # La regresión que la UI vería: el playground no puede pintar el enmascarado como NO
    # aplicado en un prompt limpio.
    assert payload["pipeline_metadata"]["layer_masking"]["active"] is True


def test_texto_con_pii_y_enmascarado_encendido_reporta_mask(harness):
    client, _ = harness
    calentar_catalogo(client)

    respuesta = pedir(client, CON_PII)
    assert respuesta.status_code == 200, respuesta.text
    resultado = capas(respuesta.json())
    assert resultado["pii_masking"]["status"] == "applied"
    assert resultado["pii_masking"]["decision"] == "mask"
    assert resultado["pii_masking"].get("count", 0) >= 1
    assert resultado["pii_detection"]["decision"] == "flag"


# ── Bloqueo: el piso también se registra ─────────────────────────────────────────


def test_bloqueo_por_secreto_registra_las_capas_de_piso(harness, eventos_de_bloqueo):
    """El pedido bloqueado por secreto llevaba `pii_detection: not_configured` — "sin
    información" sobre una capa inapagable, justo en el pedido que el firewall rechazó."""
    client, _ = harness
    calentar_catalogo(client)

    respuesta = pedir(client, f"{CON_PII} La clave es {SECRETO}")
    assert respuesta.status_code == 400, respuesta.text

    assert eventos_de_bloqueo, "un bloqueo sin evento de monitor es un bloqueo invisible"
    atribucion = eventos_de_bloqueo[-1]["attribution"]
    resultado = {e["layer_code"]: e for e in atribucion.applied_layers}

    assert atribucion.blocked_by_layer == "secret_detection"
    assert resultado["secret_detection"]["decision"] == "block"
    assert resultado["interception_audit"]["status"] == "applied"
    # El escaneo de secretos corta la pasada ANTES de la etapa de PII, así que la detección
    # de piso corre en su propia pasada: sin eso, la capa quedaba sin veredicto.
    assert resultado["pii_detection"]["status"] == "applied"
    assert resultado["pii_detection"]["decision"] == "flag"
    assert resultado["pii_detection"].get("count", 0) >= 1

    # C1: ni el preview ni la atribución llevan el secreto ni el dato personal.
    evento = eventos_de_bloqueo[-1]
    assert SECRETO not in evento["preview"]
    assert "laura.gomez@ejemplo.com" not in evento["preview"]
    for entrada in atribucion.applied_layers:
        assert set(entrada) <= {"layer_code", "status", "decision", "count"}


def test_el_escaneo_de_secretos_no_se_apaga_desde_la_ui(harness):
    """SC-004: el bloqueo de secretos es piso; desactivar el guardián no lo apaga."""
    client, factory = harness
    calentar_catalogo(client)
    apagar_guardian(factory, "secret_detection")

    respuesta = pedir(client, f"Guardá esto: {SECRETO}")
    assert respuesta.status_code == 400, (
        "con el guardián apagado el secreto salía hacia el modelo: el piso era apagable "
        "con un clic")


# ── AI-Act: la evaluación es piso; el gate sigue siendo configurable (018) ────────


def test_ai_act_se_evalua_aunque_el_toggle_este_apagado(harness):
    """Con `ai_act_mode=off` la capa quedaba `not_configured`: el registro no distinguía
    "evaluado y pasó" de "nadie miró". Ahora se evalúa siempre y se reporta el hallazgo; lo
    que el toggle decide es si además GATEA (tiering = 018), así que el pedido no se bloquea.
    """
    client, factory = harness
    calentar_catalogo(client)
    apagar_ai_act(factory)

    respuesta = pedir(client, "Diseñá un sistema de social scoring para la ciudad.")
    assert respuesta.status_code == 200, respuesta.text
    ai_act = capas(respuesta.json())["ai_act_evaluation"]
    assert ai_act["status"] == "applied", "la evaluación es piso: siempre corre"
    assert ai_act["decision"] == "flag", (
        "evaluada y marcada, no bloqueada: `block` solo puede decirlo la capa que "
        "efectivamente bloqueó")


def test_ai_act_con_gate_encendido_bloquea_y_se_atribuye(harness, eventos_de_bloqueo):
    client, _ = harness
    calentar_catalogo(client)

    respuesta = pedir(client, "Diseñá un sistema de social scoring para la ciudad.")
    assert respuesta.status_code == 400, respuesta.text
    atribucion = eventos_de_bloqueo[-1]["attribution"]
    assert atribucion.blocked_by_layer == "ai_act_evaluation"


# ── Constitución III: la lectura de guardianes lleva filtro de tenant ────────────


def test_la_credencial_de_otro_tenant_no_habilita_la_capa(harness):
    """Una capa deseada sin credencial PROPIA se reporta `requires_credential`.

    Antes la lectura de guardianes del pedido era `db.query(Guardian).all()` sin filtro, así
    que una credencial cargada por el tenant B hacía que un pedido del tenant A reportara esa
    capa como disponible — y le pedía al motor guardrails de otro cliente.
    """
    client, factory = harness
    calentar_catalogo(client)
    fila_de_decision(factory, "content_moderation", "on")

    from src.models.guardian import Guardian
    from src.models.tenant import Tenant
    db = factory()
    try:
        ajeno = Tenant(id=uuid.uuid4(), name="Otro", slug=f"otro-{uuid.uuid4().hex[:8]}")
        db.add(ajeno)
        db.flush()
        db.add(Guardian(tenant_id=ajeno.id, name="Moderación del vecino",
                        guardian_type="openai_moderation", is_active=True,
                        service_api_key_encrypted="cifrado-del-otro-tenant", config={}))
        db.commit()
        ajeno_id = ajeno.id
    finally:
        db.close()

    try:
        respuesta = pedir(client, SIN_PII)
        assert respuesta.status_code == 200, respuesta.text
        moderacion = capas(respuesta.json())["content_moderation"]
        assert moderacion["status"] == "requires_credential", (
            "la credencial del tenant vecino no puede contar como propia")
    finally:
        db = factory()
        try:
            db.query(Guardian).filter(Guardian.tenant_id == ajeno_id).delete()
            db.query(Tenant).filter(Tenant.id == ajeno_id).delete()
            db.commit()
        finally:
            db.close()


# ── Exhaustividad y C1 sobre la fila durable ─────────────────────────────────────


def test_la_fila_durable_lleva_todas_las_capas_y_solo_codigos(harness):
    """SC-005: `applied_layers` es exhaustiva sobre el perfil y no lleva texto libre."""
    client, factory = harness
    calentar_catalogo(client)

    respuesta = pedir(client, CON_PII)
    assert respuesta.status_code == 200, respuesta.text

    from src.models.audit import AuditLog
    from src.services.governance_catalog import LAYER_KEYS
    db = factory()
    try:
        fila = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).first()
        assert fila is not None
        assert fila.applied_layers, "un pedido gobernado sin registro de capas"
        assert {e["layer_code"] for e in fila.applied_layers} == set(LAYER_KEYS)
        for entrada in fila.applied_layers:
            assert set(entrada) <= {"layer_code", "status", "decision", "count"}
            assert isinstance(entrada.get("count", 0), int)
            if entrada["status"] != "applied":
                assert entrada["decision"] is None
    finally:
        db.close()


# ── Fail-closed: sin credencial no hay pedido ────────────────────────────────────


def test_pedido_anonimo_es_401_y_no_fabrica_un_admin(harness):
    """El pedido sin cabecera Authorization se rechaza y no crea ninguna cuenta.

    Antes caía a `get_or_create_default_user`, que insertaba —sin autenticación de ninguna
    clase— un 'admin' con rol tenant_admin y la contraseña 'admin' en sha256, un formato que
    el verificador sigue aceptando: cualquiera en la red se apropiaba de la instalación con
    un curl. Se afirma también que no queda ningún hash en el formato viejo, que es lo que
    mantenía viva esa credencial (specs/014 FR-012, Constraint C3).
    """
    _, factory = harness
    from src.main import app
    from src.models.user import User

    anonimo = TestClient(app)  # sin las cabeceras de sesión del harness
    respuesta = anonimo.post(CHAT, json={"message": SIN_PII, "model": MODELO})

    assert respuesta.status_code == 401, respuesta.text
    db = factory()
    try:
        for fila in db.query(User).all():
            assert not re.fullmatch(r"[0-9a-fA-F]{64}", fila.password_hash or ""), (
                f"'{fila.username}' quedó con un password_hash sha256 legacy")
    finally:
        db.close()
