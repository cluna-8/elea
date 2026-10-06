"""Rotación de la clave de cifrado sin perder datos (069 D3, FR-005; T018).

`FERNET_SECRET_KEY` cifra; `FERNET_PREVIOUS_KEYS` (coma-separadas) solo descifra. Una clave
faltante NO puede degradar en silencio: `descifrar_estricto` levanta un error visible.
"""

import pytest
from cryptography.fernet import Fernet


class _Svc:
    """El módulo real con un `_fernet` armado a medida (sin recargar el módulo: recargarlo crearía
    clases de excepción nuevas y los `pytest.raises` de otros tests dejarían de coincidir)."""

    def __init__(self, monkeypatch, actual, previas=()):
        from src.services import encryption_service as m
        self._m = m
        monkeypatch.setattr(m, "_fernet", m._construir(actual, list(previas)))

    def __getattr__(self, name):
        return getattr(self._m, name)


def _cargar(monkeypatch, actual, previas=""):
    return _Svc(monkeypatch, actual, [k for k in previas.split(",") if k])


def test_una_sola_clave_sigue_funcionando_como_antes(monkeypatch):
    k = Fernet.generate_key().decode()
    svc = _cargar(monkeypatch, k)
    assert svc.decrypt(svc.encrypt("sk-secreto")) == "sk-secreto"
    assert Fernet(k.encode()).decrypt(svc.encrypt("x").encode()) == b"x"   # mismo formato Fernet


def test_dato_cifrado_con_la_clave_vieja_se_lee_tras_rotar(monkeypatch):
    vieja, nueva = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token_viejo = _cargar(monkeypatch, vieja).encrypt("sk-secreto")
    svc = _cargar(monkeypatch, nueva, vieja)
    assert svc.decrypt(token_viejo) == "sk-secreto"


def test_lo_nuevo_se_cifra_con_la_clave_actual(monkeypatch):
    vieja, nueva = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    svc = _cargar(monkeypatch, nueva, vieja)
    token = svc.encrypt("sk-nuevo")
    assert Fernet(nueva.encode()).decrypt(token.encode()) == b"sk-nuevo"
    with pytest.raises(Exception):
        Fernet(vieja.encode()).decrypt(token.encode())


def test_rotar_recifra_con_la_clave_actual(monkeypatch):
    vieja, nueva = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token_viejo = _cargar(monkeypatch, vieja).encrypt("sk-secreto")
    svc = _cargar(monkeypatch, nueva, vieja)
    recifrado = svc.rotar(token_viejo)
    assert Fernet(nueva.encode()).decrypt(recifrado.encode()) == b"sk-secreto"


def test_clave_faltante_es_error_visible_en_modo_estricto(monkeypatch):
    vieja, nueva = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token_viejo = _cargar(monkeypatch, vieja).encrypt("sk-secreto")
    svc = _cargar(monkeypatch, nueva)                       # se olvidó la clave vieja
    assert svc.decrypt(token_viejo) is None                 # contrato histórico: fail-closed
    with pytest.raises(svc.ClaveDeCifradoFaltante):
        svc.descifrar_estricto(token_viejo)


def test_clave_previa_invalida_se_ignora_con_aviso_y_no_rompe_la_actual(monkeypatch):
    k = Fernet.generate_key().decode()
    svc = _cargar(monkeypatch, k, "esto-no-es-una-clave")
    assert svc.decrypt(svc.encrypt("sk")) == "sk"


def test_sin_cifrado_el_estricto_levanta_cifrado_no_disponible(monkeypatch):
    svc = _cargar(monkeypatch, "")
    with pytest.raises(svc.CifradoNoDisponible):
        svc.descifrar_estricto("gAAAAA")
