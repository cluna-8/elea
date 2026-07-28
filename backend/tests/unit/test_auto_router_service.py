"""Unit del auto-router semántico (spec 030, T004).

Todos PUROS: sin Postgres, sin Redis y sin motor. El cliente de embeddings y el
cliente de Redis se sustituyen por dobles, así que lo que se verifica es la lógica
de DECISIÓN — que es donde vive el riesgo:

- el switch OFF tiene que costar CERO llamadas de embeddings (SC-003, verificable
  en los logs del motor durante la demo);
- la degradación nunca puede ser silenciosa: cada fallo (timeout, motor caído,
  config rota, ruta rota) trae su `reason` concreto (FR-004);
- `below_threshold` NO es degradación: es el diseño (lo que no matchea va al local
  a coste 0), y confundirlo con un fallo llenaría la auditoría de falsos positivos;
- el empate exacto tiene que resolverse siempre igual (primera ruta declarada), o
  la demo mostraría destinos distintos para la misma consulta.

Contrato: specs/030-semantic-auto-router/data-model.md §1-2.
"""
import asyncio
import hashlib
import json

import httpx
import pytest

from src.services import ai_engine_client
from src.services import auto_router_service as svc


# --------------------------------------------------------------------------- #
# Dobles y fixtures
# --------------------------------------------------------------------------- #

# Vectores 3-D elegidos a mano: cada ruta ocupa un eje, así que el coseno con la
# consulta es exactamente 1.0 (match perfecto) o 0.0 (nada que ver). Sin números
# mágicos ni umbrales al borde: lo que se testea es la lógica, no el modelo.
_CODIGO = [1.0, 0.0, 0.0]
_RESUMEN = [0.0, 1.0, 0.0]
_CHARLA = [0.0, 0.0, 1.0]

_UTT_CODIGO = "escribí una función en python"
_UTT_RESUMEN = "resumime este documento"

_VECTORES = {
    _UTT_CODIGO: _CODIGO,
    _UTT_RESUMEN: _RESUMEN,
    "necesito una función que ordene una lista": _CODIGO,
    "hazme un resumen del acta": _RESUMEN,
    "hola, ¿qué tal?": _CHARLA,
}


class _Motor:
    """Doble de `ai_engine_client.embeddings`: cuenta invocaciones y guarda qué se
    le mandó (para verificar truncado, timeout y ausencia de ascii-fold)."""

    def __init__(self, mapa=None, error=None):
        self.mapa = dict(mapa or _VECTORES)
        self.error = error
        self.llamadas = 0
        self.inputs = []
        self.modelos = []
        self.timeouts = []

    async def __call__(self, model, inputs, timeout=10.0):
        self.llamadas += 1
        self.inputs.append(list(inputs))
        self.modelos.append(model)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        # Un texto sin vector declarado puntúa 0 contra todo (coseno con el vector
        # nulo), nunca un match accidental.
        return [self.mapa.get(t, [0.0, 0.0, 0.0]) for t in inputs]


class _FakeRedis:
    """Cache mínimo con la superficie que usa el servicio (`get`/`set`)."""

    def __init__(self):
        self.store = {}
        self.escrituras = 0

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.escrituras += 1


def _cfg(**override) -> dict:
    """Config del seed del piloto reducida a dos rutas + default local."""
    cfg = {
        "enabled": True,
        "default_model": "local-qwen",
        "timeout_seconds": 5,
        "embedding_model": "router-embeddings",
        "routes": [
            {
                "name": "Código y análisis",
                "description": "Código, análisis y razonamiento",
                "target_model": "gpt-4o",
                "score_threshold": 0.45,
                "tier": "premium",
                "utterances": [_UTT_CODIGO],
            },
            {
                "name": "Redacción y resumen",
                "target_model": "gpt-4o-mini",
                "score_threshold": 0.45,
                "tier": "economy",
                "utterances": [_UTT_RESUMEN],
            },
        ],
    }
    cfg.update(override)
    return cfg


@pytest.fixture(autouse=True)
def _sin_redis(monkeypatch):
    """Por defecto se rutea SIN cache: Redis caído no puede romper el ruteo. El test
    de cache instala su doble explícitamente por encima de este."""
    monkeypatch.setattr(svc, "get_redis", lambda: None)


@pytest.fixture
def en_disco(tmp_path, monkeypatch):
    """Escribe el config en un JSON temporal y apunta el servicio ahí."""
    def _escribir(contenido) -> str:
        ruta = tmp_path / "auto_router.json"
        crudo = contenido if isinstance(contenido, str) else json.dumps(contenido, ensure_ascii=False)
        ruta.write_text(crudo, encoding="utf-8")
        monkeypatch.setattr(svc, "get_config_path", lambda: str(ruta))
        return str(ruta)
    return _escribir


@pytest.fixture
def motor(monkeypatch):
    """Instala el doble del cliente de embeddings y lo devuelve para inspección."""
    def _instalar(**kwargs) -> _Motor:
        doble = _Motor(**kwargs)
        monkeypatch.setattr(svc.ai_engine_client, "embeddings", doble)
        return doble
    return _instalar


# --------------------------------------------------------------------------- #
# Switch global (SC-003)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_switch_off_sirve_el_default_sin_una_sola_llamada_de_embeddings(en_disco, motor):
    en_disco(_cfg(enabled=False))
    doble = motor()

    decision = await svc.route("escribí una función en python que ordene una lista")

    assert decision["model_selected"] == "local-qwen"
    assert decision["reason"] == "switch_off"
    assert decision["degraded"] is False
    assert decision["route"] is None
    assert decision["score"] == 0.0
    # El criterio de SC-003: con el switch apagado NO se toca el motor.
    assert doble.llamadas == 0


@pytest.mark.asyncio
async def test_la_decision_declara_siempre_el_modelo_pedido(en_disco, motor):
    en_disco(_cfg())
    motor()

    decision = await svc.route("necesito una función que ordene una lista")

    assert decision["requested"] == "auto"


# --------------------------------------------------------------------------- #
# Clasificación: best-of, empate determinista, bajo umbral
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_best_of_manda_la_consulta_de_codigo_al_modelo_premium(en_disco, motor):
    en_disco(_cfg())
    doble = motor()

    decision = await svc.route("necesito una función que ordene una lista")

    assert decision["model_selected"] == "gpt-4o"
    assert decision["route"] == "Código y análisis"
    assert decision["score"] == 1.0
    assert decision["degraded"] is False
    assert decision["reason"] is None
    # Una sola llamada con las utterances de TODAS las rutas + la consulta al final.
    assert doble.llamadas == 1
    assert doble.inputs[0] == [_UTT_CODIGO, _UTT_RESUMEN,
                               "necesito una función que ordene una lista"]


@pytest.mark.asyncio
async def test_best_of_manda_el_resumen_al_modelo_economico(en_disco, motor):
    en_disco(_cfg())
    motor()

    decision = await svc.route("hazme un resumen del acta")

    assert decision["model_selected"] == "gpt-4o-mini"
    assert decision["route"] == "Redacción y resumen"


@pytest.mark.asyncio
async def test_empate_exacto_gana_la_primera_ruta_declarada(en_disco, motor):
    # Las dos rutas apuntan al MISMO eje: score idéntico, sin desempate posible por
    # similitud. El contrato dice: gana la primera declarada, siempre.
    cfg = _cfg()
    cfg["routes"][1]["utterances"] = ["otra utterance que apunta al mismo lado"]
    en_disco(cfg)
    motor(mapa={**_VECTORES, "otra utterance que apunta al mismo lado": _CODIGO})

    decision = await svc.route("necesito una función que ordene una lista")

    assert decision["route"] == "Código y análisis"
    assert decision["model_selected"] == "gpt-4o"


@pytest.mark.asyncio
async def test_empate_exacto_invirtiendo_el_orden_declarado_cambia_el_ganador(en_disco, motor):
    # Mismo empate con las rutas al revés: gana la otra. Confirma que el desempate
    # es el ORDEN declarado y no un accidente del diccionario o del nombre.
    cfg = _cfg()
    cfg["routes"][1]["utterances"] = ["otra utterance que apunta al mismo lado"]
    cfg["routes"] = list(reversed(cfg["routes"]))
    en_disco(cfg)
    motor(mapa={**_VECTORES, "otra utterance que apunta al mismo lado": _CODIGO})

    decision = await svc.route("necesito una función que ordene una lista")

    assert decision["route"] == "Redacción y resumen"
    assert decision["model_selected"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_bajo_umbral_cae_al_default_y_NO_es_degradacion(en_disco, motor):
    en_disco(_cfg())
    motor()

    decision = await svc.route("hola, ¿qué tal?")

    assert decision["model_selected"] == "local-qwen"
    assert decision["reason"] == "below_threshold"
    # Clave: la charla trivial servida por el local es el DISEÑO (coste 0), no un
    # fallo. Marcarla como degradada llenaría la auditoría de falsas alarmas.
    assert decision["degraded"] is False
    assert decision["route"] is None


@pytest.mark.asyncio
async def test_router_encendido_sin_rutas_cae_al_default_sin_degradar(en_disco, motor):
    en_disco(_cfg(routes=[]))
    doble = motor()

    decision = await svc.route("necesito una función que ordene una lista")

    assert decision["model_selected"] == "local-qwen"
    assert decision["reason"] == "below_threshold"
    assert decision["degraded"] is False
    assert doble.llamadas == 0


# --------------------------------------------------------------------------- #
# Degradaciones (FR-004): siempre con motivo concreto
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_timeout_de_embeddings_degrada_con_embed_timeout(en_disco, motor):
    en_disco(_cfg())
    motor(error=httpx.ReadTimeout("timeout"))

    decision = await svc.route("necesito una función que ordene una lista")

    assert decision["model_selected"] == "local-qwen"
    assert decision["degraded"] is True
    assert decision["reason"] == "embed_timeout"


@pytest.mark.asyncio
async def test_timeout_de_asyncio_tambien_degrada_con_embed_timeout(en_disco, motor):
    en_disco(_cfg())
    motor(error=asyncio.TimeoutError())

    decision = await svc.route("necesito una función que ordene una lista")

    assert decision["reason"] == "embed_timeout"
    assert decision["degraded"] is True


@pytest.mark.asyncio
async def test_motor_caido_degrada_con_embed_error(en_disco, motor):
    en_disco(_cfg())
    motor(error=httpx.ConnectError("connection refused"))

    decision = await svc.route("necesito una función que ordene una lista")

    assert decision["model_selected"] == "local-qwen"
    assert decision["degraded"] is True
    assert decision["reason"] == "embed_error"


@pytest.mark.asyncio
async def test_respuesta_de_embeddings_incompleta_degrada_con_embed_error(en_disco, monkeypatch):
    # El motor responde 200 pero con menos vectores que textos: alinear índices a
    # ciegas asignaría el score de una ruta a otra. Se degrada en vez de mentir.
    en_disco(_cfg())

    async def _corto(model, inputs, timeout=10.0):
        return [_CODIGO]

    monkeypatch.setattr(svc.ai_engine_client, "embeddings", _corto)

    decision = await svc.route("necesito una función que ordene una lista")

    assert decision["degraded"] is True
    assert decision["reason"] == "embed_error"


@pytest.mark.asyncio
async def test_config_corrupta_degrada_con_config_error(en_disco, motor):
    en_disco("{ esto no es JSON válido")
    doble = motor()

    decision = await svc.route("necesito una función que ordene una lista")

    assert decision["degraded"] is True
    assert decision["reason"] == "config_error"
    assert doble.llamadas == 0


@pytest.mark.asyncio
async def test_config_ausente_degrada_con_config_error(tmp_path, monkeypatch, motor):
    monkeypatch.setattr(svc, "get_config_path", lambda: str(tmp_path / "no-existe.json"))
    doble = motor()

    decision = await svc.route("necesito una función que ordene una lista")

    assert decision["degraded"] is True
    assert decision["reason"] == "config_error"
    assert doble.llamadas == 0


@pytest.mark.asyncio
async def test_target_ausente_del_catalogo_degrada_con_target_missing(en_disco, motor):
    en_disco(_cfg())
    motor()

    decision = await svc.route(
        "necesito una función que ordene una lista",
        available_models={"local-qwen", "gpt-4o-mini"},   # gpt-4o ya no está
    )

    assert decision["model_selected"] == "local-qwen"
    assert decision["degraded"] is True
    assert decision["reason"] == "target_missing"
    # El registro tiene que decir QUÉ ruta quedó rota, no solo que se degradó.
    assert decision["route"] == "Código y análisis"
    assert decision["score"] == 1.0


@pytest.mark.asyncio
async def test_target_presente_en_el_catalogo_no_degrada(en_disco, motor):
    en_disco(_cfg())
    motor()

    decision = await svc.route(
        "necesito una función que ordene una lista",
        available_models={"local-qwen", "gpt-4o", "gpt-4o-mini"},
    )

    assert decision["model_selected"] == "gpt-4o"
    assert decision["degraded"] is False


# --------------------------------------------------------------------------- #
# Cache de vectores (R5)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_cache_hit_no_vuelve_a_embeber(en_disco, motor, monkeypatch):
    en_disco(_cfg())
    cache = _FakeRedis()
    monkeypatch.setattr(svc, "get_redis", lambda: cache)
    doble = motor()

    primera = await svc.route("necesito una función que ordene una lista")
    assert doble.llamadas == 1
    assert len(doble.inputs[0]) == 3          # 2 utterances + consulta
    assert cache.escrituras == 3

    segunda = await svc.route("necesito una función que ordene una lista")

    # Todo estaba cacheado: la segunda consulta no toca el motor.
    assert doble.llamadas == 1
    assert segunda == primera


@pytest.mark.asyncio
async def test_utterance_nueva_es_el_unico_miss(en_disco, motor, monkeypatch):
    # Editar rutas aplica en la consulta siguiente sin reiniciar nada: la utterance
    # nueva se embebe y las intactas salen del cache (cache por hash de contenido).
    en_disco(_cfg())
    cache = _FakeRedis()
    monkeypatch.setattr(svc, "get_redis", lambda: cache)
    doble = motor()
    await svc.route("necesito una función que ordene una lista")

    cfg = _cfg()
    cfg["routes"][0]["utterances"] = [_UTT_CODIGO, "refactorizá este método"]
    en_disco(cfg)
    doble.mapa["refactorizá este método"] = _CODIGO

    await svc.route("necesito una función que ordene una lista")

    assert doble.llamadas == 2
    assert doble.inputs[1] == ["refactorizá este método"]


@pytest.mark.asyncio
async def test_la_clave_de_cache_lleva_modelo_y_version_del_pipeline(en_disco, motor, monkeypatch):
    # El bump de versión es lo que impide que vectores del pipeline viejo (Azure +
    # ascii-fold) se sigan sirviendo para siempre tras cambiar de modelo.
    assert svc._CACHE_VERSION == "v3-local-qwen"
    en_disco(_cfg())
    cache = _FakeRedis()
    monkeypatch.setattr(svc, "get_redis", lambda: cache)
    motor()

    await svc.route("necesito una función que ordene una lista")

    esperada = "autoroute:emb:" + hashlib.sha256(
        f"router-embeddings:v3-local-qwen:{_UTT_CODIGO}".encode()
    ).hexdigest()
    assert esperada in cache.store
    assert json.loads(cache.store[esperada]) == _CODIGO


@pytest.mark.asyncio
async def test_redis_caido_no_rompe_el_ruteo(en_disco, motor, monkeypatch):
    class _RedisRoto:
        def get(self, key):
            raise RuntimeError("connection refused")

        def set(self, key, value, ex=None):
            raise RuntimeError("connection refused")

    en_disco(_cfg())
    monkeypatch.setattr(svc, "get_redis", lambda: _RedisRoto())
    motor()

    decision = await svc.route("necesito una función que ordene una lista")

    assert decision["model_selected"] == "gpt-4o"
    assert decision["degraded"] is False


# --------------------------------------------------------------------------- #
# Preparación del texto: truncado, acentos, timeout del panel
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_la_consulta_se_trunca_a_500_caracteres(en_disco, motor):
    en_disco(_cfg())
    doble = motor()
    largo = "x" * 900

    await svc.route(largo)

    embebido = doble.inputs[0][-1]
    assert len(embebido) == 500
    assert embebido == largo[:500]


@pytest.mark.asyncio
async def test_los_acentos_llegan_intactos_al_motor(en_disco, motor):
    # Sin `_ascii_fold` (era workaround del proxy Azure): con embeddings locales los
    # acentos y la ñ son señal útil en español, no ruido que haya que aplanar.
    en_disco(_cfg())
    doble = motor()

    await svc.route("necesito una función que ordene una lista")

    assert doble.inputs[0][0] == _UTT_CODIGO
    assert "ó" in doble.inputs[0][-1]


@pytest.mark.asyncio
async def test_el_timeout_del_panel_llega_al_cliente_de_embeddings(en_disco, motor):
    en_disco(_cfg(timeout_seconds=3))
    doble = motor()

    await svc.route("necesito una función que ordene una lista")

    assert doble.timeouts[0] == 3.0
    assert doble.modelos[0] == "router-embeddings"


@pytest.mark.asyncio
async def test_timeout_invalido_en_el_json_no_rompe_el_ruteo(en_disco, motor):
    en_disco(_cfg(timeout_seconds="cinco"))
    doble = motor()

    decision = await svc.route("necesito una función que ordene una lista")

    assert doble.timeouts[0] == 5.0
    assert decision["model_selected"] == "gpt-4o"


# --------------------------------------------------------------------------- #
# Config: carga, validación y escritura atómica
# --------------------------------------------------------------------------- #

def test_load_config_sin_fichero_devuelve_los_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "get_config_path", lambda: str(tmp_path / "no-existe.json"))
    assert svc.load_config() == svc.DEFAULT_CONFIG


def test_load_config_mergea_sobre_los_defaults(en_disco):
    en_disco({"enabled": True, "default_model": "local-qwen"})
    cfg = svc.load_config()
    assert cfg["enabled"] is True
    assert cfg["default_model"] == "local-qwen"
    assert cfg["timeout_seconds"] == 5
    assert cfg["embedding_model"] == "router-embeddings"
    assert cfg["routes"] == []


def test_load_config_ignora_claves_en_null(en_disco):
    # Una clave presente-en-None rompería a todo consumidor que use .get(campo, def).
    en_disco({"enabled": True, "default_model": "local-qwen", "timeout_seconds": None})
    assert svc.load_config()["timeout_seconds"] == 5


def test_load_config_no_deja_mutar_los_defaults_del_modulo(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "get_config_path", lambda: str(tmp_path / "no-existe.json"))
    cfg = svc.load_config()
    cfg["routes"].append({"name": "intruso"})
    assert svc.DEFAULT_CONFIG["routes"] == []


def test_load_config_corrupta_levanta_error_tipado(en_disco):
    en_disco("{ roto")
    with pytest.raises(svc.AutoRouterConfigError):
        svc.load_config()


def test_load_config_con_json_que_no_es_objeto_levanta_error_tipado(en_disco):
    en_disco("[1, 2, 3]")
    with pytest.raises(svc.AutoRouterConfigError):
        svc.load_config()


def test_validate_config_acepta_el_seed_del_piloto():
    assert svc.validate_config(_cfg()) == []


def test_validate_config_acepta_rutas_vacias():
    assert svc.validate_config(_cfg(routes=[])) == []


@pytest.mark.parametrize("override, fragmento", [
    ({"enabled": "true"}, "enabled"),
    ({"default_model": ""}, "default_model"),
    ({"default_model": None}, "default_model"),
    ({"timeout_seconds": 0}, "timeout_seconds"),
    ({"timeout_seconds": 61}, "timeout_seconds"),
    ({"timeout_seconds": "cinco"}, "timeout_seconds"),
    ({"timeout_seconds": True}, "timeout_seconds"),
    ({"embedding_model": ""}, "embedding_model"),
    ({"routes": "no soy una lista"}, "routes"),
])
def test_validate_config_rechaza_cabecera_invalida(override, fragmento):
    errores = svc.validate_config(_cfg(**override))
    assert any(fragmento in e for e in errores), errores


@pytest.mark.parametrize("cambio, fragmento", [
    ({"name": ""}, "name"),
    ({"target_model": ""}, "target_model"),
    ({"score_threshold": 0}, "score_threshold"),
    ({"score_threshold": 1.5}, "score_threshold"),
    ({"score_threshold": "alto"}, "score_threshold"),
    ({"utterances": []}, "utterances"),
    ({"utterances": "no soy lista"}, "utterances"),
    ({"utterances": ["", "vale"]}, "utterances"),
])
def test_validate_config_rechaza_ruta_invalida(cambio, fragmento):
    cfg = _cfg()
    cfg["routes"][0].update(cambio)
    errores = svc.validate_config(cfg)
    assert any(fragmento in e and "routes[0]" in e for e in errores), errores


def test_validate_config_rechaza_lo_que_no_es_objeto():
    assert len(svc.validate_config(["no", "soy", "un", "objeto"])) == 1


def test_save_config_es_atomico_y_relee_lo_guardado(tmp_path, monkeypatch):
    destino = tmp_path / "auto_router.json"
    monkeypatch.setattr(svc, "get_config_path", lambda: str(destino))

    svc.save_config(_cfg())

    # Sin temporales huérfanos: el guardado es tmp + os.replace en el mismo dir.
    assert [p.name for p in tmp_path.iterdir()] == ["auto_router.json"]
    assert svc.load_config() == _cfg()


def test_save_config_conserva_los_acentos_sin_escapar(tmp_path, monkeypatch):
    destino = tmp_path / "auto_router.json"
    monkeypatch.setattr(svc, "get_config_path", lambda: str(destino))

    svc.save_config(_cfg())

    assert _UTT_CODIGO in destino.read_text(encoding="utf-8")


def test_save_config_sobrescribe_sin_dejar_restos(tmp_path, monkeypatch):
    destino = tmp_path / "auto_router.json"
    monkeypatch.setattr(svc, "get_config_path", lambda: str(destino))
    svc.save_config(_cfg())

    svc.save_config(_cfg(enabled=False))

    assert [p.name for p in tmp_path.iterdir()] == ["auto_router.json"]
    assert svc.load_config()["enabled"] is False


# --------------------------------------------------------------------------- #
# Cliente de embeddings del motor (`ai_engine_client.embeddings`)
#
# Lo mockean todos los tests de arriba, así que sin esta sección nadie lo mira. Y
# tiene dos contratos que el router da por sentados: el ORDEN de los vectores y que
# las excepciones lleguen crudas (si se envolvieran en AIEngineClientError, el
# router no podría distinguir `embed_timeout` de `embed_error`).
# --------------------------------------------------------------------------- #

class _RespuestaFake:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error del motor",
                request=httpx.Request("POST", "http://motor/v1/embeddings"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._payload


class _ClienteHttpFake:
    """Sustituye a `httpx.AsyncClient` como context manager asíncrono."""

    def __init__(self, respuesta=None, error=None):
        self.respuesta = respuesta
        self.error = error
        self.timeout = None
        self.llamada = {}

    def __call__(self, timeout=None, **kwargs):
        self.timeout = timeout
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self.llamada = {"url": url, "json": json, "headers": headers}
        if self.error is not None:
            raise self.error
        return self.respuesta


@pytest.mark.asyncio
async def test_embeddings_devuelve_los_vectores_en_el_orden_del_input(monkeypatch):
    # La respuesta llega desordenada a propósito: el orden se reconstruye por `index`,
    # no por la suerte de que el proveedor lo respete.
    payload = {"data": [
        {"index": 2, "embedding": [3.0]},
        {"index": 0, "embedding": [1.0]},
        {"index": 1, "embedding": [2.0]},
    ]}
    cliente = _ClienteHttpFake(respuesta=_RespuestaFake(payload))
    monkeypatch.setattr(ai_engine_client.httpx, "AsyncClient", cliente)

    vectores = await ai_engine_client.embeddings("router-embeddings", ["a", "b", "c"], timeout=3.0)

    assert vectores == [[1.0], [2.0], [3.0]]
    assert cliente.llamada["url"].endswith("/v1/embeddings")
    assert cliente.llamada["json"] == {"model": "router-embeddings", "input": ["a", "b", "c"]}
    assert cliente.llamada["headers"]["Authorization"].startswith("Bearer ")
    # El timeout es el del panel del router, no la constante del cliente.
    assert cliente.timeout == 3.0


@pytest.mark.asyncio
async def test_embeddings_propaga_el_timeout_sin_envolverlo(monkeypatch):
    cliente = _ClienteHttpFake(error=httpx.ReadTimeout("timeout"))
    monkeypatch.setattr(ai_engine_client.httpx, "AsyncClient", cliente)

    with pytest.raises(httpx.TimeoutException):
        await ai_engine_client.embeddings("router-embeddings", ["a"], timeout=1.0)


@pytest.mark.asyncio
async def test_embeddings_propaga_el_error_http_sin_envolverlo(monkeypatch):
    cliente = _ClienteHttpFake(respuesta=_RespuestaFake({}, status=500))
    monkeypatch.setattr(ai_engine_client.httpx, "AsyncClient", cliente)

    with pytest.raises(httpx.HTTPStatusError):
        await ai_engine_client.embeddings("router-embeddings", ["a"])
