"""Arranque con migraciones de extensiones (S4, spec 057 T088, QA B1; research R27).

Sin `ALEMBIC_EXTRA_VERSION_LOCATIONS`, una migración que falla se REGISTRA y el arranque sigue (el
comportamiento de siempre, `src/main.py`). Con la variable —hay ramas de extensión que migrar—, la
falla ABORTA el arranque: servir con el esquema a medias, con la extensión activa, es peor que no
servir. Sin Postgres: `alembic.command.upgrade` se reemplaza por un doble.
"""
import logging

import pytest
from alembic import command

from src import main

ENV = "ALEMBIC_EXTRA_VERSION_LOCATIONS"


@pytest.fixture
def upgrade_roto(monkeypatch):
    llamadas = []

    def _upgrade(cfg, target):
        llamadas.append(target)
        raise RuntimeError("migración de prueba rota")

    monkeypatch.setattr(command, "upgrade", _upgrade)
    monkeypatch.delenv("RUN_ALEMBIC_ON_STARTUP", raising=False)
    return llamadas


def test_sin_la_variable_la_falla_se_registra_y_el_arranque_sigue(upgrade_roto, monkeypatch, caplog):
    monkeypatch.delenv(ENV, raising=False)
    with caplog.at_level(logging.ERROR, logger="sentinel-secure-gateway"):
        main._run_alembic_upgrade_head()                      # no levanta
    assert upgrade_roto == ["head"]
    assert "Alembic auto-run failed" in caplog.text


@pytest.mark.parametrize("valor", ["", "   ", " , "])
def test_una_variable_vacia_es_como_no_tenerla(upgrade_roto, monkeypatch, valor):
    monkeypatch.setenv(ENV, valor)
    main._run_alembic_upgrade_head()                          # no levanta
    assert upgrade_roto == ["head"]


def test_con_la_variable_la_falla_aborta_el_arranque(upgrade_roto, monkeypatch, tmp_path, caplog):
    monkeypatch.setenv(ENV, str(tmp_path))
    with caplog.at_level(logging.ERROR, logger="sentinel-secure-gateway"):
        with pytest.raises(RuntimeError, match="migración de prueba rota"):
            main._run_alembic_upgrade_head()
    assert upgrade_roto == ["heads"]
    assert "Alembic auto-run failed" in caplog.text           # se registra igual, antes de abortar


def test_con_la_variable_un_directorio_inexistente_tambien_aborta(monkeypatch, tmp_path):
    """El directorio extra mal escrito no se ignora: la extensión quedaría sin sus tablas."""
    monkeypatch.setenv(ENV, str(tmp_path / "no-existe"))
    monkeypatch.delenv("RUN_ALEMBIC_ON_STARTUP", raising=False)
    with pytest.raises(Exception, match="no existe"):
        main._run_alembic_upgrade_head()


def test_apagada_por_run_alembic_on_startup_no_hace_nada(upgrade_roto, monkeypatch, tmp_path):
    monkeypatch.setenv(ENV, str(tmp_path))
    monkeypatch.setenv("RUN_ALEMBIC_ON_STARTUP", "false")
    main._run_alembic_upgrade_head()
    assert upgrade_roto == []
