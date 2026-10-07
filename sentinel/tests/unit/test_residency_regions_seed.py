"""T064 (057 FR-030, FR-031; research R13, R23; data-model §1): cargador idempotente de regiones y seed de Eleia.

`python -m sentinel.redirect.regions_seed <archivo>`: crea la fila si no existe y **nunca pisa** lo que un
administrador cambió (reiniciar no revierte una relajación por región). Todo o nada: un valor desconocido de
`default_posture` es un error y no se escribe nada. El seed de Eleia siembra `AMERICAS` con `masked_all`."""
import sys
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sentinel" / "tests"))
from residency_fixtures import AMERICAS_JURISDICTIONS  # noqa: E402

from sentinel.redirect import models as m  # noqa: E402
from sentinel.redirect import regions_seed  # noqa: E402
from sentinel.redirect.residency import resolve_region, satisfies  # noqa: E402

SEED = ROOT / "deploy" / "redirect-seeds" / "regions.americas.yaml"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    m.RedirectBase.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _data(**kw):
    region = {"name": "OTRA", "level": "installation", "is_zone": True, "region_profiles": ["otra"],
              "default_posture": "masked_all", "jurisdictions": ["US", "AR"]}
    region.update(kw)
    return {"regions": [region]}


# ── el seed de Eleia ────────────────────────────────────────────────────────────────────────────────

def test_el_seed_de_eleia_es_americas_con_masked_all():
    data = yaml.safe_load(SEED.read_text(encoding="utf-8"))
    [region] = data["regions"]
    assert region["name"] == "AMERICAS" and region["level"] == "installation" and region["is_zone"] is True
    assert region["default_posture"] == "masked_all"                      # D2 del owner, 2026-10-06
    assert {"latam_ar"} <= set(region["region_profiles"])                 # ⊇ latam_ar
    assert set(region["jurisdictions"]) == set(AMERICAS_JURISDICTIONS)    # Norte, Centro, Caribe, Sur y LATAM
    assert regions_seed.check_seed(data)                                  # y valida


def test_el_seed_dice_que_americas_es_criterio_de_riesgo_no_de_legalidad():
    texto = SEED.read_text(encoding="utf-8").lower()
    assert "riesgo" in texto and "legalidad" in texto


def test_el_seed_de_eleia_se_siembra_y_resuelve_latam_ar(db):
    regions_seed.seed_regions(db, regions_seed.load_seed_file(SEED))
    rows = [{"tenant_id": None, "level": r.level, "name": r.name, "jurisdictions": r.jurisdictions,
             "region_profiles": r.region_profiles, "default_posture": r.default_posture, "is_zone": r.is_zone}
            for r in db.query(m.RedirectRegion)]
    region = resolve_region("latam_ar", rows, "t1")
    assert region.name == "AMERICAS" and region.default_posture == "masked_all"
    assert satisfies("BR", region.codes) and not satisfies("DE", region.codes)


def test_el_seed_no_nombra_marcas_ni_componentes_internos():
    texto = SEED.read_text(encoding="utf-8").lower()
    for prohibido in ("litellm", "berriai", "presidio"):
        assert prohibido not in texto


# ── el cargador ─────────────────────────────────────────────────────────────────────────────────────

def test_crea_la_fila_y_deja_el_registro(db):
    r = regions_seed.seed_regions(db, _data())
    assert r == {"created": 1, "skipped": 0}
    [row] = db.query(m.RedirectRegion).all()
    assert (row.level, row.tenant_id, row.name, row.default_posture) == ("installation", None, "OTRA", "masked_all")
    assert row.jurisdictions == ["US", "AR"] and row.region_profiles == ["otra"] and row.is_zone is True
    [aud] = db.query(m.RedirectConfigAudit).all()
    assert (aud.entity, aud.action, aud.actor_role, aud.tenant_id) == ("region", "create", "seed", None)
    assert aud.reason and "seed" in aud.reason


def test_es_idempotente(db):
    regions_seed.seed_regions(db, _data())
    r = regions_seed.seed_regions(db, _data())
    assert r == {"created": 0, "skipped": 1}
    assert db.query(m.RedirectRegion).count() == 1 and db.query(m.RedirectConfigAudit).count() == 1


def test_no_pisa_lo_que_un_administrador_cambio(db):
    regions_seed.seed_regions(db, _data())
    row = db.query(m.RedirectRegion).one()
    row.default_posture, row.jurisdictions = "masked_offregion", ["AR"]          # la relajación por región
    db.commit()
    regions_seed.seed_regions(db, _data())
    row = db.query(m.RedirectRegion).one()
    assert row.default_posture == "masked_offregion" and row.jurisdictions == ["AR"]


def test_un_perfil_ya_tomado_por_otra_fila_de_instalacion_se_salta(db):
    regions_seed.seed_regions(db, _data(name="PRIMERA", region_profiles=["x"]))
    r = regions_seed.seed_regions(db, _data(name="SEGUNDA", region_profiles=["x"]))
    assert r == {"created": 0, "skipped": 1}
    assert [x.name for x in db.query(m.RedirectRegion)] == ["PRIMERA"]


@pytest.mark.parametrize("campo,valor", [
    ("default_posture", "desconocido"), ("default_posture", None), ("default_posture", ""),
    ("name", "con espacio"), ("name", "minuscula"), ("name", ""), ("jurisdictions", []),
    ("jurisdictions", "US"), ("jurisdictions", ["no valido!"]), ("level", "tenant"), ("level", "x"),
    ("region_profiles", "latam_ar"), ("is_zone", "si"),
])
def test_un_valor_invalido_es_error_y_no_se_escribe_nada(db, campo, valor):
    data = {"regions": [_data(name="BUENA", region_profiles=["b"])["regions"][0], _data(**{campo: valor})["regions"][0]]}
    with pytest.raises(ValueError):
        regions_seed.seed_regions(db, data)
    assert db.query(m.RedirectRegion).count() == 0 and db.query(m.RedirectConfigAudit).count() == 0


@pytest.mark.parametrize("data", [None, [], "texto", {"regions": "x"}, {"otra": []}, {"regions": ["x"]}])
def test_un_documento_que_no_es_el_esperado_es_error(db, data):
    with pytest.raises(ValueError):
        regions_seed.seed_regions(db, data)


def test_un_documento_vacio_no_hace_nada(db):
    assert regions_seed.seed_regions(db, {"regions": []}) == {"created": 0, "skipped": 0}


def test_claves_desconocidas_son_error(db):
    with pytest.raises(ValueError):
        regions_seed.seed_regions(db, _data(rol="super_admin"))


def test_normaliza_codigos_y_perfiles(db):
    regions_seed.seed_regions(db, _data(jurisdictions=["us", " ar ", "us"], region_profiles=["Latam_AR", "latam_ar"]))
    row = db.query(m.RedirectRegion).one()
    assert row.jurisdictions == ["US", "AR"] and row.region_profiles == ["latam_ar"]


def test_los_cuatro_valores_de_default_posture_se_aceptan(db):
    for i, valor in enumerate(("reject_offregion", "masked_offregion", "masked_all", "allow")):
        regions_seed.seed_regions(db, _data(name=f"R{i}", region_profiles=[f"p{i}"], default_posture=valor))
    assert db.query(m.RedirectRegion).count() == 4


def test_load_seed_file_lee_yaml_y_vacio_es_un_documento_vacio(tmp_path):
    f = tmp_path / "r.yaml"
    f.write_text("", encoding="utf-8")
    assert regions_seed.load_seed_file(f) == {"regions": []}


def test_cli_devuelve_codigo_de_salida(tmp_path, monkeypatch, db, capsys):
    f = tmp_path / "r.yaml"
    f.write_text(yaml.safe_dump(_data()), encoding="utf-8")
    monkeypatch.setattr(regions_seed, "SESSION_FACTORY", lambda: db)
    assert regions_seed.main([str(f)]) == 0
    assert "1" in capsys.readouterr().out
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(_data(default_posture="x")), encoding="utf-8")
    assert regions_seed.main([str(bad)]) == 1
    assert regions_seed.main([]) == 2
