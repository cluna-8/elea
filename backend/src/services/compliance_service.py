import re
import logging
from typing import Tuple, Dict, Any

logger = logging.getLogger("sentinel-secure-gateway.compliance")

# Prohibited AI practices under EU AI Act (Article 5) — universales (aplican a cualquier sector)
PROHIBITED_KEYWORDS = [
    r"social\s*scoring", r"score\s*social", r"clasificación\s*social",
    r"subliminal\s*manipulation", r"manipulación\s*subliminal",
    r"biometric\s*categorization", r"categorización\s*biométrica"
]

# High-risk AI systems under EU AI Act (Annex III) — framings relevantes para pharma + marketing + gastos.
# Nota: este gate es heurístico (regex), no sustituye la DPIA ni la evaluación de conformidad.
HIGH_RISK_KEYWORDS = [
    # Pharma / regulatorio
    r"farmacovigilancia\s*automatizada", r"farmacovigilancia\s*autónoma",
    r"decisión\s*regulatoria\s*autónoma", r"decision\s*regulatoria\s*autonoma",
    r"ensayo\s*clínico\s*autónomo", r"ensayo\s*clinico\s*autonomo",
    # RRHH / gastos (evaluación automatizada de personas — Annex III)
    r"evaluación\s*de\s*crédito", r"credit\s*scoring",
    r"automated\s*hiring", r"evaluación\s*de\s*cv", r"selección\s*de\s*personal\s*automática",
    r"scoring\s*de\s*empleados", r"evaluación\s*automatizada\s*de\s*representantes",
    r"evaluacion\s*automatizada\s*de\s*representantes",
    # Marketing (personalización manipuladora / subliminal de ads)
    r"personalización\s*manipuladora", r"personalizacion\s*manipuladora",
]

class ComplianceService:
    @staticmethod
    def evaluate_prompt(text: str, ai_act_mode: bool) -> Dict[str, Any]:
        """
        Evaluates a prompt against EU AI Act rules.
        Returns a dictionary with status, risk level, and reason.
        """
        if not ai_act_mode or not text:
            return {"status": "passed", "risk_level": "low", "reason": None}

        # Check prohibited practices first (critical)
        for pattern in PROHIBITED_KEYWORDS:
            if re.search(pattern, text, re.IGNORECASE):
                logger.warning(f"AI Act Violation: Prohibited practice detected matching '{pattern}'")
                return {
                    "status": "blocked_prohibited",
                    "risk_level": "prohibited",
                    "reason": f"Petición bloqueada por la Ley de IA (AI Act): Práctica prohibida detectada ({pattern})."
                }

        # Check high-risk categories
        for pattern in HIGH_RISK_KEYWORDS:
            if re.search(pattern, text, re.IGNORECASE):
                logger.warning(f"AI Act Warning: High-risk application detected matching '{pattern}'")
                return {
                    "status": "flagged_high_risk",
                    "risk_level": "high",
                    "reason": f"Advertencia de la Ley de IA: Aplicación de alto riesgo detectada ({pattern}). Se requiere supervisión humana."
                }

        return {"status": "passed", "risk_level": "low", "reason": None}
