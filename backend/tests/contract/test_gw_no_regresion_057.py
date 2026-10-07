"""Batería de no-regresión de la pasarela `/gw` con motor falso (spec 057, T003; SC-001, US2 esc. 1–2).

**Qué fija.** Lo que la pasarela hace HOY, sin ninguna extensión registrada, para cada superficie
que la 057 toca por cherry-pick (S1, S2, S2-OpenAI, S6, S7): `POST /gw/v1/messages` con la llave
del producto (camino al motor) y con la suscripción del cliente (camino a Anthropic), en
no-stream y en stream; `POST /gw/v1/messages/count_tokens`; `GET /gw/v1/models`; y los rechazos
que salen de la propia pasarela (bloqueo por secreto, byok sin llave, motor caído, error del
motor). Por caso compara **cuerpo, estado, lo que llegó al motor/proveedor y las filas de
auditoría y de monitor** contra lo grabado el día que se escribió, antes de traer ninguna costura
(`backend/tests/contract/gw_no_regresion_057.golden.json`).

**Cómo corre.** Sin Docker, sin Postgres, sin Redis y sin red: el motor y el proveedor son un
doble de `httpx.AsyncClient`; `_resolve_attribution`, `_audit` y `_publish_monitor` son dobles
que registran lo que habrían escrito (la fila real exige Postgres: su forma la fijan los tests de
integración existentes). Las variables de la extensión (`GATEWAY_PLUGINS`, `PLUGIN_PACKAGES`) se
borran del entorno, de modo que la batería mide la pasarela SIN extensión.

**Contrato del tramo T-A.** Verde antes del primer cherry-pick y verde después de cada uno, sin
tocar el JSON grabado: si un cherry-pick cambia una sola respuesta, fila o cabecera de estos
casos, es una regresión (FR-001, FR-002, SC-001). El JSON solo se regenera, a propósito, con
`GW_NO_REGRESION_GRABAR=1` (y el cambio queda a la vista en el diff).

**Reuso.** T018 (`sentinel/tests/integration/test_no_regresion_con_extension.py`) importa
`CASOS`, `observar` y `bateria` de este módulo y corre los mismos casos con la extensión montada y
la política apagada.
"""
import json
import os
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import gateway

GOLDEN = Path(__file__).with_name("gw_no_regresion_057.golden.json")
GRABAR = os.environ.get("GW_NO_REGRESION_GRABAR") == "1"

TENANT = "00000000-0000-0000-0000-000000000001"
LLAVE = "sk-sentinel-test-057-no-regresion"
OAUTH = "Bearer oauth-sub-tok-057"
MOTOR = "http://engine:4000"
PROVEEDOR = "https://api.anthropic.com"

# Cabeceras que se comparan de lo que llegó al upstream: las que el cliente necesita intactas
# (credencial, versión, beta) y las que la pasarela fija. El resto (host, content-length…) las
# recomputa httpx y no son contrato.
_CABECERAS = ("authorization", "x-api-key", "anthropic-version", "anthropic-beta", "user-agent",
              "content-type", "accept-encoding")

# Marcador de enmascarado: el sufijo es aleatorio por pedido (sin S13), se normaliza.
_MARCADOR = re.compile(r"\[([A-Z][A-Z_]*?)_(\d+)_[0-9a-f]{3,8}\]")

IDENT_CON_LLAVE = {
    "tenant_id": TENANT, "user_id": "u-057", "group_id": "g-057", "api_key_id": "key-057",
    "client_username": "dev.057", "tenant_slug": "acme", "group_name": "Equipo 057",
    "key_label": "llave-057", "tool_type": None, "redact_enabled": None,
    "oauth_credential_ref": None,
}
IDENT_ANONIMA = {**IDENT_CON_LLAVE, "user_id": None, "group_id": None, "api_key_id": None,
                 "client_username": None, "tenant_slug": None, "group_name": None,
                 "key_label": None}

BENIGNO = {"model": "claude-3-5-sonnet-20241022", "max_tokens": 64,
           "messages": [{"role": "user", "content": "hola mundo"}]}
CON_PII = {"model": "claude-3-5-sonnet-20241022", "max_tokens": 64,
           "messages": [{"role": "user",
                         "content": "mi correo es juan.perez@example.com, resumí esto"}]}
CON_SECRETO = {"model": "claude-3-5-sonnet-20241022", "max_tokens": 64,
               "messages": [{"role": "user",
                             "content": "usá esta clave: sk-ABCDEFGHIJ0123456789 y subí el archivo"}]}

RESP_OK = {"id": "msg_057", "type": "message", "role": "assistant", "model": "claude-3-5-sonnet",
           "content": [{"type": "text", "text": "listo"}],
           "usage": {"input_tokens": 7, "output_tokens": 3}}
SSE_OK = (b'event: message_start\ndata: {"type":"message_start","message":{"usage":'
          b'{"input_tokens":7,"output_tokens":0}}}\n\n'
          b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
          b'"delta":{"type":"text_delta","text":"listo"}}\n\n'
          b'event: message_delta\ndata: {"type":"message_delta","delta":{},'
          b'"usage":{"output_tokens":3}}\n\n'
          b'event: message_stop\ndata: {"type":"message_stop"}\n\n')
MODELOS = {"data": [{"type": "model", "id": "claude-3-5-sonnet-20241022",
                     "display_name": "Claude 3.5 Sonnet"}],
           "has_more": False, "first_id": None, "last_id": None}


# ── Doble del motor/proveedor ─────────────────────────────────────────────────────────

class _Respuesta:
    """Mismo shape que lo que la pasarela lee de `httpx`: `status_code`/`headers`/`content`/
    `json()` (no-stream) y `aiter_raw`/`aread`/`aclose` (stream)."""

    def __init__(self, estado=200, cuerpo=None, crudo=None, tipo="application/json"):
        self.status_code = estado
        self.headers = {"content-type": tipo}
        self._crudo = crudo if crudo is not None else json.dumps(cuerpo).encode("utf-8")

    @property
    def content(self):
        return self._crudo

    def json(self):
        return json.loads(self._crudo)

    async def aiter_raw(self):
        for i in range(0, len(self._crudo), 97):          # trozos que parten los eventos
            yield self._crudo[i:i + 97]

    async def aread(self):
        return self._crudo

    async def aclose(self):
        return None


class UpstreamFalso:
    """Reemplaza `gateway.httpx.AsyncClient`. Registra cada llamada (método, URL, cabeceras,
    cuerpo) y contesta con lo guionado por `(método, ruta)`; sin guion, un 500 del upstream."""

    def __init__(self):
        self.llamadas: list = []
        self.guion: dict = {}
        self.explotar: Exception | None = None

    def __call__(self, *a, **k):
        return _ClienteFalso(self)

    def _atender(self, metodo, url, headers, content):
        self.llamadas.append({"metodo": metodo, "url": url, "headers": dict(headers or {}),
                              "content": content})
        if self.explotar is not None:
            raise self.explotar
        ruta = "/" + url.split("://", 1)[1].split("/", 1)[1] if "://" in url else url
        return self.guion.get((metodo, ruta.split("?")[0])) or _Respuesta(
            500, {"type": "error", "error": {"type": "api_error", "message": "sin guion"}})


class _ClienteFalso:
    def __init__(self, upstream: UpstreamFalso):
        self._u = upstream

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aclose(self):
        return None

    async def post(self, url, headers=None, content=None):
        return self._u._atender("POST", url, headers, content)

    async def get(self, url, headers=None):
        return self._u._atender("GET", url, headers, None)

    def build_request(self, metodo, url, headers=None, content=None):
        return (metodo, url, headers, content)

    async def send(self, req, stream=False):
        return self._u._atender(*req)


# ── Casos ────────────────────────────────────────────────────────────────────────────

def _caso(nombre, *, metodo="POST", ruta="/gw/v1/messages", headers=None, cuerpo=None,
          crudo=None, stream=False, guion=None, ident=None, explotar=None):
    return {"nombre": nombre, "metodo": metodo, "ruta": ruta, "headers": headers or {},
            "cuerpo": cuerpo, "crudo": crudo, "stream": stream, "guion": guion or {},
            "ident": ident or IDENT_CON_LLAVE, "explotar": explotar}


_BYOK = {"X-Sentinel-Key": LLAVE, "X-Sentinel-Upstream": "byok", "anthropic-version": "2023-06-01"}
_SUSCRIPCION = {"Authorization": OAUTH, "anthropic-version": "2023-06-01",
                "anthropic-beta": "oauth-2025-04-20", "user-agent": "claude-cli/1.0 (external)",
                "X-Sentinel-Key": LLAVE}
_MENSAJES_MOTOR = ("POST", "/v1/messages")
_MENSAJES_PROVEEDOR = ("POST", "/v1/messages")

CASOS = [
    # llave del producto → motor (byok): el cuerpo va verbatim, la política es del motor
    _caso("byok_mensajes_no_stream", headers=_BYOK, cuerpo=BENIGNO,
          guion={_MENSAJES_MOTOR: _Respuesta(200, RESP_OK)}),
    _caso("byok_mensajes_stream", headers=_BYOK, cuerpo={**BENIGNO, "stream": True}, stream=True,
          guion={_MENSAJES_MOTOR: _Respuesta(200, crudo=SSE_OK, tipo="text/event-stream")}),
    _caso("byok_llave_en_authorization", headers={"Authorization": f"Bearer {LLAVE}"},
          cuerpo=BENIGNO, guion={_MENSAJES_MOTOR: _Respuesta(200, RESP_OK)}),
    _caso("byok_error_del_motor_pasa_verbatim", headers=_BYOK, cuerpo=BENIGNO,
          guion={_MENSAJES_MOTOR: _Respuesta(429, {"type": "error", "error": {
              "type": "rate_limit_error", "message": "limite"}})}),
    _caso("byok_stream_error_del_motor", headers=_BYOK, cuerpo={**BENIGNO, "stream": True},
          stream=True, guion={_MENSAJES_MOTOR: _Respuesta(503, {"type": "error", "error": {
              "type": "api_error", "message": "motor ocupado"}})}),
    _caso("byok_motor_caido", headers=_BYOK, cuerpo=BENIGNO, explotar=ConnectionError("boom")),
    _caso("byok_sin_llave_es_401", headers={"X-Sentinel-Upstream": "byok"}, cuerpo=BENIGNO),
    _caso("byok_auto_se_reescribe_al_default", headers=_BYOK, cuerpo={**BENIGNO, "model": "auto"},
          guion={_MENSAJES_MOTOR: _Respuesta(200, RESP_OK)}),
    # suscripción → proveedor: la pasarela aplica política y audita
    _caso("suscripcion_no_stream", headers=_SUSCRIPCION, cuerpo=BENIGNO,
          guion={_MENSAJES_PROVEEDOR: _Respuesta(200, RESP_OK)}),
    _caso("suscripcion_stream", headers=_SUSCRIPCION, cuerpo={**BENIGNO, "stream": True},
          stream=True,
          guion={_MENSAJES_PROVEEDOR: _Respuesta(200, crudo=SSE_OK, tipo="text/event-stream")}),
    _caso("suscripcion_anonima", headers={"Authorization": OAUTH}, cuerpo=BENIGNO,
          ident=IDENT_ANONIMA, guion={_MENSAJES_PROVEEDOR: _Respuesta(200, RESP_OK)}),
    _caso("suscripcion_con_pii_se_enmascara_y_se_restituye", headers=_SUSCRIPCION, cuerpo=CON_PII,
          guion={_MENSAJES_PROVEEDOR: _Respuesta(200, RESP_OK)}),
    _caso("suscripcion_bloqueo_por_secreto", headers=_SUSCRIPCION, cuerpo=CON_SECRETO),
    _caso("suscripcion_error_del_proveedor", headers=_SUSCRIPCION, cuerpo=BENIGNO,
          guion={_MENSAJES_PROVEEDOR: _Respuesta(529, {"type": "error", "error": {
              "type": "overloaded_error", "message": "saturado"}})}),
    _caso("suscripcion_proveedor_caido", headers=_SUSCRIPCION, cuerpo=BENIGNO,
          explotar=ConnectionError("boom")),
    _caso("mensajes_cuerpo_no_json", headers=_SUSCRIPCION, crudo=b"{no es json"),
    _caso("mensajes_modelo_reservado_de_la_cadena", headers=_SUSCRIPCION,
          cuerpo={**BENIGNO, "model": "license"}),
    # count_tokens y models, en las dos puertas
    _caso("count_tokens_byok", ruta="/gw/v1/messages/count_tokens", headers=_BYOK, cuerpo=BENIGNO,
          guion={("POST", "/v1/messages/count_tokens"): _Respuesta(200, {"input_tokens": 9})}),
    _caso("count_tokens_suscripcion", ruta="/gw/v1/messages/count_tokens", headers=_SUSCRIPCION,
          cuerpo=BENIGNO,
          guion={("POST", "/v1/messages/count_tokens"): _Respuesta(200, {"input_tokens": 9})}),
    _caso("count_tokens_byok_sin_llave_es_401", ruta="/gw/v1/messages/count_tokens",
          headers={"X-Sentinel-Upstream": "byok"}, cuerpo=BENIGNO),
    _caso("models_byok", metodo="GET", ruta="/gw/v1/models", headers=_BYOK,
          guion={("GET", "/v1/models"): _Respuesta(200, MODELOS)}),
    _caso("models_suscripcion", metodo="GET", ruta="/gw/v1/models", headers=_SUSCRIPCION,
          guion={("GET", "/v1/models"): _Respuesta(200, MODELOS)}),
    _caso("models_byok_sin_llave_es_401", metodo="GET", ruta="/gw/v1/models",
          headers={"X-Sentinel-Upstream": "byok"}),
    _caso("models_con_query_se_reenvia", metodo="GET", ruta="/gw/v1/models?limit=5",
          headers=_BYOK, guion={("GET", "/v1/models"): _Respuesta(200, MODELOS)}),
]


# ── Observación ──────────────────────────────────────────────────────────────────────

def _normalizar(texto):
    return _MARCADOR.sub(r"[\1_\2_<sufijo>]", texto) if isinstance(texto, str) else texto


def _bruto(valor):
    """Cuerpo → algo comparable y estable: JSON si lo es, texto si no; marcadores normalizados."""
    if isinstance(valor, bytes):
        valor = valor.decode("utf-8", errors="replace")
    if not isinstance(valor, str):
        return valor
    try:
        return json.loads(_normalizar(valor))
    except ValueError:
        return _normalizar(valor)


def _fila_auditoria(args, kwargs):
    ident, modelo, tok_in, tok_out, estado, entidades, _latencia = args[:7]
    atribucion = args[7] if len(args) > 7 else kwargs.get("attribution")
    return {
        "modelo": modelo, "tokens_in": tok_in, "tokens_out": tok_out, "estado": estado,
        "entidades": sorted(
            [(e.get("entity_type") or e.get("type") or str(e)) if isinstance(e, dict) else str(e)
             for e in (entidades or [])]),
        "capas": getattr(atribucion, "applied_layers", None),
        "bloqueada_por": getattr(atribucion, "blocked_by_layer", None),
        "tenant": ident.get("tenant_id"), "llave": ident.get("api_key_id"),
        # Los kwargs con valor `None` son el default del escritor (`routing_decision=None` lo suma
        # S2 en cada call-site, e3a5297): no cambian la fila escrita, así que no son contrato. Todo
        # kwarg con valor sí se compara.
        "extra": {k: v for k, v in kwargs.items() if k != "attribution" and v is not None},
    }


def _evento_monitor(args, kwargs):
    _ident, herramienta, modelo, estado, entidades = args[:5]
    return {"herramienta": herramienta, "modelo": modelo, "estado": estado,
            "entidades": len(entidades or []),
            "capas": getattr(kwargs.get("attribution"), "applied_layers", None),
            "bloqueada_por": getattr(kwargs.get("attribution"), "blocked_by_layer", None)}


class Bateria:
    def __init__(self, cliente, upstream, auditorias, eventos, identidad):
        self.cliente, self.upstream = cliente, upstream
        self.auditorias, self.eventos, self.identidad = auditorias, eventos, identidad


@pytest.fixture
def bateria(monkeypatch):
    """Pasarela sola (sin extensión) con el motor falso. Devuelve el arnés; los dobles de
    atribución/auditoría/monitor registran en vez de escribir."""
    for var in ("GATEWAY_PLUGINS", "PLUGIN_PACKAGES", "ALEMBIC_EXTRA_VERSION_LOCATIONS"):
        monkeypatch.delenv(var, raising=False)
    upstream = UpstreamFalso()
    auditorias, eventos = [], []
    identidad = {"actual": IDENT_CON_LLAVE}
    monkeypatch.setattr(gateway.httpx, "AsyncClient", upstream)
    monkeypatch.setattr(gateway, "_LITELLM_UPSTREAM", MOTOR)
    monkeypatch.setattr(gateway, "_ANTHROPIC_UPSTREAM", PROVEEDOR)
    monkeypatch.setattr(gateway, "_resolve_attribution",
                        lambda k: identidad["actual"] if k else IDENT_ANONIMA)
    monkeypatch.setattr(gateway, "_audit",
                        lambda *a, **k: auditorias.append(_fila_auditoria(a, k)) or True)
    monkeypatch.setattr(gateway, "_publish_monitor",
                        lambda *a, **k: eventos.append(_evento_monitor(a, k)))
    # El pre-check de auditoría lee Postgres: acá no hay, y su rama no es lo que se mide.
    monkeypatch.setattr(gateway, "_audit_precheck_ok", lambda exige: True)
    # «auto» se reescribe al default del router, que sale de un archivo de config del entorno:
    # se fija para que el caso no dependa de lo que haya en disco.
    from src.services import auto_router_service
    monkeypatch.setattr(auto_router_service, "load_config",
                        lambda: {"default_model": "modelo-por-defecto-057"})
    app = FastAPI()
    app.include_router(gateway.router)
    return Bateria(TestClient(app), upstream, auditorias, eventos, identidad)


def observar(b: Bateria, caso: dict) -> dict:
    """Corre un caso contra la pasarela y devuelve todo lo observable, en forma estable."""
    b.upstream.llamadas.clear()
    b.auditorias.clear()
    b.eventos.clear()
    b.upstream.guion = caso["guion"]
    b.upstream.explotar = caso["explotar"]
    b.identidad["actual"] = caso["ident"]
    kwargs = {"headers": caso["headers"]}
    if caso["crudo"] is not None:
        kwargs["content"] = caso["crudo"]
    elif caso["cuerpo"] is not None:
        kwargs["json"] = caso["cuerpo"]
    if caso["stream"]:
        with b.cliente.stream(caso["metodo"], caso["ruta"], **kwargs) as r:
            cuerpo = b"".join(r.iter_raw())
            estado, tipo = r.status_code, r.headers.get("content-type")
    else:
        r = b.cliente.request(caso["metodo"], caso["ruta"], **kwargs)
        cuerpo, estado, tipo = r.content, r.status_code, r.headers.get("content-type")
    return {
        "estado": estado,
        "tipo": (tipo or "").split(";")[0],
        "cuerpo": _bruto(cuerpo),
        "upstream": [{
            "metodo": c["metodo"], "url": c["url"],
            "headers": {k.lower(): v for k, v in c["headers"].items()
                        if k.lower() in _CABECERAS},
            "cuerpo": _bruto(c["content"]) if c["content"] is not None else None,
        } for c in b.upstream.llamadas],
        "auditoria": [{**f} for f in b.auditorias],
        "monitor": list(b.eventos),
    }


# ── Tests ────────────────────────────────────────────────────────────────────────────

def _grabado() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}


@pytest.fixture(scope="module", autouse=True)
def _cerrar_grabacion():
    """Con `GW_NO_REGRESION_GRABAR=1` regraba el JSON entero al final del módulo."""
    nuevo: dict = {}
    yield nuevo
    if GRABAR and nuevo:
        GOLDEN.write_text(json.dumps(nuevo, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                          encoding="utf-8")


@pytest.mark.parametrize("caso", CASOS, ids=[c["nombre"] for c in CASOS])
def test_la_pasarela_no_cambia(bateria, caso, _cerrar_grabacion):
    observado = observar(bateria, caso)
    # ida y vuelta por JSON: lo que se compara es lo que queda grabado (tuplas → listas)
    observado = json.loads(json.dumps(observado, ensure_ascii=False))
    if GRABAR:
        _cerrar_grabacion[caso["nombre"]] = observado
        return
    grabado = _grabado()
    assert caso["nombre"] in grabado, (
        f"caso sin grabar: {caso['nombre']} (regrabar a propósito con GW_NO_REGRESION_GRABAR=1)")
    assert observado == grabado[caso["nombre"]]


def test_el_json_grabado_cubre_exactamente_los_casos():
    nombres = {c["nombre"] for c in CASOS}
    assert set(_grabado()) == nombres or GRABAR
    assert len(nombres) == len(CASOS), "nombres de caso duplicados"


def test_la_bateria_corre_sin_extension_registrada(bateria):
    """La bateria mide la pasarela pelada: sin variables de extensión en el entorno."""
    assert not os.environ.get("GATEWAY_PLUGINS")
    assert not os.environ.get("PLUGIN_PACKAGES")
