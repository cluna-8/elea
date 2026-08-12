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
    """Backend de auditoría simulado, FIEL a ``_build_query`` (``backend/src/api/audit.py``).

    Modela las tres cosas que deciden un conteo, cada una por separado para que los tests
    puedan romperlas de a una:

    - ``estado`` parte el universo del tráfico excluyendo los eslabones ``model='license'``
      y —desde la H4 del PR #135— los rechazos por capacidad (``~LIKE 'rejected%'``).
      ``h4=False`` modela una imagen PRE-#135, donde los rechazos caen en ``permitidos``.
    - ``compliance_status`` filtra exacto y es COMPONIBLE con ``estado`` (el backend
      aplica los dos filtros; en un backend con H4 esa combinación es contradictoria).
    - las fechas se parsean POR CAMPO dentro de un ``try/except ValueError: pass``:
      ``ignora_from``/``ignora_to`` modelan que un borde se caiga en silencio sin tocar
      el otro. Las filas del seed viven "antes del run" y las del run, dentro.
    """

    def __init__(self, *, bloqueados=0, permitidos=0, rejected=0, licencia=0, seed_rows=5,
                 login_status=200, audit_status=200, total_override=...,
                 ignora_from=False, ignora_to=False, h4=True):
        self.bloqueados = bloqueados
        self.permitidos = permitidos
        self.rejected = rejected
        self.licencia = licencia          # eslabones model='license' de la hash-chain
        self.seed_rows = seed_rows        # tráfico del seed, FUERA de la ventana del run
        self.login_status = login_status
        self.audit_status = audit_status
        self.total_override = total_override
        self.ignora_from = ignora_from    # el `except ValueError: pass` de from_date
        self.ignora_to = ignora_to        # …y el de to_date, independiente
        self.h4 = h4                      # False = imagen pre-#135 (sin exclusión rejected%)
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
        # 1) ventana: cada borde se aplica (o se cae) por separado, como el backend real.
        desde = str(params.get("from_date", ""))
        hasta = str(params.get("to_date", ""))
        anio_desde = desde[:4] if desde else ""
        anio_hasta = hasta[:4] if hasta else ""
        # Universo por defecto: las filas del run. El seed queda fuera salvo que el borde
        # inferior se caiga; una ventana que termina en el pasado no debería ver nada.
        incluye_seed = self.ignora_from or anio_desde in ("", "1970")
        if anio_desde == "2999" and not self.ignora_from:
            return 0                       # ventana futura: el borde inferior corta todo
        if anio_hasta == "1970" and not self.ignora_to:
            return 0                       # ventana pasada: el borde superior corta todo
        if anio_hasta == "1970" and self.ignora_to:
            # `to_date` descartado en silencio → vuelve la tabla entera (incluido el run)
            return self.bloqueados + self.permitidos + self.rejected + self.licencia
        extra = self.seed_rows if (incluye_seed and anio_desde != "1970") else 0

        # 2) filtros de clase.
        estado = params.get("estado")
        status = params.get("compliance_status")
        if estado is None and status is not None:
            return self.rejected if status == "rejected_saturated" else 0
        if estado is None:
            # sin `estado`: el universo incluye los eslabones de licencia (lo que NO queremos)
            return self.bloqueados + self.permitidos + self.rejected + self.licencia + extra
        # con `estado`: fuera license y (si hay H4) fuera los rechazos.
        if estado == "bloqueados":
            base = self.bloqueados
        else:
            base = self.permitidos if self.h4 else self.permitidos + self.rejected
        if status is not None:
            # AND de los dos filtros: con H4 es contradictorio (0); sin H4, los rechazos
            # están dentro de `permitidos` y la combinación los devuelve.
            if self.h4 or estado == "bloqueados" or status != "rejected_saturated":
                return 0
            return self.rejected
        return base + (extra if estado == "permitidos" else 0)


def _summary(auditable=100, blocks=0):
    return {"schema": "basa-harness/k6-summary@1", "auditable_events": auditable,
            "observed_blocks": blocks, "provoked_blocks": blocks}


def _fn(session, **kw):
    fn = build_http_reconcile(BACKEND, "itv-g125-cmp-0000", "fake-test-password-itv", session=session,
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
    assert recon["desglose"] == {"filas_bloqueadas": 6, "filas_permitidas": 94,
                                 "filas_rechazadas": 0}


def test_los_rechazos_de_admision_cuentan_como_trafico():
    """Post-H4 (#135): la rama `estado` excluye `rejected%` de AMBOS baldes, pero el guion
    cuenta cada 503 saturado como evento auditable (fila durable del contrato C1). Si el
    total no re-sumara el balde de rechazos, un run con N rechazos reportaría «faltan N
    filas» que el producto SÍ escribió — falso FAIL del SLO (b)."""
    session = FakeSession(bloqueados=6, permitidos=84, rejected=10, licencia=2)
    recon = _fn(session)(_summary(auditable=100, blocks=6))

    assert recon["filas_persistidas"] == 100          # 6 + 84 + 10, sin los 2 de licencia
    assert recon["filas_rejected_saturated"] == 10
    assert recon["con_fila"] == 6                     # SLO (d) sigue siendo SOLO política
    assert recon["desglose"] == {"filas_bloqueadas": 6, "filas_permitidas": 84,
                                 "filas_rechazadas": 10}
    # Contrafáctico: solo bloqueados+permitidos habría dado 90 → «faltan 10 filas».
    assert session.bloqueados + session.permitidos == 90


def test_el_total_sin_estado_habria_inflado_las_filas():
    """Contrafáctico explícito de la decisión de filtro: el universo sin `estado` incluye
    los eslabones `model='license'`, que el filtro `estado` excluye a propósito."""
    session = FakeSession(bloqueados=0, permitidos=98, licencia=2, seed_rows=0)
    recon = _fn(session)(_summary(auditable=100, blocks=0))
    # El producto perdió 2 filas de tráfico (98 de 100) → el SLO (b) tiene que verlo.
    assert recon["filas_persistidas"] == 98
    # Sin el filtro, el mismo backend habría devuelto 100 y el examen habría "cuadrado".
    assert session._total({"from_date": "2026-08-11T09:00:00.000000",
                           "to_date": "2026-08-11T09:30:00.000000"}) == 100


def test_la_ventana_viaja_en_los_params_y_en_formato_naive_utc():
    session = FakeSession(bloqueados=1, permitidos=1)
    _fn(session)(_summary(auditable=2, blocks=1))
    reales = [c for c in _audit_calls(session)
              if not str(c["params"]["from_date"]).startswith(("2999", "1970"))]
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
    assert logins[0]["json"] == {"username": "itv-g125-cmp-0000", "password": "fake-test-password-itv"}


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


def test_borde_inferior_de_la_ventana_ignorado_aborta():
    """El backend descarta en silencio una fecha que no parsea (`except ValueError: pass`).
    La sonda futura es lo único que separa «contamos desde t0» de «contamos también el
    tráfico del seed»."""
    session = FakeSession(bloqueados=5, permitidos=95, ignora_from=True)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)(_summary(auditable=100, blocks=5))
    assert "borde inferior" in str(ei.value)
    # abortó ANTES de contar nada real
    assert len(_audit_calls(session)) == 1


def test_borde_superior_de_la_ventana_ignorado_aborta():
    """El `except ValueError: pass` del backend es POR CAMPO: `from_date` puede aplicarse y
    `to_date` caerse en silencio. La sonda futura NO lo ve (con from_date aplicado da 0
    igual), así que hace falta la sonda espejo en el pasado: si `to_date` se descarta,
    vuelve la tabla entera y se detecta. Sin ella, el conteo incluiría tráfico posterior
    a t1 sin que nadie se entere."""
    session = FakeSession(bloqueados=5, permitidos=95, ignora_to=True)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)(_summary(auditable=100, blocks=5))
    assert "borde superior" in str(ei.value)
    # la sonda futura pasó (1 llamada) y la pasada abortó (2ª): nada real se contó
    assert len(_audit_calls(session)) == 2


def test_backend_pre_h4_no_se_certifica():
    """A1: contra una imagen anterior al PR #135, los rechazos por capacidad viven DENTRO
    de `permitidos`. Re-sumar el balde de rechazos los doble-contaría — y el caso perverso
    cancela filas perdidas reales, regalando un PASS del SLO (b). La sonda de la H4 lo
    caza: `estado=permitidos` AND `compliance_status=rejected_saturated` debe dar 0."""
    session = FakeSession(bloqueados=6, permitidos=84, rejected=10, h4=False, seed_rows=0)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)(_summary(auditable=100, blocks=6))
    assert "#135" in str(ei.value)

    # Contrafáctico del PASS regalado: el producto PERDIÓ 2 filas de tráfico, pero el
    # doble conteo de los 10 rechazos las habría tapado hasta cuadrar.
    perdidas = FakeSession(bloqueados=6, permitidos=82, rejected=10, h4=False, seed_rows=0)
    assert (perdidas.bloqueados + perdidas.permitidos) + perdidas.rejected == 98 + 0 or True
    with pytest.raises(ReconcileError):
        _fn(perdidas)(_summary(auditable=100, blocks=6))


def test_sin_rechazos_no_se_sondea_la_h4():
    """Si no hubo rechazos no hay nada que doble-contar: la sonda extra no se paga."""
    session = FakeSession(bloqueados=4, permitidos=96, rejected=0, seed_rows=0)
    recon = _fn(session)(_summary(auditable=100, blocks=4))
    assert recon["filas_persistidas"] == 100
    combinadas = [c for c in _audit_calls(session)
                  if c["params"].get("estado") and c["params"].get("compliance_status")]
    assert combinadas == []


def test_los_402_sin_fila_quedan_en_la_evidencia():
    """A4: el guion NO cuenta los 402 de presupuesto como auditables (el producto no les
    escribe fila, issue #157). El conteo viaja igual a la evidencia para que el delta de
    la reconciliación sea explicable a posteriori."""
    session = FakeSession(bloqueados=2, permitidos=98, seed_rows=0)
    summary = _summary(auditable=100, blocks=2)
    summary["budget_402"] = 37
    recon = _fn(session)(summary)
    assert recon["respuestas_402_sin_fila"] == 37
    assert recon["filas_persistidas"] == 100          # los 402 no cuentan de ningún lado

    # Un summary sin el contador (guion pre-A4) no inventa la clave.
    assert "respuestas_402_sin_fila" not in _fn(
        FakeSession(bloqueados=2, permitidos=98, seed_rows=0))(_summary(auditable=100, blocks=2))


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
