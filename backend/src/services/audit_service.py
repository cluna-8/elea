import logging
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import UUID

from ..models.audit import AuditLog

logger = logging.getLogger("basa-secure-gateway.audit")

class AuditService:
    @staticmethod
    def log_transaction(
        db: Session,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        pii_detected: bool,
        masked_entities: List[Dict[str, Any]],
        compliance_status: str,
        latency_ms: int,
        tokens_saved_by_optimization: int = 0,
        user_id: Optional[UUID] = None,
        api_key_id: Optional[UUID] = None,
        guardian_events: Optional[List[Dict[str, Any]]] = None,
        review_token=None,
        ai_disclosure_delivered: bool = False,
    ) -> AuditLog:
        """
        Creates a secure audit log entry for a transaction.
        Ensures absolutely no raw prompt text or PII is recorded.
        """
        try:
            # Masked entities parameter format: [{"type": "PERSON", "count": 2}]
            # We summarize the counts from the list of masked entities
            summary_entities = []
            if masked_entities:
                entity_counts = {}
                for ent in masked_entities:
                    ent_type = ent.get("type", "UNKNOWN")
                    entity_counts[ent_type] = entity_counts.get(ent_type, 0) + 1
                
                summary_entities = [{"type": k, "count": v} for k, v in entity_counts.items()]

            log_entry = AuditLog(
                user_id=user_id,
                api_key_id=api_key_id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                pii_detected=pii_detected,
                masked_entities=summary_entities if pii_detected else None,
                compliance_status=compliance_status,
                latency_ms=latency_ms,
                tokens_saved_by_optimization=tokens_saved_by_optimization,
                guardian_events=guardian_events or [],
                review_token=review_token,
                ai_disclosure_delivered=ai_disclosure_delivered,
                timestamp=datetime.utcnow()
            )
            
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)
            
            logger.info(f"Audit log saved: ID {log_entry.id} | Cost ${cost_usd:.6f} | PII: {pii_detected} | Compliance: {compliance_status}")
            return log_entry
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to write audit log: {e}", exc_info=True)
            return None
