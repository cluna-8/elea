"""Cliente hacia el motor de análisis exacto de datos (DB-GPT, spec 048).

Contrato real descubierto en vivo (10-sep-2026, T074 — NO documentado por DB-GPT en ningún
lado oficial, ver `specs/048-motor-analisis-exacto-dbgpt/contracts/02-dbgpt-real-api.md`):

1. `POST /api/v1/resource/file/upload?chat_mode=chat_excel&conv_uid=<uuid>` (multipart,
   campo `doc_files`) → `{"data": {...}}`.
2. `POST /api/v1/chat/completions` (**v1**, no v2 — v2 no soporta `chat_mode=chat_excel`) con
   `select_param` = el objeto `data` del paso 1, VUELTO A SERIALIZAR a JSON string (pasar solo
   el `file_path` revienta con un `JSONDecodeError` del lado de DB-GPT — hallazgo real de esta
   sesión). Respuesta: streaming SSE, la ÚLTIMA línea trae el contenido final completo con el
   SQL ejecutado embebido en un tag `<chart-view content="...">`.

DB-GPT llama al motor interno de Eleia (LiteLLM) por su cuenta, con su propia llave de servicio
(`svc.dbgpt-excel`, `can_act_on_behalf=true`) — el motor NUNCA lo hace este backend (FR-004).
Limitación real, documentada honestamente (mismo criterio que CHANGELOG 044 §13 para el RAG de
AnythingLLM): DB-GPT no reenvía ningún header de "en nombre de quién" en esa llamada — no soporta
headers custom configurables en su cliente proxy/openai (a confirmar definitivamente contra su
código fuente si se necesita cerrar esto del todo; no es un bloqueo para el resto de esta spec).
El costo de esa llamada específica queda hoy atribuido a la llave de servicio en el motor, igual
que ya pasa con `svc.anythingllm-provider` — no es una regresión nueva, es el mismo patrón ya
aceptado. Lo que SÍ hace este servicio es registrar, del lado de Eleia, quién pidió qué (ver
`api/exact_analysis.py`), para que la app tenga trazabilidad aunque el motor no la tenga sola.
"""
import html
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger("sentinel-secure-gateway")

_BASE_URL = os.getenv("EXACT_ANALYSIS_ENGINE_URL", "http://exact-analysis-engine:5670")
_TIMEOUT = 90.0  # el motor puede tardar — real, no un mock; el modelo + la ejecución SQL
                 # pueden tomar varios segundos, visto en vivo (~15-20s con azure-gpt-4o-mini)

_CHART_VIEW_RE = re.compile(r'<chart-view content="(.*?)">', re.DOTALL)


class ExactAnalysisEngineError(Exception):
    """El motor de análisis exacto no respondió, o respondió con un error — el caller SIEMPRE
    lo traduce a un mensaje neutro (FR-009), nunca deja pasar esta excepción cruda al usuario."""


@dataclass
class ExactAnalysisAnswer:
    content: str
    sql_executed: Optional[str]
    model_used: str


async def upload_file(*, conv_uid: str, filename: str, content: bytes, content_type: str) -> dict:
    """Sube un archivo tabular ya enmascarado (US3, T090 — el enmascarado pasa ANTES de
    llegar acá, esta función no lo hace) y devuelve el objeto `data` crudo de DB-GPT, que hay
    que volver a pasar TAL CUAL a `ask_question` como `select_param`."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            r = await client.post(
                f"{_BASE_URL}/api/v1/resource/file/upload",
                params={"chat_mode": "chat_excel", "conv_uid": conv_uid},
                files={"doc_files": (filename, content, content_type)},
            )
            r.raise_for_status()
            body = r.json()
        except httpx.HTTPStatusError as e:
            logger.error("exact-analysis-engine upload %s: %s", e.response.status_code, e.response.text)
            raise ExactAnalysisEngineError("upload failed") from e
        except httpx.RequestError as e:
            logger.error("exact-analysis-engine unreachable (upload): %s", e)
            raise ExactAnalysisEngineError("engine unavailable") from e
    if not body.get("success"):
        raise ExactAnalysisEngineError(f"DB-GPT rejected the upload: {body.get('err_msg')}")
    return body["data"]


async def ask_question(*, conv_uid: str, question: str, model_name: str,
                       select_param: dict) -> ExactAnalysisAnswer:
    """`select_param` es el `data` DEVUELTO por `upload_file` — nunca un `file_path` pelado
    (ver docstring del módulo). Usa `/api/v1/chat/completions` (v1, `ConversationVo`), NUNCA
    v2 — v2 rechaza `chat_mode=chat_excel` con 400 `invalid_chat_mode` (confirmado en vivo)."""
    payload = {
        "model_name": model_name,
        "chat_mode": "chat_excel",
        "conv_uid": conv_uid,
        "select_param": json.dumps(select_param, ensure_ascii=False),
        "user_input": question,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            r = await client.post(f"{_BASE_URL}/api/v1/chat/completions", json=payload)
            r.raise_for_status()
            raw = r.text
        except httpx.HTTPStatusError as e:
            logger.error("exact-analysis-engine query %s: %s", e.response.status_code, e.response.text)
            raise ExactAnalysisEngineError("query failed") from e
        except httpx.RequestError as e:
            logger.error("exact-analysis-engine unreachable (query): %s", e)
            raise ExactAnalysisEngineError("engine unavailable") from e
    return _parse_streaming_response(raw, model_name)


def _parse_streaming_response(raw: str, model_name: str) -> ExactAnalysisAnswer:
    """El motor devuelve SSE (`data: {...}` por línea, contenido ACUMULADO no incremental) —
    la última línea con contenido real trae la respuesta final. Se extrae también el SQL
    ejecutado del tag `<chart-view content="...">` si está presente (R3 de research.md: es la
    única evidencia auditable de que el SQL fue de solo lectura, dado que DB-GPT lo ejecuta
    puertas adentro y este backend no puede interceptarlo directamente)."""
    last_content = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue
        choices = chunk.get("choices") or []
        if choices:
            content = choices[0].get("message", {}).get("content")
            if content:
                last_content = content
    if not last_content:
        raise ExactAnalysisEngineError("empty response from exact-analysis engine")

    sql_executed = None
    match = _CHART_VIEW_RE.search(last_content)
    if match:
        try:
            chart_json = json.loads(html.unescape(match.group(1)))
            sql_executed = chart_json.get("sql")
        except (json.JSONDecodeError, AttributeError):
            logger.warning("no se pudo parsear el <chart-view> de la respuesta (formato cambió?)")

    return ExactAnalysisAnswer(content=last_content, sql_executed=sql_executed, model_used=model_name)


def new_conv_uid() -> str:
    return str(uuid.uuid4())
