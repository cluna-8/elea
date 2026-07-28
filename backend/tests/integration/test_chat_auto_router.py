"""Auto-router semántico en el plano chat (spec 030, US1/US3 — T009).

Qué se prueba y por qué así:

- **El servicio real, con los embeddings falsos.** No se mockea `auto_router_service.route`:
  lo que hay que verificar es que el ENDPOINT hace fluir el modelo efectivo por todo el
  pipeline (FR-010) y que la decisión llega a las tres superficies (FR-006), y eso se
  rompería igual con un `route()` de mentira devolviendo un dict lindo. Lo único falso es
  la frontera de red: `ai_engine_client.embeddings` (vectores deterministas y contador de
  llamadas) y el `httpx` del namespace de `chat` (el motor de chat).
- **La config del router vive en un fichero temporal por test.** `get_config_path()` se
  redirige a `tmp_path`: sin eso los tests leerían el `auto_router.json` del repo —que en
  dev viene ENCENDIDO— y estarían midiendo el seed en vez del comportamiento.
- **Sin cache de vectores.** `_abrir_cache` se anula: el contador de llamadas de embeddings
  es la evidencia de SC-003 ("switch OFF ⇒ cero llamadas"), y un hit de Redis dejado por
  otra corrida lo volvería un número sin significado.

Los vectores falsos son one-hot por «tema»: dos textos del mismo tema tienen coseno 1.0 y
de temas distintos 0.0. Así el ruteo es totalmente determinista y el test afirma la
DECISIÓN del endpoint, no la calidad semántica del modelo de embeddings (eso es SC-001, y
se mide contra el stack vivo en el checkpoint T010, no acá).
"""
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient  # noqa: F401 — usado por build_app_client

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_chat_auto_router"

CHAT = "/api/v1/chat/completions"
MODELOS = "/api/v1/chat/models"

# Modelos que existen de verdad en el catálogo del motor (litellm/config.yaml): el router
# valida el destino contra el catálogo real, así que un target inventado degradaría a
# `target_missing` y el test estaría probando otra cosa.
PREMIUM = "gpt-4o"
ECONOMICO = "gpt-4o-mini"
LOCAL = "ollama-qwen3-4b"

# Temas de los vectores falsos. El texto no importa semánticamente: lo que importa es que
# la consulta comparta tema con las utterances de UNA sola ruta.
CONSULTA_CODIGO = "tema-codigo: escribí una función que ordene una lista"
CONSULTA_CHARLA = "tema-charla: hola, ¿qué tal andás?"


def _tema(texto: str) -> str:
    """Primer token `tema-*` del texto; `otro` si no declara tema."""
    for palabra in texto.replace(":", " ").split():
        if palabra.startswith("tema-"):
            return palabra
    return "otro"


_EJES = ["tema-codigo", "tema-resumen", "tema-charla", "otro"]


def _vector(texto: str) -> list:
    """One-hot por tema: coseno 1.0 dentro del tema, 0.0 entre temas."""
    tema = _tema(texto)
    return [1.0 if eje == tema else 0.0 for eje in _EJES]


def config_router(**overrides) -> dict:
    """Config con las 3 rutas del seed, en el schema de data-model §1."""
    cfg = {
        "enabled": True,
        "default_model": LOCAL,
        "timeout_seconds": 5,
        "embedding_model": "router-embeddings",
        "routes": [
            {
                "name": "Código y análisis",
                "description": "Código, análisis y razonamiento",
                "target_model": PREMIUM,
                "score_threshold": 0.45,
                "tier": "premium",
                "utterances": ["tema-codigo: escribí una función en python",
                               "tema-codigo: corregí este error"],
            },
            {
                "name": "Redacción y resumen",
                "target_model": ECONOMICO,
                "score_threshold": 0.45,
                "tier": "economy",
                "utterances": ["tema-resumen: resumime este texto"],
            },
        ],
    }
    cfg.update(overrides)
    return cfg


# ── Dobles ────────────────────────────────────────────────────────────────────────


class _FakeResponse:
    status_code = 200
    text = "ok"
    headers: dict = {}

    def __init__(self, modelo_que_contesto=None):
        self._modelo = modelo_que_contesto

    def json(self):
        cuerpo = {
            "choices": [{"message": {"content": "listo"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        }
        if self._modelo:
            cuerpo["model"] = self._modelo
        return cuerpo


class _FakeClient:
    """Registra a qué modelo se le mandó de verdad el pedido."""

    def __init__(self, registro, modelo_que_contesto=None):
        self._registro = registro
        self._modelo = modelo_que_contesto

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, *_args, **kwargs):
        cuerpo = kwargs.get("json") or {}
        self._registro.append(cuerpo.get("model"))
        return _FakeResponse(self._modelo)


class _FakeHttpx:
    def __init__(self, registro, modelo_que_contesto=None):
        self.registro = registro
        self._modelo = modelo_que_contesto

    def AsyncClient(self, *_args, **_kwargs):  # noqa: N802 — espeja el nombre real
        return _FakeClient(self.registro, self._modelo)


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    client.headers.update(admin_headers(client))
    yield client, factory
    cleanup()


@pytest.fixture
def motor(monkeypatch):
    """Motor de chat mockeado. Devuelve la lista de modelos que recibió."""
    from src.api import chat
    registro: list = []
    monkeypatch.setattr(chat, "httpx", _FakeHttpx(registro))
    return registro


@pytest.fixture
def embeddings(monkeypatch):
    """Doble de la frontera de embeddings: vectores deterministas + contador.

    Cuenta LLAMADAS (no textos): SC-003 afirma que con el switch apagado el motor no recibe
    ninguna, y eso es una propiedad del transporte, no del batch.
    """
    from src.services import auto_router_service

    llamadas: list = []

    async def _fake(model, inputs, timeout=10.0):
        llamadas.append({"model": model, "inputs": list(inputs), "timeout": timeout})
        return [_vector(t) for t in inputs]

    monkeypatch.setattr(auto_router_service.ai_engine_client, "embeddings", _fake)
    # Sin cache: el contador tiene que reflejar este test y no lo que dejó otro.
    monkeypatch.setattr(auto_router_service, "_abrir_cache", lambda: None)
    return llamadas


@pytest.fixture
def router_config(monkeypatch, tmp_path):
    """Escribe una config del router y apunta el servicio ahí. Devuelve el escritor."""
    from src.services import auto_router_service

    destino = tmp_path / "auto_router.json"
    monkeypatch.setattr(auto_router_service, "get_config_path", lambda: str(destino))

    def escribir(cfg):
        destino.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return destino

    return escribir


@pytest.fixture
def catalogo_temporal(monkeypatch, tmp_path):
    """Copia del `config.yaml` del motor en `tmp_path`, con el plano chat apuntando ahí.

    Los tests de alta de modelos ESCRIBEN el catálogo: sin esta copia, correr la suite
    modificaría el `litellm/config.yaml` del repo (que en dev está montado dentro del
    contenedor, o sea que el daño sería real y persistente).
    """
    from src.api import chat

    destino = tmp_path / "config.yaml"
    shutil.copyfile(chat._get_config_path(), destino)
    monkeypatch.setattr(chat, "_get_config_path", lambda: str(destino))

    def leer():
        with open(destino, "r") as f:
            return yaml.safe_load(f) or {}

    return destino, leer


# ── Helpers ───────────────────────────────────────────────────────────────────────


def pedir(client, mensaje, modelo="auto"):
    return client.post(CHAT, json={"message": mensaje, "model": modelo})


def ultima_fila(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return db.query(AuditLog).order_by(AuditLog.timestamp.desc()).first()
    finally:
        db.close()


def auto_router_de(payload):
    return payload["pipeline_metadata"]["layer_llm"].get("auto_router")


# ── (a) «auto» → ruta premium ─────────────────────────────────────────────────────


def test_auto_rutea_a_la_ruta_ganadora_y_registra_la_decision(
        harness, motor, embeddings, router_config):
    """El escenario 1 de US1: consulta de código con «auto» ⇒ contesta el premium.

    Se afirma la cadena entera, porque cada eslabón es un lugar donde el ruteo podría
    quedarse a medias: el modelo que recibió el MOTOR, el objeto decisión del Debugger, y
    la fila durable con `routing_decision` + el modelo EFECTIVO (jamás «auto»).
    """
    client, factory = harness
    router_config(config_router())

    respuesta = pedir(client, CONSULTA_CODIGO)
    assert respuesta.status_code == 200, respuesta.text
    payload = respuesta.json()

    assert motor == [PREMIUM], "el pipeline no llevó el modelo efectivo hasta el motor"

    decision = auto_router_de(payload)
    assert decision is not None, "sin decisión en layer_llm el Debugger no puede explicar nada"
    assert decision["requested"] == "auto"
    assert decision["route"] == "Código y análisis"
    assert decision["model_selected"] == PREMIUM
    assert decision["degraded"] is False
    assert decision["reason"] is None
    assert decision["score"] == pytest.approx(1.0)
    # El badge del modelo de la respuesta tiene que decir quién contestó (US3/FR-007).
    assert payload["pipeline_metadata"]["layer_llm"]["model_used"] == PREMIUM

    fila = ultima_fila(factory)
    assert fila is not None
    assert fila.model == PREMIUM, "la auditoría jamás puede decir «auto»: no es un modelo"
    assert fila.routing_decision is not None, "la decisión tiene que quedar en la columna durable"
    assert fila.routing_decision["route"] == "Código y análisis"
    assert fila.routing_decision["model_selected"] == PREMIUM
    # C1 / data-model §2: metadata-only, jamás texto del prompt.
    assert set(fila.routing_decision) == {"requested", "route", "score", "model_selected",
                                          "degraded", "reason"}
    assert "función" not in json.dumps(fila.routing_decision, ensure_ascii=False)


def test_bajo_umbral_sirve_por_el_default_sin_degradar(
        harness, motor, embeddings, router_config):
    """Escenario 3: lo que no matchea ninguna ruta va al local, y eso NO es una degradación
    — es el diseño (`below_threshold`, coste 0). Marcarlo `degraded` haría que el panel
    encendiera una alarma en el caso más común y más barato del producto."""
    client, _ = harness
    router_config(config_router())

    respuesta = pedir(client, CONSULTA_CHARLA)
    assert respuesta.status_code == 200, respuesta.text

    decision = auto_router_de(respuesta.json())
    assert motor == [LOCAL]
    assert decision["route"] is None
    assert decision["model_selected"] == LOCAL
    assert decision["degraded"] is False
    assert decision["reason"] == "below_threshold"


# ── (b) Embeddings caídos ─────────────────────────────────────────────────────────


def test_embeddings_caidos_responden_200_por_el_default_y_lo_registran(
        harness, motor, embeddings, router_config, monkeypatch):
    """Escenario 4 de US1 (FR-004): el modelo de embeddings caído NO puede romper el chat.

    Lo que se exige no es solo el 200: es que la degradación quede ESCRITA. Un fallback
    silencioso al default sería indistinguible de un ruteo exitoso al default, y ahí el
    cliente no tendría cómo enterarse de que su router lleva días sin decidir nada.
    """
    client, factory = harness
    router_config(config_router())

    from src.services import auto_router_service

    async def _explota(model, inputs, timeout=10.0):
        raise RuntimeError("motor de embeddings caído")

    monkeypatch.setattr(auto_router_service.ai_engine_client, "embeddings", _explota)

    respuesta = pedir(client, CONSULTA_CODIGO)
    assert respuesta.status_code == 200, respuesta.text

    decision = auto_router_de(respuesta.json())
    assert motor == [LOCAL], "con el ruteo caído la consulta se sirve igual, por el default"
    assert decision["degraded"] is True
    assert decision["reason"] == "embed_error"
    assert decision["model_selected"] == LOCAL

    fila = ultima_fila(factory)
    assert fila.routing_decision["degraded"] is True, (
        "una degradación que solo vive en la respuesta HTTP se pierde: el registro durable "
        "es el único lugar donde el cliente puede auditarla después")
    assert fila.routing_decision["reason"] == "embed_error"
    assert fila.model == LOCAL


def test_timeout_de_embeddings_se_distingue_de_un_fallo(
        harness, motor, embeddings, router_config, monkeypatch):
    """`embed_timeout` y `embed_error` son motivos distintos y el panel los trata distinto
    (uno se arregla subiendo el timeout, el otro levantando el modelo)."""
    import asyncio

    client, _ = harness
    router_config(config_router())

    from src.services import auto_router_service

    async def _tarda(model, inputs, timeout=10.0):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(auto_router_service.ai_engine_client, "embeddings", _tarda)

    respuesta = pedir(client, CONSULTA_CODIGO)
    assert respuesta.status_code == 200, respuesta.text
    decision = auto_router_de(respuesta.json())
    assert decision["degraded"] is True
    assert decision["reason"] == "embed_timeout"


# ── (c) Switch OFF: cero embeddings ───────────────────────────────────────────────


def test_switch_apagado_sirve_por_el_default_sin_una_sola_llamada_de_embeddings(
        harness, motor, embeddings, router_config):
    """SC-003 medido donde se puede medir: el contador del doble de embeddings.

    "Cero llamadas" es la diferencia entre un switch de verdad y un switch decorativo que
    igual gasta CPU del cliente en cada consulta.
    """
    client, _ = harness
    router_config(config_router(enabled=False))

    respuesta = pedir(client, CONSULTA_CODIGO)
    assert respuesta.status_code == 200, respuesta.text

    assert embeddings == [], "el switch OFF tiene que cortar ANTES de tocar el motor"
    assert motor == [LOCAL]
    decision = auto_router_de(respuesta.json())
    assert decision["reason"] == "switch_off"
    assert decision["degraded"] is False
    assert decision["route"] is None


def test_sin_config_del_router_el_pedido_auto_falla_honesto(
        harness, motor, embeddings, router_config, monkeypatch, tmp_path):
    """Sin `auto_router.json` no hay `default_model` que leer: el servicio devuelve la
    decisión degradada con `model_selected` VACÍO.

    El endpoint NO puede inventar un modelo ahí (podría mandar a la nube datos de una
    instalación que eligió local) ni mandarle `model=""` al motor, así que responde un error
    que dice qué falta. Es el único camino «auto» que no termina en 200, y es a propósito.
    """
    from src.services import auto_router_service
    client, _ = harness
    monkeypatch.setattr(auto_router_service, "get_config_path",
                        lambda: str(tmp_path / "no-existe.json"))

    respuesta = pedir(client, CONSULTA_CODIGO)
    assert respuesta.status_code == 503, respuesta.text
    assert "ruteo automático" in respuesta.json()["detail"].lower()
    assert motor == [], "no se le manda al motor un pedido sin modelo"
    assert embeddings == []


# ── Coste honesto: se pricea al que CONTESTÓ (FR-009 / research R7) ──────────────


def test_el_coste_es_el_del_modelo_que_contesto_no_el_del_pedido(
        harness, embeddings, router_config, monkeypatch):
    """US3 en el bolsillo del cliente: si el cloud se cae y contesta el LOCAL, el pedido
    cuesta 0 — no la tarifa del premium que se pidió.

    El motor dice en `model` quién respondió de verdad (verificado en vivo el 28-jul con
    OpenAI caído). Sin este camino, la instalación cobraría $5/$15 por millón de tokens que
    corrieron en el hardware del propio cliente, que es la mentira de coste que el
    Principio V prohíbe.
    """
    from src.api import chat
    client, factory = harness
    router_config(config_router())

    registro: list = []
    monkeypatch.setattr(chat, "httpx", _FakeHttpx(registro, modelo_que_contesto=LOCAL))

    respuesta = pedir(client, CONSULTA_CODIGO)
    assert respuesta.status_code == 200, respuesta.text

    assert registro == [PREMIUM], "el pedido SÍ salió hacia el premium"
    assert respuesta.json()["pipeline_metadata"]["layer_llm"]["cost_usd"] == 0.0, (
        "contestó el modelo local: el pedido no le costó nada al cliente")
    assert float(ultima_fila(factory).cost_usd) == 0.0


def test_un_id_versionado_del_proveedor_no_dispara_la_tarifa_por_defecto(
        harness, embeddings, router_config, monkeypatch):
    """El reverso del test anterior: adoptar a ciegas el `model` de la respuesta puede
    COBRAR DE MÁS.

    Los proveedores devuelven ids versionados (`gpt-4o-mini-2024-07-18`) que no están en el
    tarifario y caerían en el `default` conservador de $5/$15 — treinta veces la tarifa real
    de un modelo económico. Cuando el nombre de la respuesta no es priceable se conserva el
    del catálogo, que es el que sí tiene precio.
    """
    from src.api import chat
    client, _ = harness
    router_config(config_router())

    registro: list = []
    monkeypatch.setattr(chat, "httpx",
                        _FakeHttpx(registro, modelo_que_contesto="gpt-4o-mini-2024-07-18"))

    respuesta = pedir(client, "tema-resumen: resumime este informe")
    assert respuesta.status_code == 200, respuesta.text
    assert registro == [ECONOMICO]

    # 10 prompt + 4 completion tokens a la tarifa de gpt-4o-mini ($0.15 / $0.60 por millón).
    esperado = (10 / 1_000_000) * 0.15 + (4 / 1_000_000) * 0.60
    assert respuesta.json()["pipeline_metadata"]["layer_llm"]["cost_usd"] == pytest.approx(esperado)


# ── (d) El camino no-«auto» queda intacto ─────────────────────────────────────────


def test_pedido_con_modelo_explicito_no_tiene_ni_decision_ni_columna(
        harness, motor, embeddings, router_config):
    """El 99% del tráfico no pasa por el router y tiene que quedar exactamente igual.

    Dos ausencias, y las dos son afirmaciones: sin `auto_router` en el Debugger (la clave
    AUSENTE, no `null`) y `routing_decision` NULL en la fila. `NULL` ahí significa "este
    pedido no pasó por el router"; un objeto con `route: null` significaría "pasó y no
    eligió", que es distinto y falso.
    """
    client, factory = harness
    router_config(config_router())

    respuesta = pedir(client, "Resumime esto en una línea.", modelo=LOCAL)
    assert respuesta.status_code == 200, respuesta.text

    payload = respuesta.json()
    assert "auto_router" not in payload["pipeline_metadata"]["layer_llm"]
    assert embeddings == [], "un pedido con modelo explícito no debe costar un embedding"
    assert motor == [LOCAL]

    fila = ultima_fila(factory)
    assert fila.routing_decision is None
    assert fila.model == LOCAL


# ── (e) GET /chat/models: pseudo-modelo y exclusión del de embeddings ─────────────


def test_models_antepone_auto_y_esconde_el_modelo_de_embeddings(
        harness, router_config):
    """Contrato §GET: «auto» primero (el Playground preselecciona el índice 0) y
    `router-embeddings` fuera — no es conversable y elegirlo daría un error del motor."""
    client, _ = harness
    router_config(config_router())

    respuesta = client.get(MODELOS)
    assert respuesta.status_code == 200, respuesta.text
    modelos = respuesta.json()

    assert modelos[0]["model_name"] == "auto", "«auto» tiene que quedar preseleccionado"
    assert modelos[0]["provider"] == "auto"
    assert modelos[0]["is_configured"] is True
    assert modelos[0]["is_eu_compliant"] is True

    nombres = [m["model_name"] for m in modelos]
    assert "router-embeddings" not in nombres
    assert LOCAL in nombres, "el resto del catálogo tiene que seguir intacto"


def test_models_no_ofrece_auto_con_el_router_apagado(harness, router_config):
    """Con el switch OFF «auto» no es elegible: ofrecer un pseudo-modelo que el admin apagó
    convertiría el switch en decorativo desde el lado del usuario."""
    client, _ = harness
    router_config(config_router(enabled=False))

    modelos = client.get(MODELOS).json()
    nombres = [m["model_name"] for m in modelos]
    assert "auto" not in nombres
    assert "router-embeddings" not in nombres, (
        "el modelo de embeddings no es conversable ni con el router apagado")


# ── (f) US3: fallback siempre-a-local ─────────────────────────────────────────────


def test_alta_de_modelo_cloud_nace_con_respaldo_al_local(harness, catalogo_temporal,
                                                         router_config):
    """FR-007: el respaldo al local es un DEFAULT del alta, no una opción escondida.

    "Se cae tu proveedor y tu gente sigue trabajando gratis en local" solo es verdad si
    nadie tiene que acordarse de configurarlo modelo por modelo.
    """
    client, _ = harness
    _, leer = catalogo_temporal
    router_config(config_router(default_model=LOCAL))

    respuesta = client.post(MODELOS, json={
        "model_name": "nuevo-cloud", "provider": "openai",
        "model_id": "gpt-4o-mini", "api_key": "sk-de-prueba",
    })
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["fallback_model"] == LOCAL

    fallbacks = leer()["router_settings"]["fallbacks"]
    assert {"nuevo-cloud": [LOCAL]} in fallbacks


def test_alta_de_modelo_local_no_recibe_respaldo(harness, catalogo_temporal, router_config):
    """El respaldo va cloud→local y nunca al revés: un modelo local nace SIN respaldo."""
    client, _ = harness
    _, leer = catalogo_temporal
    router_config(config_router())

    respuesta = client.post(MODELOS, json={
        "model_name": "otro-local", "provider": "ollama_chat",
        "model_id": "llama3", "api_base": "http://host.docker.internal:11434",
    })
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["fallback_model"] is None

    fallbacks = leer().get("router_settings", {}).get("fallbacks", [])
    assert all("otro-local" not in item for item in fallbacks)


def test_el_respaldo_usa_el_default_del_router_cuando_es_local(
        harness, catalogo_temporal, monkeypatch, router_config):
    """Con VARIOS modelos locales, el respaldo va al que el admin declaró como default del
    router — que es la respuesta del producto a «¿y si hay N modelos de Ollama, a cuál va?».
    """
    client, _ = harness
    destino, leer = catalogo_temporal

    datos = leer()
    datos["model_list"].append({
        "model_name": "segundo-local",
        "litellm_params": {"model": "ollama_chat/llama3",
                           "api_base": "http://host.docker.internal:11434"},
    })
    with open(destino, "w") as f:
        yaml.safe_dump(datos, f)

    # El default del router apunta al SEGUNDO local, no al primero declarado.
    router_config(config_router(default_model="segundo-local"))

    respuesta = client.post(MODELOS, json={
        "model_name": "cloud-con-preferencia", "provider": "openai",
        "model_id": "gpt-4o", "api_key": "sk-de-prueba",
    })
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["fallback_model"] == "segundo-local"


def test_fallback_con_origen_local_se_rechaza(harness, catalogo_temporal):
    """Regla de residencia enforced en el escritor (US3, escenario 3): `local → cloud` NO
    existe. Sacar los datos del host justo cuando el modelo propio falla es exactamente lo
    que el modelo local vino a evitar."""
    client, _ = harness
    _, leer = catalogo_temporal

    respuesta = client.put(f"/api/v1/chat/fallbacks/{LOCAL}",
                           json={"fallback_model": PREMIUM})
    assert respuesta.status_code == 422, respuesta.text
    assert "local" in respuesta.json()["detail"].lower()

    fallbacks = leer().get("router_settings", {}).get("fallbacks", [])
    assert all(LOCAL not in item for item in fallbacks), (
        "un rechazo que igual escribe el fichero no es un rechazo")


def test_fallback_cloud_a_local_sigue_permitido(harness, catalogo_temporal):
    """La regla es direccional, no una prohibición general: el sentido bueno se conserva."""
    client, _ = harness
    _, leer = catalogo_temporal

    respuesta = client.put(f"/api/v1/chat/fallbacks/{PREMIUM}",
                           json={"fallback_model": LOCAL})
    assert respuesta.status_code == 200, respuesta.text
    assert {PREMIUM: [LOCAL]} in leer()["router_settings"]["fallbacks"]


def test_borrar_el_respaldo_de_un_modelo_local_se_permite(harness, catalogo_temporal):
    """Quitar una entrada nunca crea una fuga; negarlo dejaría atrapado a un admin que
    heredó una configuración mal hecha."""
    client, _ = harness
    destino, leer = catalogo_temporal

    datos = leer()
    datos.setdefault("router_settings", {}).setdefault("fallbacks", []).append(
        {LOCAL: [PREMIUM]})
    with open(destino, "w") as f:
        yaml.safe_dump(datos, f)

    respuesta = client.put(f"/api/v1/chat/fallbacks/{LOCAL}", json={"fallback_model": None})
    assert respuesta.status_code == 200, respuesta.text
    assert all(LOCAL not in item for item in leer()["router_settings"]["fallbacks"])


# ── Vitrina: el ÉXITO del plano chat se publica (SC-004) ─────────────────────────


def test_el_exito_del_chat_publica_evento_con_el_ruteo(harness, motor, embeddings,
                                                       router_config, monkeypatch):
    """SC-004: tres prompts → tres destinos visibles en «Conexiones en vivo».

    Hasta la 030 este plano solo publicaba sus bloqueos: en la vitrina, el chat existía
    únicamente cuando el firewall rechazaba algo. Se espía el serializador del GATEWAY (no
    una copia local) porque el contrato §8 exige un solo esquema para los tres productores.
    """
    from src.api import gateway
    client, _ = harness
    router_config(config_router())

    capturados = []
    real = gateway._publish_monitor

    def _espia(ident, tool, model, status, entities, preview, **kwargs):
        capturados.append({"model": model, "status": status, "tool": ident.get("tool_type"),
                           "entities": entities, "preview": preview,
                           "routing": kwargs.get("routing")})
        return real(ident, tool, model, status, entities, preview, **kwargs)

    monkeypatch.setattr(gateway, "_publish_monitor", _espia)

    respuesta = pedir(client, f"{CONSULTA_CODIGO} — avisale a laura.gomez@ejemplo.com")
    assert respuesta.status_code == 200, respuesta.text

    assert capturados, "el camino feliz del chat tiene que llegar a la vitrina"
    evento = capturados[-1]
    assert evento["tool"] == "chat-ui"
    assert evento["model"] == PREMIUM, "la vitrina muestra el modelo que atendió el pedido"
    # Vocabulario cerrado de la vitrina: los estados que ya emiten los otros productores.
    assert evento["status"] in ("passed", "flagged_high_risk")
    assert evento["routing"]["route"] == "Código y análisis"
    assert evento["routing"]["model_selected"] == PREMIUM

    # C1 sobre una superficie de emisión NUEVA: el camino feliz publica por primera vez, así
    # que es una vía de fuga nueva y hay que probarla, no heredarla del camino de bloqueo.
    assert "laura.gomez@ejemplo.com" not in (evento["preview"] or "")
    for entrada in evento["entities"]:
        assert set(entrada) == {"type", "count"}, "el evento jamás lleva el VALOR detectado"


def test_un_pedido_no_auto_publica_sin_campo_de_ruteo(harness, motor, embeddings,
                                                      router_config, monkeypatch):
    """La ausencia del campo es la codificación de "este pedido no pasó por el router": el
    gateway omite la clave cuando `routing` es None (no manda `null`)."""
    from src.api import gateway
    client, _ = harness
    router_config(config_router())

    capturados = []
    real = gateway._publish_monitor

    def _espia(ident, tool, model, status, entities, preview, **kwargs):
        capturados.append(kwargs.get("routing"))
        return real(ident, tool, model, status, entities, preview, **kwargs)

    monkeypatch.setattr(gateway, "_publish_monitor", _espia)

    assert pedir(client, "Hola.", modelo=LOCAL).status_code == 200
    assert capturados and capturados[-1] is None
