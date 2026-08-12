"""La tabla STATUS de la vitrina conoce los rechazos que el producto SÍ persiste.

`api/monitor.py` sirve una página con un mapa `compliance_status → [familia, etiqueta]`
escrito a mano en JS. El literal que se guarda en la fila vive del otro lado del árbol
(`services/engine_gate.py`, `services/budget_service.py`), así que nada obliga a que los dos
lados coincidan: agregar un rechazo nuevo y olvidarse del mapa no rompe ningún test, no
rompe el render y no se nota en code review — se nota en la sede, donde el chip sale gris con
el literal interno crudo («REJECTED_BUDGET»), que se lee como «no sé por qué» cuando sí
sabemos por qué el pedido no se sirvió.

Por eso este test importa las constantes DEL CÓDIGO DE PRODUCTO y busca esa clave en el mapa:
lo que se protege es que los dos lados no se separen, y un rename en una sola punta lo tiene
que poner rojo. Las ETIQUETAS, en cambio, van literales: son el copy que ve el officer y un
cambio de copy es una decisión, no un refactor.

Es un test de la fuente de la página, no del render: la página es una constante que se arma
al importar el módulo (`_MONITOR_HTML`), así que no hacen falta ni app ni Redis ni browser.
"""
import re

import pytest

from src.api import monitor
from src.services.budget_service import STATUS_BUDGET_EXHAUSTED
from src.services.engine_gate import STATUS_SATURATED


def _entrada_del_mapa(estado: str):
    """`[familia, etiqueta]` de un estado en la tabla STATUS de la página, o `None`."""
    hallado = re.search(
        rf"(?<![\w.]){re.escape(estado)}\s*:\s*\[\s*'([^']*)'\s*,\s*'([^']*)'\s*\]",
        monitor._MONITOR_HTML,
    )
    return hallado.groups() if hallado else None


@pytest.mark.parametrize("estado, etiqueta", [
    (STATUS_SATURATED, "RECHAZADO POR CAPACIDAD"),
    (STATUS_BUDGET_EXHAUSTED, "RECHAZADO POR PRESUPUESTO"),
])
def test_los_rechazos_nuestros_tienen_etiqueta_propia_en_la_vitrina(estado, etiqueta):
    """Los dos rechazos que NO son bloqueos de política (capacidad #135, presupuesto #157).

    La familia es `error` y no `blocked` a propósito: ninguna capa impidió el pedido, así que
    pintarlo como bloqueo le mentiría al officer con un color. Pero tampoco es neutro —el
    pedido no se sirvió—, y `error` es lo que dice eso sin acusar a nadie.
    """
    entrada = _entrada_del_mapa(estado)
    assert entrada is not None, (
        f"`{estado}` se persiste en la fila durable pero no está en la tabla STATUS de "
        f"`api/monitor.py`: el chip saldría gris con el literal interno crudo")
    assert entrada == ("error", etiqueta), entrada
