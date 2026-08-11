"""Tests de la reconciliación real (spec 035, T031) — con sesión HTTP MOCKEADA.

Frontera del módulo (DevFlow §3): pytest prueba el instrumento sin backend. Acá se cubre
lo que decide un veredicto:

- los totales salen de los filtros correctos (bloqueados + permitidos = tráfico, sin los
  eslabones ``model='license'``) y la ventana viaja en los params;
- fail-closed en TODOS los caminos por los que el módulo podría mentir: credencial mala,
  GET que falla, respuesta sin ``total``, filtro de fechas ignorado, contador de k6
  ausente, bloqueos que el guion no vio;
- el formato de fecha del wire es el que la columna naive del producto entiende.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from basa_harness.reconcile import (AUDIT_PATH, LOGIN_PATH, HttpReconcile, ReconcileError,
                                    build_http_reconcile, credential_from_pool)

T0 = datetime(2026, 8, 11, 9, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=30)

BACKEND = "http://sut.itv.internal:8000"


# ── doble de la sesión HTTP (estilo httpx: .request(method, url, **kw)) ────────────────

class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no es JSON")
        return self._payload


class FakeSession:
    """Devuelve totales por FILTRO: cada combinación de params tiene su propio conteo.

    Modela lo que hace ``_build_query``: la ventana acota, ``estado`` parte el universo
    del tráfico (sin los eslabones de licencia) y ``compliance_status`` filtra exacto.
    """

    def __init__(self, *, bloqueados=0, permitidos=0, rejected=0, licencia=0,
                 login_status=200, audit_status=200, total_override=..., ignora_ventana=False):
        self.bloqueados = bloqueados
        self.permitidos = permitidos
        self.rejected = rejected
        self.licencia = licencia          # eslabones model='license' de la hash-chain
        self.login_status = login_status
        self.audit_status = audit_status
        self.total_override = total_override
        self.ignora_ventana = ignora_ventana   # modela el `except ValueError: pass`
        self.calls: list = []

    def request(self, method, url, **kw):
        self.calls.append({"method": method, "url": url, **kw})
        if url.endswith(LOGIN_PATH):
            if self.login_status != 200:
                return FakeResponse(self.login_status, {"detail": "credenciales inválidas"})
            return FakeResponse(200, {"access_token": "tok-compliance"})
        assert url.endswith(AUDIT_PATH), f"URL inesperada: {url}"
        if self.audit_status >= 400:
            return FakeResponse(self.audit_status, {"detail": "sin permiso"})
        if self.total_override is not ...:
            return FakeResponse(200, {"total": self.total_override, "logs": []})
        return FakeResponse(200, {"total": self._total(kw.get("params") or {}), "logs": []})

    def _total(self, params):
        futuro = str(params.get("from_date", "")).startswith("2999")
        if futuro and not self.ignora_ventana:
            return 0                       # ventana imposible → nada
        estado = params.get("estado")
        status = params.get("compliance_status")
        if status is not None:
            return self.rejected
        if estado == "bloqueados":
            return self.bloqueados
        if estado == "permitidos":
            return self.permitidos
        # sin `estado`: el universo incluye los eslabones de licencia (lo que NO queremos)
        return self.bloqueados + self.permitidos + self.licencia


def _summary(auditable=100, blocks=0):
    return {"schema": "basa-harness/k6-summary@1", "auditable_events": auditable,
            "observed_blocks": blocks, "provoked_blocks": blocks}


def _fn(session, **kw):
    fn = build_http_reconcile(BACKEND, "itv-g125-cmp-0000", "Itv-secreta", session=session,
                              **kw)
    fn.set_window(T0, T1)
    return fn


def _audit_calls(session):
    return [c for c in session.calls if c["url"].endswith(AUDIT_PATH)]


# ── camino feliz: los totales y de dónde salen ────────────────────────────────────────

def test_cuenta_trafico_como_bloqueados_mas_permitidos():
    # 2 filas de la hash-chain de licencias en la misma ventana: NO son tráfico y no deben
    # sumar (si sumaran, taparían filas de tráfico perdidas → PASS regalado del SLO (b)).
    session = FakeSession(bloqueados=6, permitidos=94, rejected=0, licencia=2)
    recon = _fn(session)(_summary(auditable=100, blocks=6))

    assert recon["filas_persistidas"] == 100          # 6 + 94, sin los 2 de licencia
    assert recon["eventos_guion"] == 100
    assert recon["con_fila"] == 6
    assert recon["bloqueos_provocados"] == 6
    assert recon["filas_rejected_saturated"] == 0
    assert recon["desglose"] == {"filas_bloqueadas": 6, "filas_permitidas": 94}


def test_el_total_sin_estado_habria_inflado_las_filas():
    """Contrafáctico explícito de la decisión de filtro: el universo sin `estado` incluye
    los eslabones `model='license'`, que el filtro `estado` excluye a propósito."""
    session = FakeSession(bloqueados=0, permitidos=98, licencia=2)
    recon = _fn(session)(_summary(auditable=100, blocks=0))
    # El producto perdió 2 filas de tráfico (98 de 100) → el SLO (b) tiene que verlo.
    assert recon["filas_persistidas"] == 98
    # Sin el filtro, el mismo backend habría devuelto 100 y el examen habría "cuadrado".
    assert session._total({}) == 100


def test_la_ventana_viaja_en_los_params_y_en_formato_naive_utc():
    session = FakeSession(bloqueados=1, permitidos=1)
    _fn(session)(_summary(auditable=2, blocks=1))
    reales = [c for c in _audit_calls(session)
              if not str(c["params"]["from_date"]).startswith("2999")]
    assert reales, "no se consultó la ventana real"
    for c in reales:
        assert c["params"]["from_date"] == "2026-08-11T09:00:00"   # naive: columna naive
        assert c["params"]["to_date"] == "2026-08-11T09:30:00"
        assert "+00:00" not in c["params"]["from_date"] and "Z" not in c["params"]["from_date"]
        assert c["params"]["limit"] == 1                            # no se pagina
        assert c["headers"]["Authorization"] == "Bearer tok-compliance"


def test_los_tres_filtros_se_piden_siempre():
    session = FakeSession(bloqueados=3, permitidos=7, rejected=5)
    recon = _fn(session)(_summary(auditable=10, blocks=3))
    params = [c["params"] for c in _audit_calls(session)]
    assert {"bloqueados", "permitidos"} <= {p.get("estado") for p in params}
    assert "rejected_saturated" in {p.get("compliance_status") for p in params}
    # el contrato pide el conteo de rechazos SIEMPRE, aunque hoy el core no los escriba
    assert recon["filas_rejected_saturated"] == 5


def test_ventana_iso_string_tambien_vale():
    session = FakeSession(bloqueados=0, permitidos=4)
    fn = build_http_reconcile(BACKEND, "u", "p", session=session)
    fn.set_window("2026-08-11T09:00:00Z", "2026-08-11T09:30:00+00:00")
    recon = fn(_summary(auditable=4))
    assert recon["ventana"] == {"desde": "2026-08-11T09:00:00+00:00",
                                "hasta": "2026-08-11T09:30:00+00:00"}


def test_login_una_sola_vez_y_con_la_credencial_del_pool():
    session = FakeSession(bloqueados=0, permitidos=1)
    fn = _fn(session)
    fn(_summary(auditable=1))
    fn(_summary(auditable=1))
    logins = [c for c in session.calls if c["url"].endswith(LOGIN_PATH)]
    assert len(logins) == 1
    assert logins[0]["json"] == {"username": "itv-g125-cmp-0000", "password": "Itv-secreta"}


def test_login_fn_inyectable_evita_el_post():
    session = FakeSession(bloqueados=0, permitidos=2)
    fn = _fn(session, login_fn=lambda u, p: "tok-inyectado")
    fn(_summary(auditable=2))
    assert not [c for c in session.calls if c["url"].endswith(LOGIN_PATH)]
    assert _audit_calls(session)[0]["headers"]["Authorization"] == "Bearer tok-inyectado"


# ── fail-closed: ningún camino devuelve conteos inventados ────────────────────────────

def test_credencial_que_no_loguea_es_error_accionable():
    session = FakeSession(login_status=401)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)(_summary())
    assert "no autentica" in str(ei.value)


def test_get_que_falla_es_error_accionable():
    session = FakeSession(audit_status=403)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)(_summary())
    assert "403" in str(ei.value)
    assert "compliance" in str(ei.value).lower()


def test_respuesta_sin_total_no_se_asume_cero():
    session = FakeSession(total_override=None)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)(_summary())
    assert "total" in str(ei.value)
    assert "JAMÁS se asume 0" in str(ei.value)


def test_total_no_entero_es_ilegible():
    session = FakeSession(total_override="42")
    with pytest.raises(ReconcileError):
        _fn(session)(_summary())


def test_transporte_caido_es_error_accionable():
    class Rota:
        def request(self, *a, **kw):
            raise OSError("connection refused")

    with pytest.raises(ReconcileError) as ei:
        _fn(Rota())(_summary())
    assert "transporte" in str(ei.value)


def test_filtro_de_ventana_ignorado_aborta():
    """El backend descarta en silencio una fecha que no parsea (`except ValueError: pass`).
    La sonda con ventana imposible es lo único que separa «contamos la ventana» de
    «contamos la tabla entera»."""
    session = FakeSession(bloqueados=5, permitidos=95, ignora_ventana=True)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)(_summary(auditable=100, blocks=5))
    assert "filtro de ventana" in str(ei.value)
    # abortó ANTES de contar nada real
    assert len(_audit_calls(session)) == 1


def test_sin_ventana_no_cuenta():
    fn = build_http_reconcile(BACKEND, "u", "p", session=FakeSession())
    with pytest.raises(ReconcileError) as ei:
        fn(_summary())
    assert "set_window" in str(ei.value)


def test_ventana_invertida_es_error():
    fn = build_http_reconcile(BACKEND, "u", "p", session=FakeSession())
    with pytest.raises(ReconcileError):
        fn.set_window(T1, T0)


def test_summary_sin_contador_no_se_lee_como_cero():
    session = FakeSession(bloqueados=0, permitidos=10)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)({"auditable_events": 10})          # falta observed_blocks
    assert "observed_blocks" in str(ei.value)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)({"observed_blocks": 0})            # falta auditable_events
    assert "auditable_events" in str(ei.value)


def test_bloqueos_que_el_guion_no_vio_no_se_certifican():
    """Filas `blocked_*` en la ventana con 0 bloqueos del guion: `eval_blocked_durable`
    daría PASS vacuo (100% trivial). Eso es un aprobado regalado — se aborta."""
    session = FakeSession(bloqueados=12, permitidos=88)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)(_summary(auditable=100, blocks=0))
    msg = str(ei.value)
    assert "12" in msg and "PASS vacuo" in msg


def test_sin_bloqueos_de_ningun_lado_no_aborta():
    session = FakeSession(bloqueados=0, permitidos=100)
    recon = _fn(session)(_summary(auditable=100, blocks=0))
    assert recon["con_fila"] == 0 and recon["bloqueos_provocados"] == 0


def test_build_sin_credencial_es_error():
    with pytest.raises(ReconcileError):
        build_http_reconcile(BACKEND, "", "", session=FakeSession())


# ── credencial desde el pool del seeder ───────────────────────────────────────────────

def test_credential_from_pool_prefiere_compliance():
    pool = [{"username": "adm", "password": "a", "role": "tenant_admin", "bootstrap": True},
            {"username": "cmp", "password": "c", "role": "compliance_officer"},
            {"username": "cli", "password": "x", "role": "client"}]
    assert credential_from_pool(pool) == ("cmp", "c")


def test_credential_from_pool_cae_a_tenant_admin():
    pool = [{"username": "cli", "password": "x", "role": "client"},
            {"username": "adm", "password": "a", "role": "tenant_admin"}]
    assert credential_from_pool(pool) == ("adm", "a")


def test_credential_from_pool_sin_lector_es_error():
    with pytest.raises(ReconcileError) as ei:
        credential_from_pool([{"username": "cli", "password": "x", "role": "client"}])
    assert "admin-only" in str(ei.value)


def test_es_un_callable_con_la_firma_del_orquestador():
    fn = build_http_reconcile(BACKEND, "u", "p", session=FakeSession(permitidos=1))
    assert isinstance(fn, HttpReconcile)
    assert callable(fn) and callable(getattr(fn, "set_window"))
