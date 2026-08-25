"""Integration test de ``POST /api/v1/chat/models/apply`` (spec 033, T005).

Fija el contrato del brief cerrado (sección 3.2 y 5): el único efecto de este endpoint
es re-escribir el sentinel ``apply.trigger`` — el disparador que mira el supervisor del
motor es el ``mtime`` del fichero, no su contenido (``Supervisor._stamps()`` de
``litellm/supervisor.py``), así que re-postear tiene que volver a dispararlo.

Y el gate de rol corre por **dependency** del decorador, nunca inline (regla #251): un
cuerpo que no parsea contra el schema para un rol SIN permiso tiene que dar 403, no el
422 que daría si el chequeo de rol corriera DESPUÉS de que Pydantic valide el body.
"""
import sys
import time
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client, headers_for_role, rechazo_por_rol  # noqa: E402

from src.api import chat  # noqa: E402
from src.auth.matrix import Rol  # noqa: E402

require_postgres()

DB = "basa_test_models_apply_api"
URL = "/api/v1/chat/models/apply"

# Cuerpo NO-objeto: contra un schema Pydantic (``ModelsApplyRequest``) esto SIEMPRE es
# 422 si el request llega a validarse — es el "cuerpo inválido" del brief, sección 5.
_CUERPO_INVALIDO = b'"no-es-un-objeto"'
_HEADERS_JSON = {"content-type": "application/json"}


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture
def sentinel_path(monkeypatch, tmp_path):
    """Cada test con su propio directorio: se parchea el resolutor de path
    (``_get_engine_sentinel_path``), no ``escribir_atomico``, para ejercitar la
    escritura atómica real contra disco — mismo patrón que ``config_temporal`` de
    ``test_router_config_api.py``."""
    destino = tmp_path / "apply.trigger"
    monkeypatch.setattr(chat, "_get_engine_sentinel_path", lambda: str(destino))
    return destino


def test_el_post_escribe_el_sentinel(harness, sentinel_path):
    """Testigo positivo: el sentinel EXISTE tras el POST, no sólo "no falló"."""
    client, factory = harness
    headers = headers_for_role(client, factory, Rol.TENANT_ADMIN, sufijo="-alta")
    assert not sentinel_path.exists()

    resp = client.post(URL, headers=headers, json={})

    assert resp.status_code == 200, resp.text
    assert sentinel_path.exists()


def test_re_post_cambia_el_mtime(harness, sentinel_path):
    """El disparador del supervisor es el mtime (no el contenido): un segundo POST
    tiene que volver a moverlo, o el botón "Aplicar" del panel no dispararía nada la
    segunda vez que un admin lo aprieta."""
    client, factory = harness
    headers = headers_for_role(client, factory, Rol.TENANT_ADMIN, sufijo="-mtime")

    assert client.post(URL, headers=headers, json={}).status_code == 200
    primer_mtime = sentinel_path.stat().st_mtime_ns

    time.sleep(0.01)
    assert client.post(URL, headers=headers, json={}).status_code == 200
    segundo_mtime = sentinel_path.stat().st_mtime_ns

    assert segundo_mtime > primer_mtime


def test_rbac_cuerpo_invalido_da_403_antes_que_422(harness, sentinel_path):
    client, factory = harness
    permitido = headers_for_role(client, factory, Rol.TENANT_ADMIN, sufijo="-cuerpo")
    denegado = headers_for_role(client, factory, Rol.COMPLIANCE_OFFICER, sufijo="-cuerpo")

    # Control: con permiso, el MISMO cuerpo inválido sí da 422. Si esto no fuera
    # cierto, el test de abajo no probaría nada — el endpoint no estaría validando body.
    resp_permitido = client.post(URL, headers={**permitido, **_HEADERS_JSON},
                                 content=_CUERPO_INVALIDO)
    assert resp_permitido.status_code == 422, resp_permitido.text

    resp_denegado = client.post(URL, headers={**denegado, **_HEADERS_JSON},
                                content=_CUERPO_INVALIDO)
    assert resp_denegado.status_code == 403, resp_denegado.text
    assert rechazo_por_rol(Rol.COMPLIANCE_OFFICER) in resp_denegado.text
    assert not sentinel_path.exists(), "un 403 no puede haber tocado el disco"


def test_rbac_cuerpo_vacio_tambien_da_403(harness, sentinel_path):
    """El body ES opcional (el mecanismo no necesita nada del cliente): un cuerpo
    VACÍO para un rol sin permiso también tiene que dar 403, no colarse como 200."""
    client, factory = harness
    denegado = headers_for_role(client, factory, Rol.CLIENT, sufijo="-vacio")

    resp = client.post(URL, headers=denegado)

    assert resp.status_code == 403, resp.text
    assert rechazo_por_rol(Rol.CLIENT) in resp.text
    assert not sentinel_path.exists()
