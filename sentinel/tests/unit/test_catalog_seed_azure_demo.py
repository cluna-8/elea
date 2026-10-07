"""Datos de ejemplo del catálogo de Azure (057 T023; FR-020, research R9; QA M2).

`deploy/redirect-seeds/catalog-seed.azure-demo.yaml` es un dato editable de la instalación de demo: cuatro destinos
(`gpt-5.6-luna`, `gpt-5.1-chat`, `gpt-5.4-mini`, `gpt-4o-mini`), provider `azure`, `real_model` = nombre del despliegue,
credencial **adoptada** (referencias a variables del servidor, sin valores), y la jurisdicción de inferencia, la entidad
responsable y las jurisdicciones de entidad y de control **vacías y marcadas obligatorias**: no se presume la región.
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from sentinel.catalog import credentials as cr  # noqa: E402
from sentinel.catalog import models as cm  # noqa: E402
from sentinel.catalog import store as cs  # noqa: E402
from sentinel.catalog.seed import _validate, load_seed_file, seed_catalog  # noqa: E402

SEED_FILE = ROOT / "deploy" / "redirect-seeds" / "catalog-seed.azure-demo.yaml"
NOMBRES = ["gpt-5.6-luna", "gpt-5.1-chat", "gpt-5.4-mini", "gpt-4o-mini"]
PROHIBIDOS = [n.strip().lower() for n in (ROOT / "deploy/release/checks/prohibited_names.txt").read_text().splitlines()
              if n.strip() and not n.startswith("#")]
FICHA_OBLIGATORIA = ("jurisdicción de inferencia", "entidad responsable", "jurisdicción de la entidad",
                     "jurisdicción de control")


def _cifra(texto: str) -> str:
    return "cifrado:" + texto[::-1]


def _descifra(blob: str) -> str:
    return blob[len("cifrado:"):][::-1]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    cm.CatalogBase.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture(scope="module")
def seed():
    return load_seed_file(SEED_FILE)


def test_el_archivo_valida_con_el_validador_del_catalogo(seed):
    assert [e["name"] for e in _validate(seed)] == NOMBRES


def test_son_destinos_de_azure_con_el_modelo_real_igual_al_despliegue(seed):
    for e in seed["entries"]:
        assert e["provider"] == "azure" and e["real_model"] == e["name"] == e["public_id"], e["name"]
        assert e["protocol_family"] == "openai_chat"


def test_gpt_5_6_luna_se_siembra_y_la_verificacion_de_despliegue_decide_si_queda_activa(seed):
    """El coordinador informó el 2026-10-06 que existe; el seed no la filtra (T022 la deja inactiva si no existe)."""
    assert "gpt-5.6-luna" in [e["name"] for e in seed["entries"]]
    assert "2026-10-06" in SEED_FILE.read_text()


def test_la_ventana_y_el_precio_son_los_del_mapa_de_costos_y_donde_no_hay_dato_queda_vacio(seed):
    por = {e["name"]: e for e in seed["entries"]}
    assert (por["gpt-5.1-chat"]["price_input_per_mtok"], por["gpt-5.1-chat"]["price_output_per_mtok"]) == (1.25, 10.0)
    assert (por["gpt-5.4-mini"]["price_input_per_mtok"], por["gpt-5.4-mini"]["price_output_per_mtok"]) == (0.75, 4.5)
    assert (por["gpt-4o-mini"]["price_input_per_mtok"], por["gpt-4o-mini"]["price_output_per_mtok"]) == (0.15, 0.6)
    for n in ("gpt-5.1-chat", "gpt-5.4-mini", "gpt-4o-mini"):
        assert por[n]["context_window"] and por[n]["max_output"] and por[n]["price_source"]
    luna = por["gpt-5.6-luna"]                        # sin dato verificado: no se inventa
    assert "price_input_per_mtok" not in luna and "context_window" not in luna and "PENDIENTE" in luna["price_source"]


def test_la_ficha_no_presume_ninguna_jurisdiccion_y_marca_lo_obligatorio(seed):
    for e in seed["entries"]:
        ficha = e["sheet"]
        for campo in ("inference_jurisdiction", "entity_jurisdiction", "control_jurisdiction", "provider_legal_entity"):
            assert not ficha.get(campo), (e["name"], campo)
        assert "OBLIGATORIO" in ficha["notes"]
        assert all(t in ficha["notes"] for t in FICHA_OBLIGATORIA), e["name"]


def test_no_lleva_secretos_ni_valores_ni_nombres_de_motores_internos():
    import re
    texto = SEED_FILE.read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9_-]{8,}|bearer\s+\S|eyJ[A-Za-z0-9_-]{10,}\.|[A-Za-z0-9]{40,}", texto, re.I)
    assert "api_key:" in texto and "AZURE_API_KEY" in texto            # referencia por nombre, nunca el valor
    assert not [n for n in PROHIBIDOS if n in texto.lower()]            # marca neutra (FR-050)


def test_la_credencial_es_una_referencia_a_variables_sin_valores(seed):
    for e in seed["entries"]:
        ref = e["credential_ref"]
        assert ref == {"name": "azure-recurso", "env": {"api_key": "AZURE_API_KEY", "api_version": "AZURE_API_VERSION"}}


def test_se_carga_y_es_idempotente(db, seed):
    r1 = seed_catalog(db, seed, encrypt=_cifra)
    db.commit()
    assert r1 == {"created": NOMBRES, "skipped": []}
    r2 = seed_catalog(db, seed, encrypt=_cifra)
    db.commit()
    assert r2 == {"created": [], "skipped": NOMBRES}
    assert db.query(cm.CatalogEntry).count() == 4 and db.query(cm.ComplianceSheet).count() == 4
    assert db.query(cm.Credential).count() == 1                          # una sola credencial adoptada, compartida


def test_la_credencial_guardada_es_solo_la_referencia_y_las_cuatro_entradas_la_comparten(db, seed):
    seed_catalog(db, seed, encrypt=_cifra)
    db.commit()
    (cred,) = db.query(cm.Credential).all()
    assert cred.level == "installation" and cred.tenant_id is None and cred.status == "active"
    assert json.loads(_descifra(cred.ciphertext)) == {"api_key": "env:AZURE_API_KEY", "api_version": "env:AZURE_API_VERSION"}
    assert {e.credential_id for e in db.query(cm.CatalogEntry)} == {cred.id}
    cr.validate_for("azure", cr.resolve(cred, _descifra), "installation")   # tiene la forma que exige Azure


def test_los_destinos_nacen_activos_sin_bloqueo_sin_jurisdiccion_y_sin_clasificar(db, seed):
    seed_catalog(db, seed, encrypt=_cifra)
    db.commit()
    for e in db.query(cm.CatalogEntry):
        sheet = db.get(cm.ComplianceSheet, e.id)
        assert e.status == "active" and e.blocked_by_default is False and e.source == "seed" and e.level == "installation"
        assert sheet.inference_jurisdiction == "unknown" and not sheet.entity_jurisdiction
        assert not sheet.control_jurisdiction and not sheet.provider_legal_entity
        view = cs.sheet_view(sheet)
        assert view["inference_jurisdiction"] == "unknown"


def test_sin_jurisdiccion_de_inferencia_el_destino_no_esta_en_region(db, seed):
    from sentinel.catalog.region import in_region
    seed_catalog(db, seed, encrypt=_cifra)
    db.commit()
    for e in db.query(cm.CatalogEntry):
        assert in_region(db.get(cm.ComplianceSheet, e.id), frozenset({"US", "AR", "LATAM"})) is False


def test_nunca_pisa_lo_que_el_operador_edito(db, seed):
    seed_catalog(db, seed, encrypt=_cifra)
    db.commit()
    e = db.query(cm.CatalogEntry).filter_by(name="gpt-5.1-chat").one()
    e.api_base, e.price_input = "https://mi-recurso.openai.azure.com", 0.00000999
    sheet = db.get(cm.ComplianceSheet, e.id)
    sheet.inference_jurisdiction = "US"
    db.commit()
    seed_catalog(db, seed, encrypt=_cifra)
    db.commit()
    e = db.query(cm.CatalogEntry).filter_by(name="gpt-5.1-chat").one()
    assert e.api_base == "https://mi-recurso.openai.azure.com" and float(e.price_input) == pytest.approx(0.00000999)
    assert db.get(cm.ComplianceSheet, e.id).inference_jurisdiction == "US"


# ── la clave `credential_ref` no es una puerta para secretos ──────────────────────────────────────

BASE = {"name": "X", "provider": "azure", "real_model": "x", "protocol_family": "openai_chat"}


@pytest.mark.parametrize("ref", [
    {"name": "c", "env": {"api_key": "sk-valor-literal-que-parece-un-secreto", "api_version": "AZURE_API_VERSION"}},
    {"name": "c", "env": {"api_key": "env:AZURE_API_KEY", "api_version": "AZURE_API_VERSION"}},     # ya con prefijo
    {"name": "c", "env": {"api_key": "FERNET_SECRET_KEY", "api_version": "AZURE_API_VERSION"}},      # lista negra
    {"name": "c", "env": {"api_key": "AZURE_API_KEY"}},                                              # falta api_version
    {"name": "c", "env": {"api_key": "AZURE_API_KEY", "api_version": "AZURE_API_VERSION", "otro": "X_Y"}},
    {"name": "c", "env": {}}, {"env": {"api_key": "AZURE_API_KEY"}}, {"name": "c"}, "AZURE_API_KEY", [],
    {"name": "c", "env": {"api_key": "AZURE_API_KEY", "api_version": "AZURE_API_VERSION"}, "value": "sk-x"},
])
def test_credential_ref_rechaza_valores_literales_y_variables_de_la_plataforma(ref):
    with pytest.raises(ValueError):
        _validate({"entries": [{**BASE, "credential_ref": ref}]})


def test_la_clave_credential_con_un_secreto_sigue_prohibida():
    with pytest.raises(ValueError, match="no admitidos"):
        _validate({"entries": [{**BASE, "credential": {"api_key": "sk-no-va-aqui"}}]})
