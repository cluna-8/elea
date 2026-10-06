"""`/internal/model-credential` cerrada sin la ruta directa (057 T090; QA A10, FR-013; research R31).

La credencial **descifrada** de un destino solo sale por esta ruta HTTP para el guard del motor cuando el operador
encendió la ruta directa (`CATALOG_DIRECT_ENABLED`, vacía en Eleia). Sin ella, 404 aun con el secreto interno
correcto: lo que no se enciende no se expone. La llamada **en proceso** del chat de la consola
(`sentinel/catalog/chat_route.py`) sigue funcionando sin pasar por la ruta HTTP, y las tres rutas de la extensión
dependen de la misma `_require_internal_secret` de la base (todo chequeo que gane la base —p. ej. el de origen de red,
S15— les aplica por igual).
"""
import uuid

import pytest
from fastapi.routing import APIRoute

from sentinel.catalog.api import internal
from sentinel.tests.catalog_fixtures import T1, create_entry, make_api

INTERNAL = "interno-compartido-de-prueba"


@pytest.fixture
def api(monkeypatch):
    a = make_api(monkeypatch)
    monkeypatch.setattr(internal, "SESSION_FACTORY", a.Session)
    monkeypatch.setattr(internal, "DECRYPT", lambda b: b[len("cifrado:"):][::-1])
    monkeypatch.setattr(internal, "TODAY", lambda: __import__("datetime").date(2026, 10, 1))
    monkeypatch.setattr(internal, "VERSION", _Version())
    monkeypatch.setenv("SENTINEL_ENGINE_MASTER_KEY", INTERNAL)
    monkeypatch.delenv("CATALOG_DIRECT_ENABLED", raising=False)
    a.entry = create_entry(a, "tenant_admin", T1, provider="anthropic", protocol_family="anthropic_messages",
                           real_model="modelo-x", name="Modelo X",
                           credential={"new": {"name": "c-x", "value": "valor-inventado-de-prueba"}})
    return a


class _Version:
    def current(self, tenant):
        return 1

    def bump(self, tenant=None):
        pass


def _cred(api, secret=INTERNAL, entry_id=None):
    h = {"X-Sentinel-Internal": secret} if secret is not None else {}
    q = f"tenant={T1}&entry_id={entry_id or api.entry['id']}"
    return api.call("GET", f"/model-credential?{q}", None, prefix="/api/v1/internal", headers=h)


# ── cerrada sin la ruta directa ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("valor", [None, "", "0", "false", "no", "  "])
def test_sin_la_ruta_directa_responde_404_aun_con_el_secreto_correcto(api, monkeypatch, valor):
    if valor is not None:
        monkeypatch.setenv("CATALOG_DIRECT_ENABLED", valor)
    r = _cred(api)
    assert r.status_code == 404 and "credential" not in r.text and "valor-inventado" not in r.text


def test_el_404_es_el_mismo_con_y_sin_secreto_y_sin_entrada(api):
    cuerpos = {_cred(api).text, _cred(api, secret=None).text, _cred(api, secret="otro").text,
               _cred(api, entry_id=uuid.uuid4()).text}
    assert len(cuerpos) == 1                       # desde fuera, la ruta no existe: no se distingue nada


@pytest.mark.parametrize("valor", ["1", "true", "TRUE", "yes", " Yes "])
def test_con_la_ruta_directa_responde_como_hoy(api, monkeypatch, valor):
    monkeypatch.setenv("CATALOG_DIRECT_ENABLED", valor)
    r = _cred(api)
    assert r.status_code == 200 and r.json() == {"credential": {"api_key": "valor-inventado-de-prueba"}}
    assert "no-store" in r.headers["cache-control"]


def test_con_la_ruta_directa_sigue_exigiendo_el_secreto(api, monkeypatch):
    monkeypatch.setenv("CATALOG_DIRECT_ENABLED", "1")
    assert _cred(api, secret=None).status_code == 404 and _cred(api, secret="otro").status_code == 404


def test_apagarla_de_nuevo_la_cierra_sin_reiniciar(api, monkeypatch):
    monkeypatch.setenv("CATALOG_DIRECT_ENABLED", "1")
    assert _cred(api).status_code == 200
    monkeypatch.delenv("CATALOG_DIRECT_ENABLED")
    assert _cred(api).status_code == 404


# ── la llamada en proceso del chat de la consola no depende de la ruta HTTP ───────────────────────

def test_el_chat_de_la_consola_obtiene_la_credencial_en_proceso_con_la_ruta_apagada(api):
    from sentinel.catalog import chat_route
    assert chat_route._credential(str(T1), api.entry["id"]) == {"api_key": "valor-inventado-de-prueba"}


def test_la_funcion_en_proceso_no_exige_la_ruta_directa(api):
    from fastapi import Response
    out = internal.model_credential(Response(), tenant=T1, entry_id=uuid.UUID(api.entry["id"]))
    assert out == {"credential": {"api_key": "valor-inventado-de-prueba"}}


# ── el catálogo y el acceso no devuelven secretos y comparten la dependencia de la base ──────────

def test_las_tres_rutas_internas_dependen_de_la_misma_dependencia_de_la_base():
    from src.api.internal import _require_internal_secret
    rutas = {r.path: r for r in internal.router.routes if isinstance(r, APIRoute)}
    for path in ("/internal/model-catalog", "/internal/model-access", "/internal/model-credential"):
        deps = {d.call for d in rutas[path].dependant.dependencies}
        assert _require_internal_secret in deps, path


def test_model_catalog_y_model_access_no_devuelven_credenciales(api, monkeypatch):
    monkeypatch.setenv("CATALOG_DIRECT_ENABLED", "")
    h = {"X-Sentinel-Internal": INTERNAL}
    r = api.call("GET", f"/model-catalog?tenant={T1}", None, prefix="/api/v1/internal", headers=h)
    assert r.status_code == 200 and "valor-inventado" not in r.text and "api_key" not in r.text
    r = api.call("GET", f"/model-access?tenant={T1}", None, prefix="/api/v1/internal", headers=h)
    assert "valor-inventado" not in r.text


def test_sin_el_secreto_las_tres_rutas_responden_404(api):
    for ruta in (f"model-catalog?tenant={T1}", f"model-access?tenant={T1}",
                 f"model-credential?tenant={T1}&entry_id={api.entry['id']}"):
        assert api.call("GET", "/" + ruta, None, prefix="/api/v1/internal").status_code == 404, ruta
