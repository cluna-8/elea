import logging
from typing import Dict

logger = logging.getLogger("basa-secure-gateway.routing")

# Map standard models to their EU-based deployments for GDPR compliance
EU_MODEL_MAPPING: Dict[str, str] = {
    "gpt-4o": "gpt-4o-eu",
    "claude-3-5-sonnet": "claude-3-5-sonnet-eu"
}

class RoutingService:
    @staticmethod
    def get_route_model(model: str, gdpr_mode: bool) -> str:
        """
        Determines the target model based on GDPR data residency requirements.
        If GDPR mode is active and an EU model is available, routes to the EU model.
        """
        if not gdpr_mode:
            return model
            
        eu_model = EU_MODEL_MAPPING.get(model)
        if eu_model:
            logger.info(f"GDPR Policy Active: Routing '{model}' -> '{eu_model}' (EU Endpoint)")
            return eu_model
            
        logger.warning(f"GDPR Policy Active but no EU endpoint configured for model '{model}'. Using original.")
        return model
