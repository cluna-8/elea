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
        cost_saved_usd: float = 0.0,
        compression_strategy: str = "none",
        compression_reversed: bool = False,
        user_id: Optional[UUID] = None,
        api_key_id: Optional[UUID] = None,
        guardian_events: Optional[List[Dict[str, Any]]] = None,
        review_token=None,
        ai_disclosure_delivered: bool = False,
        processing_purpose: Optional[str] = None,
        user_group_id=None,
        tenant_id: Optional[UUID] = None,
        applied_layers: Optional[List[Dict[str, Any]]] = None,
        blocked_by_layer: Optional[str] = None,
        # Keyword-only a propósito: la firma ya arrastra 20+ parámetros posicionales y un
        # dict suelto al final es indistinguible de cualquier otro si se pasa por posición.
        *,
        routing_decision: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        """
        Creates a secure audit log entry for a transaction.
        Ensures absolutely no raw prompt text or PII is recorded.

        Atribución por pedido (spec 027, contrato evento-monitor-atribucion §5-§7):
        ``applied_layers`` es la lista EXHAUSTIVA de capas del perfil con su status y su
        decisión sobre este pedido, y ``blocked_by_layer`` el ``layer_key`` del registry
        que produjo el bloqueo (escalar aparte para que la query de bloqueos sea trivial).
        Ambos son **opcionales**: los callers previos a la 027 (gateway passthrough,
        cualquier script) siguen llamando igual y persisten ``NULL``, que en esas columnas
        significa exactamente "fila anterior a la atribución 027" — no "ninguna capa".

        C1: lo que entra por ``applied_layers`` son SOLO códigos del registry y contadores.
        El productor es ``build_attribution`` (única puerta, valida contra vocabularios
        cerrados); acá no se re-valida para no duplicar la barrera, pero tampoco se
        transforma: se persiste tal cual llega, porque el contrato exige que la columna, el
        evento del motor y el del gateway lleven **el mismo elemento sin transformar**
        (prohibido que un productor "resuma distinto").

        Ruteo automático (spec 030, data-model §2-§3): ``routing_decision`` es la copia
        DURABLE de la decisión del auto-router —``{requested, route, score, model_selected,
        degraded, reason}``— que además viaja por dos superficies efímeras (Debugger y
        vitrina). Opcional: sólo lo manda el camino ``model == "auto"``; en cualquier otra
        consulta persiste ``NULL``, que significa "no pasó por el auto-router" (por eso la
        columna no tiene default). Metadata-only, igual que ``applied_layers``: ruta y
        score son etiqueta de config y número, JAMÁS texto del prompt. Va en su PROPIA
        columna y no dentro de ``guardian_events`` — ese campo está congelado porque la
        hash-chain de licencias lo relee posicionalmente (licensing/audit_events.py:92-93)
        — así que la cadena de hash no ve esta columna y no cambia.
        """
        # DEUDA CONOCIDA (spec 018, owner: Cristian): el try/except de abajo **dropea la
        # auditoría** ante cualquier fallo de escritura — la transacción se sirve igual y la
        # fila desaparece sin que nadie se entere. Con la 027 eso pasa a llevarse puesta
        # también la atribución del pedido, así que el agujero es más caro que antes. NO se
        # arregla acá a propósito: la completitud/confiabilidad del registro durable es
        # alcance de la 018 y tocarla desde esta feature mezclaría dos cortes.
        try:
            # Masked entities parameter format: [{"type": "PERSON", "count": 2}]
            # We summarize the counts from the list of masked entities
            summary_entities = []
            if masked_entities:
                entity_counts = {}
                for ent in masked_entities:
                    ent_type = ent.get("type", "UNKNOWN")
                    # F5: respetar el `count` real cuando el caller pasa entidades ya
                    # agregadas (p.ej. [{"type":"EMAIL_ADDRESS","count":3}]); default 1
                    # cuando la lista es una entrada por entidad sin `count`.
                    entity_counts[ent_type] = entity_counts.get(ent_type, 0) + ent.get("count", 1)

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
                cost_saved_usd=cost_saved_usd,
                compression_strategy=compression_strategy,
                compression_reversed=compression_reversed,
                guardian_events=guardian_events or [],
                # `guardian_events` queda CONGELADO como legado (D6: la hash-chain de
                # licencias lo relee posicionalmente). La atribución nueva NO lo pisa ni lo
                # migra: vive en su propia columna, al lado.
                applied_layers=applied_layers,
                blocked_by_layer=blocked_by_layer,
                routing_decision=routing_decision,
                review_token=review_token,
                ai_disclosure_delivered=ai_disclosure_delivered,
                processing_purpose=processing_purpose,
                user_group_id=user_group_id,
                timestamp=datetime.utcnow()
            )
            # tenant_id explícito sólo si el caller lo resolvió (spec 014 US4); si es
            # None se respeta el default del modelo (DEFAULT_TENANT_ID) — nunca None.
            if tenant_id is not None:
                log_entry.tenant_id = tenant_id

            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)
            
            logger.info(f"Audit log saved: ID {log_entry.id} | Cost ${cost_usd:.6f} | PII: {pii_detected} | Compliance: {compliance_status}")
            return log_entry
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to write audit log: {e}", exc_info=True)
            return None
