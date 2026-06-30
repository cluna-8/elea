import re
import logging
import httpx
from typing import Dict, List, Tuple, Any

logger = logging.getLogger("basa-secure-gateway.privacy")

# Regex patterns for local, zero-dependency PII/PHI masking
PATTERNS = {
    "EMAIL_ADDRESS": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "PHONE_NUMBER": r"\b(?:\+?54)?[-. ]?\(?\d{2,4}\)?[-. ]?\d{3,4}[-. ]?\d{4}\b",
    "DNI": r"\b\d{2}\.?\d{3}\.?\d{3}\b",
    "CUIL": r"\b\d{2}-\d{8}-\d\b",
    # Captures capitalized name sequences preceded by common indicators
    "PERSON": r"\b(?:paciente|doctor|dr|dra|sr|sra|don|doña|afiliado)\s+([A-Z][a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1]+(?:\s+[A-Z][a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1]+)+)\b"
}

class PresidioService:
    @staticmethod
    async def analyze_text(text: str, language: str = "es") -> List[Dict[str, Any]]:
        """
        Scans text for PII/PHI using high-performance local regular expressions.
        Requires zero external containers or machine learning models.
        """
        entities = []
        
        for entity_type, pattern in PATTERNS.items():
            for match in re.finditer(pattern, text, re.IGNORECASE if entity_type != "PERSON" else 0):
                # For PERSON, we only want to mask the captured name, not the prefix (e.g. "paciente")
                if entity_type == "PERSON":
                    start = match.start(1)
                    end = match.end(1)
                else:
                    start = match.start()
                    end = match.end()
                
                entities.append({
                    "start": start,
                    "end": end,
                    "entity_type": entity_type,
                    "score": 0.95
                })
                
        return entities

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
    ) -> List[Dict[str, Any]]:
        """Call a Presidio Analyzer HTTP service. Returns entities in the same format as analyze_text."""
        payload: dict = {"text": text, "language": language}
        if entities:
            payload["entities"] = entities
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(f"{analyzer_url.rstrip('/')}/analyze", json=payload)
                r.raise_for_status()
                return r.json()
        except Exception as e:
            logger.warning("Presidio Analyzer unreachable (%s), falling back to regex: %s", analyzer_url, e)
            return []

    @staticmethod
    async def anonymize_text_http(
        text: str,
        anonymizer_url: str,
        analyzer_results: List[Dict[str, Any]],
    ) -> str:
        """Call a Presidio Anonymizer HTTP service. Returns anonymized text."""
        payload = {"text": text, "analyzer_results": analyzer_results}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(f"{anonymizer_url.rstrip('/')}/anonymize", json=payload)
                r.raise_for_status()
                return r.json().get("text", text)
        except Exception as e:
            logger.warning("Presidio Anonymizer unreachable (%s): %s", anonymizer_url, e)
            return text
