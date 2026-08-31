"""Políticas de contenido por palabra/frase (spec 036 US1/US2, sesión 11-ago-2026).

Contrato SIMPLE de propósito: nombre corto (`policy_id`), descripción, lista de
palabras/frases a bloquear, activo/inactivo. Todo lo demás (el motor de reglas en
sí, `litellm_content_filter`, la persistencia) vive en LiteLLM — este router es la
puerta de Sentinel hacia esa capacidad, no una reimplementación (ver
`services/ai_engine_client.py`, sección "Políticas de contenido", y
`specs/036-plantillas-politicas-cliente/spec.md`).

Deliberadamente SIN modelo propio en la base de Sentinel: LiteLLM ya persiste cada
política (su propia base, tabla de guardrails) y expone list/create/update/delete;
duplicar eso acá en una tabla espejo abriría la puerta a que las dos copias
diverjan (el mismo problema que ya resolvieron `region`/`nlp_fail_mode` para otro
caso: una sola fuente de verdad). Si más adelante hace falta auditoría propia de
"quién creó qué política y cuándo" del lado de Sentinel, es una ampliación de este
router, no un rediseño.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Literal, Optional

from ..auth.rbac import require_role
from ..services import ai_engine_client
from ..services.ai_engine_client import AIEngineClientError, ContentPolicyLostError

# Gate por endpoint, NO a nivel de router: la matriz canónica (spec 017, `auth/matrix.py`)
# le da al `compliance_officer` R —no W— sobre `compliance_config`, el grupo donde vive esta
# superficie. Un `dependencies=[...]` de router con ambos roles le abriría la escritura =
# over-permit (la misma divergencia que T006 cerró en retention/consent). Lectura =
# admin + compliance_officer; mutaciones = admin.
router = APIRouter(
    prefix="/content-policies",
    tags=["Content Policies"],
)

_LEE = Depends(require_role("admin", "compliance_officer"))
_ESCRIBE = Depends(require_role("admin"))

# Mismo criterio que el nombre de categoría de litellm_content_filter (PR #143,
# content_filter.py: `_load_categories`): solo alfanumérico/guion/guion bajo, para
# que el `policy_id` sea seguro como parte de un `guardrail_name`.
_POLICY_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


class BlockedWordSchema(BaseModel):
    keyword: str = Field(min_length=1, max_length=200)
    action: Literal["BLOCK", "MASK"] = "BLOCK"
    description: Optional[str] = None


# Plantilla YA ARMADA de litellm_content_filter — EU AI Act, Singapur MAS/PDPA, EAU, sesgo/
# daño genérico, etc. Referenciada por NOMBRE, resuelta por LiteLLM.
#
# HALLAZGO REAL (11-ago-2026, probado en vivo con Cristian): el catálogo de LiteLLM vive en
# DOS carpetas con reglas distintas, y `docs-referencia.md` las tenía mezcladas —
#   - `litellm_content_filter/categories/*.yaml` — bias_*, harmful_*, denied_*, claims_*,
#     prompt_injection_*, etc. SÍ se resuelven solo por nombre (`category`), sin
#     `category_file`.
#   - `litellm_content_filter/policy_templates/*.yaml` — TODAS las de EU AI Act, Singapur
#     MAS/PDPA y EAU. Estas NO se resuelven por nombre solo (`_load_categories` solo mira
#     `categories/`, nunca `policy_templates/`) — confirmado con curl directo: sin
#     `category_file` la política queda guardada pero vacía, sin bloquear nada, sin error
#     visible para el usuario. Necesitan `category_file` apuntando ahí explícitamente (el
#     frontend lo manda — ver `BUILT_IN_CATEGORIES` en `frontend/src/services/api.ts`).
# No se valida acá contra una lista cerrada — si el nombre/archivo no existe, LiteLLM lo
# ignora con un warning en su log, esta API no reimplementa ese catálogo.
class CategoryRefSchema(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    action: Literal["BLOCK", "MASK"] = "BLOCK"
    category_file: Optional[str] = None


class ContentPolicyCreateSchema(BaseModel):
    policy_id: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    blocked_words: List[BlockedWordSchema] = Field(default_factory=list)
    categories: List[CategoryRefSchema] = Field(default_factory=list)
    active: bool = False

    @field_validator("policy_id")
    @classmethod
    def _policy_id_seguro(cls, v: str) -> str:
        if not _POLICY_ID_RE.match(v):
            raise ValueError("policy_id solo puede tener letras, números, '_' y '-'")
        return v

    @model_validator(mode="after")
    def _al_menos_una_regla(self):
        # A NIVEL MODELO, no `field_validator("categories")`: un field validator NO corre
        # cuando el campo viene AUSENTE y toma su default, así que el guard sólo disparaba
        # con `categories: []` explícito — justo la forma que ningún cliente manda (Jeff,
        # 26-ago-2026, bloqueante #315: `update_content_policy` es borra+crea, así que un
        # PUT de sólo `description` pasaba este guard y borraba las reglas en silencio).
        if not self.categories and not self.blocked_words:
            raise ValueError("hace falta al menos una palabra propia o una plantilla ya armada")
        return self


class ContentPolicyUpdateSchema(BaseModel):
    description: str = Field(default="", max_length=500)
    blocked_words: List[BlockedWordSchema] = Field(default_factory=list)
    categories: List[CategoryRefSchema] = Field(default_factory=list)
    active: bool = False

    @model_validator(mode="after")
    def _al_menos_una_regla(self):
        if not self.categories and not self.blocked_words:
            raise ValueError("hace falta al menos una palabra propia o una plantilla ya armada")
        return self


def _palabras_a_dict(blocked_words: List[BlockedWordSchema]) -> list[dict]:
    return [w.model_dump(exclude_none=True) for w in blocked_words]


def _categorias_a_dict(categories: List[CategoryRefSchema]) -> list[dict]:
    return [c.model_dump(exclude_none=True) for c in categories]


@router.get("", dependencies=[_LEE])
async def list_content_policies():
    """Las políticas de contenido que existen hoy, con su estado real (activa o no)."""
    try:
        return await ai_engine_client.list_content_policies()
    except AIEngineClientError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("", status_code=201, dependencies=[_ESCRIBE])
async def create_content_policy(payload: ContentPolicyCreateSchema):
    """Crea una política nueva. Aplica al siguiente pedido si `active=true`, sin reiniciar
    nada. (Las categorías que se cargan por fichero en el motor sí requieren un reinicio;
    éstas no.)"""
    try:
        existentes = await ai_engine_client.list_content_policies()
    except AIEngineClientError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if any(p["policy_id"] == payload.policy_id for p in existentes):
        raise HTTPException(status_code=409,
                            detail=f"Ya existe una política con policy_id='{payload.policy_id}'.")
    try:
        return await ai_engine_client.create_content_policy(
            policy_id=payload.policy_id,
            description=payload.description,
            blocked_words=_palabras_a_dict(payload.blocked_words),
            categories=_categorias_a_dict(payload.categories),
            active=payload.active,
        )
    except AIEngineClientError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.put("/{policy_id}", dependencies=[_ESCRIBE])
async def update_content_policy(policy_id: str, payload: ContentPolicyUpdateSchema):
    """Actualiza (agregar/quitar palabras, activar/desactivar) una política existente."""
    try:
        existentes = await ai_engine_client.list_content_policies()
    except AIEngineClientError as e:
        raise HTTPException(status_code=502, detail=str(e))
    actual = next((p for p in existentes if p["policy_id"] == policy_id), None)
    if actual is None:
        raise HTTPException(status_code=404, detail=f"No existe la política '{policy_id}'.")
    try:
        return await ai_engine_client.update_content_policy(
            guardrail_id=actual["guardrail_id"],
            policy_id=policy_id,
            description=payload.description,
            blocked_words=_palabras_a_dict(payload.blocked_words),
            categories=_categorias_a_dict(payload.categories),
            active=payload.active,
        )
    # ORDEN LOAD-BEARING: `ContentPolicyLostError` es subclase de `AIEngineClientError`;
    # si este `except` va después, nunca entra y la compensación es código muerto.
    except ContentPolicyLostError as e:
        # El borrado ya se aplicó y la recreación falló ⇒ el motor quedó SIN la política.
        # En un firewall de compliance eso falla ABIERTO: el tráfico pasa sin el guard y
        # el 502 genérico se lee como «no pasó nada». Reponemos el estado anterior.
        try:
            await ai_engine_client.create_content_policy(
                policy_id=policy_id,
                description=actual["description"],
                blocked_words=actual["blocked_words"],
                categories=actual["categories"],
                active=actual["active"],
            )
        except AIEngineClientError as rollback_error:
            # Peor caso: la política NO existe en el motor y no la pudimos reponer. El
            # detalle tiene que decirlo con todas las letras — un 502 genérico acá manda
            # al admin a reintentar creyendo que su política sigue viva.
            raise HTTPException(
                status_code=500,
                detail=(f"La política '{policy_id}' quedó BORRADA en el motor: falló la "
                        f"actualización ({e}) y también el intento de reponerla "
                        f"({rollback_error}). El tráfico está pasando SIN este filtro — "
                        f"volvé a crearla antes de seguir."),
            ) from rollback_error
        raise HTTPException(
            status_code=502,
            detail=(f"No se pudo actualizar la política '{policy_id}' ({e}). No hubo "
                    f"cambios: se repuso la versión anterior."),
        ) from e
    except AIEngineClientError as e:
        # Falló el borrado ⇒ la política sigue INTACTA: no hay nada que compensar. Intentar
        # reponerla igual es un POST condenado (el motor tiene UNIQUE sobre `guardrail_name`,
        # medido) cuyo fallo habría que tragarse, y el admin terminaría con el mismo 502 en
        # las dos ramas sin saber si su política sobrevivió.
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/{policy_id}", status_code=204, dependencies=[_ESCRIBE])
async def delete_content_policy(policy_id: str):
    """Borra una política. El filtro deja de aplicarse desde el siguiente pedido, sin
    reiniciar nada. La acción no se puede deshacer: para desactivarla temporalmente
    conservando sus reglas, usá el `PUT` con `active=false`."""
    try:
        existentes = await ai_engine_client.list_content_policies()
    except AIEngineClientError as e:
        raise HTTPException(status_code=502, detail=str(e))
    actual = next((p for p in existentes if p["policy_id"] == policy_id), None)
    if actual is None:
        raise HTTPException(status_code=404, detail=f"No existe la política '{policy_id}'.")
    try:
        await ai_engine_client.delete_content_policy(actual["guardrail_id"])
    except AIEngineClientError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return None
