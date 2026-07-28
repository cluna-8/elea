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

El fichero de config vive en un tmp por test (monkeypatch de `get_config_path`): la suite no
escribe ni en el repo ni en el volumen del motor.
"""
import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_router_config_api"
URL = "/api/v1/chat/router-config"
MODELOS = "/api/v1/chat/models"


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
            db.add(User(username="router-no-admin", email="router-no-admin@basa.com.ar",
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
