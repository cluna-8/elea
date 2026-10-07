"""Restauración de marcadores por la cara genérica redirigida (057 T049; US5; contracts/cara-generica.md).

Con el enmascarado en juego, la respuesta de la cara OpenAI genérica vuelve **restaurada**: el cliente nunca ve un
marcador (`[EMAIL_ADDRESS_0_ab12]`), ni en no-stream, ni en stream —con el marcador partido entre dos chunks en
cualquier posición—, ni en los `arguments` de una herramienta. La restauración es la de Eleia (`f8118e7`, spec 050:
`unmask_openai_chunk` / `flush_openai_carries` de `sentinel_guardian_policy`), no `9fe188f`.

Cadena completa en el orden de `config.yaml` (R32/QA A3): pasarela REAL con el plugin de redirección → guardrail de la
base del motor (enmascara) → guard de la extensión (verifica el informe si el forzado rige) → el «proveedor» (que ecoa lo
que recibió, o sea los marcadores) → hook de streaming / de éxito del guardrail de la base (restaura) → envoltorio de la
cara (reescribe `model` al alias). Con y sin enmascarado forzado (postura `masked_all` de Eleia). Sin Docker.
"""
import copy
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend" / "tests" / "unit"))
import s14_helpers as sh  # noqa: E402  (instala el doble mínimo de `litellm` si el motor no está)
from extensions import sentinel_guardian_policy as policy  # noqa: E402
from extensions import sentinel_guardrail as base_guardrail  # noqa: E402

from sentinel.engine import redirect_guard as guard  # noqa: E402
from sentinel.tests import gw_harness as h  # noqa: E402
from sentinel.tests import redirect_fixtures as fx  # noqa: E402
from sentinel.tests import residency_fixtures as rf  # noqa: E402

AUTH = {"Authorization": f"Bearer {h.VK}"}
EMAIL = "juan.perez@example.com"
DNI = sh.DNI_PUNTOS
MARCADOR = re.compile(r"\[[A-Z][A-Z_]*_\d+_[0-9a-f]{3,8}\]")
DEST_US = {**fx.DEST_CHAT, "inference_jurisdiction": "US", "entity_jurisdiction": "US", "control_jurisdiction": "US"}


class _Identidad:
    metadata = {"sentinel": {"region": "latam_ar", "tenant_id": fx.TENANT}}


class MotorDeLaBase(h.Engine):
    """Motor falso con la cadena real delante: guardrail base → guard de la extensión → proveedor que ecoa → restauración."""
    proveedor: list = []                   # lo que salió hacia el proveedor (ya enmascarado)
    forma = "texto"                        # "texto" | "herramienta"
    corte = 5                              # dónde se parte el marcador entre deltas
    sin_finish = False                     # stream truncado: sin `finish_reason`

    @classmethod
    def reset(cls):
        h.Engine.reset()
        cls.proveedor, cls.forma, cls.corte, cls.sin_finish = [], "texto", 5, False

    async def _cadena(self, headers, content):
        body = json.loads(content)
        data = {**copy.deepcopy(body), "proxy_server_request": {"headers": dict(headers or {})}, "metadata": {}}
        base = base_guardrail.SentinelGuardrail.__new__(base_guardrail.SentinelGuardrail)
        masked = await base.async_pre_call_hook(_Identidad(), None, data, "acompletion")
        assert isinstance(masked, dict), f"la base bloqueó: {masked}"
        out = await guard.RedirectGuard().async_pre_call_hook({}, None, masked, "acompletion")
        MotorDeLaBase.proveedor.append(copy.deepcopy(out))
        return base, out

    @staticmethod
    def _eco(out):
        """Lo que contestaría el proveedor: el texto que recibió (con marcadores), partido en dos deltas."""
        recibido = out["messages"][-1]["content"]
        m = MARCADOR.search(recibido)
        assert m, "el proveedor tiene que haber recibido un marcador"
        texto = "Recibido: " + recibido
        corte = min(texto.index(m.group(0)) + MotorDeLaBase.corte, texto.index(m.group(0)) + len(m.group(0)) - 1)
        return texto, texto[:corte], texto[corte:]

    async def post(self, url, headers=None, content=None):
        base, out = await self._cadena(headers, content)
        texto, _, _ = self._eco(out)
        resp = {"id": "c1", "object": "chat.completion", "model": "qwen-destino", "choices": [
            {"index": 0, "message": {"role": "assistant", "content": texto}, "finish_reason": "stop"}]}
        await base.async_post_call_success_hook(out, _Identidad(), resp)
        return h._Resp(200, json.dumps(resp).encode())

    async def send(self, req, stream=False):
        url, headers, content = req
        base, out = await self._cadena(headers, content)
        texto, a, b = self._eco(out)
        fin = None if MotorDeLaBase.sin_finish else "stop"

        def chunk(delta, finish=None):
            return {"id": "c1", "model": "qwen-destino", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

        async def origen():
            if MotorDeLaBase.forma == "texto":
                yield chunk({"content": a})
                yield chunk({"content": b}, fin)
            else:                                   # el eco va como argumentos JSON de una herramienta
                fn = {"name": "responder", "arguments": ""}
                args = json.dumps({"texto": texto})
                m = MARCADOR.search(args)
                cut = m.start() + MotorDeLaBase.corte
                yield chunk({"tool_calls": [{"index": 0, "id": "t1", "type": "function",
                                             "function": {**fn, "arguments": args[:cut]}}]})
                yield chunk({"tool_calls": [{"index": 0, "function": {"arguments": args[cut:]}}]},
                            None if MotorDeLaBase.sin_finish else "tool_calls")

        async def trozos():
            async for item in base.async_post_call_streaming_iterator_hook(_Identidad(), origen(), out):
                yield b"data: " + json.dumps(item).encode() + b"\n\n"
            yield b"data: [DONE]\n\n"

        resp = h._Resp(200, b"", ctype="text/event-stream")
        resp.aiter_raw = trozos
        return resp


@pytest.fixture(params=[False, True], ids=["enmascarado-de-la-empresa", "enmascarado-forzado-masked_all"])
def env(request, monkeypatch):
    e = h.gateway_env(monkeypatch, ident=fx.ident(nlp={"region": "latam_ar"}))
    MotorDeLaBase.reset()
    monkeypatch.setattr(h.gateway.httpx, "AsyncClient", MotorDeLaBase)
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "latam_ar")
    monkeypatch.setattr(base_guardrail, "_PRESIDIO_URL", None)

    async def _nada(*_a, **_k):
        return None

    monkeypatch.setattr(base_guardrail, "_auditar_bloqueo", _nada)
    policy.clear_forced_masking_resolvers()
    forzado = request.param
    if forzado:
        # la extensión decide el forzado verificando la autorización firmada; acá, el mismo efecto sobre el pedido
        policy.register_forced_masking_resolver(lambda data, user, call_type: True)
    snap = fx.snapshot("on", regions=[rf.region_row("masked_all" if forzado else "allow")], offers=())
    snap = snap.__class__(**{**snap.__dict__, "destinations": {**snap.destinations, "d-chat": DEST_US}})
    e.register(snap)
    e.forzado, e.motor = forzado, MotorDeLaBase
    yield e
    policy.clear_forced_masking_resolvers()
    h.close_env()


def _chat(env, *, stream=False, texto=None):
    return env.client.post("/gw/v1/chat/completions", headers=AUTH, json={
        "model": "pro", "stream": stream,
        "messages": [{"role": "user", "content": texto or f"mi correo es {EMAIL} y mi DNI {DNI}"}]})


def _eventos(contenido: bytes):
    out = []
    for bloque in contenido.decode().split("\n\n"):
        for linea in bloque.split("\n"):
            if linea.startswith("data:") and linea.strip() != "data: [DONE]":
                out.append(json.loads(linea[5:]))
    return out


def _texto(eventos):
    return "".join((e["choices"][0]["delta"].get("content") or "") for e in eventos)


def _argumentos(eventos):
    return "".join(tc["function"].get("arguments") or "" for e in eventos
                   for tc in e["choices"][0]["delta"].get("tool_calls") or [])


# ── el proveedor recibe marcadores, nunca el valor ────────────────────────────────────────────────

def test_el_proveedor_recibe_marcadores_y_nunca_el_dato_personal(env):
    r = _chat(env, stream=True)
    assert r.status_code == 200
    (salida,) = env.motor.proveedor
    enviado = json.dumps(salida["messages"], ensure_ascii=False)
    assert EMAIL not in enviado and DNI not in enviado and MARCADOR.search(enviado)
    assert salida["model"] == "rdx-chatcompat/qwen-destino", "la cadena llegó hasta el destino redirigido"


# ── no-stream ─────────────────────────────────────────────────────────────────────────────────────

def test_no_stream_la_respuesta_vuelve_restaurada_y_con_el_alias(env):
    r = _chat(env)
    assert r.status_code == 200 and r.json()["model"] == "pro"
    texto = r.json()["choices"][0]["message"]["content"]
    assert EMAIL in texto and DNI in texto and not MARCADOR.search(r.text)


# ── stream: el marcador partido en cualquier posición ─────────────────────────────────────────────

@pytest.mark.parametrize("corte", list(range(1, 22)))
def test_stream_con_el_marcador_partido_entre_chunks_vuelve_restaurado(env, corte):
    env.motor.corte = corte
    r = _chat(env, stream=True)
    assert r.status_code == 200
    eventos = _eventos(r.content)
    assert EMAIL in _texto(eventos) and DNI in _texto(eventos)
    assert not MARCADOR.search(r.text), "ningún marcador llega al cliente"
    assert {e["model"] for e in eventos} == {"pro"}, "cada chunk con el alias, nunca el modelo del destino"
    assert r.content.rstrip().endswith(b"data: [DONE]")


def test_stream_con_marcador_en_los_argumentos_de_una_herramienta(env):
    env.motor.forma = "herramienta"
    r = _chat(env, stream=True)
    assert r.status_code == 200
    eventos = _eventos(r.content)
    args = json.loads(_argumentos(eventos))
    assert EMAIL in args["texto"] and not MARCADOR.search(r.text)
    assert {e["model"] for e in eventos} == {"pro"}


@pytest.mark.parametrize("forma", ["texto", "herramienta"])
def test_stream_cortado_sin_finish_reason_no_pierde_ni_deja_marcadores(env, forma):
    env.motor.forma, env.motor.sin_finish, env.motor.corte = forma, True, 3
    r = _chat(env, stream=True)
    eventos = _eventos(r.content)
    visto = _texto(eventos) if forma == "texto" else json.loads(_argumentos(eventos))["texto"]
    assert EMAIL in visto and DNI in visto and not MARCADOR.search(r.text)
