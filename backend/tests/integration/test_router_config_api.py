"""Contrato de la API admin del auto-router (spec 030, US2 · T012).

Qué se fija acá —el contrato de `contracts/router-config-api.md`, no la implementación—:

- **Roundtrip real contra disco**: GET → PUT → GET escribiendo el JSON de verdad. El PUT es
  la única forma que tiene el admin de cambiar el ruteo en caliente; si lo que se relee no
  es lo que se guardó, el panel miente sobre lo que el runtime va a usar en la siguiente
  consulta.
- **422 con detalle** en lo que la validación del servicio debe rechazar (umbral fuera de
  `(0,1]`, timeout inválido, utterances vacías) **sin tocar el disco**: una config a medio
  validar escrita encima de una buena es peor que un rechazo.
- **`target_ok: false`** cuando la ruta apunta a un modelo que ya no está en el catálogo. El
  guardado NO valida contra el catálogo a propósito (data-model §1: el catálogo cambia
  después igual); la señal es del GET y el runtime degrada al default.
- **403 para no-admin**: el panel de ruteo es admin-only (US2 escenario 4).
- **Config corrupta ⇒ 200 con `config_error`**, jamás 500: si un JSON roto tumbara el GET, el
  admin se quedaría sin la única pantalla desde la que podría arreglarlo.

Y el contrato del generador de frases (`POST .../generate-utterances`), que es lo que hace
que «ruteo automático» no signifique «sentate a inventar veinte ejemplos»:

- **El generador es el modelo LOCAL o no hay generador** (422 honesto): el nombre y la
  descripción de una ruta describen el negocio del cliente, y mandarlos a un cloud para
  ahorrarle tipeo al admin regalaría justo lo que el producto promete que no sale del host.
- **El parseo aguanta un modelo chico**: qwen contesta con `<think>` y verborrea alrededor
  del array. Si el parser se rinde ahí, la feature no funciona en la única instalación real.
- **No repite lo que ya está cargado**: dos utterances iguales son un vector repetido — una
  llamada de embedding más y cero señal nueva para el clasificador.
- **No persiste nada**: generar es una propuesta; guardar sigue siendo el PUT.

El fichero de config vive en un tmp por test (monkeypatch de `get_config_path`): la suite no
escribe ni en el repo ni en el volumen del motor.
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "sentinel_test_router_config_api"
URL = "/api/v1/chat/router-config"
GENERAR = f"{URL}/generate-utterances"
MODELOS = "/api/v1/chat/models"

# Nombres white-label a propósito: en el piloto el modelo local NO se llama "ollama-algo"
# (el motor no se filtra al cliente), así que "es local" tiene que salir del
# `litellm_params.model` y no de una heurística sobre el `model_name`.
LOCAL = "modelo-del-cliente"
LOCAL_SECUNDARIO = "segundo-modelo-del-cliente"
CLOUD = "modelo-remoto"


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture(scope="module")
def admin(harness):
    client, _ = harness
    return admin_headers(client)


@pytest.fixture(autouse=True)
def config_temporal(monkeypatch, tmp_path):
    """Cada test con su propio `auto_router.json`, ausente al empezar.

    Se parchea `get_config_path` y no `load_config`/`save_config` porque el servicio lo
    resuelve por lookup de módulo en cada lectura y escritura: así el roundtrip ejercita el
    fichero de verdad —escritura atómica incluida— en vez de un doble en memoria.
    """
    from src.services import auto_router_service
    destino = tmp_path / "auto_router.json"
    monkeypatch.setattr(auto_router_service, "get_config_path", lambda: str(destino))
    return destino


@pytest.fixture(scope="module")
def modelo_real(harness, admin):
    """Un `model_name` que EXISTE en el catálogo del motor.

    Se toma del catálogo vivo en vez de hardcodear "gpt-4o": el computado que se prueba es
    justamente "¿está en el catálogo?", y un literal lo volvería un test sobre el config.yaml
    del repo. Se excluye el pseudo-modelo «auto», que el GET /models antepone pero NO vive en
    el `model_list` (daría `target_ok: false` con toda la razón).
    """
    client, _ = harness
    resp = client.get(MODELOS, headers=admin)
    assert resp.status_code == 200, resp.text
    nombres = [m["model_name"] for m in resp.json()
               if m.get("model_name") and m.get("provider") != "auto" and m["model_name"] != "auto"]
    assert nombres, "catálogo del motor vacío: los computados no se pueden verificar"
    return nombres[0]


# ── Dobles y fixtures del generador de frases ─────────────────────────────────────


def _entrada(nombre, modelo_completo):
    return {"model_name": nombre, "litellm_params": {"model": modelo_completo}}


def _catalogo(monkeypatch, tmp_path, entradas):
    """`config.yaml` temporal + `router_config` apuntando ahí.

    Se parchea el símbolo **de `router_config`** y no el de `chat`: el módulo importa
    `_get_config_path` POR VALOR (`from .chat import _get_config_path as
    _engine_config_path`), así que parchear `chat._get_config_path` no lo tocaría y el test
    leería el catálogo real del repo.
    """
    from src.api import router_config

    destino = tmp_path / "config_motor.yaml"
    destino.write_text(yaml.safe_dump({"model_list": entradas}), encoding="utf-8")
    monkeypatch.setattr(router_config, "_engine_config_path", lambda: str(destino))
    return destino


@pytest.fixture
def catalogo_con_local(monkeypatch, tmp_path):
    """Catálogo con un cloud PRIMERO y un local después: el generador tiene que saltearlo."""
    return _catalogo(monkeypatch, tmp_path, [
        _entrada(CLOUD, "openai/gpt-4o"),
        _entrada(LOCAL, "ollama_chat/qwen3:4b"),
    ])


@pytest.fixture
def catalogo_sin_local(monkeypatch, tmp_path):
    return _catalogo(monkeypatch, tmp_path, [
        _entrada(CLOUD, "openai/gpt-4o"),
        _entrada("otro-remoto", "gemini/gemini-2.5-flash"),
    ])


class _RespuestaMotor:
    status_code = 200

    def __init__(self, contenido):
        self._contenido = contenido

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"role": "assistant", "content": self._contenido}}]}


class _ClienteMotor:
    def __init__(self, falso):
        self._falso = falso

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url, **kwargs):
        self._falso.pedidos.append({
            "url": url,
            "json": kwargs.get("json") or {},
            "headers": kwargs.get("headers") or {},
        })
        return _RespuestaMotor(self._falso.contenido)


class _HttpxFalso:
    """Doble del módulo `httpx` de `router_config`: registra el pedido al motor."""

    def __init__(self, contenido):
        self.contenido = contenido
        self.pedidos = []
        self.timeouts = []

    def AsyncClient(self, *_args, **kwargs):  # noqa: N802 — espeja el nombre real
        self.timeouts.append(kwargs.get("timeout"))
        return _ClienteMotor(self)


@pytest.fixture
def motor(monkeypatch):
    """Devuelve un `responder(contenido)` que deja el motor mockeado y el registro a mano."""
    from src.api import router_config

    def responder(contenido):
        falso = _HttpxFalso(contenido)
        monkeypatch.setattr(router_config, "httpx", falso)
        return falso

    return responder


def prompt_de(falso):
    """El texto del mensaje de usuario que se le mandó al modelo."""
    mensajes = falso.pedidos[0]["json"]["messages"]
    return next(m["content"] for m in mensajes if m["role"] == "user")


# ── Helpers ───────────────────────────────────────────────────────────────────────


def config_valida(modelo):
    """Config mínima válida del schema de data-model §1 (una ruta, todos los campos)."""
    return {
        "enabled": True,
        "default_model": modelo,
        "timeout_seconds": 5,
        "embedding_model": "router-embeddings",
        "routes": [
            {
                "name": "Código y análisis",
                "description": "Consultas de código y razonamiento",
                "target_model": modelo,
                "score_threshold": 0.45,
                "tier": "premium",
                "utterances": ["escribí una función en python", "refactorizá este método"],
            }
        ],
    }


def con(modelo, **cambios):
    base = config_valida(modelo)
    base.update(cambios)
    return base


def con_ruta(modelo, **cambios):
    base = config_valida(modelo)
    base["routes"][0].update(cambios)
    return base


def en_disco(destino):
    return json.loads(destino.read_text())


# ── GET: defaults seguros y config_error ──────────────────────────────────────────


def test_get_sin_fichero_devuelve_defaults_seguros(harness, admin):
    """Sin config en disco el panel abre igual, apagado y avisado.

    `enabled: false` es lo que hace que la ausencia sea inofensiva: el runtime sirve por el
    default sin llamar a embeddings.
    """
    client, _ = harness

    resp = client.get(URL, headers=admin)

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["enabled"] is False
    assert cuerpo["routes"] == []
    assert cuerpo["config_error"] is True
    # Los computados existen aunque no haya config: el panel los pinta sin ramas especiales.
    assert cuerpo["default_model_ok"] is False
    assert isinstance(cuerpo["embedding_model_ok"], bool)


def test_config_corrupta_en_disco_no_tumba_el_panel(harness, admin, config_temporal):
    """JSON roto ⇒ 200 con defaults + `config_error`, nunca 500 (contrato §GET)."""
    client, _ = harness
    config_temporal.write_text('{"enabled": true, "routes": [ esto no es json')

    resp = client.get(URL, headers=admin)

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["config_error"] is True
    assert cuerpo["enabled"] is False, "una config ilegible no puede dejar el router encendido"
    assert cuerpo["routes"] == []


# ── Roundtrip ─────────────────────────────────────────────────────────────────────


def test_roundtrip_get_put_get(harness, admin, modelo_real, config_temporal):
    """GET → editar → PUT → GET: lo que vuelve es lo que quedó en disco.

    Se hace el PUT con el objeto tal como lo devolvió el GET (computados incluidos), que es
    exactamente lo que manda el panel; los computados no pueden terminar persistidos.
    """
    client, _ = harness
    assert client.get(URL, headers=admin).status_code == 200

    deseado = config_valida(modelo_real)
    puesto = client.put(URL, headers=admin, json=deseado)
    assert puesto.status_code == 200, puesto.text

    cuerpo = puesto.json()
    assert cuerpo["enabled"] is True
    assert cuerpo["default_model"] == modelo_real
    assert cuerpo["default_model_ok"] is True
    assert cuerpo["config_error"] is False
    assert cuerpo["routes"][0]["target_ok"] is True
    assert cuerpo["routes"][0]["utterances"] == deseado["routes"][0]["utterances"]

    # El GET siguiente ve lo mismo: la config es caliente, no hay estado en memoria que
    # sobreviva al fichero.
    releido = client.get(URL, headers=admin)
    assert releido.status_code == 200
    assert releido.json() == cuerpo

    # Y el disco no guarda campos derivados del catálogo (envejecen mal: el admin puede
    # borrar el modelo un segundo después).
    guardado = en_disco(config_temporal)
    assert "config_error" not in guardado
    assert "default_model_ok" not in guardado
    assert "target_ok" not in guardado["routes"][0]
    assert guardado["default_model"] == modelo_real

    # Reenviar el cuerpo del GET (con computados) es el flujo REAL del panel: se acepta y
    # sigue sin ensuciar el fichero.
    reenviado = client.put(URL, headers=admin, json=releido.json())
    assert reenviado.status_code == 200, reenviado.text
    assert "target_ok" not in en_disco(config_temporal)["routes"][0]


def test_edicion_de_una_ruta_aplica_sin_reiniciar_nada(harness, admin, modelo_real, config_temporal):
    """Cambiar el destino de una ruta se ve en el GET siguiente (US2: config caliente)."""
    client, _ = harness
    assert client.put(URL, headers=admin, json=config_valida(modelo_real)).status_code == 200

    editado = con_ruta(modelo_real, utterances=["arreglá este stacktrace"], score_threshold=0.6)
    assert client.put(URL, headers=admin, json=editado).status_code == 200

    ruta = client.get(URL, headers=admin).json()["routes"][0]
    assert ruta["utterances"] == ["arreglá este stacktrace"]
    assert ruta["score_threshold"] == 0.6


# ── Validación (422) ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("umbral", [0, -0.3, 1.5, 2])
def test_umbral_fuera_de_rango_es_422(harness, admin, modelo_real, config_temporal, umbral):
    """`0 < score_threshold ≤ 1`: fuera de ahí el coseno no puede decidir nada útil."""
    client, _ = harness

    resp = client.put(URL, headers=admin, json=con_ruta(modelo_real, score_threshold=umbral))

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"], "el 422 tiene que decir QUÉ campo está mal"
    assert not config_temporal.exists(), "una config rechazada no se escribe"


@pytest.mark.parametrize("timeout", [0, -1, 61, "cinco", None])
def test_timeout_invalido_es_422(harness, admin, modelo_real, config_temporal, timeout):
    """`0 < timeout_seconds ≤ 60`: un timeout inválido cuelga el ruteo de cada consulta."""
    client, _ = harness

    resp = client.put(URL, headers=admin, json=con(modelo_real, timeout_seconds=timeout))

    assert resp.status_code == 422, resp.text
    assert not config_temporal.exists()


@pytest.mark.parametrize("utterances", [[], [""], [123], "no es lista"])
def test_utterances_vacias_son_422(harness, admin, modelo_real, config_temporal, utterances):
    """Una ruta sin utterances no puede embeber nada: sería una ruta que nunca gana."""
    client, _ = harness

    resp = client.put(URL, headers=admin, json=con_ruta(modelo_real, utterances=utterances))

    assert resp.status_code == 422, resp.text
    assert not config_temporal.exists()


@pytest.mark.parametrize("campo,valor", [
    ("default_model", ""),
    ("enabled", "sí"),
])
def test_campos_raiz_invalidos_son_422(harness, admin, modelo_real, config_temporal, campo, valor):
    client, _ = harness

    resp = client.put(URL, headers=admin, json=con(modelo_real, **{campo: valor}))

    assert resp.status_code == 422, resp.text
    assert not config_temporal.exists()


def test_un_put_invalido_no_pisa_la_config_buena(harness, admin, modelo_real, config_temporal):
    """El rechazo preserva lo que ya había: el admin no pierde el ruteo por un typo."""
    client, _ = harness
    assert client.put(URL, headers=admin, json=config_valida(modelo_real)).status_code == 200
    antes = en_disco(config_temporal)

    assert client.put(URL, headers=admin,
                      json=con_ruta(modelo_real, score_threshold=9)).status_code == 422

    assert en_disco(config_temporal) == antes


# ── Ruta rota ─────────────────────────────────────────────────────────────────────


def test_ruta_a_modelo_inexistente_se_guarda_pero_se_señala(harness, admin, modelo_real,
                                                            config_temporal):
    """`target_ok: false` en vez de rechazo: el catálogo puede cambiar DESPUÉS de guardar.

    Rechazar en el PUT no arreglaría nada (el admin borra el modelo al día siguiente y la
    config queda rota igual) y sí rompería el orden natural "declaro la ruta, doy de alta el
    modelo". La señal es del GET; el runtime cae al default.
    """
    client, _ = harness
    roto = con_ruta(modelo_real, target_model="modelo-que-no-existe-en-el-catalogo")
    roto["default_model"] = "tampoco-existe-este"

    resp = client.put(URL, headers=admin, json=roto)

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["routes"][0]["target_ok"] is False
    assert cuerpo["default_model_ok"] is False
    assert cuerpo["config_error"] is False, "una ruta rota no es una config ilegible"
    # Lo declarado se guardó tal cual: la señal es del panel, no una mutilación del dato.
    assert en_disco(config_temporal)["routes"][0]["target_model"] == \
        "modelo-que-no-existe-en-el-catalogo"


# ── Admin-only ────────────────────────────────────────────────────────────────────


def _headers_no_admin(client, factory):
    """Usuario `client` (sin display_label de developer) logueado de verdad.

    Se siembra por DB directa para no depender del gate de seats de `POST /users`: lo que se
    prueba es el rol, no la licencia.
    """
    from src.auth.passwords import hash_password
    from src.models.user import User

    db = factory()
    try:
        usuario = db.query(User).filter(User.username == "router-no-admin").first()
        if usuario is None:
            db.add(User(username="router-no-admin", email="router-no-admin@sentinel.com.ar",
                        password_hash=hash_password("clave-no-admin-12345"),
                        role="client", is_active=True))
            db.commit()
    finally:
        db.close()

    resp = client.post("/api/v1/users/login",
                       json={"username": "router-no-admin", "password": "clave-no-admin-12345"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_no_admin_ni_ve_ni_edita_el_panel(harness, admin, modelo_real, config_temporal):
    """US2 escenario 4: el usuario final ve «Auto» como un modelo más, jamás la config."""
    client, factory = harness
    assert client.put(URL, headers=admin, json=config_valida(modelo_real)).status_code == 200
    antes = en_disco(config_temporal)
    headers = _headers_no_admin(client, factory)

    assert client.get(URL, headers=headers).status_code == 403
    assert client.put(URL, headers=headers,
                      json=con(modelo_real, enabled=False)).status_code == 403
    assert en_disco(config_temporal) == antes, "un 403 no puede haber tocado el disco"


def test_sin_sesion_es_401(harness, config_temporal):
    """Fail-closed: sin credencial no se responde la config del ruteo."""
    client, _ = harness
    assert client.get(URL).status_code == 401


# ── Generación de frases de calibración ───────────────────────────────────────────


def test_generar_frases_usa_el_modelo_local_y_no_persiste_nada(
        harness, admin, config_temporal, catalogo_con_local, motor):
    """El caso feliz completo: array limpio del modelo local ⇒ frases listas para revisar.

    Se afirma también CÓMO se pidió, porque cada parámetro es una decisión de producto:
    el modelo es el local (residencia + coste 0), la temperatura es alta (si no vuelven
    diez maneras de decir lo mismo, que para el clasificador es una sola utterance) y el
    timeout es largo (un Ollama frío tarda, y cortarlo convierte un caso normal en error).
    """
    client, _ = harness
    falso = motor('["mandame el estado de mi expediente", "quiero ver mis trámites"]')

    resp = client.post(GENERAR, headers=admin, json={
        "name": "Trámites de socios",
        "description": "Consultas sobre expedientes y trámites",
    })

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["utterances"] == ["mandame el estado de mi expediente",
                                    "quiero ver mis trámites"]
    assert cuerpo["model_used"] == LOCAL, "el cloud del catálogo no puede haber sido elegido"

    pedido = falso.pedidos[0]
    assert pedido["url"].endswith("/v1/chat/completions")
    assert pedido["json"]["model"] == LOCAL
    assert pedido["json"]["temperature"] == 0.8
    assert pedido["headers"].get("Authorization", "").startswith("Bearer")
    assert falso.timeouts == [90.0]
    # La ruta viaja al modelo: es de ahí de donde salen las frases.
    assert "Trámites de socios" in prompt_de(falso)

    # Generar es proponer: el fichero del router sigue sin existir.
    assert not config_temporal.exists(), "generar frases no puede escribir la config"


def test_el_thinking_del_modelo_no_rompe_el_parseo(
        harness, admin, catalogo_con_local, motor):
    """qwen razona en voz alta antes del array: hay que sacarle el array igual.

    Es el caso REAL de la instalación del piloto, no una hipótesis: el generador corre
    contra un modelo chico con thinking, y un parser que sólo acepte `json.loads` del
    contenido entero deja la feature muerta en la única máquina donde tiene que andar.
    El `[1, 2, 3]` del razonamiento está a propósito: parsea como JSON perfectamente y NO
    es el array buscado, así que el barrido tiene que seguir de largo.
    """
    client, _ = harness
    contenido = (
        "<think>\n"
        "El usuario pide frases sobre reclamos. Pienso [1, 2, 3] variantes distintas.\n"
        "</think>\n\n"
        'Acá van las frases:\n["me cobraron de más este mes", "quiero reclamar una factura"]\n'
    )
    falso = motor(contenido)

    resp = client.post(GENERAR, headers=admin, json={
        "name": "Reclamos de facturación", "description": "Quejas sobre cobros",
    })

    assert resp.status_code == 200, resp.text
    assert resp.json()["utterances"] == ["me cobraron de más este mes",
                                         "quiero reclamar una factura"]
    assert falso.pedidos, "el motor tiene que haber sido consultado"


def test_sin_array_se_cae_a_las_lineas_en_vez_de_fallar(harness, admin, catalogo_con_local,
                                                        motor):
    """Un modelo chico que se olvida del JSON no puede dejar al admin sin nada.

    Diez frases con una que se borra de un click es mejor producto que un error que lo manda
    a escribir las diez a mano. El razonamiento sí se descarta: si cada línea del monólogo
    entrara como "frase", el fallback daría más trabajo del que ahorra.
    """
    client, _ = harness
    motor("<think>\nA ver, el usuario quiere frases de turnos.\nPienso tres.\n</think>\n"
          "1. quiero sacar un turno\n- necesito cambiar mi turno\n\"cancelame el turno\",\n")

    resp = client.post(GENERAR, headers=admin, json={"name": "Turnos", "description": "Agenda"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["utterances"] == ["quiero sacar un turno", "necesito cambiar mi turno",
                                         "cancelame el turno"]


def test_las_frases_ya_cargadas_no_vuelven_a_proponerse(
        harness, admin, catalogo_con_local, motor):
    """Dedup case-insensitive contra `existing` y contra sí misma.

    Insensible a mayúsculas porque para el clasificador «Quiero mi factura» y «quiero mi
    factura» son el mismo vector: guardar las dos cuesta una llamada de embedding más y no
    agrega ninguna señal. Y las existentes viajan en el prompt para que genere
    COMPLEMENTARIAS, no para filtrarlas después.
    """
    client, _ = harness
    falso = motor('["Quiero mi factura", "quiero mi factura", '
                  '"necesito el comprobante de pago", "Necesito el comprobante de pago"]')

    resp = client.post(GENERAR, headers=admin, json={
        "name": "Facturación",
        "description": "Consultas de facturas",
        "existing": ["quiero mi factura"],
    })

    assert resp.status_code == 200, resp.text
    assert resp.json()["utterances"] == ["necesito el comprobante de pago"]
    assert "quiero mi factura" in prompt_de(falso), \
        "sin las existentes en el prompt el modelo repite y el dedup se come todo"


def test_count_recorta_lo_que_el_modelo_manda_de_más(harness, admin, catalogo_con_local, motor):
    """El panel pide N y recibe N: un modelo generoso no puede inundar el formulario."""
    client, _ = harness
    falso = motor('["una", "dos", "tres", "cuatro", "cinco"]')

    resp = client.post(GENERAR, headers=admin,
                       json={"name": "Ruta", "description": "algo", "count": 2})

    assert resp.status_code == 200, resp.text
    assert resp.json()["utterances"] == ["una", "dos"]
    assert "2" in prompt_de(falso), "el count pedido también se le dice al modelo"


def test_el_default_del_router_gana_si_es_local(
        harness, admin, config_temporal, monkeypatch, tmp_path, motor):
    """Con varios Ollama, el generador usa el que el admin ya eligió como default.

    Dos respuestas distintas a «¿cuál es TU modelo local?» en la misma instalación es
    exactamente lo que confunde: el respaldo de los cloud ya usa esta regla, y el generador
    tiene que usar la misma.
    """
    client, _ = harness
    _catalogo(monkeypatch, tmp_path, [
        _entrada(LOCAL, "ollama_chat/qwen3:4b"),
        _entrada(LOCAL_SECUNDARIO, "ollama/qwen3:8b"),
    ])
    config_temporal.write_text(json.dumps({
        "enabled": True, "default_model": LOCAL_SECUNDARIO, "timeout_seconds": 5,
        "embedding_model": "router-embeddings", "routes": [],
    }), encoding="utf-8")
    falso = motor('["una frase corta de ejemplo"]')

    resp = client.post(GENERAR, headers=admin, json={"name": "Ruta", "description": "algo"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["model_used"] == LOCAL_SECUNDARIO
    assert falso.pedidos[0]["json"]["model"] == LOCAL_SECUNDARIO


def test_sin_modelo_local_es_422_honesto_y_no_llama_a_ningún_cloud(
        harness, admin, catalogo_sin_local, motor):
    """Catálogo sólo con cloud ⇒ 422 que dice qué hacer, y CERO tráfico saliente.

    El nombre y la descripción de una ruta describen el negocio del cliente («Reclamos de
    facturación», «Expedientes de socios»). Mandarlos a OpenAI para ahorrarle tipeo al admin
    regalaría justo lo que el producto promete que no sale del host — y encima facturado.
    Sin local no se genera: se lo decimos y escribe a mano.
    """
    client, _ = harness
    falso = motor('["esto no se tendría que haber pedido nunca"]')

    resp = client.post(GENERAR, headers=admin,
                       json={"name": "Reclamos de facturación", "description": "Quejas"})

    assert resp.status_code == 422, resp.text
    detalle = resp.json()["detail"]
    assert "modelo local" in detalle and "Ollama" in detalle, \
        "el 422 tiene que decir QUÉ hacer, no sólo que no se pudo"
    assert falso.pedidos == [], "sin modelo local no se llama a NADA: ni un cloud de refilón"


def test_generar_frases_es_admin_only(harness, admin, catalogo_con_local, motor):
    """Mismo guard que el GET/PUT: el generador quema tiempo de GPU del cliente."""
    client, factory = harness
    falso = motor('["no se tendría que haber generado"]')
    headers = _headers_no_admin(client, factory)

    resp = client.post(GENERAR, headers=headers, json={"name": "Ruta", "description": "algo"})

    assert resp.status_code == 403, resp.text
    assert falso.pedidos == [], "un 403 no puede haber tocado el motor"
