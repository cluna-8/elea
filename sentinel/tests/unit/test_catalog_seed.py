"""Siembra del catálogo desde el perfil de instalación (069 T031; FR-007).

Solo inserta lo que falta y nunca pisa una ficha editada. Sin credenciales: las carga el operador.
"""
import sys
import uuid
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from sentinel.catalog import models as cm  # noqa: E402
from sentinel.catalog.seed import load_seed_file, seed_catalog  # noqa: E402
from sentinel.catalog.store import semaforo_of  # noqa: E402

SEED = {"entries": [{
    "name": "OpenRouter — GLM 4.6", "provider": "openrouter", "real_model": "z-ai/glm-4.6",
    "protocol_family": "openai_chat", "aggregator": True, "capability": "standard",
    "features": {"tools": True},
    "sheet": {"provider_legal_entity": "OpenRouter, Inc.", "inference_jurisdiction": "US",
              "logs_jurisdiction": "none", "zero_data_retention": True, "trains_on_data": None,
              "transfer_mechanism": "scc", "eu_region_contracted": False,
              "notes": "cubre solo la capa del agregador"},
}]}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    cm.CatalogBase.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_siembra_entrada_de_instalacion_agregador_con_ficha_y_sin_credencial(db):
    r = seed_catalog(db, SEED)
    assert r == {"created": ["OpenRouter — GLM 4.6"], "skipped": []}
    e = db.query(cm.CatalogEntry).one()
    assert e.level == "installation" and e.tenant_id is None and e.source == "seed"
    assert e.public_id == "openrouter-glm-4.6" and e.is_aggregator is True and e.credential_id is None and e.features == {"tools": True}
    s = db.get(cm.ComplianceSheet, e.id)
    assert s.inference_jurisdiction == "US" and s.transfer_mechanism == "scc"
    assert s.classification_version.startswith("seed:") and s.classified_at is not None
    assert db.query(cm.Credential).count() == 0 and db.query(cm.CatalogOffer).count() == 0


def test_la_ficha_sembrada_es_honesta_no_afirma_lo_que_no_se_investigo(db):
    seed_catalog(db, SEED)
    e = db.query(cm.CatalogEntry).one()
    sem = semaforo_of(e, db.get(cm.ComplianceSheet, e.id), None, date(2026, 10, 1))
    assert sem["estado"] == "unclassified"          # «entrena con datos» quedó por verificar
    assert "dato_desconocido:trains_on_data" in sem["motivos"]


def test_idempotente_y_solo_inserta_lo_que_falta(db):
    seed_catalog(db, SEED)
    r = seed_catalog(db, SEED)
    assert r == {"created": [], "skipped": ["OpenRouter — GLM 4.6"]}
    assert db.query(cm.CatalogEntry).count() == 1
    otra = {"entries": SEED["entries"] + [{**SEED["entries"][0], "name": "OpenRouter — Qwen",
                                           "real_model": "qwen/qwen3"}]}
    assert seed_catalog(db, otra)["created"] == ["OpenRouter — Qwen"]


def test_nunca_pisa_una_ficha_editada(db):
    seed_catalog(db, SEED)
    e = db.query(cm.CatalogEntry).one()
    s = db.get(cm.ComplianceSheet, e.id)
    s.trains_on_data, s.classification_version = False, "console:2"
    e.status, e.context_window = "inactive", 4096
    db.flush()
    seed_catalog(db, {"entries": [{**SEED["entries"][0], "context_window": 128000,
                                   "sheet": {**SEED["entries"][0]["sheet"], "trains_on_data": True}}]})
    s = db.get(cm.ComplianceSheet, e.id)
    assert s.trains_on_data is False and s.classification_version == "console:2"
    e = db.get(cm.CatalogEntry, e.id)
    assert e.status == "inactive" and e.context_window == 4096


def test_si_la_entrada_existe_sin_ficha_se_le_crea_la_ficha_sin_tocar_el_resto(db):
    e = cm.CatalogEntry(id=uuid.uuid4(), level="installation", name="OpenRouter — GLM 4.6", public_id="x",
                        provider="openrouter", real_model="otro", protocol_family="openai_chat")
    db.add(e)
    db.flush()
    seed_catalog(db, SEED)
    assert db.get(cm.CatalogEntry, e.id).real_model == "otro"
    assert db.get(cm.ComplianceSheet, e.id).inference_jurisdiction == "US"


@pytest.mark.parametrize("bad", [
    {"entries": [{"name": "x", "provider": "marte", "real_model": "m", "protocol_family": "openai_chat"}]},
    {"entries": [{"name": "x", "provider": "openrouter", "real_model": "m", "protocol_family": "telepatia"}]},
    {"entries": [{"provider": "openrouter", "real_model": "m", "protocol_family": "openai_chat"}]},
    {"entries": [{"name": "x", "provider": "openrouter", "real_model": "m", "protocol_family": "openai_chat",
                  "credential": {"api_key": "sk-no-va-aqui"}}]},
])
def test_semilla_invalida_falla_fuerte_y_no_siembra_nada(db, bad):
    with pytest.raises(ValueError):
        seed_catalog(db, bad)
    assert db.query(cm.CatalogEntry).count() == 0


@pytest.mark.skipif(not (ROOT / "deploy/clients/nix/profile/catalog-seed.yaml").exists(),
                    reason="Despliegue nix de Sentinel (deploy/clients/nix/**): no existe en Eleia, que entrega la extension por S9/S11 (T020, test_extension_delivery.sh) y las variantes -ext (T091, test_ext_images.sh). 057 T017")
def test_la_semilla_del_perfil_nix_es_valida_y_no_lleva_secretos(db):
    seed = load_seed_file(ROOT / "deploy/clients/nix/profile/catalog-seed.yaml")
    r = seed_catalog(db, seed)
    assert r["created"] and not r["skipped"]
    openrouter = [e for e in db.query(cm.CatalogEntry) if e.provider == "openrouter"]
    assert openrouter and all(e.is_aggregator for e in openrouter)
    text = (ROOT / "deploy/clients/nix/profile/catalog-seed.yaml").read_text()
    assert "sk-" not in text and "api_key" not in text


def test_no_resucita_una_entrada_archivada(db):
    seed_catalog(db, SEED)
    e = db.query(cm.CatalogEntry).filter_by(name="OpenRouter — GLM 4.6").one()
    e.status = "archived"
    db.flush()
    r = seed_catalog(db, SEED)
    assert r == {"created": [], "skipped": ["OpenRouter — GLM 4.6"]}
    assert db.query(cm.CatalogEntry).filter_by(name="OpenRouter — GLM 4.6").count() == 1
    e2 = db.query(cm.CatalogEntry).filter_by(name="OpenRouter — GLM 4.6").one()
    assert e2.id == e.id and e2.status == "archived"
