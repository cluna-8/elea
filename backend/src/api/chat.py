import time
import os
import uuid
import httpx
import logging
import yaml
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Response, status, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from ..database import get_db
from ..models.user import User
from ..models.policy import SecurityPolicy
from ..models.guardian import Guardian
from ..models.audit import AuditLog
from ..models.compliance import ComplianceProject, HumanReview
from ..api.compliance import DEFAULT_DISCLOSURE_ES
from ..api.policy import get_or_create_default_policy
from ..services.budget_service import BudgetService
from ..services.presidio_service import PresidioService
from ..services.optimization_service import OptimizationService
from ..services.compliance_service import ComplianceService
from ..services.routing_service import RoutingService
from ..services.audit_service import AuditService
from ..services.guardian_service import GuardianService
from ..services.rate_limiter import check_rpm, check_tpm, RateLimitExceeded
from ..services import ai_engine_client
from ..auth.rbac import require_role, require_authenticated

router = APIRouter(prefix="/chat", tags=["Playground Chat"])
logger = logging.getLogger("basa-secure-gateway.chat")

_ENGINE_URL = os.getenv("LITELLM_API_BASE", "http://litellm:4000")
_ENGINE_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "basa_master_key_9999")

# Guardia de calidad (spec 012 US6): reintenta con el prompt original si la respuesta
# tras compresión es anómala (vacía/muy corta). Fail-open; raro (solo si se comprimió).
_REVERSAL_GUARD = os.getenv("COMPRESSION_REVERSAL_GUARD", "true").lower() == "true"

_EU_COMPLIANT_PROVIDERS = {"bedrock", "vertex_ai", "azure", "watsonx", "ollama"}


def _get_config_path() -> str:
    path = "/app/litellm_config/config.yaml"
    if not os.path.exists(path):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../litellm/config.yaml"))
    return path


def _check_configured(params: dict, model_full: str) -> bool:
    api_key = params.get("api_key", "")
    if isinstance(api_key, str) and api_key.startswith("os.environ/"):
        env_var = api_key.split("/", 1)[1]
        return bool(os.getenv(env_var, "").strip())
    if api_key:
        return True
    if "bedrock" in model_full:
        return bool(os.getenv("AWS_ACCESS_KEY_ID", "").strip() and os.getenv("AWS_SECRET_ACCESS_KEY", "").strip())
    if "vertex_ai" in model_full:
        return bool(os.getenv("VERTEX_CREDENTIALS", "").strip())
    if "watsonx" in model_full:
        return bool(os.getenv("WATSONX_API_KEY", "").strip())
    if "ollama" in model_full or "host.docker.internal" in params.get("api_base", "") or "localhost" in params.get("api_base", ""):
        return True
    return False

class ChatRequest(BaseModel):
    message: str
    model: str
    override_pii_masking: Optional[bool] = None
    override_gdpr_mode: Optional[bool] = None
    override_ai_act_mode: Optional[bool] = None
    override_headroom_mode: Optional[bool] = None

def get_or_create_default_user(db: Session) -> User:
    user = db.query(User).filter(User.username == "admin").first()
    if not user:
        import hashlib
        user = User(
            username="admin",
            email="admin@basa.com.ar",
            password_hash=hashlib.sha256("admin".encode()).hexdigest(),
            role="tenant_admin",  # canónico post-013; el fallback en sí se cierra en 017 (SC-3)
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

HUMAN_REVIEW_FLAG_ES = (
    "⚠️ **Pendiente de validación sanitaria.** Esta respuesta ha sido generada por inteligencia artificial "
    "y está siendo revisada por un profesional sanitario. No aplique estas indicaciones hasta recibir confirmación."
)

@router.post("/completions")
async def chat_completions(
    request: ChatRequest,
    http_resp: Response,
    authorization: Optional[str] = Header(None),
    x_processing_purpose: Optional[str] = Header(None, alias="X-Processing-Purpose"),
    db: Session = Depends(get_db)
):
    start_time = time.time()
    
    # 0. Virtual Key / Session Authentication
    user = None
    group = None
    api_key_obj = None
    
    client_key: Optional[str] = None  # forwarded to engine if it's a real engine key

    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "").strip()

        if token.startswith("sk-"):
            # Virtual key path: validate against DB
            import hashlib
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            from ..models.budget import APIKey
            api_key_obj = db.query(APIKey).filter(APIKey.key_hash == token_hash, APIKey.is_active == True).first()
            if not api_key_obj:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Llave virtual (Virtual Key) inválida o inactiva."
                )
            if api_key_obj.user_id:
                user = api_key_obj.user
            if api_key_obj.group_id:
                group = api_key_obj.group
            if api_key_obj.engine_key_token:
                client_key = token
        else:
            # JWT session path: identify the logged-in user and their group
            from ..auth.session import decode_session_token
            from ..models.user import User as UserModel, Group as GroupModel
            payload = decode_session_token(token)
            if payload:
                uid = payload.get("sub")
                if uid:
                    user = db.query(UserModel).filter(UserModel.id == uid, UserModel.is_active == True).first()
                    if user and user.group_id:
                        group = db.query(GroupModel).filter(GroupModel.id == user.group_id).first()
            else:
                # Token present but invalid/expired — reject so the frontend forces re-login
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Sesión expirada. Por favor, vuelve a iniciar sesión.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    if not user and not group:
        # Fallback: no Authorization header at all (direct API access, scripts, curl)
        user = get_or_create_default_user(db)

    # 1a. Rate Limiting (RPM check before any expensive processing)
    _rpm_remaining = None
    _tpm_remaining = None
    if api_key_obj:
        try:
            _rpm_remaining = check_rpm(api_key_obj.id, api_key_obj.rpm_limit or 60)
        except RateLimitExceeded as e:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=e.message,
                headers={"Retry-After": str(e.retry_after)},
            )

    policy = get_or_create_default_policy(db)

    # 1. Budget Enforcement
    user_id_check = user.id if user else None
    group_id_check = group.id if group else None
    
    if not BudgetService.has_sufficient_budget(db, user_id=user_id_check, group_id=group_id_check):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Presupuesto mensual agotado para la llave virtual o el usuario/equipo."
        )

    # 2. Compliance: AI Act Check (Prohibited practices block immediately)
    ai_act_mode = request.override_ai_act_mode if request.override_ai_act_mode is not None else policy.ai_act_mode
    compliance_result = ComplianceService.evaluate_prompt(request.message, ai_act_mode)
    if compliance_result["status"] == "blocked_prohibited":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=compliance_result["reason"]
        )

    is_pii_active = request.override_pii_masking if request.override_pii_masking is not None else policy.is_active
    
    # 3. Run prompt through the Security Guardians (PII, Secret Detection, Sensitive Routing)
    guardian_overrides = {
        "override_pii_masking": is_pii_active
    }
    
    guardian_res = await GuardianService.process_prompt(
        db=db,
        prompt=request.message,
        selected_model=request.model,
        overrides=guardian_overrides
    )
    
    if guardian_res["blocked"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=guardian_res["block_reason"]
        )
        
    masked_prompt = guardian_res["prompt"]
    routed_model = guardian_res["model"]
    placeholder_map = guardian_res["placeholder_map"]
    entities_detected = guardian_res["entities_detected"]
    guardian_triggers = guardian_res["triggers"]

    # 4. Layer 1.5: Context Optimization (Ahorro de Costes IA — spec 012)
    optimized_prompt = masked_prompt
    tokens_saved = 0
    strategy_applied = "none"
    compression_reversed = False  # spec 012 US6 — guardia de reversión

    # Resolver config de compresión: override request > grupo > política global
    comp_cache_enabled = True
    if request.override_headroom_mode is not None:
        is_headroom_active = request.override_headroom_mode
        comp_strategy = "deterministic"
        comp_threshold = OptimizationService.DEFAULT_THRESHOLD
        comp_aggressiveness = "medium"
    elif group is not None and getattr(group, "compression_mode", "off") not in (None, "off"):
        is_headroom_active = True
        comp_strategy = group.compression_mode  # 'deterministic' | 'headroom'
        comp_threshold = group.compression_threshold_tokens or OptimizationService.DEFAULT_THRESHOLD
        comp_aggressiveness = group.compression_aggressiveness or "medium"
        comp_cache_enabled = bool(getattr(group, "compression_cache_enabled", True))
    else:
        _pol_comp = getattr(policy, "compression_mode", None)
        if _pol_comp is None:
            _pol_comp = getattr(policy, "headroom_mode", False)
        is_headroom_active = bool(_pol_comp)
        comp_strategy = "deterministic"
        comp_threshold = OptimizationService.DEFAULT_THRESHOLD
        comp_aggressiveness = "medium"

    if is_headroom_active:
        # Auto-detect contenido estructurado -> headroom incluso si la estrategia dice deterministic
        stripped = masked_prompt.lstrip()
        eff_strategy = "headroom" if (comp_strategy == "headroom" or stripped.startswith("{") or stripped.startswith("[")) else "deterministic"
        optimized_prompt, tokens_saved = OptimizationService.compress_context(
            masked_prompt, True, comp_threshold, comp_aggressiveness, eff_strategy,
            cache_enabled=comp_cache_enabled,
        )
        strategy_applied = eff_strategy if tokens_saved > 0 else "none"

    # 5. Layer 2: GDPR & Routing (Apply GDPR routing only if sensitive routing did not change the model)
    is_gdpr_active = request.override_gdpr_mode if request.override_gdpr_mode is not None else policy.gdpr_mode
    if routed_model == request.model:
        routed_model = RoutingService.get_route_model(request.model, is_gdpr_active)

    # 5b. Compliance — resolve project via hierarchy: key → user → group → global
    from datetime import timedelta
    from ..models.budget import APIKey as APIKeyModel

    resolved_project = None
    # 1. Key-level
    if api_key_obj and getattr(api_key_obj, "compliance_project_id", None):
        resolved_project = db.query(ComplianceProject).filter(
            ComplianceProject.id == api_key_obj.compliance_project_id,
            ComplianceProject.is_active == True
        ).first()
    # 2. User-level
    if not resolved_project and user and getattr(user, "compliance_project_id", None):
        resolved_project = db.query(ComplianceProject).filter(
            ComplianceProject.id == user.compliance_project_id,
            ComplianceProject.is_active == True
        ).first()
    # 3. Group-level
    if not resolved_project and group and getattr(group, "compliance_project_id", None):
        resolved_project = db.query(ComplianceProject).filter(
            ComplianceProject.id == group.compliance_project_id,
            ComplianceProject.is_active == True
        ).first()
    # 4. Global fallback
    active_projects = [resolved_project] if resolved_project else []

    _applied_project_name = resolved_project.name if resolved_project else None
    _applied_risk_level = (
        getattr(api_key_obj, "risk_level", None) or  # not stored on key, but future-proof
        (getattr(user, "risk_level", None) if user else None) or
        (getattr(group, "default_risk_level", None) if group else None)
    )
    _applied_legal_basis = (
        (getattr(user, "legal_basis", None) if user else None) or
        (getattr(group, "default_legal_basis", None) if group else None)
    )
    _user_group_id = group.id if group else None

    # EU region enforcement
    eu_safe_prefixes = ("azure-", "bedrock-", "vertex-", "ollama-")
    for proj in active_projects:
        if proj.eu_region_required and not any(routed_model.startswith(p) for p in eu_safe_prefixes):
            logger.warning("EU region enforcement blocked model %s for project %s", routed_model, proj.name)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="La política de residencia de datos exige procesamiento en la UE. El modelo seleccionado no está disponible para esta solicitud."
            )

    # Determine if AI disclosure and human review apply
    _deliver_disclosure = False
    _disclosure_message = None
    _review_token_val = None
    _human_review_flag = False   # hybrid model: flag without blocking

    for proj in active_projects:
        if proj.ai_disclosure_enabled and not _deliver_disclosure:
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            recent = db.query(AuditLog).filter(
                AuditLog.api_key_id == (api_key_obj.id if api_key_obj else None),
                AuditLog.timestamp >= one_hour_ago,
                AuditLog.ai_disclosure_delivered == True
            ).first()
            if not recent:
                _deliver_disclosure = True
                _disclosure_message = proj.ai_disclosure_message or DEFAULT_DISCLOSURE_ES
        if proj.human_review_required and not _review_token_val:
            _review_token_val = uuid.uuid4()
            _human_review_flag = True

    # 6. Layer 3: LLM Execution with active guardrails
    llm_raw_response = ""
    prompt_tokens = len(optimized_prompt) // 4  # Estimate
    completion_tokens = 0
    guardian_events: list = []

    logger.info(f"Sending request to AI engine: model={routed_model}")
    actual_cost = None
    raw_request_json = None
    raw_response_json = None

    # Collect active engine-backed guardrails from DB
    active_engine_guardrails = await ai_engine_client.get_active_guardrail_names(db)

    try:
        async with httpx.AsyncClient() as client:
            raw_request_json = {
                "model": routed_model,
                "messages": [{"role": "user", "content": optimized_prompt}],
                "temperature": 0.3
            }
            if active_engine_guardrails:
                raw_request_json["guardrails"] = active_engine_guardrails

            engine_auth_key = client_key if client_key else _ENGINE_MASTER_KEY
            response = await client.post(
                f"{_ENGINE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {engine_auth_key}",
                    "Content-Type": "application/json"
                },
                json=raw_request_json,
                timeout=15.0
            )
            if response.status_code == 200:
                res_data = response.json()
                llm_raw_response = res_data["choices"][0]["message"]["content"]
                prompt_tokens = res_data["usage"]["prompt_tokens"]
                completion_tokens = res_data["usage"]["completion_tokens"]
                raw_response_json = res_data

                # Capture guardrail events returned by the engine (if any)
                guardian_events = res_data.get("guardrail_info", {}).get("guardrail_events", []) or []

                # Extract exact cost from engine headers
                cost_str = response.headers.get("x-litellm-response-cost")

                # --- Guardia de calidad (spec 012 US6) — reversión ante anomalía ---
                # Si se aplicó compresión y la respuesta es anómala (vacía/muy corta),
                # reintenta UNA vez con el prompt original (sin comprimir) y marca el
                # evento. Solo se activa cuando hubo compresión real (raro). Fail-open:
                # cualquier fallo del reintento deja la respuesta original intacta.
                if (
                    _REVERSAL_GUARD
                    and tokens_saved > 0
                    and OptimizationService.response_is_anomalous(llm_raw_response, completion_tokens)
                ):
                    logger.warning(
                        "compression reversal guard triggered (tokens_saved=%s, completion_tokens=%s) "
                        "— retrying with the original uncompressed prompt",
                        tokens_saved, completion_tokens,
                    )
                    try:
                        reversal_req = dict(raw_request_json)
                        reversal_req["messages"] = [{"role": "user", "content": masked_prompt}]
                        rev_response = await client.post(
                            f"{_ENGINE_URL}/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {engine_auth_key}",
                                "Content-Type": "application/json",
                            },
                            json=reversal_req,
                            timeout=15.0,
                        )
                        if rev_response.status_code == 200:
                            rev_data = rev_response.json()
                            rev_content = rev_data["choices"][0]["message"]["content"]
                            # Solo aceptar el reintento si mejora la respuesta
                            if rev_content and len(rev_content.strip()) > len((llm_raw_response or "").strip()):
                                llm_raw_response = rev_content
                                prompt_tokens = rev_data["usage"]["prompt_tokens"]
                                completion_tokens = rev_data["usage"]["completion_tokens"]
                                raw_response_json = rev_data
                                tokens_saved = 0  # se descuenta el ahorro: se usó el prompt original
                                strategy_applied = "none"
                                compression_reversed = True
                                rev_cost = rev_response.headers.get("x-litellm-response-cost")
                                if rev_cost:
                                    try:
                                        actual_cost = Decimal(rev_cost)
                                    except Exception:
                                        pass
                                logger.info("compression reversal succeeded — original prompt restored")
                    except Exception as rev_err:  # fail-open: nunca rompe el flujo
                        logger.warning("compression reversal retry failed (%s) — keeping original response", rev_err)
                if cost_str:
                    try:
                        actual_cost = Decimal(cost_str)
                    except Exception:
                        pass
            elif response.status_code == 400:
                # Engine blocked the request via a guardrail — do NOT expose provider names
                logger.warning("AI engine blocked request (guardrail): %s", response.text)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="La petición fue bloqueada por las políticas de seguridad configuradas."
                )
            else:
                logger.error("AI engine returned status %s: %s", response.status_code, response.text)
                error_detail = "Basa Gateway error"
                try:
                    error_json = response.json()
                    if "error" in error_json and "message" in error_json["error"]:
                        error_detail = error_json["error"]["message"]
                except Exception:
                    error_detail = response.text

                # White-label
                error_detail = error_detail.replace("litellm", "Basa Gateway").replace("LiteLLM", "Basa Gateway")
                if "litellm." in error_detail:
                    parts = error_detail.split(":", 1)
                    if len(parts) > 1:
                        error_detail = parts[1].strip()

                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Error del modelo ({routed_model}): {error_detail}"
                )
                
    except HTTPException:
        raise
    except Exception as e:
        # Check if we were able to reach the server. If yes, it's a model execution error.
        if "response" in locals() and response is not None:
            err_msg = str(e)
            if "litellm." in err_msg:
                parts = err_msg.split(":", 1)
                if len(parts) > 1:
                    err_msg = parts[1].strip()
            err_msg = err_msg.replace("litellm", "Basa Gateway").replace("LiteLLM", "Basa Gateway")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al ejecutar el modelo: {err_msg}"
            )
            
        # No response object => we never reached the AI engine (connection refused / timeout).
        # Fail-closed: do NOT fabricate a response. LiteLLM handles model-level fallbacks
        # (router_settings.fallbacks) and retries (num_retries) on its side; if it is unreachable
        # the gateway cannot serve inference and must surface the outage honestly.
        logger.error("AI engine unreachable, failing closed (no simulated response): %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El motor de IA no está disponible. Reintente en unos minutos.",
        )

    # 6b. TPM check (after LLM: we now know actual token counts)
    if api_key_obj:
        try:
            _tpm_remaining = check_tpm(
                api_key_obj.id,
                api_key_obj.tpm_limit or 100000,
                prompt_tokens + completion_tokens,
            )
        except RateLimitExceeded as e:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=e.message,
                headers={"Retry-After": str(e.retry_after)},
            )

    # 7. Layer 4: Unmasking
    final_response = PresidioService.unmask_text(llm_raw_response, placeholder_map)

    # Apply AI disclosure (prepend if this is a new session)
    if _deliver_disclosure and _disclosure_message:
        final_response = f"ℹ️ {_disclosure_message}\n\n{final_response}"

    # Hybrid man-in-the-loop: append flag at the end (response delivered, not blocked)
    if _human_review_flag:
        final_response = f"{final_response}\n\n---\n{HUMAN_REVIEW_FLAG_ES}"

    # 8. Logging and Budget Update
    latency_ms = int((time.time() - start_time) * 1000)
    cost = actual_cost if actual_cost is not None else BudgetService.calculate_cost(request.model, prompt_tokens, completion_tokens)

    # Store human review record if required — save the AI response (not the prompt)
    if _review_token_val:
        # Strip the review flag banner before storing so the reviewer sees the clean response
        clean_response = llm_raw_response if llm_raw_response else final_response.split("\n\n---\n")[0]
        review_entry = HumanReview(
            review_token=_review_token_val,
            created_at=datetime.utcnow().isoformat(),
            response_text=clean_response,
        )
        db.add(review_entry)
        db.flush()

    # Ahorro USD real (spec 012 US3) — calculado sobre el modelo final enrutado
    cost_saved_usd = Decimal("0")
    if tokens_saved > 0:
        from ..services.budget_service import MODEL_PRICING
        _pricing = MODEL_PRICING.get(routed_model, MODEL_PRICING.get("default"))
        cost_saved_usd = (Decimal(tokens_saved) / Decimal("1000000")) * _pricing["input"]

    # Save to Audit Log
    audit_log = AuditService.log_transaction(
        db=db,
        model=request.model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=float(cost),
        pii_detected=len(entities_detected) > 0,
        masked_entities=entities_detected,
        compliance_status=compliance_result["status"],
        latency_ms=latency_ms,
        tokens_saved_by_optimization=tokens_saved,
        cost_saved_usd=float(cost_saved_usd),
        compression_strategy=strategy_applied,        # spec 012 US6 — telemetría por estrategia
        compression_reversed=compression_reversed,    # spec 012 US6 — guardia de reversión
        user_id=user.id if user else None,
        api_key_id=api_key_obj.id if api_key_obj else None,
        guardian_events=(guardian_triggers or []) + (guardian_events or []),
        review_token=_review_token_val,
        ai_disclosure_delivered=_deliver_disclosure,
        processing_purpose=x_processing_purpose,
        user_group_id=_user_group_id,
    )

    # Link review record to audit log
    if _review_token_val and audit_log:
        review_entry.audit_log_id = audit_log.id
        db.commit()
    
    # Deduct from Budget
    BudgetService.update_budget(
        db=db,
        user_id=user.id if user else None,
        group_id=group.id if group else None,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model=request.model,
        override_cost=Decimal(str(cost))
    )

    # Attach rate limit headers if a virtual key was used
    if api_key_obj:
        if _rpm_remaining is not None:
            http_resp.headers["X-RateLimit-Remaining-Requests"] = str(_rpm_remaining)
        if _tpm_remaining is not None:
            http_resp.headers["X-RateLimit-Remaining-Tokens"] = str(_tpm_remaining)

    # Return complete metadata package for the UI layer animation
    return {
        "response": final_response,
        "pipeline_metadata": {
            "guardian_triggers": guardian_triggers,
            "layer_masking": {
                "active": is_pii_active,
                "original_prompt": request.message,
                "masked_prompt": masked_prompt,
                "entities_detected": entities_detected
            },
            "layer_optimization": {
                "active": is_headroom_active,
                "strategy_applied": strategy_applied,
                "original_length": len(masked_prompt),
                "optimized_length": len(optimized_prompt),
                "tokens_saved": tokens_saved,
                "cost_saved_usd": float(cost_saved_usd),
                "reversed": compression_reversed
            },
            "layer_compliance": {
                "gdpr_active": is_gdpr_active,
                "routed_model": routed_model,
                "ai_act_status": compliance_result["status"],
                "ai_act_reason": compliance_result["reason"],
                "applied_project": _applied_project_name,
                "applied_risk_level": _applied_risk_level,
                "applied_legal_basis": _applied_legal_basis,
                "ai_disclosure_delivered": _deliver_disclosure,
                "human_review_pending": _human_review_flag,
                "review_token": str(_review_token_val) if _review_token_val else None,
                "processing_purpose": x_processing_purpose,
            },
            "layer_llm": {
                "model_used": routed_model,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": float(cost),
                "raw_request_json": raw_request_json,
                "raw_response_json": raw_response_json
            },
            "layer_unmasking": {
                "raw_response": llm_raw_response,
                "unmasked_response": final_response
            }
        }
    }

class ModelCreateSchema(BaseModel):
    model_name: str
    provider: str
    model_id: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None

@router.get("/models", dependencies=[Depends(require_authenticated())])
async def list_available_models():
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}

        result = []
        for m in config_data.get("model_list", []):
            params = m.get("litellm_params", {})
            model_full = params.get("model", "")
            provider = "local"
            model_id = model_full
            if "/" in model_full:
                provider, model_id = model_full.split("/", 1)
            result.append({
                "model_name": m.get("model_name"),
                "provider": provider,
                "model_id": model_id,
                "api_base": params.get("api_base"),
                "is_configured": _check_configured(params, model_full),
                "is_eu_compliant": provider in _EU_COMPLIANT_PROVIDERS,
            })
        return result
    except Exception as e:
        logger.warning("Failed to read models from config.yaml: %s", e)
        return []

@router.post("/models", dependencies=[Depends(require_role("admin", "developer"))])
async def register_model(model_in: ModelCreateSchema):
    config_path = "/app/litellm_config/config.yaml"
    if not os.path.exists(config_path):
        config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../litellm/config.yaml"))
    
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to read litellm config: {e}")
        raise HTTPException(status_code=500, detail="Failed to read model configuration")

    if "model_list" not in config_data:
        config_data["model_list"] = []

    for m in config_data["model_list"]:
        if m.get("model_name") == model_in.model_name:
            raise HTTPException(status_code=400, detail="Model name already exists")

    litellm_params = {
        "model": f"{model_in.provider}/{model_in.model_id}" if model_in.provider != "local" else model_in.model_id
    }
    if model_in.api_key:
        litellm_params["api_key"] = model_in.api_key
    if model_in.api_base:
        litellm_params["api_base"] = model_in.api_base

    new_model_entry = {
        "model_name": model_in.model_name,
        "litellm_params": litellm_params
    }

    config_data["model_list"].append(new_model_entry)

    try:
        with open(config_path, "w") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)
    except Exception as e:
        logger.error(f"Failed to write litellm config: {e}")
        raise HTTPException(status_code=500, detail="Failed to save model configuration")

    return {"status": "success", "message": f"Model {model_in.model_name} registered successfully"}

@router.delete("/models/{model_name}", dependencies=[Depends(require_role("admin", "developer"))])
async def delete_model(model_name: str):
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to read config: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read model configuration")

    if "model_list" not in config_data:
        raise HTTPException(status_code=404, detail="No models configured")

    original_len = len(config_data["model_list"])
    config_data["model_list"] = [m for m in config_data["model_list"] if m.get("model_name") != model_name]
    if len(config_data["model_list"]) == original_len:
        raise HTTPException(status_code=404, detail="Model not found")

    try:
        with open(config_path, "w") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)
    except Exception as e:
        logger.error("Failed to write config: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save model configuration")

    return {"status": "success", "message": f"Model {model_name} deleted successfully"}


class ModelCredentialSchema(BaseModel):
    # Identificador del CONTRATO WIRE con el motor (allowlisted en los checks de marca
    # blanca); el title explícito evita que el titulado automático exponga el vendor
    # en el OpenAPI publicado (constitución VII).
    litellm_params: Optional[dict] = Field(default=None, title="Parámetros del motor")


@router.patch("/models/{model_name}", dependencies=[Depends(require_role("admin", "developer"))])
async def update_model_credential(model_name: str, body: ModelCredentialSchema):
    """Merge de credenciales del motor (campos del contrato litellm_params) en config.yaml."""
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to read config: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read model configuration")

    found = False
    for m in config_data.get("model_list", []):
        if m.get("model_name") == model_name:
            if body.litellm_params:
                m.setdefault("litellm_params", {}).update(
                    {k: v for k, v in body.litellm_params.items() if v}
                )
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="Model not found")

    try:
        with open(config_path, "w") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)
    except Exception as e:
        logger.error("Failed to write config: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save model configuration")

    return {"status": "success", "message": f"Model {model_name} updated"}


# --- Fallback configuration ---

class FallbackBody(BaseModel):
    fallback_model: Optional[str] = None


@router.get("/fallbacks", dependencies=[Depends(require_role("admin", "developer"))])
async def get_fallbacks():
    """Returns the current fallback map: {model_name: fallback_model_name}."""
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}
        raw = config_data.get("router_settings", {}).get("fallbacks", [])
        result: dict = {}
        for item in raw:
            for k, v in item.items():
                result[k] = v[0] if v else None
        return result
    except Exception:
        return {}


@router.put("/fallbacks/{model_name}", dependencies=[Depends(require_role("admin", "developer"))])
async def set_fallback(model_name: str, body: FallbackBody):
    """Set or clear the fallback model for a given model. Written to config.yaml router_settings."""
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to read config")

    if "router_settings" not in config_data:
        config_data["router_settings"] = {"disable_cooldowns": True}

    fallbacks = config_data["router_settings"].get("fallbacks", [])
    fallbacks = [item for item in fallbacks if model_name not in item]
    if body.fallback_model:
        fallbacks.append({model_name: [body.fallback_model]})
    config_data["router_settings"]["fallbacks"] = fallbacks

    try:
        with open(config_path, "w") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to write config")

    return {"status": "ok"}


@router.get("/models/pricing", dependencies=[Depends(require_authenticated())])
async def get_models_pricing():
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{_ENGINE_URL}/model/info",
                headers={"Authorization": f"Bearer {_ENGINE_MASTER_KEY}"}
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []

    result = []
    for m in data.get("data", []):
        info = m.get("model_info", {})
        input_cost = info.get("input_cost_per_token", 0) or 0
        output_cost = info.get("output_cost_per_token", 0) or 0
        result.append({
            "model_name": m.get("model_name"),
            "input_cost_per_million": round(float(input_cost) * 1_000_000, 4),
            "output_cost_per_million": round(float(output_cost) * 1_000_000, 4),
            "max_tokens": info.get("max_tokens"),
            "max_input_tokens": info.get("max_input_tokens"),
        })
    return result
