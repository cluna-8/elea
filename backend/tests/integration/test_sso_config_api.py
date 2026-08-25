"""API de config SSO (`PUT/GET /api/v1/auth/sso/config`) — spec 017 US2, T018.

Lo que este módulo pinea, en orden de gravedad:

1. **El secreto entra y no sale.** Ninguna respuesta lo devuelve, y en la base viaja
   cifrado — el test lo comprueba leyendo la fila, no confiando en el endpoint.
2. **Sin cifrado disponible, corta y no persiste.** `encryption_service.encrypt()`
   devuelve `None` en silencio si falta `FERNET_SECRET_KEY`; guardar esa fila daría un
   200 al operador y un secreto NULL en la base, y el flujo se rompería recién en el
   navegador del cliente.
3. **La siembra alimenta al flujo de verdad**: tras el PUT, el `_cargar_config` que usa
   `/auth/sso/login` devuelve el secreto descifrado. Es la prueba de que el endpoint
   sirve para lo que existe, no de que escribió una fila.
"""
import sys
from pathlib import Path

import pytest

_dir = Path(__file__).resolve().parent
if str(_dir) not in sys.path:
    sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import (  # noqa: E402
    admin_headers, build_app_client, headers_for_role, rechazo_por_rol,
    restore_suite_license, set_license,
)

from src.auth.matrix import Rol  # noqa: E402

require_postgres()

DB = "basa_test_sso_config_api"
CONFIG = "/api/v1/auth/sso/config"
SECRETO = "el-secreto-del-idp-que-no-debe-salir"


@pytest.fixture(scope="module")
def entorno():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def _tabla_limpia(entorno):
    _, factory = entorno
    from src.models.sso_provider import SSOProvider
    for _ in range(1):
        db = factory()
        try:
            db.query(SSOProvider).delete()
            db.commit()
        finally:
            db.close()
    yield


@pytest.fixture(autouse=True)
def _licencia_base():
    restore_suite_license()
    yield
    restore_suite_license()


@pytest.fixture
def cifrado_disponible(monkeypatch):
    """Fernet REAL para los caminos felices.

    La suite corre con el cifrado APAGADO a propósito (`conftest.py:29`:
    `FERNET_SECRET_KEY=""`), así que `encrypt()` devuelve `None` por default y ningún
    test del repo ejercitaba hasta ahora el guardado de un secreto cifrado. Se parchea
    el `_fernet` del módulo y no la variable de entorno porque `encryption_service` la
    lee UNA vez en el import: setear el env acá no tendría ningún efecto — el mismo
    tipo de no-op silencioso que este endpoint existe para no dejar pasar.
    """
    from cryptography.fernet import Fernet
    from src.services import encryption_service
    monkeypatch.setattr(encryption_service, "_fernet", Fernet(Fernet.generate_key()))
    yield


@pytest.fixture
def sso_licenciado(monkeypatch, tmp_path):
    """El default de la suite trae `["monitor"]`: sin `sso` esta superficie no opera."""
    set_license(monkeypatch, tmp_path, feature_flags=["sso", "monitor"])
    yield
    restore_suite_license()


def _fila(factory):
    from src.models.sso_provider import SSOProvider
    db = factory()
    try:
        return db.query(SSOProvider).first()
    finally:
        db.close()


def _cuerpo(**over):
    cuerpo = {
        "provider_type": "entra",
        "config": {"directory_id": "dir-abc", "client_id": "cli-abc"},
        "client_secret": SECRETO,
        "enabled": True,
    }
    cuerpo.update(over)
    return cuerpo


# ── El gate de licencia, heredado del router ──────────────────────────────────────

def test_sin_el_flag_sso_la_superficie_no_opera(entorno):
    """Misma puerta que el flujo: configurar una feature que la licencia no habilita
    sólo puede terminar en una pantalla que promete algo que después fail-closea."""
    client, _ = entorno
    h = admin_headers(client)
    assert client.get(CONFIG, headers=h).status_code == 403
    resp = client.put(CONFIG, json=_cuerpo(), headers=h)
    assert resp.status_code == 403
    assert "sso_no_licenciado" in resp.text


# ── El secreto entra y no sale ────────────────────────────────────────────────────

def test_el_secreto_no_vuelve_en_la_respuesta_del_put(entorno, sso_licenciado, cifrado_disponible):
    client, _ = entorno
    resp = client.put(CONFIG, json=_cuerpo(), headers=admin_headers(client))
    assert resp.status_code == 200, resp.text
    assert SECRETO not in resp.text
    assert resp.json()["client_secret_configurado"] is True


def test_el_secreto_no_vuelve_en_la_respuesta_del_get(entorno, sso_licenciado, cifrado_disponible):
    client, _ = entorno
    h = admin_headers(client)
    client.put(CONFIG, json=_cuerpo(), headers=h)
    resp = client.get(CONFIG, headers=h)
    assert resp.status_code == 200, resp.text
    assert SECRETO not in resp.text
    assert resp.json()["client_secret_configurado"] is True


def test_en_la_base_el_secreto_esta_CIFRADO(entorno, sso_licenciado, cifrado_disponible):
    """No alcanza con que no salga por la API: se comprueba en la fila."""
    client, factory = entorno
    client.put(CONFIG, json=_cuerpo(), headers=admin_headers(client))
    fila = _fila(factory)
    assert fila.client_secret_encrypted
    assert fila.client_secret_encrypted != SECRETO      # no está en claro
    assert SECRETO not in fila.client_secret_encrypted

    from src.services import encryption_service
    assert encryption_service.decrypt(fila.client_secret_encrypted) == SECRETO


# ── Sin cifrado disponible: corta y NO persiste ───────────────────────────────────

@pytest.fixture
def cifrado_caido(monkeypatch):
    """El despliegue con `FERNET_SECRET_KEY` ausente, vacía o **inválida**, sin doblar nada.

    Se apaga el `_fernet` del módulo y se deja correr el `encrypt()` REAL, que desde el #283
    levanta `CifradoNoDisponible`. Antes estos dos tests doblaban `encrypt` con un
    `lambda _v: None`; el doble medía el guard, pero dejaba de coincidir con la función
    real en el momento en que la función real cambiara — que es exactamente lo que acaba de
    pasar. Con el `_fernet` apagado no hay doble que se pueda desincronizar: el test recorre
    el mismo camino que un cliente con la clave mal generada.
    """
    from src.services import encryption_service
    monkeypatch.setattr(encryption_service, "_fernet", None)
    yield


def test_sin_fernet_corta_con_503_y_no_escribe_nada(entorno, sso_licenciado, cifrado_caido):
    """Sin cifrado disponible, `encrypt()` levanta. Persistir igual sería un 200 con el
    secreto en la nada y el síntoma a kilómetros de la causa."""
    client, factory = entorno
    resp = client.put(CONFIG, json=_cuerpo(), headers=admin_headers(client))
    assert resp.status_code == 503, resp.text
    assert "sso_cifrado_no_disponible" in resp.text
    assert _fila(factory) is None      # ni una fila a medias


def test_un_secreto_VACIO_no_se_hace_pasar_por_el_cifrado_caido(entorno, sso_licenciado,
                                                                cifrado_disponible):
    """Sin Fernet y valor vacío son DOS causas distintas, y el 503 sólo es cierto para la
    primera. Con el cifrado sano, mandar el campo en blanco tiene que dar 400 del cuerpo: un
    503 «FERNET_SECRET_KEY no configurada» manda al admin a debuggear una infra que anda, y
    encima invita a reintentar algo que nunca va a andar. (El #283 llevó esa separación a la
    raíz: `encrypt()` devuelve `None` sólo por el vacío, y levanta por el sin-Fernet.)"""
    client, factory = entorno
    resp = client.put(CONFIG, json=_cuerpo(client_secret=""), headers=admin_headers(client))
    assert resp.status_code == 400, resp.text
    assert "sso_secreto_vacio" in resp.text
    assert "FERNET" not in resp.text        # el mensaje no puede señalar al sistema equivocado
    assert _fila(factory) is None


def test_sin_fernet_una_config_YA_guardada_queda_intacta(entorno, sso_licenciado, cifrado_disponible, monkeypatch):
    """El camino de error no puede dejar la config peor que como estaba."""
    client, factory = entorno
    h = admin_headers(client)
    client.put(CONFIG, json=_cuerpo(), headers=h)
    antes = _fila(factory).client_secret_encrypted

    # Se apaga el Fernet DESPUÉS de sembrar: es el despliegue que funcionaba y dejó de
    # funcionar (rotación de la clave a un valor mal generado), no uno que nunca anduvo.
    from src.services import encryption_service
    monkeypatch.setattr(encryption_service, "_fernet", None)
    resp = client.put(CONFIG, json=_cuerpo(client_secret="otro"), headers=h)
    assert resp.status_code == 503
    assert _fila(factory).client_secret_encrypted == antes


# ── Guards de coherencia ──────────────────────────────────────────────────────────

def test_un_proveedor_que_el_build_no_implementa_se_rechaza(entorno, sso_licenciado):
    """Una fila `enabled` apuntando a un proveedor inexistente hace que `/login`
    degrade con un error que parece del IdP y es nuestro."""
    client, factory = entorno
    resp = client.put(CONFIG, json=_cuerpo(provider_type="okta"),
                      headers=admin_headers(client))
    assert resp.status_code == 400
    assert "sso_proveedor_desconocido" in resp.text
    assert _fila(factory) is None


def test_no_se_puede_habilitar_sin_secreto(entorno, sso_licenciado):
    client, factory = entorno
    resp = client.put(CONFIG, json=_cuerpo(client_secret=None, enabled=True),
                      headers=admin_headers(client))
    assert resp.status_code == 400
    assert "sso_habilitado_sin_secreto" in resp.text
    assert _fila(factory) is None


def test_alta_sin_secreto_y_deshabilitada_se_permite(entorno, sso_licenciado):
    """Cargar los IDs primero y el secreto después es un flujo real de onboarding."""
    client, factory = entorno
    resp = client.put(CONFIG, json=_cuerpo(client_secret=None, enabled=False),
                      headers=admin_headers(client))
    assert resp.status_code == 200, resp.text
    assert resp.json()["client_secret_configurado"] is False
    assert _fila(factory).enabled is False


def test_omitir_el_secreto_en_una_edicion_CONSERVA_el_guardado(entorno, sso_licenciado, cifrado_disponible):
    """Si editar el `client_id` borrara el secreto, la config quedaría rota por una
    edición que el operador considera inocua."""
    client, factory = entorno
    h = admin_headers(client)
    client.put(CONFIG, json=_cuerpo(), headers=h)
    guardado = _fila(factory).client_secret_encrypted

    resp = client.put(CONFIG, json=_cuerpo(client_secret=None,
                                           config={"client_id": "cli-nuevo"}), headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["config"]["client_id"] == "cli-nuevo"
    assert _fila(factory).client_secret_encrypted == guardado


def test_el_get_sin_config_da_404_y_no_500(entorno, sso_licenciado):
    client, _ = entorno
    resp = client.get(CONFIG, headers=admin_headers(client))
    assert resp.status_code == 404
    assert "sso_sin_configurar" in resp.text


# ── La prueba que importa: la siembra alimenta al flujo real ──────────────────────

def test_lo_sembrado_lo_lee_el_flujo_de_login(entorno, sso_licenciado, cifrado_disponible):
    """`_cargar_config` es lo que usa `/auth/sso/login`. Que devuelva el secreto
    descifrado prueba que este endpoint sirve para lo que existe — no que escribió
    una fila con la forma correcta."""
    client, factory = entorno
    client.put(CONFIG, json=_cuerpo(), headers=admin_headers(client))

    from src.licensing.entitlement import expected_tenant_id
    from src.sso.api import _cargar_config
    db = factory()
    try:
        provider_type, config, secreto = _cargar_config(db, expected_tenant_id())
    finally:
        db.close()

    assert provider_type == "entra"
    assert config["client_id"] == "cli-abc"
    assert secreto == SECRETO


def test_una_config_deshabilitada_no_la_toma_el_flujo(entorno, sso_licenciado, cifrado_disponible):
    """`_cargar_config` filtra por `enabled`: apagar el SSO desde esta API tiene que
    apagarlo en el login, no sólo en la pantalla."""
    client, factory = entorno
    h = admin_headers(client)
    client.put(CONFIG, json=_cuerpo(), headers=h)
    client.put(CONFIG, json=_cuerpo(client_secret=None, enabled=False), headers=h)

    from fastapi import HTTPException
    from src.licensing.entitlement import expected_tenant_id
    from src.sso.api import _cargar_config
    db = factory()
    try:
        with pytest.raises(HTTPException):
            _cargar_config(db, expected_tenant_id())
    finally:
        db.close()


# ── El reparto de rol: `config_producto` (admin RW · auditor R · el resto, nada) ───
#
# Esta superficie NO entra al catálogo de `test_role_matrix.py` porque allá el gate de
# LICENCIA dispararía primero y su `_cumple` no distingue un 403 del otro (mira el texto).
# Acá sí se puede: la licencia está montada CON `sso`, así que el único 403 posible es el
# de rol — y cada caso lo afirma por el texto de `rbac.require_role`.
#
# Lo que el `assert "sso_no_licenciado" not in resp.text` pinea, exactamente, para que no
# prometa de más: el ORDEN. Hoy los dos gates son mutuamente excluyentes (el de licencia va
# en el `include_router`, o sea antes que el de rol), así que ninguna mutación lo deja
# ROJO a él solo. Es un cross-check para el día en que ese orden cambie, no una garantía
# medida. Lo que sí está medido: con la licencia SIN `sso`, los cuatro tests de acá abajo
# se caen — no quedan verdes afirmando un reparto que no se estaría ejerciendo.


def test_el_auditor_LEE_la_config(entorno, sso_licenciado, cifrado_disponible):
    """`config_producto` le da R al compliance_officer: qué IdP está cableado es material
    de auditoría. Y el secreto tampoco sale POR ACÁ — la lectura del auditor es la más
    ancha de la superficie, así que es donde una fuga costaría más."""
    client, factory = entorno
    client.put(CONFIG, json=_cuerpo(), headers=admin_headers(client))

    resp = client.get(CONFIG, headers=headers_for_role(client, factory, Rol.COMPLIANCE_OFFICER))
    assert resp.status_code == 200, resp.text
    assert SECRETO not in resp.text
    assert resp.json()["client_secret_configurado"] is True


def test_el_auditor_NO_escribe_la_config(entorno, sso_licenciado, cifrado_disponible):
    """El auditor es solo-lectura (Regla 1 del contrato 017: perdió toda escritura).
    Ensanchar `_ESCRITURA` a `compliance_officer` dejaría a quien audita el cableado
    del IdP pudiendo cambiarlo — y el cambio quedaría firmado con su propio actor."""
    client, factory = entorno
    h_admin = admin_headers(client)
    client.put(CONFIG, json=_cuerpo(), headers=h_admin)
    antes = _fila(factory).config["client_id"]

    resp = client.put(CONFIG, json=_cuerpo(config={"client_id": "cli-del-auditor"}),
                      headers=headers_for_role(client, factory, Rol.COMPLIANCE_OFFICER))
    assert resp.status_code == 403, resp.text
    assert rechazo_por_rol(Rol.COMPLIANCE_OFFICER) in resp.text
    assert "sso_no_licenciado" not in resp.text          # el 403 es de ROL, no de licencia
    assert _fila(factory).config["client_id"] == antes   # y no escribió nada


@pytest.mark.parametrize("rol", [Rol.CLIENT, Rol.LECTURA])
def test_los_roles_sin_config_producto_ni_leen_ni_escriben(entorno, sso_licenciado,
                                                           cifrado_disponible, rol):
    """`client` y `lectura` son NINGUNO en `config_producto`. Se prueban los DOS verbos:
    el GET y el PUT los gatea cada uno su propio `require_role`, así que ensanchar uno no
    ensancha el otro y un solo caso dejaría medio cableado sin medir."""
    client, factory = entorno
    client.put(CONFIG, json=_cuerpo(), headers=admin_headers(client))
    antes = _fila(factory).config["client_id"]
    h = headers_for_role(client, factory, rol)

    for resp in (client.get(CONFIG, headers=h),
                 client.put(CONFIG, json=_cuerpo(config={"client_id": "cli-del-negado"}),
                            headers=h)):
        assert resp.status_code == 403, resp.text
        assert rechazo_por_rol(rol) in resp.text
        assert "sso_no_licenciado" not in resp.text     # el 403 es de ROL, no de licencia
        assert SECRETO not in resp.text
    assert _fila(factory).config["client_id"] == antes  # el PUT negado no escribió
