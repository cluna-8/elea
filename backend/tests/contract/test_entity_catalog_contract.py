"""Contract test end-to-end de la 016 US5 (T046) contra Postgres REAL — no un
Guardian fake. Cubre los 3 hallazgos de review formalizados como tasks T043-T045:
sanitización de entity_type, unicidad entre activas, y locking real ante
escritura concurrente (el fake de test_entity_catalog_service.py no puede
probar `with_for_update()` de verdad — necesita una base real).

Se auto-skipea si Postgres no está levantado (mismo patrón que
`migration_harness.py`): `docker compose up -d db`.
"""
import threading
import uuid

import pytest

from tests.migration_harness import require_postgres

require_postgres()

from src.database import SessionLocal  # noqa: E402
from src.models.guardian import Guardian  # noqa: E402
from src.models.tenant import DEFAULT_TENANT_ID  # noqa: E402
from src.services import entity_catalog_service as svc  # noqa: E402


@pytest.fixture
def clean_pii_guardian():
    """Aísla cada test: deja el Guardian pii_masking del tenant default sin
    entidades custom antes y después (no toca otros campos ya seedeados)."""
    db = SessionLocal()
    try:
        svc.list_custom_entities(db, DEFAULT_TENANT_ID)  # auto-provisiona si hace falta
        guardian = db.query(Guardian).filter(
            Guardian.tenant_id == DEFAULT_TENANT_ID, Guardian.guardian_type == "pii_masking"
        ).first()
        guardian.config = {**guardian.config, "custom_entities": []}
        db.commit()
        yield db
    finally:
        guardian = db.query(Guardian).filter(
            Guardian.tenant_id == DEFAULT_TENANT_ID, Guardian.guardian_type == "pii_masking"
        ).first()
        if guardian:
            guardian.config = {**guardian.config, "custom_entities": []}
            db.commit()
        db.close()


def test_create_rejects_invalid_entity_type_against_real_db(clean_pii_guardian):
    db = clean_pii_guardian
    with pytest.raises(svc.InvalidEntityTypeError):
        svc.create_custom_entity(
            db, DEFAULT_TENANT_ID, name="Raro", entity_type="TIPO]RARO",
            regex=r"\bHC-\d{6}\b",
        )
    assert svc.list_custom_entities(db, DEFAULT_TENANT_ID) == []


def test_create_rejects_duplicate_active_entity_type_against_real_db(clean_pii_guardian):
    db = clean_pii_guardian
    svc.create_custom_entity(
        db, DEFAULT_TENANT_ID, name="v1", entity_type="HISTORIA_CLINICA_ES",
        regex=r"\bHC-\d{6}\b",
    )
    with pytest.raises(svc.DuplicateEntityTypeError):
        svc.create_custom_entity(
            db, DEFAULT_TENANT_ID, name="v2", entity_type="historia_clinica_es",
            regex=r"\bHC-\d{7}\b",
        )
    assert len(svc.list_custom_entities(db, DEFAULT_TENANT_ID)) == 1


def test_concurrent_creates_do_not_lose_updates(clean_pii_guardian):
    """T045: N hilos creando entidades DISTINTAS en paralelo, cada uno con su
    propia sesión (como en producción, una por request) — sin el lock de fila
    (`with_for_update`), esto pierde escrituras (lost update) porque todas leen
    la misma lista antes de que la primera comitee. Con el lock, Postgres
    serializa: cada transacción espera a la anterior antes de leer."""
    n = 8
    errors = []

    def _create(i):
        db = SessionLocal()
        try:
            svc.create_custom_entity(
                db, DEFAULT_TENANT_ID, name=f"Concurrente {i}",
                entity_type=f"CONCURRENTE_{i}_{uuid.uuid4().hex[:6]}",
                regex=rf"\bZZ-{i}\d{{4}}\b",
            )
        except Exception as e:  # pragma: no cover - solo si algo sale mal
            errors.append(e)
        finally:
            db.close()

    threads = [threading.Thread(target=_create, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, f"errores inesperados: {errors}"
    verify_db = SessionLocal()
    try:
        entities = svc.list_custom_entities(verify_db, DEFAULT_TENANT_ID)
        assert len(entities) == n, (
            f"se esperaban {n} entidades, hay {len(entities)} — lost update real"
        )
    finally:
        verify_db.close()
