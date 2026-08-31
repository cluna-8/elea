"""Tests de la migración 013 — columna ``routing_decision`` y su NO-interacción con la
hash-chain de licencias (spec 030, data-model §3).

La migración es de una sola columna, pero tiene dos invariantes que sí se pueden romper
sin darse cuenta:

1. **Nullable, sin default y sin índice.** NULL debe seguir significando "esta consulta no
   pasó por el auto-router" — un default ``'{}'`` lo volvería indistinguible de "hubo
   ruteo vacío", y un índice GIN sobre JSONB cobraría escritura en la tabla más caliente
   del sistema para una query que en v1 nadie hace.
2. **La columna queda FUERA del payload de la hash-chain 021.** Es la razón por la que la
   decisión NO se guarda dentro de ``guardian_events`` (congelado: la cadena lo relee
   posicionalmente, licensing/audit_events.py:92-93). El último test lo prueba de verdad:
   escribe ``routing_decision`` sobre las filas YA encadenadas y verifica que la cadena
   sigue válida y el head no se movió.

Mismo harness que la 012: Postgres de Docker Compose, conectado como ``rls_owner``
(NOSUPERUSER dueño de las tablas). Self-skip si Postgres no está.
"""
import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from migration_harness import (
    DEFAULT_TENANT, fresh_db, owner_engine, require_postgres, run_alembic,
)

require_postgres()

DB = "sentinel_test_migration_013"

# El objeto decisión COMPLETO de data-model §2 — se guarda tal cual, sin transformar.
DECISION = {
    "requested": "auto",
    "route": "Código y análisis",
    "score": 0.61,
    "model_selected": "gpt-4o",
    "degraded": False,
    "reason": None,
}
# Variante degradada: `route` NULL y `reason` con el motivo concreto (FR-004).
DECISION_DEGRADED = {
    "requested": "auto",
    "route": None,
    "score": 0.0,
    "model_selected": "camara-comercio-local",
    "degraded": True,
    "reason": "embed_timeout",
}


@pytest.fixture(scope="module")
def engine():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    eng = owner_engine(DB)
    yield eng
    eng.dispose()


# ── Esquema ────────────────────────────────────────────────────────────────────────────

def test_routing_decision_is_nullable_jsonb_without_default(engine):
    """data-model §3: JSONB nullable, SIN default y SIN backfill. Las filas históricas no
    tuvieron ruteo y NULL dice exactamente eso."""
    with engine.connect() as cx:
        col = cx.execute(text("""
            SELECT data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'audit_logs' AND column_name = 'routing_decision'
        """)).one_or_none()

    assert col is not None, "falta audit_logs.routing_decision"
    assert col.data_type == "jsonb"
    assert col.is_nullable == "YES"
    assert col.column_default is None, f"la columna no debe tener default: {col.column_default}"


def test_no_index_on_routing_decision(engine):
    """v1 la lee como DETALLE de una fila ya localizada por (tenant, timestamp), nunca
    como filtro: indexarla sería pagar escritura en audit_logs por nada."""
    with engine.connect() as cx:
        indexdefs = [r.indexdef for r in cx.execute(text(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'audit_logs'"
        ))]
    assert not [d for d in indexdefs if "routing_decision" in d], indexdefs


def test_row_accepts_the_decision_object_and_defaults_to_null(engine):
    """Control positivo + semántica del NULL: una fila sin ruteo y otra con la decisión
    completa de data-model §2 conviven en la misma tabla."""
    with engine.begin() as cx:
        cx.execute(text("""
            INSERT INTO audit_logs (tenant_id, model, prompt_tokens, completion_tokens,
                                    cost_usd, compliance_status, latency_ms)
            VALUES (:tenant, 'sin-ruteo', 1, 1, 0.0, 'passed', 10)
        """), {"tenant": DEFAULT_TENANT})
        cx.execute(text("""
            INSERT INTO audit_logs (tenant_id, model, prompt_tokens, completion_tokens,
                                    cost_usd, compliance_status, latency_ms, routing_decision)
            VALUES (:tenant, 'gpt-4o', 1, 1, 0.0, 'passed', 10, :decision)
        """), {"tenant": DEFAULT_TENANT, "decision": json.dumps(DECISION)})

        sin = cx.execute(text(
            "SELECT routing_decision FROM audit_logs WHERE model = 'sin-ruteo'"
        )).scalar()
        con = cx.execute(text(
            "SELECT routing_decision FROM audit_logs WHERE model = 'gpt-4o'"
        )).scalar()

    assert sin is None, "sin auto-router la columna queda NULL (no '{}')"
    assert con == DECISION, "la decisión se persiste sin transformar"


# ── La invariante que importa: la cadena de licencias no ve esta columna ────────────────

def test_writing_routing_decision_does_not_break_the_license_hash_chain(engine):
    """Gate de T005: la hash-chain 021 arma su payload con un dict de claves fijas
    (``_append_chained``) y lo recomputa desde ``guardian_events[0]`` — no mira las
    columnas de la fila. Escribir ``routing_decision`` sobre filas YA encadenadas debe
    dejar la cadena válida y el head intacto. Si alguien algún día mete la decisión
    DENTRO de ``guardian_events``, este test se pone rojo."""
    from src.licensing.audit_events import EVENT_SEAT_LIMIT, emit_license_event, verify_chain
    from src.models.license_state import LicenseRuntimeState

    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()
    try:
        for i in range(3):
            emit_license_event(db, EVENT_SEAT_LIMIT, license_id="lic_mig_013",
                               seats_used=10 + i, max_seats=10, reason=f"mig-013-{i}")
        head_before = db.query(LicenseRuntimeState).filter_by(id=1).one().hash_head
        assert verify_chain(db)["ok"], "la cadena ya venía rota antes de tocar nada"

        # La decisión de ruteo aterriza en la fila de auditoría, al lado del evento.
        db.execute(text("UPDATE audit_logs SET routing_decision = CAST(:d AS JSONB)"),
                   {"d": json.dumps(DECISION_DEGRADED)})
        db.commit()

        report = verify_chain(db)
        head_after = db.query(LicenseRuntimeState).filter_by(id=1).one().hash_head
    finally:
        db.close()

    assert report["ok"], report
    assert report["checked"] >= 3
    assert head_after == head_before, "el head se movió: la columna entró a la cadena"


# ── Ida y vuelta ───────────────────────────────────────────────────────────────────────

def test_downgrade_then_reupgrade_is_clean(engine):
    """El downgrade no deja restos y no se lleva puesto nada de la 012 (``applied_layers``
    y ``blocked_by_layer`` siguen en pie); un upgrade posterior vuelve a head."""
    run_alembic(DB, "downgrade", "012")

    with engine.connect() as cx:
        assert cx.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'audit_logs' AND column_name = 'routing_decision'
        """)).scalar() == 0
        assert cx.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'audit_logs'
              AND column_name IN ('applied_layers', 'blocked_by_layer')
        """)).scalar() == 2

    run_alembic(DB, "upgrade", "head")
    with engine.connect() as cx:
        assert cx.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'audit_logs' AND column_name = 'routing_decision'
        """)).scalar() == 1


def test_upgrade_body_is_idempotent(engine):
    """Re-ejecutar el cuerpo de la 013 sobre el esquema ya migrado (stamp 012 → upgrade
    head) no falla: patrón IF NOT EXISTS del repo."""
    run_alembic(DB, "stamp", "012")
    run_alembic(DB, "upgrade", "head")

    with engine.connect() as cx:
        assert cx.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'audit_logs' AND column_name = 'routing_decision'
        """)).scalar() == 1
