"""Rutas del flujo SSO (spec 017 US2, FR-006/007/009/010/011).

``GET /api/v1/auth/sso/login`` → redirect al IdP · ``GET /api/v1/auth/sso/callback``
→ identidad verificada → JIT → **el MISMO JWT del login local**
(``create_session_token`` con tenant claim). Aguas abajo, cero bifurcación: nada
sabe si la sesión nació de una contraseña o de Entra.

**El gate va como dependency del router, no inline** (``require_sso_enabled``): con
``Depends`` corre ANTES de la validación de request, así una llamada con el flag
apagado devuelve 403 y no un 422 que tape el veredicto de licencia. Inline correría
después y filtraría la forma de la superficie. Primer consumidor real de
``feature_enabled`` (021) — el precedente de forma es
``licensing/degraded.require_not_hard_blocked``.

**Password login = fallback PERMANENTE (FR-009).** Todo fallo de este módulo —flag
apagado, tenant sin config, IdP caído, id_token inválido— degrada SÓLO el camino
SSO, con error claro + auth event. ``/users/login`` no se entera y sigue operando.

Concurrencia: el intercambio con el IdP es una llamada de red. Ninguna fase DB
retiene la conexión a través de ese await — cada una entra por
``run_in_threadpool`` (precedente ``api/users.login``; P1 #238).
"""
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from ..auth.session import ALGORITHM, _ensure_secret, create_session_token
from ..database import get_db
from ..licensing.entitlement import expected_tenant_id, get_state
from ..models.sso_provider import SSOProvider
from ..services.auth_events import emit_auth_event
from ..services.encryption_service import decrypt
from .jit import buscar_por_email, crear_jit, resolver_existente
from .registry import get_provider

logger = logging.getLogger("sentinel-secure-gateway.sso.api")

router = APIRouter(prefix="/auth/sso", tags=["sso"])

SSO_FLAG = "sso"

# Eventos de auth propios del camino SSO (mismo canal metadata-only de T011).
AUTH_SSO_LOGIN = "auth_sso_login"
AUTH_SSO_DENIED = "auth_sso_denied"

# El state/nonce viaja en una cookie firmada de vida corta en vez de en memoria del
# proceso: el callback puede caer en otro worker. 10 min cubre un login humano con
# MFA de por medio sin dejar una ventana de replay ancha.
_STATE_COOKIE = "sentinel_sso_state"
_STATE_TTL_MIN = 10
# Marca de propósito: este token NUNCA es una sesión. No lleva ``sub``, así que
# ``get_current_user`` lo descarta (session.py:97-99) aunque se lo presente como
# Bearer; el claim lo hace explícito además de implícito.
_STATE_PURPOSE = "sso_state"


def require_sso_enabled() -> None:
    """Gate de licencia del router (FR-010). Fail-closed: sin entitlement válido o
    sin el flag ``sso``, la superficie no opera.

    ``def`` (no ``async def``) a propósito: FastAPI la corre en el threadpool, así
    que la lectura del entitlement no puede bloquear el event loop.
    """
    state = get_state()
    token = state.token
    if token is None or not token.feature_enabled(SSO_FLAG):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="sso_no_licenciado: el acceso por SSO no está habilitado en esta licencia.",
        )


def _cookie_segura() -> bool:
    """``Secure`` en la cookie de state salvo que el deployment declare HTTP plano
    (dev). Default True: en duda, la cookie no viaja por texto claro."""
    return os.getenv("SENTINEL_SSO_COOKIE_INSECURE", "").lower() not in ("1", "true", "yes")


def _firmar_estado(state: str, nonce: str, provider_type: str) -> str:
    return jwt.encode(
        {
            "purpose": _STATE_PURPOSE,
            "state": state,
            "nonce": nonce,
            "provider_type": provider_type,
            "exp": datetime.utcnow() + timedelta(minutes=_STATE_TTL_MIN),
        },
        _ensure_secret(),
        algorithm=ALGORITHM,
    )


def _leer_estado(raw: Optional[str]) -> dict:
    """Valida la cookie de state. Cualquier defecto → 400: sin state verificado no
    hay defensa contra CSRF de login (un callback inyectado engancharía la sesión
    del atacante en el navegador de la víctima)."""
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sso_state_ausente: no hay flujo SSO en curso en este navegador.",
        )
    try:
        payload = jwt.decode(raw, _ensure_secret(), algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sso_state_invalido: el flujo SSO expiró o no es válido.",
        )
    if payload.get("purpose") != _STATE_PURPOSE:
        # Un token de otro propósito firmado con el mismo secreto no habilita este paso.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sso_state_invalido: el flujo SSO expiró o no es válido.",
        )
    return payload


def _redirect_uri(request: Request) -> str:
    """URI de callback que se registra en el IdP DEL cliente (operatoria de instalación).

    **Apunta al FRONTEND, no a este endpoint.** El IdP redirige un NAVEGADOR: si lo
    mandáramos acá, el usuario aterrizaría mirando el JSON de la sesión. El patrón es
    el de cualquier SPA con OIDC: el IdP devuelve el browser a la ruta del frontend,
    y el frontend cambia el `code` por la sesión llamando a ``/callback`` por fetch.
    Así el token viaja en el cuerpo de una respuesta y nunca por la URL (donde
    quedaría en el historial, en el Referer y en los logs del proxy).

    Es **obligatoria y explícita**: sin configurar, el flujo corta con un error claro.
    Derivarla del Host entrante la haría manipulable por encabezado, y caer en
    silencio a la URL de este endpoint daría un flujo que "funciona" en los tests y
    aterriza en una página de JSON en producción. OIDC exige además que el valor sea
    IDÉNTICO en authorize y en el intercambio: por eso lo lee un solo lugar.
    """
    override = os.getenv("SENTINEL_SSO_REDIRECT_URI")
    if not override:
        logger.error(
            "sso: SENTINEL_SSO_REDIRECT_URI no está configurada — es la URI del frontend "
            "registrada en el IdP del cliente; sin ella el flujo no puede iniciarse."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="sso_redirect_uri_no_configurado: falta la URI de retorno del SSO. "
                   "El acceso con usuario y contraseña sigue disponible.",
        )
    return override


def _cargar_config(db: Session, tenant_id: str) -> tuple:
    """Config SSO habilitada del tenant. Fase DB sync (threadpool).

    Devuelve ``(provider_type, config, client_secret)`` con el secreto YA descifrado
    — el descifrado es del consumidor, no del modelo (T013). El secreto no se loguea
    ni se devuelve al cliente en ningún camino.
    """
    if isinstance(tenant_id, str):
        tenant_id = uuid.UUID(tenant_id)
    fila = (
        db.query(SSOProvider)
        .filter(SSOProvider.tenant_id == tenant_id, SSOProvider.enabled.is_(True))
        .first()
    )
    if fila is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="sso_no_configurado: este tenant no tiene un proveedor SSO habilitado.",
        )
    return fila.provider_type, dict(fila.config or {}), decrypt(fila.client_secret_encrypted)


@router.get("/available", name="sso_available")
async def sso_available(db: Session = Depends(get_db)):
    """¿La pantalla de login debe mostrar el botón de SSO? (FR-010)

    Discovery pre-auth: la pantalla de login no tiene sesión todavía, así que no
    puede consultar la licencia por ningún camino autenticado. Vive DENTRO del router
    gateado a propósito: con el flag apagado devuelve 403 igual que el resto, y el
    frontend oculta el botón — no se agrega una superficie nueva sin gate sólo para
    contestar esta pregunta.

    Devuelve el ``provider_type`` y NADA más: ni ``config`` ni el secreto. Un
    ``client_id`` o el directory ID del IdP en una respuesta pre-auth es información
    del cliente que no hace falta para dibujar un botón.
    """
    tenant_id = expected_tenant_id()
    try:
        provider_type, _config, _secret = await run_in_threadpool(_cargar_config, db, tenant_id)
    except HTTPException:
        # Licenciado pero sin proveedor habilitado: la respuesta es "no hay botón",
        # no un 404 que el frontend tendría que interpretar como error.
        return {"enabled": False, "provider_type": None}
    return {"enabled": True, "provider_type": provider_type}


@router.get("/login", name="sso_login")
async def sso_login(request: Request, db: Session = Depends(get_db)):
    """Arranca el flujo: config del tenant → ``authorize_url`` → 302 al IdP."""
    tenant_id = expected_tenant_id()
    provider_type, config, _secret = await run_in_threadpool(_cargar_config, db, tenant_id)

    try:
        provider = get_provider(provider_type)
    except KeyError:
        # Config apunta a un proveedor que este build no implementa: degradar el
        # camino SSO con error claro, jamás 500.
        logger.warning("sso login: provider_type desconocido '%s' (tenant=%s)", provider_type, tenant_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"sso_proveedor_desconocido: '{provider_type}' no está soportado en esta versión.",
        )

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    redirect_uri = _redirect_uri(request)

    try:
        destino = await run_in_threadpool(
            provider.authorize_url, config, state, nonce=nonce, redirect_uri=redirect_uri
        )
    except Exception as exc:
        # Discovery caído / config rota. FR-009: degrada SÓLO SSO.
        logger.warning("sso login: no se pudo construir authorize_url (tenant=%s): %s", tenant_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="sso_idp_inaccesible: no se pudo iniciar el flujo con el proveedor. "
                   "El acceso con usuario y contraseña sigue disponible.",
        )

    respuesta = RedirectResponse(url=destino, status_code=status.HTTP_302_FOUND)
    respuesta.set_cookie(
        _STATE_COOKIE,
        _firmar_estado(state, nonce, provider_type),
        max_age=_STATE_TTL_MIN * 60,
        httponly=True,
        secure=_cookie_segura(),
        samesite="lax",  # el IdP nos devuelve por redirect GET de otro sitio
        path="/api/v1/auth/sso",
    )
    return respuesta


@router.get("/callback", name="sso_callback")
async def sso_callback(
    request: Request,
    response: Response,
    state: str = "",
    code: str = "",
    db: Session = Depends(get_db),
):
    """Cierra el flujo: valida state → ``exchange_code`` → JIT → sesión."""
    tenant_id = expected_tenant_id()
    esperado = _leer_estado(request.cookies.get(_STATE_COOKIE))

    # CSRF de login: el state que vuelve del IdP debe ser EL que emitimos.
    # ``compare_digest`` para no filtrar el prefijo válido por tiempo.
    if not state or not secrets.compare_digest(state, esperado.get("state", "")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sso_state_invalido: el flujo SSO expiró o no es válido.",
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sso_code_ausente: el proveedor no devolvió un código de autorización.",
        )

    provider_type, config, secret = await run_in_threadpool(_cargar_config, db, tenant_id)
    if provider_type != esperado.get("provider_type"):
        # La config del tenant cambió entre login y callback: no completamos un
        # intercambio contra un proveedor distinto del que originó el state.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sso_state_invalido: el flujo SSO expiró o no es válido.",
        )
    if secret is not None:
        config = {**config, "client_secret": secret}

    try:
        provider = get_provider(provider_type)
        identidad = await run_in_threadpool(
            provider.exchange_code,
            config,
            code,
            nonce=esperado.get("nonce", ""),
            redirect_uri=_redirect_uri(request),
        )
    except HTTPException:
        raise
    except Exception as exc:
        # id_token con firma/iss/aud/nonce inválidos, o IdP inaccesible. El detalle
        # técnico va a logs server-side; al cliente sólo el veredicto (el texto de la
        # excepción puede citar config del IdP).
        logger.warning("sso callback: intercambio rechazado (tenant=%s): %s", tenant_id, exc)
        await run_in_threadpool(_auditar_denegado, db, tenant_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="sso_identidad_no_verificada: el proveedor no devolvió una identidad válida. "
                   "El acceso con usuario y contraseña sigue disponible.",
        )

    email = (identidad.get("email") or "").strip().lower()
    if not email:
        # Sin email no hay clave de matching (FR-008): no inventamos una.
        logger.warning("sso callback: identidad sin email (tenant=%s)", tenant_id)
        await run_in_threadpool(_auditar_denegado, db, tenant_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="sso_identidad_sin_email: el proveedor no devolvió un email verificable.",
        )

    usuario = await _resolver_identidad(db, email, identidad.get("display_name") or "", tenant_id)

    token = create_session_token(
        str(usuario["id"]), usuario["role"], usuario["username"], str(usuario["tenant_id"])
    )
    salida = {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(usuario["id"]),
            "username": usuario["username"],
            "role": usuario["role"],
            "display_label": usuario["display_label"],
            "email": usuario["email"],
        },
    }
    response.delete_cookie(_STATE_COOKIE, path="/api/v1/auth/sso")
    return salida


def _auditar_denegado(db, tenant_id) -> None:
    """Auth event del rechazo (FR-009: ambos caminos auditan). Metadata-only: NO
    lleva el email —es PII y este canal es el mismo que audita PII."""
    try:
        emit_auth_event(db, AUTH_SSO_DENIED, tenant_id=tenant_id)
        db.commit()
    except Exception:  # pragma: no cover — auditar no puede tumbar el rechazo
        db.rollback()
        logger.exception("sso: no se pudo auditar el rechazo")


def _resolver_jit_sync(db, email: str, display_name: str, tenant_id) -> dict:
    """Fase DB del JIT, en UNA transacción. Devuelve un snapshot plano: la fila ORM
    no sobrevive al cierre de la sesión y el caller sólo necesita los datos."""
    existente = buscar_por_email(db, email, tenant_id)
    if existente is not None:
        usuario = resolver_existente(db, existente)
        nuevo = False
    else:
        usuario = crear_jit(db, email=email, display_name=display_name, tenant_id=tenant_id)
        nuevo = True

    emit_auth_event(
        db, AUTH_SSO_LOGIN, target_user_id=str(usuario.id),
        new_role=usuario.role if nuevo else None, tenant_id=tenant_id,
    )
    snapshot = {
        "id": usuario.id, "username": usuario.username, "email": usuario.email,
        "role": usuario.role, "display_label": usuario.display_label,
        "tenant_id": usuario.tenant_id, "nuevo": nuevo,
    }
    db.commit()
    return snapshot


async def _resolver_identidad(db, email: str, display_name: str, tenant_id) -> dict:
    """JIT + provisioning en el motor, sin retener la conexión en el await de red."""
    try:
        snapshot = await run_in_threadpool(_resolver_jit_sync, db, email, display_name, tenant_id)
    except HTTPException:
        await run_in_threadpool(_auditar_denegado, db, tenant_id)
        raise

    if snapshot["nuevo"]:
        # Mismo camino de alta que la UI: la identidad se provisiona en el motor.
        # Un fallo acá NO deshace el User (a diferencia del alta por UI): la sesión
        # ya es legítima y el reintento es idempotente por email. Queda logueado.
        from ..services import ai_engine_client
        from ..services.ai_engine_client import AIEngineClientError
        try:
            engine_user_id = await ai_engine_client.create_user(user_id=email)
            await run_in_threadpool(_persistir_engine_id, db, snapshot["id"], engine_user_id)
        except AIEngineClientError as exc:
            logger.warning(
                "sso jit: motor inaccesible al provisionar (user=%s): %s — la sesión se emite igual",
                snapshot["id"], exc,
            )
    return snapshot


def _persistir_engine_id(db, user_id, engine_user_id: str) -> None:
    from ..models.user import User
    fila = db.query(User).filter(User.id == user_id).first()
    if fila is not None:
        fila.engine_user_id = engine_user_id
        db.commit()
