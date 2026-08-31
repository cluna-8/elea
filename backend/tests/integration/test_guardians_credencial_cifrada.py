"""La credencial de servicio del guardián: se cifra, o no se escribe (issue #283).

Antes de este módulo, **ningún test del repo mandaba `service_api_key` por la API**. Los
cuatro que tocaban el campo escribían `service_api_key_encrypted="cifrada"` directo en el
modelo, salteando `encrypt()` por completo: el camino de escritura tenía cobertura CERO. Y
como la suite corre con el cifrado apagado (`conftest.py` de `backend/tests/`, `FERNET_SECRET_KEY=""`), un
test escrito sin la fixture de abajo mediría el camino roto y lo llamaría verde.

Los dos estados que se ejercitan son estados de DESPLIEGUE, no de la petición:

- **cifrado sano** — `_fernet` cargado. Es el único modo en que estos endpoints guardan.
- **cifrado caído** — `_fernet` en None: `FERNET_SECRET_KEY` ausente, vacía o **inválida**.
  La tercera es la que llega a producción: el compose exige la variable con
  `${FERNET_SECRET_KEY:?...}`, que corta con ausente o vacía pero acepta cualquier cadena no
  vacía. Una clave mal generada pasa ese guard y deja `_fernet` en None con un warning.

Se parchea el `_fernet` del módulo y **no** la variable de entorno porque
`encryption_service` la lee UNA vez en el import: setear el env en un test no haría nada.
"""
import pytest

from migration_harness import require_postgres
from seat_gate_harness import admin_headers, build_app_client

require_postgres()

DB = "sentinel_test_guardians_credencial_cifrada"

SECRETO = "sk-la-credencial-del-servicio-del-cliente"


@pytest.fixture(scope="module")
def entorno():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


@pytest.fixture
def cifrado_sano(monkeypatch):
    """Fernet REAL: el único estado en que estos endpoints tienen permitido guardar."""
    from cryptography.fernet import Fernet
    from src.services import encryption_service
    monkeypatch.setattr(encryption_service, "_fernet", Fernet(Fernet.generate_key()))
    yield


@pytest.fixture
def cifrado_caido(monkeypatch):
    """`FERNET_SECRET_KEY` ausente, vacía o inválida — sin doblar `encrypt`, para que el
    test recorra la misma función que corre en la sede del cliente."""
    from src.services import encryption_service
    monkeypatch.setattr(encryption_service, "_fernet", None)
    yield


def _cuerpo(nombre, **extra):
    # `is_active` en False a propósito: el gate de activación (FR-007) es de OTRO invariante
    # y no tiene que poder decidir el resultado de estos tests.
    cuerpo = {"name": nombre, "guardian_type": "openai_moderation", "is_active": False,
              "config": {}, "fail_mode": "log", "apply_on": "pre_call"}
    cuerpo.update(extra)
    return cuerpo


def _fila(factory, nombre):
    from src.models.guardian import Guardian
    db = factory()
    try:
        return db.query(Guardian).filter(Guardian.name == nombre).first()
    finally:
        db.close()


# ── Cifrado sano: se guarda, y se guarda DESCIFRABLE ──────────────────────────────

def test_la_credencial_guardada_se_puede_volver_a_leer(entorno, cifrado_sano):
    """No alcanza con que la columna quede no-nula: tiene que devolver el MISMO secreto.

    Una columna con cualquier cosa adentro pasaría un `assert is not None` y rompería recién
    cuando el guardián intente autenticarse contra su servicio, lejos de acá."""
    client, factory, h = entorno
    resp = client.post("/api/v1/guardians", json=_cuerpo("cred-alta", service_api_key=SECRETO),
                       headers=h)
    assert resp.status_code == 201, resp.text
    assert resp.json()["has_service_key"] is True
    assert SECRETO not in resp.text          # el secreto entra y no sale

    from src.services import encryption_service
    guardado = _fila(factory, "cred-alta").service_api_key_encrypted
    assert guardado != SECRETO               # no quedó en claro
    assert encryption_service.decrypt(guardado) == SECRETO


def test_un_alta_SIN_credencial_no_se_ve_afectada(entorno, cifrado_caido):
    """El 503 es sólo para quien mandó una credencial.

    Es el control negativo del guard: sin este test, cortar de más —romper TODA alta de
    guardián en un despliegue con el cifrado roto— pasaría por «fail-closed» y nadie lo
    notaría hasta la sede."""
    client, factory, h = entorno
    resp = client.post("/api/v1/guardians", json=_cuerpo("cred-sin-clave"), headers=h)
    assert resp.status_code == 201, resp.text
    assert resp.json()["has_service_key"] is False
    assert _fila(factory, "cred-sin-clave").service_api_key_encrypted is None


# ── Cifrado caído: corta con 503 y NO escribe ─────────────────────────────────────

def test_el_alta_con_el_cifrado_caido_corta_y_no_deja_fila(entorno, cifrado_caido):
    """Antes del #283 esto devolvía **201** con la credencial tirada: el admin veía el alta
    hecha y la credencial nunca existió."""
    client, factory, h = entorno
    resp = client.post("/api/v1/guardians", json=_cuerpo("cred-503", service_api_key=SECRETO),
                       headers=h)
    assert resp.status_code == 503, resp.text
    assert "guardian_cifrado_no_disponible" in resp.text
    assert _fila(factory, "cred-503") is None      # ni el guardián a medias


def test_el_PUT_con_el_cifrado_caido_NO_pisa_una_credencial_SANA(entorno, cifrado_sano,
                                                                 monkeypatch):
    """**El defecto que motivó la issue.** La fila ya tenía una credencial funcionando —
    cifrada cuando el despliegue tenía un Fernet sano —; el admin la va a rotar con el
    cifrado ya roto y antes del #283 se llevaba puesta la vieja, dejando NULL y **200**. No
    hay vuelta atrás: el texto en claro no se guarda en ningún lado.
    """
    client, factory, h = entorno
    creado = client.post("/api/v1/guardians",
                         json=_cuerpo("cred-rotacion", service_api_key=SECRETO), headers=h)
    assert creado.status_code == 201, creado.text
    gid = creado.json()["id"]
    antes = _fila(factory, "cred-rotacion").service_api_key_encrypted

    # El Fernet se rompe DESPUÉS de que la credencial estaba guardada y andando.
    from src.services import encryption_service
    monkeypatch.setattr(encryption_service, "_fernet", None)

    resp = client.put(f"/api/v1/guardians/{gid}",
                      json=_cuerpo("cred-rotacion", service_api_key="sk-la-nueva"), headers=h)
    assert resp.status_code == 503, resp.text
    assert "guardian_cifrado_no_disponible" in resp.text

    despues = _fila(factory, "cred-rotacion").service_api_key_encrypted
    assert despues == antes, "el PUT fallido pisó una credencial que estaba sana"


def test_el_PUT_fallido_tampoco_deja_a_medias_el_RESTO_de_la_fila(entorno, cifrado_sano,
                                                                  monkeypatch):
    """El 503 deja la fila ENTERA como estaba: tampoco el nombre nuevo con la credencial vieja.

    ⚠ Lo que este test **no** pinea, medido y no supuesto: el ORDEN. En el handler el cifrado
    va antes de mutar un solo atributo, pero moverlo al renglón de la asignación —o sea,
    dejar que la fila se mute y recién ahí levante— **deja este test en verde igual**
    (mutación corrida: 7/7 pasan). El motivo es que `get_db` cierra la sesión y descarta la
    transacción abierta, así que hoy las mutaciones pendientes no llegan a persistir por sí
    solas. Lo verificado acá es el resultado observable —la fila intacta—, no la mecánica que
    lo produce.

    El orden se mantiene igual, como defensa en profundidad y por la misma razón que está
    escrita en `sso/admin_api`: que hoy no persista es una propiedad del wiring del
    framework, no de este código. El día que alguien commitee la sesión en otro lado, el
    orden es lo único que separa «la fila quedó intacta» de «quedó a medias», y ningún test
    de este archivo lo va a avisar."""
    client, factory, h = entorno
    creado = client.post("/api/v1/guardians",
                         json=_cuerpo("cred-atomica", service_api_key=SECRETO), headers=h)
    assert creado.status_code == 201, creado.text
    gid = creado.json()["id"]

    from src.services import encryption_service
    monkeypatch.setattr(encryption_service, "_fernet", None)

    resp = client.put(f"/api/v1/guardians/{gid}",
                      json=_cuerpo("cred-atomica-RENOMBRADA", service_api_key="sk-la-nueva"),
                      headers=h)
    assert resp.status_code == 503, resp.text
    assert _fila(factory, "cred-atomica-RENOMBRADA") is None
    assert _fila(factory, "cred-atomica") is not None


# ── El NULL deliberado sigue siendo posible ───────────────────────────────────────

def test_mandar_la_credencial_VACIA_la_borra_a_proposito(entorno, cifrado_sano):
    """Con el cifrado SANO, el campo en blanco borra la credencial y devuelve 200.

    Es el contrapunto del test de arriba y lo que separa las dos causas del NULL: acá el
    admin pidió el borrado y la respuesta se lo confirma; allá el sistema se lo hizo sin
    decírselo. Que este siga en 200 es lo que prueba que el guard del #283 no se comió el
    borrado explícito de paso."""
    client, factory, h = entorno
    creado = client.post("/api/v1/guardians",
                         json=_cuerpo("cred-borrado", service_api_key=SECRETO), headers=h)
    gid = creado.json()["id"]
    assert _fila(factory, "cred-borrado").service_api_key_encrypted is not None

    resp = client.put(f"/api/v1/guardians/{gid}",
                      json=_cuerpo("cred-borrado", service_api_key=""), headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_service_key"] is False
    assert _fila(factory, "cred-borrado").service_api_key_encrypted is None


def test_OMITIR_la_credencial_en_una_edicion_la_conserva(entorno, cifrado_sano):
    """Editar el nombre no puede borrar la credencial: omitir el campo la conserva. Sin
    este test, «cortar por las dudas» en el PUT sin credencial pasaría desapercibido."""
    client, factory, h = entorno
    creado = client.post("/api/v1/guardians",
                         json=_cuerpo("cred-conserva", service_api_key=SECRETO), headers=h)
    gid = creado.json()["id"]
    antes = _fila(factory, "cred-conserva").service_api_key_encrypted

    resp = client.put(f"/api/v1/guardians/{gid}", json=_cuerpo("cred-conserva"), headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_service_key"] is True
    assert _fila(factory, "cred-conserva").service_api_key_encrypted == antes
