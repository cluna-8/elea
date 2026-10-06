"""Capa de ORIGEN del plano interno (`/api/v1/internal/*`): `INTERNAL_ALLOWED_CIDRS`.

Hasta acá el plano interno se defendía con dos cosas: el ingress lo niega con 404 y el secreto
compartido (`SENTINEL_ENGINE_MASTER_KEY`). La segunda capa exige además que quien llama venga
de una red permitida: un secreto filtrado, usado desde fuera de la red de compose, deja de
servir. Qué se prueba acá, sin Postgres ni Docker (la app mínima monta el router REAL con la
sesión doblada):

- sin la variable (o vacía) el comportamiento es el de siempre (retrocompatible);
- con la variable: pasa desde dentro de la lista, 403 desde fuera AUNQUE traiga el secreto;
- el orden de las capas: sin secreto sigue siendo el 404 de siempre (no se revela que existe);
- fail-closed: una lista mal escrita o un origen que no es IP niegan, no abren;
- `auto` = las subredes conectadas del propio contenedor (leídas de la tabla de rutas).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from src.api import internal  # noqa: E402
from src.database import get_db  # noqa: E402

SECRETO = "secreto-interno-de-la-suite-capa-2"
CABECERA = {"X-Sentinel-Internal": SECRETO}
PROBE = "/api/v1/internal/audit/probe"

# `/proc/net/route` de un contenedor en una red de compose: la subred conectada
# (172.18.0.0/16, máscara 0000FFFF en little-endian), la ruta por defecto vía el gateway
# 172.18.0.1 y una ruta de loopback que no debe contar.
RUTAS_COMPOSE = (
    "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
    "eth0\t00000000\t010012AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
    "eth0\t000012AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n"
    "lo\t0000007F\t00000000\t0001\t0\t0\t0\t000000FF\t0\t0\t0\n"
)


def _app_desde(ip_origen):
    """App mínima con el router interno REAL y un ASGI que fija el `client` del scope: es el
    único modo de simular el origen de la conexión, que `TestClient` fija en «testclient»."""
    app = FastAPI()
    app.include_router(internal.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: MagicMock()

    async def con_origen(scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope, client=(ip_origen, 50000) if ip_origen else None)
        await app(scope, receive, send)

    return TestClient(con_origen)


@pytest.fixture(autouse=True)
def _secreto(monkeypatch):
    monkeypatch.setenv("SENTINEL_ENGINE_MASTER_KEY", SECRETO)
    monkeypatch.delenv("INTERNAL_ALLOWED_CIDRS", raising=False)


# ── Sin la variable: como hoy ────────────────────────────────────────────────────────


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_sin_variable_o_vacia_no_hay_chequeo_de_origen(monkeypatch, valor):
    if valor is not None:
        monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", valor)
    for origen in ("8.8.8.8", "testclient", None):
        assert _app_desde(origen).get(PROBE, headers=CABECERA).status_code == 200


def test_sin_variable_el_secreto_sigue_mandando(monkeypatch):
    assert _app_desde("8.8.8.8").get(PROBE).status_code == 404


# ── Con la variable: lista de CIDR ──────────────────────────────────────────────────


def test_pasa_desde_la_red_interna(monkeypatch):
    monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", "172.18.0.0/16")
    assert _app_desde("172.18.0.7").get(PROBE, headers=CABECERA).status_code == 200


def test_403_desde_afuera_aunque_traiga_el_secreto(monkeypatch):
    monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", "172.18.0.0/16")
    resp = _app_desde("203.0.113.9").get(PROBE, headers=CABECERA)
    assert resp.status_code == 403
    assert CABECERA["X-Sentinel-Internal"] not in resp.text


def test_sin_secreto_desde_afuera_es_404_no_403(monkeypatch):
    """El 403 solo lo ve quien ya conoce el secreto: sin él el endpoint «no existe»."""
    monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", "172.18.0.0/16")
    assert _app_desde("203.0.113.9").get(PROBE).status_code == 404


def test_varios_cidr_con_espacios_y_ipv6(monkeypatch):
    monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", " 10.0.0.0/8 , 172.18.0.0/16,fd00::/8 ")
    for origen in ("10.9.9.9", "172.18.5.5", "fd00::1"):
        assert _app_desde(origen).get(PROBE, headers=CABECERA).status_code == 200, origen
    assert _app_desde("192.168.1.1").get(PROBE, headers=CABECERA).status_code == 403


def test_ipv4_mapeada_en_ipv6_cuenta_como_la_ipv4(monkeypatch):
    monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", "172.18.0.0/16")
    assert _app_desde("::ffff:172.18.0.7").get(PROBE, headers=CABECERA).status_code == 200
    assert _app_desde("::ffff:203.0.113.9").get(PROBE, headers=CABECERA).status_code == 403


def test_ip_suelta_sin_mascara_es_un_host(monkeypatch):
    monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", "172.18.0.7")
    assert _app_desde("172.18.0.7").get(PROBE, headers=CABECERA).status_code == 200
    assert _app_desde("172.18.0.8").get(PROBE, headers=CABECERA).status_code == 403


@pytest.mark.parametrize("origen", ["testclient", "no-es-una-ip", None])
def test_origen_que_no_es_ip_se_niega(monkeypatch, origen):
    monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", "0.0.0.0/0")
    assert _app_desde(origen).get(PROBE, headers=CABECERA).status_code == 403


@pytest.mark.parametrize("valor", ["esto-no-es-un-cidr", "172.18.0.0/16,basura", "300.1.1.1/8"])
def test_lista_mal_escrita_niega_todo_en_vez_de_abrir(monkeypatch, valor):
    monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", valor)
    assert _app_desde("172.18.0.7").get(PROBE, headers=CABECERA).status_code == 403


# ── Todas las rutas del router quedan cubiertas ─────────────────────────────────────


@pytest.mark.parametrize("metodo,ruta,extra", [
    ("get", "/api/v1/internal/verify-user?user_id=u&tenant_id=t", {}),
    ("get", "/api/v1/internal/identity?key_hash=" + "a" * 64, {}),
    ("get", PROBE, {}),
    ("post", "/api/v1/internal/audit", {"json": {"model": "m", "compliance_status": "allowed"}}),
])
def test_cada_ruta_del_router_exige_el_origen(monkeypatch, metodo, ruta, extra):
    monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", "172.18.0.0/16")
    resp = getattr(_app_desde("203.0.113.9"), metodo)(ruta, headers=CABECERA, **extra)
    assert resp.status_code == 403, (ruta, resp.status_code)


def test_toda_ruta_futura_del_router_hereda_la_capa():
    """La capa es del ROUTER, no de cada ruta: una ruta nueva no puede olvidarla."""
    assert any(d.dependency is internal._require_internal_origen
               for d in internal.router.dependencies)


# ── `auto`: la subred del propio contenedor ─────────────────────────────────────────


def test_parser_de_rutas_devuelve_solo_las_subredes_conectadas():
    redes = internal._redes_conectadas(RUTAS_COMPOSE)
    assert [str(r) for r in redes] == ["172.18.0.0/16"]


def test_parser_tolera_vacio_y_basura():
    assert internal._redes_conectadas("") == []
    assert internal._redes_conectadas("Iface\tDestination\nbasura sin columnas\n") == []


def test_auto_permite_la_subred_de_compose(monkeypatch):
    monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", "auto")
    monkeypatch.setattr(internal, "_leer_tabla_de_rutas", lambda: RUTAS_COMPOSE)
    assert _app_desde("172.18.0.7").get(PROBE, headers=CABECERA).status_code == 200
    assert _app_desde("203.0.113.9").get(PROBE, headers=CABECERA).status_code == 403


def test_auto_sin_rutas_legibles_niega_en_vez_de_abrir(monkeypatch):
    monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", "auto")
    monkeypatch.setattr(internal, "_leer_tabla_de_rutas", lambda: "")
    assert _app_desde("172.18.0.7").get(PROBE, headers=CABECERA).status_code == 403


def test_auto_se_combina_con_cidr_explicitos(monkeypatch):
    monkeypatch.setenv("INTERNAL_ALLOWED_CIDRS", "auto, 10.0.0.0/8")
    monkeypatch.setattr(internal, "_leer_tabla_de_rutas", lambda: RUTAS_COMPOSE)
    assert _app_desde("172.18.0.7").get(PROBE, headers=CABECERA).status_code == 200
    assert _app_desde("10.1.1.1").get(PROBE, headers=CABECERA).status_code == 200
    assert _app_desde("192.168.1.1").get(PROBE, headers=CABECERA).status_code == 403
