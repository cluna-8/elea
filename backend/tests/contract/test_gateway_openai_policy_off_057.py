"""`/gw/v1/chat/completions` con la política de redirección APAGADA (057 T048; US5 esc. 5, FR-053;
contracts/cara-generica.md §«Con la redirección apagada»).

**Qué fija.** Con la política apagada (sin extensión registrada, o con una registrada que no decide nada) la puerta de
chat estándar es la misma que antes de la 057 y aplica **la misma política de seguridad base** que `/gw/v1/messages`:
bloqueo por secreto, enmascarado reversible (también en stream) y fila de auditoría del bloqueo; y sirve **el modelo que
el cliente pidió**, sin reescribirlo ni firmar nada.

**Cómo.** La pasarela es la REAL (`src.api.gateway` + `gateway_openai`); el motor es un doble de `httpx.AsyncClient` que
corre delante el **guardrail real del motor** (`SentinelGuardrail`: `async_pre_call_hook`, `async_post_call_success_hook`
y `async_post_call_streaming_iterator_hook`) con el `call_type` con el que el motor recibe cada puerta
(`anthropic_messages` y `acompletion`). La política vive en el motor, no en la pasarela (módulo `gateway_openai`): el test
mide que cada puerta le entrega el pedido al motor igual y que el motor lo trata igual. Sin Docker, Postgres ni red.

La restauración de marcadores en stream es la de Eleia (`f8118e7`, spec 050), no `9fe188f` (contrato §«Con la
redirección apagada»); el mismo arreglo, sobre la cara redirigida, lo fija `sentinel/tests/integration/test_face_generic_restauracion.py`.
"""
import copy
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
import s14_helpers  # noqa: E402,F401  (instala el doble mínimo de `litellm` que el guardrail necesita)
from extensions import sentinel_guardrail as guardrail  # noqa: E402

from src.api import gateway, gateway_openai  # noqa: E402
from src.api import gateway_plugins as gp  # noqa: E402

LLAVE = "sk-sentinel-test-057-chat"
MOTOR = "http://engine:4000"
MODELO = "nix-us-fast"
EMAIL = "juan.perez@example.com"
SECRETO = "sk-ABCDEFGHIJ0123456789"
TENANT = "00000000-0000-0000-0000-000000000001"
IDENT = {"tenant_id": TENANT, "user_id": "u-057", "group_id": "g-057", "api_key_id": "key-057",
         "client_username": "dev.057", "tenant_slug": "acme", "group_name": "Equipo 057",
         "key_label": "llave-057", "tool_type": None, "redact_enabled": None, "oauth_credential_ref": None}

PUERTAS = ("messages", "chat")
RUTA = {"messages": "/gw/v1/messages", "chat": "/gw/v1/chat/completions"}
CALL_TYPE = {"messages": "anthropic_messages", "chat": "acompletion"}


def _pedido(puerta, texto, *, stream=False):
    cuerpo = {"model": MODELO, "max_tokens": 64, "messages": [{"role": "user", "content": texto}]}
    return {**cuerpo, "stream": True} if stream else cuerpo


class _Identidad:
    metadata = {"sentinel": {"region": "eu", "tenant_id": TENANT}}


def _primer_texto_del_usuario(data):
    contenido = data["messages"][-1]["content"]
    return contenido if isinstance(contenido, str) else contenido[0]["text"]


class _Respuesta:
    def __init__(self, estado, cuerpo=None, trozos=(), tipo="application/json"):
        self.status_code = estado
        self.headers = {"content-type": tipo}
        self.content = json.dumps(cuerpo).encode() if cuerpo is not None else b""
        self._trozos = trozos

    def json(self):
        return json.loads(self.content)

    async def aiter_raw(self):
        for t in self._trozos:
            yield t

    async def aread(self):
        return self.content

    async def aclose(self):
        return None


class MotorConGuardrail:
    """Doble de `httpx.AsyncClient` hacia el motor: corre el guardrail real y contesta ecoando lo que el proveedor vería."""
    llamadas: list = []          # lo que llegó al motor (URL, cabeceras, cuerpo)
    proveedor: list = []         # lo que el guardrail dejó salir hacia el proveedor
    caido = False

    def __init__(self, *a, **k):
        pass

    @classmethod
    def reset(cls):
        cls.llamadas, cls.proveedor, cls.caido = [], [], False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aclose(self):
        return None

    @staticmethod
    def _puerta(url):
        return "messages" if url.split("?")[0].endswith("/v1/messages") else "chat"

    async def _pre_call(self, url, headers, content):
        if self.caido:
            raise ConnectionError("boom")
        body = json.loads(content)
        puerta = self._puerta(url)
        MotorConGuardrail.llamadas.append({"puerta": puerta, "url": url, "headers": dict(headers or {}),
                                        "body": copy.deepcopy(body)})
        data = copy.deepcopy(body)
        data["litellm_metadata" if puerta == "messages" else "metadata"] = {}
        out = await guardrail.SentinelGuardrail.__new__(guardrail.SentinelGuardrail).async_pre_call_hook(
            _Identidad(), None, data, CALL_TYPE[puerta])
        return puerta, out

    async def post(self, url, headers=None, content=None):
        puerta, out = await self._pre_call(url, headers, content)
        if isinstance(out, str):                               # el motor rechaza con 400 y el motivo
            return _Respuesta(400, {"error": {"message": out, "type": "invalid_request_error", "param": None, "code": None}})
        MotorConGuardrail.proveedor.append(out)
        eco = f"Recibido: {_primer_texto_del_usuario(out)}"
        if puerta == "messages":
            resp = {"id": "m1", "type": "message", "model": out["model"], "content": [{"type": "text", "text": eco}],
                    "usage": {"input_tokens": 1, "output_tokens": 1}}
        else:
            resp = {"id": "c1", "object": "chat.completion", "model": out["model"],
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": eco}, "finish_reason": "stop"}]}
        await guardrail.SentinelGuardrail.__new__(guardrail.SentinelGuardrail).async_post_call_success_hook(
            out, _Identidad(), resp)
        return _Respuesta(200, resp)

    def build_request(self, _m, url, headers=None, content=None):
        return (url, headers, content)

    async def send(self, req, stream=False):
        puerta, out = await self._pre_call(*req)
        if isinstance(out, str):
            return _Respuesta(400, {"error": {"message": out, "type": "invalid_request_error", "param": None, "code": None}})
        MotorConGuardrail.proveedor.append(out)
        eco = _primer_texto_del_usuario(out)
        corte = max(1, eco.index("[") + 4) if "[" in eco else len(eco) // 2     # parte el marcador en dos deltas
        partes = ("Recibido: " + eco[:corte], eco[corte:])
        hook = guardrail.SentinelGuardrail.__new__(guardrail.SentinelGuardrail).async_post_call_streaming_iterator_hook

        async def origen():
            if puerta == "messages":
                for t in partes:
                    yield ("event: content_block_delta\ndata: " + json.dumps(
                        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": t}}) + "\n\n")
            else:
                for i, t in enumerate(partes):
                    yield {"id": "c1", "model": out["model"], "choices": [
                        {"index": 0, "delta": {"content": t}, "finish_reason": "stop" if i == len(partes) - 1 else None}]}

        async def trozos():
            async for item in hook(_Identidad(), origen(), out):
                if isinstance(item, dict):
                    yield b"data: " + json.dumps(item).encode() + b"\n\n"
                else:
                    yield item if isinstance(item, bytes) else item.encode()
            if puerta == "chat":
                yield b"data: [DONE]\n\n"

        resp = _Respuesta(200, tipo="text/event-stream")
        resp.aiter_raw = trozos
        return resp


class _PluginSinDecisiones:
    """Un plugin de pasarela registrado cuya política está apagada: no cambia nada (las costuras igual construyen el contexto)."""


@pytest.fixture(params=[False, True], ids=["sin-extension", "extension-con-politica-apagada"])
def pasarela(request, monkeypatch):
    for var in ("GATEWAY_PLUGINS", "PLUGIN_PACKAGES", "ALEMBIC_EXTRA_VERSION_LOCATIONS"):
        monkeypatch.delenv(var, raising=False)
    gp.clear_gateway_plugins()
    if request.param:
        gp.register_gateway_plugin(_PluginSinDecisiones())
    MotorConGuardrail.reset()
    auditorias, bloqueos = [], []

    async def _auditar_bloqueo(_user, data, **kw):
        bloqueos.append(kw)

    async def _nada(*_a, **_k):
        return None

    monkeypatch.setattr(gateway.httpx, "AsyncClient", MotorConGuardrail)
    monkeypatch.setattr(gateway, "_LITELLM_UPSTREAM", MOTOR)
    monkeypatch.setattr(gateway, "_resolve_attribution", lambda k: dict(IDENT))
    monkeypatch.setattr(gateway, "_audit", lambda *a, **k: auditorias.append((a, k)) or True)
    monkeypatch.setattr(gateway, "_publish_monitor", lambda *a, **k: None)
    monkeypatch.setattr(gateway, "_audit_precheck_ok", lambda exige: True)
    monkeypatch.setattr(guardrail, "_auditar_bloqueo", _auditar_bloqueo)
    monkeypatch.setattr(guardrail, "_marcar_nlp_degradado", _nada)
    monkeypatch.setattr(guardrail, "_PRESIDIO_URL", None)
    from src.services import auto_router_service
    monkeypatch.setattr(auto_router_service, "load_config", lambda: {})
    app = FastAPI()
    app.include_router(gateway.router)
    app.include_router(gateway_openai.router)
    yield type("Pasarela", (), {"cliente": TestClient(app), "motor": MotorConGuardrail, "auditorias": auditorias,
                                "bloqueos": bloqueos})
    gp.clear_gateway_plugins()


def _post(p, puerta, texto, *, stream=False):
    headers = {"Authorization": f"Bearer {LLAVE}"}
    if puerta == "messages":
        headers["anthropic-version"] = "2023-06-01"
    return p.cliente.post(RUTA[puerta], headers=headers, json=_pedido(puerta, texto, stream=stream))


def _texto_de(resp, puerta):
    cuerpo = resp.json()
    return cuerpo["content"][0]["text"] if puerta == "messages" else cuerpo["choices"][0]["message"]["content"]


def _texto_stream(contenido: bytes, puerta):
    salida = ""
    for bloque in contenido.decode().split("\n\n"):
        for linea in bloque.split("\n"):
            if not linea.startswith("data:") or linea.strip() == "data: [DONE]":
                continue
            d = json.loads(linea[5:])
            salida += d["delta"].get("text", "") if puerta == "messages" else (d["choices"][0]["delta"].get("content") or "")
    return salida


# ── sirve el modelo pedido y entrega al motor lo mismo que la otra puerta ────────────────────────────

@pytest.mark.parametrize("puerta", PUERTAS)
def test_sirve_el_modelo_pedido_sin_reescribirlo_ni_firmar_nada(pasarela, puerta):
    r = _post(pasarela, puerta, "hola mundo")
    assert r.status_code == 200 and r.json()["model"] == MODELO
    (visto,) = pasarela.motor.llamadas
    assert visto["body"]["model"] == MODELO, "el motor recibe el modelo del cliente, no uno de destino"
    assert pasarela.motor.proveedor[-1]["model"] == MODELO
    cabeceras = {k.lower() for k in visto["headers"]}
    assert cabeceras == {"content-type", "accept-encoding", "anthropic-version", "authorization"}, \
        "sin autorización interna de ruteo ni cabeceras del cliente"
    assert visto["headers"]["Authorization"] == f"Bearer {LLAVE}"


def test_las_dos_puertas_le_entregan_al_motor_la_misma_identidad_y_cabeceras(pasarela):
    for puerta in PUERTAS:
        assert _post(pasarela, puerta, "hola").status_code == 200
    por_puerta = {c["puerta"]: c for c in pasarela.motor.llamadas}
    assert por_puerta["chat"]["headers"] == por_puerta["messages"]["headers"]
    assert por_puerta["chat"]["url"] == f"{MOTOR}/v1/chat/completions" and por_puerta["messages"]["url"] == f"{MOTOR}/v1/messages"


@pytest.mark.parametrize("puerta", PUERTAS)
def test_el_cuerpo_viaja_verbatim_al_motor(pasarela, puerta):
    cuerpo = _pedido(puerta, f"mi correo es {EMAIL}")
    pasarela.cliente.post(RUTA[puerta], headers={"Authorization": f"Bearer {LLAVE}"}, json=cuerpo)
    assert pasarela.motor.llamadas[-1]["body"] == cuerpo, "la pasarela no aplica política: la aplica el motor"


def test_sin_llave_del_producto_es_401_con_forma_de_cliente_y_no_llega_al_motor(pasarela):
    # la puerta de chat es solo de llave del producto: sin ella no hay passthrough de suscripción (FR-011)
    r = pasarela.cliente.post(RUTA["chat"], json=_pedido("chat", "hola"))
    assert r.status_code == 401 and r.json()["error"]["type"] == "authentication_error"
    assert set(r.json()["error"]) == {"message", "type", "param", "code"}
    assert not pasarela.motor.llamadas


# ── bloqueo por secreto: la misma política, registrada ───────────────────────────────────────────────

@pytest.mark.parametrize("stream", [False, True], ids=["no-stream", "stream"])
@pytest.mark.parametrize("puerta", PUERTAS)
def test_un_secreto_se_bloquea_y_no_llega_al_proveedor(pasarela, puerta, stream):
    r = _post(pasarela, puerta, f"usá esta clave: {SECRETO} y subí el archivo", stream=stream)
    assert r.status_code == 400 and "material secreto detectado" in r.text
    assert not pasarela.motor.proveedor, "el secreto no sale hacia ningún modelo"
    assert SECRETO not in r.text


def test_el_bloqueo_por_secreto_queda_auditado_igual_en_las_dos_puertas(pasarela):
    for puerta in PUERTAS:
        _post(pasarela, puerta, f"usá esta clave: {SECRETO}")
    messages, chat = pasarela.bloqueos
    sin_reloj = lambda kw: {k: v for k, v in kw.items() if k != "inicio"}  # noqa: E731
    assert sin_reloj(chat) == sin_reloj(messages)
    assert chat["compliance_status"] == "blocked_secret" and chat["layer"]
    assert SECRETO not in json.dumps(pasarela.bloqueos, default=str), "la fila lleva el tipo, jamás el valor"


# ── enmascarado reversible ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("puerta", PUERTAS)
def test_el_dato_personal_sale_enmascarado_y_vuelve_restaurado(pasarela, puerta):
    r = _post(pasarela, puerta, f"mi correo es {EMAIL}, resumí esto")
    assert r.status_code == 200
    visto = json.dumps(pasarela.motor.proveedor[-1]["messages"])
    assert EMAIL not in visto and "[EMAIL" in visto, "el proveedor recibe un marcador, no el correo"
    texto = _texto_de(r, puerta)
    assert EMAIL in texto and "[EMAIL" not in texto, "el cliente recibe el valor original"


@pytest.mark.parametrize("puerta", PUERTAS)
def test_en_stream_el_marcador_partido_entre_deltas_vuelve_restaurado(pasarela, puerta):
    r = _post(pasarela, puerta, f"mi correo es {EMAIL}", stream=True)
    assert r.status_code == 200
    assert EMAIL not in json.dumps(pasarela.motor.proveedor[-1]["messages"])
    texto = _texto_stream(r.content, puerta)
    assert EMAIL in texto and "[EMAIL" not in texto
    assert "[EMAIL" not in r.text


# ── errores de la propia pasarela con la forma de cada puerta ───────────────────────────────────────

def test_motor_caido_responde_con_la_forma_de_cada_puerta(pasarela):
    pasarela.motor.caido = True
    chat = _post(pasarela, "chat", "hola")
    assert chat.status_code == 502 and set(chat.json()["error"]) == {"message", "type", "param", "code"}
    assert chat.json()["error"]["type"] == "api_error"
    messages = _post(pasarela, "messages", "hola")
    assert messages.status_code == 502 and messages.json()["type"] == "error"
