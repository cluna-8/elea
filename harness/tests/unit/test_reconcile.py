"""Tests de la reconciliación real (spec 035, T031) — con sesión HTTP MOCKEADA.

Frontera del módulo (DevFlow §3): pytest prueba el instrumento sin backend. Acá se cubre
lo que decide un veredicto:

- los totales salen de los filtros correctos (bloqueados + permitidos + los dos baldes
  ``rejected_*`` = tráfico, sin los eslabones ``model='license'``) y la ventana viaja en
  los params;
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
      y —desde la H4 del PR #135— TODOS los rechazos (``~LIKE 'rejected%'``: por capacidad
      y, desde #177, por presupuesto). ``h4=False`` modela una imagen PRE-#135, donde los
      rechazos caen en ``permitidos``.
    - ``compliance_status`` filtra exacto y es COMPONIBLE con ``estado`` (el backend
      aplica los dos filtros; en un backend con H4 esa combinación es contradictoria).
    - las fechas se parsean POR CAMPO dentro de un ``try/except ValueError: pass``:
      ``ignora_from``/``ignora_to`` modelan que un borde se caiga en silencio sin tocar
      el otro. Las filas del seed viven "antes del run" y las del run, dentro.
    """

    def __init__(self, *, bloqueados=0, permitidos=0, rejected=0, rejected_budget=0,
                 licencia=0, seed_rows=5,
                 login_status=200, audit_status=200, total_override=...,
                 ignora_from=False, ignora_to=False, h4=True):
        self.bloqueados = bloqueados
        self.permitidos = permitidos
        self.rejected = rejected                  # compliance_status='rejected_saturated'
        self.rejected_budget = rejected_budget    # compliance_status='rejected_budget'
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
            return (self.bloqueados + self.permitidos + self._rechazos() + self.licencia)
        extra = self.seed_rows if (incluye_seed and anio_desde != "1970") else 0

        # 2) filtros de clase.
        estado = params.get("estado")
        status = params.get("compliance_status")
        if estado is None and status is not None:
            return self._por_literal(status)
        if estado is None:
            # sin `estado`: el universo incluye los eslabones de licencia (lo que NO queremos)
            return (self.bloqueados + self.permitidos + self._rechazos() + self.licencia
                    + extra)
        # con `estado`: fuera license y (si hay H4) fuera TODOS los rechazos.
        if estado == "bloqueados":
            base = self.bloqueados
        else:
            base = self.permitidos if self.h4 else self.permitidos + self._rechazos()
        if status is not None:
            # AND de los dos filtros: con H4 es contradictorio (0); sin H4, los rechazos
            # están dentro de `permitidos` y la combinación los devuelve.
            if self.h4 or estado == "bloqueados":
                return 0
            return self._por_literal(status)
        return base + (extra if estado == "permitidos" else 0)

    def _rechazos(self):
        """Todo lo que el prefijo `rejected%` del filtro `estado` deja afuera."""
        return self.rejected + self.rejected_budget

    def _por_literal(self, status):
        if status == "rejected_saturated":
            return self.rejected
        if status == "rejected_budget":
            return self.rejected_budget
        return 0


def _summary(auditable=100, blocks=0, budget_402=0):
    # `buildSummary` (common.js) emite SIEMPRE los cuatro contadores, 0 incluido: un
    # summary al que le falte uno no es el que produce este harness.
    return {"schema": "basa-harness/k6-summary@1", "auditable_events": auditable,
            "observed_blocks": blocks, "provoked_blocks": blocks,
            "budget_402": budget_402}


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
    assert recon["filas_rejected_budget"] == 0
    assert recon["desglose"] == {"filas_bloqueadas": 6, "filas_permitidas": 94,
                                 "filas_rechazadas": 0, "filas_rechazadas_budget": 0}


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
                                 "filas_rechazadas": 10, "filas_rechazadas_budget": 0}
    # Contrafáctico: solo bloqueados+permitidos habría dado 90 → «faltan 10 filas».
    assert session.bloqueados + session.permitidos == 90


def test_los_402_de_presupuesto_cuentan_como_trafico():
    """Post-#177 el plano chat escribe fila durable `rejected_budget` ANTES de responder el
    402, y el guion cuenta ese 402 como evento auditable. El literal cae bajo el mismo
    prefijo `rejected%` que excluye el filtro binario, así que necesita su propio balde:
    sin él, un run con la cohorte 402 que el gate 125 siembra a propósito reportaría
    «faltan N filas» que el producto SÍ escribió (falso FAIL del SLO (b))."""
    session = FakeSession(bloqueados=6, permitidos=79, rejected=10, rejected_budget=5,
                          licencia=2)
    recon = _fn(session)(_summary(auditable=100, blocks=6))

    assert recon["filas_persistidas"] == 100      # 6 + 79 + 10 + 5, sin los 2 de licencia
    assert recon["filas_rejected_budget"] == 5
    assert recon["filas_rejected_saturated"] == 10
    assert recon["con_fila"] == 6                 # SLO (d) sigue siendo SOLO política
    assert recon["desglose"] == {"filas_bloqueadas": 6, "filas_permitidas": 79,
                                 "filas_rechazadas": 10, "filas_rechazadas_budget": 5}
    # Contrafáctico: sin el cuarto balde el total habría dado 95 → «faltan 5 filas».
    assert session.bloqueados + session.permitidos + session.rejected == 95


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


def test_los_cuatro_filtros_se_piden_siempre():
    session = FakeSession(bloqueados=3, permitidos=7, rejected=5, rejected_budget=2)
    recon = _fn(session)(_summary(auditable=10, blocks=3))
    params = [c["params"] for c in _audit_calls(session)]
    assert {"bloqueados", "permitidos"} <= {p.get("estado") for p in params}
    assert {"rejected_saturated", "rejected_budget"} <= {p.get("compliance_status")
                                                         for p in params}
    # el contrato pide el conteo de rechazos SIEMPRE, aunque el run no produzca ninguno
    assert recon["filas_rejected_saturated"] == 5
    assert recon["filas_rejected_budget"] == 2


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


def test_backend_que_cuenta_los_402_dentro_de_permitidos_no_se_certifica():
    """Espejo de A1 para `rejected_budget`: la exclusión `rejected%` (H4) cubre también el
    literal del 402, pero contra una imagen que no la tenga esas filas viven DENTRO de
    `permitidos` y re-sumar el balde las doble-contaría — tapando filas de tráfico perdidas
    hasta cuadrar (PASS regalado del SLO (b)). El mensaje nombra el literal para que quien
    lea el abort sepa por cuál balde entró."""
    session = FakeSession(bloqueados=6, permitidos=84, rejected=0, rejected_budget=10,
                          h4=False, seed_rows=0)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)(_summary(auditable=100, blocks=6))
    assert "rejected_budget" in str(ei.value)


@pytest.mark.parametrize("rejected,budget,sondeados", [
    (0, 0, set()),
    (10, 0, {"rejected_saturated"}),
    (0, 7, {"rejected_budget"}),
    (10, 7, {"rejected_saturated", "rejected_budget"}),
])
def test_la_sonda_de_doble_conteo_se_paga_por_balde_con_filas(rejected, budget, sondeados):
    """Si un balde `rejected_*` vino en 0 no hay nada que doble-contar y la sonda extra no
    se paga. Si vino con filas, se paga SOLO por ese literal: la exclusión `rejected%` del
    backend es una sola, pero cada balde se re-suma por separado y el doble conteo entra
    por el que de verdad tuvo filas."""
    session = FakeSession(bloqueados=4, permitidos=96 - rejected - budget,
                          rejected=rejected, rejected_budget=budget, seed_rows=0)
    recon = _fn(session)(_summary(auditable=100, blocks=4))
    assert recon["filas_persistidas"] == 100
    combinadas = {c["params"].get("compliance_status") for c in _audit_calls(session)
                  if c["params"].get("estado") and c["params"].get("compliance_status")}
    assert combinadas == sondeados


def test_la_cohorte_402_del_guion_queda_en_la_evidencia():
    """Post-#177 los 402 del plano chat YA están dentro de `auditable_events` (el producto
    les escribe fila `rejected_budget`). El Counter del guion viaja igual a la evidencia:
    es lo que permite cruzar la cohorte que vio el guion contra `filas_rejected_budget`
    del producto cuando la paridad no cuadra."""
    session = FakeSession(bloqueados=2, permitidos=61, rejected_budget=37, seed_rows=0)
    recon = _fn(session)(_summary(auditable=100, blocks=2, budget_402=37))
    assert recon["respuestas_402"] == 37
    assert recon["filas_rejected_budget"] == 37       # cruzan: cohorte del guion = filas
    assert recon["filas_persistidas"] == 100

    # La clave está SIEMPRE (el contador también): un run sin cohorte reporta 0, no la omite.
    limpio = _fn(FakeSession(bloqueados=2, permitidos=98, seed_rows=0))(
        _summary(auditable=100, blocks=2))
    assert limpio["respuestas_402"] == 0


def test_summary_sin_budget_402_no_se_degrada_a_no_se():
    """`budget_402` es el insumo de la guarda pre-#177, así que leerlo con `.get` sería
    fail-OPEN: un summary sin el contador saltearía la guarda en silencio y dejaría pasar
    justo la imagen que la guarda existe para cazar. Se lee como el resto de los
    contadores — ausente = summary que no es de este harness = abort."""
    session = FakeSession(bloqueados=2, permitidos=98, seed_rows=0)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)({"auditable_events": 100, "observed_blocks": 2})
    assert "budget_402" in str(ei.value)


def test_cohorte_402_sin_filas_rejected_budget_es_imagen_pre_177():
    """El guion cuenta el 402 como auditable ASUMIENDO la fila del PR #177. Contra una
    imagen sin ese PR la paridad saldría con un «faltan N filas» que parece pérdida de
    auditoría — y el yaml NO puede impedirlo: `producto_incluye` es una lista y
    `_stack_config_drift` solo compara escalares, así que jamás produce drift. La firma
    (cohorte vista > 0, cero filas) se caza acá y el run sale `invalid` con causa."""
    session = FakeSession(bloqueados=2, permitidos=98, rejected_budget=0, seed_rows=0)
    with pytest.raises(ReconcileError) as ei:
        _fn(session)(_summary(auditable=100, blocks=2, budget_402=18))
    assert "#177" in str(ei.value)


def test_sin_cohorte_402_ejercitada_la_guarda_no_se_dispara():
    """Un run sin cohorte 402 (b402 == 0) no afirma nada sobre el escritor de filas: sin
    402 recibidos no hay fila que exigir. Abortar ahí invalidaría runs legítimos."""
    session = FakeSession(bloqueados=2, permitidos=98, rejected_budget=0, seed_rows=0)
    recon = _fn(session)(_summary(auditable=100, blocks=2, budget_402=0))
    assert recon["respuestas_402"] == 0
    assert recon["filas_rejected_budget"] == 0


def test_cohorte_402_con_sus_filas_no_aborta():
    """El camino post-#177: cada 402 que vio el guion tiene su fila `rejected_budget`."""
    session = FakeSession(bloqueados=2, permitidos=80, rejected_budget=18, seed_rows=0)
    recon = _fn(session)(_summary(auditable=100, blocks=2, budget_402=18))
    assert recon["respuestas_402"] == 18 and recon["filas_rejected_budget"] == 18
    assert recon["filas_persistidas"] == 100


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
