"""T060 (057 FR-021, FR-031a, FR-051): la instantánea del plano de datos trae las regiones y las relajaciones vigentes.

`load_from_session` suma `regions` (instalación + las de la empresa; nunca las de otra) y `relaxations`
(solo las vigentes cuya ficha todavía cumple las precondiciones: una cuya ficha dejó de cumplir no tiene efecto al
resolver aunque la fila siga sin revocar), y las filas de postura con `created_by_role`."""
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redirect_fixtures as fx  # noqa: E402

from sentinel.catalog import models as cm  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402
from sentinel.redirect.store import load_from_session  # noqa: E402

T = uuid.UUID(fx.TENANT)
OTRA = uuid.UUID(fx.OTHER)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    rm.RedirectBase.metadata.create_all(engine)
    cm.CatalogBase.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(rm.RedirectPolicy(id=uuid.uuid4(), tenant_id=T, scope_type="tenant", scope_value="*", state="on"))
    s.commit()
    yield s
    s.close()


def region(db, name, *, tenant=None, profiles=("p",), posture="masked_all"):
    db.add(rm.RedirectRegion(id=uuid.uuid4(), level="installation" if tenant is None else "tenant", tenant_id=tenant,
                             name=name, jurisdictions=["US"], region_profiles=list(profiles), default_posture=posture,
                             is_zone=True))
    db.commit()


def relajacion(db, entry, *, level="tenant", tenant=T, revocada=False):
    from datetime import datetime, timezone
    r = rm.RedirectMaskingRelaxation(id=uuid.uuid4(), level=level, tenant_id=None if level == "installation" else tenant,
                                     entry_id=uuid.UUID(entry["id"]), reason="motivo de prueba",
                                     created_by_role="compliance_officer",
                                     revoked_at=datetime.now(timezone.utc) if revocada else None)
    db.add(r)
    db.commit()
    return r


def snap(db):
    return load_from_session(db, str(T))


def test_trae_las_regiones_de_instalacion_y_las_de_la_empresa_nunca_las_de_otra(db):
    region(db, "INSTALACION", profiles=("a",))
    region(db, "PROPIA", tenant=T, profiles=("b",))
    region(db, "AJENA", tenant=OTRA, profiles=("c",))
    nombres = {r["name"] for r in snap(db).regions}
    assert nombres == {"INSTALACION", "PROPIA"}


def test_la_region_viaja_con_todos_sus_campos_y_ids_en_texto(db):
    region(db, "R")
    [r] = snap(db).regions
    assert r["jurisdictions"] == ["US"] and r["region_profiles"] == ["p"] and r["default_posture"] == "masked_all"
    assert r["is_zone"] is True and r["tenant_id"] is None and isinstance(r["id"], str)


def test_sin_regiones_la_instantanea_la_trae_vacia(db):
    assert snap(db).regions == () and snap(db).relaxations == ()


def test_una_relajacion_vigente_con_la_ficha_completa_llega(db):
    e = fx.seed_entry(db, inference="US", entity="US", zero_data_retention=True)
    relajacion(db, e)
    assert [(r["entry_id"], r["level"]) for r in snap(db).relaxations] == [(e["id"], "tenant")]


def test_una_revocada_no_llega(db):
    e = fx.seed_entry(db, inference="US", entity="US", zero_data_retention=True)
    relajacion(db, e, revocada=True)
    assert snap(db).relaxations == ()


@pytest.mark.parametrize("kw", [{"inference": "unknown"}, {"entity": None}, {"control": None},
                                {"zero_data_retention": None}, {"zero_data_retention": False}])
def test_una_cuya_ficha_ya_no_cumple_no_llega_aunque_siga_sin_revocar(db, kw):
    base = dict(inference="US", entity="US", control="US", zero_data_retention=True)
    e = fx.seed_entry(db, **{**base, **kw})
    relajacion(db, e)
    assert snap(db).relaxations == ()


def test_una_entrada_archivada_o_inactiva_no_relaja(db):
    for estado in ("archived", "inactive"):
        e = fx.seed_entry(db, name=f"E-{estado}", status=estado, inference="US", entity="US", zero_data_retention=True)
        relajacion(db, e)
    assert snap(db).relaxations == ()


def test_un_agregador_sin_lista_no_llega_y_con_lista_si(db):
    kw = dict(provider="openrouter", is_aggregator=True, inference="US", entity="US", zero_data_retention=True)
    sin = fx.seed_entry(db, name="sin", **kw)
    con = fx.seed_entry(db, name="con", provider_options={"providers_allowlist": ["acme-us"]}, **kw)
    relajacion(db, sin)
    relajacion(db, con)
    assert [r["entry_id"] for r in snap(db).relaxations] == [con["id"]]


def test_una_de_instalacion_llega_a_todas_las_empresas_y_una_de_otra_empresa_no(db):
    inst = fx.seed_entry(db, name="inst", level="installation", offered_to=["*"], inference="US", entity="US",
                         zero_data_retention=True)
    ajena = fx.seed_entry(db, name="ajena", level="tenant", tenant=fx.OTHER, inference="US", entity="US",
                          zero_data_retention=True)
    relajacion(db, inst, level="installation")
    relajacion(db, ajena, tenant=OTRA)
    assert [r["entry_id"] for r in snap(db).relaxations] == [inst["id"]]


def test_las_filas_de_postura_llevan_el_rol_de_quien_las_escribio(db):
    db.add(rm.RedirectPosture(id=uuid.uuid4(), tenant_id=T, scope_type="tenant", scope_value="*", mode="off",
                              jurisdictions=[], reason="motivo", created_by_role="tenant_admin"))
    db.commit()
    [p] = snap(db).postures
    assert p["created_by_role"] == "tenant_admin"


def test_sin_las_tablas_del_catalogo_las_relajaciones_son_ninguna():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    rm.RedirectBase.metadata.create_all(engine)                     # catálogo sin migrar
    s = sessionmaker(bind=engine)()
    s.add(rm.RedirectPolicy(id=uuid.uuid4(), tenant_id=T, scope_type="tenant", scope_value="*", state="on"))
    s.add(rm.RedirectMaskingRelaxation(id=uuid.uuid4(), level="tenant", tenant_id=T, entry_id=uuid.uuid4(),
                                       reason="x", created_by_role="compliance_officer"))
    s.commit()
    assert load_from_session(s, str(T)).relaxations == ()
