"""Determinismo y rendición de cuentas de la postura `nlp_fail_mode` (issue #104).

Hallazgo #6 del gate de seguridad del PR #97 (severidad MEDIA, post-merge del #63/#97). Son
tres agujeros del guardián `pii_masking`, y los tres eran invisibles para la suite:

(a) **Postura NO determinista**: sin `ORDER BY`, con DOS guardianes `pii_masking` activos los
    cuatro lectores de la postura elegían una fila ARBITRARIA con `LIMIT 1`/`.first()`, así que
    el backend, el motor y `/health` podían discrepar sobre qué pasa con el NLP caído. El fix es
    el mismo desempate «determinista» que `_IDENTITY_SQL` ya usa para el presupuesto:
    `ORDER BY (created_at, id)` ⇒ gana SIEMPRE la fila más antigua.

(b) **Alta sin fila durable**: `POST /guardians` podía crear un `pii_masking` ACTIVO con
    `nlp_fail_mode: degrade` sin escribir la fila de auditoría (el registro sólo colgaba del PUT).

(c) **Evasión por doble PUT**: el chequeo `pii_masking` se evaluaba sobre el tipo YA mutado —
    sacar el tipo, guardar `degrade`, devolver el tipo dejaba la postura sin registro.

Se afirma comportamiento observable —qué postura leen los lectores, qué queda en `audit_logs`—,
nunca la forma interna. El sembrado usa filas REALES de `guardians`, no mocks de los lectores:
el canal por el que la postura del admin llega a cada plano es justo lo que el #104 blinda.
"""
import hashlib
import os
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

DB = "basa_test_nlp_posture_determinista"

SECRETO = "secreto-interno-determinismo-104"
CABECERA_INTERNA = {"X-Basa-Internal": SECRETO}
IDENTITY = "/api/v1/internal/identity"
GUARDIANS = "/api/v1/guardians"
HEALTH = "/api/v1/health"

# Estado de compliance de la fila durable del cambio de postura (guardians.py).
CONFIG_CHANGE = "config_change_nlp_fail_mode"

# Dos instantes bien separados: "la más antigua" es inequívoca y el desempate por `id` no entra
# en juego (los timestamps ya difieren). El más NUEVO lleva `degrade`, el más VIEJO `block`.
VIEJO = datetime(2020, 1, 1, 0, 0, 0)
NUEVO = datetime(2030, 1, 1, 0, 0, 0)


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    """DB fresca migrada a head + app real. El secreto interno se inyecta en el env porque
    `_require_internal_secret` lo lee en cada request al plano interno."""
    previo = os.environ.get("LITELLM_MASTER_KEY")
    os.environ["LITELLM_MASTER_KEY"] = SECRETO
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()
    if previo is None:
        os.environ.pop("LITELLM_MASTER_KEY", None)
    else:
        os.environ["LITELLM_MASTER_KEY"] = previo


@pytest.fixture(autouse=True)
def limpiar(harness):
    """Cada test parte de CERO guardianes y CERO filas de cambio de postura: los tests del
    módulo comparten DB y se apoyan en conteos exactos."""
    _, factory = harness
    from src.models.audit import AuditLog
    from src.models.guardian import Guardian
    db = factory()
    try:
        db.query(Guardian).delete()
        db.query(AuditLog).filter(AuditLog.compliance_status == CONFIG_CHANGE).delete()
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture(autouse=True)
def probe_mockeada(monkeypatch):
    """El motor no se toca: `create`/`update` sondean guardrails cargados para `_to_response`.
    Se dobla la sonda (mismo criterio que `test_guardians_disponibilidad`) para no depender del
    entorno ni de la red."""
    from src.api import guardians

    class _Probe:
        confirmed = True

        def has(self, _name):
            return False

    async def _fake(**_kwargs):
        return _Probe()

    monkeypatch.setattr(guardians.ai_engine_client, "probe_loaded_guardrails", _fake)


# ── Sembrado ──────────────────────────────────────────────────────────────────────


def sembrar_pii(factory, *, config, created_at, name):
    from src.models.guardian import Guardian
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        row = Guardian(name=name, guardian_type="pii_masking", is_active=True,
                       tenant_id=DEFAULT_TENANT_ID, config=config, created_at=created_at)
        db.add(row)
        db.commit()
        return str(row.id)
    finally:
        db.close()


def sembrar_connection(factory):
    """Connection mínima del tenant por defecto: la resuelve `/internal/identity`."""
    from src.models.budget import APIKey
    from src.models.tenant import DEFAULT_TENANT_ID
    key_hash = hashlib.sha256(b"clave-determinismo-104").hexdigest()
    db = factory()
    try:
        db.add(APIKey(tenant_id=DEFAULT_TENANT_ID, key_hash=key_hash,
                      key_preview="sk-...104", name="conn-104", is_active=True,
                      tool_type="claude-code", upstream_mode="byok"))
        db.commit()
    finally:
        db.close()
    return key_hash


def filas_config_change(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return [{"model": f.model, "compliance_status": f.compliance_status}
                for f in db.query(AuditLog)
                .filter(AuditLog.compliance_status == CONFIG_CHANGE).all()]
    finally:
        db.close()


def pii_activos(factory):
    from src.models.guardian import Guardian
    db = factory()
    try:
        return [{"guardian_type": g.guardian_type, "config": g.config, "is_active": g.is_active}
                for g in db.query(Guardian)
                .filter(Guardian.guardian_type == "pii_masking").all()]
    finally:
        db.close()


# ── (a) DETERMINISMO: los lectores del backend + /health coinciden ────────────────


def test_con_dos_pii_masking_activos_todos_los_lectores_eligen_la_mas_antigua(harness,
                                                                              monkeypatch):
    """Con dos `pii_masking` activos —el más NUEVO con `degrade`, el más VIEJO con `block`—,
    los cuatro lectores tienen que coincidir en la postura de la fila MÁS ANTIGUA (`block`).

    Sin el fix (`.first()`/`LIMIT 1` sin `ORDER BY`) la fila devuelta es la del orden físico:
    se siembra primero la de `degrade`, así que sin el desempate los lectores leerían `degrade`
    y estas afirmaciones fallarían — que es justo lo que el issue pide poder detectar."""
    from src.api.gateway import _nlp_context
    from src.api.health import _fail_mode_efectivo
    from src.models.tenant import DEFAULT_TENANT_ID

    client, factory = harness
    key_hash = sembrar_connection(factory)
    # Orden de inserción = orden físico. Primero el NUEVO (degrade): sin ORDER BY sería el que
    # gana, y el test lo caza. Con ORDER BY gana el VIEJO (block).
    sembrar_pii(factory, config={"nlp_fail_mode": "degrade"}, created_at=NUEVO, name="PII-nuevo")
    sembrar_pii(factory, config={"nlp_fail_mode": "block"}, created_at=VIEJO, name="PII-viejo")

    # 1) Lectores del backend, llamados directamente sobre una sesión que ve las dos filas.
    db = factory()
    try:
        assert _fail_mode_efectivo(db, DEFAULT_TENANT_ID) == "block"
        assert _nlp_context(db, DEFAULT_TENANT_ID, atribuible=True)["nlp_fail_mode"] == "block"
    finally:
        db.close()

    # 2) Plano interno (backend/src/api/internal.py `_IDENTITY_SQL`) vía su endpoint.
    resp = client.get(IDENTITY, params={"key_hash": key_hash}, headers=CABECERA_INTERNA)
    assert resp.status_code == 200, resp.text
    assert resp.json()["row"]["nlp_fail_mode"] == "block"

    # 3) /health (mismo `_fail_mode_efectivo`, ahora por HTTP y en el tier detallado del admin).
    #    Se configura la URL del NLP y se dobla el probe al sidecar para no salir a la red.
    from src.api import health
    monkeypatch.setenv("NLP_ANALYZER_URL", "http://nlp-analyzer-104:3000")
    monkeypatch.setattr(health, "_nlp_alcanzable", lambda _url: (False, True))
    body = client.get(HEALTH, headers=admin_headers(client)).json()
    assert body["nlp"]["fail_mode_efectivo"] == "block"


# ── (b) POST /guardians con `degrade` deja fila durable ───────────────────────────


def test_post_pii_masking_degrade_escribe_fila_durable(harness):
    """El alta con una postura != default tiene que dejar el mismo rastro que un PUT: antes,
    crear un `pii_masking` ACTIVO en `degrade` no registraba nada — una decisión de seguridad
    sin rastro."""
    client, factory = harness
    resp = client.post(GUARDIANS, headers=admin_headers(client), json={
        "name": "PII", "guardian_type": "pii_masking", "is_active": True,
        "config": {"nlp_fail_mode": "degrade"},
    })

    assert resp.status_code == 201, resp.text
    filas = filas_config_change(factory)
    assert len(filas) == 1, f"el alta en degrade no dejó exactamente una fila durable: {filas}"
    assert filas[0]["model"] == f"{CONFIG_CHANGE}:block->degrade"


def test_post_pii_masking_en_block_no_genera_ruido(harness):
    """Contracara: el alta en el default (`block`) no es un cambio de postura, así que no
    escribe fila. Sin esto, el fix (b) podría estar registrando TODA alta indiscriminadamente."""
    client, factory = harness
    resp = client.post(GUARDIANS, headers=admin_headers(client), json={
        "name": "PII", "guardian_type": "pii_masking", "is_active": True,
        "config": {"nlp_fail_mode": "block"},
    })

    assert resp.status_code == 201, resp.text
    assert filas_config_change(factory) == []


# ── (c) Doble PUT: quitar tipo → guardar degrade → restaurar tipo NO evade ─────────


def test_doble_put_no_evade_la_auditoria(harness):
    """La evasión del issue: partir de un `pii_masking` en `block`, PUT #1 saca el tipo y de
    paso guarda `degrade` (que en una fila no-`pii_masking` queda inerte), PUT #2 devuelve el
    tipo `pii_masking`. El resultado es un `pii_masking` ACTIVO sirviendo con `degrade`.

    Con el bug, el chequeo `pii_masking` se evaluaba sobre el tipo ya mutado y NINGÚN PUT dejaba
    fila. Con el fix, la llegada a `degrade` (PUT #2, cuando la fila VUELVE a ser `pii_masking`)
    queda registrada: la postura efectiva no puede terminar en `degrade` sin rastro durable."""
    client, factory = harness
    headers = admin_headers(client)

    # Alta en block (sin postura != default ⇒ sin fila todavía).
    gid = client.post(GUARDIANS, headers=headers, json={
        "name": "PII", "guardian_type": "pii_masking", "is_active": True,
        "config": {"nlp_fail_mode": "block"},
    }).json()["id"]
    assert filas_config_change(factory) == []

    # PUT #1: quitar tipo Y guardar degrade en el mismo pedido (la fila deja de ser pii_masking).
    r1 = client.put(f"{GUARDIANS}/{gid}", headers=headers, json={
        "name": "PII", "guardian_type": "regex", "is_active": True,
        "config": {"nlp_fail_mode": "degrade"},
    })
    assert r1.status_code == 200, r1.text

    # PUT #2: devolver el tipo pii_masking; la config sigue en degrade.
    r2 = client.put(f"{GUARDIANS}/{gid}", headers=headers, json={
        "name": "PII", "guardian_type": "pii_masking", "is_active": True,
        "config": {"nlp_fail_mode": "degrade"},
    })
    assert r2.status_code == 200, r2.text

    # El guardián terminó ACTIVO, pii_masking y en degrade — la postura relajada quedó vigente…
    activos = pii_activos(factory)
    assert activos == [{"guardian_type": "pii_masking",
                        "config": {"nlp_fail_mode": "degrade"}, "is_active": True}]
    # …y NO pudo hacerlo en silencio: hay al menos una fila durable que registra la llegada a
    # degrade. Sin el fix, la lista queda vacía (evasión completa) y este assert falla.
    filas = filas_config_change(factory)
    assert any(f["model"].endswith("->degrade") for f in filas), (
        f"la postura terminó en degrade sin fila de auditoría (evasión del #104): {filas}")


# ── (round 2) La postura EFECTIVA del tenant no se mueve sin rastro ────────────────
#
# El gate adversarial reprodujo que auditar la fila AISLADA seguía dejando escapar la evasión
# por PROMOCIÓN: la postura que gobierna es la del `pii_masking` activo más antiguo, así que
# desactivar o borrar la gobernante promueve a la siguiente y mueve la política sin que ninguna
# fila "cambie". El fix audita la postura efectiva del tenant antes/después de cada mutación.


def _payload_de(config, *, is_active=True, guardian_type="pii_masking", name="PII"):
    return {"name": name, "guardian_type": guardian_type,
            "is_active": is_active, "config": config}


def _postura_del_tenant(factory):
    """La postura EFECTIVA que hoy gobierna el tráfico del tenant por defecto, leída por el
    mismo `_fail_mode_efectivo` que publica `/health`."""
    from src.api.health import _fail_mode_efectivo
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        return _fail_mode_efectivo(db, DEFAULT_TENANT_ID)
    finally:
        db.close()


def test_desactivar_la_gobernante_promueve_y_deja_fila(harness):
    """Repro exacto del round 2: A (más antigua, `block`, activa) gobierna; B (más nueva,
    `degrade`, activa) espera detrás. `PUT A is_active=false` promueve a B ⇒ la postura EFECTIVA
    del tenant pasa `block→degrade`. Auditar la fila AISLADA (A sigue siendo pii_masking/block
    antes y después) NO veía el cambio; auditar la postura efectiva sí. Sin el fix del round 2
    este test falla (0 filas)."""
    client, factory = harness
    gid_a = sembrar_pii(factory, config={"nlp_fail_mode": "block"}, created_at=VIEJO, name="A")
    sembrar_pii(factory, config={"nlp_fail_mode": "degrade"}, created_at=NUEVO, name="B")
    assert _postura_del_tenant(factory) == "block"  # A gobierna

    r = client.put(f"{GUARDIANS}/{gid_a}", headers=admin_headers(client),
                   json=_payload_de({"nlp_fail_mode": "block"}, is_active=False, name="A"))
    assert r.status_code == 200, r.text

    # La postura efectiva se movió a degrade (B promovida)…
    assert _postura_del_tenant(factory) == "degrade"
    # …y NO en silencio: hay fila durable del cambio.
    filas = filas_config_change(factory)
    assert any(f["model"].endswith("block->degrade") for f in filas), (
        f"promover B al desactivar A movió la postura sin rastro (evasión round 2): {filas}")


def test_borrar_la_gobernante_promueve_y_deja_fila(harness):
    """`DELETE` de la gobernante también promueve a la siguiente y mueve la postura efectiva.
    Antes, `DELETE` ni siquiera llamaba a la auditoría — el agujero más crudo. Sin el fix, falla."""
    client, factory = harness
    gid_a = sembrar_pii(factory, config={"nlp_fail_mode": "block"}, created_at=VIEJO, name="A")
    sembrar_pii(factory, config={"nlp_fail_mode": "degrade"}, created_at=NUEVO, name="B")
    assert _postura_del_tenant(factory) == "block"

    r = client.delete(f"{GUARDIANS}/{gid_a}", headers=admin_headers(client))
    assert r.status_code == 204, r.text

    assert _postura_del_tenant(factory) == "degrade"
    filas = filas_config_change(factory)
    assert any(f["model"].endswith("block->degrade") for f in filas), (
        f"borrar la gobernante movió la postura sin rastro: {filas}")


def test_post_pii_masking_inactivo_en_degrade_no_genera_ruido(harness):
    """El criterio "postura EFECTIVA" borra además el ruido del round 1: un `pii_masking`
    INACTIVO en `degrade` no gobierna nada (los lectores filtran `is_active=true`), así que su
    alta no cambia la postura efectiva del tenant ⇒ no audita."""
    client, factory = harness
    r = client.post(GUARDIANS, headers=admin_headers(client),
                    json=_payload_de({"nlp_fail_mode": "degrade"}, is_active=False))

    assert r.status_code == 201, r.text
    assert _postura_del_tenant(factory) == "block"  # el inactivo no gobierna
    assert filas_config_change(factory) == []
