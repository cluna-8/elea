"""Alta y edición de la config SSO del tenant — API-first (spec 017 US2, T018).

Por qué existe: hasta ahora **nada** escribía `sso_providers` salvo los tests (cero
endpoints, cero scripts). La config del IdP se cargaba a mano en la base durante el
onboarding, que es justo lo que el nodo «el partner configura TODO solo» promete que
no hace falta. Es además el prerrequisito del E2E contra un tenant Entra real: sin
una fila, `/auth/sso/login` no tiene a dónde ir.

**API-first, no pantalla-first** (principio wizardable de JF): esto es un `PUT` que el
wizard de onboarding podrá disparar sin UI, y sobre el que la pantalla de admin se
apoyará después. La superficie es el contrato; la UI, un cliente más.

Tres decisiones que este módulo sostiene:

1. **El secreto ENTRA y no sale nunca.** El patrón `KeyGeneratedResponse` —mostrar el
   valor UNA vez porque el servidor lo generó y el usuario no lo tiene— no aplica acá:
   el `client_secret` lo genera Azure y el admin ya lo tiene en su custodia. Devolverlo
   sólo agregaría un lugar más del que puede filtrarse. Las respuestas informan
   `client_secret_configurado: bool`, nunca el valor.

2. **Si el cifrado no está disponible, esto corta — no persiste.** `encryption_service`
   se inicializa en el import con `FERNET_SECRET_KEY`; si falta o es inválida, `encrypt()`
   levanta `CifradoNoDisponible` (#283 — antes devolvía `None` sin levantar, y este módulo
   era el único de los tres callers que miraba ese `None`). Guardar esa fila daría un 200 al
   operador, un `client_secret_encrypted` NULL en la base y un canje de código contra
   el IdP con secreto vacío: el flujo se rompe lejos, en el navegador del cliente, y el
   síntoma no señala a esta llamada. Es la clase de defecto que sólo aparece en la sede.

3. **No se puede habilitar un proveedor que este build no implementa.** El
   `provider_type` se valida contra el registry (`get_provider`) antes de escribir: una
   fila `enabled` apuntando a un proveedor inexistente hace que `/login` degrade con un
   error que parece del IdP y es nuestro.

⚠ Límite conocido de `config` (gate de T018, P3): es un dict libre que se guarda EN CLARO y
   se devuelve entero en el GET —que el compliance_officer también lee—, así que un secreto
   tipeado ADENTRO de `config` en vez de en `client_secret` esquiva las tres decisiones de
   arriba. El campo lo advierte y el reparto de rol está medido, pero la advertencia no es un
   gate. El cierre real no es una blocklist de nombres de clave (frágil, y rechazaría claves
   legítimas): es tipar `config` por proveedor con `extra="forbid"`, decisión que corresponde
   a quien agregue el segundo proveedor y tenga los dos contratos delante. Queda en issue.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.rbac import require_role
from ..database import get_db
from ..licensing.entitlement import expected_tenant_id
from ..models.sso_provider import SSOProvider
from ..models.user import User
from ..services.auth_events import emit_auth_event
from ..services.encryption_service import CifradoNoDisponible, encrypt
from .registry import get_provider

logger = logging.getLogger("basa-secure-gateway.sso.admin")

# Tipo de evento local al módulo, siguiendo el precedente de `AUTH_SSO_DENIED` en
# `sso/api.py`: los event types propios del SSO viven junto a quien los emite.
AUTH_SSO_CONFIG_CHANGED = "auth_sso_config_changed"

router = APIRouter(prefix="/auth/sso/config", tags=["sso-admin"])

# El auditor LEE la config (qué IdP está cableado es material de auditoría); escribir es
# del admin. Mismo reparto que el resto de `config_producto` en la matriz 017.
_LECTURA = Depends(require_role("admin", "compliance_officer"))
_ESCRITURA = require_role("admin")


class SsoConfigIn(BaseModel):
    provider_type: str = Field(..., description="tipo registrado en el build (hoy: 'entra')")
    config: dict = Field(
        default_factory=dict,
        description="datos NO secretos del IdP: tenant_id, client_id, authority… "
                    "ACÁ NO VAN SECRETOS: este dict se guarda EN CLARO y se devuelve entero "
                    "en el GET, que el auditor también puede leer. El secreto va en "
                    "`client_secret`, que se cifra y no sale nunca.")
    client_secret: Optional[str] = Field(
        default=None,
        description="secreto del IdP. Omitirlo en una edición CONSERVA el guardado; "
                    "nunca se devuelve en ninguna respuesta.")
    enabled: bool = False


class SsoConfigOut(BaseModel):
    """Sin `client_secret`: no es un olvido, es el contrato (decisión 1 del módulo)."""
    provider_type: str
    config: dict
    enabled: bool
    client_secret_configurado: bool


def _a_salida(fila: SSOProvider) -> SsoConfigOut:
    return SsoConfigOut(
        provider_type=fila.provider_type,
        config=dict(fila.config or {}),
        enabled=bool(fila.enabled),
        client_secret_configurado=bool(fila.client_secret_encrypted),
    )


@router.get("", name="sso_config_get", response_model=SsoConfigOut,
            dependencies=[_LECTURA])
def leer_config(db: Session = Depends(get_db)) -> SsoConfigOut:
    """Config SSO del tenant del deployment. 404 si todavía no se cargó ninguna."""
    tenant_id = expected_tenant_id()
    fila = db.query(SSOProvider).filter(SSOProvider.tenant_id == tenant_id).first()
    if fila is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="sso_sin_configurar: este tenant todavía no tiene proveedor SSO cargado.",
        )
    return _a_salida(fila)


@router.put("", name="sso_config_put", response_model=SsoConfigOut)
def escribir_config(payload: SsoConfigIn, db: Session = Depends(get_db),
                    actor: User = Depends(_ESCRITURA)) -> SsoConfigOut:
    """Alta o edición de la config del tenant (upsert por tenant)."""
    try:
        get_provider(payload.provider_type)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"sso_proveedor_desconocido: este build no implementa "
                   f"'{payload.provider_type}'. Habilitarlo dejaría el login SSO roto.",
        )

    tenant_id = expected_tenant_id()
    fila = db.query(SSOProvider).filter(SSOProvider.tenant_id == tenant_id).first()

    # ── Se valida TODO antes de tocar la sesión ────────────────────────────────────
    # Mutar primero y validar después deja objetos pendientes en la sesión cuando el
    # camino de error levanta. Hoy no persistirían (`get_db` cierra y el close descarta
    # la transacción abierta), pero eso es una propiedad del wiring del framework, no
    # de este código: si un día la sesión se commitea en otro lado, una fila con el
    # secreto en NULL sería exactamente el estado que estos dos guards existen para
    # impedir. Con este orden, la pregunta no se puede llegar a hacer.
    if payload.client_secret is not None:
        # El valor vacío se ataja ACÁ y no más abajo: `encrypt()` lo trata como «no hay nada
        # que cifrar» y devuelve `None` sin levantar, así que sin este guard un campo en
        # blanco caería en el 503 y mandaría al admin a debuggear una infra que está sana.
        # Pasa en la sede del cliente, donde no hay nadie para aclarárselo. (Cuando este
        # guard se escribió, `encrypt()` además colapsaba el vacío con el sin-Fernet en el
        # mismo `None`; el #283 separó las dos causas en la raíz y este orden quedó igual.)
        if not payload.client_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sso_secreto_vacio: el secreto del IdP no puede ser una cadena vacía. "
                       "Para conservar el guardado, OMITÍ el campo; mandarlo en blanco no es "
                       "una forma de borrarlo.",
            )
        try:
            secreto_cifrado = encrypt(payload.client_secret)
        except CifradoNoDisponible:
            # Fail-closed y RUIDOSO: ver decisión 2 del módulo. Un 200 acá deja el
            # secreto en la nada y el síntoma aparece en el navegador del cliente.
            logger.error("sso: FERNET_SECRET_KEY ausente o inválida — no se persiste el secreto")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="sso_cifrado_no_disponible: el servicio de cifrado no está "
                       "configurado (FERNET_SECRET_KEY), así que el secreto NO se guardó. "
                       "La config quedó sin tocar.",
            )
    else:
        # Omitir el secreto en una edición CONSERVA el guardado; en un alta, queda sin él
        # (cargar los IDs primero y el secreto después es un flujo real de onboarding).
        secreto_cifrado = fila.client_secret_encrypted if fila is not None else None

    if payload.enabled and not secreto_cifrado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sso_habilitado_sin_secreto: no se puede habilitar el SSO sin el "
                   "secreto del IdP — el canje del código fallaría en el login.",
        )

    # ── Recién acá se escribe ──────────────────────────────────────────────────────
    if fila is None:
        fila = SSOProvider(tenant_id=tenant_id, provider_type=payload.provider_type)
        db.add(fila)
    fila.provider_type = payload.provider_type
    fila.config = dict(payload.config or {})
    fila.client_secret_encrypted = secreto_cifrado
    fila.enabled = payload.enabled

    emit_auth_event(db, AUTH_SSO_CONFIG_CHANGED, actor_user_id=str(actor.id),
                    tenant_id=tenant_id)
    db.commit()
    db.refresh(fila)
    return _a_salida(fila)
