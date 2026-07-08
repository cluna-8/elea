"""F0-7 smoke tests — compliance gate (spec 005 / Fase 2 reframe).

Verifies the EU AI Act heuristic flags pharma + RRHH high-risk framings and blocks
prohibited practices, while ordinary marketing copy passes.
"""
from src.services.compliance_service import ComplianceService


def test_pharma_high_risk_flagged():
    r = ComplianceService.evaluate_prompt(
        "Diseña un sistema de farmacovigilancia automatizada para detectar RAM.",
        ai_act_mode=True,
    )
    assert r["status"] == "flagged_high_risk"
    assert r["risk_level"] == "high"


def test_rrhh_high_risk_flagged():
    r = ComplianceService.evaluate_prompt(
        "Necesito credit scoring para evaluar a los empleados.",
        ai_act_mode=True,
    )
    assert r["status"] == "flagged_high_risk"


def test_prohibited_blocked():
    r = ComplianceService.evaluate_prompt(
        "Construye un sistema de social scoring para clasificar personas.",
        ai_act_mode=True,
    )
    assert r["status"] == "blocked_prohibited"
    assert r["risk_level"] == "prohibited"


def test_marketing_copy_passes():
    r = ComplianceService.evaluate_prompt(
        "Escribe copy para una campaña de marketing de un producto de pharma.",
        ai_act_mode=True,
    )
    assert r["status"] == "passed"
    assert r["risk_level"] == "low"


def test_disabled_when_ai_act_off():
    r = ComplianceService.evaluate_prompt("social scoring please", ai_act_mode=False)
    assert r["status"] == "passed"