import time
import os
import httpx
import logging
import yaml
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, Any

from ..database import get_db
from ..models.user import User
from ..models.policy import SecurityPolicy
from ..api.policy import get_or_create_default_policy
from ..services.budget_service import BudgetService
from ..services.presidio_service import PresidioService
from ..services.optimization_service import OptimizationService
from ..services.compliance_service import ComplianceService
from ..services.routing_service import RoutingService
from ..services.audit_service import AuditService
from ..services.guardian_service import GuardianService

router = APIRouter(prefix="/chat", tags=["Playground Chat"])
logger = logging.getLogger("basa-secure-gateway.chat")

_ENGINE_URL = os.getenv("LITELLM_API_BASE", "http://litellm:4000")
_ENGINE_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "basa_master_key_9999")

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
            role="admin",
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

@router.post("/completions")
async def chat_completions(
    request: ChatRequest, 
    authorization: Optional[str] = Header(None),
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

        # If this is a real engine key, forward it so the engine enforces the budget
        if api_key_obj.engine_key_token:
            client_key = token
            
    if not user and not group:
        # Fallback to default user (Playground UI dashboard session)
        user = get_or_create_default_user(db)
        
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

    # 4. Layer 1.5: Context Optimization (Headroom)
    optimized_prompt = masked_prompt
    tokens_saved = 0
    is_headroom_active = request.override_headroom_mode if request.override_headroom_mode is not None else policy.headroom_mode
    if is_headroom_active:
        optimized_prompt, tokens_saved = OptimizationService.compress_context(
            masked_prompt, is_headroom_active
        )

    # 5. Layer 2: GDPR & Routing (Apply GDPR routing only if sensitive routing did not change the model)
    is_gdpr_active = request.override_gdpr_mode if request.override_gdpr_mode is not None else policy.gdpr_mode
    if routed_model == request.model:
        routed_model = RoutingService.get_route_model(request.model, is_gdpr_active)

    # 6. Layer 3: LLM Execution (LiteLLM call with fallback)
    llm_raw_response = ""
    prompt_tokens = len(optimized_prompt) // 4  # Estimate
    completion_tokens = 0
    
    logger.info(f"Sending request to LiteLLM: model={routed_model}")
    actual_cost = None
    raw_request_json = None
    raw_response_json = None
    
    try:
        async with httpx.AsyncClient() as client:
            raw_request_json = {
                "model": routed_model,
                "messages": [{"role": "user", "content": optimized_prompt}],
                "temperature": 0.3
            }
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
            litellm_connected = False
            if response.status_code == 200:
                litellm_connected = True
                res_data = response.json()
                llm_raw_response = res_data["choices"][0]["message"]["content"]
                prompt_tokens = res_data["usage"]["prompt_tokens"]
                completion_tokens = res_data["usage"]["completion_tokens"]
                raw_response_json = res_data
                
                # Extract exact cost from LiteLLM headers
                litellm_cost_str = response.headers.get("x-litellm-response-cost")
                if litellm_cost_str:
                    try:
                        from decimal import Decimal
                        actual_cost = Decimal(litellm_cost_str)
                    except Exception:
                        pass
            else:
                logger.error(f"LiteLLM returned status {response.status_code}: {response.text}")
                error_detail = "Basa Gateway error"
                try:
                    error_json = response.json()
                    if "error" in error_json and "message" in error_json["error"]:
                        error_detail = error_json["error"]["message"]
                except Exception:
                    error_detail = response.text
                
                # White-label the error message
                if "litellm." in error_detail:
                    parts = error_detail.split(":", 1)
                    if len(parts) > 1:
                        error_detail = parts[1].strip()
                error_detail = error_detail.replace("litellm", "Basa Gateway").replace("LiteLLM", "Basa Gateway")
                
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
            
        logger.warning(f"Failed to connect to LiteLLM, using simulated response: {e}")
        # Simulated response fallback to ensure playground works beautifully without keys
        time.sleep(1.0) # Simulate network delay
        
        # If prompt was masked, we return a response that references the placeholders
        # so the unmasking layer can be demonstrated visually!
        placeholder_refs = ", ".join(placeholder_map.keys())
        if placeholder_refs:
            llm_raw_response = (
                f"[Simulado - {routed_model}] He recibido la información de {placeholder_refs}. "
                "Según los protocolos médicos de BASA, el paciente requiere reposo clínico y monitoreo de temperatura."
            )
        else:
            llm_raw_response = (
                f"[Simulado - {routed_model}] He procesado tu consulta correctamente. "
                "La pasarela segura de BASA ha verificado este canal de comunicación."
            )
        completion_tokens = len(llm_raw_response) // 4
        
        # Populate simulated JSONs for debugger
        raw_request_json = {
            "model": routed_model,
            "messages": [{"role": "user", "content": optimized_prompt}],
            "temperature": 0.3,
            "note": "Petición simulada (motor fuera de línea)"
        }
        raw_response_json = {
            "id": "chatcmpl-simulated-12345",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": routed_model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": llm_raw_response
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens
            },
            "note": "Respuesta simulada (motor fuera de línea)"
        }

    # 7. Layer 4: Unmasking
    final_response = PresidioService.unmask_text(llm_raw_response, placeholder_map)

    # 8. Logging and Budget Update
    latency_ms = int((time.time() - start_time) * 1000)
    cost = actual_cost if actual_cost is not None else BudgetService.calculate_cost(request.model, prompt_tokens, completion_tokens)
    
    # Save to Audit Log
    AuditService.log_transaction(
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
        user_id=user.id if user else None,
        api_key_id=api_key_obj.id if api_key_obj else None
    )
    
    # Deduct from Budget
    from decimal import Decimal
    BudgetService.update_budget(
        db=db,
        user_id=user.id if user else None,
        group_id=group.id if group else None,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model=request.model,
        override_cost=Decimal(str(cost))
    )

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
                "original_length": len(masked_prompt),
                "optimized_length": len(optimized_prompt),
                "tokens_saved": tokens_saved
            },
            "layer_compliance": {
                "gdpr_active": is_gdpr_active,
                "routed_model": routed_model,
                "ai_act_status": compliance_result["status"],
                "ai_act_reason": compliance_result["reason"]
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

@router.get("/models")
async def list_available_models():
    config_path = "/app/litellm_config/config.yaml"
    if not os.path.exists(config_path):
        config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../litellm/config.yaml"))
    
    models_detail = []
    try:
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config_data = yaml.safe_load(f) or {}
            for m in config_data.get("model_list", []):
                params = m.get("litellm_params", {})
                model_full = params.get("model", "")
                
                # Check if API Key or credentials are configured
                is_key_configured = False
                api_key = params.get("api_key", "")
                
                if isinstance(api_key, str) and api_key.startswith("os.environ/"):
                    env_var_name = api_key.split("/", 1)[1]
                    env_value = os.getenv(env_var_name, "").strip()
                    if env_value:
                        is_key_configured = True
                elif api_key:
                    is_key_configured = True
                else:
                    # Special check for providers with other credentials
                    if "bedrock" in model_full:
                        aws_key = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
                        aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
                        if aws_key and aws_secret:
                            is_key_configured = True
                    elif "vertex_ai" in model_full:
                        vertex_cred = os.getenv("VERTEX_CREDENTIALS", "").strip()
                        if vertex_cred:
                            is_key_configured = True
                    elif "watsonx" in model_full:
                        ibm_key = os.getenv("WATSONX_API_KEY", "").strip()
                        if ibm_key:
                            is_key_configured = True
                    elif "ollama" in model_full or "localhost" in params.get("api_base", ""):
                        # Local models don't need credentials
                        is_key_configured = True
                
                if is_key_configured:
                    provider = "local"
                    model_id = model_full
                    if "/" in model_full:
                        provider, model_id = model_full.split("/", 1)
                    
                    models_detail.append({
                        "model_name": m.get("model_name"),
                        "provider": provider,
                        "model_id": model_id,
                        "api_base": params.get("api_base")
                    })
            
            # If we filtered and found active models, return them
            if models_detail:
                return models_detail
    except Exception as e:
        logger.warning(f"Failed to read models from config.yaml: {e}")
        
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{LITELLM_URL}/v1/models",
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                timeout=5.0
            )
            if response.status_code == 200:
                data = response.json()
                return [
                    {
                        "model_name": m["id"],
                        "provider": "unknown",
                        "model_id": m["id"],
                        "api_base": None
                    }
                    for m in data.get("data", [])
                ]
    except Exception as e:
        logger.warning(f"Failed to fetch models from LiteLLM: {e}")
    
    return [
        {"model_name": "claude-3-5-sonnet", "provider": "anthropic", "model_id": "claude-3-5-sonnet-20240620", "api_base": None},
        {"model_name": "gpt-4o", "provider": "openai", "model_id": "gpt-4o", "api_base": None}
    ]

@router.post("/models")
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

@router.delete("/models/{model_name}")
async def delete_model(model_name: str):
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
        raise HTTPException(status_code=404, detail="No models configured")

    original_len = len(config_data["model_list"])
    config_data["model_list"] = [m for m in config_data["model_list"] if m.get("model_name") != model_name]

    if len(config_data["model_list"]) == original_len:
        raise HTTPException(status_code=404, detail="Model not found")

    try:
        with open(config_path, "w") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)
    except Exception as e:
        logger.error(f"Failed to write litellm config: {e}")
        raise HTTPException(status_code=500, detail="Failed to save model configuration")

    return {"status": "success", "message": f"Model {model_name} deleted successfully"}
