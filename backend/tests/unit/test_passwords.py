"""Unit del módulo de contraseñas (``src/auth/passwords.py``).

Lo que se fija acá es el contrato que hace posible cambiar el formato de almacenamiento sin
un script de migración: bcrypt para lo nuevo, lectura del sha256 legacy para lo que ya está
en las tablas de los despliegues entregados, y **cero excepciones** ante un
``password_hash`` que no es ninguno de los dos (hay filas así en producción a propósito:
los clientes sembrados llevan un centinela porque no loguean con contraseña).
"""
import asyncio
import hashlib
import threading

import pytest

from src.auth import passwords
from src.auth.passwords import (MIN_PASSWORD_LEN, hash_password, necesita_rehash,
                                validar_password, verify_password)

CLAVE = "clave-de-prueba-valida"


def _legacy(raw):
    """El formato viejo tal cual lo escribía el backend: sha256 hex, sin sal."""
    return hashlib.sha256(raw.encode()).hexdigest()


# Todo lo que puede aparecer en password_hash y NO es un hash verificable. Las dos primeras
# son literales de producción (onboarding.seed_client y los fixtures e2e).
BASURA = [
    "!seeded-client-no-login",
    "!e2e-no-login",
    "x",
    "",
    None,
    "$2b$12$truncado",
    _legacy(CLAVE)[:63],          # sha256 al que le falta un caracter
    _legacy(CLAVE) + "0",         # sha256 con uno de más
    "zz" + _legacy(CLAVE)[2:],    # 64 caracteres pero no hex
]


# ── bcrypt ────────────────────────────────────────────────────────────────────────


def test_round_trip_bcrypt():
    almacenado = hash_password(CLAVE)

    assert almacenado.startswith("$2")
    assert CLAVE not in almacenado
    assert verify_password(CLAVE, almacenado) is True
    assert verify_password("otra-clave-valida", almacenado) is False


def test_dos_hashes_de_la_misma_clave_son_distintos():
    """La sal es la mitad del arreglo: con sha256, dos usuarios con la misma contraseña
    tenían el mismo hash y una sola tabla precomputada abría las dos cuentas."""
    assert hash_password(CLAVE) != hash_password(CLAVE)


def test_clave_mas_larga_que_el_limite_de_bcrypt_no_revienta():
    """bcrypt lanza ValueError arriba de 72 bytes en vez de ignorar el sobrante: sin el
    recorte del módulo, una contraseña larga sería un 500 en el alta."""
    larga = "á" * 80  # 160 bytes en utf-8

    almacenado = hash_password(larga)

    assert verify_password(larga, almacenado) is True


# ── legacy sha256 ─────────────────────────────────────────────────────────────────


def test_verify_acepta_el_legacy_sha256():
    """Los usuarios ya cargados siguen entrando: sin esto, actualizar el backend los deja
    afuera a todos."""
    assert verify_password(CLAVE, _legacy(CLAVE)) is True
    assert verify_password("otra-clave-valida", _legacy(CLAVE)) is False


def test_verify_acepta_el_legacy_en_mayusculas():
    """Defensivo: el hex es el mismo valor escrito de otra forma."""
    assert verify_password(CLAVE, _legacy(CLAVE).upper()) is True


def test_necesita_rehash_distingue_los_formatos():
    assert necesita_rehash(_legacy(CLAVE)) is True
    assert necesita_rehash(hash_password(CLAVE)) is False


@pytest.mark.parametrize("almacenado", BASURA)
def test_necesita_rehash_no_marca_basura(almacenado):
    """Un centinela no es un hash legacy: marcarlo haría que el login lo "migrara"."""
    assert necesita_rehash(almacenado) is False


# ── hashes que no son hashes ───────────────────────────────────────────────────────


@pytest.mark.parametrize("almacenado", BASURA)
def test_verify_devuelve_false_sin_excepcion(almacenado):
    """Un ``password_hash`` con formato desconocido es "esta cuenta no loguea", no un 500."""
    assert verify_password(CLAVE, almacenado) is False


# ── política de longitud ──────────────────────────────────────────────────────────


def test_validar_password_acepta_el_minimo():
    validar_password("a" * MIN_PASSWORD_LEN)  # no lanza


@pytest.mark.parametrize("corta", ["", "a" * (MIN_PASSWORD_LEN - 1), None])
def test_validar_password_rechaza_lo_corto_en_espanol(corta):
    with pytest.raises(ValueError) as exc:
        validar_password(corta)

    mensaje = str(exc.value)
    assert str(MIN_PASSWORD_LEN) in mensaje
    assert "contraseña" in mensaje.lower()


# ── executor dedicado de bcrypt (#167) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hash_password_async_corre_en_el_executor_dedicado(monkeypatch):
    """Causa raíz #167: el bcrypt del login sale del threadpool anyio COMPARTIDO (el que el
    gateway necesita para su auditoría/rechazo vía ``run_in_threadpool``) y va a
    ``_BCRYPT_EXECUTOR``, hilos ``bcrypt_*``. Si alguien lo devuelve al pool general o lo corre
    sync en el event loop, el nombre del hilo deja de empezar con ``bcrypt`` y esto rojea."""
    hilos = []

    def _spy(raw):
        hilos.append(threading.current_thread().name)
        return "hash-de-mentira"

    monkeypatch.setattr(passwords, "hash_password", _spy)

    out = await passwords.hash_password_async(CLAVE)

    assert out == "hash-de-mentira"
    assert hilos, "hash_password nunca corrió"
    assert hilos[0].startswith("bcrypt"), f"corrió en {hilos[0]!r}, no en el executor dedicado"


@pytest.mark.asyncio
async def test_verify_password_async_corre_en_el_executor_dedicado(monkeypatch):
    """Igual que el hash: la verificación del login se offloadea a ``_BCRYPT_EXECUTOR``."""
    hilos = []

    def _spy(raw, stored):
        hilos.append(threading.current_thread().name)
        return True

    monkeypatch.setattr(passwords, "verify_password", _spy)

    ok = await passwords.verify_password_async(CLAVE, "hash-cualquiera")

    assert ok is True
    assert hilos and hilos[0].startswith("bcrypt"), hilos


@pytest.mark.asyncio
async def test_las_wrappers_async_no_cambian_el_resultado():
    """El offload es sólo de HILO: el hash async es un bcrypt real y verificable, y la
    verificación async da lo mismo que la sync (round-trip contra `verify_password`)."""
    almacenado = await passwords.hash_password_async(CLAVE)

    assert almacenado.startswith("$2")
    assert verify_password(CLAVE, almacenado) is True
    assert await passwords.verify_password_async(CLAVE, almacenado) is True
    assert await passwords.verify_password_async("otra-clave-valida", almacenado) is False


@pytest.mark.parametrize("valor,esperado", [("1", 1), ("2", 2), ("99", 4)])
def test_bcrypt_workers_respeta_y_clampea_el_override(monkeypatch, valor, esperado):
    """``SENTINEL_BCRYPT_WORKERS`` overridea el default, topeado a 4 (bcrypt es CPU-bound: más de 4
    hilos sólo agrega contención)."""
    monkeypatch.setenv("SENTINEL_BCRYPT_WORKERS", valor)
    assert passwords._bcrypt_workers() == esperado


@pytest.mark.parametrize("basura", ["", "basura", "0", "-3", "3.5"])
def test_bcrypt_workers_cae_al_default_sin_reventar(monkeypatch, basura):
    """Un valor ausente/vacío/malformado/fuera de rango NO tumba el arranque: cae a un valor
    seguro en [1, 4]. Un typo en el env no debe voltear el login."""
    monkeypatch.setenv("SENTINEL_BCRYPT_WORKERS", basura)
    n = passwords._bcrypt_workers()
    assert 1 <= n <= 4


@pytest.mark.asyncio
async def test_el_hash_async_no_bloquea_el_event_loop():
    """Testigo (P2a): mientras el hash de bcrypt corre en el executor dedicado, el event loop
    tiene que seguir despachando otras tareas. Una tarea testigo de 10 ms DEBE completar ANTES
    que el hash (bcrypt a coste 12 tarda cientos de ms). Si alguien volviera el wrapper
    bloqueante (`.result()` en vez de `await run_in_executor`), el hash monopolizaría el loop
    y el testigo terminaría DESPUÉS → este test lo caza; los spy-tests de arriba no, porque no
    miden tiempo y darían verde igual con un `.result()`."""
    orden = []

    async def _testigo():
        await asyncio.sleep(0.01)
        orden.append("testigo")

    async def _hashear():
        await passwords.hash_password_async(CLAVE)
        orden.append("hash")

    await asyncio.gather(_hashear(), _testigo())

    assert orden[0] == "testigo", f"el event loop se bloqueó durante el hash: {orden}"
