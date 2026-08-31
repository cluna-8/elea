"""Harness del «mundo post-017»: RLS sin la red de contención de la 010 (spec 018, Contrato 2).

## Qué mundo monta este módulo, y por qué existe

Hoy las 14 tablas tenant-scoped —más la propia ``tenants``— están bajo ``ENABLE`` + ``FORCE
ROW LEVEL SECURITY``, pero en la práctica no dejan a nadie afuera: junto a la policy
estricta ``tenant_isolation``, la
010 creó una permisiva ``tenant_isolation_bootstrap`` que deja pasar TODA fila mientras el
GUC ``app.current_tenant`` no esté seteado (las policies permisivas se OR-ean). Esa es la
ventana de deploy on-prem —cero regresión mientras la identidad no está cableada— y la 017
tiene mandato ESCRITO de cerrarla (`010_multitenant_foundation.py:33-38`, `database.py:38`).

El día que la 017 mergee, cualquier job batch que abra una sesión sin declarar identidad
deja de ver —y de escribir— sus propias filas. Para la 018 ese es el peor modo de falla
imaginable: un purgador que pasa de borrar a no encontrar nada, en silencio, dejando una
retención que APARENTA estar enforced sin estarlo (spec 018, FR-006). Por eso existe este
harness: monta HOY el mundo que la 017 activa DESPUÉS, para que el contrato de identidad de
los jobs se pruebe antes y no el día del merge de la otra spec. Si esto se lee dentro de tres
meses y la 017 ya está en main, este harness dejó de ser una simulación y pasó a ser una
segunda verificación del mismo mundo: sigue siendo útil, pero ya no es la única.

## Las dos mitades del mundo (SC-004)

1. **Sin policy bootstrap**: se dropea ``tenant_isolation_bootstrap`` de toda tabla que la
   tenga, DESCUBIERTAS en ``pg_policies`` y no leídas de una lista hardcodeada. Es a
   propósito: una tabla nueva que nazca con las dos policies entra sola al mundo post-017,
   en vez de quedar como un agujero mudo — que es exactamente cómo se coló
   ``governance_profiles`` sin RLS hasta que la 027 lo encontró.
2. **Rol NOSUPERUSER que además NO es dueño de nada**: ``migration_harness`` ya conecta con
   ``rls_owner`` (NOSUPERUSER, y por eso ``FORCE`` es observable), pero ese rol es el DUEÑO
   de las tablas: le alcanza un ``NO FORCE`` accidental en una migración futura para que el
   aislamiento se evapore sin que nadie se entere. El runtime post-017 se conecta con un rol
   de aplicación —NOSUPERUSER, NOBYPASSRLS, sin propiedad, sólo DML—, y ése es el que este
   harness crea ad-hoc en la DB de test (``sentinel_app_post017``). Un no-dueño está sujeto a RLS
   con FORCE o sin FORCE: el mundo que monta acá no depende de que esa bandera siga puesta.

## El rol de aplicación es una credencial de CLUSTER, no de la base de test

``sentinel_app_post017`` se crea con ``LOGIN``, y en Postgres los roles NO viven en la base: viven
en la instancia y se ven desde todas sus bases. O sea que este harness, que por lo demás sólo
toca una base descartable, deja atrás lo único suyo que no es descartable. Con el password
escrito en el fuente eso era una credencial conocida y permanente en cualquier instancia contra
la que alguien corriera la suite — incluida una real, si los ``POSTGRES_*`` del entorno
apuntaran ahí (gate adversarial de la 018, H6). Tres medidas, y las tres hacen falta:

1. **Password aleatorio por corrida** (``APP_ROLE_PASSWORD``): lo que quede vivo después no es
   una credencial que nadie pueda usar — el secreto muere con el proceso.
2. **Se borra al terminar** (``borrar_rol_app``): lo normal es que no quede nada. Es
   best-effort y avisa con un warning cuando no puede, porque romper la suite por la limpieza
   sería peor que el problema que limpia.
3. **Guard de destino** (``_exigir_instancia_de_test``): antes de crear nada se verifica que
   la instancia huela a test. Falla ruidoso y explicando, no en silencio.

## El listener del GUC no viene gratis en los tests

En producción el GUC lo inyecta un listener registrado sobre ``SessionLocal``
(`database.py:44`). Un ``sessionmaker`` de test es OTRO objeto y nace SIN ese listener: si el
harness no lo re-registra, ``tenant_context`` no inyecta nada, ningún job vería sus filas y
los tests estarían midiendo el harness en vez del código. Por eso el ``session_factory`` que
devuelve ``construir_mundo_post017`` viene con ``_inject_tenant_guc`` ya enganchado — es el
equivalente exacto de ``SessionLocal``, apuntado a la DB de test.

## Uso

    from post017_harness import mundo_post017  # noqa: F401  (fixture, scope de módulo)

    def test_algo(mundo_post017):
        # La sesión se ABRE Y SE CIERRA DENTRO del bloque. No al revés.
        with tenant_context(None, bypass=True):
            db = mundo_post017.session_factory()
            try:
                ...                            # identidad declarada: el job trabaja
            finally:
                db.close()

⚠️ **Nunca crees la sesión ANTES del `with`.** Una sesión abierta afuera que dispare su primera
consulta adentro abre su transacción adentro y se lleva el bypass a todo lo que haga después,
ya fuera del bloque: un bypass de RLS fugado de su alcance, en el proceso que además hace
`DELETE`. El módulo recibe `session_factory` y jamás una `Session` ya viva, justamente para que
el camino natural —abrir adentro— sea el correcto. Patrón vivo del que copiar:
`licensing/audit_events.py::emit_state_event`.
"""
import secrets
import warnings
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from migration_harness import (
    ADMIN_PASSWORD, ADMIN_USER, PG_HOST, RLS_OWNER, RLS_OWNER_PASSWORD, fresh_db, run_alembic,
    url,
)

# Rol de aplicación del mundo post-017. Nombre propio (no ``rls_owner``) porque la diferencia
# ES el punto: éste no es dueño de ninguna tabla.
APP_ROLE = "sentinel_app_post017"
# Password ALEATORIO por corrida y NO un literal en el fuente (ver el docstring del módulo):
# el rol es un objeto de cluster con LOGIN, así que un password fijo y versionado es una
# credencial conocida en toda instancia contra la que se haya corrido la suite alguna vez.
# `token_urlsafe` da alfabeto `[A-Za-z0-9_-]`: entra igual en el literal SQL del CREATE/ALTER
# y en la URL de conexión, sin escapes de por medio.
APP_ROLE_PASSWORD = secrets.token_urlsafe(24)

POLICY_BOOTSTRAP = "tenant_isolation_bootstrap"
POLICY_ESTRICTA = "tenant_isolation"

# ── Guard de destino ──────────────────────────────────────────────────────────────────
# Los dos olores de «esto es una instancia de test». El del nombre de la base es el
# específico; el del host, el grueso. Ver `_exigir_instancia_de_test`.
PREFIJO_DB_TEST = "sentinel_test_"
HOSTS_DE_TEST = frozenset({
    "localhost", "127.0.0.1", "::1",  # la suite corrida desde el host (compose publica 5433)
    "db", "postgres",                 # el servicio de Postgres dentro de la red del compose
})


@dataclass
class MundoPost017:
    """La DB de test ya migrada, con la ventana bootstrap cerrada y un engine/factory
    conectados como el rol de aplicación. ``session_factory`` trae el listener del GUC."""
    dbname: str
    engine: object
    session_factory: object
    rol: str = APP_ROLE
    tablas_sin_bootstrap: tuple = ()


def _admin_autocommit(dbname: str = "postgres"):
    """CREATE ROLE / GRANT van como superuser: los GRANT son sobre tablas de ``rls_owner``
    y en PG16 el schema ``public`` es de ``pg_database_owner`` — el superuser saltea las dos
    discusiones de propiedad de una."""
    return create_engine(url(ADMIN_USER, ADMIN_PASSWORD, dbname), isolation_level="AUTOCOMMIT")


def _admin_exec(sql: str, dbname: str = "postgres", params: dict = None) -> None:
    """Una sentencia como superuser, con el engine siempre devuelto. Existe para que la
    limpieza del rol —que abre y cierra tres conexiones distintas— no repita el `dispose`."""
    engine = _admin_autocommit(dbname)
    try:
        with engine.connect() as cx:
            cx.execute(text(sql), params or {})
    finally:
        engine.dispose()


def _exigir_instancia_de_test(dbname: str) -> None:
    """Aborta —ruidoso— si el destino no huele a instancia de test.

    Este harness CREA UN ROL, y los roles son objetos de CLUSTER: no viven en la base
    descartable, viven en la instancia y se ven desde todas sus bases. Si alguien corre la
    suite con los ``POSTGRES_*`` apuntados a una caja real (el env de un despliegue, un túnel
    abierto, un ``.env`` copiado de otro lado), el rol nace ALLÁ y sobrevive a la corrida. Por
    eso el destino se verifica ANTES de tocar nada.

    Dos condiciones, porque ninguna sola alcanza. El nombre de la base es lo específico —y lo
    que más importa, porque ``fresh_db`` hace ``DROP DATABASE``: apuntar a una base real ya
    sería un desastre mucho mayor que el rol—. El host es lo grueso: caza el entorno apuntado a
    otra caja aunque la base se llame igual. Ninguna de las dos reemplaza a no apuntar la suite
    a producción; lo que cierran es el accidente obvio.

    Falla con ``RuntimeError`` y con el motivo escrito: quien lo lea tiene que poder decidir si
    agregar su host a ``HOSTS_DE_TEST`` (CI con otro nombre de servicio) o si acaba de
    esquivar un incidente.
    """
    motivos = []
    if not dbname.startswith(PREFIJO_DB_TEST):
        motivos.append(
            f"la base destino es {dbname!r} y no empieza con {PREFIJO_DB_TEST!r} — este harness "
            "sólo trabaja sobre bases descartables (las borra y las recrea)")
    if PG_HOST not in HOSTS_DE_TEST:
        motivos.append(
            f"POSTGRES_HOST={PG_HOST!r} no está en {sorted(HOSTS_DE_TEST)} — si es un host de "
            "test nuevo (CI con otro nombre de servicio), agregalo a HOSTS_DE_TEST; si no lo "
            "es, esto acaba de frenar la creación de un rol LOGIN en un cluster ajeno")
    if motivos:
        raise RuntimeError(
            "post017_harness: el destino no parece una instancia de test y el harness crea un "
            "rol LOGIN, que en Postgres es un objeto de CLUSTER (queda vivo en TODAS las bases "
            "de la instancia, no sólo en la de test). Motivos:\n  · " + "\n  · ".join(motivos))


def asegurar_rol_app(dbname: str) -> None:
    """Crea (o re-normaliza) el rol de aplicación NOSUPERUSER / NOBYPASSRLS.

    El ``ALTER`` no es decorativo: los roles viven en el CLUSTER, no en la base, así que un
    rol dejado por otra corrida podría venir con atributos cambiados. Sin re-normalizar,
    un ``BYPASSRLS`` heredado dejaría pasar toda la suite en verde sin probar nada. Y de paso
    le pone el password de ESTA corrida al rol que haya sobrevivido a una limpieza fallida.

    ``dbname`` no se usa para conectar (esto va a la base de mantenimiento): se pide para
    correr el guard de destino justo acá, delante de la única sentencia del harness que crea
    algo fuera de la base descartable.
    """
    _exigir_instancia_de_test(dbname)
    engine = _admin_autocommit()
    with engine.connect() as cx:
        cx.execute(text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                    CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_ROLE_PASSWORD}';
                END IF;
            END $$;
        """))
        cx.execute(text(
            f"ALTER ROLE {APP_ROLE} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE "
            f"LOGIN PASSWORD '{APP_ROLE_PASSWORD}'"
        ))
    engine.dispose()


def borrar_rol_app(dbname: str) -> None:
    """Borra el rol de aplicación al terminar. Best-effort, pero RUIDOSO cuando no puede.

    Sin esto el harness dejaba su rol vivo en el cluster después de correr la suite: con
    ``LOGIN``, en todas las bases de la instancia y para siempre (nadie lo borraba nunca). El
    password aleatorio quita el filo —lo que sobreviva ya no es una credencial que alguien
    pueda usar—, pero un rol que no debería existir sigue siendo algo que hay que barrer.

    Tres pasos y en este orden: (1) echar las sesiones del rol, porque un rol con conexiones
    abiertas no se dropea; (2) ``DROP OWNED BY`` en la base de test, porque los ``GRANT`` de
    ``otorgar_dml`` quedan registrados como dependencias del rol EN ESA BASE y sin soltarlos el
    ``DROP ROLE`` falla con «privileges for table …»; (3) el ``DROP ROLE``, en la base de
    mantenimiento.

    Si aun así falla —el caso conocido: quedaron GRANTs suyos en OTRA base de test de una
    corrida anterior, y esas dependencias sólo se sueltan desde adentro de cada base— NO se
    rompe la suite: se avisa con un warning. Fallar la corrida entera por la limpieza sería
    cambiar un problema de higiene por uno de disponibilidad, y el warning igual hace que
    alguien se entere.

    Ojo el día que dos módulos monten el mundo a la vez: el paso (1) echa TODAS las sesiones
    del rol, no sólo las de este mundo. Con un único consumidor —hoy,
    ``test_identidad_batch_post017``— no hay a quién pisar; con dos, esto hay que scopearlo.
    """
    try:
        _admin_exec(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE usename = :rol AND pid <> pg_backend_pid()",
            params={"rol": APP_ROLE},
        )
        _admin_exec(f"DROP OWNED BY {APP_ROLE}", dbname=dbname)
        _admin_exec(f"DROP ROLE IF EXISTS {APP_ROLE}")
    except Exception as error:  # noqa: BLE001 — la limpieza jamás tumba la suite
        warnings.warn(
            f"post017_harness: no se pudo borrar el rol {APP_ROLE!r} ({error}). Queda vivo en el "
            f"CLUSTER de {PG_HOST!r} —con LOGIN y visible desde todas sus bases— hasta que "
            f"alguien lo borre a mano (`DROP OWNED BY {APP_ROLE}` en cada base de test y después "
            f"`DROP ROLE {APP_ROLE}`). Su password es aleatorio y murió con este proceso, así "
            "que no es una credencial utilizable, pero no debería seguir ahí.",
            stacklevel=2,
        )


def otorgar_dml(dbname: str) -> None:
    """Privilegios del rol de aplicación: DML y nada más.

    Sin ``TRUNCATE``, sin ``REFERENCES``, sin ``TRIGGER`` y sin propiedad — el runtime lee,
    escribe y borra filas; el esquema lo mueve alembic con OTRO rol. Que el purgador necesite
    ``DELETE`` (y sólo ``DELETE``) es parte de lo que este harness deja verificable."""
    engine = _admin_autocommit(dbname)
    with engine.connect() as cx:
        cx.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
        cx.execute(text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
        ))
        # Las PK con default de Python no la usan, pero las columnas serial heredadas sí.
        cx.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}"))
    engine.dispose()


def cerrar_ventana_bootstrap(dbname: str) -> tuple:
    """Dropea ``tenant_isolation_bootstrap`` de TODAS las tablas que la tengan (lo que la 017
    hace al cablear la identidad) y devuelve la tupla de tablas tocadas.

    Va como dueño (``rls_owner``): ``DROP POLICY`` exige propiedad de la tabla. Verifica
    después —y grita— que no quedó ninguna y que la policy ESTRICTA sigue viva: un mundo sin
    ninguna de las dos no es «post-017», es «sin RLS», y ahí los tests pasarían por el motivo
    equivocado."""
    engine = create_engine(url(RLS_OWNER, RLS_OWNER_PASSWORD, dbname))
    try:
        with engine.begin() as cx:
            tablas = tuple(r.tablename for r in cx.execute(text("""
                SELECT DISTINCT tablename FROM pg_policies
                WHERE schemaname = 'public' AND policyname = :policy
                ORDER BY tablename
            """), {"policy": POLICY_BOOTSTRAP}))
            for tabla in tablas:
                cx.execute(text(f'DROP POLICY IF EXISTS {POLICY_BOOTSTRAP} ON "{tabla}"'))

        with engine.connect() as cx:
            quedan = cx.execute(text(
                "SELECT count(*) FROM pg_policies WHERE policyname = :policy"
            ), {"policy": POLICY_BOOTSTRAP}).scalar()
            estrictas = cx.execute(text(
                "SELECT count(*) FROM pg_policies WHERE policyname = :policy"
            ), {"policy": POLICY_ESTRICTA}).scalar()
    finally:
        engine.dispose()

    if quedan:
        raise RuntimeError(
            f"mundo post-017 incompleto: quedaron {quedan} policies {POLICY_BOOTSTRAP}"
        )
    if not estrictas:
        raise RuntimeError(
            f"mundo post-017 inválido: no quedó ninguna policy {POLICY_ESTRICTA} — eso no es "
            "RLS cerrada, es RLS ausente"
        )
    return tablas


def app_engine(dbname: str):
    return create_engine(url(APP_ROLE, APP_ROLE_PASSWORD, dbname))


def session_factory_con_guc(engine):
    """``sessionmaker`` gemelo de ``SessionLocal``, con el listener del GUC enganchado.

    Devuelve ``(factory, desenganchar)``: el listener se registra sobre ESTE sessionmaker
    (objeto local del test), así que no toca el ``SessionLocal`` de producción."""
    from src.database import _inject_tenant_guc

    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    event.listen(factory, "after_begin", _inject_tenant_guc)

    def desenganchar():
        event.remove(factory, "after_begin", _inject_tenant_guc)

    return factory, desenganchar


def construir_mundo_post017(dbname: str):
    """DB fresca → head → ventana bootstrap cerrada → rol de aplicación conectado.

    Devuelve ``(MundoPost017, cerrar)``; el caller es dueño del ciclo de vida (misma
    convención que ``seat_gate_harness.build_app_client``). ``cerrar`` también BORRA el rol:
    es lo único que este harness deja fuera de la base descartable (ver el docstring del
    módulo)."""
    # Antes de `fresh_db`, que hace DROP DATABASE: si el destino no es de test, el guard tiene
    # que frenar la corrida ANTES de destruir nada, no después.
    _exigir_instancia_de_test(dbname)
    fresh_db(dbname)
    run_alembic(dbname, "upgrade", "head")
    asegurar_rol_app(dbname)
    otorgar_dml(dbname)
    tablas = cerrar_ventana_bootstrap(dbname)

    engine = app_engine(dbname)
    factory, desenganchar = session_factory_con_guc(engine)
    mundo = MundoPost017(dbname=dbname, engine=engine, session_factory=factory,
                         tablas_sin_bootstrap=tablas)

    def cerrar():
        desenganchar()
        # El `dispose` primero: cierra las conexiones del pool que están abiertas COMO el rol,
        # que son justamente las que impedirían dropearlo.
        engine.dispose()
        borrar_rol_app(dbname)

    return mundo, cerrar


def _dbname_para(modulo: str) -> str:
    """Una DB por módulo de test (los identificadores de Postgres toleran 63 chars)."""
    return f"sentinel_test_post017_{modulo.rsplit('.', 1)[-1]}"[:63]


@pytest.fixture(scope="module")
def mundo_post017(request):
    """El mundo post-017 para el módulo que la pide (ver docstring del módulo).

    Scope de módulo por costo: montar la DB es ``fresh_db`` + alembic completo. Los tests que
    cuentan filas leen su propia línea de base en vez de asumir una DB vacía — la disciplina
    de siempre: cada test autosuficiente e independiente del orden.
    """
    dbname = _dbname_para(request.module.__name__)
    mundo, cerrar = construir_mundo_post017(dbname)
    try:
        yield mundo
    finally:
        cerrar()
