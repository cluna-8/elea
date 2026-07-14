"""Superficie browser-DLP (spec 019 US3): endpoints que consume la extensión MV3.

La extensión ``Basa Guard`` (portada de ``basa-browser-dlp/``) hookea ``window.fetch``
en ChatGPT/Claude web y, por cada prompt, llama a estos endpoints del gateway:

- ``GET  /gw/whoami``  → valida la virtual key → identidad (login del popup). **Fail-closed**.
- ``POST /gw/inspect`` → enmascara el texto plano del usuario y devuelve los
  ``replacements`` (token→original) para que la extensión reescriba el body (el modelo
  ve placeholders) y des-enmascare en el DOM. Empuja al MISMO monitor (``surface="browser"``)
  y audita **metadata-only** (Constraint C1).

**Reuso (Principio VI):** identidad, monitor y audit se reusan del ``gateway`` (014);
el masking reusa la **misma** ``basa_guardian_policy`` que el resto (regex hoy; Presidio
real llega en 016). Así la extensión y las rutas base_url comparten una sola política.
"""
import time
from typing import Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from . import gateway  # reuse: _resolve_attribution (fail-closed check), _audit, _publish_monitor, policy

router = APIRouter(prefix="/gw", tags=["Browser-DLP (extensión MV3)"])


def _fail_closed():
    return JSONResponse(status_code=401,
                        content={"ok": False, "error": "API key requerida o inválida"})


@router.get("/whoami")
def gw_whoami(x_basa_key: Optional[str] = Header(None, alias="X-Basa-Key")):
    """Valida la key → identidad para el login del popup. Fail-closed (SC-005)."""
    ident = gateway._resolve_attribution(x_basa_key)
    if ident["api_key_id"] is None:
        return _fail_closed()
    return {
        "ok": True,
        "user": ident.get("client_username") or "—",
        "team": ident.get("group_name") or "—",
        "key_label": ident.get("key_label") or "—",
    }


@router.post("/inspect")
async def gw_inspect(request: Request, body: dict,
                     x_basa_key: Optional[str] = Header(None, alias="X-Basa-Key")):
    """Enmascara el texto plano de un prompt para la extensión browser-DLP.
    Fail-closed sin key válida → 401. Empuja al monitor (surface=browser) + audita."""
    start = time.time()
    ident = gateway._resolve_attribution(x_basa_key)
    if ident["api_key_id"] is None:
        return _fail_closed()

    # F7: coerción segura — un `text` no-string (int/list/None) NO debe crashear el
    # endpoint; se trata como vacío (200 con replacements=[]), nunca un 500.
    # F3: se enmascara el texto COMPLETO (sin cap). Truncar acá dejaba salir la PII del
    # tail SIN placeholder; el cap sólo aplica al preview del monitor (display), abajo.
    raw = body.get("text")
    text = raw if isinstance(raw, str) else ""
    tool = body.get("tool") or gateway.policy.detect_tool(request.headers.get("user-agent"))

    masked = text
    replacements: list = []
    entities: list = []
    if text.strip():
        pmap = gateway.policy.PlaceholderMap()
        masked = await gateway.policy.mask_text(text, gateway.policy.default_analyze, pmap)
        replacements = [{"token": ph, "original": orig} for ph, orig in pmap.ph_to_orig.items()]
        entities = gateway._entity_counts(pmap.ph_to_orig)

    latency = int((time.time() - start) * 1000)
    # Preview del monitor: SIEMPRE enmascarado + secretos scrubbeados (C1: la vitrina
    # jamás muestra PII cruda ni credenciales, ni siquiera efímera en Redis).
    preview = gateway.policy.redact_secrets(masked)[:gateway._DISPLAY_CAP]
    gateway._audit(ident, tool, 0, 0, "passed", entities, latency)
    gateway._publish_monitor(ident, tool, tool, "passed", entities, preview, surface="browser")

    return {
        "ok": True,
        "masked": masked,
        "replacements": replacements,
        "entities": entities,
        "user": ident.get("client_username") or "default",
        "team": ident.get("group_name") or "—",
    }
