"""Reconciliación REAL de auditoría (spec 035, T031; contract ``run-report.md`` §insumos).

Cierra el último hueco de la corrida real: el orquestador sabe evaluar los SLO (b)
``reconciliation_rows`` y (d) ``blocked_rows_durable_100``, pero necesita que alguien
cuente las filas que el PRODUCTO persistió. Este módulo es ese alguien: lee
``GET /api/v1/audit-logs`` con credencial compliance/admin, acotado a la ventana del run,
y devuelve el dict que consume ``reporting.evaluator``.

REGLA DE ORO — el conteo alimenta un veredicto, así que ante CUALQUIER ambigüedad se elige
la lectura que NO pueda regalar un PASS. En concreto:

1. **Qué es "fila de tráfico"** (``filas_persistidas``). El endpoint no tiene un filtro
   «todo el tráfico»: la rama ``estado`` de ``_build_query`` excluye los eslabones de
   licencia (``AuditLog.model != 'license'``) **y, desde el PR #135 (decisión H4), también
   los rechazos por capacidad** (``~LIKE 'rejected%'``, ``backend/src/api/audit.py``): un
   rechazo no es ni permitido ni bloqueado por política, así que no vive en ningún balde
   del filtro binario. Pero para la reconciliación SÍ es tráfico: el contrato C1 exige una
   fila durable por rechazo y el guion cuenta cada 503 saturado como evento auditable
   (``chat.js``/``coding-sse.js``). Por eso el total se arma como ``estado=bloqueados`` +
   ``estado=permitidos`` + el conteo exacto de ``compliance_status=rejected_saturated`` —
   sin ese tercer balde, un run con N rechazos reportaría «faltan N filas» que el producto
   sí escribió (falso FAIL del SLO (b)). La alternativa (pedir el total SIN ``estado``)
   contaría además los eslabones ``model='license'`` de la hash-chain (021), que se
   escriben DURANTE el run y no son tráfico: inflarían ``filas_persistidas`` y podrían
   TAPAR filas de tráfico perdidas hasta cuadrar con los eventos del guion. Es decir,
   regalarían un PASS del SLO (b). Por eso se excluyen.

2. **El filtro tiene que haberse aplicado.** ``_build_query`` parsea las fechas con
   ``datetime.fromisoformat`` dentro de un ``try/except ValueError: pass``
   (``audit.py:99-108``): una fecha que no parsea NO es un error, es un filtro que
   desaparece en silencio y un total que cuenta la tabla entera. Antes de contar nada se
   dispara una sonda con una ventana IMPOSIBLE (año 2999): si vuelve algo distinto de 0,
   el backend está ignorando el filtro y se aborta. Barato (una request) y cierra el único
   camino por el que este módulo podría mentir sin enterarse.

3. **Formato de fecha del wire**: ``audit_logs.timestamp`` es ``DateTime`` NAIVE con
   default ``datetime.utcnow`` (``backend/src/models/audit.py:17``), así que la ventana
   viaja como ISO UTC **sin** offset ni sufijo ``Z`` — un datetime aware compararía
   contra una columna naive (y ``fromisoformat`` de Python <3.11 ni siquiera parsea la
   ``Z``: caería en el ``except`` del punto 2). En el reporte del run la ventana queda
   registrada en UTC explícito.

4. **Bloqueos que el guion no vio.** ``bloqueos_provocados`` sale de ``observed_blocks``
   del summary de k6 y hoy NINGÚN scenario incrementa ese contador (``scenarios/*.js``),
   así que llega 0 siempre. Con 0 provocados, ``eval_blocked_durable`` da PASS vacuo. Si
   además el producto SÍ tiene filas ``blocked_*`` en la ventana, ese PASS sería regalado
   sobre un run donde el bloqueo demostrablemente ocurrió: se aborta con error accionable
   (run sin veredicto limpio) en vez de certificarlo.

Errores fail-closed: si el GET falla, la credencial no loguea o la respuesta no trae
``total``, se levanta ``ReconcileError``. JAMÁS se devuelve un conteo inventado ni un 0
por defecto — el orquestador convierte la excepción en un run marcado ``invalid``, que es
la lectura honesta de «no se pudo medir».
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional, Union

# Rutas REALES verificadas en el repo (el router de auditoría monta ``/audit-logs`` bajo
# ``/api/v1``: backend/src/api/audit.py:18 + api/__init__.py:21).
LOGIN_PATH = "/api/v1/users/login"
AUDIT_PATH = "/api/v1/audit-logs"

# Valores del enum ``EstadoFiltro`` (audit.py:49). Complementarios sobre el tráfico.
ESTADO_BLOQUEADOS = "bloqueados"
ESTADO_PERMITIDOS = "permitidos"

# Estado LITERAL del rechazo de admisión C1 (contrato de wire sellado con el core; en main
# desde el PR #135). Se pide SIEMPRE porque el contrato lo exige ante cualquier rechazo y
# cuesta una request. Dos huecos CONOCIDOS y aceptados de este balde (hallazgos B1/B2 del
# gate): (1) va sin `estado`, así que no excluye `model='license'` — hoy imposible que
# colisione: los eventos de licencia solo emiten passed/flagged_high_risk/blocked_by_policy;
# (2) cualquier `rejected_*` FUTURO distinto de este literal quedaría fuera de los tres
# baldes (el filtro `estado` excluye por prefijo, esto cuenta por match exacto) — el día
# que el core acuñe otro literal (p. ej. rejected_budget), ampliar el conteo acá.
COMPLIANCE_REJECTED_SATURATED = "rejected_saturated"

# Ventanas imposibles para las sondas de "¿el filtro de fechas se está aplicando?"
# (punto 2). Se necesitan las DOS porque el `except ValueError: pass` de `_build_query`
# es por campo: la futura prueba el borde `from_date`, la pasada el borde `to_date`.
# El formato lleva microsegundos, igual que el que emite `_wire()` para los conteos
# reales: la sonda debe validar el MISMO formato que se usa de verdad.
_SONDA_FUTURO_DESDE = "2999-01-01T00:00:00.000000"
_SONDA_FUTURO_HASTA = "2999-01-02T00:00:00.000000"
_SONDA_PASADO_DESDE = "1970-01-01T00:00:00.000000"
_SONDA_PASADO_HASTA = "1970-01-02T00:00:00.000000"

# ``limit`` mínimo aceptado por el endpoint (``Query(50, ge=1, le=100)``): sólo interesa
# ``total``, así que se pide la fila más chica posible en vez de paginar miles.
_LIMIT = 1


class ReconcileError(RuntimeError):
    """Fallo accionable de la reconciliación (credencial, transporte, respuesta ilegible).

    No es un veredicto FAIL: es «no se pudo contar», y un examen que no se puede contar no
    se certifica."""


class HttpReconcile:
    """Callable con la firma que espera ``Orchestrator._reconcile`` (recibe el summary de
    k6, devuelve el dict de reconciliación). La VENTANA la fija el orquestador con
    ``set_window`` — el reloj vive allá, no acá (el evaluador sigue recibiendo el
    ``timestamp`` inyectado)."""

    def __init__(self, backend_url: str, username: str, password: str, *,
                 session: Optional[object] = None,
                 login_fn: Optional[Callable[[str, str], str]] = None,
                 timeout: float = 30.0):
        self.backend_url = backend_url.rstrip("/")
        self.username = username
        self.password = password
        self._login_fn = login_fn
        self._timeout = timeout
        self._session = session
        self._owns_session = session is None
        self._token: Optional[str] = None
        self._desde: Optional[datetime] = None
        self._hasta: Optional[datetime] = None

    # ── ventana ────────────────────────────────────────────────────────────────────────

    def set_window(self, desde: Union[str, datetime], hasta: Union[str, datetime]) -> None:
        """Fija la ventana del run (t0 ANTES de k6, t1 DESPUÉS). Acepta datetime o ISO."""
        self._desde = _as_utc(desde, "desde")
        self._hasta = _as_utc(hasta, "hasta")
        if self._hasta < self._desde:
            raise ReconcileError(
                f"ventana invertida: t1 ({self._hasta.isoformat()}) es anterior a t0 "
                f"({self._desde.isoformat()}). Sin ventana confiable no hay conteo.")

    # ── ejecución ──────────────────────────────────────────────────────────────────────

    def __call__(self, k6_summary: dict) -> dict:
        if self._desde is None or self._hasta is None:
            raise ReconcileError(
                "reconciliación sin ventana: el orquestador debe llamar a set_window(t0, t1) "
                "con los instantes de arranque y cierre de k6. Contar sin ventana mezclaría "
                "el tráfico del seed con el del examen.")

        eventos = _counter(k6_summary, "auditable_events")
        bloqueos = _counter(k6_summary, "observed_blocks")
        # Informativo, no decide SLO: 402s de presupuesto que el guion NO contó como
        # auditables porque el producto no les escribe fila (issue #157). Queda en la
        # evidencia para que el delta de la reconciliación sea explicable a posteriori.
        b402 = k6_summary.get("budget_402")
        b402 = b402 if isinstance(b402, int) and not isinstance(b402, bool) else None

        self._assert_filtro_de_ventana_activo()
        bloqueadas = self._total(estado=ESTADO_BLOQUEADOS)
        permitidas = self._total(estado=ESTADO_PERMITIDOS)
        rechazadas = self._total(compliance_status=COMPLIANCE_REJECTED_SATURATED)
        # A1: el conteo re-suma `rechazadas` porque se ASUME que el backend tiene la H4
        # (#135), que excluye `rejected%` del filtro `estado`. Contra un backend pre-#135
        # las rechazadas YA están dentro de `permitidos` y re-sumarlas las doble-cuenta —
        # y el caso perverso cancela filas perdidas reales (PASS regalado). Solo importa
        # si de verdad hubo rechazos: si son 0, no hay nada que doble-contar.
        if rechazadas > 0:
            self._assert_backend_tiene_h4()

        if bloqueos == 0 and bloqueadas > 0:
            raise ReconcileError(
                f"el producto registró {bloqueadas} fila(s) de bloqueo en la ventana pero el "
                "guion contó 0 bloqueos provocados (k6 no incrementa `observed_blocks` en "
                "ninguna superficie). Con 0 provocados el SLO (d) sale PASS vacuo: sería un "
                "aprobado regalado sobre un run donde el bloqueo SÍ ocurrió. Revisá esas "
                "filas a mano (GET /api/v1/audit-logs?estado=bloqueados) antes de certificar.")

        resultado = {
            "eventos_guion": eventos,
            # Los rechazos se re-suman: el filtro `estado` los excluye de ambos baldes
            # (H4, #135) pero son filas de tráfico que el guion contó como auditables.
            "filas_persistidas": bloqueadas + permitidas + rechazadas,
            "bloqueos_provocados": bloqueos,
            "con_fila": bloqueadas,
            "filas_rejected_saturated": rechazadas,
            # Evidencia del conteo (el evaluador ignora las claves que no conoce; esto va al
            # reconciliation.json del run para que la cifra sea auditable después).
            "ventana": {"desde": self._desde.isoformat(), "hasta": self._hasta.isoformat()},
            "desglose": {"filas_bloqueadas": bloqueadas, "filas_permitidas": permitidas,
                         "filas_rechazadas": rechazadas},
            "fuente": (f"GET {AUDIT_PATH} (estado=bloqueados + estado=permitidos + "
                       "compliance_status=rejected_saturated; excluye model='license', "
                       "que no es tráfico)"),
        }
        if b402 is not None:
            resultado["respuestas_402_sin_fila"] = b402
        return resultado

    # ── HTTP ───────────────────────────────────────────────────────────────────────────

    def _assert_filtro_de_ventana_activo(self) -> None:
        """Sondas: una ventana imposible tiene que devolver 0 filas, por AMBOS bordes.

        El ``except ValueError: pass`` de ``_build_query`` es POR CAMPO: descarta una
        ``from_date`` ilegible sin tocar ``to_date`` y viceversa. Por eso hacen falta dos
        sondas: (1) ventana en el FUTURO (año 2999) — si ``from_date`` se aplica, da 0
        aunque ``to_date`` se descarte, así que esta prueba SOLO el borde inferior; (2)
        ventana espejo en el PASADO (1970) — la tabla del examen tiene filas del seed
        posteriores a 1970, así que si ``to_date`` se descarta vuelve la tabla entera y se
        detecta. Con las dos, ningún borde puede caerse en silencio y contar tráfico fuera
        de la ventana del run."""
        futuro = self._get_total({"limit": _LIMIT, "estado": ESTADO_PERMITIDOS,
                                  "from_date": _SONDA_FUTURO_DESDE,
                                  "to_date": _SONDA_FUTURO_HASTA})
        if futuro != 0:
            raise ReconcileError(
                f"el filtro de ventana NO se aplica en el borde inferior: una ventana "
                f"futura imposible ({_SONDA_FUTURO_DESDE} … {_SONDA_FUTURO_HASTA}) "
                f"devolvió {futuro} filas. El backend descarta `from_date` en silencio, "
                "así que los conteos contarían tráfico anterior a t0 (incluido el seed). "
                "No se certifica un examen con la ventana rota.")
        pasado = self._get_total({"limit": _LIMIT, "estado": ESTADO_PERMITIDOS,
                                  "from_date": _SONDA_PASADO_DESDE,
                                  "to_date": _SONDA_PASADO_HASTA})
        if pasado != 0:
            raise ReconcileError(
                f"el filtro de ventana NO se aplica en el borde superior: una ventana "
                f"pasada imposible ({_SONDA_PASADO_DESDE} … {_SONDA_PASADO_HASTA}) "
                f"devolvió {pasado} filas. El backend descarta `to_date` en silencio, así "
                "que los conteos contarían tráfico posterior a t1. No se certifica un "
                "examen con la ventana rota.")

    def _assert_backend_tiene_h4(self) -> None:
        """Sonda A1: confirma que el backend excluye ``rejected%`` del filtro ``estado``.

        Un AND de ``estado=permitidos`` y ``compliance_status=rejected_saturated`` es
        contradictorio en un backend post-#135 (la rama ``estado`` filtra
        ``~LIKE 'rejected%'``, así que ninguna fila rechazada cae en ``permitidos``) →
        total 0 SIEMPRE. Si devuelve >0, el backend está contando los rechazos DENTRO de
        ``permitidos`` (imagen pre-#135): re-sumar ``rechazadas`` los doble-contaría. Un
        gate oficial no se corre —ni se certifica— contra una imagen sin la H4."""
        solapan = self._get_total({"limit": _LIMIT, "estado": ESTADO_PERMITIDOS,
                                   "compliance_status": COMPLIANCE_REJECTED_SATURATED,
                                   "from_date": _wire(self._desde),
                                   "to_date": _wire(self._hasta)})
        if solapan != 0:
            raise ReconcileError(
                f"el backend cuenta los rechazos por capacidad DENTRO de `permitidos` "
                f"({solapan} fila(s) con estado=permitidos Y "
                "compliance_status=rejected_saturated): es una imagen anterior al PR #135 "
                "(sin la exclusión `rejected%` del filtro binario, H4). Re-sumar las filas "
                "rechazadas las doble-contaría y el SLO (b) mentiría. Corré el gate contra "
                "una imagen con #135 en main.")

    def _total(self, *, estado: Optional[str] = None,
               compliance_status: Optional[str] = None) -> int:
        params: dict = {"limit": _LIMIT,
                        "from_date": _wire(self._desde), "to_date": _wire(self._hasta)}
        if estado is not None:
            params["estado"] = estado
        if compliance_status is not None:
            params["compliance_status"] = compliance_status
        return self._get_total(params)

    def _get_total(self, params: dict) -> int:
        resp = self._request("GET", AUDIT_PATH, params=params,
                             headers={"Authorization": f"Bearer {self._ensure_token()}"})
        if resp.status_code >= 400:
            raise ReconcileError(
                f"GET {AUDIT_PATH} devolvió {resp.status_code} ({_detail(resp)}) con "
                f"params={ _safe(params) }. Los SLO (b) y (d) no se pueden afirmar sin el "
                "conteo de audit_logs; ¿la credencial es admin/compliance_officer?")
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001 — cuerpo no-JSON es respuesta ilegible
            raise ReconcileError(
                f"GET {AUDIT_PATH} devolvió un cuerpo no-JSON: {exc}") from exc
        total = body.get("total") if isinstance(body, dict) else None
        if not isinstance(total, int) or isinstance(total, bool):
            raise ReconcileError(
                f"GET {AUDIT_PATH} no devolvió 'total' entero (vino {total!r}): sin ese "
                "número no hay reconciliación. JAMÁS se asume 0.")
        return total

    def _ensure_token(self) -> str:
        if self._token:
            return self._token
        if self._login_fn is not None:
            token = self._login_fn(self.username, self.password)
            if not token:
                raise ReconcileError(
                    f"el login de {self.username!r} no devolvió token (login_fn inyectado).")
            self._token = token
            return self._token
        resp = self._request("POST", LOGIN_PATH,
                             json={"username": self.username, "password": self.password})
        if resp.status_code != 200:
            raise ReconcileError(
                f"la credencial de reconciliación {self.username!r} no autentica "
                f"(POST {LOGIN_PATH} → {resp.status_code}: {_detail(resp)}). El lector de "
                "audit_logs necesita un compliance_officer o tenant_admin del MISMO seed "
                "(¿el pool es de otra semilla o de otra instalación?).")
        try:
            token = resp.json().get("access_token")
        except Exception as exc:  # noqa: BLE001
            raise ReconcileError(f"login con respuesta ilegible: {exc}") from exc
        if not isinstance(token, str) or not token:
            raise ReconcileError(
                f"el login de {self.username!r} respondió 200 sin 'access_token'.")
        self._token = token
        return self._token

    def _request(self, method: str, path: str, **kw):
        session = self._session_obj()
        url = f"{self.backend_url}{path}"
        try:
            return session.request(method, url, **kw)
        except ReconcileError:
            raise
        except Exception as exc:  # noqa: BLE001 — transporte caído es fallo accionable
            raise ReconcileError(
                f"{method} {url} falló en transporte ({type(exc).__name__}: {exc}). Sin el "
                "conteo del producto no hay veredicto de los SLO (b)/(d).") from exc

    def _session_obj(self):
        if self._session is None:  # pragma: no cover — camino real (los tests inyectan)
            import httpx
            self._session = httpx.Client(timeout=self._timeout)
        return self._session

    def close(self) -> None:
        if self._owns_session and self._session is not None:
            closer = getattr(self._session, "close", None)
            if callable(closer):
                closer()
            self._session = None


def build_http_reconcile(backend_url: str, username: str, password: str, *,
                         session: Optional[object] = None,
                         login_fn: Optional[Callable[[str, str], str]] = None,
                         timeout: float = 30.0) -> HttpReconcile:
    """Arma el ``reconcile_fn`` real del orquestador.

    ``session`` (cualquier objeto con ``.request(method, url, **kw)`` estilo httpx) y
    ``login_fn`` son inyectables para los tests: el módulo no importa httpx salvo en el
    camino real."""
    if not backend_url:
        raise ReconcileError("build_http_reconcile necesita la URL del backend.")
    if not username or not password:
        raise ReconcileError(
            "build_http_reconcile necesita una credencial compliance/admin del seed: sin "
            "ella no se puede leer audit_logs (el endpoint es admin-only).")
    return HttpReconcile(backend_url, username, password, session=session,
                         login_fn=login_fn, timeout=timeout)


# ── credencial del pool emitido por el seeder ─────────────────────────────────────────

# Roles que ``require_role('admin', 'compliance_officer')`` acepta en /audit-logs:
# compliance_officer directo y tenant_admin vía el shim legacy (auth/rbac.py:43).
_ROLES_LECTORES = ("compliance_officer", "tenant_admin")


def credential_from_pool(pool: list) -> tuple:
    """Elige del pool 0600 del seeder la credencial que lee ``audit_logs``.

    Se prefiere un ``compliance_officer`` (el MISMO lector que usa el SLO (a) para
    ``/health``) y se cae a ``tenant_admin``. La password sale de acá y no de ``argv``: un
    ``ps`` en la caja del examen no debe mostrarla."""
    for role in _ROLES_LECTORES:
        for entry in pool or []:
            if not isinstance(entry, dict) or entry.get("role") != role:
                continue
            usuario, clave = entry.get("username"), entry.get("password")
            if usuario and clave:
                return usuario, clave
    raise ReconcileError(
        "el pool no trae ninguna credencial con rol compliance_officer o tenant_admin: "
        "GET /api/v1/audit-logs es admin-only. ¿El pool es el que emitió "
        "`seed --emit-credentials`?")


# ── helpers ───────────────────────────────────────────────────────────────────────────

def _as_utc(value: Union[str, datetime], cual: str) -> datetime:
    """Normaliza a datetime UTC aware. Un valor no interpretable es fail-closed."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReconcileError(
                f"la marca '{cual}' de la ventana no es ISO 8601: {value!r}") from exc
    else:
        raise ReconcileError(
            f"la marca '{cual}' de la ventana no es una fecha: {value!r}")
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _wire(dt: Optional[datetime]) -> str:
    """ISO UTC SIN offset: ``audit_logs.timestamp`` es una columna naive en UTC."""
    assert dt is not None  # garantizado por __call__
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def _counter(k6_summary: object, nombre: str) -> int:
    """Contador del summary de k6, entero o error. Un contador ausente/ilegible NO se
    interpreta como 0: ``buildSummary`` los emite SIEMPRE (0 incluido), así que si falta,
    el summary no es el que este harness produce y el conteo no significa lo que dice."""
    valor = k6_summary.get(nombre) if isinstance(k6_summary, dict) else None
    if not isinstance(valor, int) or isinstance(valor, bool):
        raise ReconcileError(
            f"el summary de k6 no trae '{nombre}' como entero (vino {valor!r}): sin el "
            "conteo del guion no hay con qué comparar las filas del producto.")
    return valor


def _detail(resp: object) -> str:
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return str(getattr(resp, "text", ""))[:300]
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])
    return str(data)[:300]


def _safe(params: dict) -> dict:
    """Params para el mensaje de error (no hay secretos acá, pero se acota el ruido)."""
    return {k: v for k, v in params.items() if k != "limit"}
