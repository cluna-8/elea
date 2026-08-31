"""Contract test del CRUD del perfil de gobernanza (spec 027, US2/T020).

Cubre las garantías de ``PUT``/``DELETE /profile`` de contracts/api-gobernanza.md, que son
las que hacen falsificables dos criterios de éxito:

- **SC-004** — ningún camino de configuración deja el piso apagado: el 422 del piso se prueba
  junto con sus dos consecuencias, que son las que la garantía (a) exige y las que se olvidan
  primero: **no queda fila escrita** y **el intento queda registrado**. Un 422 que además
  escribiera la fila, o que rechazara en silencio, pasaría un test que solo mirara el código
  de estado.
- **SC-006** — el admin cambia la postura sin tocar archivos: el ``PUT`` responde la **verdad
  recalculada** (garantía (d)), no un eco del body. Encender una capa que el motor no tiene
  cargada NO devuelve 200-verde, y ese es el test que impide que la vista de configuración
  vuelva a mentir como mentía ``is_active``.

Más la garantía (b) de D5 refinada —la fila de superficie que RELAJA se acepta, con la
honestidad de alcance explícita en el ``motivo``— y el invariante #1 del contrato: la
protección real es el ``Depends(require_role("admin"))`` del router, no el nav de la UI.
"""
import sys
import uuid
from pathlib import Path

import pytest

# Mismo enganche de path que el contract test del status: los harness de DB viven en
# ``tests/`` y ``tests/integration/``, y desde ``tests/contract/`` no se ven solos.
_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "sentinel_test_governance_profile_contract"

CLAVES_DE_FILA = {"scope_type", "scope_value", "layer_key", "decision", "updated_by",
                  "updated_at"}
ESTADOS = {"aplicandose", "requiere_credencial", "delegada", "no_disponible", "degradada"}


class _Probe:
    """Doble de la sonda al motor, con sus tres estados reales (confirmada con nombres,
    confirmada vacía, y **no confirmada**, que no es lo mismo que vacía)."""

    def __init__(self, confirmed, names=()):
        self.confirmed = confirmed
        self.names = frozenset(names)

    def has(self, name):
        return bool(self.confirmed and name and name in self.names)


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


@pytest.fixture(autouse=True)
def _sonda_confirmada(harness, monkeypatch):
    """Sonda confirmada con NUESTRA pieza cargada, salvo que el test diga otra cosa.

    Sin este default, el estado recalculado de cada PUT dependería de si el motor está
    levantado en la máquina que corre la suite, y un contract test que cambia de resultado
    según el entorno no verifica ningún contrato.
    """
    from src.api import governance

    async def _fake(**_kwargs):
        return _Probe(True, {"sentinel-guardian"})

    monkeypatch.setattr(governance.ai_engine_client, "probe_loaded_guardrails", _fake)


@pytest.fixture(autouse=True)
def _limpiar(harness):
    """Cada test arranca sin filas de decisión ni instancias de guardián.

    Arrastrarlas entre tests haría que el resultado dependiera del orden de ejecución, y
    justo acá lo que se mide es una cascada de precedencia: una fila huérfana de otro test
    cambia la decisión resuelta sin que se note.
    """
    _, factory, _ = harness
    yield
    from src.models.governance import GovernanceProfile
    from src.models.guardian import Guardian
    db = factory()
    try:
        db.query(GovernanceProfile).delete()
        db.query(Guardian).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def eventos(monkeypatch):
    """Captura los eventos de registro sin depender del logger.

    Lo que el contrato exige no es "que tal canal reciba algo" sino que el intento **se
    registre con esos campos**; interceptar el registrador es lo que hace falsificable eso
    último sin atarse al formato de una línea de log.

    **Estos eventos NO van al feed del monitor** (hallazgo A1 de la verificación de US2): iban
    al ring compartido ``sentinel:gw:events``, que ``GET /gw/events`` servía **sin sesión** —o
    sea, el ``layer_key``, el alcance, el ``updated_by`` y el ``tenant`` de la configuración
    admin-only salían por un endpoint abierto—. Hoy el registro es el log estructurado (más la
    propia fila, para los cambios aceptados), así que este fixture ya no protege al feed de
    otros tests: protege la aserción.
    """
    from src.api import governance
    capturados = []
    real = governance._registrar_evento_de_gobernanza

    def _espia(evento, **kwargs):
        capturados.append({"event": evento, **kwargs})
        # Envuelve en vez de reemplazar: así el registrador REAL sigue corriendo y el test
        # que vigila que nadie vuelva a publicar en el feed del monitor cubre también su
        # cuerpo, no solo el del endpoint.
        return real(evento, **kwargs)

    monkeypatch.setattr(governance, "_registrar_evento_de_gobernanza", _espia)
    return capturados


# ── Helpers de request ────────────────────────────────────────────────────────────


def put_profile(client, headers, scope_type, scope_value, layer_key, decision):
    return client.put("/api/v1/governance/profile", headers=headers,
                      json={"scope_type": scope_type, "scope_value": scope_value,
                            "layer_key": layer_key, "decision": decision})


def delete_profile(client, headers, scope_type, scope_value, layer_key):
    return client.delete(f"/api/v1/governance/profile/{scope_type}/{scope_value}/{layer_key}",
                         headers=headers)


def get_profile(client, headers):
    return client.get("/api/v1/governance/profile", headers=headers)


def filas_en_db(factory):
    from src.models.governance import GovernanceProfile
    db = factory()
    try:
        return [(f.scope_type, f.scope_value, f.layer_key, f.decision, f.updated_by)
                for f in db.query(GovernanceProfile).all()]
    finally:
        db.close()


def seed_guardian(factory, guardian_type, *, engine_name=None, con_credencial=False):
    from src.models.guardian import Guardian
    db = factory()
    try:
        db.add(Guardian(name=f"instancia-{guardian_type}", guardian_type=guardian_type,
                        is_active=True, config={}, engine_guardrail_name=engine_name,
                        service_api_key_encrypted="cifrada" if con_credencial else None))
        db.commit()
    finally:
        db.close()


# ── GET: la ausencia de fila ES heredar ───────────────────────────────────────────


def test_get_no_fabrica_filas_implicitas(harness):
    """D2: lo no configurado simplemente no está.

    Si el endpoint "completara" el catálogo con los defaults de producto, el default dejaría
    de vivir en el registry en código y pasaría a parecer un dato editable —y borrable—, que
    es exactamente lo que la migración 012 evita al no sembrar nada.
    """
    client, _, headers = harness

    cuerpo = get_profile(client, headers).json()

    assert cuerpo["filas"] == []
    assert cuerpo["tenant_id"]


def test_get_lista_solo_lo_configurado_con_el_shape_del_contrato(harness):
    client, _, headers = harness
    put_profile(client, headers, "connection_mode", "gateway-models", "sensitive_routing", "on")

    cuerpo = get_profile(client, headers).json()

    assert len(cuerpo["filas"]) == 1
    fila = cuerpo["filas"][0]
    assert set(fila) == CLAVES_DE_FILA
    assert (fila["scope_type"], fila["scope_value"], fila["layer_key"], fila["decision"]) == \
        ("connection_mode", "gateway-models", "sensitive_routing", "on")


def test_updated_by_lleva_el_usuario_y_nunca_el_email(harness):
    """Contrato de la columna: username o id, **jamás el email** (C1).

    La tabla se exporta como evidencia de auditoría y no tiene purga por retención: un email
    acá queda en claro para siempre. El admin del bootstrap tiene email conocido, así que el
    test puede afirmar la ausencia y no solo la presencia.
    """
    client, _, headers = harness
    resp = put_profile(client, headers, "tenant_default", "*", "sensitive_routing", "on")

    updated_by = resp.json()["fila"]["updated_by"]
    assert updated_by == "admin"
    assert "@" not in updated_by


# ── PUT: la respuesta es la verdad recalculada, no un eco (garantía (d)) ──────────


def test_put_persiste_y_recalcula_estado(harness):
    client, factory, headers = harness

    resp = put_profile(client, headers, "connection_mode", "gateway-models",
                       "sensitive_routing", "on")

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert set(cuerpo["fila"]) == CLAVES_DE_FILA
    assert cuerpo["estado_efectivo"] in ESTADOS
    assert cuerpo["motivo"]
    assert [e["mode"] for e in cuerpo["por_modo"]] == ["gateway-models"]
    assert filas_en_db(factory) == [
        ("connection_mode", "gateway-models", "sensitive_routing", "on", "admin")]


def test_encender_una_capa_que_el_motor_no_tiene_cargada_no_devuelve_200_verde(harness):
    """Garantía (d), el corazón de la US2: el deseo no fabrica ejecución.

    ``content_moderation`` requiere credencial y no hay ninguna instancia cargada. La fila se
    persiste con ``decision='on'`` —el admin pidió eso— y aun así el estado recalculado NO es
    ``aplicandose``. Decisión y estado son ejes independientes también en la respuesta de la
    escritura, no solo en la vista de estado.
    """
    client, _, headers = harness

    cuerpo = put_profile(client, headers, "connection_mode", "gateway-models",
                         "content_moderation", "on").json()

    assert cuerpo["fila"]["decision"] == "on"
    assert cuerpo["estado_efectivo"] != "aplicandose"
    assert cuerpo["estado_efectivo"] == "requiere_credencial"
    assert cuerpo["motivo"]


def test_estado_recalculado_refleja_el_cableado_real(harness):
    """El recálculo usa el mismo servicio que el status: con credencial cargada pero con la
    pieza AUSENTE de la sonda, sigue sin poder afirmarse que se aplica."""
    client, factory, headers = harness
    seed_guardian(factory, "openai_moderation", engine_name="litellm_content_filter",
                  con_credencial=True)

    cuerpo = put_profile(client, headers, "connection_mode", "gateway-models",
                         "content_moderation", "on").json()

    assert cuerpo["estado_efectivo"] != "aplicandose"


def test_put_es_idempotente_sobre_la_clave_natural(harness):
    """Dos PUT del mismo alcance actualizan la MISMA fila: la clave natural es el UNIQUE
    ``(tenant, scope_type, scope_value, layer_key)``, no una fila nueva por click."""
    client, factory, headers = harness

    put_profile(client, headers, "connection_mode", "subscription", "sensitive_routing", "on")
    put_profile(client, headers, "connection_mode", "subscription", "sensitive_routing", "off")

    assert filas_en_db(factory) == [
        ("connection_mode", "subscription", "sensitive_routing", "off", "admin")]


def test_propagacion_al_motor_no_se_declara_confirmada(harness):
    """Honestidad de la garantía (e): la señal se emite, **nadie la confirma todavía**.

    El cache de identidad del motor (``custom_auth._cache``, TTL 60 s) vive en otro proceso y
    hoy no tiene lector de la señal. Declarar ``confirmada=True`` sería la misma clase de
    mentira que la feature borra, así que el contrato del campo es que sea ``False`` mientras
    falte el consumidor — y que el motivo diga el tamaño real de la ventana.
    """
    client, _, headers = harness

    propagacion = put_profile(client, headers, "tenant_default", "*",
                              "sensitive_routing", "on").json()["propagacion"]

    assert propagacion["confirmada"] is False
    assert "60" in propagacion["motivo"]


# ── PUT: el piso (FR-003 / SC-004) ────────────────────────────────────────────────


@pytest.mark.parametrize("layer_key", ["interception_audit", "pii_detection",
                                       "secret_detection", "ai_act_evaluation"])
@pytest.mark.parametrize("decision", ["off", "on"])
def test_piso_devuelve_422_sin_escribir_fila(harness, eventos, layer_key, decision):
    """Las 4 capas de piso, en los dos sentidos.

    También con ``decision='on'``: el piso no es "una capa que siempre está encendida por
    configuración", es una capa que **no se configura**. Aceptar el ``on`` crearía una fila
    borrable cuya ausencia parecería significar algo, y volvería representable un piso
    apagado por la vía de borrarla.
    """
    client, factory, headers = harness

    resp = put_profile(client, headers, "connection_mode", "gateway-models",
                       layer_key, decision)

    assert resp.status_code == 422, resp.text
    assert layer_key in resp.json()["detail"]
    assert filas_en_db(factory) == []


def test_el_intento_contra_el_piso_queda_registrado(harness, eventos):
    """Garantía (a): el rechazo **jamás es silencioso** — con los campos de data-model §1.4."""
    client, _, headers = harness

    put_profile(client, headers, "surface", "claude-code", "secret_detection", "off")

    piso = [e for e in eventos if e["event"] == "governance_floor_violation"]
    assert len(piso) == 1
    evento = piso[0]
    assert evento["layer_key"] == "secret_detection"
    assert evento["scope_type"] == "surface"
    assert evento["scope_value"] == "claude-code"
    assert evento["updated_by"] == "admin"
    assert evento["tenant"]


def test_el_registro_del_intento_no_lleva_payload(harness, eventos):
    """C1: el evento es **metadata-only**. Ni el body crudo, ni texto libre, ni nada que
    haya escrito un usuario final — este registro se exporta."""
    client, _, headers = harness

    put_profile(client, headers, "tenant_default", "*", "pii_detection", "off")

    evento = [e for e in eventos if e["event"] == "governance_floor_violation"][0]
    assert set(evento) == {"event", "tenant", "layer_key", "scope_type", "scope_value",
                           "updated_by"}


# ── PUT: 422 de enums (garantía (c)) ──────────────────────────────────────────────


@pytest.mark.parametrize("scope_type,scope_value,layer_key,decision,campo,eco", [
    ("produccion", "*", "sensitive_routing", "on", "scope_type", "produccion"),
    # El centinela '*' es del default de tenant y de NINGÚN otro eje, y viceversa: el
    # dominio de scope_value depende del eje, así que se valida el PAR.
    ("tenant_default", "subscription", "sensitive_routing", "on", "scope_value", "subscription"),
    ("connection_mode", "*", "sensitive_routing", "on", "scope_value", "*"),
    ("connection_mode", "claude-code", "sensitive_routing", "on", "scope_value", "claude-code"),
    ("surface", "telepatia", "sensitive_routing", "on", "scope_value", "telepatia"),
    ("connection_mode", "subscription", "capa_inventada", "on", "layer_key", "capa_inventada"),
    ("connection_mode", "subscription", "sensitive_routing", "quizas", "decision", "quizas"),
])
def test_422_nombrando_el_campo_invalido(harness, scope_type, scope_value, layer_key,
                                         decision, campo, eco):
    client, factory, headers = harness

    resp = put_profile(client, headers, scope_type, scope_value, layer_key, decision)

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert campo in detail, detail
    assert eco in detail, detail
    assert filas_en_db(factory) == []


def test_el_centinela_del_default_de_tenant_se_acepta(harness):
    """La contracara del test anterior: ``('tenant_default', '*')`` es el par legal.

    El centinela existe porque el UNIQUE de Postgres no deduplica NULLs, así que el default
    de tenant necesita un valor concreto — y por eso tiene que pasar la validación.
    """
    client, factory, headers = harness

    resp = put_profile(client, headers, "tenant_default", "*", "sensitive_routing", "on")

    assert resp.status_code == 200, resp.text
    assert filas_en_db(factory) == [
        ("tenant_default", "*", "sensitive_routing", "on", "admin")]


# ── PUT: superficie que relaja (garantía (b), D5 refinada) ────────────────────────


def test_superficie_que_relaja_se_acepta_con_la_honestidad_de_alcance(harness):
    """El caso insignia de D8 —enmascarado off para coding tools— **no es un 422**.

    Pero la respuesta dice el alcance real: el resolutor solo aplica una fila que relaja
    cuando la superficie del pedido viene del ``tool_type`` provisionado en la Connection.
    Al tráfico cuya superficie se deriva del User-Agent (spoofeable) no se le relaja nada. Sin
    esta frase, la configuración prometería más alcance del que tiene.
    """
    client, factory, headers = harness

    resp = put_profile(client, headers, "surface", "claude-code", "pii_masking", "off")

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["fila"]["decision"] == "off"
    assert "aplica solo a Connections con esta herramienta declarada" in cuerpo["motivo"]
    assert filas_en_db(factory) == [
        ("surface", "claude-code", "pii_masking", "off", "admin")]


def test_la_superficie_que_agrega_no_lleva_la_advertencia_de_alcance(harness):
    """La advertencia es de las filas que RELAJAN. Una fila de superficie que AGREGA
    protección sí aplica también al tráfico con superficie derivada —el resolutor solo ignora
    las que relajan—, así que advertir ahí sería una advertencia falsa."""
    client, _, headers = harness

    cuerpo = put_profile(client, headers, "surface", "cursor", "sensitive_routing", "on").json()

    assert "aplica solo a Connections" not in cuerpo["motivo"]


# ── DELETE: volver a heredar ──────────────────────────────────────────────────────


def test_delete_es_idempotente_sobre_fila_inexistente(harness):
    """Garantía (a): "que este alcance herede" ya es el estado resultante, así que un 404
    describiría el mundo y no el pedido — y obligaría a la UI a tratar como error algo que no
    tiene nada que arreglar."""
    client, _, headers = harness

    resp = delete_profile(client, headers, "connection_mode", "subscription",
                          "sensitive_routing")

    assert resp.status_code == 204, resp.text


def test_delete_borra_la_decision_y_vuelve_a_heredar(harness):
    client, factory, headers = harness
    put_profile(client, headers, "surface", "copilot", "pii_masking", "off")

    resp = delete_profile(client, headers, "surface", "copilot", "pii_masking")

    assert resp.status_code == 204, resp.text
    assert filas_en_db(factory) == []
    assert get_profile(client, headers).json()["filas"] == []


def test_delete_del_centinela_por_path(harness):
    """El ``'*'`` del default de tenant viaja en la URL: si el ruteo lo comiera, "volver a
    heredar" sería imposible justo en el alcance más ancho."""
    client, factory, headers = harness
    put_profile(client, headers, "tenant_default", "*", "sensitive_routing", "on")

    resp = delete_profile(client, headers, "tenant_default", "*", "sensitive_routing")

    assert resp.status_code == 204, resp.text
    assert filas_en_db(factory) == []


def test_delete_con_enum_invalido_da_422(harness):
    """Un typo que devolviera 204 le diría al admin que reseteó un alcance que nunca tocó."""
    client, _, headers = harness

    resp = delete_profile(client, headers, "connection_mode", "subscription", "capa_inventada")

    assert resp.status_code == 422
    assert "layer_key" in resp.json()["detail"]


def test_delete_se_registra(harness, eventos):
    """Garantía (c) del DELETE: también se audita, con quién y qué alcance."""
    client, _, headers = harness
    put_profile(client, headers, "connection_mode", "subscription", "sensitive_routing", "on")

    delete_profile(client, headers, "connection_mode", "subscription", "sensitive_routing")

    reset = [e for e in eventos if e["event"] == "governance_profile_reset"]
    assert len(reset) == 1
    assert reset[0]["layer_key"] == "sensitive_routing"
    assert reset[0]["updated_by"] == "admin"


# ── Invariante #1: admin-only en el router, no en la UI ───────────────────────────


@pytest.fixture
def headers_no_admin(harness):
    """Sesión de un usuario NO admin, creada por DB directa.

    Por DB y no por la API de usuarios a propósito: el alta por API pasa por el gate de seats
    de la 021 y por el provisioning al motor, y ninguna de las dos cosas tiene que ver con lo
    que este test mide.
    """
    client, factory, _ = harness
    from src.api.users import hash_password
    from src.models.user import User

    username = f"cliente-{uuid.uuid4().hex[:8]}"
    db = factory()
    try:
        db.add(User(username=username, email=f"{username}@ejemplo.test",
                    password_hash=hash_password("clave-de-prueba"),
                    role="client", is_active=True))
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/v1/users/login",
                       json={"username": username, "password": "clave-de-prueba"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_la_configuracion_no_sale_por_el_feed_del_monitor(harness, eventos, monkeypatch):
    """Hallazgo A1: el invariante #1 no se sostiene si la misma información sale por otro lado.

    Los eventos de cambio de configuración se publicaban en ``sentinel:gw:events`` —el ring que
    sirve ``GET /gw/events``—, así que ``layer_key``, alcance, ``updated_by`` y ``tenant`` de
    un router admin-only viajaban a un feed que no pedía sesión. Este test vigila la mitad
    productora: **ninguna** operación del CRUD escribe en el ring. Lo único que este router
    puede tocar en Redis es el contador de invalidación de la garantía (e).
    """
    from src.api import governance
    llamadas = []

    class _RedisEspia:
        def __getattr__(self, nombre):
            def _registrar(*args, **kwargs):
                llamadas.append((nombre, args))
                return None
            return _registrar

    monkeypatch.setattr(governance, "get_redis", lambda: _RedisEspia())
    client, _, headers = harness

    put_profile(client, headers, "tenant_default", "*", "sensitive_routing", "on")
    put_profile(client, headers, "tenant_default", "*", "secret_detection", "off")  # piso
    delete_profile(client, headers, "tenant_default", "*", "sensitive_routing")

    escrituras = [n for n, _ in llamadas if n not in ("incr",)]
    assert escrituras == [], f"el CRUD tocó Redis fuera del contador de invalidación: {llamadas}"


def test_el_feed_del_monitor_exige_sesion(harness, headers_no_admin):
    """La otra mitad del hallazgo A1: la vitrina en vivo dejó de ser un endpoint abierto.

    Vive en este archivo y no en uno propio porque lo que defiende es el invariante #1 del
    contrato de gobernanza visto desde el otro lado: el feed muestra la atribución por capa de
    cada pedido —qué capa bloqueó, qué capas no corrieron—, que es postura de seguridad del
    tenant y no dato público.

    La **página** sigue abierta y eso es deliberado (ver el punto 0 del docstring de
    ``monitor.py``): un browser no puede mandar ``Authorization`` en una navegación, así que
    protegerla sería matarla. Lo que se afirma acá es lo que la vuelve inofensiva: el cascarón
    no trae ningún dato del tenant, los trae ``/events``, y ése sí exige sesión.
    """
    client, _, headers = harness

    assert client.get("/api/v1/gw/events").status_code == 401
    assert client.get("/api/v1/gw/events", headers=headers_no_admin).status_code == 403
    assert client.get("/api/v1/gw/events", headers=headers).status_code == 200

    pagina = client.get("/api/v1/gw/monitor")
    assert pagina.status_code == 200
    assert pagina.text.lower().startswith("<!doctype html>")
    # El cascarón se sirve sin sesión, así que no puede traer eventos horneados: los pide por
    # ``/events`` con el token. Si alguna vez alguien inyecta el feed en el HTML "para que
    # cargue más rápido", vuelve a haber fuga y este assert la caza.
    assert "sentinel:gw:events" not in pagina.text
    assert "Bearer" in pagina.text, "la página tiene que pedir el feed CON credencial"


def test_un_rol_no_admin_recibe_403_en_los_tres_verbos(harness, headers_no_admin):
    """El gating del nav del frontend es cosmético; la protección real es la dependencia del
    router. Se prueban los tres verbos porque proteger solo la lectura y dejar la escritura
    abierta es el olvido clásico."""
    client, factory, _ = harness

    assert get_profile(client, headers_no_admin).status_code == 403
    assert put_profile(client, headers_no_admin, "tenant_default", "*",
                       "sensitive_routing", "on").status_code == 403
    assert delete_profile(client, headers_no_admin, "tenant_default", "*",
                          "sensitive_routing").status_code == 403
    assert filas_en_db(factory) == []


def test_sin_sesion_da_401_en_los_tres_verbos(harness):
    client, _, _ = harness

    assert client.get("/api/v1/governance/profile").status_code == 401
    assert client.put("/api/v1/governance/profile",
                      json={"scope_type": "tenant_default", "scope_value": "*",
                            "layer_key": "sensitive_routing", "decision": "on"}).status_code == 401
    assert client.delete(
        "/api/v1/governance/profile/tenant_default/*/sensitive_routing").status_code == 401
