"""Registro de proveedores SSO (spec 017 US2, `contracts/proveedor-sso.md`, T014).

Cubre el registro puro (`register`/`get_provider`/`known_types`) y el auto-abastecimiento de
los built-ins (enmienda de Jeff sobre el brief original: `get_provider`/`known_types` cargan
`entra` con un import perezoso INTERNO — ningún consumidor externo necesita
`from src.sso import entra` sólo por el side-effect del registro).

Todo el estado que se toca acá (`registry._REGISTRY`, `registry._BUILTINS_CARGADOS`,
`sys.modules["src.sso.entra"]`) es un singleton de módulo compartido por TODO el proceso de
tests — el fixture de abajo lo snapshotea y lo restaura para no envenenar otros archivos
(`test_sso_entra.py` incluido). Sin fixtures compartidas en `conftest.py` por instrucción del
brief (colisión con trabajo en paralelo): todo vive acá.
"""
import sys

import pytest

import src.sso as _sso_pkg
from src.sso import registry


def _olvidar_entra() -> None:
    """Fuerza el estado "proceso donde `entra` jamás se importó".

    Popear `sys.modules["src.sso.entra"]` NO ALCANZA: el mecanismo de `from . import entra`
    de Python resuelve primero con `hasattr(paquete, "entra")` (`importlib._bootstrap
    ._handle_fromlist`), y esa referencia queda colgada del objeto módulo `src.sso` aunque se
    borre de `sys.modules` — con sólo eso, `from . import entra` devuelve el módulo VIEJO ya
    inicializado sin volver a ejecutar su `registry.register(EntraProvider())`, y el test pasa
    o falla por la razón equivocada (lo viví armando este archivo: quedaba en `KeyError` un
    `_cargar_builtins()` perfectamente correcto). Hay que borrar TAMBIÉN el atributo del
    paquete para que el import se re-ejecute de verdad."""
    sys.modules.pop("src.sso.entra", None)
    if hasattr(_sso_pkg, "entra"):
        delattr(_sso_pkg, "entra")


@pytest.fixture(autouse=True)
def _snapshot_registro():
    """Restaura `_REGISTRY`, `_BUILTINS_CARGADOS`, `sys.modules["src.sso.entra"]` y el
    atributo `entra` del paquete `src.sso`, tal cual estaban antes del test. Necesario porque
    varios tests de este archivo fuerzan `_olvidar_entra()` para poder medir el import
    perezoso — sin restaurar, el siguiente test (o `test_sso_entra.py`, si corre después en la
    misma sesión) heredaría un registro vacío o un módulo recién re-ejecutado."""
    registro_previo = dict(registry._REGISTRY)
    builtins_previo = registry._BUILTINS_CARGADOS
    modulo_entra_previo = sys.modules.get("src.sso.entra")

    yield

    registry._REGISTRY.clear()
    registry._REGISTRY.update(registro_previo)
    registry._BUILTINS_CARGADOS = builtins_previo
    if modulo_entra_previo is not None:
        sys.modules["src.sso.entra"] = modulo_entra_previo
        _sso_pkg.entra = modulo_entra_previo
    else:
        sys.modules.pop("src.sso.entra", None)
        if hasattr(_sso_pkg, "entra"):
            delattr(_sso_pkg, "entra")


class _ProveedorDeJuguete:
    """Doble mínimo del Protocol — sólo necesita `provider_type` para el registro."""

    def __init__(self, provider_type: str):
        self.provider_type = provider_type

    def authorize_url(self, config, state, *, nonce, redirect_uri):
        raise NotImplementedError

    def exchange_code(self, config, code, *, nonce, redirect_uri):
        raise NotImplementedError


def test_register_y_get_provider_hacen_roundtrip():
    doble = _ProveedorDeJuguete("juguete")
    registry.register(doble)
    assert registry.get_provider("juguete") is doble


def test_get_provider_tipo_desconocido_levanta_keyerror():
    with pytest.raises(KeyError):
        registry.get_provider("okta")  # nunca dado de alta en esta spec (research D11)


def test_ultima_alta_gana():
    """Dos registros con el MISMO `provider_type`: el segundo pisa al primero — permite que
    un test reemplace un proveedor sin reiniciar el proceso."""
    primero = _ProveedorDeJuguete("juguete-2")
    segundo = _ProveedorDeJuguete("juguete-2")
    registry.register(primero)
    registry.register(segundo)
    assert registry.get_provider("juguete-2") is segundo
    assert registry.get_provider("juguete-2") is not primero


def test_known_types_incluye_los_registrados():
    registry.register(_ProveedorDeJuguete("juguete-3"))
    assert "juguete-3" in registry.known_types()


def test_get_provider_entra_sin_import_explicito_del_modulo_entra():
    """Este archivo NUNCA hace `from src.sso import entra` ni `import src.sso.entra`. Se
    fuerza el estado "proceso donde entra jamás se importó" (se popea de `sys.modules`, se
    resetea el flag de builtins y se borra la entrada `entra` del registro) y se pide el
    proveedor directamente.

    Si se saca la carga perezosa de `get_provider` (la llamada a `_cargar_builtins()`), este
    test rompe con `KeyError` — es la prueba de que el auto-abastecimiento funciona y no de que
    "alguna otra parte de la suite ya lo había importado antes".
    """
    _olvidar_entra()
    registry._BUILTINS_CARGADOS = False
    registry._REGISTRY.pop("entra", None)

    proveedor = registry.get_provider("entra")

    assert proveedor.provider_type == "entra"
    assert "src.sso.entra" in sys.modules, (
        "get_provider() devolvió algo pero no disparó el import perezoso de entra.py")


def test_known_types_carga_entra_sin_import_explicito_del_modulo_entra():
    """Gemelo del anterior para `known_types()`: sin cargar los built-ins primero, mentiría
    que `entra` no existe en un proceso donde todavía nadie llamó `get_provider`."""
    _olvidar_entra()
    registry._BUILTINS_CARGADOS = False
    registry._REGISTRY.pop("entra", None)

    tipos = registry.known_types()

    assert "entra" in tipos


def test_get_provider_okta_sigue_desconocido_incluso_tras_cargar_builtins():
    """Cargar los built-ins no inventa proveedores que nadie registró — `okta` sigue
    levantando `KeyError` aunque `entra` ya esté cargado."""
    registry.get_provider("entra")  # fuerza la carga de builtins
    with pytest.raises(KeyError):
        registry.get_provider("okta")
