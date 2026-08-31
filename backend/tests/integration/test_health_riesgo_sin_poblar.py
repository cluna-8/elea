"""Señal de riesgo sin poblar en `/api/v1/health` — contra Postgres REAL (spec 038 D2).

El agujero que cubre la sonda (`health.py::_usuarios_sin_riesgo_cacheado` +
`_estado_de_auditoria`): desde D1 el modo por defecto es `policy`, o sea que la decisión
servir/cortar sale de `applied_risk_level`, y esa columna es NULLABLE SIN DEFAULT en toda la
cascada. Una instalación nueva resuelve `None` para TODO su tráfico —y `None` corta—, así
que se comporta como `closed` sin que nadie haya pedido `closed`. La sonda lo dice en el
PRIMER `/health`, antes del primer pedido.

**Por qué este archivo es de integración y no un test unitario más de
`tests/unit/test_health_audit.py`, que es donde vive todo lo demás del endpoint**: aquel
archivo monta el health con un `_FakeSession` que implementa `execute()`/`get_bind()`/
`rollback()` y **no implementa `query()`**. La sonda hace `db.query(User)…count()`, con lo
cual contra ese doble levanta `AttributeError`, el `except Exception` de la sonda la captura,
el conteo queda en 0 y la señal NO DEGRADA NUNCA. Un test escrito ahí sería exactamente lo
que este encargo vino a evitar: pasaría igual con la sonda BORRADA del código de producción.
Acá el padrón es de verdad —usuarios reales en una base migrada a head— así que el conteo
es el conteo y el testigo negativo puede rojear.

Ambigüedad que este archivo tiene que esquivar y por eso se nombra: el motivo del TIER
(038 D3, `_tier_estricto_cacheado`) también contiene la subcadena `SENTINEL_AUDIT_FAIL=policy`.
Afirmar sólo eso no distinguiría una degradación de la sonda de una del tier — de ahí que
todo testigo positivo del motivo pida ADEMÁS el número de usuarios (que el motivo del tier
no tiene) y niegue explícitamente el texto del tier.

Los cinco testigos de la spec, más tres de forma de la query (grupo, `is_active`, conteo
filtrado) que existen porque son los filtros que un refactor rompe sin que nada más chille.
"""
import sys
import uuid
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "sentinel_test_health_riesgo_sin_poblar"

HEALTH = "/api/v1/health"

#: Prefijo de TODA fila que crea este módulo (usuarios y grupos): el teardown la reconoce
#: por acá y no por id, así un test que aborte a mitad no le deja padrón sucio al siguiente.
PREFIJO = "riesgo-sin-poblar"

#: Los usuarios de prueba jamás se loguean: hashear con bcrypt de verdad costaría ~250 ms
#: por fila para un campo que nadie verifica. El centinela es el mismo patrón que usa el
#: seed de clients por config (`password_hash` que no verifica nunca).
HASH_CENTINELA = "sin-login-jamas-centinela-038"

#: Nivel que la matriz D2 SÍ sirve (`audit_service._RISK_LEVELS_SIRVE`).
RIESGO_BAJO = "limited"

#: Fragmentos del motivo de la sonda (`health.py::_estado_de_auditoria`). Se acoplan a la
#: copy a propósito: el número y el modo son lo que el operador lee para saber a cuántos
#: usuarios le está por cortar el tráfico, no un detalle de formato.
MODO_EN_EL_MOTIVO = "SENTINEL_AUDIT_FAIL=policy"
MOTIVO_SONDA = "no resuelven nivel de riesgo"
#: Motivo del TIER (038 D3): dice `SENTINEL_AUDIT_FAIL=policy` IGUAL que el de la sonda. Se
#: niega explícitamente en cada testigo para que una degradación por tier no se lea como
#: una degradación por padrón (ver el header del módulo).
MOTIVO_TIER = "el tier de enforcement es estricto"


def conteo_en_el_motivo(n: int) -> str:
    """El pedazo del motivo que NINGÚN otro motivo del health puede producir: el número."""
    return f"{n} usuario(s) activo(s)"


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    """DB fresca migrada a head + app real, con la sesión del admin ya en las cabeceras.

    El `reason` sólo viaja al tier de operación (admin/compliance_officer): sin la sesión,
    todos los testigos de este archivo mirarían un body que ni siquiera trae el campo.
    """
    client, factory, cleanup = build_app_client(DB)
    client.headers.update(admin_headers(client))
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def modo_policy_por_defecto(monkeypatch):
    """La env es global al proceso: cada test parte de la env AUSENTE, que desde D1 resuelve
    a `policy` (el default). Los testigos de override (`open`/`closed`) la fijan ellos."""
    from src.services import audit_service
    monkeypatch.delenv(audit_service.AUDIT_FAIL_ENV, raising=False)


@pytest.fixture(autouse=True)
def padron_controlado(harness):
    """El padrón ES el sujeto de estos tests, así que no se hereda: cada uno arranca con
    TODOS los usuarios activos resolviendo `None` (sin riesgo propio y sin grupo) y devuelve
    la base a ese estado al terminar.

    El orden del teardown importa: primero se despuebla —que también desengancha el
    `group_id` de los usuarios que quedan— y recién después se borran los grupos de prueba;
    al revés, la FK `users.group_id → groups.id` haría fallar el borrado.

    El cache en proceso de la sonda lo resetea la fixture autouse de `tests/conftest.py`
    (`_resetear_caches_de_health`): sin ella un test heredaría el conteo del anterior.
    """
    _, factory = harness
    despoblar_todos(factory)
    yield
    despoblar_todos(factory)
    borrar_filas_de_prueba(factory)


# ── Helpers del padrón (nunca reimplementan la cascada: la CONSTRUYEN) ────────────
#
# Ninguno de estos helpers replica la query de la sonda —hacerlo volvería tautológico el
# conteo esperado—: lo que hacen es forzar el mundo a un estado donde el número correcto se
# deduce por construcción (todos sin riesgo ⇒ el conteo es la cantidad de activos; todos
# poblados ⇒ es cero).


def usuarios_activos(factory) -> int:
    """Cuántos usuarios ACTIVOS hay, sin mirar riesgo ni grupo."""
    from src.models.user import User
    db = factory()
    try:
        return db.query(User).filter(User.is_active.is_(True)).count()
    finally:
        db.close()


def despoblar_todos(factory) -> int:
    """Deja a TODOS los usuarios resolviendo `None`: sin `risk_level` propio y sin grupo.

    Se tocan los dos eslabones y no sólo el riesgo del usuario: con el `group_id` intacto,
    un usuario podría seguir resolviendo por el `default_risk_level` de su grupo y el
    conteo esperado dejaría de ser deducible por construcción.
    """
    from src.models.user import User
    db = factory()
    try:
        filas = db.query(User).all()
        for usuario in filas:
            usuario.risk_level = None
            usuario.group_id = None
        db.commit()
        return len(filas)
    finally:
        db.close()


def poblar_todos(factory, nivel: str = RIESGO_BAJO) -> int:
    """Puebla `risk_level` en CADA usuario activo. Devuelve cuántos tocó.

    Poblar «el admin» y no todos sería el error clásico de este testigo: la base del harness
    puede tener más de un usuario activo (los que mintee un test previo del módulo), y con
    uno solo sin poblar el motivo sigue apareciendo — se leería como que la sonda no se
    apaga cuando en realidad el padrón nunca se terminó de poblar.
    """
    from src.models.user import User
    db = factory()
    try:
        activos = db.query(User).filter(User.is_active.is_(True)).all()
        assert activos, "sin usuarios activos no hay padrón que poblar ni testigo que dar"
        for usuario in activos:
            usuario.risk_level = nivel
        db.commit()
        return len(activos)
    finally:
        db.close()


def crear_usuario(factory, *, activo: bool = True, risk_level=None, group_id=None):
    """Un usuario más en el padrón, por DB directa.

    Por DB directa y no por `POST /users`: ese endpoint construye el `User(...)` con una
    lista explícita de columnas que NO incluye `risk_level` (lo descarta en silencio), y
    además pasa por el gate de seats — dos cosas ajenas a lo que se mide acá.
    """
    from src.models.user import User
    nombre = f"{PREFIJO}-{uuid.uuid4().hex[:8]}"
    db = factory()
    try:
        usuario = User(
            username=nombre,
            # @sentinel.com.ar (no .test): `UserResponse.email` es EmailStr y rechaza el TLD
            # reservado, con lo que un GET /users explotaría al serializar estas filas.
            email=f"{nombre}@sentinel.com.ar",
            password_hash=HASH_CENTINELA,
            role="client",
            is_active=activo,
            risk_level=risk_level,
            group_id=group_id,
        )
        db.add(usuario)
        db.commit()
        return usuario.id
    finally:
        db.close()


def crear_grupo(factory, *, default_risk_level=None):
    from src.models.user import Group
    nombre = f"{PREFIJO}-{uuid.uuid4().hex[:8]}"
    db = factory()
    try:
        grupo = Group(name=nombre, default_risk_level=default_risk_level)
        db.add(grupo)
        db.commit()
        return grupo.id
    finally:
        db.close()


def asignar_grupo_a_todos(factory, group_id) -> int:
    """Mete a todos los activos en un grupo SIN tocarles el `risk_level` propio: es el
    escenario donde el riesgo lo tiene que aportar el eslabón grupo de la cascada."""
    from src.models.user import User
    db = factory()
    try:
        activos = db.query(User).filter(User.is_active.is_(True)).all()
        for usuario in activos:
            usuario.group_id = group_id
        db.commit()
        return len(activos)
    finally:
        db.close()


def borrar_filas_de_prueba(factory):
    from src.models.user import Group, User
    db = factory()
    try:
        db.query(User).filter(User.username.like(f"{PREFIJO}%")).delete(
            synchronize_session=False)
        db.query(Group).filter(Group.name.like(f"{PREFIJO}%")).delete(
            synchronize_session=False)
        db.commit()
    finally:
        db.close()


def probe(client) -> dict:
    """Un `GET /api/v1/health` del tier de OPERACIÓN, con el body ya validado.

    El `assert "reason" in body` no es decorativo: si la sesión del harness dejara de
    resolver al tier detallado, el campo desaparecería del body y todos los testigos que
    afirman «no hay motivo» pasarían por la razón equivocada.
    """
    respuesta = client.get(HEALTH)
    assert respuesta.status_code == 200, respuesta.text
    body = respuesta.json()
    assert "reason" in body and "audit" in body, (
        "el harness pega con la sesión admin: sin el tier detallado no hay `reason` que "
        f"mirar y estos tests medirían otra cosa (vino {sorted(body)})")
    return body


def sin_motivo(body, contexto: str):
    """Afirma que el health quedó limpio, nombrando primero al sospechoso de este archivo."""
    reason = body["reason"] or ""
    assert MOTIVO_SONDA not in reason and MODO_EN_EL_MOTIVO not in reason, (
        f"{contexto}: la señal de riesgo sin poblar no debería estar y está — {reason!r}")
    assert body["reason"] is None, (
        f"{contexto}: el health tiene que quedar SIN ningún motivo; apareció otro distinto "
        f"del de la sonda ({reason!r}) — si es el del tier o el del NLP, el entorno del "
        "módulo se ensució y este test ya no mide lo que dice medir")
    assert body["status"] == "healthy", f"{contexto}: sin motivos el estado es healthy"


# ── 1. Testigo NEGATIVO: la sonda no es un adorno ─────────────────────────────────


def test_policy_con_el_padron_sin_poblar_DEGRADA_el_health(harness):
    """El invariante central (038 D2): con `policy` —el default— y usuarios activos que
    resuelven `None`, el `/health` lo DICE, con el modo y con cuántos son.

    Es la única forma que tiene el operador de enterarse ANTES de la caída: sin esto, la
    primera noticia de que su instalación se comporta como `closed` llega el día que la
    auditoría se cae y corta el tráfico entero con 503.

    Vacuidad: si se borrara la sonda de `health.py`, este `/health` volvería `healthy` con
    `reason: None` y los tres asserts de abajo caen — es el testigo que fija que el código
    de producción hace algo. (Y por eso vive contra Postgres real: con el `_FakeSession` de
    `tests/unit/test_health_audit.py`, que no tiene `query()`, pasaría igual sin la sonda.)
    """
    client, factory = harness
    activos = usuarios_activos(factory)
    assert activos >= 1, (
        "el testigo necesita al menos un usuario activo sin riesgo; el bootstrap del admin "
        "de `admin_headers` lo crea sin `risk_level` y sin grupo")

    body = probe(client)

    assert body["audit"]["mode"] == "policy", "el default de D1, sin env seteada"
    assert body["status"] == "degraded", (
        f"{activos} usuario(s) activo(s) sin riesgo resuelto y el health dice "
        f"{body['status']!r}: la señal no está llegando")
    assert MODO_EN_EL_MOTIVO in body["reason"]
    assert conteo_en_el_motivo(activos) in body["reason"], (
        "el motivo tiene que decir A CUÁNTOS les corta: sin el número el operador no sabe "
        f"si es un usuario olvidado o el padrón entero — {body['reason']!r}")
    assert MOTIVO_TIER not in body["reason"], (
        "el motivo del tier (038 D3) trae la MISMA subcadena `SENTINEL_AUDIT_FAIL=policy`: si "
        "el que disparó fue ése, este test estaría verde sin haber ejercitado la sonda")


# ── 2. Testigo POSITIVO: poblado el riesgo, la señal se va ────────────────────────


def test_con_el_riesgo_poblado_en_los_usuarios_el_motivo_desaparece(harness):
    """La otra mitad del par: la señal no es un motivo permanente, se APAGA cuando el
    operador hace lo que el propio motivo le pide.

    Sin este testigo, una sonda rota que degradara SIEMPRE (por ejemplo, si el filtro de
    `risk_level` se cayera en un refactor) pasaría el testigo negativo sin despeinarse y el
    health quedaría con una degradación fantasma que nadie puede sacar.

    Se pueblan TODOS los activos, no «el admin»: con uno solo sin poblar el motivo sigue
    apareciendo y se leería como un bug de la sonda que en realidad es del padrón.

    Vacuidad: sin la sonda pasaría — por eso NO se entrega solo, es la contraparte del
    testigo negativo de arriba, que sí roja.
    """
    client, factory = harness
    poblados = poblar_todos(factory, RIESGO_BAJO)
    assert poblados >= 1, "sin nadie a quien poblar, este testigo no dice nada"

    sin_motivo(probe(client), f"los {poblados} activos con `risk_level` poblado")


def test_el_riesgo_del_GRUPO_tambien_apaga_la_senal(harness):
    """La sonda espeja la cascada completa (User > Group), no sólo el eslabón usuario.

    `PUT /api/v1/groups/{id}/compliance` —la vía que el propio motivo le recomienda al
    operador— puebla `groups.default_risk_level`, NO el riesgo del usuario. Si la sonda
    mirara sólo `users.risk_level`, el operador haría exactamente lo que el health le pide
    y el health seguiría degradado: el peor final posible para una señal de configuración.

    Vacuidad: sin la sonda pasaría; con la sonda sin el `outerjoin` (o con el OR de
    `default_risk_level` roto) ROJEA, que es el refactor que este testigo cuida.
    """
    client, factory = harness
    grupo = crear_grupo(factory, default_risk_level=RIESGO_BAJO)
    # Sólo se toca el grupo: el `risk_level` propio de cada usuario sigue en `None` (lo dejó
    # así `padron_controlado`), así que el riesgo lo tiene que aportar el segundo eslabón.
    asignados = asignar_grupo_a_todos(factory, grupo)
    assert asignados >= 1, "sin nadie en el grupo, este testigo no ejercita el outerjoin"

    sin_motivo(probe(client), "todos los activos en un grupo con `default_risk_level`")


def test_un_usuario_INACTIVO_sin_riesgo_no_cuenta(harness):
    """El padrón que importa es el que puede pedir: una cuenta dada de baja no genera
    tráfico, así que su riesgo sin poblar no es una amenaza de corte.

    Sin el filtro `is_active`, toda instalación con bajas acumuladas leería una degradación
    permanente por usuarios que ya no existen para el producto — ruido que entrena al
    operador a ignorar el `/health`.

    Vacuidad: sin la sonda pasaría; sin el `.filter(User.is_active.is_(True))` ROJEA.
    """
    client, factory = harness
    poblar_todos(factory, RIESGO_BAJO)      # el padrón ACTIVO queda sano…
    crear_usuario(factory, activo=False)    # …y el único sin riesgo está dado de baja

    sin_motivo(probe(client), "el único sin riesgo es un usuario inactivo")


def test_el_conteo_nombra_SOLO_a_los_que_no_resuelven(harness):
    """El número del motivo es un conteo FILTRADO, no un `COUNT(*)` del padrón.

    Es lo que vuelve accionable la señal: «1 de 40» manda a arreglar una fila, «40 de 40»
    manda a revisar el despliegue entero. Un conteo que incluya a los usuarios ya poblados
    haría que el operador poblara todo y siguiera viendo el mismo número.

    Vacuidad: sin la sonda no hay `reason` donde buscar el número ⇒ roja. Con la sonda sin
    el filtro de `risk_level`, el motivo diría `N+1` y también roja.
    """
    client, factory = harness
    poblar_todos(factory, RIESGO_BAJO)
    crear_usuario(factory, activo=True)     # exactamente UNO no resuelve

    body = probe(client)

    assert body["status"] == "degraded", "hay un activo sin riesgo: la señal tiene que estar"
    assert conteo_en_el_motivo(1) in body["reason"], (
        "con un solo usuario sin riesgo el motivo tiene que decir 1, no el total del "
        f"padrón — {body['reason']!r}")


# ── 3-4. Los overrides globales no consultan el padrón ────────────────────────────


def test_open_explicito_no_degrada_por_riesgo_sin_poblar(harness, monkeypatch):
    """En `open` la matriz D2 NI SE CONSULTA (`audit_exige_registro` resuelve el override
    antes de mirar el riesgo), así que un padrón sin poblar no cambia absolutamente nada:
    esa instalación eligió continuidad y ningún pedido se va a cortar por `None`.

    Degradar igual sería una alarma que el operador no puede apagar salvo poblando un dato
    que su modo no usa.

    Vacuidad: el primer assert pasaría sin la sonda — por eso el test lleva su BRAZO DE
    CONTROL adentro: con la MISMA base y el MISMO padrón, quitando el override, el motivo
    tiene que aparecer. Sin la sonda ese segundo tramo roja, y el test entero con él.
    """
    client, _ = harness
    from src.services import audit_service
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "open")

    body = probe(client)

    assert body["audit"]["mode"] == "open"
    sin_motivo(body, "`open` explícito con el padrón sin poblar")

    # Brazo de control: el padrón de esta base SÍ está sin poblar (si no, el tramo de
    # arriba estaría verde por no haber nada que reportar, no por el override).
    monkeypatch.delenv(audit_service.AUDIT_FAIL_ENV)
    control = probe(client)
    assert MODO_EN_EL_MOTIVO in (control["reason"] or ""), (
        "quitando el override el mismo padrón tiene que degradar: sin esto, el testigo de "
        "`open` no distingue «el override exime» de «no había riesgo sin poblar»")
    assert MOTIVO_TIER not in control["reason"]


def test_closed_explicito_con_la_auditoria_sana_no_mira_el_padron(harness, monkeypatch):
    """`closed` retorna ANTES de llegar a la sonda: con la auditoría escribible el motivo es
    `None` y punto.

    Y tiene que seguir siendo así: en `closed` la instalación ya exige registro para TODO el
    tráfico, con riesgo o sin él, así que el padrón sin poblar no anticipa ningún corte que
    la postura global no haya declarado ya. Sumarle la señal sería contarle dos veces la
    misma decisión.

    Vacuidad: igual que el de `open` — el brazo de control (quitar el override ⇒ el motivo
    aparece) es lo que hace que este test roje si la sonda no existe.
    """
    client, _ = harness
    from src.services import audit_service
    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "closed")

    body = probe(client)

    assert body["audit"]["mode"] == "closed"
    sin_motivo(body, "`closed` explícito con la auditoría escribible")

    monkeypatch.delenv(audit_service.AUDIT_FAIL_ENV)
    control = probe(client)
    assert MODO_EN_EL_MOTIVO in (control["reason"] or ""), (
        "el mismo padrón, sin el override, tiene que degradar")


# ── 5. El cache absorbe pero VENCE ────────────────────────────────────────────────


def test_el_cache_de_la_sonda_VENCE_y_el_padron_nuevo_viaja(harness):
    """Pasado el TTL se re-consulta Y el valor nuevo llega al body.

    Es el par del anti-martilleo, misma forma que
    `test_el_cache_VENCE_y_el_cambio_de_tier_viaja` en `tests/unit/test_health_audit.py`:
    aquel tramo prueba que el cache ABSORBE, éste que VENCE. Sin el segundo, un bug que
    congele `vencimiento` deja la degradación clavada para siempre —el operador puebla el
    riesgo de toda su gente y el health le sigue diciendo que no— y la suite sigue verde.

    Diferencia deliberada con el test unitario: allá el reloj se monkeypatchea
    (`health.time.monotonic`), acá el vencimiento se fuerza a mano. `health.time` ES el
    módulo `time` del proceso, y este test conduce un Postgres real, un pool de SQLAlchemy y
    la app entera: pisarle `monotonic()` a todo eso durante el request alcanzaría mucho más
    que el módulo bajo prueba. Lo que esa forma cuida —que el TTL no sea un valor absurdo
    que en la práctica no vence nunca— lo cubre `test_el_TTL_de_la_sonda_esta_en_un_rango_sano`.

    Vacuidad: sin la sonda no hay `_riesgo_cache` que tocar ⇒ el test ni siquiera importa;
    y con el cache, el tramo del medio roja si alguien lo saca (cada probe re-contaría) y
    el último roja si el vencimiento no se respeta.
    """
    client, factory = harness
    from src.api import health

    primero = probe(client)
    assert MODO_EN_EL_MOTIVO in (primero["reason"] or ""), (
        "el test arranca del padrón sin poblar: si acá ya no hay motivo, lo que sigue no "
        "mide el cache")

    poblar_todos(factory, RIESGO_BAJO)

    dentro_del_ttl = probe(client)
    assert MODO_EN_EL_MOTIVO in (dentro_del_ttl["reason"] or ""), (
        "dentro del TTL el conteo viejo se sirve del cache: si el padrón nuevo ya viajó, la "
        "sonda está pagando una query por probe y el endpoint es PÚBLICO")

    health._riesgo_cache["vencimiento"] = 0.0

    sin_motivo(probe(client), "cache vencido y el padrón ya poblado")


def test_el_TTL_de_la_sonda_esta_en_un_rango_sano():
    """Cota explícita sobre la constante, porque el test de arriba fuerza el vencimiento a
    mano y por eso mismo no cazaría un valor absurdo.

    Un TTL enorme es un cache que no vence nunca (la promesa de «drift acotado» deja de ser
    cierta y la señal no se apaga aunque el operador arregle el padrón); uno de 0 es no
    cachear, y esta sonda cuelga de una superficie pública que se martillea justo cuando
    algo anda mal.

    Vacuidad: sin la sonda la constante no existe y el test roja al importarla.
    """
    from src.api import health

    ttl = health._RIESGO_CACHE_TTL_SEGUNDOS

    assert 0 < ttl <= 300, (
        f"TTL={ttl}: fuera de rango, o el cache no vence nunca o no absorbe nada")


# ── 6. El costo: la query del padrón no se paga fuera de `policy` ─────────────────


def test_open_no_paga_la_query_del_padron(harness, monkeypatch):
    """Análogo de `test_fuera_de_closed_no_paga_el_probe_de_escribibilidad`: en `open` la
    sonda no se INVOCA, no es que se invoque y su resultado se descarte.

    `/health` es público y sin autenticar en su tier básico: cada consulta que se le agregue
    al camino la puede disparar cualquiera, a la tasa que quiera. Que la señal de la 038 no
    le sume una query al modo que ni siquiera la usa es la condición con la que entró.

    Vacuidad: el `llamadas == []` pasaría sin la sonda (el nombre no existiría… y de hecho
    el `monkeypatch.setattr` fallaría, que también es rojo). El testigo POSITIVO del MISMO
    espía —en `policy` se invoca exactamente una vez— es lo que prueba que el espía está
    cableado al nombre que el endpoint ejecuta de verdad, y no a un homónimo muerto.
    """
    client, _ = harness
    from src.api import health
    from src.services import audit_service

    llamadas = []
    real = health._usuarios_sin_riesgo_cacheado

    def _espia(db):
        # Envuelve al REAL (no lo reemplaza): lo que se afirma es cuándo se lo llama, no
        # que se lo haya podido sustituir por un doble que devuelve cualquier cosa.
        llamadas.append(db)
        return real(db)

    # Se parchea el nombre en `health`, que es el módulo que lo ejecuta: parchear otro
    # origen dejaría el espía sin usar y el test pasaría por la razón equivocada.
    monkeypatch.setattr(health, "_usuarios_sin_riesgo_cacheado", _espia)

    monkeypatch.setenv(audit_service.AUDIT_FAIL_ENV, "open")
    body = probe(client)

    assert body["status"] == "healthy"
    assert llamadas == [], (
        "en `open` la matriz D2 no se consulta: contar el padrón sería pagar una query por "
        f"probe sin ninguna decisión que tomar (se contó {len(llamadas)}x)")

    # Testigo positivo del mismo espía: sin esto, un espía mal cableado daría el mismo
    # `llamadas == []` de arriba y el test sería una tautología.
    monkeypatch.delenv(audit_service.AUDIT_FAIL_ENV)
    probe(client)
    assert len(llamadas) == 1, (
        "en `policy` la sonda SÍ se consulta: si acá tampoco se invocó, el espía no está "
        "puesto sobre el nombre que ejecuta el endpoint y el assert de arriba no probó nada")
