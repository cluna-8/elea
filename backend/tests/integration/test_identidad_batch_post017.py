"""Contrato 2 de la 018 — identidad de los jobs batch bajo RLS (FR-006, SC-004).

Todo lo de acá corre bajo el harness del «mundo post-017» (``post017_harness``): policy
``tenant_isolation_bootstrap`` DROPEADA y conexión con un rol NOSUPERUSER, sin BYPASSRLS y
sin propiedad sobre las tablas. Ése es el mundo que la 017 activa cuando cablee la identidad
por request, y es el único donde el bug de FR-006 es visible: con la ventana bootstrap
abierta —el estado de main hoy— una sesión pelada escribe igual y estos tests pasarían sin
probar nada.

El módulo cubre dos cosas, en este orden y a propósito:

1. **Que el mundo sea de verdad el mundo post-017** (los tres primeros tests). Un harness que
   no muerde convierte al resto de la suite en decoración: si mañana alguien deja el rol con
   BYPASSRLS o el drop de policies se saltea una tabla, el que falla es el harness, acá, con
   nombre y apellido — y no la spec 018 el día que la 017 mergee.
2. **Que el emisor de la cadena de licencias sobreviva a ese mundo** (T007). Escribe fuera de
   todo request —gate de arranque y tick del scheduler— y hasta la 018 abría la sesión pelada.
   Como el emisor es fail-soft, bajo RLS cerrada no explotaba: dejaba de escribir EN SILENCIO,
   que para una cadena encadenada por hash es el peor final posible.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from migration_harness import DEFAULT_TENANT, RLS_TENANT_TABLES, require_postgres
from post017_harness import (  # noqa: F401 — `mundo_post017` se importa PARA usarse de fixture
    APP_ROLE, POLICY_BOOTSTRAP, POLICY_ESTRICTA, mundo_post017,
)

require_postgres()


# ── Utilidades ────────────────────────────────────────────────────────────────────────────

def _estado_licencia(status="active", reason="estado sintético del test"):
    """``LicenseState`` armado a mano: sin token (``license_id=None``) para que el emisor
    escriba UN solo eslabón — el anclaje diferido de la génesis sólo dispara cuando aparece
    un license_id, y acá lo que se mide es la identidad bajo RLS, no la cadena."""
    from src.licensing.entitlement import LicenseState

    return LicenseState(status=status, reason=reason, token=None,
                        checked_at=datetime.now(timezone.utc))


def _eventos_de_licencia(mundo):
    """Las entradas de la cadena, leídas DECLARANDO identidad.

    El lector también está bajo RLS: sin ``tenant_context`` este query devolvería 0 filas y el
    test no distinguiría «no se escribió» de «no puedo verlo»."""
    from src.database import tenant_context
    from src.models.audit import AuditLog

    with tenant_context(None, bypass=True):
        db = mundo.session_factory()
        try:
            # `id` desempata: el `timestamp` no lo pone la DB sino `checked_at` del estado
            # evaluado, así que dos eslabones pueden traer el mismo instante y sin desempate
            # el orden lo elige el planner — con `[-1]` leyendo «el último» eso es un test que
            # falla una vez cada tanto y nadie sabe por qué.
            filas = (db.query(AuditLog).filter(AuditLog.model == "license")
                     .order_by(AuditLog.timestamp, AuditLog.id).all())
            return [(fila.tenant_id, fila.guardian_events[0]) for fila in filas]
        finally:
            db.close()


def _verificar_cadena(mundo):
    from src.database import tenant_context
    from src.licensing.audit_events import verify_chain

    with tenant_context(None, bypass=True):
        db = mundo.session_factory()
        try:
            return verify_chain(db)
        finally:
            db.close()


def _intentar_escribir_sin_identidad(mundo):
    """INSERT en ``audit_logs`` con una sesión que no declaró nada. Bajo el mundo post-017
    tiene que rebotar contra el ``WITH CHECK`` de ``tenant_isolation``."""
    from src.models.audit import AuditLog

    db = mundo.session_factory()
    try:
        db.add(AuditLog(tenant_id=DEFAULT_TENANT, model="canario-post017",
                        prompt_tokens=0, completion_tokens=0, cost_usd=0,
                        pii_detected=False, compliance_status="passed", latency_ms=0))
        db.commit()
    finally:
        db.rollback()
        db.close()


# ── 1. El harness muerde ──────────────────────────────────────────────────────────────────

def test_la_ventana_bootstrap_esta_cerrada_en_todas_las_tablas(mundo_post017):
    """SC-004 (mitad A): cero ``tenant_isolation_bootstrap`` y la estricta intacta.

    Se exige el barrido COMPLETO (``RLS_TENANT_TABLES`` + ``tenants``) y no sólo
    ``audit_logs``: una tabla que conservara su policy permisiva sería una puerta abierta
    justo para el job que la use, y el mundo dejaría de ser el que la 017 va a activar."""
    with mundo_post017.engine.connect() as cx:
        bootstrap = cx.execute(text(
            "SELECT count(*) FROM pg_policies WHERE policyname = :policy"
        ), {"policy": POLICY_BOOTSTRAP}).scalar()
        estrictas = {r.tablename for r in cx.execute(text(
            "SELECT tablename FROM pg_policies WHERE policyname = :policy"
        ), {"policy": POLICY_ESTRICTA})}

    assert bootstrap == 0, "quedó viva la policy permisiva: el mundo NO es post-017"
    esperadas = set(RLS_TENANT_TABLES) | {"tenants"}
    assert esperadas <= set(mundo_post017.tablas_sin_bootstrap), \
        f"el harness no tocó {esperadas - set(mundo_post017.tablas_sin_bootstrap)}"
    assert esperadas <= estrictas, \
        "sin la policy estricta esto no es RLS cerrada, es RLS ausente (falso verde)"


def test_el_rol_de_la_app_no_puede_saltearse_la_rls(mundo_post017):
    """SC-004 (mitad B): NOSUPERUSER + NOBYPASSRLS + dueño de NADA.

    Las tres condiciones son necesarias y cada una tapa una forma distinta de falso verde:
    un superuser saltea RLS siempre; ``BYPASSRLS`` también; y el DUEÑO de las tablas sólo
    queda sujeto mientras ``FORCE`` siga puesto — un ``NO FORCE`` accidental en una migración
    futura lo liberaría sin que ningún test se entere. El rol de aplicación no es dueño de
    nada, así que este mundo no depende de esa bandera."""
    with mundo_post017.engine.connect() as cx:
        rol = cx.execute(text("""
            SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user
        """)).one()
        propias = cx.execute(text("""
            SELECT count(*) FROM pg_class c
            JOIN pg_roles r ON r.oid = c.relowner
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE r.rolname = current_user AND n.nspname = 'public' AND c.relkind = 'r'
        """)).scalar()

    assert rol.rolname == APP_ROLE
    assert rol.rolsuper is False, "un superuser bypasea RLS SIEMPRE, incluso con FORCE"
    assert rol.rolbypassrls is False
    assert propias == 0, "el rol de aplicación no debe ser dueño de ninguna tabla"


def test_sin_identidad_declarada_la_sesion_no_ve_ni_escribe(mundo_post017):
    """El canario del mundo post-017: una sesión pelada no lee ni escribe ``audit_logs``.

    Es el test que le da sentido a T007. Si este afloja —porque el mundo se aguó o porque la
    RLS dejó de aplicar—, el test del emisor pasaría con el bug adentro."""
    from src.models.audit import AuditLog

    db = mundo_post017.session_factory()
    try:
        assert db.query(AuditLog).count() == 0, \
            "sin GUC la sesión no debería ver NINGUNA fila (ni las que escribió otro)"
    finally:
        db.close()

    with pytest.raises(DBAPIError, match="row-level security"):
        _intentar_escribir_sin_identidad(mundo_post017)


# ── 1b. Y no deja nada suyo en el CLUSTER (gate adversarial 018, H6) ──────────────────────
#
# El harness monta un mundo descartable salvo por una cosa: el rol de aplicación. En Postgres
# los roles NO viven en la base, viven en la instancia, así que es lo único que sobrevive a la
# corrida y se ve desde todas las bases de esa instancia. Estos dos tests cuidan dos de las tres
# mitigaciones; la tercera —que el rol se borre al terminar— la hace `borrar_rol_app` en el
# teardown de la fixture y no se puede afirmar desde acá sin matarle las conexiones al mundo que
# los demás tests de este módulo todavía están usando.

def test_el_password_del_rol_de_la_app_no_esta_escrito_en_el_fuente():
    """Un password literal en el repo es una credencial CONOCIDA y permanente en toda instancia
    contra la que alguien haya corrido la suite alguna vez — incluida una real, si los
    ``POSTGRES_*`` del entorno apuntaran ahí.

    Lo que se afirma es lo observable, y es justo lo que se rompió aquella vez: que el secreto no
    esté en el archivo. «Que sea aleatorio» no se puede afirmar mirando un valor; que no esté
    versionado, sí. Si alguien vuelve a fijarlo para «poder entrar a mirar», se pone rojo acá."""
    from pathlib import Path

    import post017_harness
    from post017_harness import APP_ROLE_PASSWORD

    fuente = Path(post017_harness.__file__).read_text(encoding="utf-8")
    assert APP_ROLE_PASSWORD not in fuente, (
        f"el password de {APP_ROLE!r} está escrito en {post017_harness.__file__}: es un rol "
        "LOGIN de CLUSTER, o sea una credencial versionada que sirve en todas las bases de la "
        "instancia. Va generado por corrida (`secrets.token_urlsafe`), no literal.")
    assert len(APP_ROLE_PASSWORD) >= 16, (
        "password demasiado corto para un rol con LOGIN: si el generador se degradó, lo que "
        "queda vivo entre el CREATE y el DROP es adivinable")


def test_el_guard_frena_un_destino_que_no_parece_de_test(monkeypatch):
    """El harness crea el rol conectándose como superuser: si el entorno apunta a una caja real
    (un ``.env`` copiado, un túnel abierto), lo crea ALLÁ. El guard corre antes de tocar nada
    —incluso antes del ``DROP DATABASE`` de ``fresh_db``— y tiene que fallar RUIDOSO.

    Se muerden las dos condiciones por separado, porque cada una tapa un accidente distinto: el
    nombre de la base caza «apunté a la base equivocada en la instancia correcta», y el host caza
    «apunté a la instancia equivocada con el nombre de siempre»."""
    import post017_harness
    from post017_harness import PREFIJO_DB_TEST, _exigir_instancia_de_test

    destino_valido = f"{PREFIJO_DB_TEST}post017_canario"
    # El destino real de esta suite pasa: un guard que no deja correr nada tampoco sirve.
    _exigir_instancia_de_test(destino_valido)

    with pytest.raises(RuntimeError, match="sentinel_test_"):
        _exigir_instancia_de_test("sentinel_gateway")  # la base del producto

    monkeypatch.setattr(post017_harness, "PG_HOST", "guardian.sentinel-dev.com")
    with pytest.raises(RuntimeError, match="POSTGRES_HOST"):
        _exigir_instancia_de_test(destino_valido)


# ── 2. El emisor de la cadena bajo ese mundo (T007 / FR-006) ──────────────────────────────

def test_el_emisor_de_la_cadena_escribe_bajo_rls_cerrada(mundo_post017):
    """FR-006: ``emit_state_event`` persiste su eslabón con la ventana bootstrap cerrada.

    Con el ``SessionLocal()`` pelado anterior esto daba CERO filas y ni siquiera una
    excepción: el ``except`` fail-soft del emisor se comía el rechazo de la RLS y la cadena
    se congelaba en silencio. La línea de base se lee del propio mundo (no se asume DB
    vacía): el test no depende del orden de ejecución del módulo."""
    from src.licensing.audit_events import EVENT_LOADED, emit_state_event

    antes = _eventos_de_licencia(mundo_post017)

    emit_state_event(_estado_licencia(), session_factory=mundo_post017.session_factory)

    despues = _eventos_de_licencia(mundo_post017)
    assert len(despues) == len(antes) + 1, \
        "el emisor no escribió su eslabón bajo RLS cerrada (FR-006)"

    tenant, entrada = despues[-1]
    assert entrada["event_type"] == EVENT_LOADED
    assert entrada["seq"] == len(antes) + 1
    assert tenant == DEFAULT_TENANT, "la fila se atribuye al tenant del deployment"

    veredicto = _verificar_cadena(mundo_post017)
    assert veredicto["ok"], veredicto["issues"]
    assert veredicto["checked"] == len(despues)


def test_el_bypass_del_emisor_es_explicito_y_localizado(mundo_post017):
    """Contrato 2, regla 2: el bypass muere con el ``with`` — jamás queda de default.

    Muerde contra el atajo obvio (setear los ContextVar al importar el módulo, o dejarlos
    seteados «porque el job igual los necesita»): tras la corrida, no sólo los ContextVar
    vuelven a su valor de reposo, sino que una sesión NUEVA sigue sin poder escribir. Si
    alguien globalizara el bypass, ese segundo INSERT pasaría y este test lo agarra."""
    from src.database import current_tenant_id, rls_bypass
    from src.licensing.audit_events import emit_state_event

    assert rls_bypass.get() is False and current_tenant_id.get() is None

    emit_state_event(_estado_licencia(status="grace", reason="vence pronto"),
                     session_factory=mundo_post017.session_factory)

    assert rls_bypass.get() is False, "el bypass quedó pegado como default de sesión"
    assert current_tenant_id.get() is None

    with pytest.raises(DBAPIError, match="row-level security"):
        _intentar_escribir_sin_identidad(mundo_post017)


# ── 3. El job de reconciliación de seats bajo ese mundo (H2 / FR-006) ─────────────────────
#
# El emisor de arriba escribe; éste además LEE, y ahí está la diferencia que importa. Un
# escritor sin identidad rebota contra el `WITH CHECK` y deja al menos una excepción que
# alguien puede loguear; un lector sin identidad no rebota: recibe cero filas y sigue
# trabajando como si el sistema estuviera vacío. Por eso la reconciliación es el peor caso de
# FR-006 de todo el backend hoy.

@pytest.fixture
def reconciliacion_limpia():
    """Los dos singletons EN MEMORIA que toca una corrida, a cero antes y después.

    ``reconcile._registry`` es lo que el gate de creación consulta y ``entitlement._state``
    decide qué tenant está licenciado: los dos son globales de módulo y sobreviven a cualquier
    test que los haya tocado antes. Sin este reset, un registro heredado de otra corrida haría
    pasar el assert de abajo sin que el job hubiera visto una sola fila — justo el falso verde
    que este test viene a impedir. El reset de salida es simetría: lo que se ensucia acá no se
    le deja puesto al módulo siguiente.
    """
    from src.licensing import entitlement, reconcile

    reconcile.reset_for_tests()
    entitlement.reset_for_tests()
    try:
        yield reconcile
    finally:
        reconcile.reset_for_tests()
        entitlement.reset_for_tests()


def test_la_reconciliacion_ve_los_tenants_bajo_rls_cerrada(mundo_post017, reconciliacion_limpia):
    """FR-006: ``run_once`` recorre los tenants con la ventana bootstrap cerrada.

    La reconciliación es el job que enforcea los asientos: corre en su propio thread (lo
    arranca ``main.py`` en el lifespan), lee ``tenants``, cuenta seats sobre ``api_keys`` y
    publica un estado por tenant que el gate de creación consulta para degradar. Las tres
    tablas están bajo RLS con FORCE.

    Con el ``session_factory()`` pelado que tenía hasta la 018, en este mundo el
    ``query(Tenant)`` devuelve CERO filas: el bucle no entra nunca, el registro queda vacío,
    ``get_tenant_status`` empieza a devolver ``None`` para todos y el enforcement de licencia
    se apaga SIN UNA SOLA EXCEPCIÓN. Ni siquiera se activan los ``except`` best-effort del
    audit, porque no hay transición que emitir: la corrida termina «bien», a tiempo y sin
    ruido, midiendo un sistema vacío. Un job que falla se ve en los logs; éste no fallaba.
    """
    publicado = reconciliacion_limpia.run_once(session_factory=mundo_post017.session_factory)

    assert str(DEFAULT_TENANT) in publicado, (
        "la reconciliación no vio ni el tenant del deployment: sin identidad declarada el "
        "query(Tenant) devuelve cero filas y la corrida termina en silencio con el registro "
        "vacío (FR-006)")
    assert reconciliacion_limpia.get_tenant_status(DEFAULT_TENANT) is not None, (
        "el gate de creación lee el estado PUBLICADO: si es None no degrada nada y el "
        "enforcement de asientos queda apagado sin que nadie se entere")


def test_el_bypass_de_la_reconciliacion_muere_con_la_corrida(mundo_post017, reconciliacion_limpia):
    """Contrato 2, regla 2, del lado del LECTOR: el bypass no sobrevive a ``run_once``.

    El gemelo del test del emisor, y hace falta aparte porque tapa un agujero propio: si
    alguien «arreglara» el test de arriba globalizando los ContextVar —seteados al importar,
    o puestos y nunca reseteados— pasaría igual, y este mundo dejaría de probar nada para el
    resto del módulo. Se afirma sobre la MISMA query que el job necesita: una sesión nueva,
    después de la corrida, vuelve a ver cero tenants. Si ve uno, la RLS dejó de aplicar y el
    verde de arriba era decoración.
    """
    from src.database import current_tenant_id, rls_bypass
    from src.models.tenant import Tenant

    assert rls_bypass.get() is False and current_tenant_id.get() is None

    reconciliacion_limpia.run_once(session_factory=mundo_post017.session_factory)

    assert rls_bypass.get() is False, "el bypass quedó pegado como default de sesión"
    assert current_tenant_id.get() is None

    db = mundo_post017.session_factory()
    try:
        assert db.query(Tenant).count() == 0, \
            "una sesión sin identidad sigue sin ver tenants — si los ve, el bypass se escapó"
    finally:
        db.close()
