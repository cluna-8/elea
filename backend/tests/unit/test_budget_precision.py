"""Precisión del contador de gasto, sin base de por medio (issue #76).

Estos tests son el hermano rápido de `test_migration_014.py`: allá se prueba que **la
columna** ya no redondea (hace falta Postgres de verdad, el redondeo lo hace la base); acá
se prueba que **el servicio** no vuelve a introducir el truncado por su cuenta —una
cuantización a 4 decimales en el camino haría inútil la migración—.

El caso que hay que tener siempre a la vista: una llamada corta a `gpt-4o-mini` cuesta
~$0.000012. Todo lo que redondee por encima de 1e-5 convierte el contador de presupuesto en
un cero permanente, que es como llegó al ensayo del piloto.
"""
from decimal import Decimal

import pytest

from src.services.budget_service import BudgetService, cuantizar_usd


class _BudgetFalso:
    """Presupuesto en memoria: acá se mide la aritmética, no el ORM."""
    def __init__(self, max_spend="10", spend="0", max_tokens=1_000_000, tokens=0):
        self.max_spend_usd = Decimal(max_spend)
        self.current_spend_usd = Decimal(spend)
        self.max_tokens = max_tokens
        self.current_tokens = tokens


class _SesionFalsa:
    def commit(self):
        self.commiteado = True


@pytest.fixture
def cargar(monkeypatch):
    """Devuelve un cargador que fuerza `update_budget` sobre un presupuesto dado."""
    def _cargar(presupuesto, veces=1, **kwargs):
        monkeypatch.setattr(BudgetService, "get_applicable_budgets",
                            staticmethod(lambda *a, **k: [presupuesto]))
        for _ in range(veces):
            BudgetService.update_budget(_SesionFalsa(), user_id="u", **kwargs)
        return presupuesto
    return _cargar


# ── Cuantización ───────────────────────────────────────────────────────────────────────

def test_la_escala_es_la_de_la_columna():
    assert cuantizar_usd(Decimal("0.000012345678901")).as_tuple().exponent == -8


def test_no_pierde_el_pedido_barato():
    """1.2e-5 es el orden de magnitud de un pedido REAL: tiene que sobrevivir entero."""
    assert cuantizar_usd(Decimal("0.000012")) == Decimal("0.00001200")


def test_redondea_half_up_y_no_half_even():
    """`decimal` redondea a par por defecto: para dinero mostrado en un panel, la mitad
    sube. Sin fijarlo, dos importes idénticos podrían redondear distinto según el dígito
    anterior."""
    assert cuantizar_usd(Decimal("0.000000005")) == Decimal("0.00000001")
    assert cuantizar_usd(Decimal("0.000000015")) == Decimal("0.00000002")


def test_acepta_float_del_plano_interno():
    """El coste del motor llega como float por JSON (`override_cost` viene de ahí)."""
    assert cuantizar_usd(0.00001) == Decimal("0.00001000")


# ── Tarifario ──────────────────────────────────────────────────────────────────────────

def test_calculate_cost_conserva_los_decimales_finos():
    # 100 tokens in + 50 out de gpt-4o-mini = 100/1e6*0.15 + 50/1e6*0.60 = 0.000045
    assert BudgetService.calculate_cost("gpt-4o-mini", 100, 50) == Decimal("0.00004500")


def test_calculate_cost_de_modelo_local_sigue_valiendo_cero():
    """El modelo local corre en el hardware del cliente: la cuantización no puede
    inventarle un coste (el panel de costes del piloto se apoya en esto)."""
    assert BudgetService.calculate_cost("camara-comercio-local", 5000, 5000) == Decimal("0")


# ── Acumulación ────────────────────────────────────────────────────────────────────────

def test_dos_pedidos_baratos_suman_y_no_se_pierden(cargar):
    """El anclaje de #76 en versión aritmética: 0.00001 + 0.00001 = 0.00002, jamás 0."""
    presupuesto = cargar(_BudgetFalso(), veces=2, override_cost=Decimal("0.00001"),
                         prompt_tokens=10, completion_tokens=5)

    assert presupuesto.current_spend_usd == Decimal("0.00002")
    assert presupuesto.current_tokens == 30


def test_muchos_pedidos_baratos_terminan_agotando_el_presupuesto(cargar):
    """La razón de ser del fix: con el contador congelado en 0 el tope NUNCA se alcanzaba y
    el 402 del motor no se disparaba jamás."""
    presupuesto = cargar(_BudgetFalso(max_spend="0.0001"), veces=10,
                         override_cost=Decimal("0.00001"))

    assert presupuesto.current_spend_usd == Decimal("0.0001")
    assert not BudgetService._budget_has_credit(presupuesto), "el tope no llegó a agotarse"


def test_el_coste_del_motor_no_se_recalcula_con_el_tarifario_local(cargar):
    """`override_cost` es el coste que el motor midió contra la respuesta real del
    proveedor. Si acá se recalculara, la fila de auditoría y el presupuesto contarían
    historias distintas para el mismo pedido."""
    presupuesto = cargar(_BudgetFalso(), override_cost=Decimal("0.12345678"),
                         model="gpt-4o", prompt_tokens=999, completion_tokens=999)

    assert presupuesto.current_spend_usd == Decimal("0.12345678")


def test_sin_presupuesto_aplicable_no_explota(monkeypatch):
    """Instalación sin presupuestos configurados: el camino de carga se llama igual en cada
    pedido y no puede fallar."""
    monkeypatch.setattr(BudgetService, "get_applicable_budgets", staticmethod(lambda *a, **k: []))
    BudgetService.update_budget(_SesionFalsa(), user_id="u", override_cost=Decimal("1"))
