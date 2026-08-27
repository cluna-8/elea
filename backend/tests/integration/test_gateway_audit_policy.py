"""`BASA_AUDIT_FAIL=policy` en el plano `/gw` (spec 038, Phase 2, T007).

Espejo de `test_chat_audit_policy.py` para el segundo plano que decide por riesgo: acá el
riesgo NO llega resuelto (a diferencia de chat, que lo hereda de `user`/`api_key_obj`) —
`gateway.py` lo tiene que PRODUCIR él mismo, en `_resolve_attribution`, con la cascada
`riesgo_aplicado(key, key.user, key.group)` (Key > User > Group). La matriz que decide
servir/cortar (`audit_service.audit_fail_decision`) es la MISMA de siempre: `minimal`/
`limited` sirve sin fila; `high_risk_annex1`/`high_risk_annex3`/`None`/desconocido corta.

Lo que se fija acá, específico de `/gw`:

- la cascada del riesgo se PRODUCE en este plano (T007) y llega hasta el eslabón grupo;
- **`X-Basa-Key` es OPCIONAL en `/gw`** (la credencial real es el OAuth de suscripción):
  sin el header no hay key, ni usuario, ni grupo, así que `applied_risk_level` resuelve
  `None` y la matriz D2 corta el tráfico anónimo bajo `policy` — DISEÑO SELLADO (★A,
  27-ago), no un bug que este archivo descubrió;
- FR-002 + el punto de costo (D4): tráfico de bajo riesgo no paga el pre-check de
  escribibilidad (`audit_writable`), medido con un espía que CUENTA llamadas, con su brazo
  positivo (riesgo alto SÍ lo paga) al lado — para que el espía no pase por dar siempre cero;
- el corte de `policy` es honesto y distinto del de `closed`: el mensaje del error nombra
  `(audit_fail=policy)`, no `(audit_fail=closed)`;
- SC-002: `open`/`closed` puestos EXPLÍCITOS en la env siguen siendo overrides globales que
  ignoran la matriz por completo, en los dos sentidos;
- FR-004: el claim de `policy` no es "riesgo bajo se sirve" a secas, es "riesgo bajo se
  sirve SIN FILA y la pérdida queda contada" — con el pre-check sano (D4 lo salta) pero el
  ESCRITOR roto, la fila no se graba y `basa:audit:lost` sí se incrementa. Es la contraparte
  del hallazgo medido de más abajo: el pre-check caído no pierde nada (D4 ni lo consulta);
  el escritor caído sí, y de eso no puede quedar en silencio.

Mismo harness y misma convención de nombres que `test_gateway_block_audit.py` — los dobles
(`_HttpxEspia`, `_SesionSinBase`) y las fixtures de sesión/proveedor/pérdidas se REUSAN de
ahí (copiados, no importados: mismo criterio que ya usa `test_chat_audit_policy.py` frente a
`test_chat_block_audit.py`, para no acoplar dos archivos de test entre sí).

**Nota medida sobre `_SesionSinBase` y la escritura final** (para quien toque este archivo
después): esa sesión sólo rompe el `execute()` que se le llama EXPLÍCITAMENTE — es lo que ve
`audit_writable` (el pre-check, `SELECT 1`). El escritor real del camino feliz
(`AuditService.log_transaction`) usa `db.add(...)` + `db.commit()`, que en SQLAlchemy 2.0 NO
pasan por ese `execute()` (el flush de un `commit()` corre sobre la `Connection` de Core, no
sobre `Session.execute()`) — confirmado con un experimento standalone antes de escribir este
archivo. Consecuencia: en los caminos donde el pre-check se salta por D4 (riesgo bajo, u
`open` explícito) la fila del camino feliz se graba de verdad contra el Postgres real del
harness, y no hay pérdida que contar — a diferencia de lo que un lector apurado del docstring
de `_SesionSinBase` podría asumir. Los tests de esos caminos afirman eso, MEDIDO.
"""
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client  # noqa: E402

require_postgres()

from src.services.audit_service import (  # noqa: E402
    AUDIT_CLOSED_DETAIL,
    AUDIT_FAIL_ENV,
    AUDIT_POLICY_DETAIL,
)

DB = "basa_test_gateway_audit_policy"
GW = "/api/v1/gw/v1/messages"

# Espejo EXACTO de `CUERPO_LIMPIO` en `test_gateway_block_audit.py`: no dispara ninguna capa
# de bloqueo (ni AI-Act, ni secreto, ni PII), así que lo único que decide servir/cortar es la
# política de auditoría por riesgo que este archivo fija.
CUERPO_LIMPIO = {"model": "claude-3-5-sonnet-20241022",
                 "messages": [{"role": "user", "content": "resumime esto en una línea"}]}


# ── Dobles (copiados de `test_gateway_block_audit.py`, mismo nombre y mismo contrato) ──


class _RespuestaFalsa:
    status_code = 200
    headers = {"content-type": "application/json"}
    content = (b'{"content": [{"type": "text", "text": "ok"}], '
              b'"usage": {"input_tokens": 3, "output_tokens": 2}}')

    def json(self):
        return json.loads(self.content)


class _ClienteFalso:
    def __init__(self, registro):
        self._registro = registro

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url, **_kwargs):
        self._registro.append(url)
        return _RespuestaFalsa()


class _HttpxEspia:
    """Doble del módulo `httpx` que usa el gateway: cuenta a quién se llamó — el
    instrumento de "cero POST al proveedor" en cada corte por auditoría."""

    def __init__(self):
        self.llamadas = []

    def AsyncClient(self, *_args, **_kwargs):  # noqa: N802 — espeja el nombre real
        return _ClienteFalso(self.llamadas)


class _SesionSinBase:
    """Sesión cuyo `execute` revienta: es lo que ve `audit_writable` con la base caída.

    `query()` sigue funcionando a propósito (delega al `_real` vía `__getattr__`, así que la
    atribución del gateway — `db.query(APIKey)...` — no participa del escenario) y el
    escritor real (`db.add`/`db.commit`) TAMBIÉN sigue funcionando por la misma vía, ver la
    nota del docstring del módulo: sólo el `execute()` que un caller invoca DIRECTO sobre
    este objeto (como hace `audit_writable`) revienta."""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)

    def execute(self, *_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, Exception("could not connect to server"))

    def __getattr__(self, nombre):
        return getattr(self._real, nombre)


class _SesionQueFallaAlCommitear:
    """Sesión real envuelta que falla los primeros N `commit()` y después delega todo —
    copiada de `test_gateway_block_audit.py` (`con_fallos`). A diferencia de `_SesionSinBase`
    (que rompe el pre-check y nada más, ver la nota del docstring del módulo), ÉSTA es la que
    rompe el ESCRITOR: `add`/`rollback`/el `commit` bueno son los de SQLAlchemy real, así que
    el reintento del escritor se ejerce contra una sesión de verdad."""

    def __init__(self, real, estado):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_estado", estado)

    def commit(self):
        if self._estado["restantes"] > 0:
            self._estado["restantes"] -= 1
            self._estado["fallos"] += 1
            raise OperationalError("COMMIT", {},
                                   Exception("server closed the connection unexpectedly"))
        return self._real.commit()

    def __getattr__(self, nombre):
        return getattr(self._real, nombre)


def con_fallos(factory, veces):
    """Factory que devuelve sesiones que fallan `veces` commits — mismo helper que
    `test_gateway_block_audit.py`. Con `veces=99` agota el presupuesto de reintentos de
    `AuditService.log_transaction` (D5: 1 intento + 2 reintentos = 3), así que el escritor
    SIEMPRE pierde la fila."""
    estado = {"restantes": veces, "fallos": 0}
    return (lambda: _SesionQueFallaAlCommitear(factory(), estado)), estado


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def sesion_del_gateway(harness, monkeypatch):
    """Base de auditoría CAÍDA por DEFECTO en todo este archivo (a diferencia de
    `test_gateway_block_audit.py`, donde `_SesionSinBase` es el override puntual de algunos
    tests): acá TODOS los casos de la matriz D2 parten de la base caída — es la premisa que
    el brief fija para 1-7, y lo que cambia entre tests es el riesgo resuelto y el modo, no
    el estado de la base."""
    _, factory = harness
    from src.api import gateway
    monkeypatch.setattr(gateway, "SessionLocal", lambda: _SesionSinBase(factory()))
    return factory


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    """El backoff del escritor (0,2 s + 0,5 s) es presupuesto de producción, no de suite."""
    from src.services import audit_service
    monkeypatch.setattr(audit_service, "_wait", lambda _s: None)


@pytest.fixture(autouse=True)
def proveedor(monkeypatch):
    from src.api import gateway
    espia = _HttpxEspia()
    monkeypatch.setattr(gateway, "httpx", espia)
    return espia


@pytest.fixture(autouse=True)
def modo_policy_por_defecto(monkeypatch):
    """Cada test parte de la env AUSENTE — el modo efectivo desde D1 es `policy`, el
    default de la spec 038. Los tests de override (`closed`/`open` explícitos) la pisan
    ellos mismos con su propio `monkeypatch.setenv`, DESPUÉS de este `delenv`: mismo
    `monkeypatch` de la fixture, así que el último `setenv` gana durante el test."""
    monkeypatch.delenv(AUDIT_FAIL_ENV, raising=False)


@pytest.fixture
def perdidas(monkeypatch):
    """Espía del contador de pérdidas en sus dos puntos de llamada (el escritor y el
    envoltorio del gateway) — mismo patrón que `test_gateway_block_audit.py`."""
    from src.api import gateway
    from src.services import audit_service
    registro = []
    monkeypatch.setattr(audit_service, "record_audit_loss",
                        lambda reason="": registro.append(reason))
    monkeypatch.setattr(gateway, "record_audit_loss",
                        lambda reason="": registro.append(reason))
    return registro


# ── Helpers ───────────────────────────────────────────────────────────────────────


def pedir(client, headers=None, cuerpo=None):
    return client.post(GW, json=cuerpo or CUERPO_LIMPIO, headers=headers or {})


def mensaje_de(respuesta):
    """El `/gw` responde con la FORMA de error de Anthropic (`_anthropic_error`):
    `{"type": "error", "error": {"type": ..., "message": "..."}}` — a diferencia del plano
    chat, que usa `detail` de FastAPI. El texto vive en `error.message`."""
    return respuesta.json()["error"]["message"]


def crear_identidad(factory, *, risk_usuario=None, risk_grupo=None, con_grupo=False,
                    sufijo=""):
    """Crea (Group opcional) + User + APIKey en la DB del harness y devuelve el header
    `X-Basa-Key` que la resuelve — mismo patrón de alta que `test_gateway_nlp_paridad.py`
    (fixture `key_atribuible`, ~línea 233): `upstream_mode="byok"` porque una fila
    `subscription-passthrough` exige `oauth_credential_ref` (CHECK
    `ck_api_keys_subscription_oauth`) y acá no hay credencial que custodiar. Eso NO manda el
    pedido por la ruta byok del motor: `X-Basa-Key` está excluido del scan de
    `_detect_mode_and_key` (`x-basa-*` no cuenta como credencial auto-detectada), así que el
    tráfico sigue yendo por passthrough — la Connection sólo sirve para ATRIBUIR.

    Escribe la fila DIRECTO — nunca un `UPDATE` sobre una fila existente: bajo RLS un
    `UPDATE` corrido desde una `factory()` sin el tenant de la app "pasa" sin tocar ninguna
    fila (#334, medido en otro harness). Crear la fila entera con el valor puesto ya es la
    vía que funciona.

    `key.group` (la cascada de `riesgo_aplicado` lee `key.group`, NO `key.user.group`) se
    fija al MISMO grupo que el usuario cuando `con_grupo=True`, para que la Connection sea
    consistente con el cliente que la usa."""
    from src.models.budget import APIKey
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.models.user import Group, User
    from src.services.key_material import hash_key

    db = factory()
    try:
        group_id = None
        if con_grupo:
            grupo = Group(tenant_id=DEFAULT_TENANT_ID, name=f"grupo-riesgo-{sufijo}",
                          default_risk_level=risk_grupo)
            db.add(grupo)
            db.flush()
            group_id = grupo.id

        usuario = User(tenant_id=DEFAULT_TENANT_ID, username=f"riesgo-{sufijo}",
                      email=f"riesgo-{sufijo}@basa.com.ar", password_hash="x",
                      role="client", client_type="base_url",
                      risk_level=risk_usuario, group_id=group_id, is_active=True)
        db.add(usuario)
        db.flush()

        clave = f"sk-basa-riesgo-{sufijo}"
        db.query(APIKey).filter(APIKey.key_hash == hash_key(clave)).delete()
        db.add(APIKey(tenant_id=DEFAULT_TENANT_ID, key_hash=hash_key(clave),
                      key_preview=f"sk-...{sufijo}", name=f"key-riesgo-{sufijo}",
                      is_active=True, tool_type="claude-code", upstream_mode="byok",
                      user_id=usuario.id, group_id=group_id))
        db.commit()
        return clave
    finally:
        db.close()


def contar_audit_logs(factory):
    """Cantidad de filas en `audit_logs` — el módulo comparte base entre tests, así que lo
    que se mide es el DELTA (antes/después de un pedido), nunca un valor absoluto."""
    from src.models.audit import AuditLog
    db = factory()
    try:
        return db.query(AuditLog).count()
    finally:
        db.close()


def espiar_audit_writable(monkeypatch):
    """Cuenta cuántas veces `_audit_precheck_ok` llega a preguntarle a `audit_writable` —
    el instrumento del punto de costo D4. Devuelve `False` (base "no escribible"): consistente
    con la premisa de auditoría caída del archivo, y de paso da el 503 que el brazo de riesgo
    alto necesita para completar su propia aserción."""
    from src.api import gateway
    llamadas = []

    def _contador(db):
        llamadas.append(db)
        return False

    monkeypatch.setattr(gateway, "audit_writable", _contador)
    return llamadas


# Nota sobre los literales: se IMPORTAN de `audit_service` (arriba) y no se retipean acá —
# no hay copia local que verificar contra el import, así que no hace falta un test aparte
# para eso (brief: "si los pegás, verificá con un assert de igualdad contra el import").


# ── 1) Riesgo bajo: D4 salta el pre-check y el pedido se sirve ────────────────────


def test_riesgo_minimo_sirve_sin_pagar_el_pre_check_pese_a_la_base_caida(
        harness, proveedor, perdidas):
    """`policy` (default, env ausente) + `X-Basa-Key` de un usuario `risk_level=minimal` +
    base de auditoría caída ⇒ 200, y el proveedor se llama UNA vez: D4 corta el pre-check
    ANTES de tocar la base, así que la caída no afecta a este pedido en absoluto (mismo
    invariante de costo que `open` fija en `test_gateway_block_audit.py`, ahora bajo el modo
    que HOY es el default de instalación)."""
    client, factory = harness
    clave = crear_identidad(factory, risk_usuario="minimal", sufijo="min")

    respuesta = pedir(client, headers={"X-Basa-Key": clave})

    assert respuesta.status_code == 200, respuesta.text
    assert len(proveedor.llamadas) == 1, "riesgo bajo: el pedido se sirve de verdad"
    # MEDIDO (ver nota del docstring del módulo): con el pre-check salteado por D4, la fila
    # del camino feliz se graba contra el Postgres real del harness — `_SesionSinBase` no
    # rompe `db.add`/`db.commit`, sólo el `execute()` explícito de `audit_writable`. No hay
    # pérdida que contar en este camino.
    assert perdidas == [], "con el escritor sano la fila se graba: nada que perder acá"


# ── 1b) FR-004: riesgo bajo + ESCRITOR caído ⇒ se sirve, sin fila, pérdida contada ─
#
# El test de arriba prueba que el pre-check no se paga (D4). Éste prueba la otra mitad del
# claim de producto de `policy`: "riesgo bajo se sirve sin fila" no puede significar "y si
# la escritura falla, nadie se entera" (FR-004). Acá se rompe el ESCRITOR
# (`_SesionQueFallaAlCommitear`, no `_SesionSinBase`) — la única forma de que la fila
# realmente no se grabe, medida en el test de arriba.


def test_riesgo_minimo_con_el_escritor_caido_sirve_sin_fila_y_cuenta_la_perdida(
        harness, monkeypatch, proveedor, perdidas):
    """`policy` + `risk_level=minimal` + escritor (no pre-check) caído ⇒ 200, CERO filas
    nuevas en `audit_logs`, y la pérdida contada UNA vez — ni una fila fantasma ni un
    silencio: "servido sin fila" es un hecho que el health tiene que poder mostrar."""
    client, factory = harness
    clave = crear_identidad(factory, risk_usuario="minimal", sufijo="min-escritor-caido")

    from src.api import gateway
    fallona, estado = con_fallos(factory, 99)
    monkeypatch.setattr(gateway, "SessionLocal", fallona)

    antes = contar_audit_logs(factory)
    respuesta = pedir(client, headers={"X-Basa-Key": clave})

    assert respuesta.status_code == 200, respuesta.text
    assert len(proveedor.llamadas) == 1, "riesgo bajo: se sirve de verdad pese al escritor caído"
    assert estado["fallos"] == 3, "presupuesto D5 agotado: 1 intento + 2 reintentos"
    assert contar_audit_logs(factory) == antes, "el escritor caído no deja fila nueva"
    assert len(perdidas) == 1, (
        "la pérdida se cuenta UNA vez, no una por capa que la vea pasar")


# ── 2) Riesgo alto + base caída: 503 honesto de `policy`, no de `closed` ──────────


def test_riesgo_alto_y_base_caida_corta_con_503_de_policy(harness, proveedor):
    """`policy` + `risk_level=high_risk_annex3` + base de auditoría caída ⇒ 503 ANTES del
    proveedor (FR-005), con el copy de `policy` — no el de `closed` — en el mensaje (D2):
    confundirlos manda al operador a buscar una env que nunca seteó."""
    client, factory = harness
    clave = crear_identidad(factory, risk_usuario="high_risk_annex3", sufijo="alto")

    respuesta = pedir(client, headers={"X-Basa-Key": clave})

    assert respuesta.status_code == 503, respuesta.text
    mensaje = mensaje_de(respuesta)
    assert AUDIT_POLICY_DETAIL in mensaje
    assert "(audit_fail=closed)" not in mensaje
    assert proveedor.llamadas == [], "riesgo alto + base caída: cero POST al proveedor"


# ── 3) Sin X-Basa-Key: tráfico anónimo, diseño sellado (★A, 27-ago) ───────────────


def test_sin_x_basa_key_corta_con_503_de_policy_disenio_sellado_no_regresion(
        harness, proveedor):
    """Tráfico anónimo (sin `X-Basa-Key`) + `policy` + base caída ⇒ 503 con el copy de
    `policy`.

    **DISEÑO SELLADO (★A, 27-ago-2026), no una regresión.** `X-Basa-Key` es OPCIONAL en
    `/gw` — la credencial real de esta ruta es el OAuth de suscripción reenviado verbatim
    ([D-014]) — así que un pedido sin el header no tiene key, ni usuario, ni grupo de dónde
    sacar un riesgo: `applied_risk_level` resuelve `None`, y la matriz D2 trata `None` igual
    que un riesgo alto (fail-closed hacia lo reversible: un pedido que no demostró ser de
    bajo riesgo no se sirve sin fila). Si este test rojea algún día porque alguien decidió
    que el tráfico anónimo debería servirse sin registro, es un cambio de decisión de
    producto que hay que discutir explícitamente — no un bug que este test encontró solo."""
    client, _ = harness

    respuesta = pedir(client)  # sin X-Basa-Key

    assert respuesta.status_code == 503, respuesta.text
    mensaje = mensaje_de(respuesta)
    assert AUDIT_POLICY_DETAIL in mensaje
    assert proveedor.llamadas == []


# ── 4) La cascada llega hasta el eslabón GRUPO ─────────────────────────────────────


def test_riesgo_desde_el_grupo_llega_hasta_gw_y_sirve(harness, proveedor):
    """Usuario SIN `risk_level` propio + `Group.default_risk_level="limited"` (y la
    Connection atada a ESE grupo) ⇒ igual sirve (200). Fija que la cascada Key > User >
    Group de `riesgo_aplicado()` no se queda a mitad de camino en este plano: `/gw` la tiene
    que PRODUCIR (a diferencia de chat, que la recibe resuelta), y esto prueba que el
    eslabón grupo también se produce, no sólo el de usuario."""
    client, factory = harness
    clave = crear_identidad(factory, risk_usuario=None, risk_grupo="limited",
                            con_grupo=True, sufijo="grupo")

    respuesta = pedir(client, headers={"X-Basa-Key": clave})

    assert respuesta.status_code == 200, respuesta.text
    assert len(proveedor.llamadas) == 1, "riesgo de grupo: se sirve de verdad"


# ── 5) D4: el costo del pre-check depende del RIESGO, no del modo ─────────────────


def test_d4_riesgo_minimo_no_paga_el_pre_check_de_escribibilidad(harness, monkeypatch):
    """Punto de costo D4: con `applied_risk_level=minimal` el pre-check ni se consulta —
    `audit_writable` queda en CERO invocaciones. Instrumentado con un espía que reemplaza
    la función (no un mock que "sabe" la respuesta): lo que se mide es si LLAMÓ, y el brazo
    hermano de abajo prueba que el espía sabe contar."""
    client, factory = harness
    clave = crear_identidad(factory, risk_usuario="minimal", sufijo="d4-min")
    llamadas = espiar_audit_writable(monkeypatch)

    respuesta = pedir(client, headers={"X-Basa-Key": clave})

    assert respuesta.status_code == 200, respuesta.text
    assert llamadas == [], "riesgo bajo: el pre-check de policy no debe correr (D4)"


def test_d4_riesgo_alto_si_paga_el_pre_check_de_escribibilidad(harness, monkeypatch):
    """Brazo POSITIVO del mismo espía (hermano del test de arriba): con riesgo alto el
    contador SÍ tiene que ver al menos una llamada. Sin este brazo, un espía roto que
    siempre devuelve `[]` pasaría el test de riesgo bajo por la razón equivocada."""
    client, factory = harness
    clave = crear_identidad(factory, risk_usuario="high_risk_annex3", sufijo="d4-alto")
    llamadas = espiar_audit_writable(monkeypatch)

    respuesta = pedir(client, headers={"X-Basa-Key": clave})

    assert respuesta.status_code == 503, respuesta.text
    assert len(llamadas) >= 1, "riesgo alto: el pre-check SÍ tiene que consultar audit_writable"


# ── 6) SC-002: `closed` explícito ignora la matriz (lado restrictivo) ─────────────


def test_closed_explicito_corta_igual_con_riesgo_minimo(harness, monkeypatch, proveedor):
    """`BASA_AUDIT_FAIL=closed` EXPLÍCITO + `risk_level=minimal` ⇒ igual corta (503) con el
    texto de `closed`, no el de `policy` — el override global ignora la matriz D2 por
    completo, incluso para el riesgo que `policy` serviría sin pestañear (SC-002)."""
    client, factory = harness
    monkeypatch.setenv(AUDIT_FAIL_ENV, "closed")
    clave = crear_identidad(factory, risk_usuario="minimal", sufijo="closed-min")

    respuesta = pedir(client, headers={"X-Basa-Key": clave})

    assert respuesta.status_code == 503, respuesta.text
    mensaje = mensaje_de(respuesta)
    assert AUDIT_CLOSED_DETAIL in mensaje, "closed explícito conserva SU texto, no el de policy"
    assert "(audit_fail=policy)" not in mensaje
    assert proveedor.llamadas == []


# ── 7) SC-002: `open` explícito ignora la matriz (lado permisivo) ─────────────────


def test_open_explicito_sirve_igual_con_riesgo_alto(harness, monkeypatch, proveedor,
                                                     perdidas):
    """`BASA_AUDIT_FAIL=open` EXPLÍCITO + `risk_level=high_risk_annex3` ⇒ se SIRVE (200) —
    el override permisivo también ignora la matriz D2 por completo, del otro lado
    (SC-002): ni el riesgo alto paga el pre-check bajo `open`."""
    client, factory = harness
    monkeypatch.setenv(AUDIT_FAIL_ENV, "open")
    clave = crear_identidad(factory, risk_usuario="high_risk_annex3", sufijo="open-alto")

    respuesta = pedir(client, headers={"X-Basa-Key": clave})

    assert respuesta.status_code == 200, respuesta.text
    assert len(proveedor.llamadas) == 1, "se sirvió de verdad: el proveedor se llamó una vez"
    # Mismo hallazgo MEDIDO que en el test #1: con el pre-check salteado (acá por el
    # override, no por D4) la fila se graba de verdad contra la base sana del harness.
    assert perdidas == [], "con el escritor sano la fila se graba: nada que perder acá"


# ── 8) Los OTROS call-sites de T007: bloqueo y literal reservado, bajo `policy` ────
#
# Hallazgo del review independiente (post-T007, mismo diff): `gw_messages` tiene TRES
# puntos que pasaron de mirar `audit_fail_mode() == AUDIT_FAIL_CLOSED` a mirar la
# `exige_registro` ya resuelta — el pre-check del camino feliz (casos 1-7 de arriba), el
# rechazo de BLOQUEO (US1 AC4) y el rechazo del LITERAL RESERVADO de la cadena de
# licencias. Los tres cambiaron con el mismo diff de una línea cada uno, y son TRES
# call-sites que alguien puede volver a leer `audit_fail_mode()` directo por separado — el
# testigo tiene que ser por call-site, no por el hecho de que "ya cubrí el cambio una vez".
#
# Estos tres usan el ESCRITOR caído (`con_fallos`, el que rompe `commit()`) — a diferencia
# de 1-7, acá el pre-check NI ENTRA: el camino de bloqueo/literal escribe la fila directo,
# nunca consulta `audit_writable`.

SECRETO = "sk-ABCdefghij0123456789"
# Dispara `SECRET_PATTERNS["OpenAI API Key"]` — regex pura, no depende del NLP (mismo
# cuerpo que `test_gateway_block_audit.py::CUERPO_BLOQUEADO`).
CUERPO_BLOQUEADO = {"model": "claude-3-5-sonnet-20241022",
                    "messages": [{"role": "user", "content": f"la clave es {SECRETO}"}]}
CUERPO_LICENCIA = {"model": "license",
                   "messages": [{"role": "user", "content": "resumime esto en una línea"}]}


def test_bloqueo_con_riesgo_alto_y_escritor_caido_corta_con_503_de_policy(
        harness, monkeypatch):
    """US1 AC4 bajo `policy` (no sólo bajo `closed`, que es lo único que
    `test_gateway_block_audit.py` cubre): riesgo `high_risk_annex3` EXIGE registro: con el
    escritor caído la fila de bloqueo no se graba ⇒ 503 con el copy de `policy` — «se
    bloqueó y no quedó nada» no puede salir con la cara del rechazo normal (400)."""
    client, factory = harness
    clave = crear_identidad(factory, risk_usuario="high_risk_annex3", sufijo="bloq-alto")

    from src.api import gateway
    fallona, _estado = con_fallos(factory, 99)
    monkeypatch.setattr(gateway, "SessionLocal", fallona)

    respuesta = pedir(client, headers={"X-Basa-Key": clave}, cuerpo=CUERPO_BLOQUEADO)

    assert respuesta.status_code == 503, respuesta.text
    mensaje = mensaje_de(respuesta)
    assert AUDIT_POLICY_DETAIL in mensaje
    assert "material secreto" not in mensaje, "no puede salir con la cara del bloqueo normal"


def test_bloqueo_con_riesgo_bajo_y_escritor_caido_responde_el_bloqueo_y_cuenta_la_perdida(
        harness, monkeypatch, perdidas):
    """Brazo NEGATIVO del test de arriba: riesgo `minimal` no exige registro, así que aunque
    el escritor esté IGUAL de caído el bloqueo sale con su 400 de siempre — y la pérdida
    queda contada igual (FR-004). Sin este brazo, un fix que cortara con 503 ante CUALQUIER
    fallo de escritura del camino de bloqueo —sin mirar el riesgo— pasaría el test de arriba
    igual, por la razón equivocada."""
    client, factory = harness
    clave = crear_identidad(factory, risk_usuario="minimal", sufijo="bloq-bajo")

    from src.api import gateway
    fallona, _estado = con_fallos(factory, 99)
    monkeypatch.setattr(gateway, "SessionLocal", fallona)

    respuesta = pedir(client, headers={"X-Basa-Key": clave}, cuerpo=CUERPO_BLOQUEADO)

    assert respuesta.status_code == 400, respuesta.text
    assert "material secreto" in mensaje_de(respuesta)
    assert len(perdidas) == 1, (
        "el bloqueo ocurrió de verdad; la fila que no se pudo grabar se cuenta igual")


def test_literal_reservado_con_riesgo_alto_y_escritor_caido_corta_con_503_de_policy(
        harness, monkeypatch):
    """Mismo criterio que el bloqueo, para el OTRO rechazo que escribe fila propia: el 422
    del literal reservado de la cadena de licencias (`model: "license"`). Riesgo alto +
    escritor caído ⇒ 503 de `policy`, no el 422 de siempre — este rechazo tampoco puede
    salir con cara de rechazo normal cuando no quedó nada registrado."""
    client, factory = harness
    clave = crear_identidad(factory, risk_usuario="high_risk_annex3", sufijo="lic-alto")

    from src.api import gateway
    fallona, _estado = con_fallos(factory, 99)
    monkeypatch.setattr(gateway, "SessionLocal", fallona)

    respuesta = pedir(client, headers={"X-Basa-Key": clave}, cuerpo=CUERPO_LICENCIA)

    assert respuesta.status_code == 503, respuesta.text
    mensaje = mensaje_de(respuesta)
    assert AUDIT_POLICY_DETAIL in mensaje
    assert "literal reservado" not in mensaje, "no puede salir con la cara del 422 normal"


# ── 9) El CARVE-OUT byok: la excepción a la matriz, con su propio testigo ─────────
#
# `gw_messages` tiene un CUARTO call-site del pre-check —la rama byok, `_exige_registro_byok()`—
# y es el único que NO consulta la matriz por riesgo: corta sólo bajo el override global
# `closed`. No es un olvido, es la restricción de T007: la fila del tráfico byok la escribe el
# MOTOR (que la pide por `/internal/audit/probe` con contexto de credencial, T008), y el riesgo
# que ESTE plano puede ver para una virtual key sin usuario es `None` — que la matriz D2 trata
# como alto. Decidir acá cortaría por un dato que no gobierna esa fila.
#
# **Por qué hace falta un test y no alcanza con que la excepción sea greppable.** El modo de
# falla no es que alguien BORRE el carve-out: es que alguien lo UNIFORMICE —«¿por qué esta rama
# no usa `audit_exige_registro` como las otras tres?»— antes de que T008 le dé el contexto de
# credencial. Con 2667 tests corriendo, esa uniformización pasaba entera: el comportamiento
# `closed` del byok sí está clavado (`test_gateway_block_audit.py::test_closed_con_auditoria_
# caida_no_reenvia_al_motor_en_byok`), pero el de `policy` no lo miraba nadie. Es la regla que
# sellamos el 27-ago —*un override sin mutación que lo rompa es un override sin testigo*—
# aplicada a la EXCEPCIÓN en vez de al override.
#
# Mutación que tiene que matar el primero de estos dos tests y ningún otro:
#   `_exige_registro_byok()` → `return audit_exige_registro(None)`   (byok entra a la matriz)

# Forma válida de virtual key (`_BASA_KEY_RE`) que NO existe en la base a propósito: es
# exactamente la credencial que este plano no puede atribuir, o sea el caso donde el riesgo
# resolvería `None` si alguien enrutara byok por la matriz. Misma clave en los DOS tests de
# abajo — el par sólo prueba algo si la única variable es la cabecera de ruteo.
CLAVE_BYOK = "sk-basa-inexistente-pero-con-forma"


def test_byok_bajo_policy_con_la_base_caida_lo_sirve_este_plano_no_lo_corta(
        harness, proveedor):
    """El carve-out, medido: `policy` + base de auditoría caída + ruta byok ⇒ **no hay 503 de
    la pasarela**, el pedido sale al motor.

    Dos asserts y no uno: el 200 solo no distingue «el carve-out funcionó» de «se sirvió por
    el plano equivocado». El segundo nombra A QUIÉN se contactó — el motor (`_LITELLM_UPSTREAM`),
    no Anthropic — porque un 200 del passthrough sería un bug mucho peor que el que este test
    busca, y desde afuera se ve igual. La URL se compara contra el símbolo importado, no contra
    un literal retipeado."""
    from src.api.gateway import _LITELLM_UPSTREAM
    client, _ = harness

    respuesta = pedir(client, headers={"X-Basa-Upstream": "byok",
                                       "X-Basa-Key": CLAVE_BYOK})

    assert respuesta.status_code == 200, respuesta.text
    assert len(proveedor.llamadas) == 1, "el carve-out sirve de verdad: el motor fue contactado"
    assert proveedor.llamadas[0].startswith(_LITELLM_UPSTREAM), (
        f"el pedido byok tiene que ir al MOTOR, fue a {proveedor.llamadas[0]}")


def test_el_mismo_pedido_sin_la_cabecera_byok_si_lo_corta_la_matriz(harness, proveedor):
    """Brazo de control del de arriba: MISMA clave inexistente, MISMO cuerpo, MISMA base
    caída — sin `X-Basa-Upstream: byok` el pedido cae al passthrough, `_resolve_attribution`
    no puede atribuirlo, el riesgo resuelve `None` y la matriz D2 lo corta con el 503 de
    `policy`.

    Sin este brazo, el test de arriba podría estar verde porque el 503 no se produce en NINGÚN
    caso de este escenario (una matriz rota, un `SessionLocal` que no llegó a patchearse) y
    diría «el carve-out funciona» midiendo un mecanismo apagado. La única variable entre los
    dos tests es la cabecera de ruteo, que es exactamente el eje que el carve-out gobierna."""
    client, _ = harness

    respuesta = pedir(client, headers={"X-Basa-Key": CLAVE_BYOK})  # sin X-Basa-Upstream

    assert respuesta.status_code == 503, respuesta.text
    assert AUDIT_POLICY_DETAIL in mensaje_de(respuesta)
    assert proveedor.llamadas == [], "cortado ANTES del proveedor (FR-005)"
