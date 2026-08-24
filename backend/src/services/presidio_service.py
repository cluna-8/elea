import logging
import os
import sys
from typing import Dict, List, Optional, Tuple, Any

import httpx

logger = logging.getLogger("basa-secure-gateway.privacy")

# ── Librería PURA compartida (spec 016 T028/T029, FR-012/SC-006) ──────────────────
# Antes este archivo mantenía su PROPIO diccionario PATTERNS, literalmente duplicado
# con `basa_guardian_policy.PII_PATTERNS` del firewall real (spec 014/016) — el
# comentario de ese archivo decía explícitamente "espejo de PresidioService.PATTERNS".
# Importa la MISMA librería que usa el motor (mismo patrón que ya usa gateway.py para
# el passthrough) en vez de mantener una segunda copia que puede divergir en silencio.
for _shared in ("/app/litellm_config/extensions",
                os.path.join(os.path.dirname(__file__), "..", "..", "..", "litellm", "extensions")):
    if os.path.isdir(_shared):
        _abs = os.path.abspath(_shared)
        if _abs not in sys.path:
            sys.path.insert(0, _abs)
        break
import basa_guardian_policy as policy  # noqa: E402


class NlpUnavailableError(Exception):
    """El motor de detección NLP real no respondió — el panel/playground puede
    degradar de forma VISIBLE (spec 016 Assumptions: no es tráfico de producción
    hacia herramientas), pero nunca en silencio como el `except: return []` heredado."""


class PresidioService:
    @staticmethod
    async def analyze_text(text: str, language: str = "es",
                           region: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fallback de dev/demo (regex) — delega en `basa_guardian_policy.default_analyze`,
        la MISMA fuente que usa el camino de producción (spec 016 SC-006). Nunca es el
        detector primario con PHI real (Constraint SC-2) — ver `analyze_text_http`.

        `region` (H1 del gate de #137): `None` ⇒ `policy.DEFAULT_REGION`, nunca un literal
        propio — una segunda constante desconectada de `policy.DEFAULT_REGION` es
        exactamente la clase de bug que H3 corrigió del lado del seed. El caller
        (`guardian_service.process_prompt`) resuelve la región del tenant y la pasa."""
        return await policy.default_analyze(text, region=(region or policy.DEFAULT_REGION))

    @staticmethod
    def mask_text(text: str, entities: List[Dict[str, Any]]) -> Tuple[str, Dict[str, str], List[Dict[str, Any]]]:
        """
        Masks the detected PII/PHI entities in the text and returns:
        1. The masked text
        2. A dictionary mapping placeholders to original values (for unmasking)
        3. A summary of masked entities for audit logs
        """
        # Sort entities by start position in descending order to avoid offset shifts
        sorted_entities = sorted(entities, key=lambda x: x["start"], reverse=True)

        masked_text = text
        placeholder_map = {}
        masked_summary = []

        entity_counts = {}

        for ent in sorted_entities:
            start = ent["start"]
            end = ent["end"]
            entity_type = ent["entity_type"]
            original_val = text[start:end]

            # Count occurrences to create unique placeholders (e.g., [PERSON_0], [PERSON_1])
            entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1
            idx = entity_counts[entity_type] - 1
            placeholder = f"[{entity_type}_{idx}]"

            # Replace in text
            masked_text = masked_text[:start] + placeholder + masked_text[end:]
            placeholder_map[placeholder] = original_val

            masked_summary.append({
                "type": entity_type,
                "placeholder": placeholder,
                "score": ent["score"]
            })

        return masked_text, placeholder_map, masked_summary

    @staticmethod
    def unmask_text(text: str, placeholder_map: Dict[str, str]) -> str:
        """
        Replaces the placeholders in the LLM response with their original values.
        """
        unmasked_text = text
        for placeholder, original_val in placeholder_map.items():
            unmasked_text = unmasked_text.replace(placeholder, original_val)
        return unmasked_text

    # ── Presidio HTTP API (real NLP) ──────────────────────────────────────────

    @staticmethod
    async def analyze_text_http(
        text: str,
        analyzer_url: str,
        language: str = "es",
        entities: List[str] | None = None,
        custom_names: List[str] | None = None,
        region: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Llama al mismo sidecar Presidio Analyzer que usa el firewall real, con los
        mismos `ad_hoc_recognizers` (spec 016 SC-006 — antes este método no aceptaba
        `ad_hoc_recognizers` y el panel no tenía forma de sumar entidades custom).

        FAIL-CLOSED por default (Corrección T028/T029): antes esto atrapaba CUALQUIER
        excepción y devolvía `[]` — fail-open silencioso, contrario a spec 016 FR-004.
        Ahora levanta `NlpUnavailableError`; el caller (`guardian_service.py`) decide
        cómo degradar de forma VISIBLE para el camino de panel/playground (Assumptions
        de la spec: uso interno, no tráfico de producción hacia herramientas — puede
        degradar visible, nunca en silencio).

        `region` (H1 del gate de #137): antes era `"eu"` LITERAL — el Playground SIEMPRE
        detectaba con los patrones de España, sin importar la región del tenant ni la de
        la instalación. `None` ⇒ `policy.DEFAULT_REGION` (mismo criterio que
        `analyze_text`); el caller resuelve la región real y la pasa explícita."""
        payload: dict = {
            "text": text, "language": language, "entities": entities,
            "ad_hoc_recognizers": policy.build_ad_hoc_recognizers(
                custom_names, region or policy.DEFAULT_REGION),
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(f"{analyzer_url.rstrip('/')}/analyze", json=payload)
                r.raise_for_status()
                raw = r.json()
        except Exception as e:
            logger.warning("Presidio Analyzer no disponible (%s): %s", analyzer_url, e)
            raise NlpUnavailableError(str(e)) from e
        if not isinstance(raw, list):
            raise NlpUnavailableError(f"respuesta inesperada del Analyzer: {type(raw)!r}")
        return policy.resolve_overlaps(raw)
