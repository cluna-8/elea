"""`DELETE /users/groups/{id}` (spec 054, 17-sep) — hasta esta spec un equipo se podía
crear pero nunca dar de baja ("es un error grave", reportado en vivo probando la spec 053).
Mismo patrón que `deactivate_user`: no es baja física, revoca Connections propias del
grupo, libera a los miembros a "sin equipo", y la auditoría histórica sigue intacta."""
import uuid

import pytest

from migration_harness import require_postgres
from seat_gate_harness import admin_headers, build_app_client

require_postgres()

DB = "sentinel_test_group_deactivation_054"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


def test_dar_de_baja_desactiva_libera_miembros_y_revoca_connections(harness):
    client, factory, headers = harness
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.user import User, Group
    from src.models.budget import APIKey

    db = factory()
    try:
        suf = uuid.uuid4().hex[:6]
        grupo = Group(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, name=f"equipo-baja-{suf}")
        db.add(grupo)
        db.flush()

        miembro = User(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, username=f"miembro-{suf}",
                        email=f"miembro-{suf}@x.test", password_hash="!", role="client",
                        group_id=grupo.id)
        db.add(miembro)
        db.flush()

        llave = APIKey(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, key_hash=f"hash-{suf}",
                        key_preview="sk-...test", group_id=grupo.id, name="llave del equipo",
                        is_active=True)
        db.add(llave)
        db.commit()

        grupo_id, miembro_id, llave_id, nombre = grupo.id, miembro.id, llave.id, grupo.name
    finally:
        db.close()

    r = client.delete(f"/api/v1/users/groups/{grupo_id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "deactivated"
    assert body["members_unassigned"] == 1

    db = factory()
    try:
        grupo_db = db.query(Group).filter(Group.id == grupo_id).first()
        assert grupo_db.is_active is False
        assert grupo_db.deactivated_at is not None

        miembro_db = db.query(User).filter(User.id == miembro_id).first()
        assert miembro_db.group_id is None, "el miembro debe quedar sin equipo, no borrado"

        llave_db = db.query(APIKey).filter(APIKey.id == llave_id).first()
        assert llave_db.is_active is False, "la Connection del grupo debe revocarse"
    finally:
        db.close()

    # Segunda baja: 409, ya está de baja.
    r2 = client.delete(f"/api/v1/users/groups/{grupo_id}", headers=headers)
    assert r2.status_code == 409


def test_grupo_inactivo_no_aparece_en_list_groups_por_defecto(harness):
    client, factory, headers = harness
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.user import Group

    db = factory()
    try:
        suf = uuid.uuid4().hex[:6]
        grupo = Group(id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID, name=f"equipo-oculto-{suf}")
        db.add(grupo)
        db.commit()
        grupo_id, nombre = grupo.id, grupo.name
    finally:
        db.close()

    client.delete(f"/api/v1/users/groups/{grupo_id}", headers=headers)

    r = client.get("/api/v1/users/groups", headers=headers)
    nombres = {g["name"] for g in r.json()}
    assert nombre not in nombres

    r2 = client.get("/api/v1/users/groups?include_inactive=true", headers=headers)
    nombres2 = {g["name"] for g in r2.json()}
    assert nombre in nombres2
