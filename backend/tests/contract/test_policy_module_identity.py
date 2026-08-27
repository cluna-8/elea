"""La librería compartida `basa_guardian_policy` tiene que ser UN solo objeto-módulo.

Por qué existe este archivo (038 T008): la matriz D2 se muda a la librería PURA compartida
para que el backend y el motor evalúen **el mismo objeto** en vez de dos copias «igualitas»
—lo que `specs/038/tasks.md` declara NO_APTO—. Esa mudanza sólo vale si el módulo es de
verdad uno, y hoy no lo es.

El mismo archivo se importa por DOS caminos y produce DOS entradas de `sys.modules` con
globals independientes:

  * `import basa_guardian_policy`            (nombre PLANO) — lo que hace PRODUCCIÓN:
    `gateway.py`, `presidio_service.py`, `basa_guardrail.py`, `basa_audit_logger.py`.
  * `from extensions import basa_guardian_policy` (nombre PAQUETE) — lo que hacen los TESTS
    de policy y `litellm/extensions/contract_checks.py`, que es un check de RELEASE.

Los dos invariantes de abajo NO son intercambiables y por eso van los dos:

  * `__file__` idéntico  ⇒ no pueden divergir en LÓGICA (es el mismo fuente).
  * `is`                 ⇒ no pueden divergir en ESTADO (globals compartidos).

El segundo es el que hoy falla, y el que la red de auto-registro al pie de
`basa_guardian_policy.py` viene a poner en verde — el mismo patrón que ya usa
`basa_governance.py` (bloque de identidad del módulo, al final del archivo).

Ojo con el autouse `_reset_presidio_http_client_singleton` de `conftest.py`: existe porque
`_http_client` vive DUPLICADO en las dos copias. NO se simplifica junto con esta red: sigue
cubriendo a los demás módulos compartidos, que no la tienen.
"""
import importlib
import sys

import pytest

# Los dos caminos, explícitos: este archivo mide la partición, así que tiene que ejercitarla
# —no alcanza con importar por uno solo y confiar en que el otro ya esté cargado por otro
# test, que dependería del orden de colecta.
#
# El camino PAQUETE es directo: `conftest.py` pone la carpeta CONTENEDORA en `sys.path`.
# El camino PLANO **no se puede importar acá a secas**: `conftest.py` NO agrega la carpeta
# `extensions` misma, así que `import basa_guardian_policy` explota con ModuleNotFoundError
# si nadie lo cargó antes. Medido: el nombre plano existe ÚNICAMENTE como efecto de que un
# módulo de producción (que se agrega su propio directorio a `sys.path`) se haya importado
# primero. Por eso la referencia plana se toma de donde PRODUCCIÓN la crea —igual que
# `test_nlp_fail_mode.py` toma `policy = basa_guardrail.policy`— y no con un import propio
# que mediría una tercera cosa.
from extensions import basa_guardian_policy as via_paquete  # noqa: E402  (camino de TESTS)

_gateway = importlib.import_module("src.api.gateway")  # hace el baile de sys.path y el import plano
via_plano = sys.modules["basa_guardian_policy"]  # noqa: E402  (camino de PRODUCCIÓN)


def test_las_dos_entradas_de_sys_modules_existen():
    """Control del INSTRUMENTO: si un solo camino estuviera cargado, los asserts de abajo
    medirían la copia contra sí misma y pasarían sin probar nada."""
    assert sys.modules.get("basa_guardian_policy") is via_plano
    assert sys.modules.get("extensions.basa_guardian_policy") is via_paquete


def test_mismo_archivo_fuente_no_pueden_divergir_en_logica():
    """`__file__` idéntico: sea cual sea el camino, la lógica es la del mismo archivo."""
    assert via_plano.__file__ == via_paquete.__file__


def test_un_solo_objeto_modulo_no_pueden_divergir_en_estado():
    """`is`: un solo objeto ⇒ un solo juego de globals.

    Sin esto, el estado módulo-level se parte por copia en silencio (el `_http_client` de
    `presidio_analyze` ya obligó a un autouse global en `conftest.py` por exactamente esto),
    y un `monkeypatch` de un test toca una copia que producción no ejecuta.
    """
    assert via_plano is via_paquete


def test_canario_de_estado_lo_escrito_en_una_copia_se_lee_en_la_otra():
    """El `is` de arriba dicho en la forma que se puede ver fallar.

    Un assert de identidad se lee como plomería; este canario muestra la CONSECUENCIA:
    un atributo escrito por un camino es invisible desde el otro.
    """
    marca = "_canario_identidad_038t008"
    assert not hasattr(via_plano, marca), "residuo de una corrida previa"
    try:
        setattr(via_plano, marca, "escrito-por-el-camino-plano")
        assert getattr(via_paquete, marca, None) == "escrito-por-el-camino-plano"
    finally:
        for _mod in (via_plano, via_paquete):
            if hasattr(_mod, marca):
                delattr(_mod, marca)


@pytest.mark.parametrize("nombre_modulo, atributo", [
    ("src.api.gateway", "policy"),
    ("extensions.basa_guardrail", "policy"),
    ("extensions.basa_audit_logger", "policy"),
])
def test_los_call_sites_de_produccion_ven_el_objeto_unico(nombre_modulo, atributo):
    """Los planos reales, no una referencia que este test se importa para sí mismo.

    Es la mitad que faltaba en la primera versión de este invariante: los cuatro consumidores
    de producción ya importan por el nombre PLANO, así que compararlos ENTRE ELLOS pasa hoy
    sin la red puesta. Lo que hay que probar es que el objeto que ellos ejecutan es el mismo
    que este test pinea — o sea, cruzando la partición.
    """
    modulo = importlib.import_module(nombre_modulo)
    assert getattr(modulo, atributo) is via_paquete
