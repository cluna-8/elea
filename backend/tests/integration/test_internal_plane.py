"""Plano interno (backend/src/api/internal.py): identidad, auditoría durable y probe.

Es el ÚNICO camino que tiene el motor hacia la base del producto —no trae driver de
Postgres— así que acá se juegan tres cosas que ninguna otra suite mira:

1. **Retrocompatibilidad del POST de auditoría** (spec 031, contrato §internal): el payload
   de éxito que emite `basa_audit_logger` hoy tiene que seguir insertando idéntico mientras
   el guardrail empieza a mandar filas de BLOQUEO por el mismo endpoint.
2. **La fila de bloqueo** (contrato §Fila de bloqueo, convención D1): `compliance_status`
   con prefijo `blocked_` + `blocked_by_layer`, recuperable con el filtro canónico
   `LIKE 'blocked%'`. Y el caso feo: un bloqueo sin identidad resoluble NO puede perderse
   por un 422 — el intento existe aunque no sepamos de quién es.
3. **El presupuesto en el plano motor** (issue #76): la identidad expone techo y gasto para
   que el motor pueda rechazar ANTES de llamar al proveedor, y cada evento auditado mueve
   el contador. Hasta acá el gasto byok era invisible: el panel de costes solo veía el
   Playground, que es el plano que menos tráfico tiene.
"""
import hashlib
import os
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_internal_plane"

SECRETO = "secreto-interno-de-la-suite-031"
CABECERA = {"X-Basa-Internal": SECRETO}

AUDIT = "/api/v1/internal/audit"
PROBE = "/api/v1/internal/audit/probe"
IDENTITY = "/api/v1/internal/identity"


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    """DB fresca + app real. El secreto interno se inyecta en el env porque
    `_require_internal_secret` lo lee en cada request (fail-closed: sin secreto
    configurado, el endpoint responde 404 a todo el mundo)."""
    previo = os.environ.get("BASA_ENGINE_MASTER_KEY")
    os.environ["BASA_ENGINE_MASTER_KEY"] = SECRETO
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()
    if previo is None:
        os.environ.pop("BASA_ENGINE_MASTER_KEY", None)
    else:
        os.environ["BASA_ENGINE_MASTER_KEY"] = previo


# ── Sembrado ──────────────────────────────────────────────────────────────────────


def sembrar_connection(factory, *, sufijo, con_presupuesto=None, presupuesto_de_grupo=None,
                       gasto=Decimal("0")):
    """Crea Group + User + Connection (+ presupuesto opcional) y devuelve sus ids.

    `con_presupuesto` = techo del presupuesto PERSONAL del user;
    `presupuesto_de_grupo` = techo del presupuesto del GRUPO (respaldo del anterior).
    """
    from src.models.budget import APIKey, Budget
    from src.models.user import Group, User

    key_hash = hashlib.sha256(f"clave-{sufijo}".encode()).hexdigest()
    db = factory()
    try:
        grupo = Group(name=f"grupo-{sufijo}")
        db.add(grupo)
        db.flush()
        user = User(username=f"user-{sufijo}", email=f"{sufijo}@ejemplo.test",
                    password_hash="x", role="client", client_type="base_url",
                    group_id=grupo.id)
        db.add(user)
        db.flush()
        key = APIKey(name=f"conn-{sufijo}", key_hash=key_hash,
                     key_preview=f"sk-...{sufijo}", tool_type="claude-code",
                     user_id=user.id, group_id=grupo.id)
        db.add(key)
        if con_presupuesto is not None:
            db.add(Budget(user_id=user.id, max_spend_usd=Decimal(str(con_presupuesto)),
                          current_spend_usd=gasto, max_tokens=1_000_000,
                          current_tokens=0, reset_period="monthly"))
        if presupuesto_de_grupo is not None:
            db.add(Budget(group_id=grupo.id, max_spend_usd=Decimal(str(presupuesto_de_grupo)),
                          current_spend_usd=gasto, max_tokens=1_000_000,
                          current_tokens=0, reset_period="monthly"))
        db.commit()
        return {"key_hash": key_hash, "user_id": str(user.id), "group_id": str(grupo.id),
                "key_id": str(key.id)}
    finally:
        db.close()


def identidad(client, key_hash):
    resp = client.get(IDENTITY, params={"key_hash": key_hash}, headers=CABECERA)
    assert resp.status_code == 200, resp.text
    return resp.json()["row"]


def fila_por_modelo(factory, modelo):
    from src.models.audit import AuditLog
    db = factory()
    try:
        fila = db.query(AuditLog).filter(AuditLog.model == modelo).one_or_none()
        if fila is None:
            return None
        return {
            "tenant_id": str(fila.tenant_id),
            "user_id": str(fila.user_id) if fila.user_id else None,
            "api_key_id": str(fila.api_key_id) if fila.api_key_id else None,
            "compliance_status": fila.compliance_status,
            "blocked_by_layer": fila.blocked_by_layer,
            "prompt_tokens": fila.prompt_tokens,
            "completion_tokens": fila.completion_tokens,
            "cost_usd": Decimal(fila.cost_usd),
            "masked_entities": fila.masked_entities,
            "applied_layers": fila.applied_layers,
        }
    finally:
        db.close()


def presupuesto_de(factory, user_id):
    from src.models.budget import Budget
    db = factory()
    try:
        fila = db.query(Budget).filter(Budget.user_id == user_id).one()
        return {"gasto": Decimal(fila.current_spend_usd), "tokens": fila.current_tokens}
    finally:
        db.close()


# ── Auditoría: retrocompatibilidad y fila de bloqueo ──────────────────────────────


def test_payload_viejo_de_exito_sigue_insertando_igual(harness):
    """El payload EXACTO que emite hoy `basa_audit_logger._log` (sin los campos de
    bloqueo) tiene que seguir dando 200 y una fila `passed` con atribución intacta."""
    client, factory = harness
    ids = sembrar_connection(factory, sufijo="viejo")
    modelo = "modelo-payload-viejo"

    resp = client.post(AUDIT, headers=CABECERA, json={
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "user_id": ids["user_id"],
        "api_key_id": ids["key_id"],
        "model": modelo,
        "prompt_tokens": 120,
        "completion_tokens": 40,
        "cost_usd": 0.0,
        "pii_detected": True,
        "masked_entities": [{"type": "EMAIL_ADDRESS", "count": 2}],
        "compliance_status": "passed",
        "latency_ms": 350,
        "user_group_id": ids["group_id"],
        "applied_layers": None,
        "blocked_by_layer": None,
    })

    assert resp.status_code == 200, resp.text
    fila = fila_por_modelo(factory, modelo)
    assert fila["compliance_status"] == "passed"
    assert fila["blocked_by_layer"] is None
    assert fila["applied_layers"] is None
    assert fila["masked_entities"] == [{"type": "EMAIL_ADDRESS", "count": 2}]
    assert fila["api_key_id"] == ids["key_id"]


def test_fila_de_bloqueo_queda_durable_con_capa_y_atribucion(harness):
    """Contrato §Fila de bloqueo: estado `blocked_*` + capa del registry, tokens y coste
    en cero, atribución completa. Y aparece bajo el filtro canónico `LIKE 'blocked%'`."""
    client, factory = harness
    ids = sembrar_connection(factory, sufijo="bloqueo")
    modelo = "modelo-bloqueado"

    resp = client.post(AUDIT, headers=CABECERA, json={
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "user_id": ids["user_id"],
        "api_key_id": ids["key_id"],
        "model": modelo,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_usd": 0,
        "pii_detected": True,
        "masked_entities": [{"type": "ES_NIF", "count": 1}],
        "compliance_status": "blocked_prohibited",
        "latency_ms": 12,
        "user_group_id": ids["group_id"],
        "applied_layers": [{"layer_code": "ai_act_prohibited", "status": "applied",
                            "decision": "block", "count": 1}],
        "blocked_by_layer": "ai_act_prohibited",
    })

    assert resp.status_code == 200, resp.text
    fila = fila_por_modelo(factory, modelo)
    assert fila["compliance_status"] == "blocked_prohibited"
    assert fila["blocked_by_layer"] == "ai_act_prohibited"
    assert (fila["prompt_tokens"], fila["completion_tokens"]) == (0, 0)
    assert fila["user_id"] == ids["user_id"]

    # Filtro canónico de la 031 (FR-006): el officer los aísla sin interpretar tokens 0/0.
    from sqlalchemy import text as sql
    db = factory()
    try:
        encontrados = db.execute(
            sql("SELECT model FROM audit_logs WHERE compliance_status LIKE 'blocked%'")
        ).scalars().all()
    finally:
        db.close()
    assert modelo in encontrados


def test_bloqueo_sin_tenant_resoluble_no_pierde_la_fila(harness):
    """Edge case de la spec: llave master / identidad no resoluble. Antes el `tenant_id`
    obligatorio devolvía 422 y el intento bloqueado desaparecía — el peor resultado
    posible para un producto de auditoría."""
    client, factory = harness
    modelo = "modelo-sin-tenant"

    resp = client.post(AUDIT, headers=CABECERA, json={
        "model": modelo,
        "compliance_status": "blocked_secret",
        "blocked_by_layer": "secret_detection",
        "latency_ms": 5,
    })

    assert resp.status_code == 200, resp.text
    fila = fila_por_modelo(factory, modelo)
    assert fila["tenant_id"] == "00000000-0000-0000-0000-000000000001"
    assert fila["user_id"] is None and fila["api_key_id"] is None
    assert fila["compliance_status"] == "blocked_secret"


def test_sin_el_secreto_interno_el_plano_no_existe(harness):
    """Mismo 404 que emite el ingress: desde fuera de la red de compose no hay endpoint."""
    client, _ = harness
    assert client.post(AUDIT, json={"model": "x"}).status_code == 404
    assert client.get(PROBE).status_code == 404
    assert client.get(IDENTITY, params={"key_hash": "a" * 64}).status_code == 404
    assert client.get(PROBE, headers={"X-Basa-Internal": "otro"}).status_code == 404


# ── Probe de escribibilidad (contrato §probe) ─────────────────────────────────────


def test_probe_responde_writable_con_la_base_arriba(harness):
    client, _ = harness
    resp = client.get(PROBE, headers=CABECERA)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"writable": True}


def test_probe_da_503_cuando_la_base_no_responde(harness):
    """Lo que consume el modo `closed`: si esto no da 200, el guardrail rechaza ANTES de
    llamar al proveedor (FR-005: no se gasta dinero en tráfico inauditable)."""
    client, _ = harness

    class _SesionCaida:
        def execute(self, *_a, **_kw):
            raise RuntimeError("la base de auditoría no responde")

        def rollback(self):
            raise RuntimeError("el rollback tampoco")

    from src.database import get_db
    from src.main import app

    anterior = app.dependency_overrides[get_db]

    def _caida():
        yield _SesionCaida()

    app.dependency_overrides[get_db] = _caida
    try:
        resp = client.get(PROBE, headers=CABECERA)
    finally:
        app.dependency_overrides[get_db] = anterior

    assert resp.status_code == 503
    assert resp.json()["writable"] is False


# ── Identidad: presupuesto del dueño de la llave (issue #76) ──────────────────────


def test_identidad_expone_techo_y_gasto_del_presupuesto_personal(harness):
    client, factory = harness
    ids = sembrar_connection(factory, sufijo="con-presu", con_presupuesto="25.0000",
                             gasto=Decimal("3.5000"))

    row = identidad(client, ids["key_hash"])

    assert row["max_budget_usd"] == 25.0
    assert row["spend_usd"] == 3.5
    assert isinstance(row["max_budget_usd"], float)
    assert isinstance(row["spend_usd"], float)


def test_identidad_sin_presupuesto_omite_el_techo_y_el_gasto_es_cero(harness):
    """Gotcha del contrato: la clave AUSENTE (no `None`) — el consumidor lee con
    `.get(campo, default)` y un `null` explícito le rompería el default. Y el techo
    ausente significa "sin límite configurado", que no es lo mismo que un techo de 0."""
    client, factory = harness
    ids = sembrar_connection(factory, sufijo="sin-presu")

    row = identidad(client, ids["key_hash"])

    assert "max_budget_usd" not in row
    assert row["spend_usd"] == 0.0


def test_identidad_cae_al_presupuesto_del_grupo_si_no_hay_personal(harness):
    """Misma precedencia que `BudgetService.get_applicable_budgets`: personal primero,
    grupo de respaldo. Sin esto, un cliente sin presupuesto propio pero con uno de grupo
    gastaría sin límite por el plano motor mientras el chat sí lo frena."""
    client, factory = harness
    ids = sembrar_connection(factory, sufijo="presu-grupo", presupuesto_de_grupo="12.0000",
                             gasto=Decimal("1.0000"))

    row = identidad(client, ids["key_hash"])

    assert row["max_budget_usd"] == 12.0
    assert row["spend_usd"] == 1.0


def test_identidad_prefiere_el_personal_sobre_el_del_grupo(harness):
    client, factory = harness
    ids = sembrar_connection(factory, sufijo="presu-doble", con_presupuesto="7.0000",
                             presupuesto_de_grupo="99.0000", gasto=Decimal("2.0000"))

    row = identidad(client, ids["key_hash"])

    assert row["max_budget_usd"] == 7.0


def test_identidad_no_manda_columnas_nulas(harness):
    """El filtro de NULLs es del CONTRATO, no de la disciplina del consumidor: con la
    clave presente valiendo `None`, `.get("redact_enabled", True)` devuelve `None` y el
    motor deja de enmascarar (verificado en vivo el 2026-07-27)."""
    client, factory = harness
    ids = sembrar_connection(factory, sufijo="nulls")

    row = identidad(client, ids["key_hash"])

    assert "expires_at" not in row          # NULL en la Connection sembrada
    assert "redact_enabled" not in row      # NULL = heredar, jamás `null` explícito
    assert row["key_id"] == ids["key_id"]   # lo NOT NULL sigue viajando
    assert row["user_id"] == ids["user_id"]


def test_identidad_de_llave_inexistente_sigue_devolviendo_null(harness):
    client, _ = harness
    resp = client.get(IDENTITY, params={"key_hash": "f" * 64}, headers=CABECERA)
    assert resp.status_code == 200
    assert resp.json() == {"row": None}


# ── Auditoría: el evento mueve el contador de gasto (issue #76) ───────────────────


def test_record_audit_incrementa_el_gasto_del_presupuesto(harness):
    client, factory = harness
    ids = sembrar_connection(factory, sufijo="gasto", con_presupuesto="10.0000")

    resp = client.post(AUDIT, headers=CABECERA, json={
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "user_id": ids["user_id"],
        "api_key_id": ids["key_id"],
        "model": "modelo-que-gasta",
        "prompt_tokens": 1000,
        "completion_tokens": 200,
        "cost_usd": 0.0025,
        "compliance_status": "passed",
        "latency_ms": 800,
        "user_group_id": ids["group_id"],
    })

    assert resp.status_code == 200, resp.text
    estado = presupuesto_de(factory, ids["user_id"])
    assert estado["gasto"] == Decimal("0.0025")
    assert estado["tokens"] == 1200


def test_una_fila_de_bloqueo_no_le_cobra_nada_a_nadie(harness):
    """0 tokens y 0 coste: el intento se registra, el presupuesto no se toca."""
    client, factory = harness
    ids = sembrar_connection(factory, sufijo="bloqueo-sin-cargo", con_presupuesto="10.0000",
                             gasto=Decimal("4.0000"))

    resp = client.post(AUDIT, headers=CABECERA, json={
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "user_id": ids["user_id"],
        "api_key_id": ids["key_id"],
        "model": "modelo-bloqueado-sin-cargo",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_usd": 0,
        "compliance_status": "blocked_guardian",
        "blocked_by_layer": "pii_masking",
        "latency_ms": 9,
        "user_group_id": ids["group_id"],
    })

    assert resp.status_code == 200, resp.text
    assert presupuesto_de(factory, ids["user_id"])["gasto"] == Decimal("4.0000")


def test_si_falla_el_presupuesto_la_fila_de_auditoria_sobrevive(harness, monkeypatch):
    """El registro es el entregable del endpoint: que el contador de gasto explote no
    puede llevarse puesta la fila (y el fallo queda en el log, jamás en silencio)."""
    client, factory = harness
    ids = sembrar_connection(factory, sufijo="presu-roto", con_presupuesto="10.0000")
    modelo = "modelo-con-presupuesto-roto"

    from src.api import internal

    def _explota(*_a, **_kw):
        raise RuntimeError("presupuesto inaccesible")

    monkeypatch.setattr(internal.BudgetService, "update_budget", staticmethod(_explota))

    resp = client.post(AUDIT, headers=CABECERA, json={
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "user_id": ids["user_id"],
        "api_key_id": ids["key_id"],
        "model": modelo,
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost_usd": 0.001,
        "compliance_status": "passed",
        "latency_ms": 100,
        "user_group_id": ids["group_id"],
    })

    assert resp.status_code == 200, resp.text
    assert fila_por_modelo(factory, modelo) is not None
    assert presupuesto_de(factory, ids["user_id"])["gasto"] == Decimal("0")


def test_el_gasto_registrado_es_el_del_evento_no_el_de_la_tabla_local(harness):
    """El motor conoce el coste real de la respuesta del proveedor; `MODEL_PRICING` es la
    aproximación del backend. Si acá recalculáramos, la fila de `audit_logs` y el contador
    del presupuesto contarían historias distintas — y las dos se auditan."""
    client, factory = harness
    ids = sembrar_connection(factory, sufijo="coste-del-evento", con_presupuesto="10.0000")

    client.post(AUDIT, headers=CABECERA, json={
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "user_id": ids["user_id"],
        "api_key_id": ids["key_id"],
        # Modelo desconocido para MODEL_PRICING: recalcular acá lo cobraría al `default`
        # conservador de $5/$15 por millón y el contador se despegaría de la fila.
        "model": "modelo-de-proveedor-desconocido",
        "prompt_tokens": 100000,
        "completion_tokens": 0,
        "cost_usd": 0.0100,
        "compliance_status": "passed",
        "latency_ms": 400,
        "user_group_id": ids["group_id"],
    })

    fila = fila_por_modelo(factory, "modelo-de-proveedor-desconocido")
    estado = presupuesto_de(factory, ids["user_id"])
    assert estado["gasto"] == Decimal("0.0100")
    assert estado["gasto"] == fila["cost_usd"]
