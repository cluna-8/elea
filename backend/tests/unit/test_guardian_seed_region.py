"""Seed fresco de guardianes (`get_or_create_default_guardians`, camino < 9 filas):
`region` deriva del default DE LA INSTALACIÓN, no hardcodea `"eu"` (H3 del gate de #137).

El criterio «igual que `nlp_fail_mode`» NO transfería tal cual: `nlp_fail_mode` siembra
una CONSTANTE porque no hay env equivalente (sembrarla es no-op, cualquier instalación
la quiere igual). `region` sí tiene un default de instalación (`BASA_ENTITY_REGION`), así
que sembrar el literal `"eu"` a ciegas ANULABA ese default en la primera pantalla que un
admin de una instalación no-EU abriera: `GET /guardians` re-seedea y desde ahí la env deja
de tener efecto. Estos tests fijan que el seed lee la env EN EL MOMENTO de sembrar.

DB stub mínimo (sin Postgres): sólo lo que usa el camino de re-seed completo (`query().all()`
vacío, `query().filter().first()` None —sin fila que migrar—, `delete()`, `add_all()`,
`commit()`)."""
import pytest

from src.models.guardian import Guardian
from src.services.guardian_service import GuardianService


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def filter(self, *_args, **_kwargs):
        return _FakeQuery([])  # tabla vacía: nada que migrar

    def first(self):
        return None

    def delete(self):
        n = len(self._rows)
        self._rows.clear()
        return n


class _FakeSession:
    def __init__(self):
        self._rows = []
        self.commits = 0
        self.added = []

    def query(self, _model):
        return _FakeQuery(self._rows)

    def commit(self):
        self.commits += 1

    def add_all(self, items):
        self.added.extend(items)
        self._rows.extend(items)


def _pii_guardian(db) -> Guardian:
    return next(g for g in db.added if g.guardian_type == "pii_masking")


def test_instalacion_latam_siembra_region_latam_no_eu(monkeypatch):
    """El bug exacto de H3: una instalación `latam_ar` fresca no puede nacer con `"eu"`
    cableado — eso apaga DNI/CUIL desde el primer GET, sin que nadie tocara nada."""
    monkeypatch.setenv("BASA_ENTITY_REGION", "latam_ar")
    db = _FakeSession()

    GuardianService.get_or_create_default_guardians(db)

    assert _pii_guardian(db).config["region"] == "latam_ar"


def test_instalacion_sin_env_siembra_el_default_del_codigo(monkeypatch):
    """Retrocompatibilidad: sin `BASA_ENTITY_REGION` seteada (instalación vieja o
    perfil que no la declara), el seed sigue naciendo en `eu` — el `DEFAULT_REGION`
    del código, no un literal desconectado de él."""
    monkeypatch.delenv("BASA_ENTITY_REGION", raising=False)
    db = _FakeSession()

    GuardianService.get_or_create_default_guardians(db)

    from src.services.guardian_service import policy
    assert _pii_guardian(db).config["region"] == policy.DEFAULT_REGION == "eu"


def test_instalacion_eu_explicita_tambien_se_respeta(monkeypatch):
    monkeypatch.setenv("BASA_ENTITY_REGION", "eu")
    db = _FakeSession()

    GuardianService.get_or_create_default_guardians(db)

    assert _pii_guardian(db).config["region"] == "eu"
