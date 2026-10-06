"""Prueba de fidelidad de un destino (FR-031; T111).

Reproduce un corpus de conversaciones **sintéticas** con la forma de pedido de cada herramienta
(`fidelity_corpus/<herramienta>.json`) contra un destino, por la cara de esa herramienta, y
devuelve un informe por capacidad: conversación, herramientas, streaming largo, errores y
contexto. Garantías:

- sin datos reales: `run` no recibe contenido; los cuerpos salen solo del corpus (el relleno del
  caso de contexto es texto fijo generado aquí);
- solo destinos del catálogo del tenant, con la postura de residencia de quien la lanza
  (`ensure_allowed`, la misma `check_target` del plano de datos);
- presupuesto propio (`Budget`): no descuenta de ninguna llave ni usuario, y al agotarse el
  informe queda `incompleto` en vez de apto;
- veredicto `apto` si ≥95 % de los casos pasan y NINGUNO falla en silencio (200 que no cumple lo
  pedido: vacío, sin llamada a herramienta, sin el dato del contexto, o un éxito donde debía haber
  error). Un fallo visible (HTTP de error) cuenta como falla, pero no es silencioso.

El envío es inyectable (`send`); `engine_sender` es el real: firma la autorización interna igual
que el plugin y llama al motor, que es quien tiene el acceso de salida al destino.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

from . import credentials, resolver
from .kits import TOOL_FACE, TOOLS  # noqa: F401 — TOOLS se re-exporta
from .residency import Posture
from .scopes import RequestScope

logger = logging.getLogger("sentinel.redirect.fidelity")

CAPABILITIES = ("conversation", "tools", "long_stream", "errors", "context")
CORPUS_DIR = Path(__file__).with_name("fidelity_corpus")
PASS_THRESHOLD = 0.95
DEFAULT_BUDGET_USD = Decimal("0.50")
CASE_TIMEOUT_S = 120
MAX_FILL_CHARS = 40_000
CHARS_PER_TOKEN = 3
ALLOWED_BODY_KEYS = frozenset({
    "model", "messages", "system", "max_tokens", "max_completion_tokens", "max_output_tokens",
    "stream", "tools", "tool_choice", "input", "instructions", "temperature", "stop"})
_FILLER = ("La revisión del módulo de ejemplo no encontró incidencias relevantes en esta iteración. ")


class FidelityRefused(Exception):
    def __init__(self, code: str, message: Optional[str] = None):
        super().__init__(message or code)
        self.code, self.message = code, message or code


@dataclass(frozen=True)
class Corpus:
    version: str
    synthetic: bool
    tool: str
    cases: list = field(default_factory=list)


@dataclass
class Outcome:
    status: int = 200
    text: str = ""
    tool_calls: list = field(default_factory=list)
    events: int = 0
    finished: bool = True
    error_class: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


class Budget:
    """Presupuesto de la prueba, propio: se agota con lo que gasta ella y con nada más."""

    def __init__(self, limit: Decimal):
        self.limit, self.spent = Decimal(limit), Decimal(0)

    @classmethod
    def from_env(cls) -> "Budget":
        try:
            limit = Decimal(os.environ.get("REDIRECT_FIDELITY_BUDGET_USD", ""))
            if limit <= 0:
                raise InvalidOperation
        except InvalidOperation:
            limit = DEFAULT_BUDGET_USD
        return cls(limit)

    @property
    def remaining(self) -> Decimal:
        return max(self.limit - self.spent, Decimal(0))

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.limit

    def charge(self, cost: Decimal) -> None:
        self.spent += Decimal(cost)


# ── corpus ──────────────────────────────────────────────────────────────────────────

def face_for_tool(tool: str) -> str:
    if tool not in TOOL_FACE:
        raise FidelityRefused("unknown_tool", f"herramienta desconocida: {tool}")
    return TOOL_FACE[tool]


def load_corpus(tool: str) -> Corpus:
    face_for_tool(tool)
    doc = json.loads((CORPUS_DIR / f"{tool}.json").read_text(encoding="utf-8"))
    return Corpus(version=str(doc["corpus_version"]), synthetic=bool(doc.get("synthetic")),
                  tool=tool, cases=list(doc["cases"]))


def _context_text(case: Mapping[str, Any], window: Optional[int]) -> str:
    target = int((window or 8000) * float(case.get("fill_ratio", 0.5)) * CHARS_PER_TOKEN)
    target = max(2000, min(target, MAX_FILL_CHARS))
    filler = (_FILLER * (target // len(_FILLER) + 1))[:target]
    cut = int(len(filler) * 0.4)
    return f"{filler[:cut]}\nEl código de verificación es {case['needle']}.\n{filler[cut:]}"


def _fill(node: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(node, str):
        for key, value in replacements.items():
            node = node.replace(key, value)
        return node
    if isinstance(node, list):
        return [_fill(v, replacements) for v in node]
    if isinstance(node, dict):
        return {k: _fill(v, replacements) for k, v in node.items()}
    return node


def build_body(case: Mapping[str, Any], destination: Mapping[str, Any]) -> dict:
    body = copy.deepcopy(case["request"])
    if case.get("needle"):
        body = _fill(body, {"{{CONTEXT}}": _context_text(case, destination.get("context_window"))})
    body["model"] = destination.get("real_model")
    return body


# ── destino permitido ───────────────────────────────────────────────────────────────

def ensure_allowed(destination_id: str, destinations: Mapping[str, Mapping[str, Any]], *,
                   offers: Iterable[Mapping[str, Any]], scope: RequestScope,
                   posture: Posture) -> dict:
    """El destino tiene que ser elegible para quien lanza la prueba, igual que en el tráfico:
    del catálogo del tenant (propio u ofrecido), activo, con credencial y dentro de su postura."""
    reason, _ = resolver.check_target(destinations.get(str(destination_id)), list(offers), scope, posture)
    if reason is not None:
        raise FidelityRefused(reason, f"destino no permitido para la prueba: {reason}")
    return dict(destinations[str(destination_id)])


# ── evaluación ──────────────────────────────────────────────────────────────────────

def evaluate(case: Mapping[str, Any], out: Outcome) -> tuple:
    """→ (pasó, detail_code, silencioso)."""
    cap, expect = case["capability"], case.get("expect") or {}
    if cap == "errors":
        if out.status < 400:
            return False, "no_error", True                  # aceptó lo inválido
        wanted = expect.get("error_class")
        if not out.error_class or (wanted and out.error_class not in wanted):
            return False, "unclassified_error", False
        return True, "ok", False
    if out.status >= 400:
        return False, f"http_{out.status}", False
    if not out.finished:
        return False, "no_finish", False
    if cap == "tools":
        if expect.get("tool") not in {c.get("name") for c in out.tool_calls}:
            return False, "no_tool_call", True
        return True, "ok", False
    if not out.text.strip():
        return False, "empty_response", True
    if cap == "long_stream" and (out.events < expect.get("min_events", 1)
                                 or len(out.text) < expect.get("min_chars", 1)):
        return False, "stream_too_short", True
    if cap == "context" and case["needle"] not in out.text:
        return False, "needle_missing", True
    return True, "ok", False


def _verdict(results: list, complete: bool) -> tuple:
    rate = sum(1 for r in results if r["passed"]) / len(results) if results else 0.0
    if not complete:
        return "incompleto", rate
    silent = any(r["silent"] for r in results)
    return ("apto" if rate >= PASS_THRESHOLD and not silent else "no_apto"), rate


def regressions(previous: Iterable[Mapping[str, Any]], current: Iterable[Mapping[str, Any]]) -> list:
    """Casos que pasaban en la corrida anterior y ahora no (US5, escenario 4). Lo que no corrió
    por presupuesto no cuenta: no es una regresión, es un hueco del informe."""
    before = {r["name"] for r in previous if r.get("passed")}
    return [{"capability": r["capability"], "name": r["name"], "detail_code": r["detail_code"]}
            for r in current if r["name"] in before and not r["passed"]
            and r["detail_code"] != "budget_exhausted"]


# ── ejecución ───────────────────────────────────────────────────────────────────────

Sender = Callable[[Mapping[str, Any], dict], Awaitable[Outcome]]


async def run(destination: Mapping[str, Any], face: str, tool: str, *, send: Sender,
              price: Callable[[str, int, int], Decimal], budget: Budget, tenant_id: str,
              tool_version: Optional[str] = None, run_by: Optional[str] = None,
              corpus: Optional[Corpus] = None) -> dict:
    corpus = corpus or load_corpus(tool)
    results, cost, complete = [], Decimal(0), True
    for case in corpus.cases:
        item = {"capability": case["capability"], "name": case["name"], "passed": False,
                "detail_code": "", "silent": False}
        if budget.exhausted:
            item["detail_code"] = "budget_exhausted"
            complete = False
        else:
            try:
                out = await asyncio.wait_for(send(case, build_body(case, destination)), CASE_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001 — un caso caído es un resultado, no un crash
                logger.info("fidelidad: %s/%s falló al enviar: %s", tool, case["name"], type(exc).__name__)
                item["detail_code"] = "send_failed"
            else:
                spent = price(destination["real_model"], out.prompt_tokens, out.completion_tokens)
                budget.charge(spent)
                cost += spent
                item["passed"], item["detail_code"], item["silent"] = evaluate(case, out)
        results.append(item)
    verdict, rate = _verdict(results, complete)
    return {"tenant_id": tenant_id, "destination_id": str(destination["id"]), "face": face, "tool": tool,
            "tool_version": tool_version, "corpus_version": corpus.version, "results": results,
            "verdict": verdict, "complete": complete, "pass_rate": round(rate, 4),
            "cost": float(cost.quantize(Decimal("0.00000001"))), "run_by": run_by,
            "run_at": datetime.now(timezone.utc).isoformat()}


# ── envío real al motor ─────────────────────────────────────────────────────────────

_CLASS_BY_STATUS = {400: "invalid_request", 422: "invalid_request", 401: "authentication",
                    403: "permission", 404: "not_found", 413: "context_exceeded", 429: "rate_limit"}


def error_class_for(status: int) -> Optional[str]:
    if status < 400:
        return None
    return _CLASS_BY_STATUS.get(status, "upstream" if status >= 500 else "invalid_request")


class _Reader:
    """Acumula texto, llamadas a herramienta y uso de una respuesta en cualquiera de las tres
    formas de la API (mensajes, chat, respuestas), completa o por eventos."""

    def __init__(self):
        self.out = Outcome(finished=False)

    def event(self, data: Mapping[str, Any]) -> None:
        o, kind = self.out, data.get("type", "")
        o.events += 1
        usage = data.get("usage") or (data.get("message") or {}).get("usage") \
            or (data.get("response") or {}).get("usage") or {}
        o.prompt_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or o.prompt_tokens)
        o.completion_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens")
                                  or o.completion_tokens)
        if kind == "content_block_delta":
            o.text += (data.get("delta") or {}).get("text") or ""
        elif kind == "content_block_start" and (data.get("content_block") or {}).get("type") == "tool_use":
            o.tool_calls.append({"name": data["content_block"].get("name")})
        elif kind == "message_stop":
            o.finished = True
        elif kind == "response.output_text.delta":
            o.text += data.get("delta") or ""
        elif kind in ("response.output_item.added", "response.output_item.done"):
            item = data.get("item") or {}
            if item.get("type") == "function_call" and item.get("name") and \
                    item["name"] not in {c["name"] for c in o.tool_calls}:
                o.tool_calls.append({"name": item["name"]})
        elif kind == "response.completed":
            o.finished = True
        for choice in data.get("choices") or ():
            delta = choice.get("delta") or {}
            o.text += delta.get("content") or ""
            for call in delta.get("tool_calls") or ():
                name = (call.get("function") or {}).get("name")
                if name and name not in {c["name"] for c in o.tool_calls}:
                    o.tool_calls.append({"name": name})
            if choice.get("finish_reason"):
                o.finished = True

    def whole(self, data: Mapping[str, Any]) -> None:
        o = self.out
        self.event(data)
        o.events = 1
        for block in data.get("content") or ():
            if isinstance(block, Mapping):
                if block.get("type") == "text":
                    o.text += block.get("text") or ""
                elif block.get("type") == "tool_use":
                    o.tool_calls.append({"name": block.get("name")})
        for choice in data.get("choices") or ():
            msg = choice.get("message") or {}
            o.text += msg.get("content") or ""
            o.tool_calls += [{"name": (c.get("function") or {}).get("name")} for c in msg.get("tool_calls") or ()]
        for item in data.get("output") or ():
            if item.get("type") == "function_call":
                o.tool_calls.append({"name": item.get("name")})
            for part in item.get("content") or ():
                if part.get("type") == "output_text":
                    o.text += part.get("text") or ""
        o.finished = True


def _estimate(out: Outcome, body: Mapping[str, Any]) -> None:
    """Un destino sin `usage` no deja gastar gratis: se estima por longitud (3 caracteres/token)."""
    if not out.prompt_tokens:
        out.prompt_tokens = len(json.dumps(body, ensure_ascii=False)) // CHARS_PER_TOKEN
    if not out.completion_tokens:
        out.completion_tokens = max(len(out.text) // CHARS_PER_TOKEN, 1) if out.status < 400 else 0


def engine_sender(destination: Mapping[str, Any], credential: Mapping[str, Any], *, face: str,
                  tenant_id: str, base_url: Optional[str] = None, master_key: Optional[str] = None,
                  timeout: float = CASE_TIMEOUT_S) -> Sender:
    """Sender real: misma firma de autorización y misma normalización que el plugin del plano de
    datos, contra el motor. Sin verificar contra un motor en vivo desde esta rama (ver informe)."""
    import httpx
    import uuid

    from . import authz
    from .faces import claude as claude_face
    from .faces import generic as generic_face

    engine_model = credentials.family_model(destination["provider"], destination["real_model"])
    path = {"claude": "/v1/messages", "codex": "/v1/responses"}.get(face, "/v1/chat/completions")

    async def send(case: Mapping[str, Any], body: dict) -> Outcome:
        from src.services import ai_engine_client as engine
        if face == "claude":
            wire = dict(body)
            if resolver.fidelity("claude", destination) == "translated":
                wire, _ = claude_face.normalize_for_translated(
                    wire, destination.get("capability_profile") or {},
                    max_output=destination.get("max_output") or 0)
            wire["model"] = engine_model
        else:
            wire, _ = generic_face.prepare_request(body, engine_model=engine_model,
                                                   max_output=destination.get("max_output"))
        token = authz.issue(request_id=str(uuid.uuid4()), scope=f"{tenant_id}/tenant:*",
                            destination_id=str(destination["id"]), model=engine_model,
                            provider=destination["provider"], credential=dict(credential),
                            api_base=destination.get("api_base"),
                            decision={"public_id": "fidelity-probe", "face": face},
                            price=destination.get("price_override"),
                            drop_params=destination.get("unsupported_params") or None)
        headers = {"Authorization": f"Bearer {master_key if master_key is not None else engine._MASTER_KEY}",
                   authz.HEADER: token, "Content-Type": "application/json"}
        url = f"{base_url or engine._BASE_URL}{path}"
        reader = _Reader()
        async with httpx.AsyncClient(timeout=timeout) as client:
            if wire.get("stream"):
                async with client.stream("POST", url, json=wire, headers=headers) as resp:
                    status = resp.status_code
                    if status >= 400:
                        await resp.aread()
                    else:
                        async for line in resp.aiter_lines():
                            if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
                                try:
                                    reader.event(json.loads(line[5:]))
                                except ValueError:
                                    pass
                            elif line.strip() == "data: [DONE]":
                                reader.out.finished = True
            else:
                resp = await client.post(url, json=wire, headers=headers)
                status = resp.status_code
                if status < 400:
                    try:
                        reader.whole(resp.json())
                    except ValueError:
                        reader.out.status = 502
        out = reader.out
        out.status = status if out.status == 200 else out.status
        out.error_class = error_class_for(out.status)
        if out.status >= 400:
            out.finished = True
        _estimate(out, wire)
        return out

    return send
