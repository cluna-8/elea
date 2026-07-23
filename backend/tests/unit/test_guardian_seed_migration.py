"""Migración-on-read del guardián PII (`get_or_create_default_guardians`).

Regresión del hallazgo de review del PR #21: el método corre en CADA
`GET /api/v1/guardians`, así que cualquier reescritura incondicional de `config`
revierte lo que el administrador acaba de guardar — la UI "se desconfiguraba
sola". La regla que estos tests fijan: se corrige el valor que dejó una versión
anterior del seed, y NADA más.

DB stub mínimo (sin Postgres): el método solo necesita query/filter/commit, y con
9 guardianes ya presentes nunca entra al camino de re-seed.
"""
import pytest

from src.models.guardian import Guardian
from src.services.guardian_service import GuardianService

LEGACY_AR = ["PERSON", "DNI", "CUIL", "EMAIL_ADDRESS", "PHONE_NUMBER"]
EU = ["PERSON", "ES_NIF", "ES_NIE", "PASSPORT", "EMAIL_ADDRESS",
      "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD"]


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def filter(self, *_args, **_kwargs):
        # El único filtro del método es guardian_type == "pii_masking".
        return _FakeQuery([g for g in self._rows if g.guardian_type == "pii_masking"])

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.commits = 0

    def query(self, _model):
        return _FakeQuery(self._rows)

    def commit(self):
        self.commits += 1


def _db(pii_config):
    """Sesión con el guardián PII + relleno hasta 9 (evita el camino de re-seed)."""
    pii = Guardian(name="PII", guardian_type="pii_masking", is_active=True, config=pii_config)
    filler = [Guardian(name=f"g{i}", guardian_type=f"other_{i}", is_active=True, config={})
              for i in range(8)]
    return _FakeSession([pii] + filler), pii


# ── entities: se migra SOLO desde el default argentino viejo ───────────────────

def test_migra_el_default_argentino_viejo_a_eu():
    db, pii = _db({"entities": list(LEGACY_AR), "custom_names": []})
    GuardianService.get_or_create_default_guardians(db)
    assert set(pii.config["entities"]) == set(EU)


def test_siembra_entities_cuando_la_clave_nunca_existio():
    db, pii = _db({"custom_names": []})
    GuardianService.get_or_create_default_guardians(db)
    assert set(pii.config["entities"]) == set(EU)


@pytest.mark.parametrize("elegido", [
    ["PERSON"],                                  # el admin recortó la lista
    ["PERSON", "EMAIL_ADDRESS", "IBAN_CODE"],    # subconjunto propio del cliente
    ["PERSON", "ES_NIF", "CUSTOM_HC"],           # incluye una entidad custom suya
    [],                                          # apagó todo a propósito
])
def test_no_pisa_la_eleccion_del_administrador(elegido):
    db, pii = _db({"entities": list(elegido), "custom_names": []})
    GuardianService.get_or_create_default_guardians(db)
    assert pii.config["entities"] == elegido
    assert db.commits == 0, "no debería escribir nada si no hay nada que migrar"


def test_es_idempotente_entre_lecturas():
    """El caso real del bug: dos GET seguidos con una edición en el medio."""
    db, pii = _db({"entities": list(LEGACY_AR), "custom_names": []})
    GuardianService.get_or_create_default_guardians(db)   # 1er GET: migra
    pii.config = {**pii.config, "entities": ["PERSON"]}   # el admin edita y guarda
    GuardianService.get_or_create_default_guardians(db)   # 2do GET: NO debe revertir
    assert pii.config["entities"] == ["PERSON"]


# ── custom_names: se siembra una vez, no se resucita ──────────────────────────

def test_siembra_nombres_del_piloto_solo_si_la_clave_nunca_existio():
    db, pii = _db({"entities": list(EU)})
    GuardianService.get_or_create_default_guardians(db)
    assert pii.config["custom_names"] == ["Pedro", "Cristian"]


def test_respeta_que_el_admin_haya_borrado_los_nombres():
    db, pii = _db({"entities": list(EU), "custom_names": []})
    GuardianService.get_or_create_default_guardians(db)
    assert pii.config["custom_names"] == []
    assert db.commits == 0
