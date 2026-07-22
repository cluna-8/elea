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
    def get_route_model(model: str, gdpr_mode: bool,
                        available_models: "set[str] | None" = None) -> str:
        """
        Determines the target model based on GDPR data residency requirements.
        If GDPR mode is active and an EU model is available, routes to the EU model.

        available_models: nombres del catálogo vigente del motor. El renombrado
        SOLO se aplica si el destino existe ahí — un mapeo a un alias que el
        catálogo del cliente no define jamás debe salir del backend (rompería
        el request con "modelo desconocido" delante del usuario).
        """
        if not gdpr_mode:
            return model

        eu_model = EU_MODEL_MAPPING.get(model)
        if eu_model:
            if available_models is not None and eu_model not in available_models:
                logger.warning(
                    f"GDPR Policy: destino '{eu_model}' no existe en el catálogo del motor; "
                    f"se mantiene '{model}' (la residencia EU la aplica el enforcement por proveedor)"
                )
                return model
            logger.info(f"GDPR Policy Active: Routing '{model}' -> '{eu_model}' (EU Endpoint)")
            return eu_model

        logger.warning(f"GDPR Policy Active but no EU endpoint configured for model '{model}'. Using original.")
        return model
