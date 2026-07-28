from decimal import ROUND_HALF_UP, Decimal
from sqlalchemy.orm import Session
from ..models.budget import Budget
from ..models.user import User

# Precisión del contador de gasto (issue #76 + migración 014). Es la MISMA escala que
# `budgets.current_spend_usd` en la base: cuantizar acá con otra escala no serviría de nada
# —Postgres redondearía igual al guardar— y cuantizar con MENOS decimales reintroduciría el
# bug que la 014 arregla (una llamada de ~$0.000012 valía 0.0000 y el gasto no se movía).
_ESCALA_USD = Decimal("0.00000001")  # 1e-8, o sea numeric(14,8)


def cuantizar_usd(monto: Decimal) -> Decimal:
    """Redondea un coste a la escala real de la columna (8 decimales).

    Se hace explícito y no se deja al driver porque el redondeo silencioso ES el bug: con
    la escala vieja, dos llamadas de $0.00001 sumaban $0.0000. HALF_UP (y no el HALF_EVEN
    por defecto de `decimal`) porque es lo que espera quien lee dinero en un panel.
    """
    if not isinstance(monto, Decimal):
        monto = Decimal(str(monto))
    return monto.quantize(_ESCALA_USD, rounding=ROUND_HALF_UP)

# Model pricing per 1,000,000 tokens (Input, Output) in USD
MODEL_PRICING = {
    "gpt-4o": {"input": Decimal("5.00"), "output": Decimal("15.00")},
    "azure-gpt-4o-mini": {"input": Decimal("0.165"), "output": Decimal("0.66")},
    "gemini-2.5-flash": {"input": Decimal("0.30"), "output": Decimal("2.50")},
    "gemini-2.5-flash-lite": {"input": Decimal("0.075"), "output": Decimal("0.30")},
    "gpt-4o-mini": {"input": Decimal("0.15"), "output": Decimal("0.60")},
    "claude-3-5-sonnet": {"input": Decimal("3.00"), "output": Decimal("15.00")},
    "default": {"input": Decimal("5.00"), "output": Decimal("15.00")}
}

# Modelos locales/self-hosted (Ollama del cliente): el token NO tiene costo — el
# hardware es del cliente (ver litellm/config.yaml: input/output_cost_per_token: 0
# para `ollama-qwen3-4b`). Sin esta detección caían al `default` $5/$15 y falseaban
# el reporte de costos del piloto. Se identifican por el prefijo del provider Ollama,
# que es como el motor los nombra: `ollama-...` en el catálogo (model_name) y
# `ollama/` / `ollama_chat/` como litellm_provider. El `default` conservador de
# $5/$15 se mantiene INTACTO para modelos remotos desconocidos.
_LOCAL_MODEL_PREFIXES = ("ollama-", "ollama/", "ollama_chat/", "ollama:")
# El prefijo NO alcanza en una instalación white-label: el perfil de cliente nombra su
# modelo local `${TENANT_SLUG}-local` (deploy/clients/*/config.yaml.tmpl), o sea
# `camara-comercio-local` en el piloto — nada de "ollama" a la vista, justamente porque
# el nombre del motor no puede filtrarse al cliente. Sin este sufijo el panel de costos
# le cobraba $5/$15 por millón de tokens a un modelo que corre en SU hardware y no
# cuesta nada, y es la primera pantalla que mira el cliente.
_LOCAL_MODEL_SUFFIXES = ("-local",)
_LOCAL_MODEL_PRICING = {"input": Decimal("0"), "output": Decimal("0")}


def _is_local_model(model: str) -> bool:
    """True si el modelo es local/self-hosted (sin costo por token)."""
    if not model:
        return False
    nombre = model.strip().lower()
    return nombre.startswith(_LOCAL_MODEL_PREFIXES) or nombre.endswith(_LOCAL_MODEL_SUFFIXES)


def has_known_pricing(model: str) -> bool:
    """¿Este catálogo sabe cuánto cuesta el modelo, o caería en el `default` conservador?

    Lo necesita quien elige CON QUÉ nombre costear un pedido cuando tiene más de un
    candidato (spec 030 R7: el motor devuelve en `model` quién contestó de verdad, que tras
    un fallback es más honesto que el modelo pedido). El nombre del proveedor suele venir
    versionado —`gpt-4o-mini-2024-07-18`— y ese no está en la tabla: adoptarlo a ciegas
    haría caer el pedido en el `default` de $5/$15 y le cobraría al cliente treinta veces
    de más por un modelo económico. Con este predicado, el llamador se queda con el nombre
    del catálogo cuando el de la respuesta no es priceable.

    NO cambia ningún precio: solo responde si `calculate_cost` tiene una entrada propia
    para ese nombre (o si es local, que vale 0 por prefijo/sufijo).
    """
    return bool(model) and (_is_local_model(model) or model in MODEL_PRICING)


class BudgetService:
    @staticmethod
    def get_personal_budget(db: Session, user_id: str) -> Budget:
        if not user_id:
            return None
        return db.query(Budget).filter(Budget.user_id == user_id).first()

    @staticmethod
    def get_group_budget(db: Session, group_id: str) -> Budget:
        if not group_id:
            return None
        return db.query(Budget).filter(Budget.group_id == group_id).first()

    @staticmethod
    def get_applicable_budgets(db: Session, user_id: str = None, group_id: str = None) -> list:
        """
        Returns all budgets that apply to this request (personal and/or group).
        Both layers apply simultaneously — the request is blocked if ANY is exhausted.
        When the user has a personal budget, the group budget is ALSO checked (dual-layer).
        When the user has no personal budget, only the group budget applies.
        """
        budgets = []
        resolved_group_id = group_id

        if user_id:
            personal = BudgetService.get_personal_budget(db, user_id)
            if personal:
                budgets.append(personal)

            # Resolve group_id from the user record if not passed explicitly
            if not resolved_group_id:
                user_obj = db.query(User).filter(User.id == user_id).first()
                if user_obj and user_obj.group_id:
                    resolved_group_id = str(user_obj.group_id)

        if resolved_group_id:
            group_b = BudgetService.get_group_budget(db, resolved_group_id)
            if group_b and group_b not in budgets:
                budgets.append(group_b)

        return budgets

    @staticmethod
    def get_budget_by_owner(db: Session, user_id: str = None, group_id: str = None) -> Budget:
        """Legacy single-budget lookup — kept for backward compatibility."""
        budgets = BudgetService.get_applicable_budgets(db, user_id=user_id, group_id=group_id)
        return budgets[0] if budgets else None

    @staticmethod
    def get_user_budget(db: Session, user_id: str) -> Budget:
        return BudgetService.get_personal_budget(db, user_id)

    @staticmethod
    def _budget_has_credit(budget: "Budget") -> bool:
        return (
            budget.current_spend_usd < budget.max_spend_usd
            and budget.current_tokens < budget.max_tokens
        )

    @staticmethod
    def has_sufficient_budget(db: Session, user_id: str = None, group_id: str = None) -> bool:
        """
        Allow if AT LEAST ONE applicable budget has remaining credit (personal OR group).
        Sequential model: personal is charged first; group is the fallback layer.
        If no budget is configured, the request is allowed.
        """
        budgets = BudgetService.get_applicable_budgets(db, user_id=user_id, group_id=group_id)
        if not budgets:
            return True
        return any(BudgetService._budget_has_credit(b) for b in budgets)

    @staticmethod
    def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
        """
        Calculates the cost of a request based on the model and token counts.

        Devuelve el coste cuantizado a 8 decimales (issue #76): la escala de la columna que
        lo va a acumular. Un pedido barato de verdad vale ~1e-5 USD, así que truncar antes
        de esto es lo que dejaba el contador en cero.
        """
        if _is_local_model(model):
            pricing = _LOCAL_MODEL_PRICING
        else:
            pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
        input_cost = (Decimal(prompt_tokens) / Decimal("1000000")) * pricing["input"]
        output_cost = (Decimal(completion_tokens) / Decimal("1000000")) * pricing["output"]
        return cuantizar_usd(input_cost + output_cost)

    @staticmethod
    def update_budget(db: Session, user_id: str = None, group_id: str = None, prompt_tokens: int = 0, completion_tokens: int = 0, model: str = "", override_cost: Decimal = None) -> None:
        """
        Sequential deduction: personal budget is charged first; group budget is the fallback.
        Only one layer is charged per request — whichever has credit first (personal > group).
        """
        budgets = BudgetService.get_applicable_budgets(db, user_id=user_id, group_id=group_id)
        if not budgets:
            return
        cost = override_cost if override_cost is not None else BudgetService.calculate_cost(model, prompt_tokens, completion_tokens)
        # El coste de fuera (`override_cost`: el que calculó el motor contra la respuesta
        # real del proveedor, y que el plano interno reenvía como float) también se
        # cuantiza acá — es el único punto por el que pasan TODOS los caminos de carga, así
        # que es donde la escala tiene que quedar fijada una sola vez.
        cost = cuantizar_usd(cost)
        total_tokens = prompt_tokens + completion_tokens
        for budget in budgets:
            if BudgetService._budget_has_credit(budget):
                # `+=` sobre el Decimal de la columna: la suma es exacta y la escala la fija
                # `cuantizar_usd` (8 decimales = la de la columna tras la migración 014).
                # Con la escala vieja (10,4) esta línea sumaba 0.0000 en cada pedido barato.
                budget.current_spend_usd = cuantizar_usd(
                    Decimal(budget.current_spend_usd or 0) + cost)
                budget.current_tokens += total_tokens
                break  # charge the first budget with credit; personal exhausted → group kicks in
        db.commit()
