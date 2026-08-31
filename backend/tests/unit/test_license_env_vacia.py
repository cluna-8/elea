"""Unit tests: en la superficie de licencia, una variable SETEADA-PERO-VACÍA
cuenta como AUSENTE (spec 021, FR-003/005/018/029).

``os.getenv(V, DEFAULT)`` devuelve ``''`` cuando ``V`` está seteada vacía: el
default del producto queda ANULADO por una línea de config que el operador cree
inerte (``VAR=`` en un ``.env``, un ``environment:`` de compose sin valor). Acá
eso no es cosmético — degrada un deployment sano y, peor, lo hace por el carril
equivocado: ``Path('') → '.'`` levanta ``LicenseReadError``, que ``refresh()``
trata como BLIP TRANSITORIO de I/O y absorbe con histéresis.

Cada test fija UN camino y trae su brazo de control (ausente) o su brazo
anti-vacuidad (un valor real tiene que seguir ganándole al default). Cero red,
cero DB.
"""
from pathlib import Path

import pytest

from license_fixtures import DEFAULT_TENANT_ID, issue_files

from src.licensing import deployment_key, entitlement

OTRO_TENANT = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _no_contaminar_el_singleton():
    """``refresh()``/``initialize()`` escriben el singleton de proceso: soltarlo
    al salir para que el resto de la suite vuelva a la licencia dev del conftest."""
    yield
    entitlement.reset_for_tests()


@pytest.fixture
def env_limpio(monkeypatch):
    """El conftest instala una licencia dev de suite en ``os.environ``; cada
    test parte del estado NO CONFIGURADO y setea sólo lo suyo."""
    for var in ("SENTINEL_LICENSE_TOKEN", "SENTINEL_LICENSE_TOKEN_FILE",
                "SENTINEL_LICENSE_PUBLIC_KEYS_FILE", "SENTINEL_DEPLOYMENT_TENANT_ID",
                "SENTINEL_DEPLOYMENT_KEY_FILE"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _keyset_ajeno(tmp_path):
    """Keyset válido de OTRO firmante: verifica bien, pero no conoce el kid del
    token de la suite → sirve de default distinguible."""
    ajeno = tmp_path / "ajeno"
    ajeno.mkdir()
    keyset_path, _, _ = issue_files(ajeno, kid="sentinel-ajeno")
    return keyset_path


# --- SENTINEL_LICENSE_PUBLIC_KEYS_FILE: vacía ⇒ keyset embebido -------------------

def test_keyset_vacio_cae_al_embebido_igual_que_ausente(env_limpio, tmp_path):
    """ANTES: ``LicenseReadError: keyset ilegible: Is a directory: '.'`` — el
    keyset embebido quedaba anulado y el fallo salía por el carril de I/O."""
    keyset_path, lic_path, _ = issue_files(tmp_path)
    env_limpio.setattr(entitlement, "DEFAULT_KEYSET_PATH", keyset_path)
    env_limpio.setenv("SENTINEL_LICENSE_TOKEN_FILE", str(lic_path))

    ausente = entitlement.evaluate()
    env_limpio.setenv("SENTINEL_LICENSE_PUBLIC_KEYS_FILE", "")
    vacia = entitlement.evaluate()

    assert ausente.status == "active"  # control: el default del producto verifica
    assert (vacia.status, vacia.reason) == (ausente.status, ausente.reason)


def test_keyset_en_blanco_tambien_es_ausente(env_limpio, tmp_path):
    keyset_path, lic_path, _ = issue_files(tmp_path)
    env_limpio.setattr(entitlement, "DEFAULT_KEYSET_PATH", keyset_path)
    env_limpio.setenv("SENTINEL_LICENSE_TOKEN_FILE", str(lic_path))
    env_limpio.setenv("SENTINEL_LICENSE_PUBLIC_KEYS_FILE", "   ")

    assert entitlement.evaluate().status == "active"


def test_keyset_configurado_le_gana_al_default(env_limpio, tmp_path):
    """Anti-vacuidad: 'vacío ⇒ default' no puede degenerar en 'siempre default'.
    El default es un keyset AJENO; sólo la variable lleva al que verifica."""
    keyset_path, lic_path, _ = issue_files(tmp_path)
    env_limpio.setattr(entitlement, "DEFAULT_KEYSET_PATH", _keyset_ajeno(tmp_path))
    env_limpio.setenv("SENTINEL_LICENSE_TOKEN_FILE", str(lic_path))

    env_limpio.setenv("SENTINEL_LICENSE_PUBLIC_KEYS_FILE", str(keyset_path))
    assert entitlement.evaluate().status == "active"

    env_limpio.delenv("SENTINEL_LICENSE_PUBLIC_KEYS_FILE")
    assert entitlement.evaluate().status == "invalid"  # el ajeno no conoce el kid


# --- SENTINEL_DEPLOYMENT_TENANT_ID: vacía ⇒ tenant seed --------------------------

def test_tenant_del_deployment_vacio_es_el_default(env_limpio, tmp_path):
    """ANTES: ``mismatch`` contra un deployment de tenant ``''`` — una licencia
    legítima quedaba repudiada y el motivo auditado decía 'deployment ' (vacío)."""
    keyset_path, lic_path, _ = issue_files(tmp_path)  # token del tenant seed
    env_limpio.setenv("SENTINEL_LICENSE_PUBLIC_KEYS_FILE", str(keyset_path))
    env_limpio.setenv("SENTINEL_LICENSE_TOKEN_FILE", str(lic_path))

    env_limpio.setenv("SENTINEL_DEPLOYMENT_TENANT_ID", "")
    assert entitlement.expected_tenant_id() == DEFAULT_TENANT_ID
    assert entitlement.evaluate().status == "active"


def test_tenant_del_deployment_configurado_le_gana_al_default(env_limpio, tmp_path):
    """Anti-vacuidad: el mismatch de tenant (FR-005) tiene que seguir vivo."""
    keyset_path, lic_path, _ = issue_files(tmp_path)
    env_limpio.setenv("SENTINEL_LICENSE_PUBLIC_KEYS_FILE", str(keyset_path))
    env_limpio.setenv("SENTINEL_LICENSE_TOKEN_FILE", str(lic_path))

    env_limpio.setenv("SENTINEL_DEPLOYMENT_TENANT_ID", OTRO_TENANT)
    assert entitlement.evaluate().status == "mismatch"


# --- SENTINEL_LICENSE_TOKEN_FILE: en blanco ⇒ token no configurado ---------------

def test_token_file_en_blanco_es_token_ausente(env_limpio, tmp_path):
    """``' '`` pasaba el ``if path:`` y moría en el read → LicenseReadError
    (carril de blip) en vez del ``missing`` honesto de 'no lo configuraste'."""
    keyset_path, _, _ = issue_files(tmp_path)
    env_limpio.setenv("SENTINEL_LICENSE_PUBLIC_KEYS_FILE", str(keyset_path))
    env_limpio.setenv("SENTINEL_LICENSE_TOKEN_FILE", "   ")

    assert entitlement.evaluate().status == "missing"


# --- SENTINEL_DEPLOYMENT_KEY_FILE: vacía ⇒ path default --------------------------

def test_deployment_key_vacia_es_el_path_default(env_limpio):
    """ANTES: ``Path('')`` → ``'.'``; ``exists()`` da True sobre el cwd y la
    carga de la privada muere leyendo un directorio (true-up sin firma)."""
    env_limpio.setenv("SENTINEL_DEPLOYMENT_KEY_FILE", "")
    assert deployment_key.key_path() == Path(deployment_key.DEFAULT_KEY_PATH)


def test_deployment_key_configurada_le_gana_al_default(env_limpio, tmp_path):
    propia = tmp_path / "deployment_key.pem"
    env_limpio.setenv("SENTINEL_DEPLOYMENT_KEY_FILE", str(propia))
    assert deployment_key.key_path() == propia


# --- Por qué importa en RUNTIME ----------------------------------------------

def test_config_vacia_no_se_lava_como_blip_de_io(env_limpio, tmp_path):
    """La histéresis de ``refresh()`` existe para blips de I/O (rotación de
    secret no atómica, volumen): conserva un estado con firma validada hasta
    READ_FAILURE_TOLERANCE ticks. Un error de CONFIGURACIÓN no es transitorio —
    si entra por ese carril, el sistema sostiene un ``active`` viejo y audita
    'ilegible (I/O)', que manda a mirar el volumen en vez del ``.env``.
    """
    keyset_path, lic_path, _ = issue_files(tmp_path)
    env_limpio.setattr(entitlement, "DEFAULT_KEYSET_PATH", _keyset_ajeno(tmp_path))
    env_limpio.setenv("SENTINEL_LICENSE_PUBLIC_KEYS_FILE", str(keyset_path))
    env_limpio.setenv("SENTINEL_LICENSE_TOKEN_FILE", str(lic_path))
    env_limpio.setattr("src.licensing.audit_events.emit_state_event",
                       lambda *a, **k: None)

    assert entitlement.initialize(force=True, emit_audit=False).status == "active"

    env_limpio.setenv("SENTINEL_LICENSE_PUBLIC_KEYS_FILE", "")  # el operador 'declara' la var
    primer_tick = entitlement.refresh()

    assert primer_tick.status != "active", "conservó el estado viejo: entró por el carril de blip"
    assert "I/O" not in (primer_tick.reason or ""), "culpó a I/O un problema de configuración"
