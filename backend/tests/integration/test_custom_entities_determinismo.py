"""Determinismo del subsistema de ENTIDADES CUSTOM del guardián `pii_masking` (issue #119).

Misma familia que el #104 (que hizo determinista la POSTURA `nlp_fail_mode` en los 4 lectores
de tráfico con `ORDER BY created_at, id`), otro subsistema. El gate adversarial del #118
encontró (hallazgo BAJO ⇒ #119) que el catálogo de entidades custom quedó incoherente:

- El **ESCRITOR** (`entity_catalog_service._pii_guardian`, vía `create_custom_entity`) elegía
  la fila `pii_masking` con `.first()` **SIN `ORDER BY`** ni filtro de actividad.
- Los **LECTORES del plano chat** (`guardian_service.process_prompt` y `chat._detect_floor_pii`)
  tomaban una fila **ARBITRARIA** con `next(...)` sobre `db.query(...).all()`.

Con DOS `pii_masking` ACTIVOS, el panel podía ESCRIBIR en una fila y los planos LEER otra ⇒ la
entidad/nombre custom no aplicaba, en silencio. El fix aplica el MISMO desempate determinista
que el #104 —la ACTIVA más antigua, `is_active=true ORDER BY created_at, id LIMIT 1`— al
escritor y a los dos lectores de chat, para que escritor y TODOS los lectores coincidan SIEMPRE
en la MISMA fila.

Se siembra la fila NUEVA PRIMERO (orden físico) y con created_at futuro, y la VIEJA después:
así, sin el desempate, `.first()`/`next(...)` devuelven la fila física-primera (la NUEVA, la
equivocada) y los asserts fallan — que es justo lo que el #119 pide poder detectar. Con el fix
gana la VIEJA (la más antigua), que es la que lleva el vocabulario distintivo.
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_custom_entities_determinismo"
CHAT = "/api/v1/chat/completions"
MODELO = "ollama-qwen3-4b"

# Dos instantes bien separados: "la más antigua" es inequívoca y el desempate por `id` no entra
# en juego. La VIEJA (que gobierna) lleva el vocabulario distintivo; la NUEVA no.
VIEJO = datetime(2020, 1, 1, 0, 0, 0)
NUEVO = datetime(2030, 1, 1, 0, 0, 0)

# Token que NINGÚN detector de dev flagea por su cuenta (el `PERSON` regex de `default_analyze`
# exige un tratamiento sr/sra/dr… delante). Sólo puede enmascararse/contarse vía `custom_names`,
# así que su presencia en el hallazgo prueba de qué fila salió el vocabulario. No está en los
# `custom_names` del seed por defecto (Pedro/Cristian/…).
MARCA = "Xytherio"
MENSAJE = f"Prepara el alta de {MARCA} para el turno de mañana."

# Config de una fila `pii_masking` que enmascara nombres propios del cliente.
def _config(custom_names):
    return {
        "entities": ["PERSON", "ES_NIF", "ES_NIE", "PASSPORT", "EMAIL_ADDRESS",
                     "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD"],
        "action": "MASK",
        "custom_names": list(custom_names),
        "nlp_fail_mode": "block",
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    # El chat es fail-closed: sin credencial es 401. El admin del tenant default se crea en el
    # bootstrap del login; la sesión va en el cliente.
    client.headers.update(admin_headers(client))
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def motor_mockeado(monkeypatch):
    """El motor no se toca: se dobla `httpx` del namespace de `chat` (mismo criterio que la
    suite de atribución) — lo que se mide es qué fila se lee, no que haya un modelo levantado."""
    class _Resp:
        status_code = 200
        text = "ok"
        headers = {"x-litellm-response-cost": "0.00012"}

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "listo"}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 3}}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, *_a, **_k):
            return _Resp()

    class _Httpx:
        @staticmethod
        def AsyncClient(*_a, **_k):  # noqa: N802 — espeja el nombre real
            return _Client()

    from src.api import chat
    monkeypatch.setattr(chat, "httpx", _Httpx)


@pytest.fixture(autouse=True)
def limpiar(harness):
    """Cada test parte de CERO guardianes y CERO perfiles de gobernanza: la DB del módulo se
    comparte y los asserts se apoyan en qué fila gobierna."""
    _, factory = harness
    from src.models.governance import GovernanceProfile
    from src.models.guardian import Guardian
    db = factory()
    try:
        db.query(GovernanceProfile).delete()
        db.query(Guardian).delete()
        db.commit()
    finally:
        db.close()
    yield


# ── Helpers ──────────────────────────────────────────────────────────────────────


def sembrar_pii(factory, *, config, created_at, name, is_active=True):
    from src.models.guardian import Guardian
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        row = Guardian(name=name, guardian_type="pii_masking", is_active=is_active,
                       tenant_id=DEFAULT_TENANT_ID, config=config, created_at=created_at)
        db.add(row)
        db.commit()
        return str(row.id)
    finally:
        db.close()


def config_de(factory, guardian_id):
    from src.models.guardian import Guardian
    db = factory()
    try:
        row = db.query(Guardian).filter(Guardian.id == guardian_id).first()
        return dict(row.config or {})
    finally:
        db.close()


def guardianes(factory):
    """Igual que los lectores de chat: TODAS las filas del tenant, sin ordenar (orden físico)."""
    from src.models.guardian import Guardian
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        return db.query(Guardian).filter(Guardian.tenant_id == DEFAULT_TENANT_ID).all()
    finally:
        db.close()


# ── (1) ESCRITOR: la entidad custom se escribe en la ACTIVA más antigua ───────────


def test_escritor_escribe_la_entidad_en_la_pii_masking_activa_mas_antigua(harness):
    """El panel (`create_custom_entity` → `_pii_guardian`) tiene que escribir en la fila que los
    planos LEEN: la ACTIVA más antigua. Se siembra la NUEVA primero (orden físico) para que, sin
    el fix, el `.first()` sin `ORDER BY` caiga en ella y la entidad quede en la fila equivocada."""
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.services import entity_catalog_service as svc

    _, factory = harness
    nueva = sembrar_pii(factory, config=_config([]), created_at=NUEVO, name="PII-nueva")
    vieja = sembrar_pii(factory, config=_config([MARCA]), created_at=VIEJO, name="PII-vieja")

    db = factory()
    try:
        svc.create_custom_entity(
            db, DEFAULT_TENANT_ID, name="Historia Clínica ES",
            entity_type="HISTORIA_CLINICA_ES", regex=r"\bHC-\d{6}\b", score=0.7,
        )
    finally:
        db.close()

    tipos_vieja = [e["entity_type"] for e in config_de(factory, vieja).get("custom_entities", [])]
    tipos_nueva = [e["entity_type"] for e in config_de(factory, nueva).get("custom_entities", [])]
    assert tipos_vieja == ["HISTORIA_CLINICA_ES"], (
        "la entidad custom tiene que quedar en la fila ACTIVA más antigua (la que gobierna), "
        f"pero la vieja quedó con {tipos_vieja}")
    assert tipos_nueva == [], (
        f"la entidad no puede quedar en la fila más nueva (fila arbitraria del bug): {tipos_nueva}")


# ── (2) LECTOR de piso (`chat._detect_floor_pii`) lee la ACTIVA más antigua ───────


def test_piso_de_chat_lee_el_vocabulario_de_la_fila_gobernante(harness):
    """`_detect_floor_pii` cuenta los `custom_names` de la fila `pii_masking`. Con dos activas —la
    VIEJA (gobernante) con `MARCA` en su lista, la NUEVA sin ella— el piso tiene que contar la
    MARCA (leyó la vieja). Sin el fix, `next(...)` toma la física-primera (la nueva, sin la marca)
    y el conteo queda vacío."""
    from src.api.chat import _detect_floor_pii

    _, factory = harness
    sembrar_pii(factory, config=_config([]), created_at=NUEVO, name="PII-nueva")
    sembrar_pii(factory, config=_config([MARCA]), created_at=VIEJO, name="PII-vieja")

    hallazgo = asyncio.run(_detect_floor_pii(MENSAJE, guardianes(factory)))
    tipos = {e["type"]: e["count"] for e in (hallazgo or [])}
    assert tipos.get("PERSON", 0) >= 1, (
        "el piso tiene que contar el nombre custom de la fila gobernante (la más antigua); "
        f"leyó una fila sin ese vocabulario: {hallazgo}")


# ── (3) End-to-end: el enmascarado del chat usa la fila gobernante ────────────────


def test_chat_enmascara_con_el_vocabulario_de_la_fila_gobernante(harness):
    """`process_prompt` (lector del plano chat) enmascara los `custom_names` de la fila que
    gobierna. Con el catálogo por defecto (`pii_masking` activo, created_at ~hoy) MÁS una segunda
    fila ACTIVA más ANTIGUA que lleva `MARCA`, mandar un prompt con `MARCA` tiene que enmascararla
    (leyó la vieja). Sin el fix, `next(...)` toma la física-primera —el guardián del seed, que no
    tiene `MARCA`— y el enmascarado reporta `allow` en vez de `mask`."""
    client, factory = harness

    # 1) Primer pedido: siembra el catálogo de 9 guardianes (el seed BORRA y re-siembra con <9
    #    filas; hacerlo ahora evita que un guardián sembrado a mano sea destruido después).
    assert client.post(CHAT, json={"message": "hola", "model": MODELO}).status_code == 200

    # 2) Segunda fila `pii_masking` ACTIVA y MÁS ANTIGUA (gobernante) con la MARCA. Queda un
    #    catálogo de 10 guardianes ⇒ el seed ya no re-siembra.
    sembrar_pii(factory, config=_config([MARCA]), created_at=VIEJO, name="PII-vieja-gobernante")

    resp = client.post(CHAT, json={"message": MENSAJE, "model": MODELO})
    assert resp.status_code == 200, resp.text
    capas = {e["layer_code"]: e
             for e in resp.json()["pipeline_metadata"]["governance"]["applied_layers"]}
    enmascarado = capas["pii_masking"]
    assert enmascarado["status"] == "applied"
    assert enmascarado["decision"] == "mask", (
        "el enmascarado tiene que leer el nombre custom de la fila gobernante (la más antigua) y "
        f"enmascararlo; leyó una fila sin ese vocabulario: {enmascarado}")
    assert enmascarado.get("count", 0) >= 1
