"""Contract test de ``GET /api/v1/chat/models/status`` (spec 033, T004).

Fija el contrato del brief cerrado (sección 3.1 y 5): las 4 claves de ``status.json``
—que escribe el supervisor del motor (PR-A #301, ``litellm/supervisor.py``)— se
propagan TAL CUAL, sin maquillar un ``state=error``: el ``last_error`` real es lo que
la UI (T006) necesita para mostrarle al admin qué falló.

Y el caso volumen/archivo ausente o corrupto: **200, nunca 500** — mismo patrón que
``GET /chat/router-config`` (``router_config.py:216-220``). Un supervisor que todavía
no escribió su primer ``status.json`` (o un PR-B que llega a un entorno antes que
PR-A) no puede dejar al admin sin la única pantalla desde la que podría enterarse.
"""
import json
import sys
from pathlib import Path

import pytest

# Los harness de DB viven en ``tests/`` y ``tests/integration/`` (pytest solo agrega al
# path el directorio del módulo que colecta, así que desde ``tests/contract/`` no se ven).
_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client, headers_for_role, rechazo_por_rol  # noqa: E402

from src.api import chat  # noqa: E402
from src.auth.matrix import Rol  # noqa: E402

require_postgres()

DB = "basa_test_models_status_contract"
URL = "/api/v1/chat/models/status"


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture
def status_path(monkeypatch, tmp_path):
    """Cada test con su propio ``status.json``, AUSENTE al empezar.

    Se parchea el resolutor de path (``_get_engine_status_path``) y no una función de
    más alto nivel, para ejercitar la lectura real del fichero — mismo patrón que
    ``config_temporal`` de ``test_router_config_api.py`` sobre
    ``auto_router_service.get_config_path``.
    """
    destino = tmp_path / "status.json"
    monkeypatch.setattr(chat, "_get_engine_status_path", lambda: str(destino))
    return destino


def _escribir(path, contenido):
    path.write_text(contenido, encoding="utf-8")


def test_estado_idle_expone_las_cuatro_claves(harness, status_path):
    client, factory = harness
    headers = headers_for_role(client, factory, Rol.COMPLIANCE_OFFICER, sufijo="-idle")
    _escribir(status_path, json.dumps({"state": "idle", "ts": 1756134000.0,
                                        "last_error": None, "config_hash": "abc123"}))

    resp = client.get(URL, headers=headers)

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert set(cuerpo) == {"state", "ts", "last_error", "config_hash"}
    assert cuerpo == {"state": "idle", "ts": 1756134000.0, "last_error": None,
                      "config_hash": "abc123"}


def test_estado_error_propaga_el_last_error_tal_cual(harness, status_path):
    client, factory = harness
    headers = headers_for_role(client, factory, Rol.COMPLIANCE_OFFICER, sufijo="-error")
    _escribir(status_path, json.dumps({"state": "error", "ts": 1756134500.0,
                                        "last_error": "YAML inválido: line 3",
                                        "config_hash": None}))

    resp = client.get(URL, headers=headers)

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["state"] == "error"
    assert cuerpo["last_error"] == "YAML inválido: line 3"
    assert cuerpo["config_hash"] is None


def test_archivo_ausente_responde_honesto_no_500(harness, status_path):
    """``status_path`` crea el PATH pero no el fichero: el volumen todavía no montado
    (o el supervisor sin arrancar) es el caso explícito de la spec (tasks.md:54-55) —
    nunca puede ser un 500."""
    client, factory = harness
    headers = headers_for_role(client, factory, Rol.COMPLIANCE_OFFICER, sufijo="-ausente")
    assert not status_path.exists()

    resp = client.get(URL, headers=headers)

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["state"] == "unknown"
    assert cuerpo["last_error"]
    assert cuerpo["ts"] is None
    assert cuerpo["config_hash"] is None


def test_json_corrupto_no_es_500(harness, status_path):
    client, factory = harness
    headers = headers_for_role(client, factory, Rol.COMPLIANCE_OFFICER, sufijo="-corrupto")
    _escribir(status_path, "{esto no es json")

    resp = client.get(URL, headers=headers)

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["state"] == "unknown"
    assert cuerpo["last_error"]


def test_rbac_compliance_officer_lee_client_no(harness, status_path):
    client, factory = harness
    _escribir(status_path, json.dumps({"state": "idle", "ts": 1.0, "last_error": None,
                                        "config_hash": "x"}))

    co = headers_for_role(client, factory, Rol.COMPLIANCE_OFFICER, sufijo="-rbac")
    sin_permiso = headers_for_role(client, factory, Rol.CLIENT, sufijo="-rbac")

    assert client.get(URL, headers=co).status_code == 200

    resp_denegado = client.get(URL, headers=sin_permiso)
    assert resp_denegado.status_code == 403
    assert rechazo_por_rol(Rol.CLIENT) in resp_denegado.text
