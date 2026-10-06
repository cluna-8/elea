"""Migración de destinos de la 068 al catálogo y no-regresión (069 T019; FR-039, FR-040, FR-041).

Sin Postgres: SQLite en memoria con las dos metadatas (la RLS la cubren los tests de migración).
Corre con el venv del backend.
"""
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from sentinel.catalog import models as cm  # noqa: E402
from sentinel.catalog.migrate import credential_id_for, migrate_all, mirror_destination  # noqa: E402
from sentinel.redirect import models as rm  # noqa: E402
from sentinel.redirect.store import decrypt_credential, load_from_session  # noqa: E402

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
BLOB = "gAAAA-cifrado-opaco"          # lo que guardó `encryption_service`: la migración no lo descifra


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    rm.RedirectBase.metadata.create_all(engine)
    cm.CatalogBase.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _dest(db, **kw):
    base = dict(id=uuid.uuid4(), level="tenant", tenant_id=T1, name="Qwen UE", provider="openai_compatible",
                real_model="qwen", protocol_family="openai_chat", inference_jurisdiction="DE",
                entity_jurisdiction="DE", api_base="http://qwen/v1", credential_encrypted=BLOB,
                provider_options={}, capability_profile={"thinking": False, "images": True},
                context_window=128000, max_output=8192, status="active")
    base.update(kw)
    d = rm.RedirectDestination(**base)
    db.add(d)
    db.flush()
    return d


def _policy(db, tenant=T1):
    db.add(rm.RedirectPolicy(tenant_id=tenant, scope_type="tenant", scope_value="*", state="on"))
    db.flush()


# ── migración ────────────────────────────────────────────────────────────────────

def test_cada_destino_pasa_a_entrada_con_el_mismo_id_y_sin_clasificar(db):
    d = _dest(db)
    assert migrate_all(db) == 1
    e = db.get(cm.CatalogEntry, d.id)
    assert (e.name, e.provider, e.real_model, e.level, e.tenant_id) == (d.name, d.provider, d.real_model, "tenant", T1)
    assert e.source == "migrated_068" and e.status == "active"
    sheet = db.get(cm.ComplianceSheet, d.id)
    assert sheet.classification_version == "migrated_068" and sheet.inference_jurisdiction == "DE"
    # registros, entrenamiento y transferencia sin cargar ⇒ el semáforo nace «sin clasificar» (FR-039/041)
    from datetime import date

    from sentinel.catalog.store import semaforo_of
    assert semaforo_of(e, sheet, None, date(2026, 10, 1))["estado"] == "unclassified"


def test_el_id_publico_se_deriva_del_nombre_y_no_choca(db):
    a = _dest(db, name="Qwen UE")
    b = _dest(db, name="Qwen  UE!", real_model="otro")
    migrate_all(db)
    ids = {db.get(cm.CatalogEntry, x.id).public_id for x in (a, b)}
    assert ids == {"qwen-ue", "qwen-ue-2"}


def test_la_credencial_se_copia_cifrada_sin_descifrar(db):
    d = _dest(db)
    migrate_all(db)
    c = db.get(cm.Credential, credential_id_for(d.id))
    assert c.ciphertext == BLOB and c.kind == "secret" and c.status == "active" and c.tenant_id == T1
    assert db.get(cm.CatalogEntry, d.id).credential_id == c.id


def test_es_idempotente(db):
    d = _dest(db)
    migrate_all(db)
    migrate_all(db)
    assert db.query(cm.CatalogEntry).count() == 1 and db.query(cm.Credential).count() == 1
    assert db.query(cm.ComplianceSheet).count() == 1


def test_no_pisa_una_ficha_editada_en_la_consola(db):
    d = _dest(db)
    migrate_all(db)
    sheet = db.get(cm.ComplianceSheet, d.id)
    sheet.inference_jurisdiction, sheet.classification_version = "FR", "console:3"
    db.flush()
    d.inference_jurisdiction = "US"          # alguien edita luego por la API vieja
    mirror_destination(db, d)
    assert db.get(cm.ComplianceSheet, d.id).inference_jurisdiction == "FR"


def test_revocar_en_la_068_archiva_la_entrada_y_destruye_el_secreto(db):
    d = _dest(db)
    migrate_all(db)
    d.status, d.credential_encrypted = "revoked", None
    mirror_destination(db, d)
    e = db.get(cm.CatalogEntry, d.id)
    assert e.status == "archived" and e.credential_id is None
    c = db.get(cm.Credential, credential_id_for(d.id))
    assert c.status == "revoked" and c.ciphertext is None


def test_destino_de_instalacion_y_sus_ofertas(db):
    d = _dest(db, level="installation", tenant_id=None, name="Nativo", provider="anthropic",
              protocol_family="anthropic_messages", credential_encrypted=BLOB, api_base=None)
    db.add(rm.RedirectOffer(id=uuid.uuid4(), destination_id=d.id, tenant_id=T2,
                            enabled_at=datetime(2026, 9, 1, tzinfo=timezone.utc), enable_reason="ok"))
    db.add(rm.RedirectOffer(id=uuid.uuid4(), destination_id=d.id, tenant_id=None))
    db.flush()
    migrate_all(db)
    offers = {o.tenant_id: o for o in db.query(cm.CatalogOffer)}
    assert set(offers) == {T2, None} and offers[T2].enable_reason == "ok"
    d_offer = db.query(rm.RedirectOffer).filter(rm.RedirectOffer.tenant_id == T2).one()
    db.delete(d_offer)
    db.flush()
    migrate_all(db)
    assert {o.tenant_id for o in db.query(cm.CatalogOffer)} == {None}


def test_precio_por_millon_se_guarda_por_token_y_vuelve_igual(db):
    _policy(db)
    d = _dest(db, price_override={"input_per_mtok": 0.27, "output_per_mtok": 1.1})
    migrate_all(db)
    e = db.get(cm.CatalogEntry, d.id)
    assert float(e.price_input) == pytest.approx(0.27e-6) and float(e.price_output) == pytest.approx(1.1e-6)
    snap = load_from_session(db, str(T1))
    assert snap.destinations[str(d.id)]["price_override"] == {"input_per_mtok": 0.27, "output_per_mtok": 1.1}


# ── no-regresión (FR-039, SC-009) ─────────────────────────────────────────────────

def _snapshot_dump(snap):
    # `public_id` (069 US2), `unsupported_params` (enmienda 2-oct), `role` (E3) y `control_jurisdiction` (057 D12) son
    # datos nuevos que solo traen los destinos del catálogo: no son parte de lo que la migración debe preservar de la 068.
    nuevos = ("public_id", "unsupported_params", "role", "control_jurisdiction")
    dest = {k: {f: v for f, v in d.items() if f not in nuevos} for k, d in snap.destinations.items()}
    return json.dumps({"dest": dest, "offers": sorted(map(json.dumps, snap.offers)),
                       "creds": snap.credentials}, sort_keys=True, default=str)


def _catalogo_sin_migrar(*_a, **_k):
    raise RuntimeError("no such table: ext_catalog_entry")


def test_la_instantanea_es_identica_antes_y_despues_de_migrar(db, monkeypatch):
    """«Antes» = la imagen que todavía no tiene el catálogo (rige la tabla de la 068, respaldo de la E3); con las
    tablas del catálogo pero sin migrar, la fila vieja NO se sirve (el catálogo es la única fuente):
    `test_redirect_plano_de_datos_catalogo.py::test_la_fila_vieja_sin_entrada_no_se_sirve`."""
    _policy(db)
    _dest(db)
    inst = _dest(db, level="installation", tenant_id=None, name="Nativo", provider="anthropic",
                 protocol_family="anthropic_messages", credential_encrypted="gAAAA-otro", api_base=None,
                 capability_profile={})
    db.add(rm.RedirectOffer(id=uuid.uuid4(), destination_id=inst.id, tenant_id=None))
    db.flush()
    with monkeypatch.context() as mp:
        mp.setattr("sentinel.catalog.store.catalog_destinations", _catalogo_sin_migrar)
        antes = _snapshot_dump(load_from_session(db, str(T1)))
    assert json.loads(antes)["dest"]                      # no es una comparación de vacíos
    migrate_all(db)
    despues = _snapshot_dump(load_from_session(db, str(T1)))
    assert despues == antes


def test_sin_las_tablas_del_catalogo_la_068_sigue_sirviendo():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    rm.RedirectBase.metadata.create_all(engine)         # NO crea las ext_*
    s = sessionmaker(bind=engine)()
    _policy(s)
    d = _dest(s)
    snap = load_from_session(s, str(T1))
    assert str(d.id) in snap.destinations and snap.credentials[str(d.id)] == BLOB


def test_destinos_de_otra_organizacion_no_se_filtran(db):
    _policy(db)
    mine = _dest(db)
    _dest(db, tenant_id=T2, name="Ajeno")
    migrate_all(db)
    assert set(load_from_session(db, str(T1)).destinations) == {str(mine.id)}


def test_entrada_nueva_de_la_consola_llega_al_plano_de_datos(db):
    _policy(db)
    e = cm.CatalogEntry(id=uuid.uuid4(), level="tenant", tenant_id=T1, name="OpenRouter GLM",
                        public_id="openrouter-glm", provider="openrouter", real_model="z-ai/glm-4.6", protocol_family="openai_chat",
                        is_aggregator=True, status="active", source="console")
    c = cm.Credential(id=uuid.uuid4(), level="tenant", tenant_id=T1, name="k", kind="secret", ciphertext=BLOB)
    db.add_all([c, e])
    db.flush()
    e.credential_id = c.id
    db.add(cm.ComplianceSheet(entry_id=e.id))
    db.flush()
    snap = load_from_session(db, str(T1))
    assert snap.destinations[str(e.id)]["name"] == "OpenRouter GLM"
    assert snap.destinations[str(e.id)]["inference_jurisdiction"] is None      # desconocida ⇒ fuera de toda allowlist
    assert snap.credentials[str(e.id)] == BLOB


def test_referencia_a_variable_del_servidor_viaja_como_referencia(db):
    _policy(db)
    from sentinel.catalog import credentials as cr
    e = cm.CatalogEntry(id=uuid.uuid4(), level="installation", tenant_id=None, name="OR inst",
                        public_id="or-inst", provider="openrouter", real_model="x", protocol_family="openai_chat", status="active")
    c = cm.Credential(id=uuid.uuid4(), level="installation", name="OR_KEY", kind="env_ref",
                      env_name="REDIRECT_CRED_OR", fingerprint="abcd")
    db.add_all([c, e])
    db.flush()
    e.credential_id = c.id
    db.add_all([cm.ComplianceSheet(entry_id=e.id), cm.CatalogOffer(entry_id=e.id, tenant_id=None)])
    db.flush()
    snap = load_from_session(db, str(T1))
    assert decrypt_credential(snap.credentials[str(e.id)]) == {"api_key": "env:REDIRECT_CRED_OR"}


def test_entrada_archivada_se_ve_revocada_para_el_resolver(db):
    _policy(db)
    d = _dest(db)
    migrate_all(db)
    e = db.get(cm.CatalogEntry, d.id)
    e.status, e.archived_reason = "archived", "obsoleta"
    db.flush()
    assert load_from_session(db, str(T1)).destinations[str(d.id)]["status"] == "revoked"
