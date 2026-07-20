"""BasaGuardrail — la política Basa como CustomGuardrail nativo (spec 014 US1).

Tres hooks sobre el pipeline del motor (firmas confirmadas contra litellm 1.92.0,
research T005 — corren también sobre ``/v1/messages`` con ``call_type=
"anthropic_messages"``):

1. ``async_pre_call_hook``: AI-Act Art.5 → 400; secretos → block; PII → mask
   reversible (el upstream solo ve placeholders).
2. ``async_post_call_success_hook``: unmask de la respuesta no-streaming.
3. ``async_post_call_streaming_iterator_hook``: **Estrategia A′** (decisión T005) —
   el punto de extensión es nativo, y como en ``/v1/messages`` los chunks son frames
   SSE Anthropic crudos (bytes), DENTRO del hook se aplica el rewrite SSE de la
   librería compartida (carry-split). No se reimplementa transporte: el motor sigue
   siendo dueño del HTTP/SSE framing hacia el cliente, auth, usage y retries.

Rutas bridged (modelos no-Claude): el round-trip completo lo cierra la spec 024 —
respuesta dict en el hook 2 (``unmask_response_payload``) y carry de ``[`` pelado en
la lib compartida (deltas de 1-3 chars del bridge partían el placeholder tras el
``[``; research 024 T002).
LÍMITE VIGENTE: ``/v1/responses`` NO está en ``_TEXT_CALL_TYPES`` → esa ruta corre SIN
política (solo identidad de custom_auth) — no ofrecer superficies sobre ella (issue #28).

El mapa reversible viaja en ``litellm_metadata`` (ruta anthropic — el motor filtra
``metadata`` a los campos válidos de la API de Anthropic ANTES del upstream, así que
el mapa no puede fugar; verificado en ``validate_anthropic_api_metadata``) o en
``metadata`` (rutas openai, que el motor no reenvía). JAMÁS se persiste (C1): el
audit logger lo scrubbea explícitamente.

GOTCHAS aplicados (research T005): NO definir ``apply_guardrail`` (redirigiría todo
al unified_guardrail); el override del streaming hook debe estar en ESTA clase hoja.
"""
import codecs
import logging
import os
import sys
from typing import Any, AsyncGenerator, Optional

from litellm.integrations.custom_guardrail import CustomGuardrail

sys.path.insert(0, os.path.dirname(__file__))
import basa_guardian_policy as policy  # noqa: E402

logger = logging.getLogger("basa-guardrail")

# call_types con body de mensajes que esta política inspecciona/enmascara
_TEXT_CALL_TYPES = {"completion", "acompletion", "atext_completion", "anthropic_messages"}

# spec 016: motor de detección NLP real. Sin esta env var, el guardrail degrada a
# `default_analyze` (regex) — modo dev/demo EXPLÍCITO, nunca el default de prod
# (Constraint SC-2). Se lee una vez al importar el módulo (mismo proceso que la
# imagen pinneada del motor).
_PRESIDIO_URL = os.environ.get("PRESIDIO_ANALYZER_URL")


def _metadata_home(data: dict, call_type: Optional[str] = None) -> dict:
    """Dónde viven los campos litellm-specific según la ruta (research T005):
    ``litellm_metadata`` en la ruta anthropic (``metadata`` ahí es un campo del body
    de la API de Anthropic), ``metadata`` en el resto."""
    key = "litellm_metadata" if call_type == "anthropic_messages" or "litellm_metadata" in data else "metadata"
    home = data.get(key)
    if not isinstance(home, dict):
        home = {}
        data[key] = home
    return home


def _pii_tokens_from(data: dict) -> dict:
    for key in ("litellm_metadata", "metadata"):
        home = data.get(key)
        if isinstance(home, dict) and isinstance(home.get("pii_tokens"), dict):
            return home["pii_tokens"]
    return {}


def _basa_identity(user_api_key_dict) -> dict:
    md = getattr(user_api_key_dict, "metadata", None) or {}
    return md.get("basa") or {}


def _nlp_unavailable_block(home: dict) -> str:
    """Motivo de bloqueo fail-closed (FR-004) cuando el motor NLP no responde —
    reusado tanto en el preview de BLOCK como en el masking real."""
    home["basa_compliance"] = {
        "status": "blocked_nlp_unavailable", "risk_level": "unknown",
        "reason": "nlp_unavailable",
    }
    return ("Petición bloqueada: el motor de detección de datos personales "
            "no está disponible. No se procesa sin garantía de protección de PII/PHI.")


class BasaGuardrail(CustomGuardrail):
    """La política de compliance de Basa Guardian, montada en el motor."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        if call_type not in _TEXT_CALL_TYPES:
            return None

        identity = _basa_identity(user_api_key_dict)
        inspect_text = policy.extract_inspect_text(data)

        # 1) Enforcement duro: AI-Act Art.5 (400) — real hoy, nivel 1 de [D3]
        verdict = policy.evaluate_ai_act(inspect_text)
        home = _metadata_home(data, call_type)
        home["basa_compliance"] = verdict
        if verdict["status"] == "blocked_prohibited":
            return verdict["reason"]  # str → HTTPException 400 (contrato del hook)

        # 2) Secretos/keys: jamás salen hacia un LLM
        secrets = policy.detect_secrets(inspect_text)
        if secrets:
            return (f"Petición bloqueada: material secreto detectado ({', '.join(secrets)}). "
                    "Las credenciales nunca deben enviarse a un modelo.")

        # 3) Mask PII reversible — toggle por Connection (NULL=heredar → True hoy)
        if identity.get("redact_enabled", True):
            custom_names = identity.get("custom_names") or []

            # Región de patrones estructurados (spec 016, corrección post-review: el
            # despliegue objetivo es Europa, con LATAM como roadmap posterior — ver
            # STRUCTURED_ID_PATTERNS_BY_REGION). Hardcodeado por ahora; llevarlo a un
            # campo por tenant es extensión natural cuando haya despliegues multi-región
            # reales (no antes — YAGNI mientras solo exista Europa).
            region = os.environ.get("BASA_ENTITY_REGION", policy.DEFAULT_REGION)

            if _PRESIDIO_URL:
                async def _analyze(text: str) -> list:
                    return await policy.presidio_analyze(text, _PRESIDIO_URL, custom_names, region)
            else:
                logger.warning(
                    "PRESIDIO_ANALYZER_URL no configurada — usando detección regex de "
                    "dev/demo (Constraint SC-2: NO usar en producción con PHI)."
                )
                _analyze = policy.default_analyze

            # 3a) Preview de entidades sobre el texto completo (misma fuente que ya
            # usan AI-Act/secretos): decide MASK vs BLOCK por tipo ANTES de tocar el
            # body — evita enmascarar parcialmente una request que después se
            # bloquea, y evita una segunda ronda de red si hay que bloquear (spec
            # 016 US2, FR-005/FR-006).
            entity_configs = identity.get("entity_configs") or {}
            try:
                preview_entities = await _analyze(inspect_text)
            except policy.NlpUnavailableError:
                return _nlp_unavailable_block(home)

            blocked_types = sorted({
                e["entity_type"] for e in preview_entities
                if policy.resolve_entity_action(e["entity_type"], entity_configs) == "BLOCK"
            })
            if blocked_types:
                home["basa_compliance"] = {
                    "status": "blocked_entity_type", "risk_level": "high",
                    "reason": f"tipos bloqueados por política: {', '.join(blocked_types)}",
                }
                return (f"Petición bloqueada: se detectaron datos personales cuya política "
                        f"exige bloquear, no enmascarar ({', '.join(blocked_types)}).")

            # 3b) Sin bloqueos → enmascarar reversible las entidades restantes (MASK).
            try:
                data, ph_to_orig = await policy.mask_body(data, _analyze)
            except policy.NlpUnavailableError:
                # Fail-closed (FR-004): sin detección NLP confiable, no hay garantía
                # de protección — se rechaza la request en vez de degradar en silencio.
                return _nlp_unavailable_block(home)

            if ph_to_orig:
                home["pii_tokens"] = ph_to_orig
                home["basa_masked_entities"] = _entity_counts(ph_to_orig)

        return data

    async def async_post_call_success_hook(self, data: dict, user_api_key_dict, response):
        ph_to_orig = _pii_tokens_from(data)
        if not ph_to_orig:
            return response
        _unmask_response_inplace(response, ph_to_orig)
        return response

    async def async_post_call_streaming_iterator_hook(
        self, user_api_key_dict, response: Any, request_data: dict
    ) -> AsyncGenerator[Any, None]:
        ph_to_orig = _pii_tokens_from(request_data)
        if not ph_to_orig:
            async for item in response:
                yield item
            return

        # Estrategia A′: los chunks de /v1/messages son frames SSE crudos (bytes/str).
        # Decoder UTF-8 incremental (un multibyte puede venir partido entre chunks) +
        # buffer de frames (un evento SSE puede venir partido) + carry-split compartido.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""      # texto acumulado hasta el próximo límite de evento (\n\n)
        carry = ""       # fragmento de placeholder retenido entre deltas
        carry_field: Optional[str] = None

        async for item in response:
            if isinstance(item, bytes):
                buffer += decoder.decode(item)
            elif isinstance(item, str):
                buffer += item
            else:
                # Objeto ya parseado (otra ruta/versión): se entrega tal cual
                yield item
                continue

            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                if not block.strip():
                    continue
                out_blocks, carry, carry_field, _, _ = policy.rewrite_sse_block(
                    block, carry, carry_field, ph_to_orig
                )
                for ob in out_blocks:
                    yield (ob + "\n\n").encode("utf-8")

        # Fin del stream: procesar resto + flush del carry (stream truncado — 0 texto perdido)
        buffer += decoder.decode(b"", final=True)
        if buffer.strip():
            out_blocks, carry, carry_field, _, _ = policy.rewrite_sse_block(
                buffer, carry, carry_field, ph_to_orig
            )
            for ob in out_blocks:
                yield (ob + "\n\n").encode("utf-8")
        if carry:
            # Framed (review 024): un flush crudo lo descarta el parser SSE del cliente.
            yield policy.flush_carry_sse_block(carry, carry_field, ph_to_orig).encode("utf-8")


def _entity_counts(ph_to_orig: dict) -> list:
    counts: dict = {}
    for ph in ph_to_orig:
        m = policy.PH_TYPE_RE.match(ph)
        etype = m.group(1) if m else "PII"
        counts[etype] = counts.get(etype, 0) + 1
    return [{"type": t, "count": c} for t, c in counts.items()]


def _unmask_response_inplace(response, ph_to_orig: dict) -> None:
    """Des-enmascara una respuesta no-streaming (dict bridged u objeto), mutándola.
    La lógica vive en la lib compartida (testeable desde la suite del backend) — 024."""
    policy.unmask_response_payload(response, ph_to_orig)
